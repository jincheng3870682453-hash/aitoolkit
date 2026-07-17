#!/usr/bin/env python3
"""
Long Memory Manager V1.0
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
核心功能：长对话记忆与注意力优化（独立模块，不集成 word 体系）
对应文档：DeepSeek 长对话记忆与注意力优化方案 V1.7
作者：沈锃杰（金呈）
版本：V1.0（代码化落地）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
功能：
  - 回忆快照注入（裂缝一）
  - SimHash 主题检测 + 缓存 + 锁（裂缝二）
  - 主题切换判断（裂缝二）
  - 短输入保护（裂缝二）
  - 连续短输入计数器（漏洞5修复）
  - urgency 行为信号（漏洞4修复）
  - logit_bias 可插拔（漏洞1修复）
  - 并发锁（漏洞2修复）
  - RAG 置信度回调（漏洞6修复）
  - 压测分离（漏洞7修复）
状态：可独立运行 | 可压测 | 可插拔
"""

import os
import sys
import json
import time
import hashlib
import re
import logging
import tempfile
import sys
if sys.platform == "win32":
    import msvcrt
else:
    import fcntl
from typing import Dict, List, Optional, Any, Tuple, Callable
from dataclasses import dataclass, field
from collections import deque

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# ============================================================
# 1. 数据类型定义
# ============================================================

@dataclass
class Snapshot:
    """对话快照数据结构"""
    topic_id: str                          # 64位 SimHash 十六进制
    start_time: str                        # ISO 时间
    end_time: str
    anchor_sentence: str                  # 锚点句子（前100字符）
    pointer: Dict[str, Any]               # {type, conversation_id, message_offset}
    block_hashes: List[str]               # 分块 SimHash 数组
    urgency: int = 0                      # 紧急度信号（0-5）
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "topic_id": self.topic_id,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "anchor_sentence": self.anchor_sentence,
            "pointer": self.pointer,
            "block_hashes": self.block_hashes,
            "urgency": self.urgency,
            "metadata": self.metadata
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Snapshot":
        return cls(
            topic_id=data["topic_id"],
            start_time=data["start_time"],
            end_time=data["end_time"],
            anchor_sentence=data["anchor_sentence"],
            pointer=data["pointer"],
            block_hashes=data.get("block_hashes", []),
            urgency=data.get("urgency", 0),
            metadata=data.get("metadata", {})
        )


@dataclass
class RecallBlock:
    """生成的回忆块"""
    content: str                          # 回忆文本
    topic_id: str                         # 关联主题ID
    source_snapshot: Snapshot             # 来源快照
    repeat_count: int = 1                 # 重复次数


# ============================================================
# 2. 核心模块：SimHash 引擎（裂缝二）
# ============================================================

