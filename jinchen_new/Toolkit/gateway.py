"""
gateway.py —— 统一网关（路由层）

职责：
  - 识别用户意图（关键词 / 语义双模式）
  - 按需加载 Skill（不把 7 个全塞进 prompt）
  - 调用 AI 模型（带熔断保护）
  - 把模型输出交给 work.py 检查
  - 违规时反馈原因让模型改（不是死循环重试）
  - 记录反馈飞轮数据

设计思路（借鉴 Skill Router 分层架构）：
  L1 流量过滤：清洗输入、拦截无效请求
  L2 规则匹配：关键词快速命中（零成本）
  L3 语义识别：sentence-transformers 升级（可选）
  L4 后置校验：模型输出过守门员
  L5 反馈闭环：违规原因注入下一轮 prompt

不关心规则细节，规则在 work.py 里。
"""

import os
import sys
import json
import time
import logging
from pathlib import Path
from typing import Optional, Callable

# ── 兄弟模块 ──────────────────────────────────────────────
from .work import check as guard_check, Report, Violation
from .Archive import Archive, should_switch_topic
from .guardian import Guardian, safe_call, ConservativePass

log = logging.getLogger("jinchen.gateway")


# ═════════════════════════════════════════════════════════
#  L1 · 流量过滤层
# ═════════════════════════════════════════════════════════
def _sanitize_input(text: str) -> str:
    """清洗用户输入：去空白、截超长、过滤纯表情/乱码"""
    if not text:
        return ""
    text = text.strip()
    # 超长截断（防止 token 爆炸）
    if len(text) > 8000:
        text = text[:7986] + "...[truncated]"
        log.warning("输入超长，已截断到 8000 字符")
    return text


def _is_valid_request(text: str) -> bool:
    """判断是不是有效请求"""
    if not text:
        return False
    # 纯表情/纯标点 → 无效
    import re
    meaningful = re.sub(r'[^\w\s]', '', text).strip()
    if len(meaningful) < 2:
        return False
    return True


# ═════════════════════════════════════════════════════════
#  L2 · 关键词意图识别（零成本，默认启用）
# ═════════════════════════════════════════════════════════
KEYWORD_CATEGORIES = {
    "code_python": [
        "python", "函数", "类", "def ", "import ", "pip",
        "爬虫", "scrap", "flask", "django", "fastapi",
        "类型注解", "装饰器", "生成器", "迭代器",
    ],
    "code_java": [
        "java", "spring", "maven", "gradle", "jvm",
        "接口", "抽象类", "重载",
    ],
    "code_sql": [
        "sql", "查询", "数据库", "mysql", "postgres",
        "建表", "索引", "迁移",
    ],
    "code_frontend": [
        "react", "vue", "组件", "jsx", "tsx",
        "样式", "css", "html", "前端",
    ],
    "narrative": [
        "小说", "故事", "角色", "世界观", "剧情",
        "冲突", "钩子", "章纲", "叙事", "剧本",
    ],
    "refactor": [
        "重构", "优化", "简化", "重命名", "拆分",
        "性能", "加速",
    ],
    "test": [
        "测试", "unittest", "pytest", "覆盖率",
        "mock", "断言",
    ],
    "doc": [
        "文档", "注释", "readme", "changelog",
        "说明", "接口文档",
    ],
}

# 关键词 → Skill 映射（按需加载，不全塞）
CATEGORY_TO_SKILLS = {
    "code_python":   ["python_api_design", "error_handling", "code_refactor"],
    "code_java":     ["error_handling", "code_refactor"],
    "code_sql":      ["sql_safety", "code_refactor"],
    "code_frontend": ["code_refactor", "interactive_ux"],
    "narrative":     ["fiction_writing"],
    "refactor":      ["code_refactor"],
    "test":          ["code_refactor", "error_handling"],
    "doc":           ["markdown_format"],
}


def detect_intent_keyword(text: str) -> str:
    """关键词快速分类（零成本，<1ms）"""
    text_lower = text.lower()
    scores = {}
    for cat, kws in KEYWORD_CATEGORIES.items():
        score = sum(1 for kw in kws if kw.lower() in text_lower)
        if score > 0:
            scores[cat] = score
    if not scores:
        return "general"
    return max(scores, key=scores.get)


