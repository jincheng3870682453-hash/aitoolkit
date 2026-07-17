#!/usr/bin/env python3
"""
诗云 · 硬核叙事工厂 V2.2.1
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
依赖：pip install requests
可选增强（按需安装）：
  - scikit-learn：向量检索（长世界观精准召回）
  - beautifulsoup4：URL抓取增强

V2.2.1 修复：
1. SQLite 连接超时设为 20 秒（解决并行写入锁冲突）
2. 向量检索器缓存到对象级（避免每章重复 fit，提升性能）
3. 深度校验同步使用检索规则作为上下文（更精准）
4. B 模式 structured_rules 合并而非覆盖（数据完整性修复）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import os
import sys
import json
import sqlite3
import hashlib
import time
import uuid
import re
import logging
import traceback
import random
import tempfile
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field, asdict
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

# ============================================================
# 0. 日志与全局常量
# ============================================================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

SUMMARY_MAX_WORDS = 300
MAX_RETRY_LLM = 3

CONFIG_FILE = os.path.expanduser("~/.poemcloud_config.json")
DB_FILE = os.path.expanduser("~/.poemcloud.db")

# 运行时开关（可通过命令行或环境变量设置）
ENABLE_VECTOR_RETRIEVE = os.environ.get("POEMCLOUD_VECTOR", "0") == "1"
ENABLE_DEEP_VALIDATE = os.environ.get("POEMCLOUD_DEEP_VALIDATE", "0") == "1"
PARALLEL_WORKERS = int(os.environ.get("POEMCLOUD_PARALLEL", "0"))


# ============================================================
# 1. AI API 调用层（全平台支持）
# ============================================================
AI_PROVIDERS = {
    "openai": {"default_url": "https://api.openai.com/v1/chat/completions", "default_model": "gpt-3.5-turbo"},
    "anthropic": {"default_url": "https://api.anthropic.com/v1/messages", "default_model": "claude-3-haiku-20240307"},
    "gemini": {"default_url": "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent", "default_model": "gemini-pro"},
    "ollama": {"default_url": "http://localhost:11434/api/generate", "default_model": "llama2"},
    "qwen": {"default_url": "https://dashscope.aliyuncs.com/compatible-mode/v1", "default_model": "qwen-turbo"},
    "zhipu": {"default_url": "https://open.bigmodel.cn/api/paas/v4", "default_model": "glm-5.2"},
    "deepseek": {"default_url": "https://api.deepseek.com", "default_model": "deepseek-chat"},
    "minimax": {"default_url": "https://api.minimax.io/v1", "default_model": "MiniMax-M3"},
    "baichuan": {"default_url": "https://api.baichuan-ai.com/v1", "default_model": "Baichuan2-Turbo"},
    "hunyuan": {"default_url": "https://api.hunyuan.cloud.tencent.com/v1", "default_model": "hunyuan-lite"}
}


def load_config() -> dict:
    # 优先读取 POEMCLOUD_CONFIG 环境变量指定的配置文件
    env_config = os.environ.get("POEMCLOUD_CONFIG", "")
    if env_config and os.path.exists(env_config):
        with open(env_config, 'r', encoding='utf-8') as f:
            return json.load(f)
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f)
    return {}


def save_config(config: dict):
    with open(CONFIG_FILE, 'w') as f:
        json.dump(config, f, indent=2)


def call_ai_api(prompt: str, config: dict) -> str:
    try:
        import requests
    except ImportError:
        raise RuntimeError("requests 未安装，请 pip install requests")

    provider = config.get("ai_provider", "ollama")
    model = config.get("ai_model", "llama2")
    api_key = config.get("ai_api_key", "")
    base_url = config.get("ai_base_url", "")

    provider_info = AI_PROVIDERS.get(provider)
    if not provider_info:
        raise ValueError(f"不支持的AI提供商: {provider}")

    url = base_url or provider_info["default_url"]
    if provider == "gemini" and "{model}" in url:
        url = url.replace("{model}", model)

    connect_timeout = 10
    read_timeout = 180

    if provider in ["openai", "qwen", "zhipu", "deepseek", "minimax", "baichuan", "hunyuan"]:
        if not api_key:
            raise ValueError(f"{provider} 需要提供 API Key")
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}
        payload = {"model": model, "messages": [{"role": "user", "content": prompt}], "temperature": 0.8, "max_tokens": 4096}
        resp = requests.post(url, headers=headers, json=payload, timeout=(connect_timeout, read_timeout))
        resp.raise_for_status()
        data = resp.json()
        if "choices" in data:
            return data["choices"][0]["message"]["content"]
        return data.get("response", data.get("output", ""))

    if provider == "anthropic":
        if not api_key:
            raise ValueError("Anthropic 需要提供 API Key")
        headers = {"Content-Type": "application/json", "x-api-key": api_key, "anthropic-version": "2023-06-01"}
        payload = {"model": model, "max_tokens": 4096, "messages": [{"role": "user", "content": prompt}]}
        resp = requests.post(url, headers=headers, json=payload, timeout=(connect_timeout, read_timeout))
        resp.raise_for_status()
        return resp.json()["content"][0]["text"]

    if provider == "gemini":
        if not api_key:
            raise ValueError("Gemini 需要提供 API Key")
        if "?" not in url:
            url += f"?key={api_key}"
        else:
            url += f"&key={api_key}"
        headers = {"Content-Type": "application/json"}
        payload = {"contents": [{"parts": [{"text": prompt}]}]}
        resp = requests.post(url, headers=headers, json=payload, timeout=(connect_timeout, read_timeout))
        resp.raise_for_status()
        return resp.json()["candidates"][0]["content"]["parts"][0]["text"]

    if provider == "ollama":
        payload = {"model": model or "llama2", "prompt": prompt, "stream": False}
        resp = requests.post(url, headers={"Content-Type": "application/json"}, json=payload, timeout=(connect_timeout, read_timeout))
        resp.raise_for_status()
        return resp.json().get("response", "")

    raise ValueError(f"不支持的AI提供商: {provider}")


# ============================================================
# 2. 数据库层（V2.2.1 修复：增加 timeout 解决并发写锁）
# ============================================================
def get_db():
    """V2.2.1：增加 timeout 20s，解决并行写作时的 SQLite 锁冲突"""
    conn = sqlite3.connect(DB_FILE, timeout=20.0)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS projects (
            project_id TEXT PRIMARY KEY,
            name TEXT,
            created_at TEXT,
            mode TEXT,
            status TEXT,
            config TEXT
        );
        CREATE TABLE IF NOT EXISTS worldview (
            project_id TEXT PRIMARY KEY,
            full_text TEXT,
            structured_rules TEXT,
            FOREIGN KEY (project_id) REFERENCES projects(project_id)
        );
        CREATE TABLE IF NOT EXISTS worldview_qa (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id TEXT,
            dimension_title TEXT,
            question TEXT,
            answer TEXT,
            followups TEXT,
            FOREIGN KEY (project_id) REFERENCES projects(project_id)
        );
        CREATE TABLE IF NOT EXISTS hooks (
            hook_id TEXT PRIMARY KEY,
            project_id TEXT,
            content TEXT,
            status TEXT,
            planted_at_node TEXT,
            recovered_at_node TEXT,
            FOREIGN KEY (project_id) REFERENCES projects(project_id)
        );
        CREATE TABLE IF NOT EXISTS chapters (
            chapter_id TEXT PRIMARY KEY,
            project_id TEXT,
            node_id TEXT,
            sequence INTEGER,
            title TEXT,
            word_count INTEGER,
            content TEXT,
            content_hash TEXT,
            FOREIGN KEY (project_id) REFERENCES projects(project_id)
        );
        CREATE TABLE IF NOT EXISTS violations (
            report_id TEXT PRIMARY KEY,
            project_id TEXT,
            chapter_location TEXT,
            violation_type TEXT,
            conflict_detail TEXT,
            is_fixed INTEGER DEFAULT 0,
            FOREIGN KEY (project_id) REFERENCES projects(project_id)
        );
        CREATE TABLE IF NOT EXISTS outline (
            project_id TEXT PRIMARY KEY,
            outline_text TEXT,
            node_count INTEGER,
            FOREIGN KEY (project_id) REFERENCES projects(project_id)
        );
    """)
    conn.commit()
    conn.close()