class SimHashEngine:
    """
    64位 SimHash 实现
    - 分词级粒度（支持 jieba，降级用字符级）
    - 词频权重
    - 分块策略（512 字符，最后一块不足一半则合并）
    - MD5 缓存 + 文件锁防并发脏写
    """

    def __init__(self, block_size: int = 512, use_jieba: bool = False):
        self.block_size = block_size
        self.use_jieba = use_jieba
        self._cache: Dict[str, Tuple[str, List[str]]] = {}  # md5 -> (topic_id, block_hashes)
        self._lock_dir = tempfile.gettempdir()

        if use_jieba:
            try:
                import jieba
                self._tokenizer = jieba
                logger.info("SimHash 使用 jieba 分词")
            except ImportError:
                logger.warning("jieba 未安装，使用字符级分词（效果较差）")
                self.use_jieba = False
                self._tokenizer = None
        else:
            self._tokenizer = None

    def _get_lock_path(self, md5: str) -> str:
        return os.path.join(self._lock_dir, f"simhash_lock_{md5[:8]}.lock")

    def _acquire_lock(self, md5: str):
        lock_path = self._get_lock_path(md5)
        os.makedirs(os.path.dirname(lock_path), exist_ok=True)
        lock_file = open(lock_path, 'w')
        if sys.platform == "win32":
            msvcrt.locking(lock_file.fileno(), msvcrt.LK_LOCK, 1)
        else:
            fcntl.flock(lock_file, fcntl.LOCK_EX)
        return lock_file

    def _release_lock(self, lock_file):
        if sys.platform == "win32":
            msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            fcntl.flock(lock_file, fcntl.LOCK_UN)
        lock_file.close()

    def _tokenize(self, text: str) -> List[str]:
        """分词"""
        if self.use_jieba and self._tokenizer:
            return list(self._tokenizer.cut(text))
        # 字符级降级（中文按字符，英文按空格）
        return list(text)

    def _compute_simhash_single(self, text: str) -> Tuple[str, List[str]]:
        """计算单个文本的 SimHash"""
        tokens = self._tokenize(text)
        # 词频统计
        freq = {}
        for t in tokens:
            freq[t] = freq.get(t, 0) + 1

        # 64位向量
        vector = [0] * 64
        for token, weight in freq.items():
            h = int(hashlib.md5(token.encode()).hexdigest(), 16)
            for i in range(64):
                bit = (h >> i) & 1
                if bit:
                    vector[i] += weight
                else:
                    vector[i] -= weight

        # 符号函数二值化
        simhash = 0
        for i, v in enumerate(vector):
            if v > 0:
                simhash |= (1 << i)

        return hex(simhash)[2:].zfill(16), []  # 64位hex

    def compute_simhash_full(self, text: str) -> Tuple[str, List[str]]:
        """
        全量计算：分块后逐块计算 SimHash
        返回: (topic_id, block_hashes)
        """
        md5 = hashlib.md5(text.encode()).hexdigest()

        # 检查缓存（需加锁）
        lock_file = self._acquire_lock(md5)
        try:
            if md5 in self._cache:
                logger.debug(f"SimHash 缓存命中: {md5[:8]}")
                return self._cache[md5]
            # 未命中，开始计算
            logger.debug(f"SimHash 缓存未命中，计算: {md5[:8]}")
        finally:
            self._release_lock(lock_file)

        # 分块
        blocks = []
        i = 0
        while i < len(text):
            block = text[i:i+self.block_size]
            if block:
                blocks.append(block)
            i += self.block_size

        # 最后一块不足一半则合并
        if len(blocks) > 1 and len(blocks[-1]) < self.block_size // 2:
            blocks[-2] += blocks[-1]
            blocks.pop()

        # 计算每块的 SimHash
        block_hashes = []
        for block in blocks:
            h, _ = self._compute_simhash_single(block)
            block_hashes.append(h)

        # 整体 SimHash（用第一块作为主题ID）
        topic_id = block_hashes[0] if block_hashes else "0"*16

        # 存入缓存（再次加锁，防并发写）
        lock_file = self._acquire_lock(md5)
        try:
            self._cache[md5] = (topic_id, block_hashes)
        finally:
            self._release_lock(lock_file)

        return topic_id, block_hashes

    def compute_simhash_lite(self, text: str) -> Tuple[str, List[str]]:
        """
        轻量降级计算（用于超长文本 >5000 字符）
        MD5 命中缓存时直接返回；否则调用全量计算
        """
        md5 = hashlib.md5(text.encode()).hexdigest()

        # 检查缓存
        lock_file = self._acquire_lock(md5)
        try:
            if md5 in self._cache:
                return self._cache[md5]
        finally:
            self._release_lock(lock_file)

        # 未命中，调用全量计算
        return self.compute_simhash_full(text)

    def compute_overlap(self, blocks1: List[str], blocks2: List[str]) -> float:
        """计算两组块哈希的重叠率"""
        if not blocks1 or not blocks2:
            return 0.0
        set1 = set(blocks1)
        set2 = set(blocks2)
        overlap = len(set1 & set2)
        return overlap / max(len(set1), len(set2))


# ============================================================
# 3. 核心模块：主题检测（裂缝二 + 漏洞5修复）
# ============================================================

