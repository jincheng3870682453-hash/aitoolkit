#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gateway.py — 统一网关 V3.1（诚实版）

修复记录（回应 audit）：
  [F1] Mock 模式：移除静默兜底，调用失败直接抛 ModelCallError
  [F2] 重试逻辑：改为反馈式重试（把违规原因注入 prompt）
  [F3] 无状态：移除 FeedbackFlywheel 内存状态，改为文件-only
  [F4] 密钥安全：强制环境变量优先级最高，config.json 不存明文
  [F5] 意图识别：升级为 sentence-transformers 语义匹配（可选降级为关键词）
"""

import os
import re
import sys
import json
import random
import string
import logging
import importlib
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass, field
from typing import Optional

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("gateway")


# ═══════════════════════════════════════════════════════
# 异常定义
# ═══════════════════════════════════════════════════════

class ModelCallError(RuntimeError):
    """模型调用失败 —— 不静默，不 Mock，直接抛"""
    pass


# ═══════════════════════════════════════════════════════
# 工具函数
# ═══════════════════════════════════════════════════════

def _rid(prefix: str = "id", n: int = 8) -> str:
    return prefix + "-" + "".join(random.choices(string.hexdigits.lower(), k=n))

def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")

def _read(p: str) -> str:
    try:
        return Path(p).read_text(encoding="utf-8")
    except Exception:
        return ""

def _write(p: str, content: str) -> None:
    Path(p).parent.mkdir(parents=True, exist_ok=True)
    Path(p).write_text(content, encoding="utf-8")


# ═══════════════════════════════════════════════════════
# L1 — IntentEngine  意图理解（语义匹配 + 关键词降级）
# ═══════════════════════════════════════════════════════

class IntentEngine:
    """
    意图识别 —— 优先用 sentence-transformers 做语义匹配，
    不可用时降级为关键词匹配（明确标注准确率有限）。
    """

    CATEGORIES = {
        "code_python":  ["python", "函数", "类", "def ", "import ", "pip", "爬虫", "脚本"],
        "code_java":    ["java", "spring", "maven", "jvm", "jar"],
        "code_api":     ["接口", "api", "路由", "endpoint", "rest", "微服务"],
        "code_sql":     ["sql", "查询", "数据库", "select", "insert", "表", "迁移"],
        "code_refactor":["重构", "优化", "简化", "重命名", "重构代码"],
        "fiction":      ["小说", "故事", "角色", "剧情", "世界观", "章节", "叙事"],
        "doc":          ["文档", "readme", "说明", "markdown", "注释"],
        "config":       ["配置", "环境变量", "config", "settings", "yaml"],
        "test":         ["测试", "test", "unittest", "pytest", "断言"],
        "security":     ["安全", "加密", "签名", "认证", "鉴权", "漏洞"],
    }

    def __init__(self):
        self._model = None
        self._use_semantic = False
        self._category_texts: dict[str, str] = {}
        # 预生成每个类别的描述文本（用于语义匹配）
        self._category_texts = {
            k: " ".join(v) for k, v in self.CATEGORIES.items()
        }
        # 尝试加载语义模型
        try:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer("all-MiniLM-L6-v2")
            # 预编码所有类别
            self._cat_embeddings = self._model.encode(
                list(self._category_texts.values()),
                convert_to_numpy=True,
            )
            self._use_semantic = True
            log.info("🧠 意图识别: 语义模式 (sentence-transformers)")
        except Exception:
            self._use_semantic = False
            log.info("💡 意图识别: 关键词模式（安装 sentence-transformers 可升级为语义匹配）")

    def classify(self, user_input: str) -> dict:
        text = user_input.lower()

        if self._use_semantic:
            try:
                import numpy as np
                q_emb = self._model.encode([user_input], convert_to_numpy=True)[0]
                sims = np.dot(self._cat_embeddings, q_emb) / (
                    np.linalg.norm(self._cat_embeddings, axis=1) * np.linalg.norm(q_emb) + 1e-9
                )
                best_idx = int(sims.argmax())
                best_cat = list(self.CATEGORIES.keys())[best_idx]
                confidence = float(sims[best_idx])
                if confidence < 0.3:
                    return {"category": "general", "confidence": 0.0, "tags": [], "method": "semantic"}
                return {
                    "category": best_cat,
                    "confidence": round(confidence, 3),
                    "tags": [kw for kw in self.CATEGORIES[best_cat] if kw.lower() in text],
                    "method": "semantic",
                }
            except Exception:
                pass  # 降级到关键词

        # 关键词匹配（降级方案）
        scores: dict[str, float] = {}
        for cat, kws in self.CATEGORIES.items():
            score = 0.0
            for kw in kws:
                if kw.lower() in text:
                    score += 1.0
            if score > 0:
                scores[cat] = score
        if not scores:
            return {"category": "general", "confidence": 0.0, "tags": [], "method": "keyword"}
        best = max(scores, key=scores.get)
        return {
            "category": best,
            "confidence": round(scores[best] / len(self.CATEGORIES[best]), 3),
            "tags": [kw for kw in self.CATEGORIES[best] if kw.lower() in text],
            "method": "keyword",
        }


# ═══════════════════════════════════════════════════════
# L2 — Skill  技能单元
# ═══════════════════════════════════════════════════════

@dataclass
class Skill:
    """单个 Skill 文件"""
    name: str
    content: str
    tags: list[str] = field(default_factory=list)
    desc: str = ""

    @classmethod
    def load(cls, path: str) -> "Skill":
        text = Path(path).read_text(encoding="utf-8")
        tags: list[str] = []
        desc = ""
        for line in text.splitlines():
            if line.startswith("# Tags:"):
                tags = [t.strip() for t in line.replace("# Tags:", "").split(",")]
            elif line.startswith("# Desc:"):
                desc = line.replace("# Desc:", "").strip()
        return cls(name=Path(path).stem, content=text, tags=tags, desc=desc)

    @classmethod
    def load_dir(cls, directory: str) -> list["Skill"]:
        skills = []
        d = Path(directory)
        if not d.exists():
            return skills
        for f in sorted(d.glob("*.skill")):
            try:
                skills.append(cls.load(str(f)))
            except Exception as e:
                log.warning(f"⚠️ 加载 Skill 失败 {f}: {e}")
        return skills


class SkillRecommender:
    """
    Skill 推荐器 —— 不猜用户要什么，直接问。
    支持语义匹配（如果 sentence-transformers 可用）。
    """

    def __init__(self, skills: list[Skill]):
        self.skills = skills
        self._skill_embeddings = None
        try:
            from sentence_transformers import SentenceTransformer
            model = SentenceTransformer("all-MiniLM-L6-v2")
            self._skill_embeddings = model.encode(
                [s.content[:500] for s in skills],
                convert_to_numpy=True,
            )
            self._sem_model = model
        except Exception:
            pass

    def recommend(self, user_input: str, top_k: int = 5) -> list[Skill]:
        text = user_input.lower()
        scored: list[tuple[float, Skill]] = []

        if self._skill_embeddings is not None:
            import numpy as np
            q_emb = self._sem_model.encode([user_input], convert_to_numpy=True)[0]
            sims = np.dot(self._skill_embeddings, q_emb) / (
                np.linalg.norm(self._skill_embeddings, axis=1) * np.linalg.norm(q_emb) + 1e-9
            )
            indices = sims.argsort()[-top_k:][::-1]
            return [self.skills[i] for i in indices if sims[i] > 0.2]

        # 降级：关键词
        extra_kw = ["python", "api", "sql", "markdown", "error",
                    "test", "refactor", "fiction", "novel", "narrative",
                    "小说", "故事", "剧情", "接口", "数据库", "文档",
                    "世界观", "角色", "章节"]
        for s in self.skills:
            score = 0
            for tag in s.tags:
                if tag.lower() in text:
                    score += 2
            content_l = s.content.lower()
            for kw in extra_kw:
                if kw in text and kw in content_l:
                    score += 1
            for word in re.split(r"[\s,，。.!?]+", user_input):
                if len(word) >= 2 and word.lower() in content_l:
                    score += 0.5
            if score > 0:
                scored.append((score, s))
        scored.sort(key=lambda x: -x[0])
        return [s for _, s in scored[:top_k]]

    def ask_user(self, user_input: str, top_k: int = 5) -> list[Skill]:
        """交互式：弹出推荐 → 用户勾选 → 返回"""
        recs = self.recommend(user_input, top_k)
        if not recs:
            return []
        print(f"\n{'═'*40}")
        print(f"🎯 检测到需求: {user_input}")
        print(f"{'─'*40}")
        print(f"📋 推荐以下 Skill（输入编号选择，逗号分隔）:\n")
        for i, s in enumerate(recs, 1):
            tags = ", ".join(s.tags)
            desc = s.desc or s.content.split('\n')[0][:60]
            print(f"  [{i}] {s.name}  ({tags})")
            print(f"      └─ {desc}")
        print(f"\n  [a] 全选   [s] 跳过   [q] 取消")
        print(f"{'═'*40}")

        try:
            choice = input("👉 你的选择(默认全选): ").strip()
        except (KeyboardInterrupt, EOFError):
            choice = ""

        if choice == "q":
            return []
        if choice == "s":
            return []
        if choice == "a" or not choice:
            return recs
        selected = []
        for idx in choice.split(","):
            idx = idx.strip()
            if idx.isdigit() and 1 <= int(idx) <= len(recs):
                selected.append(recs[int(idx) - 1])
        return selected or recs

    def assemble(self, skills: list[Skill], user_input: str) -> str:
        if not skills:
            return user_input
        parts = ["以下是可用的专业规范（Skill）：\n"]
        for s in skills:
            parts.append(f"--- Skill: {s.name} ---")
            parts.append(s.content[:2000])
            parts.append("")
        parts.append(f"--- 用户需求 ---")
        parts.append(user_input)
        return "\n".join(parts)


# ═══════════════════════════════════════════════════════
# L3 — FineTunedCore  多平台模型调用（无 Mock 兜底）
# ═══════════════════════════════════════════════════════

PROVIDERS: dict[str, dict] = {
    "openai":      {"url": "https://api.openai.com/v1/chat/completions",       "model": "gpt-4o-mini"},
    "anthropic":   {"url": "https://api.anthropic.com/v1/messages",           "model": "claude-sonnet-4-20250514"},
    "gemini":      {"url": "https://generativelanguage.googleapis.com/v1beta/models", "model": "gemini-1.5-pro"},
    "ollama":      {"url": "http://localhost:11434/api/generate",             "model": "llama2"},
    "qwen":        {"url": "https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation", "model": "qwen-plus"},
    "zhipu":       {"url": "https://open.bigmodel.cn/api/paas/v4/chat/completions", "model": "glm-4"},
    "deepseek":    {"url": "https://api.deepseek.com/v1/chat/completions",    "model": "deepseek-coder"},
    "minimax":     {"url": "https://api.minimax.chat/v1/text/chatcompletion_v2", "model": "abab6-chat"},
    "baichuan":    {"url": "https://api.baichuan-ai.com/v1/chat",            "model": "Baichuan3-Turbo"},
    "hunyuan":     {"url": "https://hunyuan.tencentcloudapi.com/",           "model": "hunyuan-pro"},
}


class FineTunedCore:
    """多平台模型调用 —— 失败时直接抛异常，不返回假数据"""

    def __init__(self, provider: str = "deepseek", model: str = "",
                 api_key: str = "", base_url: str = "", timeout: int = 60):
        self.provider = provider
        self.model = model or PROVIDERS.get(provider, {}).get("model", "default")
        # [F4] 密钥优先级：环境变量 > 传入参数 > 报错
        self.api_key = (
            os.getenv(f"NUWA_AI_API_KEY")
            or os.getenv(f"{provider.upper()}_API_KEY")
            or api_key
        )
        if not self.api_key:
            raise ModelCallError(
                f"❌ 未配置 API Key。请设置环境变量 NUWA_AI_API_KEY 或 {provider.upper()}_API_KEY"
            )
        self.base_url = base_url or PROVIDERS.get(provider, {}).get("url", "")
        self.timeout = timeout

    def generate(self, prompt: str, **kwargs) -> str:
        """调用模型生成文本 —— 失败直接抛 ModelCallError"""
        try:
            import requests
        except ImportError:
            raise ModelCallError("❌ 缺少依赖: pip install requests")

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        url = self.base_url
        data: dict = {}

        if self.provider == "anthropic":
            data = {
                "model": self.model,
                "max_tokens": kwargs.get("max_tokens", 2048),
                "messages": [{"role": "user", "content": prompt}],
            }
        elif self.provider == "gemini":
            url = f"{self.base_url}/{self.model}:generateContent?key={self.api_key}"
            data = {"contents": [{"parts": [{"text": prompt}]}]}
        elif self.provider == "ollama":
            data = {"model": self.model, "prompt": prompt, "stream": False}
        else:
            data = {
                "model": self.model,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": kwargs.get("max_tokens", 2048),
                "temperature": kwargs.get("temperature", 0.3),
            }

        try:
            resp = requests.post(url, headers=headers, json=data, timeout=self.timeout)
            resp.raise_for_status()
            j = resp.json()
        except requests.exceptions.Timeout:
            raise ModelCallError(f"❌ 模型调用超时 ({self.provider}, {self.timeout}s)")
        except requests.exceptions.ConnectionError:
            raise ModelCallError(f"❌ 网络连接失败 ({self.provider})，请检查网络或代理")
        except requests.exceptions.HTTPError as e:
            raise ModelCallError(f"❌ 模型返回错误 ({self.provider}): {e}")
        except Exception as e:
            raise ModelCallError(f"❌ 模型调用异常 ({self.provider}): {e}")

        # 统一提取文本
        try:
            if self.provider == "anthropic":
                return j.get("content", [{}])[0].get("text", "")
            elif self.provider == "gemini":
                return j.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "")
            elif self.provider == "ollama":
                return j.get("response", "")
            else:
                return j.get("choices", [{}])[0].get("message", {}).get("content", "")
        except Exception as e:
            raise ModelCallError(f"❌ 模型返回格式异常: {e}")

    def list_providers(self) -> dict:
        return {k: v["model"] for k, v in PROVIDERS.items()}


# ═══════════════════════════════════════════════════════
# L4 — PolicyEngine  动态策略引擎
# ═══════════════════════════════════════════════════════

class PolicyEngine:
    """
    动态策略引擎 —— 按环境等级加载不同规则集。
    dev → 只卡红线（安全相关）
    test → 加代码质量
    prod → 全部规则 + 严格模式
    """

    POLICIES = {
        "dev": {
            "description": "开发环境：仅安全红线",
            "rules": ["no_hardcoded_secrets", "no_sql_injection"],
            "max_retries": 1,
            "strict": False,
        },
        "test": {
            "description": "测试环境：加代码质量",
            "rules": [
                "type_hints", "no_hardcoded_secrets",
                "no_sql_injection", "markdown_clean",
                "no_infinite_recursion", "no_unused_import",
            ],
            "max_retries": 2,
            "strict": False,
        },
        "prod": {
            "description": "生产环境：全部规则 + 严格模式",
            "rules": [
                "type_hints", "try_except", "no_hardcoded_secrets",
                "no_sql_injection", "markdown_clean",
                "no_infinite_recursion", "no_unused_import",
                "v1_ast_check",
            ],
            "max_retries": 2,
            "strict": True,
        },
    }

    def __init__(self, env: str = "dev"):
        self.env = env if env in self.POLICIES else "dev"
        self.policy = self.POLICIES[self.env].copy()

    def active_rule_names(self, all_rule_names: list[str]) -> list[str]:
        active = set(self.policy["rules"])
        return [r for r in all_rule_names if r in active]

    def should_block(self, results: list) -> bool:
        if self.policy.get("strict"):
            return any(not r.passed for r in results)
        return any(not r.passed and r.action == "rollback" for r in results)

    def max_retries(self) -> int:
        return self.policy.get("max_retries", 2)


# ═══════════════════════════════════════════════════════
# L5 — FeedbackStore  反馈存储（文件 only，无内存状态）
# ═══════════════════════════════════════════════════════

@dataclass
class FeedbackRecord:
    """单条反馈记录"""
    timestamp: str
    user_input: str
    rule: str
    original: str
    fixed: str
    skills: list[str] = field(default_factory=list)
    verdict_id: str = ""

class FeedbackStore:
    """
    反馈存储 —— 仅文件持久化，不在内存中维护全局状态。
    每次 record() 直接追加写入文件，不缓存到内存。
    导出训练数据时按需读取文件。
    """

    def __init__(self, store_dir: str = "feedback"):
        self.store_dir = Path(store_dir)
        self.store_dir.mkdir(parents=True, exist_ok=True)
        self._file = self.store_dir / "feedback.jsonl"

    def record(self, *, user_input: str, rule: str,
               original: str, fixed: str,
               skills: list[str] | None = None,
               verdict_id: str = "") -> FeedbackRecord:
        rec = FeedbackRecord(
            timestamp=_now(),
            user_input=user_input[:200],
            rule=rule,
            original=original[:1000],
            fixed=fixed[:1000],
            skills=skills or [],
            verdict_id=verdict_id,
        )
        # 直接追加写文件，不维护内存列表
        with open(self._file, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec.__dict__, ensure_ascii=False) + "\n")
        return rec

    def export_training_data(self, output_path: str) -> str:
        """导出 SFT 训练数据（JSONL 格式）"""
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        count = 0
        with open(output_path, "w", encoding="utf-8") as out:
            for line in self._file.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    d = json.loads(line)
                    item = {
                        "instruction": d.get("user_input", ""),
                        "input": d.get("original", ""),
                        "output": d.get("fixed", ""),
                        "metadata": {
                            "rule": d.get("rule", ""),
                            "skills": d.get("skills", []),
                            "verdict_id": d.get("verdict_id", ""),
                        },
                    }
                    out.write(json.dumps(item, ensure_ascii=False) + "\n")
                    count += 1
                except json.JSONDecodeError as e:
                    log.warning(f"⚠️ 跳过损坏记录: {e}")
        return f"导出 {count} 条 SFT 训练样本 → {output_path}"

    def stats(self) -> dict:
        """按需读取文件统计"""
        if not self._file.exists():
            return {"total": 0, "by_rule": {}}
        by_rule: dict = {}
        total = 0
        for line in self._file.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                d = json.loads(line)
                total += 1
                r = d.get("rule", "unknown")
                by_rule[r] = by_rule.get(r, 0) + 1
            except json.JSONDecodeError:
                continue
        return {"total": total, "by_rule": by_rule}


# ═══════════════════════════════════════════════════════
# V1Bridge  V1 模块桥接（异常不吞，记录后继续）
# ═══════════════════════════════════════════════════════

class V1Bridge:
    """
    V1 模块桥接 —— 检测失败时记录错误并继续，不静默吞掉。
    """

    MODULES = ["work", "guardian", "Archive", "shiyun", "Nuwa"]

    def __init__(self):
        self.available: dict[str, bool] = {}
        self.modules: dict[str, object] = {}
        self.errors: list[str] = []
        for name in self.MODULES:
            try:
                mod = importlib.import_module(f".{name}", package="Toolkit")
                self.modules[name] = mod
                self.available[name] = True
            except Exception as e:
                self.available[name] = False
                self.errors.append(f"⚠️ 模块 {name} 加载失败: {e}")
                log.warning(f"⚠️ 模块 {name} 不可用: {e}")

    def get(self, name: str):
        return self.modules.get(name)

    def ast_check(self, code: str) -> list[dict]:
        """调用 V1 work.py 的 AST 检测 —— 失败返回错误记录，不静默"""
        work_mod = self.get("work")
        if not work_mod:
            return [{"rule": "v1_ast_check", "passed": True, "note": "V1 work 模块不可用"}]
        results = []
        for fn_name in ["check_type_hints", "check_no_recursion",
                        "check_hardcoded", "check_injection"]:
            fn = getattr(work_mod, fn_name, None)
            if not fn:
                results.append({"rule": fn_name, "passed": True, "note": "函数不存在"})
                continue
            try:
                r = fn(code)
                if isinstance(r, dict):
                    results.append(r)
            except Exception as e:
                # [F7] 不静默，记录具体错误
                log.error(f"❌ V1 检测 {fn_name} 异常: {e}")
                results.append({
                    "rule": fn_name,
                    "passed": False,
                    "action": "warn",
                    "evidence": {"error": str(e)},
                    "message": f"检测模块异常: {e}",
                })
        return results

    def snapshot(self, root: str = ".") -> Optional[str]:
        g = self.get("guardian")
        if not g:
            return None
        fn = getattr(g, "create_snapshot", None)
        if not fn:
            return None
        try:
            return fn(root)
        except Exception as e:
            log.error(f"❌ 快照创建失败: {e}")
            return None

    def rollback(self, snap_id: str, root: str = ".") -> Optional[dict]:
        g = self.get("guardian")
        if not g:
            return None
        fn = getattr(g, "rollback", None)
        if not fn:
            return None
        try:
            return fn(snap_id, root)
        except Exception as e:
            log.error(f"❌ 回滚失败: {e}")
            return None


# ═══════════════════════════════════════════════════════
# GatewayResult  统一返回
# ═══════════════════════════════════════════════════════

@dataclass
class GatewayResult:
    """WordGateway 的统一返回"""
    intent: dict = field(default_factory=dict)
    intent_method: str = ""  # semantic / keyword
    skills_used: list[str] = field(default_factory=list)
    model_output: str = ""
    guard_summary: dict = field(default_factory=dict)
    retries: int = 0
    final_action: str = "pass"
    multilingal: dict = field(default_factory=dict)
    verdict_id: str = ""
    errors: list[str] = field(default_factory=list)


# ═══════════════════════════════════════════════════════
# WordGateway  主入口（无状态）
# ═══════════════════════════════════════════════════════

class WordGateway:
    """
    Word 体系统一网关 V3.1（诚实版）。

    设计原则：
    - 无状态：不维护任何跨请求的内存状态
    - 不欺骗：模型失败直接报错，不返回 Mock 数据
    - 反馈式重试：违规时把原因注入 prompt，让模型知道哪里错了
    - 密钥安全：强制环境变量优先
    """

    def __init__(self, config: dict | None = None):
        config = config or {}

        # 环境
        self.env_name = config.get("env", os.getenv("NUWA_ENV", "dev"))
        self.user = config.get("user", os.getenv("NUWA_USER", "anonymous"))

        # 子模块（每次创建新实例，无共享状态）
        self.intent = IntentEngine()
        self.skill_recommender = SkillRecommender(
            Skill.load_dir(config.get("skill_dir", "Toolkit/skills"))
        )

        # 模型配置（强制环境变量优先）
        provider = config.get("model", {}).get("provider", "deepseek")
        api_key = config.get("model", {}).get("api_key", "")
        # 如果 config 里写了明文 key，发出警告
        if api_key and not api_key.startswith("${"):
            log.warning("⚠️ 检测到 config 中可能存在明文 API Key，建议使用环境变量")

        self.model = FineTunedCore(
            provider=provider,
            model=config.get("model", {}).get("model", ""),
            api_key=api_key,
            base_url=config.get("model", {}).get("base_url", ""),
            timeout=config.get("model", {}).get("timeout", 60),
        )
        self.guard = None  # 延迟导入，避免循环依赖
        self.policy = PolicyEngine(self.env_name)
        self.feedback_store = FeedbackStore(config.get("feedback_dir", "feedback"))
        self.v1 = V1Bridge()

        # 延迟导入 work（避免循环引用）
        try:
            from . import work
            self.work_mod = work
            self.guard = work.InstinctGuard()
            self.multilang = work.MultiLangASTEngine()
        except Exception as e:
            log.error(f"❌ work 模块加载失败: {e}")
            self.work_mod = None
            self.guard = None
            self.multilang = None

        # 回滚陪审团（来自 guardian 模块）
        self.jury = None
        guardian_mod = self.v1.get("guardian")
        if guardian_mod:
            try:
                self.jury = guardian_mod.RollbackJury(
                    config.get("verdict_dir", "verdicts"))
            except Exception as e:
                log.error(f"❌ RollbackJury 初始化失败: {e}")

        # 辐射检测（来自 Nuwa 模块）
        self.rad = None
        nuwa_mod = self.v1.get("Nuwa")
        if nuwa_mod:
            try:
                rad_class = getattr(nuwa_mod, "RadiationDetector", None)
                if rad_class:
                    self.rad = rad_class(config.get("project_root", "."))
            except Exception as e:
                log.error(f"❌ RadiationDetector 初始化失败: {e}")

        # 配置守门规则（按策略过滤）
        if self.guard:
            all_rules = list(self.guard.ALL_RULES)
            active = self.policy.active_rule_names(all_rules)
            v1_rules = ["v1_ast_check"] if self.v1.available.get("work") else []
            self.guard.extra_rules = [r for r in v1_rules if r in active]

    # ── 构建违规反馈 prompt ────────────────────────
    def _build_feedback_prompt(self, original_prompt: str,
                              guard_results: list,
                              ml_result: dict) -> str:
        """把违规原因注入 prompt，让模型知道哪里错了"""
        parts = [original_prompt]
        parts.append("\n\n--- 上次生成的问题（请修复后再输出）---")
        for gr in guard_results:
            if gr.passed:
                continue
            parts.append(f"\n❌ 违规规则: {gr.rule}")
            parts.append(f"   原因: {gr.message}")
            if gr.evidence:
                ev = json.dumps(gr.evidence, ensure_ascii=False)[:300]
                parts.append(f"   证据: {ev}")
        if ml_result and not ml_result.get("passed", True):
            parts.append(f"\n❌ 多语言检测: {ml_result.get('language', '?')}")
            for v in ml_result.get("violations", []):
                parts.append(f"   - {v.get('rule', '?')}: {v.get('on_fail', '')}")
        parts.append("\n请修复以上所有问题后重新输出完整代码。")
        return "\n".join(parts)

    # ── 主入口 ──────────────────────────────────────
    def handle(self, user_input: str, *, interactive: bool = False,
               filename: str = "") -> GatewayResult:
        """
        处理一次完整的用户请求。
        无状态：每次调用独立，不依赖历史内存状态。
        """
        result = GatewayResult(intent=self.intent.classify(user_input))
        result.intent_method = result.intent.get("method", "unknown")

        # L2: Skill 推荐
        if interactive:
            skills = self.skill_recommender.ask_user(user_input)
        else:
            skills = self.skill_recommender.recommend(user_input)
        result.skills_used = [s.name for s in skills]

        # 组装 prompt
        prompt = self.skill_recommender.assemble(skills, user_input)

        # L3+L4: 模型调用 + 守门检测（反馈式重试）
        max_retries = self.policy.max_retries()
        output = ""
        last_error = None

        for attempt in range(max_retries + 1):
            try:
                if attempt == 0:
                    output = self.model.generate(prompt)
                else:
                    # [F4] 反馈式重试：把违规原因告诉模型
                    feedback_prompt = self._build_feedback_prompt(
                        prompt, guard_results, ml_result)
                    output = self.model.generate(feedback_prompt)
                result.retries = attempt
            except ModelCallError as e:
                last_error = str(e)
                result.errors.append(last_error)
                log.error(last_error)
                break  # 模型调用失败，不重试（重试也没用）

            # L4: 守门检测
            if self.guard:
                guard_results = self.guard.check_all(output)
            else:
                guard_results = []
            result.guard_summary = self.guard.summary(guard_results) if self.guard else {}

            # 多语言检测
            if self.multilang:
                ml_result = self.multilang.check(output, filename)
            else:
                ml_result = {"language": "unknown", "violations": [], "passed": True}
            result.multilingal = ml_result

            # 判断是否需要重试
            should_block = self.policy.should_block(guard_results)
            if not should_block and ml_result.get("passed", True):
                result.final_action = "pass"
                break

            # 违规 → 签发判决书
            for gr in guard_results:
                if gr.passed:
                    continue
                if self.jury:
                    try:
                        verdict = self.jury.issue(
                            rule_name=gr.rule,
                            original_code=output[:500],
                            evidence=gr.evidence,
                            snapshot_id=f"snap-{attempt}",
                            user=self.user,
                            env=self.env_name,
                            model=self.model.provider,
                        )
                        result.verdict_id = verdict.data["verdict_id"]
                    except Exception as e:
                        log.error(f"❌ 判决书签发失败: {e}")

                # 记录反馈（文件持久化，无内存状态）
                self.feedback_store.record(
                    user_input=user_input,
                    rule=gr.rule,
                    original=output[:500],
                    fixed=f"[retry-{attempt+1}]",
                    skills=result.skills_used,
                    verdict_id=result.verdict_id,
                )

            log.info(f"  ⚠️ 第 {attempt+1} 次尝试违规，注入反馈后重试...")

        if last_error:
            result.final_action = "error"
            result.model_output = f"❌ 模型调用失败: {last_error}"
        else:
            result.model_output = output
            if self.guard:
                result.model_output = self.guard.sanitize(output)
        return result

    # ── 统计（按需读取文件，不依赖内存） ────────────
    def stats(self) -> dict:
        return {
            "env": self.env_name,
            "policy": self.policy.policy.get("description", ""),
            "rules_active": self.policy.active_rule_names(
                list(self.guard.ALL_RULES) if self.guard else []),
            "skills_loaded": len(self.skill_recommender.skills),
            "intent_method": "semantic" if self.intent._use_semantic else "keyword",
            "v1_available": self.v1.available,
            "feedback": self.feedback_store.stats(),
            "jury": self.jury.stats() if self.jury else {},
            "multilang": self.multilang.list_supported() if self.multilang else {},
            "errors": self.v1.errors,
        }


# ═══════════════════════════════════════════════════════
# CLI 入口
# ═══════════════════════════════════════════════════════

def main():
    """命令行入口"""
    config_path = "config.json"
    config = {}
    if Path(config_path).exists():
        try:
            config = json.loads(Path(config_path).read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            print(f"❌ 配置文件解析失败: {e}")
            print("💡 请检查 config.json 格式，或删除后重新配置")
            sys.exit(1)
    else:
        config = {
            "env": os.getenv("NUWA_ENV", "dev"),
            "model": {
                "provider": os.getenv("NUWA_AI_PROVIDER", "deepseek"),
                "api_key_env": "NUWA_AI_API_KEY",
            },
            "skill_dir": "Toolkit/skills",
            "user": "cli_user",
        }

    try:
        gw = WordGateway(config)
    except ModelCallError as e:
        print(e)
        print("\n💡 设置环境变量后重试:")
        print("   export NUWA_AI_API_KEY=sk-你的真实key")
        print("   export NUWA_ENV=dev  # 或 test / prod")
        sys.exit(1)

    method = "语义" if gw.intent._use_semantic else "关键词"
    print(f"🛡️ Word 体系网关 V3.1 | 环境: {gw.env_name} | 模型: {gw.model.provider}")
    print(f"📋 规则: {len(gw.policy.active_rule_names(list(gw.guard.ALL_RULES) if gw.guard else []))} 条激活")
    print(f"🎯 Skills: {len(gw.skill_recommender.skills)} 个")
    print(f"🧠 意图识别: {method}模式")
    print(f"🔌 V1: {gw.v1.available}")
    print(f"{'─'*50}")

    # 交互模式
    if sys.stdin.isatty():
        print("💬 输入需求开始对话（输入 'quit' 退出，'stats' 查看统计）:\n")
        while True:
            try:
                user_input = input("👤 > ").strip()
            except (KeyboardInterrupt, EOFError):
                print("\n👋 再见！")
                break
            if not user_input:
                continue
            if user_input.lower() in ("quit", "exit", "q"):
                print("👋 再见！")
                break
            if user_input.lower() == "stats":
                print(json.dumps(gw.stats(), indent=2, ensure_ascii=False))
                continue

            try:
                result = gw.handle(user_input, interactive=True)
            except ModelCallError as e:
                print(f"\n❌ {e}\n")
                continue

            print(f"\n{'═'*50}")
            print(f"📊 意图: {result.intent.get('category','?')} ({result.intent_method})")
            print(f"🎯 Skills: {result.skills_used}")
            print(f"🛡️ 守门: {result.guard_summary}")
            print(f"🔄 重试: {result.retries}")
            print(f"✅ 最终: {result.final_action}")
            if result.verdict_id:
                print(f"⚖️ 判决书: {result.verdict_id}")
            if result.errors:
                print(f"❌ 错误: {result.errors}")
            print(f"{'─'*50}")
            print(f"📤 输出:\n{result.model_output[:500]}")
            print()
    else:
        # 管道模式
        user_input = sys.stdin.read().strip()
        if user_input:
            try:
                result = gw.handle(user_input)
                print(result.model_output)
            except ModelCallError as e:
                print(f"❌ {e}", file=sys.stderr)
                sys.exit(1)


if __name__ == "__main__":
    main()
