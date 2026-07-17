"""
Archive.py —— 长对话记忆（SimHash + 主题感知）

设计思路：
  - SimHash：把长对话压缩成 64 位指纹，省 token
  - 主题切换检测：话题变了 → 不硬塞旧上下文
  - 紧急度信号：用户催了 → 优先处理
  - 短输入保护：单字/表情 → 不刷新记忆

零依赖（纯标准库）。
"""

import re
import json
import time
import hashlib
import logging
from pathlib import Path
from collections import defaultdict
from typing import Optional

log = logging.getLogger("jinchen.archive")


# ════════════════════════════════════════════════════════
#  SimHash 实现（64 位）
# ════════════════════════════════════════════════════════
def simhash(text: str, bits: int = 64) -> int:
    """
    SimHash 计算（64 位指纹）

    借鉴 CodeGraph 的"把代码转成紧凑指纹"思路：
    - 分词 → 哈希 → 加权投票 → 64 位指纹
    - 相似文本的指纹汉明距离小
    - 用于判断"这段对话和之前是不是同一个话题"
    """
    if not text:
        return 0

    # 分词（中英文混合）
    tokens = re.findall(r'[\u4e00-\u9fff]|[a-zA-Z0-9_]+', text.lower())
    if not tokens:
        return 0

    # 加权：高频词降权（类似 TF-IDF 思路）
    from collections import Counter
    counts = Counter(tokens)
    max_count = max(counts.values())

    v = [0] * bits
    for token, count in counts.items():
        h = int(hashlib.md5(token.encode()).hexdigest(), 16)
        weight = count / max_count  # 0~1
        for i in range(bits):
            bit = (h >> i) & 1
            if bit:
                v[i] += weight
            else:
                v[i] -= weight

    fingerprint = 0
    for i in range(bits):
        if v[i] > 0:
            fingerprint |= (1 << i)
    return fingerprint


def hamming_distance(a: int, b: int) -> int:
    """汉明距离（位数不同的个数）"""
    x = a ^ b
    count = 0
    while x:
        count += 1
        x &= x - 1
    return count


def similarity(a: int, b: int) -> float:
    """SimHash 相似度（0~1）"""
    if a == b == 0:
        return 1.0
    max_dist = 64
    return 1.0 - hamming_distance(a, b) / max_dist


# ════════════════════════════════════════════════════════
#  主题切换检测
# ════════════════════════════════════════════════════════
TOPIC_KEYWORDS = {
    "python": ["python", "函数", "类", "def", "import", "pip", "flask", "django"],
    "java":   ["java", "spring", "maven", "接口", "抽象类"],
    "sql":    ["sql", "数据库", "查询", "建表", "索引", "mysql"],
    "frontend":["react", "vue", "组件", "css", "html", "前端"],
    "narrative":["小说", "故事", "角色", "世界观", "剧情", "钩子"],
    "refactor":["重构", "优化", "简化", "性能"],
    "test":   ["测试", "unittest", "pytest", "覆盖率"],
    "doc":    ["文档", "注释", "readme"],
}

URGENCY_SIGNALS = [
    "快", "急", "马上", "立刻", "赶紧", "赶紧",
    "urgent", "asap", "quickly", "now", "hurry",
    "！", "!", "???", "???",
]


def detect_topic(text: str) -> str:
    """检测文本主题"""
    text_lower = text.lower()
    scores = {}
    for topic, kws in TOPIC_KEYWORDS.items():
        score = sum(1 for kw in kws if kw.lower() in text_lower)
        if score > 0:
            scores[topic] = score
    if not scores:
        return "general"
    return max(scores, key=scores.get)


def detect_urgency(text: str) -> bool:
    """检测紧急信号"""
    return any(sig in text for sig in URGENCY_SIGNALS)