class TopicDetector:
    """
    主题切换检测器
    - 基于 SimHash 重叠率判断
    - 短输入保护（<100 字符不切换）
    - 极短输入（<20 字符）完全跳过
    - 连续短输入计数器（漏洞5修复）
    """

    def __init__(self, simhash_engine: SimHashEngine, threshold: float = 0.3):
        self.engine = simhash_engine
        self.threshold = threshold
        self._short_input_counter = 0
        self._last_topic_id: Optional[str] = None
        self._last_blocks: List[str] = []

    def is_topic_switch(self, new_text: str) -> Tuple[bool, Optional[str], float]:
        """
        判断是否发生主题切换
        返回: (是否切换, 新主题ID, 重叠率)
        """
        # 极短输入保护（<20 字符）
        if len(new_text) < 20:
            self._short_input_counter += 1
            logger.debug(f"极短输入，计数器: {self._short_input_counter}")
            return False, self._last_topic_id, 1.0

        # 短输入保护（<100 字符）
        if len(new_text) < 100:
            # 如果连续短输入 >= 3 轮，触发确认机制
            if self._short_input_counter >= 3 and self._last_topic_id:
                logger.warning("[TOPIC_CONFIRM] 连续短输入超过3轮，建议确认主题")
                # 不切换，但返回警告标记
                return False, self._last_topic_id, 1.0
            self._short_input_counter = 0
            return False, self._last_topic_id, 1.0

        # 正常文本：计算 SimHash
        self._short_input_counter = 0
        topic_id, block_hashes = self.engine.compute_simhash_full(new_text)

        if not self._last_topic_id:
            self._last_topic_id = topic_id
            self._last_blocks = block_hashes
            return False, topic_id, 1.0

        # 计算重叠率
        overlap = self.engine.compute_overlap(block_hashes, self._last_blocks)
        is_switch = overlap < self.threshold

        if is_switch:
            logger.info(f"[TOPIC_SWITCH] 检测到主题切换: {self._last_topic_id[:8]} -> {topic_id[:8]}")
            self._last_topic_id = topic_id
            self._last_blocks = block_hashes
            return True, topic_id, overlap
        else:
            logger.debug(f"主题保持: {topic_id[:8]}, overlap: {overlap:.3f}")
            self._last_topic_id = topic_id
            self._last_blocks = block_hashes
            return False, topic_id, overlap


# ============================================================
# 4. 核心模块：回忆注入器（裂缝一 + 漏洞1修复）
# ============================================================

class RecallInjector:
    """
    回忆块注入器
    - 将快照拼接到用户输入之前
    - 支持重复注入（可配置次数）
    - logit_bias 可插拔（漏洞1修复）
    - urgency 信号影响注入位置（漏洞4修复）
    """

    def __init__(self, max_repeat: int = 2, logit_bias_enabled: bool = True):
        self.max_repeat = max_repeat
        self.logit_bias_enabled = logit_bias_enabled

    def inject_recall(self, user_input: str, snapshot: Snapshot,
                      repeat_count: int = 1) -> Tuple[str, Dict[str, float]]:
        """
        注入回忆块到用户输入前
        返回: (新输入, logit_bias 字典)
        """
        repeat = min(repeat_count, self.max_repeat)
        recall_text = f"[RECALL: {snapshot.anchor_sentence}]"

        # 如果 urgency 高，增加重复次数
        if snapshot.urgency >= 4:
            repeat = min(repeat + 1, self.max_repeat)
            logger.debug(f"高紧急度快照，重复次数提升至 {repeat}")

        # 构建新输入
        recall_blocks = [recall_text] * repeat
        new_input = " ".join(recall_blocks) + " " + user_input

        logit_bias = {}
        if self.logit_bias_enabled:
            # 提取关键词（锚点句子中的名词/动词）
            keywords = self._extract_keywords(snapshot.anchor_sentence)
            for kw in keywords:
                logit_bias[kw] = 0.5

        return new_input, logit_bias

    def _extract_keywords(self, text: str) -> List[str]:
        """提取关键词（简单实现，可替换为NLP）"""
        # 去掉标点，按空格拆分，取长度>2的词
        cleaned = re.sub(r'[^\w\s]', '', text)
        words = cleaned.split()
        return [w for w in words if len(w) > 2][:5]


# ============================================================
# 5. 核心模块：快照存储（裂缝二数据结构）
# ============================================================

