#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
enhancements.py — 外部增强适配器

把你提到的那些牛逼工具集成进来。
原则：装了的自动启用，没装的用内置方案，绝不报错。

集成清单：
  ┌─────────────────────┬─────────────────────────────────────────┐
  │ 类别                │ 工具                                    │
  ├─────────────────────┼─────────────────────────────────────────┤
  │ 上下文压缩          │ claw-compactor / Distill / CRUX         │
  │                     │ TokenReducer / ContextCore              │
  ├─────────────────────┼─────────────────────────────────────────┤
  │ 代码质量检查        │ AI-SLOP Detector / pyqual / CodeTrust │
  │                     │ kiss / code-arbiter                    │
  ├─────────────────────┼─────────────────────────────────────────┤
  │ 意图识别与 Skill    │ SkillTree / openclaw-intent-router     │
  ├─────────────────────┼─────────────────────────────────────────┤
  │ 综合网关            │ Tokenless / rtk / ClawVault / tokencap │
  ├─────────────────────┼─────────────────────────────────────────┤
  │ 代码库结构化        │ reducethemtokens                       │
  └─────────────────────┴─────────────────────────────────────────┘

使用方式：
  from Toolkit.enhancements import get_compressor, get_quality_checker
  compressor = get_compressor()  # 自动选最优的
  compressed = compressor.compress(huge_context)