# ════════════════════════════════════════════════════════
#  Archive —— 长对话记忆管理
# ════════════════════════════════════════════════════════
class Archive:
    """
    长对话记忆系统

    核心机制：
    1. SimHash 压缩：每条消息 → 64 位指纹（省 token）
    2. 主题感知：话题切换 → 不硬塞旧上下文
    3. 紧急度：用户催了 → 优先处理
    4. 短输入保护：单字/表情 → 不刷新记忆

    借鉴 CodeGraph 的"预压缩"思路：
    - 不把完整历史塞给模型
    - 只给最近 N 条相关 + 主题摘要
    """

    MAX_HISTORY = 20        # 最多存 20 条
    CONTEXT_WINDOW = 3       # 只取最近 3 条注入 prompt
    SHORT_INPUT_THRESHOLD = 2  # 少于 2 个有效字符 → 短输入

    def __init__(self, store_path: str = "archive/memory.json"):
        self.store_path = Path(store_path)
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        self._data: dict = defaultdict(list)
        self._load()

    def _load(self):
        if self.store_path.exists():
            try:
                self._data = json.loads(self.store_path.read_text(encoding="utf-8"))
            except Exception:
                self._data = defaultdict(list)

    def _save(self):
        try:
            self.store_path.write_text(
                json.dumps(dict(self._data), ensure_ascii=False, indent=2),
                encoding="utf-8")
        except Exception as e:
            log.error(f"⚠️ 存档保存失败: {e}")

    def add(self, conversation_id: str, text: str):
        """
        添加一条消息到记忆

        短输入保护：太短的内容不刷新记忆
        """
        # 短输入保护
        clean = re.sub(r'[^\w]', '', text).strip()
        if len(clean) < self.SHORT_INPUT_THRESHOLD:
            log.debug(f"📌 短输入，不刷新记忆: {text[:20]}")
            return

        entry = {
            "text": text[:500],
            "hash": simhash(text),
            "topic": detect_topic(text),
            "urgent": detect_urgency(text),
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }

        self._data[conversation_id].append(entry)
        # 只保留最近 MAX_HISTORY 条
        if len(self._data[conversation_id]) > self.MAX_HISTORY:
            self._data[conversation_id] = \
                self._data[conversation_id][-self.MAX_HISTORY:]
        self._save()

    def get_context(self, conversation_id: str, text: str = "") -> list:
        """
        获取与当前输入相关的上下文

        借鉴 CodeGraph 的"按需检索"思路：
        - 不是把全部历史塞进去
        - 而是按 SimHash 相似度 + 主题匹配筛选
        """
        history = self._data.get(conversation_id, [])
        if not history:
            return []

        current_hash = simhash(text) if text else 0
        current_topic = detect_topic(text) if text else ""

        # 计算每条历史与当前的相似度
        scored = []
        for entry in history:
            sim = similarity(current_hash, entry.get("hash", 0))
            topic_match = 1.0 if entry.get("topic") == current_topic else 0.5
            score = sim * 0.6 + topic_match * 0.4
            scored.append((score, entry))

        # 按分数排序，取最相关的
        scored.sort(key=lambda x: -x[0])
        top = scored[:self.CONTEXT_WINDOW]

        return [e["text"] for _, e in top]

    def should_switch_topic(self, conversation_id: str, text: str) -> bool:
        """
        检测是否应该切换话题

        借鉴 Headroom 的"lost in the middle"解决方案：
        - 新话题和旧话题 SimHash 距离大 → 切换
        - 切换后只保留新话题的上下文
        """
        history = self._data.get(conversation_id, [])
        if len(history) < 2:
            return False

        current_hash = simhash(text)
        last_hash = history[-1].get("hash", 0)
        current_topic = detect_topic(text)
        last_topic = history[-1].get("topic", "")

        # 主题不同 → 切换
        if current_topic != last_topic and current_topic != "general":
            log.info(f"🔄 话题切换: {last_topic} → {current_topic}")
            return True

        # SimHash 距离大 → 切换
        dist = hamming_distance(current_hash, last_hash)
        if dist > 30:  # 阈值可调
            log.info(f"🔄 语义漂移: 汉明距离={dist}")
            return True

        return False

    def clear(self, conversation_id: str = ""):
        """清除记忆"""
        if conversation_id:
            self._data.pop(conversation_id, None)
        else:
            self._data.clear()
        self._save()
        log.info(f"🧹 记忆已清除: {conversation_id or '全部'}")

    def stats(self, conversation_id: str = "") -> dict:
        """统计信息"""
        if conversation_id:
            hist = self._data.get(conversation_id, [])
            return {
                "conversation": conversation_id,
                "messages": len(hist),
                "topics": list(set(e["topic"] for e in hist)),
                "urgent_count": sum(1 for e in hist if e.get("urgent")),
            }
        return {
            "conversations": len(self._data),
            "total_messages": sum(len(v) for v in self._data.values()),
        }


# ════════════════════════════════════════════════════════
#  便捷函数
# ════════════════════════════════════════════════════════
_default_archive = None

def get_default_archive() -> Archive:
    global _default_archive
    if _default_archive is None:
        _default_archive = Archive()
    return _default_archive


def should_switch_topic(conversation_id: str, text: str) -> bool:
    return get_default_archive().should_switch_topic(conversation_id, text)


# ════════════════════════════════════════════════════════
#  CLI 入口
# ════════════════════════════════════════════════════════
if __name__ == "__main__":
    import argparse
    import sys

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    parser = argparse.ArgumentParser(description="Archive —— 长对话记忆")
    parser.add_argument("action", choices=["add", "get", "switch", "clear", "stats"])
    parser.add_argument("--text", "-t", default="", help="输入文本")
    parser.add_argument("--conversation", "-c", default="default", help="对话 ID")
    args = parser.parse_args()

    arc = Archive()

    if args.action == "add":
        arc.add(args.conversation, args.text)
        print(f"✅ 已记录: {args.text[:50]}")
    elif args.action == "get":
        ctx = arc.get_context(args.conversation, args.text)
        for i, c in enumerate(ctx):
            print(f"  [{i+1}] {c[:80]}")
    elif args.action == "switch":
        switched = arc.should_switch_topic(args.conversation, args.text)
        print(f"🔄 话题切换: {'是' if switched else '否'}")
    elif args.action == "clear":
        arc.clear(args.conversation)
        print("🧹 已清除")
    elif args.action == "stats":
        print(json.dumps(arc.stats(args.conversation), ensure_ascii=False, indent=2))
