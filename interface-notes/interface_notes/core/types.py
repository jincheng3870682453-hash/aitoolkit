"""
类型定义与枚举
"""

from enum import Enum
from dataclasses import dataclass, field
from typing import Any


class RiskLevel(str, Enum):
    """接口风险等级"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"

    @property
    def emoji(self) -> str:
        return {"low": "🟢", "medium": "🟡", "high": "🔴"}[self.value]

    @property
    def color(self) -> str:
        return {"low": "#238636", "medium": "#d29922", "high": "#f85149"}[self.value]

    @property
    def label(self) -> str:
        return {"low": "低", "medium": "中", "high": "高"}[self.value]


class Mode(str, Enum):
    """工作模式"""
    A_INCREMENTAL = "mode-a"       # 共同开发（增量）
    B_FULLSCAN = "mode-b"          # 接手旧项目（全量扫描）


class ExportFormat(str, Enum):
    """导出格式"""
    MARKDOWN = "md"
    TEXT = "txt"
    PDF = "pdf"
    JSON = "json"


@dataclass
class Param:
    """接口参数"""
    name: str
    type_hint: str = ""
    description: str = ""

    def to_dict(self) -> dict:
        return {"name": self.name, "type": self.type_hint, "description": self.description}

    @classmethod
    def from_dict(cls, data: dict) -> "Param":
        return cls(name=data.get("name", ""), type_hint=data.get("type", ""), description=data.get("description", ""))


@dataclass
class Interface:
    """
    单个接口的数据结构（对应设计文档中的 ai_notes.interfaces 条目）
    """
    name: str
    description: str = ""
    params: dict[str, str] = field(default_factory=dict)  # {"param_name": "type - description"}
    returns: str = ""
    location: str = ""           # 文件路径（相对路径）
    module_path: str = ""       # 模块路径（如 utils.email / api.endpoints），用于消歧
    imports: list[str] = field(default_factory=list)  # 该接口所在文件的 import 列表（用于消歧）
    dependencies: list[str] = field(default_factory=list)  # 调用了谁（存储为 "module_path.func_name"）
    called_by: list[str] = field(default_factory=list)      # 被谁调用（同上）
    last_used: str = ""
    risk_level: RiskLevel = RiskLevel.LOW
    notes: str = ""              # 手写批注区
    author: str = "AI自动记录"
    suspicious: str = ""         # 可疑点（模式B用）
    confirmed: bool = False      # 用户是否已确认记录
    skipped: bool = False        # 用户是否拒绝记录

    @property
    def qualified_name(self) -> str:
        """带模块前缀的唯一标识，如 utils.email.send_email"""
        if self.module_path:
            return f"{self.module_path}.{self.name}"
        return self.name

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "params": self.params,
            "returns": self.returns,
            "location": self.location,
            "module_path": self.module_path,
            "imports": self.imports,
            "dependencies": self.dependencies,
            "called_by": self.called_by,
            "last_used": self.last_used,
            "risk_level": self.risk_level.value,
            "notes": self.notes,
            "author": self.author,
            "suspicious": self.suspicious,
            "confirmed": self.confirmed,
            "skipped": self.skipped,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Interface":
        risk_raw = data.get("risk_level", "low")
        try:
            risk = RiskLevel(risk_raw)
        except ValueError:
            risk = RiskLevel.LOW
        return cls(
            name=data["name"],
            description=data.get("description", ""),
            params=data.get("params", {}),
            returns=data.get("returns", ""),
            location=data.get("location", ""),
            module_path=data.get("module_path", ""),
            imports=data.get("imports", []),
            dependencies=data.get("dependencies", []),
            called_by=data.get("called_by", []),
            last_used=data.get("last_used", ""),
            risk_level=risk,
            notes=data.get("notes", ""),
            author=data.get("author", "AI自动记录"),
            suspicious=data.get("suspicious", ""),
            confirmed=data.get("confirmed", False),
            skipped=data.get("skipped", False),
        )

    def add_param(self, name: str, type_hint: str = "", description: str = ""):
        """添加参数"""
        if description:
            self.params[name] = f"{type_hint} - {description}" if type_hint else description
        else:
            self.params[name] = type_hint

    def upgrade_risk(self, new_level: RiskLevel, reason: str = ""):
        """升级风险等级"""
        order = [RiskLevel.LOW, RiskLevel.MEDIUM, RiskLevel.HIGH]
        current_idx = order.index(self.risk_level)
        new_idx = order.index(new_level)
        if new_idx > current_idx:
            self.risk_level = new_level
            if reason:
                self.notes = f"{self.notes}\n[风险升级] {reason}".strip()

    def merge_notes(self, handwritten: str, author: str = "手写批注", date: str = ""):
        """合并手写批注"""
        tag = f"（手写-{author}" + (f"-{date}" if date else "") + "）"
        if self.notes:
            self.notes = f"{self.notes} | {handwritten} {tag}"
        else:
            self.notes = f"{handwritten} {tag}"
        self.author = "AI记录 + 人工批注"

    def should_ask(self) -> bool:
        """是否需要询问用户"""
        return not self.confirmed and not self.skipped
