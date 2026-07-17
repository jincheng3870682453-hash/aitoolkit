"""
Interface Notes — AI 接口笔记工作流引擎

让 AI 自动记接口、画图、吸收手写批注，一本活字典打通项目协作。
"""

__version__ = "1.0.0"
__author__ = "金辰"

from .core.session import Session
from .core.types import Interface, RiskLevel, Mode

__all__ = ["Session", "Interface", "RiskLevel", "Mode"]