class SnapshotStore:
    """
    快照存储
    - 保存快照到本地文件
    - 支持按 topic_id 检索
    - 支持最近的 N 个快照回溯
    """

    def __init__(self, storage_dir: str = "./snapshots"):
        self.storage_dir = storage_dir
        os.makedirs(storage_dir, exist_ok=True)

    def save(self, snapshot: Snapshot) -> str:
        """保存快照，返回文件路径"""
        filename = f"{snapshot.topic_id[:8]}_{int(time.time())}.json"
        filepath = os.path.join(self.storage_dir, filename)
        with open(filepath, 'w') as f:
            json.dump(snapshot.to_dict(), f, indent=2)
        logger.debug(f"快照已保存: {filename}")
        return filepath

    def load(self, topic_id: str) -> Optional[Snapshot]:
        """根据 topic_id 前缀加载最近的一个快照"""
        matched = []
        for fname in os.listdir(self.storage_dir):
            if fname.startswith(topic_id[:8]) and fname.endswith('.json'):
                matched.append(fname)
        if not matched:
            return None
        matched.sort(reverse=True)  # 最新的在前面
        with open(os.path.join(self.storage_dir, matched[0]), 'r') as f:
            data = json.load(f)
        return Snapshot.from_dict(data)

    def list_recent(self, n: int = 3) -> List[Snapshot]:
        """获取最近的 N 个快照"""
        files = sorted(
            [f for f in os.listdir(self.storage_dir) if f.endswith('.json')],
            reverse=True
        )[:n]
        result = []
        for fname in files:
            with open(os.path.join(self.storage_dir, fname), 'r') as f:
                data = json.load(f)
                result.append(Snapshot.from_dict(data))
        return result


# ============================================================
# 6. 核心模块：总控 MemoryManager
# ============================================================

class MemoryManager:
    """
    长对话记忆与注意力优化总控
    串联所有模块，提供对外统一接口
    """

    def __init__(
        self,
        block_size: int = 512,
        topic_threshold: float = 0.3,
        max_recall_repeat: int = 2,
        use_jieba: bool = False,
        logit_bias_enabled: bool = True,
        storage_dir: str = "./snapshots",
        rag_callback: Optional[Callable[[Any], bool]] = None
    ):
        self.simhash_engine = SimHashEngine(block_size, use_jieba)
        self.topic_detector = TopicDetector(self.simhash_engine, topic_threshold)
        self.recall_injector = RecallInjector(max_recall_repeat, logit_bias_enabled)
        self.snapshot_store = SnapshotStore(storage_dir)
        self.rag_callback = rag_callback

        # 状态
        self._current_snapshot: Optional[Snapshot] = None
        self._history: deque = deque(maxlen=100)

    def process_user_input(
        self,
        user_input: str,
        conversation_id: str,
        rag_result: Optional[Any] = None
    ) -> Tuple[str, Dict[str, float]]:
        """
        处理用户输入，返回（处理后的输入, logit_bias）
        """
        # 0. 检查 RAG 是否启用
        if self.rag_callback is not None:
            if self.rag_callback(rag_result):
                logger.debug("RAG 结果置信度高，跳过记忆召回")
                return user_input, {}

        # 1. 判断主题是否切换
        is_switch, topic_id, overlap = self.topic_detector.is_topic_switch(user_input)

        # 2. 如果是新主题，创建新快照
        if is_switch or self._current_snapshot is None:
            snapshot = self._create_snapshot(user_input, conversation_id)
            self._current_snapshot = snapshot
            self.snapshot_store.save(snapshot)
            logger.info(f"新快照创建: {snapshot.topic_id[:8]}")
            return user_input, {}  # 新主题不注入回忆

        # 3. 否则注入回忆
        if self._current_snapshot:
            # 检查是否需要注入（重叠率过低时跳过）
            if overlap < 0.2:
                logger.debug("重叠率过低，跳过注入")
                return user_input, {}

            new_input, logit_bias = self.recall_injector.inject_recall(
                user_input,
                self._current_snapshot,
                repeat_count=1
            )
            return new_input, logit_bias

        return user_input, {}

    def _create_snapshot(self, text: str, conversation_id: str) -> Snapshot:
        """创建快照"""
        topic_id, block_hashes = self.simhash_engine.compute_simhash_full(text)
        anchor = text[:100]
        # 提取 urgency 信号
        urgency = self._extract_urgency(text)

        return Snapshot(
            topic_id=topic_id,
            start_time=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            end_time=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            anchor_sentence=anchor,
            pointer={
                "type": "local",
                "conversation_id": conversation_id,
                "message_offset": 0
            },
            block_hashes=block_hashes,
            urgency=urgency
        )

    def _extract_urgency(self, text: str) -> int:
        """提取紧急度信号（漏洞4修复）"""
        urgency = 0
        # 标点信号
        if "!!" in text or "！！！" in text:
            urgency += 2
        if "?" * 3 in text:
            urgency += 1
        # 语气词信号
        urgent_words = ["急", "马上", "立刻", "尽快", "紧急"]
        for word in urgent_words:
            if word in text:
                urgency += 1
                break
        # 全大写（英文）
        if text.isupper() and len(text) > 5:
            urgency += 1
        return min(urgency, 5)

    def get_recent_snapshots(self, n: int = 3) -> List[Snapshot]:
        """获取最近的 N 个快照"""
        return self.snapshot_store.list_recent(n)

    def get_current_snapshot(self) -> Optional[Snapshot]:
        """获取当前快照"""
        return self._current_snapshot

    def clear_cache(self):
        """清空 SimHash 缓存"""
        self.simhash_engine._cache.clear()
        logger.info("SimHash 缓存已清空")