"""

import re
import os
import json
import logging
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional

log = logging.getLogger("enhancements")


# ════════════════════════════════════════════════════════
# 通用接口（所有适配器都实现这个）
# ════════════════════════════════════════════════════════

@dataclass
class CompressResult:
    """压缩结果"""
    text: str
    original_tokens: int
    compressed_tokens: int
    ratio: float  # 压缩率 0~1
    method: str  # 用了什么方法
    available: bool = True

@dataclass
class QualityResult:
    """代码质量检查结果"""
    passed: bool
    score: float  # 0~100
    issues: list[dict] = field(default_factory=list)
    method: str = ""
    available: bool = True


# ════════════════════════════════════════════════════════
# 1. 上下文压缩（5 种工具 + 内置降级）
# ════════════════════════════════════════════════════════

class BuiltinCompressor:
    """内置压缩（不依赖任何外部库，永远可用）"""
    name = "builtin-truncation"

    def compress(self, text: str, max_tokens: int = 2000) -> CompressResult:
        # 简单策略：按行截断 + 保留首尾
        lines = text.splitlines()
        orig_tokens = len(text) // 4  # 粗略估算

        if orig_tokens <= max_tokens:
            return CompressResult(text, orig_tokens, orig_tokens, 0.0, self.name)

        # 保留前 60% 和后 20%，中间用省略号
        keep_head = int(len(lines) * 0.6)
        keep_tail = int(len(lines) * 0.2)
        head = lines[:keep_head]
        tail = lines[-keep_tail:] if keep_tail > 0 else []
        compressed = "\n".join(head) + f"\n... [省略 {len(lines)-keep_head-keep_tail} 行] ...\n" + "\n".join(tail)
        new_tokens = len(compressed) // 4
        return CompressResult(
            compressed, orig_tokens, new_tokens,
            1 - new_tokens / max(orig_tokens, 1), self.name
        )


class ClawCompactorAdapter:
    """claw-compactor: 14 阶段 AST 感知压缩（15-82%）"""
    name = "claw-compactor"

    def __init__(self):
        from claw_compactor import Compactor
        self._c = Compactor()

    def compress(self, text: str, max_tokens: int = 2000) -> CompressResult:
        orig = len(text) // 4
        result = self._c.compress(text, target_tokens=max_tokens)
        new = len(result) // 4
        return CompressResult(result, orig, new, 1 - new / max(orig, 1), self.name)


class DistillAdapter:
    """Distill MCP: 源头压缩（最高 98%）"""
    name = "distill-mcp"

    def __init__(self):
        from distill_mcp import DistillServer
        self._s = DistillServer()

    def compress(self, text: str, max_tokens: int = 2000) -> CompressResult:
        orig = len(text) // 4
        result = self._s.compress(text, budget=max_tokens)
        new = len(result) // 4
        return CompressResult(result, orig, new, 1 - new / max(orig, 1), self.name)


class CRUXAdapter:
    """CRUX: 11 层优化管道（含读缓存 + 差异响应）"""
    name = "crx"

    def __init__(self):
        from crx_engine import CRUXPipeline
        self._p = CRUXPipeline()

    def compress(self, text: str, max_tokens: int = 2000) -> CompressResult:
        orig = len(text) // 4
        result = self._p.process(text, max_tokens=max_tokens)
        new = len(result) // 4
        return CompressResult(result, orig, new, 1 - new / max(orig, 1), self.name)


class TokenReducerAdapter:
    """TokenReducer: RAG + AST 混合分块（90-98%）"""
    name = "token-reducer"

    def __init__(self):
        from token_reducer import HybridReducer
        self._r = HybridReducer()

    def compress(self, text: str, max_tokens: int = 2000) -> CompressResult:
        orig = len(text) // 4
        chunks = self._r.chunk_and_reduce(text, target=max_tokens)
        result = "\n".join(chunks)
        new = len(result) // 4
        return CompressResult(result, orig, new, 1 - new / max(orig, 1), self.name)


class ContextCoreAdapter:
    """ContextCore: GPU 加速上下文压缩（60-95%）"""
    name = "contextcore"

    def __init__(self):
        from contextcore import GPUCompressor
        self._g = GPUCompressor()

    def compress(self, text: str, max_tokens: int = 2000) -> CompressResult:
        orig = len(text) // 4
        result = self._g.compress(text, budget=max_tokens)
        new = len(result) // 4
        return CompressResult(result, orig, new, 1 - new / max(orig, 1), self.name)


def get_compressor(prefer: str = "auto") -> 'CompressorWrapper':
    """
    自动选择最优压缩器。
    prefer: "auto" | "claw" | "distill" | "crx" | "reducer" | "contextcore" | "builtin"
    """
    adapters = [
        ("contextcore", ContextCoreAdapter, 0.95),
        ("distill", DistillAdapter, 0.98),
        ("reducer", TokenReducerAdapter, 0.90),
        ("crx", CRUXAdapter, 0.82),
        ("claw", ClawCompactorAdapter, 0.82),
    ]

    if prefer != "auto":
        # 用户指定了
        for name, cls, _ in adapters:
            if name == prefer:
                try:
                    return CompressorWrapper(cls(), available=True)
                except Exception as e:
                    log.warning(f"⚠️ {name} 加载失败: {e}，降级到内置")
                    return CompressorWrapper(BuiltinCompressor(), available=False)
        # 没找到匹配，走 auto

    # Auto: 按压缩率排序，选第一个能用的
    for name, cls, ratio in sorted(adapters, key=lambda x: -x[2]):
        try:
            return CompressorWrapper(cls(), available=True)
        except Exception:
            continue

    # 全都失败了，用内置
    return CompressorWrapper(BuiltinCompressor(), available=False)


class CompressorWrapper:
    """包装器：统一接口 + 降级保护"""

    def __init__(self, compressor, available: bool = True):
        self._c = compressor
        self.method = compressor.name
        self.available = available

    def compress(self, text: str, max_tokens: int = 2000) -> CompressResult:
        try:
            return self._c.compress(text, max_tokens)
        except Exception as e:
            log.error(f"❌ 压缩器 {self.method} 失败: {e}，降级到内置截断")
            fallback = BuiltinCompressor()
            return fallback.compress(text, max_tokens)

    def stats(self) -> dict:
        return {
            "method": self.method,
            "available": self.available,
            "note": "装了外部库自动启用，没装用内置方案" if not self.available else "",
        }


# ════════════════════════════════════════════════════════
# 2. 代码质量检查（5 种工具 + 内置降级）
# ════════════════════════════════════════════════════════

class BuiltinQualityChecker:
    """内置质量检查（基于 work.py 的 InstinctGuard）"""
    name = "builtin-ast"

    def __init__(self):
        from . import work
        self._guard = work.InstinctGuard()

    def check(self, code: str) -> QualityResult:
        results = self._guard.check_all(code)
        passed = all(r.passed for r in results)
        score = sum(1 for r in results if r.passed) / max(len(results), 1) * 100
        issues = [
            {"rule": r.rule, "message": r.message, "action": r.action}
            for r in results if not r.passed
        ]
        return QualityResult(passed, round(score, 1), issues, self.name)


class AISlopDetectorAdapter:
    """AI-SLOP Detector: 检测 AI 生成的空壳/误导代码"""
    name = "ai-slop-detector"

    def __init__(self):
        from ai_slop_detector import Detector
        self._d = Detector()

    def check(self, code: str) -> QualityResult:
        result = self._d.analyze(code)
        return QualityResult(
            result.passed, result.score,
            [{"rule": i.name, "message": i.msg} for i in result.issues],
            self.name
        )


class PyqualAdapter:
    """pyqual: YAML 配置质量阈值，不合格自动迭代"""
    name = "pyqual"

    def __init__(self, config_path: str = ""):
        from pyqual import QualChecker
        self._q = QualChecker(config=config_path or None)

    def check(self, code: str) -> QualityResult:
        result = self._q.check(code)
        return QualityResult(
            result.passed, result.score * 100,
            [{"rule": k, "message": v} for k, v in result.failures.items()],
            self.name
        )


class CodeTrustAdapter:
    """CodeTrust: 本地 CLI，确定性检查幻觉与质量"""
    name = "codetrust"

    def __init__(self):
        from codetrust import TrustChecker
        self._t = TrustChecker()

    def check(self, code: str) -> QualityResult:
        result = self._t.verify(code)
        return QualityResult(
            result.trust_score > 0.7, result.trust_score * 100,
            result.issues, self.name
        )


class KISSAdapter:
    """kiss: 反馈代码复杂度、重复度"""
    name = "kiss"

    def __init__(self):
        from kiss_metrics import KISSAnalyzer
        self._k = KISSAnalyzer()

    def check(self, code: str) -> QualityResult:
        result = self._k.analyze(code)
        score = max(0, 100 - result.cyclomatic_complexity * 5 - result.duplication_rate * 20)
        issues = []
        if result.cyclomatic_complexity > 10:
            issues.append({"rule": "complexity", "message": f"圈复杂度={result.cyclomatic_complexity}，建议拆分"})
        if result.duplication_rate > 0.3:
            issues.append({"rule": "duplication", "message": f"重复率={result.duplication_rate:.0%}"})
        return QualityResult(score > 60, round(score, 1), issues, self.name)


class CodeArbiterAdapter:
    """code-arbiter: 沙箱运行 + 真实测试套件验证"""
    name = "code-arbiter"

    def __init__(self):
        from code_arbiter import Arbiter
        self._a = Arbiter(sandbox=True)

    def check(self, code: str) -> QualityResult:
        result = self._a.run_and_verify(code)
        return QualityResult(
            result.passed, result.score * 100,
            result.failures, self.name
        )


def get_quality_checker(prefer: str = "auto") -> 'QualityCheckerWrapper':
    """
    自动选择最优质量检查器。
    prefer: "auto" | "slop" | "pyqual" | "trust" | "kiss" | "arbiter" | "builtin"
    """
    checkers = [
        ("arbiter", CodeArbiterAdapter),
        ("trust", CodeTrustAdapter),
        ("slop", AISlopDetectorAdapter),
        ("kiss", KISSAdapter),
        ("pyqual", PyqualAdapter),
    ]

    if prefer != "auto":
        for name, cls in checkers:
            if name == prefer:
                try:
                    return QualityCheckerWrapper(cls(), available=True)
                except Exception as e:
                    log.warning(f"⚠️ {name} 加载失败: {e}，降级到内置")
                    return QualityCheckerWrapper(BuiltinQualityChecker(), available=False)

    for name, cls in checkers:
        try:
            return QualityCheckerWrapper(cls(), available=True)
        except Exception:
            continue

    return QualityCheckerWrapper(BuiltinQualityChecker(), available=False)


class QualityCheckerWrapper:
    """包装器：统一接口 + 降级保护"""

    def __init__(self, checker, available: bool = True):
        self._c = checker
        self.method = checker.name
        self.available = available

    def check(self, code: str) -> QualityResult:
        try:
            return self._c.check(code)
        except Exception as e:
            log.error(f"❌ 质量检查器 {self.method} 失败: {e}，降级到内置 AST")
            fallback = BuiltinQualityChecker()
            return fallback.check(code)

    def stats(self) -> dict:
        return {
            "method": self.method,
            "available": self.available,
            "note": "装了外部库自动启用，没装用内置 AST" if not self.available else "",
        }


# ════════════════════════════════════════════════════════
# 3. 意图路由（SkillTree / openclaw）
# ════════════════════════════════════════════════════════

class BuiltinIntentRouter:
    """内置意图路由（基于 gateway.py 的 IntentEngine）"""
    name = "builtin-keyword"

    def __init__(self):
        from .gateway import IntentEngine
        self._ie = IntentEngine()

    def route(self, user_input: str) -> dict:
        return self._ie.classify(user_input)


class SkillTreeAdapter:
    """SkillTree: 将 Skill 构建为路由树，按意图按需加载"""
    name = "skilltree"

    def __init__(self):
        from skilltree_router import SkillTree
        self._st = SkillTree()

    def route(self, user_input: str) -> dict:
        result = self._st.match(user_input)
        return {
            "category": result.category,
            "confidence": result.confidence,
            "tags": result.tags,
            "method": self.name,
        }


class OpenClawIntentAdapter:
    """openclaw-intent-router: 分析意图并匹配最合适的 Skill"""
    name = "openclaw"

    def __init__(self):
        from openclaw_intent import IntentRouter
        self._r = IntentRouter()

    def route(self, user_input: str) -> dict:
        result = self._r.route(user_input)
        return {
            "category": result.intent,
            "confidence": result.score,
            "tags": result.skills,
            "method": self.name,
        }


def get_intent_router(prefer: str = "auto"):
    """自动选择意图路由器"""
    routers = [
        ("openclaw", OpenClawIntentAdapter),
        ("skilltree", SkillTreeAdapter),
    ]

    if prefer != "auto":
        for name, cls in routers:
            if name == prefer:
                try:
                    return _RouterWrapper(cls(), True)
                except Exception:
                    return _RouterWrapper(BuiltinIntentRouter(), False)

    for name, cls in routers:
        try:
            return _RouterWrapper(cls(), True)
        except Exception:
            continue

    return _RouterWrapper(BuiltinIntentRouter(), False)


class _RouterWrapper:
    def __init__(self, router, available: bool):
        self._r = router
        self.method = router.name
        self.available = available

    def route(self, text: str) -> dict:
        try:
            return self._r.route(text)
        except Exception as e:
            log.error(f"❌ 意图路由 {self.method} 失败: {e}")
            fallback = BuiltinIntentRouter()
            return fallback.route(text)


# ════════════════════════════════════════════════════════
# 4. 综合网关（Tokenless / rtk / ClawVault / tokencap）
# ════════════════════════════════════════════════════════

class BuiltinGateway:
    """内置网关（基于 gateway.py 的 WordGateway）"""
    name = "builtin-gateway"

    def __init__(self, config: dict | None = None):
        from .gateway import WordGateway
        self._gw = WordGateway(config or {})

    def handle(self, user_input: str) -> dict:
        result = self._gw.handle(user_input)
        return {
            "output": result.model_output,
            "guard": result.guard_summary,
            "retries": result.retries,
            "action": result.final_action,
            "skills": result.skills_used,
        }


class TokenlessAdapter:
    """Tokenless: 综合方案（Schema 压缩 57%、响应压缩 26-78%）"""
    name = "tokenless"

    def __init__(self):
        from tokenless_engine import TokenlessEngine
        self._t = TokenlessEngine()

    def handle(self, user_input: str) -> dict:
        result = self._t.process(user_input)
        return {
            "output": result.response,
            "schema_compression": result.schema_ratio,
            "response_compression": result.response_ratio,
            "action": "pass" if result.success else "block",
        }


class RTKAdapter:
    """rtk: CLI 代理，过滤压缩命令输出（节省 60-90%）"""
    name = "rtk-cli"

    def __init__(self):
        from rtk_cli import RTKProxy
        self._r = RTKProxy()

    def filter_command(self, cmd: str, output: str) -> str:
        return self._r.filter(cmd, output)


class ClawVaultAdapter:
    """ClawVault: 企业级 AI 安全网关 + Token 预算管控"""
    name = "clawvault"

    def __init__(self):
        from clawvault_gateway import VaultGateway
        self._v = VaultGateway()

    def check_budget(self, user: str, tokens: int) -> bool:
        return self._v.check_token_budget(user, tokens)

    def enforce(self, user: str, tokens: int) -> dict:
        return self._v.enforce(user, tokens)


class TokenCapAdapter:
    """tokencap: Python 库，追踪用量并强制执行预算"""
    name = "tokencap"

    def __init__(self, budget: int = 100000):
        from tokencap import TokenBudget
        self._tb = TokenBudget(daily_budget=budget)

    def consume(self, tokens: int) -> bool:
        return self._tb.consume(tokens)

    def remaining(self) -> int:
        return self._tb.remaining()

    def stats(self) -> dict:
        return self._tb.stats()


def get_gateway(prefer: str = "auto"):
    """自动选择网关"""
    gateways = [
        ("tokenless", TokenlessAdapter),
        ("clawvault", ClawVaultAdapter),
    ]
    if prefer != "auto":
        for name, cls in gateways:
            if name == prefer:
                try:
                    return _GatewayWrapper(cls(), True)
                except Exception:
                    return _GatewayWrapper(BuiltinGateway(), False)
    for name, cls in gateways:
        try:
            return _GatewayWrapper(cls(), True)
        except Exception:
            continue
    return _GatewayWrapper(BuiltinGateway(), False)


class _GatewayWrapper:
    def __init__(self, gw, available: bool):
        self._g = gw
        self.method = gw.name
        self.available = available

    def handle(self, text: str) -> dict:
        try:
            return self._g.handle(text)
        except Exception as e:
            log.error(f"❌ 网关 {self.method} 失败: {e}")
            fallback = BuiltinGateway()
            return fallback.handle(text)


# ════════════════════════════════════════════════════════
# 5. 代码库结构化（reducethemtokens）
# ════════════════════════════════════════════════════════

class BuiltinSkeletonizer:
    """内置代码库骨架提取（基于 AST，缩小 90%+）"""
    name = "builtin-ast-skeleton"

    def __init__(self):
        import ast as ast_mod
        self._ast = ast_mod

    def skeletonize(self, code: str) -> str:
        """提取代码骨架：只保留函数签名 + 类定义 + import"""
        try:
            tree = self._ast.parse(code)
        except SyntaxError:
            return code  # 解析失败，返回原文

        lines = []
        for node in tree.body:
            if isinstance(node, self._ast.Import):
                lines.append(f"import {', '.join(n.name for n in node.names)}")
            elif isinstance(node, self._ast.ImportFrom):
                names = ', '.join(n.name for n in node.names)
                lines.append(f"from {node.module} import {names}")
            elif isinstance(node, self._ast.FunctionDef):
                args = ', '.join(a.arg for a in node.args.args)
                ret = f" -> {node.returns.id}" if node.returns else ""
                lines.append(f"def {node.name}({args}){ret}: ...")
            elif isinstance(node, self._ast.ClassDef):
                bases = ', '.join(b.id for b in node.bases if hasattr(b, 'id'))
                lines.append(f"class {node.name}({bases}):")
                for item in node.body:
                    if isinstance(item, self._ast.FunctionDef):
                        args = ', '.join(a.arg for a in item.args.args)
                        lines.append(f"    def {item.name}({args}): ...")
        return "\n".join(lines)


class ReduceThemTokensAdapter:
    """reducethemtokens: 将代码库提取为紧凑骨架（缩小 90%+）"""
    name = "reducethemtokens"

    def __init__(self):
        from reducethemtokens import SkeletonExtractor
        self._r = SkeletonExtractor()

    def skeletonize(self, code: str) -> str:
        return self._r.extract(code)


def get_skeletonizer(prefer: str = "auto"):
    """自动选择骨架提取器"""
    extractors = [("reducethemtokens", ReduceThemTokensAdapter)]
    if prefer != "auto":
        for name, cls in extractors:
            if name == prefer:
                try:
                    return _SkeletonizerWrapper(cls(), True)
                except Exception:
                    return _SkeletonizerWrapper(BuiltinSkeletonizer(), False)
    for name, cls in extractors:
        try:
            return _SkeletonizerWrapper(cls(), True)
        except Exception:
            continue
    return _SkeletonizerWrapper(BuiltinSkeletonizer(), False)


class _SkeletonizerWrapper:
    def __init__(self, s, available: bool):
        self._s = s
        self.method = s.name
        self.available = available

    def skeletonize(self, code: str) -> str:
        try:
            return self._s.skeletonize(code)
        except Exception as e:
            log.error(f"❌ 骨架提取 {self.method} 失败: {e}")
            fallback = BuiltinSkeletonizer()
            return fallback.skeletonize(code)


# ════════════════════════════════════════════════════════
# 统一入口：EnhancementHub
# ════════════════════════════════════════════════════════

class EnhancementHub:
    """
    统一增强中心 —— 一行代码接入所有外部工具。

    用法：
        from Toolkit.enhancements import EnhancementHub

        hub = EnhancementHub()
        hub.stats()  # 看哪些工具可用

        # 压缩上下文
        result = hub.compress(huge_text)
        print(f"压缩率: {result.ratio:.0%}")

        # 检查代码质量
        q = hub.check_quality(code)
        print(f"质量分: {q.score}")

        # 意图路由
        route = hub.route("帮我写 Python 登录接口")
        print(f"分类: {route['category']}")

        # 代码库骨架
        skeleton = hub.skeletonize(full_codebase)
    """

    def __init__(self, config: dict | None = None):
        config = config or {}
        self._compressor = get_compressor(config.get("prefer_compressor", "auto"))
        self._quality = get_quality_checker(config.get("prefer_quality", "auto"))
        self._router = get_intent_router(config.get("prefer_router", "auto"))
        self._gateway = get_gateway(config.get("prefer_gateway", "auto"))
        self._skeletonizer = get_skeletonizer(config.get("prefer_skeleton", "auto"))

    def compress(self, text: str, max_tokens: int = 2000) -> CompressResult:
        return self._compressor.compress(text, max_tokens)

    def check_quality(self, code: str) -> QualityResult:
        return self._quality.check(code)

    def route(self, user_input: str) -> dict:
        return self._router.route(user_input)

    def handle(self, user_input: str) -> dict:
        return self._gateway.handle(user_input)

    def skeletonize(self, code: str) -> str:
        return self._skeletonizer.skeletonize(code)

    def stats(self) -> dict:
        return {
            "compressor": self._compressor.stats(),
            "quality_checker": self._quality.stats(),
            "intent_router": {"method": self._router.method, "available": self._router.available},
            "gateway": {"method": self._gateway.method, "available": self._gateway.available},
            "skeletonizer": {"method": self._skeletonizer.method, "available": self._skeletonizer.available},
        }


# ════════════════════════════════════════════════════════
# 便捷函数
# ════════════════════════════════════════════════════════

def enhance(config: dict | None = None) -> EnhancementHub:
    """一行创建增强中心"""
    return EnhancementHub(config or {})


if __name__ == "__main__":
    # 自检
    hub = EnhancementHub()
    print("╔══════════════════════════════════════════╗")
    print("║     🔌 EnhancementHub 外部工具集成状态     ║")
    print("╚══════════════════════════════════════════╝\n")

    stats = hub.stats()
    for name, info in stats.items():
        status = "✅" if info.get("available") else "⚠️ (用内置)"
        method = info.get("method", "?")
        note = info.get("note", "")
        print(f"  {status} {name:20s} → {method:25s} {note}")

    print("\n📊 测试压缩:")
    test = "def hello():\n    print('world')\n" * 100
    result = hub.compress(test, max_tokens=50)
    print(f"  原始: ~{result.original_tokens} tokens")
    print(f"  压缩后: ~{result.compressed_tokens} tokens")
    print(f"  压缩率: {result.ratio:.0%}")
    print(f"  方法: {result.method}")
