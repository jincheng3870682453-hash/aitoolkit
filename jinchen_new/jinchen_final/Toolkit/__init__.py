"""Toolkit — Word 体系 V3.1（诚实版）

模块分工：
  work.py          → 行为约束（Python=AST / 其他=正则）
  guardian.py      → 快照回滚 + 审计日志
  Archive.py       → 长对话记忆（SimHash）
  shiyun.py       → 硬核叙事工厂
  Nuwa.py         → POC 报告 + 辐射检测
  gateway.py       → 统一网关（意图→Skill→模型→守门→存储）
  Proteus.py      → 交互启动入口
"""
from . import work, guardian, Archive, shiyun, Nuwa as NuwaModule, gateway, Proteus
from .work import (
    InstinctGuard, GuardResult,
    MultiLangASTEngine, LangDetector,
)
from .guardian import Guardian, RollbackJury, Verdict, ensure_gitignore
from .Archive import Archive
from .shiyun import Shiyun
from .Nuwa import Nuwa, RadiationDetector, RadAlert
from .gateway import (
    WordGateway, IntentEngine,
    SkillRecommender, Skill,
    FineTunedCore, PolicyEngine,
    FeedbackStore, GatewayResult, V1Bridge, ModelCallError,
)

__all__ = [
    "work", "guardian", "Archive", "shiyun", "NuwaModule", "gateway", "Proteus",
    "InstinctGuard", "GuardResult",
    "MultiLangASTEngine", "LangDetector",
    "Guardian", "RollbackJury", "Verdict", "ensure_gitignore",
    "Archive", "Shiyun", "Nuwa",
    "RadiationDetector", "RadAlert",
    "WordGateway", "IntentEngine",
    "SkillRecommender", "Skill",
    "FineTunedCore", "PolicyEngine",
    "FeedbackStore", "GatewayResult", "V1Bridge", "ModelCallError",
]