# ============================================================
# 7. 压测工具（单独运行用）
# ============================================================

def run_benchmark():
    """运行压测，输出性能数据"""
    import time

    print("=== Memory Manager Benchmark ===")
    mm = MemoryManager(block_size=256, use_jieba=False)

    # 测试数据
    long_text = "这是一个非常长的测试文本，用于验证 SimHash 的性能。" * 1000
    short_text = "短文本"

    # 1. SimHash 性能测试
    start = time.time()
    for _ in range(100):
        mm.simhash_engine.compute_simhash_full(long_text)
    simhash_time = time.time() - start
    print(f"SimHash 100次: {simhash_time:.3f}s")

    # 2. 缓存命中测试
    start = time.time()
    for _ in range(100):
        mm.simhash_engine.compute_simhash_full(long_text)
    cache_time = time.time() - start
    print(f"缓存命中 100次: {cache_time:.3f}s")

    # 3. 主题检测测试
    start = time.time()
    for i in range(100):
        mm.topic_detector.is_topic_switch(long_text[:200])
    topic_time = time.time() - start
    print(f"主题检测 100次: {topic_time:.3f}s")

    # 4. 注入测试
    start = time.time()
    snapshot = mm._create_snapshot(long_text, "test")
    for i in range(100):
        mm.recall_injector.inject_recall(short_text, snapshot)
    inject_time = time.time() - start
    print(f"注入 100次: {inject_time:.3f}s")

    print("=== 压测完成 ===")


# ============================================================
# 8. 命令行入口
# ============================================================

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Long Memory Manager")
    parser.add_argument("--benchmark", action="store_true", help="运行压测")
    parser.add_argument("--block-size", type=int, default=512, help="SimHash 分块大小")
    parser.add_argument("--threshold", type=float, default=0.3, help="主题切换阈值")
    parser.add_argument("--max-repeat", type=int, default=2, help="最大回忆重复次数")
    parser.add_argument("--use-jieba", action="store_true", help="使用 jieba 分词")
    parser.add_argument("--test-input", type=str, help="测试输入文本")
    parser.add_argument("--conversation-id", default="test", help="会话ID")

    args = parser.parse_args()

    if args.benchmark:
        run_benchmark()
        return

    mm = MemoryManager(
        block_size=args.block_size,
        topic_threshold=args.threshold,
        max_recall_repeat=args.max_repeat,
        use_jieba=args.use_jieba
    )

    if args.test_input:
        result, logit_bias = mm.process_user_input(
            args.test_input,
            args.conversation_id
        )
        print("\n=== 处理结果 ===")
        print(f"原始输入: {args.test_input}")
        print(f"处理后输入: {result}")
        print(f"logit_bias: {logit_bias}")
        current = mm.get_current_snapshot()
        if current:
            print(f"当前主题: {current.topic_id[:8]}")
            print(f"紧急度: {current.urgency}")
    else:
        # 交互模式
        print("Memory Manager 交互模式 (输入 'quit' 退出)")
        conversation_id = input("会话ID: ").strip() or "default"
        while True:
            user_input = input("\n>>> ")
            if user_input.lower() == "quit":
                break
            result, logit_bias = mm.process_user_input(user_input, conversation_id)
            print(f"处理: {result}")
            if logit_bias:
                print(f"logit_bias: {logit_bias}")
            current = mm.get_current_snapshot()
            if current:
                print(f"主题: {current.topic_id[:8]} | 紧急度: {current.urgency}")


if __name__ == "__main__":
    main()