# ═════════════════════════════════════════════════════════
#  L3 · 语义意图识别（可选升级，需安装依赖）
# ═════════════════════════════════════════════════════════
_semantic_model = None
_intent_labels = list(KEYWORD_CATEGORIES.keys())

def _load_semantic_model():
    """懒加载语义模型（首次调用时才装）"""
    global _semantic_model
    if _semantic_model is not None:
        return _semantic_model
    try:
        from sentence_transformers import SentenceTransformer
        model = SentenceTransformer("all-MiniLM-L6-v2")
        # 预编码所有意图标签
        label_texts = {
            "code_python":   "写 Python 代码、函数、类、爬虫、Flask/Django 接口",
            "code_java":     "写 Java 代码、Spring 接口、JVM 相关",
            "code_sql":      "数据库查询、建表、SQL 优化、迁移",
            "code_frontend": "前端组件、React/Vue、CSS 样式",
            "narrative":     "写小说、故事、角色设定、世界观、剧情",
            "refactor":      "重构代码、优化性能、简化逻辑",
            "test":          "写单元测试、提高覆盖率、mock 数据",
            "doc":           "写文档、注释、README、接口说明",
        }
        label_embs = model.encode(list(label_texts.values()))
        _semantic_model = {
            "model": model,
            "labels": list(label_texts.keys()),
            "embeddings": label_embs,
        }
        log.info("✅ 语义意图模型加载成功（all-MiniLM-L6-v2）")
        return _semantic_model
    except Exception as e:
        log.warning(f"⚠️ 语义模型加载失败，降级为关键词模式: {e}")
        return None


def detect_intent_semantic(text: str) -> str:
    """用语义相似度分类（比关键词准，但有依赖）"""
    sm = _load_semantic_model()
    if sm is None:
        return detect_intent_keyword(text)
    model = sm["model"]
    query_emb = model.encode([text])[0]
    # 余弦相似度
    import numpy as np
    sims = np.dot(sm["embeddings"], query_emb) / (
        np.linalg.norm(sm["embeddings"], axis=1) * np.linalg.norm(query_emb) + 1e-9
    )
    best_idx = int(np.argmax(sims))
    best_label = sm["labels"][best_idx]
    best_score = float(sims[best_idx])
    log.info(f"🎯 语义意图: {best_label} (置信度 {best_score:.2f})")
    return best_label


# ═════════════════════════════════════════════════════════
#  Skill 按需加载（借鉴 Skill Router 的注册表思路）
# ═════════════════════════════════════════════════════════
class SkillRegistry:
    """
    Skill 注册表 —— 只加载需要的，不全塞进 prompt

    借鉴 SkillTree / openclaw-intent-router 的思路：
    - 每个 Skill 有元数据（名称、描述、标签）
    - 按意图匹配，只注入相关 Skill 内容
    - 新增 Skill 不改主逻辑
    """

    def __init__(self, skills_dir: Optional[str] = None):
        if skills_dir is None:
            skills_dir = Path(__file__).parent / "skills"
        self.skills_dir = Path(skills_dir)
        self._cache: dict = {}
        self._load_all()

    def _load_all(self):
        """启动时扫描所有 .skill 文件"""
        if not self.skills_dir.exists():
            log.warning(f"Skills 目录不存在: {self.skills_dir}")
            return
        for f in sorted(self.skills_dir.glob("*.skill")):
            try:
                content = f.read_text(encoding="utf-8")
                # 解析 YAML front-matter
                meta = {}
                if content.startswith("---"):
                    parts = content.split("---", 2)
                    if len(parts) >= 3:
                        import yaml
                        meta = yaml.safe_load(parts[1]) or {}
                        body = parts[2].strip()
                    else:
                        body = content
                else:
                    body = content
                name = meta.get("name", f.stem)
                self._cache[name] = {
                    "name": name,
                    "description": meta.get("description", ""),
                    "tags": meta.get("tags", []),
                    "body": body,
                }
                log.debug(f"  加载 Skill: {name}")
            except Exception as e:
                log.error(f"  ⚠️ 加载 Skill 失败 {f.name}: {e}")

    def get(self, name: str) -> Optional[dict]:
        return self._cache.get(name)

    def list_all(self) -> list:
        return list(self._cache.values())

    def match_for_intent(self, intent: str) -> list:
        """
        按意图匹配 Skill（核心省 Token 逻辑）
        只返回相关 Skill，不全塞
        """
        skill_names = CATEGORY_TO_SKILLS.get(intent, [])
        matched = []
        for name in skill_names:
            s = self._cache.get(name)
            if s:
                matched.append(s)
        # 如果意图没匹配到，返回空列表（不降级全塞）
        return matched

    def render_for_prompt(self, intent: str) -> str:
        """把匹配到的 Skill 渲染成 prompt 片段"""
        skills = self.match_for_intent(intent)
        if not skills:
            return ""
        parts = ["# 相关规范（按需遵守）"]
        for s in skills:
            parts.append(f"\n## {s['name']}")
            if s.get("description"):
                parts.append(s["description"])
            if s.get("body"):
                # 只取前 500 字符，避免 Skill 太长烧 token
                body = s["body"][:500]
                parts.append(body)
        return "\n".join(parts)