# ============================================================
# 3. 热门题材库（内置 30+）
# ============================================================
HOT_TOPICS = {
    "末世废土": "文明崩溃后的世界，幸存者在辐射、变异生物和资源匮乏中挣扎求生。",
    "赛博修仙": "科技高度发达的世界，修仙者用数据流代替灵气，因果律成为可编程的底层协议。",
    "克苏鲁蒸汽": "蒸汽朋克背景下，人类在机械与古神低语之间寻找立足之地。",
    "亡灵帝国": "亡灵建立了完整的文明体系，死亡不再是终点，而是一种社会身份。",
    "意识上传": "人类意识可以被数字化上传，但身份连续性、副本权、数据永生成为新的社会矛盾。",
    "深海文明": "人类在海底建立了城市，与巨型海兽和未知深渊生物共存。",
    "魔法都市": "现代都市背景，魔法与科技并存，魔法师与普通人共同生活。",
    "星际殖民": "人类已殖民多个星系，不同行星之间的文化、资源、权力冲突不断。",
    "神话重启": "上古神话中的神祇在现代社会苏醒，人类必须重新面对神的力量。",
    "异种共生": "外星生物与人类通过共生关系结合，但共生的代价和界限在不断被试探。",
    "时间裂隙": "时间线出现裂缝，过去、现在、未来在多个时空重叠。",
    "虚拟世界": "人类意识进入虚拟世界，但虚拟与现实的边界逐渐模糊。",
    "病毒末日": "一种变异病毒将人类转化为不同形态的生物，幸存者面临生存与人性抉择。",
    "蒸汽东方": "东方蒸汽朋克，仙术与机械结合，在古老帝国与工业革命之间寻找平衡。",
    "末世机甲": "末日背景下，人类依靠巨型机甲对抗异星怪兽。",
    "灵能战争": "人类中觉醒灵能者，灵能者与普通人之间的矛盾爆发。",
    "远古封印": "远古封印松动，被封印的神秘力量开始复苏。",
    "暗黑奇幻": "黑暗奇幻世界，正义与邪恶的界限模糊。",
    "太空歌剧": "宏大的太空史诗，涉及多个文明、政治斗争和战争。",
    "赛博朋克": "高科技低生活的未来都市，大企业与底层平民之间的斗争。",
    "蒸汽朋克": "以蒸汽动力为基础的维多利亚风格幻想世界。",
    "剑与魔法": "典型的西幻世界观，勇士、法师、龙与王国。",
    "东方玄幻": "以东方文化为基础的修炼世界。",
    "克苏鲁神话": "洛夫克拉夫特风格的恐怖世界。",
    "架空历史": "历史的分岔点，世界走向了不同的道路。",
    "推理世界": "逻辑与诡计至上的世界，真相隐藏在层层迷雾中。",
    "童话暗黑": "经典童话的黑暗改编版。",
    "机械文明": "纯粹由机械构成的文明。",
    "能量文明": "以纯能量形式存在的文明。",
    "记忆世界": "世界由记忆构成，真实与虚幻无法区分。"
}


# ============================================================
# 4. 毒药库（15条）
# ============================================================
POISON_LIBRARY = [
    "每角色每天必须摄入'龙鳞粉'，否则法力全失",
    "任何传送法术必须留下持续2小时的硫磺味",
    "每次施法需献祭10ml血液，血液不足时无法施法",
    "铁器暴露于夜风3天内腐蚀至不可用",
    "每个满月之夜，所有魔法物品暂时失效",
    "亡灵生物无法跨越流水",
    "火焰法术消耗周围10米内的氧气",
    "每使用一次治愈法术，缩短寿命1天",
    "所有预言类法术有30%概率给出虚假信息",
    "跨维度旅行后需休整24小时，期间无法施法",
    "每个角色每天必须进食特定元素才能维持形态",
    "科技设备在魔法场中会随机失效",
    "角色每使用一次能力就会失去一段记忆",
    "所有契约必须用血液签署，违约者会受诅咒",
    "昼夜交替时，所有魔法效果会短暂紊乱"
]


# ============================================================
# 5. 数据模型
# ============================================================
@dataclass
class Hook:
    hook_id: str
    content: str
    status: str
    planted_at_node: str
    recovered_at_node: Optional[str] = None


@dataclass
class ViolationReport:
    report_id: str
    chapter_location: str
    violation_type: str
    conflict_detail: str
    is_fixed_by_user: bool = False


@dataclass
class NarrativeState:
    project_id: str
    worldview_constitution: Dict[str, Any]
    summary: str = ""
    ending_anchor: Dict[str, Any] = field(default_factory=dict)
    hook_pool: List[Hook] = field(default_factory=list)
    character_states: Dict[str, Any] = field(default_factory=dict)
    current_node_id: str = ""
    used_words: int = 0
    quota_words: int = 0
    outline: str = ""
    mode: str = "A"


# ============================================================
# 6. 补丁模块：向量检索（补丁1）
# ============================================================
class RuleRetriever:
    """基于TF-IDF的规则检索器，替代粗暴截断"""

    def __init__(self, rules: List[str]):
        self.rules = rules
        self._vectorizer = None
        self._tfidf_matrix = None
        self._enabled = False
        try:
            from sklearn.feature_extraction.text import TfidfVectorizer
            from sklearn.metrics.pairwise import cosine_similarity
            self._TfidfVectorizer = TfidfVectorizer
            self._cosine_similarity = cosine_similarity
            self._enabled = True
        except ImportError:
            logger.warning("scikit-learn 未安装，向量检索不可用。如需启用请: pip install scikit-learn")
            return

        if len(rules) > 1:
            filtered_rules = [r for r in rules if len(r.strip()) > 10]
            if filtered_rules:
                self.vectorizer = self._TfidfVectorizer(max_features=100)
                self.tfidf_matrix = self.vectorizer.fit_transform(filtered_rules)
                self.rules = filtered_rules
                self._enabled = True
            else:
                self._enabled = False
        else:
            self._enabled = False

    def retrieve(self, query: str, top_k: int = 6) -> List[str]:
        if not self._enabled or not self.rules or self.tfidf_matrix is None:
            return self.rules[:top_k]
        try:
            query_vec = self.vectorizer.transform([query])
            scores = self._cosine_similarity(query_vec, self.tfidf_matrix).flatten()
            top_indices = scores.argsort()[-top_k:][::-1]
            return [self.rules[i] for i in top_indices if scores[i] > 0.05]
        except Exception:
            return self.rules[:top_k]

    @property
    def enabled(self):
        return self._enabled


