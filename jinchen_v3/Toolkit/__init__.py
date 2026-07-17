"""
Toolkit —— jinchen 核心工具集

对外接口：
    from Toolkit import work        # check(code) → Report
    from Toolkit import guardian   # Guardian, RollbackJury, safe_call
    from Toolkit import Archive    # Archive, simhash, should_switch_topic
    from Toolkit import Nuwa       # Nuwa, RadiationDetector
    from Toolkit import gateway    # WordGateway, ModelCaller, SkillRegistry
    from Toolkit import shiyun     # 叙事工厂
    from Toolkit import Proteus    # 交互入口

版本：3.2
"""

__version__ = "3.2"

from . import work, guardian, Archive, Nuwa, gateway, shiyun, Proteus

__all__ = ["work", "guardian", "Archive", "Nuwa", "gateway", "shiyun", "Proteus", "__version__"]