# ═════════════════════════════════════════════════════════
#  AI 模型调用（带熔断保护）
# ═════════════════════════════════════════════════════════
class ModelCaller:
    """
    AI 模型调用封装 —— 带熔断、超时、降级

    支持 9 个平台，但只在真正调用时才 import requests，
    没装 requests 时优雅降级。
    """

    SUPPORTED = {
        "deepseek":  {"url": "https://api.deepseek.com/v1/chat/completions", "model_default": "deepseek-chat"},
        "openai":    {"url": "https://api.openai.com/v1/chat/completions",  "model_default": "gpt-4o-mini"},
        "anthropic": {"url": None, "model_default": "claude-sonnet-4-20250514"},  # 走 SDK
        "gemini":    {"url": None, "model_default": "gemini-2.0-flash"},
        "qwen":      {"url": "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions", "model_default": "qwen-plus"},
        "zhipu":     {"url": "https://open.bigmodel.cn/api/paas/v4/chat/completions", "model_default": "glm-4-plus"},
        "ollama":    {"url": "http://localhost:11434/api/chat", "model_default": "llama2"},
        "minimax":   {"url": "https://api.minimax.chat/v1/text/chatcompletion_v2", "model_default": "abab6.5s-chat"},
        "baichuan":  {"url": "https://api.baichuan-ai.com/v1/chat/completions", "model_default": "Baichuan4"},
    }

    def __init__(self, provider: str = "deepseek",
                 model: Optional[str] = None,
                 api_key: Optional[str] = None,
                 timeout: int = 30):
        self.provider = provider
        self.model = model or self.SUPPORTED.get(provider, {}).get("model_default", "deepseek-chat")
        self.api_key = api_key or os.getenv(f"NUWA_AI_API_KEY") or os.getenv(f"{provider.upper()}_API_KEY")
        self.timeout = timeout
        self._available = self._check_availability()

    def _check_availability(self) -> bool:
        try:
            import requests  # noqa
            return True
        except ImportError:
            log.warning("⚠️ requests 未安装，AI 模型调用不可用（规则引擎仍可独立运行）")
            return False

    @safe_call("AI模型调用", fallback="[模型不可用，返回保守通过]")
    def generate(self, prompt: str, system: str = "") -> str:
        """
        调用 AI 生成内容
        失败时不抛异常（被 safe_call 捕获），返回保守通过标记
        """
        if not self._available:
            return "[AI 模型不可用 - 请安装 requests 并配置 API Key]"

        import requests

        if self.provider == "anthropic":
            return self._call_anthropic(prompt, system)
        elif self.provider == "gemini":
            return self._call_gemini(prompt, system)
        else:
            return self._call_openai_compat(prompt, system)

    def _call_openai_compat(self, prompt: str, system: str) -> str:
        import requests
        url = self.SUPPORTED[self.provider]["url"]
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        data = {"model": self.model, "messages": messages, "temperature": 0.3}
        resp = requests.post(url, headers=headers, json=data, timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]

    def _call_anthropic(self, prompt: str, system: str) -> str:
        # 优先用 SDK，没有就走 HTTP
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=self.api_key)
            msg = client.messages.create(
                model=self.model,
                max_tokens=2048,
                system=system or "You are a helpful coding assistant.",
                messages=[{"role": "user", "content": prompt}],
            )
            return msg.content[0].text
        except ImportError:
            import requests
            headers = {
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            }
            data = {
                "model": self.model,
                "max_tokens": 2048,
                "system": system or "You are a helpful coding assistant.",
                "messages": [{"role": "user", "content": prompt}],
            }
            resp = requests.post(
                "https://api.anthropic.com/v1/messages",
                headers=headers, json=data, timeout=self.timeout)
            resp.raise_for_status()
            return resp.json()["content"][0]["text"]

    def _call_gemini(self, prompt: str, system: str) -> str:
        import requests
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent?key={self.api_key}"
        data = {
            "contents": [{
                "parts": [{"text": (system + "\n\n" + prompt) if system else prompt}]
            }]
        }
        resp = requests.post(url, json=data, timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()["candidates"][0]["content"]["parts"][0]["text"]


# ═════════════════════════════════════════════════════════
#  L4 · 后置校验 + L5 · 反馈式重试
# ═════════════════════════════════════════════════════════
class FeedbackFlywheel:
    """
    反馈飞轮 —— 记录每次违规，攒够了导出给模型微调

    借鉴 Microsoft CORE 的 Proposer-Ranker 思路：
    - Proposer（模型）生成代码
    - Ranker（守门员）打分
    - 不合格的打回去，把原因告诉 Proposer
    - 记录到训练集，未来微调用
    """

    def __init__(self, store_path: str = "feedback/records.jsonl"):
        self.store_path = Path(store_path)
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        self._buffer: list = []

    def record(self, *, prompt: str, output: str,
               violations: list, attempt: int, fixed: bool):
        """记录一次交互（无论成功失败）"""
        record = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "prompt_preview": prompt[:200],
            "output_preview": output[:500],
            "violations": [v if isinstance(v, str) else str(v) for v in violations],
            "attempt": attempt,
            "fixed": fixed,
        }
        self._buffer.append(record)
        # 实时追加写入（防止崩溃丢失）
        with open(self.store_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def export_sft(self, path: str = "feedback/sft_dataset.jsonl"):
        """导出 SFT 训练格式"""
        out = Path(path)
        out.parent.mkdir(parents=True, exist_ok=True)
        count = 0
        with open(self.store_path, "r", encoding="utf-8") as fin, \
             open(out, "w", encoding="utf-8") as fout:
            for line in fin:
                rec = json.loads(line)
                if rec.get("fixed") and rec.get("violations"):
                    # 只导出"违规后修复成功"的样本
                    fout.write(json.dumps({
                        "instruction": rec["prompt_preview"],
                        "input": "",
                        "output": rec["output_preview"],
                        "metadata": {"violations_fixed": rec["violations"]},
                    }, ensure_ascii=False) + "\n")
                    count += 1
        log.info(f"📦 导出 {count} 条 SFT 样本 → {out}")
        return count


# ═════════════════════════════════════════════════════════
#  主入口：WordGateway
# ═════════════════════════════════════════════════════════
class WordGateway:
    """
    统一网关 —— 对外只暴露一个 handle() 方法

    流程：
      用户输入 → L1 清洗 → L2/L3 意图识别 → Skill 匹配
      → 构建 prompt → 调模型 → L4 守门检查
      → 违规 → 反馈原因 → 重试（最多 2 次）
      → 通过 → 返回结果 + 记录飞轮
    """

    def __init__(self, config: Optional[dict] = None,
                 env: str = "dev",
                 skills_dir: Optional[str] = None):
        self.config = config or {}
        self.env = env or os.getenv("NUWA_ENV", "dev")

        # 组件初始化
        self.skills = SkillRegistry(skills_dir)
        self.archive = Archive()
        self.guardian = Guardian()
        self.flywheel = FeedbackFlywheel()
        self.model = ModelCaller(
            provider=self.config.get("provider", os.getenv("NUWA_AI_PROVIDER", "deepseek")),
            model=self.config.get("model"),
            api_key=self.config.get("api_key", os.getenv("NUWA_AI_API_KEY")),
            timeout=self.config.get("timeout", 30),
        )

        # 策略
        self.max_retries = 2 if env == "prod" else 1
        self.strict = (env == "prod")

        log.info(f"🌐 WordGateway 就绪 | env={env} | skills={len(self.skills.list_all())}")

    # ── L1 + L2/L3 ──────────────────────────────────────
    def _classify(self, text: str) -> dict:
        """意图识别（关键词优先，可选语义升级）"""
        # 先试语义（如果模型已加载）
        if _semantic_model is not None:
            intent = detect_intent_semantic(text)
        else:
            intent = detect_intent_keyword(text)
        # 匹配 Skill
        skills = self.skills.match_for_intent(intent)
        return {
            "intent": intent,
            "skills": [s["name"] for s in skills],
            "skill_content": self.skills.render_for_prompt(intent),
        }

    # ── Prompt 构建（省 Token 核心）────────────────────
    def _build_prompt(self, user_input: str, classification: dict,
                      context: str = "") -> str:
        """
        构建 prompt —— 只注入相关 Skill，不全塞
        这是省 Token 的关键：7 个 Skill 全塞 ≈ 2000 token，按需 ≈ 300-500
        """
        parts = []

        # 系统指令（精简版）
        parts.append("你是一个严谨的编程助手。输出纯代码，不加解释。")

        # 按需注入 Skill（核心省 Token 逻辑）
        if classification["skill_content"]:
            parts.append(classification["skill_content"])

        # 上下文（来自 Archive 的记忆，已裁剪）
        if context:
            parts.append(f"# 上下文\n{context}")

        # 用户请求
        parts.append(f"# 任务\n{user_input}")

        return "\n\n".join(parts)

    # ── L4 守门 ────────────────────────────────────────
    def _guard_check(self, code: str) -> Report:
        """调用 work.py 的 check()，对外不暴露规则细节"""
        return guard_check(code)

    # ── L5 反馈式重试 ──────────────────────────────────
    def _build_feedback_prompt(self, original_prompt: str,
                               violations: list) -> str:
        """把违规原因告诉模型，让它知道哪里错了"""
        feedback = "⚠️ 上一次输出未通过检查，请修复以下问题：\n"
        for v in violations:
            if hasattr(v, 'rule'):
                feedback += f"  - [{v.rule}] {v.message}\n"
            else:
                feedback += f"  - {v}\n"
        feedback += "\n请修正后重新输出完整代码。"
        return original_prompt + "\n\n" + feedback
        return original_prompt + "\n\n" + feedback

    # ── 主入口 ──────────────────────────────────────────
    def handle(self, user_input: str, conversation_id: str = "default") -> dict:
        """
        处理一次完整请求

        返回：
            {
                "success": bool,
                "output": str,
                "intent": str,
                "skills_used": list,
                "attempts": int,
                "violations": list,
                "conservative_pass": bool,
                "context_saved": bool,
            }
        """
        # L1 清洗
        text = _sanitize_input(user_input)
        if not _is_valid_request(text):
            return {
                "success": False,
                "output": "",
                "error": "无效请求（空内容或纯标点）",
                "intent": "invalid",
                "skills_used": [],
                "attempts": 0,
                "violations": [],
                "conservative_pass": False,
                "context_saved": False,
            }

        # L2/L3 分类
        classification = self._classify(text)
        intent = classification["intent"]
        log.info(f"📌 意图: {intent} | Skills: {classification['skills']}")

        # 获取上下文（Archive 记忆，已 SimHash 裁剪）
        ctx = self.archive.get_context(conversation_id)
        context_str = ""
        if ctx:
            context_str = "\n".join(f"- {c}" for c in ctx[-3:])

        # 构建 prompt
        prompt = self._build_prompt(text, classification, context_str)

        # L5 反馈式重试
        last_violations = []
        output = ""
        code = ""
        report = None
        for attempt in range(self.max_retries + 1):
            if attempt == 0:
                current_prompt = prompt
            else:
                # 关键：把违规原因注入 prompt，不是死循环赌博
                current_prompt = self._build_feedback_prompt(prompt, last_violations)
                log.info(f"🔄 第 {attempt} 次重试（带反馈）")

            # 调模型
            output = self.model.generate(current_prompt)

            # 非字符串输出（模型挂了 → SafeResult）→ 保守通过
            if not isinstance(output, str):
                output = str(output)
                code = ""
                report = None
                last_violations = []
                break

            # 提取代码（去掉 markdown 包裹）
            code = self._extract_code(output)

            # L4 守门
            if not code.strip():
                # 没有代码内容，跳过守门
                break

            report = self._guard_check(code)

            if report.passed:
                log.info(f"✅ 第 {attempt} 次通过")
                break
            else:
                last_violations = report.violations
                log.warning(f"⚠️ 第 {attempt} 次违规: {[v.rule for v in last_violations]}")

        # 记录飞轮（output 保证是字符串）
        output_preview = output[:500] if isinstance(output, str) else str(output)[:500]
        success = bool(code.strip()) and (not last_violations or (report and report.passed))
        self.flywheel.record(
            prompt=text, output=output_preview,
            violations=[str(v) for v in last_violations],
            attempt=attempt, fixed=success,
        )

        # 存档记忆
        self.archive.add(conversation_id, text)

        return {
            "success": success,
            "output": output,
            "intent": intent,
            "skills_used": classification["skills"],
            "attempts": attempt + 1,
            "violations": [str(v) for v in last_violations],
            "conservative_pass": not isinstance(output, str),
            "context_saved": True,
        }

    def _extract_code(self, text) -> str:
        """从模型输出中提取代码块"""
        import re
        # 非字符串（如 SafeResult）直接转字符串
        if not isinstance(text, str):
            text = str(text)
        # 找 ```python ... ``` 或 ``` ... ```
        matches = re.findall(r"```(?:\w+)?\n(.*?)```", text, re.DOTALL)
        if matches:
            return "\n".join(matches)
        return text


# ═════════════════════════════════════════════════════════
#  CLI 入口
# ═════════════════════════════════════════════════════════
def main():
    """命令行入口"""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    import argparse
    parser = argparse.ArgumentParser(
        description="Word 体系 —— AI 治理网关")
    parser.add_argument("prompt", nargs="?", help="用户请求内容")
    parser.add_argument("--env", default=os.getenv("NUWA_ENV", "dev"),
                        choices=["dev", "test", "prod"])
    parser.add_argument("--provider", default=os.getenv("NUWA_AI_PROVIDER", "deepseek"))
    parser.add_argument("--conversation", default="cli", help="对话 ID（用于记忆）")
    parser.add_argument("--interactive", "-i", action="store_true", help="交互模式")
    args = parser.parse_args()

    gw = WordGateway(env=args.env, config={"provider": args.provider})

    if args.interactive or not args.prompt:
        # 交互模式
        print("🛡️  Word 网关交互模式（输入 'quit' 退出）")
        conv_id = args.conversation
        while True:
            try:
                user = input("\n👤 你: ").strip()
            except (KeyboardInterrupt, EOFError):
                print("\n👋 再见")
                break
            if user.lower() in ("quit", "exit", "q"):
                print("👋 再见")
                break
            if not user:
                continue
            result = gw.handle(user, conversation_id=conv_id)
            print(f"\n🤖 AI [{result['intent']}]:")
            print(result["output"][:2000])
            if result["violations"]:
                print(f"\n⚠️ 违规: {result['violations']}")
    else:
        result = gw.handle(args.prompt, conversation_id=args.conversation)
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