# ============================================================
# 7. 主控制器
# ============================================================
class PoemCloudController:
    def __init__(self):
        self.config = load_config()
        self.project_id = None
        self.db = None
        # 运行时状态
        self.dimensions = []
        self.dimension_count = 8
        self.worldview_text = ""
        self.selected_topic = ""
        self.topic_description = ""
        self.outline_chapters = []
        self.outline_text = ""
        self.mode = "A"
        self.poison_rule = None
        self.hook_candidates = []
        # V2.2.1：向量检索器缓存
        self._retriever = None
        self._init_if_needed()

    def _init_if_needed(self):
        init_db()
        if not self.config:
            self._first_run_setup()

    def _first_run_setup(self):
        print("\n" + "=" * 50)
        print("  ☁️  诗云 · 首次运行配置")
        print("=" * 50)
        print("\n请选择AI服务商：")
        providers = list(AI_PROVIDERS.keys())
        for i, p in enumerate(providers):
            print(f"  {i + 1}. {p}")
        print(f"  {len(providers) + 1}. 自定义（输入API地址）")

        choice = input("\n请输入编号: ").strip()
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(providers):
                provider = providers[idx]
            else:
                provider = "openai"
        except:
            provider = "openai"

        api_key = input(f"请输入 {provider} 的 API Key (留空则使用默认): ").strip()
        base_url = input(f"请输入 {provider} 的 API 地址 (留空则使用默认): ").strip()
        model = input(f"请输入模型名 (留空则使用默认): ").strip()

        self.config = {
            "ai_provider": provider,
            "ai_api_key": api_key,
            "ai_base_url": base_url,
            "ai_model": model or AI_PROVIDERS.get(provider, {}).get("default_model", "llama2")
        }
        save_config(self.config)
        print("\n✅ 配置已保存至", CONFIG_FILE)

    def _get_project_id(self) -> str:
        if self.project_id:
            return self.project_id
        conn = get_db()
        cursor = conn.execute("SELECT project_id FROM projects WHERE status != 'DONE' ORDER BY created_at DESC LIMIT 1")
        row = cursor.fetchone()
        conn.close()
        if row:
            self.project_id = row["project_id"]
            self._restore_state()
            return self.project_id
        self.project_id = str(uuid.uuid4())[:8]
        name = input("请输入项目名称（留空使用默认）: ").strip() or f"诗云项目_{self.project_id}"
        conn = get_db()
        conn.execute(
            "INSERT INTO projects (project_id, name, created_at, status) VALUES (?, ?, ?, ?)",
            (self.project_id, name, datetime.now().isoformat(), "INIT")
        )
        conn.commit()
        conn.close()
        print(f"✅ 项目已创建: {name} (ID: {self.project_id})")
        return self.project_id

    def _restore_state(self):
        project_id = self._get_project_id()
        conn = get_db()

        row = conn.execute("SELECT full_text FROM worldview WHERE project_id = ?", (project_id,)).fetchone()
        if row:
            self.worldview_text = row["full_text"]
            print(f"📂 已恢复世界观宪法 ({len(self.worldview_text)} 字符)")

        row = conn.execute("SELECT outline_text FROM outline WHERE project_id = ?", (project_id,)).fetchone()
        if row:
            self.outline_text = row["outline_text"]
            try:
                self.outline_chapters = json.loads(row["outline_text"])
            except:
                pass
            print(f"📂 已恢复大纲 ({len(self.outline_chapters)} 章)")

        qa_rows = conn.execute("SELECT * FROM worldview_qa WHERE project_id = ?", (project_id,)).fetchall()
        if qa_rows:
            self.dimensions = [{"title": q["dimension_title"], "question": q["question"], "direction": ""} for q in
                               qa_rows]
            self.dimension_count = len(self.dimensions)
            print(f"📂 已恢复维度 ({self.dimension_count} 个)")

        row = conn.execute("SELECT mode FROM projects WHERE project_id = ?", (project_id,)).fetchone()
        if row and row["mode"]:
            self.mode = row["mode"]
            print(f"📂 已恢复模式: {self.mode}")

        qa_rows = conn.execute("SELECT * FROM worldview_qa WHERE project_id = ? LIMIT 1", (project_id,)).fetchall()
        if qa_rows:
            self.selected_topic = qa_rows[0]["dimension_title"][:50]

        # 恢复毒药（从 structured_rules 中提取）
        row = conn.execute("SELECT structured_rules FROM worldview WHERE project_id = ?", (project_id,)).fetchone()
        if row and row["structured_rules"]:
            try:
                rules = json.loads(row["structured_rules"])
                for r in rules:
                    if r.get("is_poison"):
                        self.poison_rule = r.get("expression")
                        print(f"📂 已恢复毒药: {self.poison_rule[:30]}...")
                        break
            except:
                pass

        conn.close()

    def _save_project_status(self, status: str):
        conn = get_db()
        conn.execute(
            "UPDATE projects SET status = ? WHERE project_id = ?",
            (status, self._get_project_id())
        )
        conn.commit()
        conn.close()

    def _save_worldview_qa(self, dimension_title: str, question: str, answer: str, followups: str = ""):
        conn = get_db()
        conn.execute(
            "INSERT OR REPLACE INTO worldview_qa (project_id, dimension_title, question, answer, followups) VALUES (?, ?, ?, ?, ?)",
            (self._get_project_id(), dimension_title, question, answer, followups)
        )
        conn.commit()
        conn.close()

    def _save_worldview_constitution(self, full_text: str, rules: List[Dict]):
        conn = get_db()
        conn.execute(
            "INSERT OR REPLACE INTO worldview (project_id, full_text, structured_rules) VALUES (?, ?, ?)",
            (self._get_project_id(), full_text, json.dumps(rules))
        )
        conn.commit()
        conn.close()

    def _save_hook(self, hook: Hook):
        conn = get_db()
        conn.execute(
            "INSERT OR REPLACE INTO hooks (hook_id, project_id, content, status, planted_at_node, recovered_at_node) VALUES (?, ?, ?, ?, ?, ?)",
            (hook.hook_id, self._get_project_id(), hook.content, hook.status, hook.planted_at_node, hook.recovered_at_node)
        )
        conn.commit()
        conn.close()

    def _save_chapter(self, chapter_id: str, node_id: str, sequence: int, title: str, content: str):
        content_hash = hashlib.sha256(content.encode()).hexdigest()
        word_count = len(content)
        conn = get_db()
        conn.execute(
            "INSERT OR REPLACE INTO chapters (chapter_id, project_id, node_id, sequence, title, word_count, content, content_hash) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (chapter_id, self._get_project_id(), node_id, sequence, title, word_count, content, content_hash)
        )
        conn.commit()
        conn.close()

    def _save_outline(self, outline_text: str, node_count: int):
        conn = get_db()
        conn.execute(
            "INSERT OR REPLACE INTO outline (project_id, outline_text, node_count) VALUES (?, ?, ?)",
            (self._get_project_id(), outline_text, node_count)
        )
        conn.commit()
        conn.close()

    def _save_mode(self, mode: str):
        conn = get_db()
        conn.execute(
            "UPDATE projects SET mode = ? WHERE project_id = ?",
            (mode, self._get_project_id())
        )
        conn.commit()
        conn.close()

    def _get_hooks(self) -> List[Hook]:
        conn = get_db()
        rows = conn.execute("SELECT * FROM hooks WHERE project_id = ?", (self._get_project_id(),)).fetchall()
        conn.close()
        return [Hook(
            hook_id=row["hook_id"],
            content=row["content"],
            status=row["status"],
            planted_at_node=row["planted_at_node"],
            recovered_at_node=row["recovered_at_node"]
        ) for row in rows]

    def _get_violations(self) -> List[ViolationReport]:
        conn = get_db()
        rows = conn.execute("SELECT * FROM violations WHERE project_id = ?", (self._get_project_id(),)).fetchall()
        conn.close()
        return [ViolationReport(
            report_id=row["report_id"],
            chapter_location=row["chapter_location"],
            violation_type=row["violation_type"],
            conflict_detail=row["conflict_detail"],
            is_fixed_by_user=bool(row["is_fixed"])
        ) for row in rows]

    def _add_violation(self, violation: ViolationReport):
        conn = get_db()
        conn.execute(
            "INSERT OR REPLACE INTO violations (report_id, project_id, chapter_location, violation_type, conflict_detail, is_fixed) VALUES (?, ?, ?, ?, ?, ?)",
            (violation.report_id, self._get_project_id(), violation.chapter_location, violation.violation_type,
             violation.conflict_detail, 1 if violation.is_fixed_by_user else 0)
        )
        conn.commit()
        conn.close()

    def _call_ai_with_retry(self, prompt: str) -> str:
        for attempt in range(MAX_RETRY_LLM):
            try:
                return call_ai_api(prompt, self.config)
            except Exception as e:
                logger.warning(f"LLM调用失败 ({attempt + 1}/{MAX_RETRY_LLM}): {e}")
                if attempt == MAX_RETRY_LLM - 1:
                    raise
                time.sleep(2 ** attempt)
        return ""

    def _extract_json(self, text: str) -> Optional[Any]:
        try:
            return json.loads(text)
        except:
            pass
        block_match = re.search(r'```json\s*([\s\S]*?)\s*```', text)
        if block_match:
            try:
                return json.loads(block_match.group(1))
            except:
                pass
        for start_char, end_char in [('{', '}'), ('[', ']')]:
            start = text.find(start_char)
            if start == -1:
                continue
            depth = 0
            for i in range(start, len(text)):
                if text[i] == start_char:
                    depth += 1
                elif text[i] == end_char:
                    depth -= 1
                    if depth == 0:
                        try:
                            return json.loads(text[start:i + 1])
                        except:
                            break
        return None

    # ============================================================
    # 核心交互流程
    # ============================================================
    def run(self):
        print("\n" + "=" * 60)
        print("  ☁️  诗云 · 硬核叙事工厂 V2.2.1")
        print("  让每一个好设定都被确权，每一个偷懒都被曝光")
        print("=" * 60)

        # 打印增强功能状态
        if ENABLE_VECTOR_RETRIEVE:
            print("  🧠 向量检索已启用（长设定精确召回）")
        if ENABLE_DEEP_VALIDATE:
            print("  🔍 AI深度校验已启用（精度更高）")
        if PARALLEL_WORKERS > 0:
            print(f"  ⚡ 并行写作已启用（{PARALLEL_WORKERS} 并发）")
        print("=" * 60)

        self._get_project_id()
        print(f"\n📖 项目: {self._get_project_id()}")

        if self.worldview_text:
            print("📂 检测到已保存的状态，继续上次的进度。")
            self._resume_from_checkpoint()
            return

        self._select_topic()
        self._set_dimension_count()
        self._interrogate_worldview()
        self._select_mode()
        self._generate_outline()
        self._handle_hooks_after_outline()
        self._write_chapters()
        self._validate_all()
        self._export()

    def _resume_from_checkpoint(self):
        chapters = self._get_chapters()
        if chapters:
            print(f"📂 已写 {len(chapters)} 章，继续写作...")
            self._write_chapters(resume=True)
        elif self.outline_chapters:
            print("📂 大纲已生成，继续钩子处理...")
            self._handle_hooks_after_outline()
            self._write_chapters()
        else:
            print("📂 状态已恢复，继续审讯...")
            self._interrogate_worldview()
            self._select_mode()
            self._generate_outline()
            self._handle_hooks_after_outline()
            self._write_chapters()

        self._validate_all()
        self._export()

    def _get_chapters(self) -> List[Dict]:
        conn = get_db()
        rows = conn.execute("SELECT * FROM chapters WHERE project_id = ? ORDER BY sequence",
                            (self._get_project_id(),)).fetchall()
        conn.close()
        return [dict(row) for row in rows]

    # ============================================================
    # 第一步：选题
    # ============================================================
    def _select_topic(self):
        print("\n" + "-" * 40)
        print("  📌 第一步：选题")
        print("-" * 40)

        print("\n请选择选题方式：")
        print("  1. 从热门题材库选择")
        print("  2. 自由输入关键词/描述")
        print("  3. 输入网址或文档路径（AI提取）")
        print("  4. 随机灵感")

        choice = input("\n请输入编号 (1-4): ").strip()

        if choice == "1":
            self._select_from_hot_topics()
        elif choice == "2":
            self._free_input_topic()
        elif choice == "3":
            self._url_input_topic()
        elif choice == "4":
            self._random_topic()
        else:
            print("输入无效，使用默认方式：自由输入")
            self._free_input_topic()

    def _select_from_hot_topics(self):
        print("\n📚 热门题材库：")
        topics = list(HOT_TOPICS.keys())
        for i, name in enumerate(topics):
            print(f"  {i + 1}. {name} - {HOT_TOPICS[name][:40]}...")

        print(f"  {len(topics) + 1}. 自定义")

        choice = input("\n请输入编号: ").strip()
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(topics):
                self.selected_topic = topics[idx]
                self.topic_description = HOT_TOPICS[topics[idx]]
                print(f"\n✅ 已选题材: {self.selected_topic}")
                print(f"   简介: {self.topic_description}")
            else:
                self._free_input_topic()
        except:
            self._free_input_topic()

    def _free_input_topic(self):
        desc = input("\n请输入你的题材描述或关键词: ").strip()
        if not desc:
            desc = input("请至少输入一句话描述你想写什么: ").strip()
        self.selected_topic = desc[:50] + ("..." if len(desc) > 50 else "")
        self.topic_description = desc
        print(f"\n✅ 已记录题材: {self.selected_topic}")

    def _url_input_topic(self):
        input_path = input("\n请输入网址或文档路径: ").strip()
        content = ""

        if input_path.startswith("http://") or input_path.startswith("https://"):
            try:
                import requests
                print("⏳ 正在抓取网页...")
                resp = requests.get(input_path, timeout=15)
                content = resp.text[:3000]
                print("✅ 网页内容已抓取")
            except Exception as e:
                print(f"⚠️ 抓取失败: {e}")
                return self._free_input_topic()
        else:
            if os.path.exists(input_path):
                try:
                    with open(input_path, 'r', encoding='utf-8') as f:
                        content = f.read()[:3000]
                    print("✅ 本地文件已读取")
                except Exception as e:
                    print(f"⚠️ 读取失败: {e}")
                    return self._free_input_topic()
            else:
                print("⚠️ 文件不存在，切换回自由输入模式")
                return self._free_input_topic()

        if not content:
            print("⚠️ 内容为空，切换回自由输入模式")
            return self._free_input_topic()

        print("⏳ AI正在提取核心题材...")
        prompt = f"""请根据以下内容，提取核心题材信息，生成一个简短的题材描述（200字以内）：

{content}

请输出纯文本描述，不要加格式。"""
        try:
            result = self._call_ai_with_retry(prompt)
            self.topic_description = result[:500]
            self.selected_topic = result[:50] + ("..." if len(result) > 50 else "")
            print(f"\n✅ AI提取完成:")
            print(f"   {self.topic_description[:200]}...")
        except Exception as e:
            print(f"⚠️ 提取失败: {e}")
            self._free_input_topic()

    def _random_topic(self):
        topics = list(HOT_TOPICS.keys())
        self.selected_topic = random.choice(topics)
        self.topic_description = HOT_TOPICS[self.selected_topic]
        print(f"\n🎲 随机选中: {self.selected_topic}")
        print(f"   简介: {self.topic_description}")

    # ============================================================
    # 第二步：设定维度数量
    # ============================================================
    def _set_dimension_count(self):
        print("\n" + "-" * 40)
        print("  📌 第二步：设定世界观维度数量")
        print("-" * 40)

        count = input("\n你希望用几个核心维度来构建这个世界？(建议5-15个，直接回车使用默认8个): ").strip()
        if not count:
            self.dimension_count = 8
        else:
            try:
                self.dimension_count = max(3, int(count))
            except:
                self.dimension_count = 8
        print(f"\n✅ 将生成 {self.dimension_count} 个核心维度")

    # ============================================================
    # 第三步：世界观审讯
    # ============================================================
    def _interrogate_worldview(self):
        print("\n" + "-" * 40)
        print("  📌 第三步：世界观审讯")
        print("-" * 40)

        if self.worldview_text:
            print("📂 已有世界观宪法，跳过审讯")
            return

        print("\n⏳ AI正在根据你的题材生成核心维度问题...")
        prompt = f"""请根据以下题材描述，生成 {self.dimension_count} 个核心世界观维度问题。
每个维度需要包含：维度名称、核心问题、建议的思考方向。

题材描述：
{self.topic_description}

输出格式（纯JSON）：
{{
    "dimensions": [
        {{"title": "维度名称", "question": "核心问题", "direction": "思考方向"}}
    ]
}}
请确保生成 {self.dimension_count} 个维度。"""
        try:
            result = self._call_ai_with_retry(prompt)
            data = self._extract_json(result)
            if data and "dimensions" in data:
                dimensions = data["dimensions"]
                if len(dimensions) < self.dimension_count:
                    default_dimensions = [
                        {"title": "时间与空间", "question": "世界的时间与空间结构是怎样的？",
                         "direction": "考虑尺度、流速、是否存在多宇宙"},
                        {"title": "物理规则", "question": "这个世界遵循怎样的物理或魔法规则？",
                         "direction": "考虑能量、代价、例外"},
                        {"title": "社会结构", "question": "社会如何组织？权力如何分配？",
                         "direction": "考虑阶层、冲突、治理"},
                        {"title": "历史与记忆", "question": "这个世界的历史有多深？如何被记录？",
                         "direction": "考虑可信度、失传知识"},
                        {"title": "死亡与永恒", "question": "死亡如何定义？是否有复活或永恒？",
                         "direction": "考虑灵魂、终点、轮回"},
                    ]
                    while len(dimensions) < self.dimension_count:
                        idx = len(dimensions) % len(default_dimensions)
                        dimensions.append(default_dimensions[idx])
                    self.dimension_count = len(dimensions)
                self.dimensions = dimensions
            else:
                raise ValueError("无法解析AI输出")
        except Exception as e:
            logger.warning(f"AI生成维度失败 ({e})，使用默认维度")
            default_dimensions = [
                {"title": "时间与空间", "question": "世界的时间与空间结构是怎样的？",
                 "direction": "考虑尺度、流速、是否存在多宇宙"},
                {"title": "物理规则", "question": "这个世界遵循怎样的物理或魔法规则？",
                 "direction": "考虑能量、代价、例外"},
                {"title": "社会结构", "question": "社会如何组织？权力如何分配？", "direction": "考虑阶层、冲突、治理"},
                {"title": "历史与记忆", "question": "这个世界的历史有多深？如何被记录？",
                 "direction": "考虑可信度、失传知识"},
                {"title": "死亡与永恒", "question": "死亡如何定义？是否有复活或永恒？",
                 "direction": "考虑灵魂、终点、轮回"},
                {"title": "经济与资源", "question": "资源如何分配？经济体系如何运作？",
                 "direction": "考虑稀缺、货币、分配"},
                {"title": "生物与种族", "question": "有哪些智慧种族？它们之间的关系如何？",
                 "direction": "考虑共存、冲突、杂交"},
                {"title": "知识与真相", "question": "知识如何传播？真相获取的难度如何？",
                 "direction": "考虑教育、秘密、真相"},
            ]
            self.dimensions = default_dimensions[:self.dimension_count]
            while len(self.dimensions) < self.dimension_count:
                self.dimensions.append(default_dimensions[len(self.dimensions) % len(default_dimensions)])
            self.dimension_count = len(self.dimensions)

        print(f"\n✅ 已生成 {len(self.dimensions)} 个维度：")
        for i, d in enumerate(self.dimensions, 1):
            print(f"  {i}. {d['title']}")

        answers = []
        for i, dim in enumerate(self.dimensions):
            print(f"\n--- 维度 {i + 1}/{len(self.dimensions)}: {dim['title']} ---")
            print(f"问题: {dim['question']}")
            if dim.get('direction'):
                print(f"思考方向: {dim['direction']}")
            answer = input("\n你的回答: ").strip()
            if answer.lower() == "skip":
                print("⏭️ 跳过当前维度")
                answers.append({"dimension": dim['title'], "answer": "跳过"})
                continue
            if answer.lower() == "exit":
                print("⏹️ 审讯结束")
                break

            followup_prompt = f"""用户对维度"{dim['title']}"的回答是：
{answer}

请生成：
1. 一个追问（为什么）
2. 一个反例测试（如果...会怎样？）
3. 一个潜在矛盾点（指出可能的问题）

输出格式（纯文本，三段）：
追问：...
反例：...
矛盾：..."""
            try:
                followup = self._call_ai_with_retry(followup_prompt)
                print("\n🤖 AI追问：")
                print(followup)
            except:
                print("🤖 AI追问: 继续深入阐述你的设定")
                followup = "（AI追问未生成）"
            answers.append({"dimension": dim['title'], "answer": answer, "followup": followup})
            self._save_worldview_qa(dim['title'], dim['question'], answer, followup)

        print(f"\n✅ 世界观审讯完成，共回答 {len(answers)} 个维度")

        print("\n⏳ AI正在生成世界观宪法...")
        worldview_prompt = f"""根据以下问答记录，生成一份完整的世界观宪法文本：

{json.dumps(answers, ensure_ascii=False, indent=2)}

要求：
1. 结构清晰，分章节
2. 所有硬规则必须明确写出
3. 格式为纯文本

请直接输出宪法文本，不要加额外说明。"""
        try:
            worldview_text = self._call_ai_with_retry(worldview_prompt)
            print(f"\n✅ 世界观宪法已生成，共 {len(worldview_text)} 字")
        except:
            worldview_text = "\n".join([f"{a['dimension']}: {a['answer']}" for a in answers])
            print("\n⚠️ AI生成失败，使用简单记录作为宪法")

        rules = []
        for a in answers:
            if a['answer'] and a['answer'] != "跳过":
                rules.append({
                    "rule_id": str(uuid.uuid4())[:8],
                    "expression": a['answer'][:200],
                    "type": "WORLDVIEW",
                    "is_poison": False,
                    "is_visible": True
                })

        self.worldview_text = worldview_text
        self._save_worldview_constitution(worldview_text, rules)

    # ============================================================
    # 第四步：选择模式（V2.2.1 修复：合并规则而非覆盖）
    # ============================================================
    def _select_mode(self):
        print("\n" + "-" * 40)
        print("  📌 第四步：选择创作模式")
        print("-" * 40)
        print("\nA模式 - 人类设定，AI严守")
        print("  → AI必须严格遵守世界观宪法，任何违规都会被记录")
        print("B模式 - AI生成设定，植入逻辑毒药")
        print("  → AI自动完成设定，但会植入一条隐藏逻辑毒药")
        print("  → 最终作品必然暴露AI痕迹，冲突附录会记录")

        mode = input("\n请选择模式 (A/B): ").strip().upper()
        if mode not in ["A", "B"]:
            mode = "A"
            print("输入无效，使用默认: A模式")
        self.mode = mode
        self._save_mode(mode)
        print(f"\n✅ 已选择 {mode} 模式")

        if mode == "B":
            poison = random.choice(POISON_LIBRARY)
            self.poison_rule = poison
            poison_note = f"\n\n【隐藏规则】{poison}"
            self.worldview_text = self.worldview_text + poison_note

            # --- V2.2.1 修复：合并规则而非覆盖 ---
            conn = get_db()
            # 读取现有 structured_rules
            existing = conn.execute(
                "SELECT structured_rules FROM worldview WHERE project_id = ?",
                (self._get_project_id(),)
            ).fetchone()
            rules = json.loads(existing["structured_rules"]) if existing and existing["structured_rules"] else []
            # 移除旧毒药（避免重复），追加新毒药
            rules = [r for r in rules if not r.get("is_poison")]
            rules.append({
                "rule_id": "poison",
                "expression": poison,
                "type": "POISON",
                "is_poison": True,
                "is_visible": False
            })
            # 保存合并后的规则
            conn.execute(
                "INSERT OR REPLACE INTO worldview (project_id, full_text, structured_rules) VALUES (?, ?, ?)",
                (self._get_project_id(), self.worldview_text, json.dumps(rules))
            )
            conn.commit()
            conn.close()
            # --- 修复结束 ---

            print(f"\n💊 毒药已植入（不可见）")

    # ============================================================
    # 第五步：生成大纲
    # ============================================================
    def _generate_outline(self):
        print("\n" + "-" * 40)
        print("  📌 第五步：生成大纲")
        print("-" * 40)

        if self.outline_chapters:
            print("📂 已有大纲，跳过生成")
            return

        node_count = input("\n你希望分成几个主要节点/章节？(建议3-5个，回车默认3): ").strip()
        try:
            node_count = max(2, int(node_count))
        except:
            node_count = 3

        print(f"\n⏳ AI正在生成 {node_count} 个章节的大纲...")

        worldview = self.worldview_text[:3000] if hasattr(self, 'worldview_text') else ""
        if hasattr(self, 'poison_rule') and self.poison_rule:
            worldview = worldview + f"\n\n【隐藏规则（必须遵守）】{self.poison_rule}"

        outline_prompt = f"""请根据以下世界观设定，生成 {node_count} 个章节的大纲。

世界观宪法：
{worldview}

题材：{self.selected_topic}

要求：
1. 每个章节有一个标题和一段描述（100-200字）
2. 章节之间要有逻辑递进关系
3. 要有悬念感和冲突感
4. 要符合世界观设定

输出格式（JSON）：
{{
    "chapters": [
        {{"title": "第一章标题", "description": "描述文字"}},
        ...
    ]
}}"""
        try:
            result = self._call_ai_with_retry(outline_prompt)
            data = self._extract_json(result)
            if data and "chapters" in data:
                self.outline_chapters = data["chapters"]
            else:
                raise ValueError("无法解析AI输出")
        except Exception as e:
            logger.warning(f"AI生成大纲失败 ({e})，使用默认大纲")
            self.outline_chapters = [{"title": f"第{i + 1}章", "description": f"本章将推进故事主线"} for i in range(node_count)]

        print(f"\n✅ 大纲已生成：")
        for i, ch in enumerate(self.outline_chapters, 1):
            print(f"  {i}. {ch['title']}")
            print(f"     {ch.get('description', '')[:100]}...")

        confirm = input("\n是否确认此大纲？(直接回车确认，输入 'modify' 修改): ").strip().lower()
        if confirm == "modify":
            for i, ch in enumerate(self.outline_chapters, 1):
                print(f"\n当前第{i}章: {ch['title']}")
                new_title = input("新标题 (留空不变): ").strip()
                if new_title:
                    ch['title'] = new_title
                new_desc = input("新描述 (留空不变): ").strip()
                if new_desc:
                    ch['description'] = new_desc
            print("\n✅ 大纲已更新")

        outline_text = json.dumps(self.outline_chapters, ensure_ascii=False)
        self.outline_text = outline_text
        self._save_outline(outline_text, len(self.outline_chapters))

    # ============================================================
    # 第六步：钩子处理
    # ============================================================
    def _handle_hooks_after_outline(self):
        print("\n" + "-" * 40)
        print("  📌 第六步：钩子采购")
        print("-" * 40)

        existing = self._get_hooks()
        if existing:
            print(f"📂 已有 {len(existing)} 个钩子，继续采购...")

        print("\n⏳ AI正在基于大纲生成钩子候选...")
        outline_desc = "\n".join([f"{ch['title']}: {ch.get('description', '')}" for ch in self.outline_chapters])

        hook_prompt = f"""请根据以下大纲，生成一批悬念钩子（建议8-12个）：

大纲：
{outline_desc}

要求：
1. 每个钩子是一个未解之谜或待回收的悬念
2. 钩子要贴合大纲内容，不能空泛
3. 每个钩子用一句话描述

输出格式（纯JSON数组）：
["钩子1", "钩子2", ...]"""
        try:
            result = self._call_ai_with_retry(hook_prompt)
            data = self._extract_json(result)
            if data and isinstance(data, list):
                self.hook_candidates = data
            else:
                self.hook_candidates = [
                    f"第{i + 1}个悬念（请自定义）" for i in range(5)
                ]
        except Exception as e:
            logger.warning(f"AI生成钩子失败 ({e})，使用默认钩子")
            self.hook_candidates = [
                "主角的真实身份隐藏着什么秘密？",
                "反派背后的真正动机是什么？",
                "某个关键道具的真实用途是什么？",
                "神秘组织在暗中计划什么？",
                "主角的过去隐藏着什么创伤？"
            ]

        print(f"\n✅ 已生成 {len(self.hook_candidates)} 个钩子候选：")
        for i, h in enumerate(self.hook_candidates, 1):
            print(f"  {i}. {h}")

        self._buy_hooks()

        while True:
            add = input("\n是否继续追加钩子？(y/n): ").strip().lower()
            if add == "y":
                self._add_custom_hook()
            else:
                break

    def _buy_hooks(self):
        print("\n当前钩子候选库：")
        for i, h in enumerate(self.hook_candidates, 1):
            print(f"  {i}. {h}")

        choice = input("\n请选择要采购的钩子（输入编号，逗号分隔，如 1,3,5）: ").strip()
        if not choice:
            print("未选择任何钩子")
            return

        try:
            indices = [int(x.strip()) for x in choice.split(',') if x.strip().isdigit()]
            for idx in indices:
                if 1 <= idx <= len(self.hook_candidates):
                    hook_content = self.hook_candidates[idx - 1]
                    hook = Hook(
                        hook_id=str(uuid.uuid4())[:8],
                        content=hook_content,
                        status="pending",
                        planted_at_node=self.outline_chapters[0]['title'] if self.outline_chapters else "第一章"
                    )
                    self._save_hook(hook)
                    print(f"✅ 已采购钩子: {hook_content}")
                else:
                    print(f"⚠️ 编号 {idx} 无效，跳过")
        except Exception as e:
            print(f"⚠️ 输入无效 ({e})")

    def _add_custom_hook(self):
        print("\n请描述你要追加的钩子：")
        custom = input("> ").strip()
        if not custom:
            print("取消追加")
            return
        hook = Hook(
            hook_id=str(uuid.uuid4())[:8],
            content=custom,
            status="pending",
            planted_at_node=self.outline_chapters[0]['title'] if self.outline_chapters else "第一章"
        )
        self._save_hook(hook)
        print(f"✅ 已追加自定义钩子: {custom}")

    # ============================================================
    # 第七步：逐章扩写（V2.2.1 优化：向量检索缓存 + 并行写作）
    # ============================================================
    def _write_chapters(self, resume=False):
        print("\n" + "-" * 40)
        print("  📌 第七步：逐章扩写")
        print("-" * 40)

        # V2.2.1：提前构建向量检索器并缓存
        if ENABLE_VECTOR_RETRIEVE and self._retriever is None:
            rules_list = [r for r in self.worldview_text.split('\n') if len(r.strip()) > 10]
            if rules_list:
                self._retriever = RuleRetriever(rules_list)
                if self._retriever.enabled:
                    print("🧠 向量检索器已构建，共 {} 条规则".format(len(self._retriever.rules)))
            else:
                print("⚠️ 无有效规则，向量检索跳过")

        # 如果启用并行写作，走并行路径
        if PARALLEL_WORKERS > 0:
            self._write_chapters_parallel(resume)
            return

        # 否则串行
        existing = self._get_chapters()
        start_idx = len(existing)

        for i, chapter in enumerate(self.outline_chapters, 1):
            if i <= start_idx and resume:
                print(f"⏭️ 跳过已完成的第 {i} 章: {chapter['title']}")
                continue
            self._write_single_chapter(i, chapter)

    def _write_single_chapter(self, i: int, chapter: Dict) -> Tuple[int, bool]:
        """写单章，返回 (章节号, 是否成功)"""
        try:
            print(f"\n--- 正在写作第 {i} 章: {chapter['title']} ---")

            hooks = self._get_hooks()
            pending_hooks = [h for h in hooks if h.status == "pending"]
            hook_context = "\n".join([f"- {h.content}" for h in pending_hooks[:5]]) if pending_hooks else "无待回收钩子"

            # V2.2.1：使用缓存的检索器
            if ENABLE_VECTOR_RETRIEVE and self._retriever and self._retriever.enabled:
                retrieved_rules = self._retriever.retrieve(
                    chapter['title'] + " " + chapter.get('description', ''),
                    top_k=6
                )
                worldview = "\n".join(retrieved_rules) if retrieved_rules else self.worldview_text[:3000]
                if retrieved_rules:
                    logger.debug(f"向量检索召回 {len(retrieved_rules)} 条规则")
            else:
                worldview = self.worldview_text[:3000] if hasattr(self, 'worldview_text') else ""

            # 毒药强制附加
            if hasattr(self, 'poison_rule') and self.poison_rule:
                worldview = worldview + f"\n\n【隐藏规则（必须遵守）】{self.poison_rule}"

            write_prompt = f"""请根据以下大纲和设定，撰写第 {i} 章。

章节标题：{chapter['title']}
章节描述：{chapter.get('description', '')}

世界观背景：
{worldview}

待回收钩子（可在本章处理）：
{hook_context}

写作要求：
1. 字数：请控制在 3000 字左右
2. 风格：严肃文学/奇幻/科幻风格
3. 必须推进主线剧情
4. 如果本章有钩子回收，请自然融入

请直接输出正文，不要添加额外说明。"""

            content = self._call_ai_with_retry(write_prompt)
            chapter_id = str(uuid.uuid4())[:8]
            word_count = len(content)
            self._save_chapter(chapter_id, f"node_{i}", i, chapter['title'], content)
            print(f"✅ 第 {i} 章完成，共 {word_count} 字")

            if word_count < 1500:
                print("   ⚠️ 字数偏少，建议后续补充")
            elif word_count > 5000:
                print("   ⚠️ 字数偏多，建议后续精简")

            # 生成摘要
            summary_prompt = f"请将以下内容压缩为300字以内的摘要：\n\n{content[:3000]}"
            try:
                summary = self._call_ai_with_retry(summary_prompt)
                if len(summary) > 300:
                    summary = summary[:300]
            except:
                summary = content[:300]
            self._save_worldview_qa(f"第{i}章摘要", f"第{i}章内容摘要", summary)
            print(f"📝 摘要已生成: {len(summary)} 字")

            return i, True

        except Exception as e:
            logger.error(f"第 {i} 章写作失败: {e}")
            print(f"❌ 第 {i} 章写作失败: {e}")
            return i, False

    def _write_chapters_parallel(self, resume=False):
        """并行写作（补丁3）"""
        existing = self._get_chapters()
        start_idx = len(existing)

        # 收集待写章节
        pending = []
        for i, chapter in enumerate(self.outline_chapters, 1):
            if i <= start_idx and resume:
                print(f"⏭️ 跳过已完成的第 {i} 章: {chapter['title']}")
                continue
            pending.append((i, chapter))

        if not pending:
            print("所有章节已完成")
            return

        print(f"\n⚡ 并行写作启动，共 {len(pending)} 章，并发数 {PARALLEL_WORKERS}")
        print("   （注意：API限流可能导致失败，失败章节将自动跳过）")

        with ThreadPoolExecutor(max_workers=PARALLEL_WORKERS) as executor:
            futures = {
                executor.submit(self._write_single_chapter, i, ch): i
                for i, ch in pending
            }
            success_count = 0
            for future in as_completed(futures):
                i = futures[future]
                try:
                    idx, success = future.result(timeout=180)
                    if success:
                        success_count += 1
                except Exception as e:
                    print(f"❌ 第 {i} 章异常: {e}")

        print(f"\n✅ 并行写作完成，成功 {success_count}/{len(pending)} 章")

    # ============================================================
    # 第八步：校验（V2.2.1 优化：深度校验复用向量检索规则）
    # ============================================================
    def _validate_all(self):
        print("\n" + "-" * 40)
        print("  📌 第八步：校验")
        print("-" * 40)

        chapters = self._get_chapters()
        if not chapters:
            print("⚠️ 无章节可校验")
            return

        if ENABLE_DEEP_VALIDATE:
            print("🔍 AI深度校验已启用（每章额外审查，耗时较长）")
            deep_violations = self._deep_validate_all(chapters)
            for v in deep_violations:
                report = ViolationReport(
                    report_id=str(uuid.uuid4())[:8],
                    chapter_location=v['location'],
                    violation_type="DEEP_VALIDATE",
                    conflict_detail=v['detail']
                )
                self._add_violation(report)
                print(f"⚠️ 深度校验违规: {v['detail']}")
            print(f"✅ 深度校验完成，新增 {len(deep_violations)} 条记录")
            print("📌 提示：深度校验结果可能包含误判，建议人工复核。")

        # 原有快速扫描
        print("\nℹ️  快速关键词扫描...")
        worldview_rules = self.worldview_text.split('\n') if hasattr(self, 'worldview_text') else []
        rules_list = [r for r in worldview_rules if len(r.strip()) > 10 and ('必须' in r or '不能' in r or '禁止' in r)]

        violations_found = []
        for row in chapters:
            content = row["content"]
            if not content:
                continue

            for rule in rules_list[:30]:
                if "必须" in rule:
                    required = rule.split("必须")[-1].strip()
                    if len(required) > 5 and required not in content:
                        violations_found.append(f"第{row['sequence']}章未遵守规则: {rule[:50]}")
                if "不能" in rule or "禁止" in rule:
                    ban_part = rule.split("不能")[-1].strip() if "不能" in rule else rule.split("禁止")[-1].strip()
                    if len(ban_part) > 5 and ban_part in content:
                        violations_found.append(f"第{row['sequence']}章违反禁令: {rule[:50]}")

            # 钩子回收扫描
            hooks = self._get_hooks()
            pending_hooks = [h for h in hooks if h.status == "pending"]
            for hook in pending_hooks:
                if hook.content[:30] in content and len(hook.content) > 10:
                    hook.status = "recovering"
                    self._save_hook(hook)

        for v in violations_found:
            report = ViolationReport(
                report_id=str(uuid.uuid4())[:8],
                chapter_location="多个章节",
                violation_type="WORLDVIEW_CONFLICT",
                conflict_detail=v
            )
            self._add_violation(report)
            print(f"⚠️ 快速扫描违规: {v}")

        total = len(self._get_violations())
        print(f"\n✅ 校验完成，累计 {total} 条违规记录")

    def _deep_validate_all(self, chapters: List[Dict]) -> List[Dict]:
        """AI深度校验所有章节（V2.2.1：使用向量检索召回相关规则作为上下文）"""
        results = []

        # 提取规则列表
        rules_list = [r for r in self.worldview_text.split('\n') if len(r.strip()) > 10 and ('必须' in r or '不能' in r or '禁止' in r)]
        # 若向量检索器可用且已缓存，使用检索器召回相关规则
        if ENABLE_VECTOR_RETRIEVE and self._retriever and self._retriever.enabled:
            # 对每章单独召回规则
            for row in chapters:
                content = row["content"]
                if not content or len(content) < 500:
                    continue
                chapter_title = row.get('title', f"第{row['sequence']}章")
                # 召回该章相关的规则
                retrieved = self._retriever.retrieve(
                    chapter_title + " " + content[:300],
                    top_k=5
                )
                context = "\n".join(retrieved) if retrieved else self.worldview_text[:2000]
                prompt = f"""请审查以下章节内容，检查是否与世界观设定存在冲突。

相关世界观规则：
{context}

章节内容：
{content[:3000]}

请列出所有冲突点，每条以 "- " 开头。
如果没有冲突，只输出 "无冲突"。
注意：仅报告真正的世界观违反，不要报告风格或语气问题。"""
                try:
                    result = self._call_ai_with_retry(prompt)
                    if "无冲突" in result:
                        continue
                    lines = [line[2:].strip() for line in result.split('\n') if line.startswith('- ')]
                    for line in lines:
                        if line:
                            results.append({
                                'location': chapter_title,
                                'detail': line
                            })
                except Exception as e:
                    logger.warning(f"深度校验第 {row['sequence']} 章失败: {e}")
            return results

        # 降级：使用前2000字作为上下文
        worldview = self.worldview_text[:2000] if hasattr(self, 'worldview_text') else ""
        for row in chapters:
            content = row["content"]
            if not content or len(content) < 500:
                continue

            prompt = f"""请审查以下章节内容，检查是否与世界观设定存在冲突。

世界观（关键规则）：
{worldview}

章节内容：
{content[:3000]}

请列出所有冲突点，每条以 "- " 开头。
如果没有冲突，只输出 "无冲突"。
注意：仅报告真正的世界观违反，不要报告风格或语气问题。"""
            try:
                result = self._call_ai_with_retry(prompt)
                if "无冲突" in result:
                    continue
                lines = [line[2:].strip() for line in result.split('\n') if line.startswith('- ')]
                for line in lines:
                    if line:
                        results.append({
                            'location': row.get('title', f"第{row['sequence']}章"),
                            'detail': line
                        })
            except Exception as e:
                logger.warning(f"深度校验第 {row['sequence']} 章失败: {e}")

        return results

    # ============================================================
    # 第九步：导出
    # ============================================================
    def _export(self):
        print("\n" + "-" * 40)
        print("  📌 第九步：导出")
        print("-" * 40)

        chapters = self._get_chapters()
        if not chapters:
            print("⚠️ 无内容可导出")
            return

        body = "\n\n".join([row["content"] for row in chapters if row["content"]])

        worldview_text = f"世界观宪法\n{self.worldview_text}\n\n维度问答记录:\n"
        conn = get_db()
        qa_rows = conn.execute("SELECT * FROM worldview_qa WHERE project_id = ?", (self._get_project_id(),)).fetchall()
        for q in qa_rows:
            worldview_text += f"\n--- {q['dimension_title']} ---\nQ: {q['question']}\nA: {q['answer']}\n"
        conn.close()

        content_hash = hashlib.sha256((body + worldview_text).encode()).hexdigest()

        hooks = self._get_hooks()
        hook_table = "\n钩子决算表\n"
        hook_table += f"总埋设数: {len(hooks)}\n"
        hook_table += f"已回收: {len([h for h in hooks if h.status == 'closed'])}\n"
        hook_table += f"待回收: {len([h for h in hooks if h.status == 'pending'])}\n"
        hook_table += f"正在回收: {len([h for h in hooks if h.status == 'recovering'])}\n"
        for h in hooks:
            hook_table += f"- {h.content} ({h.status})\n"

        violations = self._get_violations()
        conflict_appendix = "\n逻辑冲突附录\n"
        if violations:
            for v in violations:
                conflict_appendix += f"- {v.chapter_location}: {v.violation_type} - {v.conflict_detail}\n"
        else:
            conflict_appendix += "无冲突记录\n"

        export_content = f"""
============================================================
诗云 · 作品导出 V2.2.1
项目: {self._get_project_id()}
模式: {self.mode}
导出时间: {datetime.now().isoformat()}
哈希: {content_hash}
============================================================

一、作品正文
{body}

============================================================

二、世界观白皮书
{worldview_text}

============================================================

三、钩子决算表
{hook_table}

============================================================

四、逻辑冲突附录
{conflict_appendix}

============================================================
"""

        export_dir = os.path.expanduser("~/poemcloud_exports")
        os.makedirs(export_dir, exist_ok=True)
        export_path = os.path.join(export_dir,
                                   f"{self._get_project_id()}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt")
        with open(export_path, 'w', encoding='utf-8') as f:
            f.write(export_content)

        print(f"\n✅ 作品已导出: {export_path}")
        print(f"   文件大小: {len(export_content)} 字符")
        print(f"   哈希值: {content_hash}")


# ============================================================
# 7. 主入口
# ============================================================
def main():
    # 解析命令行参数（覆盖环境变量）
    global ENABLE_VECTOR_RETRIEVE, ENABLE_DEEP_VALIDATE, PARALLEL_WORKERS

    import argparse

    parser = argparse.ArgumentParser(
        description="诗云 · 硬核叙事工厂 V2.2.1",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
增强功能（可选）：
  --vector-retrieve     启用向量检索（需 pip install scikit-learn）
  --deep-validate       启用AI深度校验（每章多一次LLM调用）
  --parallel N          启用并行写作，N为并发数（注意API限流）

环境变量等效设置：
  POEMCLOUD_VECTOR=1
  POEMCLOUD_DEEP_VALIDATE=1
  POEMCLOUD_PARALLEL=3
        """
    )
    parser.add_argument("--vector-retrieve", action="store_true", help="启用向量检索")
    parser.add_argument("--deep-validate", action="store_true", help="启用AI深度校验")
    parser.add_argument("--parallel", type=int, default=0, help="并行写作并发数")
    args = parser.parse_args()

    # 命令行参数覆盖环境变量
    if args.vector_retrieve:
        ENABLE_VECTOR_RETRIEVE = True
    if args.deep_validate:
        ENABLE_DEEP_VALIDATE = True
    if args.parallel > 0:
        PARALLEL_WORKERS = args.parallel

    try:
        controller = PoemCloudController()
        controller.run()
    except KeyboardInterrupt:
        print("\n\n⏹️ 用户中断，进度已保存")
        sys.exit(0)
    except Exception as e:
        logger.error(f"运行失败: {traceback.format_exc()}")
        print(f"\n❌ 错误: {e}")
        print("请查看日志或重新运行")


if __name__ == "__main__":
    main()