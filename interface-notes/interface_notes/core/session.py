"""
会话管理 — 维护项目级状态、接口列表、调用关系图
"""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

from .types import Interface, RiskLevel, Mode


class Session:
    """
    项目会话：管理所有接口记录、调用关系、会话状态。

    内部以 qualified_name（module_path.name）作为唯一键，
    避免同名函数在跨文件调用解析时互相串扰。
    """

    def __init__(self, project_name: str, mode: Mode = Mode.A_INCREMENTAL):
        self.project_name = project_name
        self.mode = mode
        self.created_at = datetime.now().strftime("%Y-%m-%d %H:%M")
        self.last_exported: Optional[str] = None
        self.version: int = 1
        # 内部存储键：qualified_name
        self._interfaces: dict[str, Interface] = {}
        # 兼容旧数据 / 短名快速查找（name → qualified_name）
        self._name_index: dict[str, str] = {}
        self._asked_interfaces: set[str] = set()
        self.stats = {
            "total_files_scanned": 0,
            "total_interfaces_found": 0,
            "total_exported": 0,
            "token_estimate": 0,
            "scan_truncated": False,       # 是否因 max_files 截断
            "max_files_limit": 0,
        }

    # ──────────────────────────────────────
    # 内部工具
    # ──────────────────────────────────────

    def _key(self, iface: Interface) -> str:
        """获取接口的唯一键"""
        return iface.qualified_name

    def _register_name(self, iface: Interface):
        """维护短名 → qualified_name 索引（用于向后兼容查找）"""
        # 如果短名已存在且指向不同接口，说明有同名 → 不覆盖
        existing = self._name_index.get(iface.name)
        if existing is None or existing == iface.qualified_name:
            self._name_index[iface.name] = iface.qualified_name

    # ──────────────────────────────────────
    # 接口 CRUD
    # ──────────────────────────────────────

    def add_interface(self, interface: Interface) -> bool:
        """
        添加/更新接口。返回 True 表示新增，False 表示更新已有。
        """
        key = self._key(interface)

        if key in self._interfaces:
            # 更新已有（保留手写 notes 和更高风险等级）
            existing = self._interfaces[key]
            old_notes = existing.notes
            old_risk = existing.risk_level
            self._interfaces[key] = interface
            if old_notes and not interface.notes:
                interface.notes = old_notes
            if old_risk.value > interface.risk_level.value:
                interface.risk_level = old_risk
            interface.confirmed = existing.confirmed
            interface.skipped = existing.skipped
            return False
        else:
            self._interfaces[key] = interface
            self._register_name(interface)
            self.stats["total_interfaces_found"] += 1
            return True

    def get_interface(self, name: str) -> Optional[Interface]:
        """按短名或 qualified_name 查找接口"""
        # 先试 qualified_name
        if name in self._interfaces:
            return self._interfaces[name]
        # 再试短名索引
        qn = self._name_index.get(name)
        if qn:
            return self._interfaces.get(qn)
        return None

    def remove_interface(self, name: str) -> bool:
        if name in self._interfaces:
            iface = self._interfaces[name]
            del self._interfaces[name]
            # 清理索引
            if self._name_index.get(iface.name) == name:
                del self._name_index[iface.name]
            return True
        # 试短名
        qn = self._name_index.get(name)
        if qn and qn in self._interfaces:
            del self._interfaces[qn]
            del self._name_index[name]
            return True
        return False

    def confirm_interface(self, name: str):
        iface = self.get_interface(name)
        if iface:
            iface.confirmed = True
            iface.skipped = False
        self._asked_interfaces.add(name)

    def skip_interface(self, name: str):
        iface = self.get_interface(name)
        if iface:
            iface.skipped = True
        self._asked_interfaces.add(name)

    def should_ask_about(self, name: str) -> bool:
        return name not in self._asked_interfaces

    def list_pending(self) -> list[Interface]:
        return [i for i in self._interfaces.values() if i.should_ask()]

    def list_confirmed(self) -> list[Interface]:
        return [i for i in self._interfaces.values() if i.confirmed]

    # 属性代理：让外部代码 `session.interfaces` 仍然可用
    @property
    def interfaces(self) -> dict[str, Interface]:
        """
        对外暴露的接口字典。
        键优先用 qualified_name；若两个接口同名（不同模块），
        短名会带后缀以消歧。
        """
        result = {}
        for qn, iface in self._interfaces.items():
            # 如果有同名不同模块的接口，短名加模块前缀
            same_short = [k for k in self._interfaces if self._interfaces[k].name == iface.name]
            if len(same_short) > 1:
                result[qn] = iface
            else:
                result[iface.name] = iface
        return result

    # ──────────────────────────────────────
    # 调用关系管理（基于 qualified_name）
    # ──────────────────────────────────────

    def add_call_relation(self, caller: str, callee: str):
        """记录 A 调用 B 的关系（caller/callee 可为短名或 qualified_name）"""
        caller_iface = self.get_interface(caller)
        callee_iface = self.get_interface(callee)
        if caller_iface and callee_iface:
            cq = callee_iface.qualified_name
            if cq not in caller_iface.dependencies:
                caller_iface.dependencies.append(cq)
            rq = caller_iface.qualified_name
            if rq not in callee_iface.called_by:
                callee_iface.called_by.append(rq)

    def get_call_graph(self) -> dict[str, list[str]]:
        """获取完整调用图 {caller_qn: [callee_qns]}"""
        graph = {}
        for qn, iface in self._interfaces.items():
            if iface.dependencies:
                graph[qn] = list(iface.dependencies)
        return graph

    # ──────────────────────────────────────
    # 序列化 / 持久化
    # ──────────────────────────────────────

    def to_dict(self) -> dict:
        return {
            "project_name": self.project_name,
            "mode": self.mode.value,
            "created_at": self.created_at,
            "last_exported": self.last_exported,
            "version": self.version,
            "stats": self.stats,
            "interfaces": {
                qn: iface.to_dict()
                for qn, iface in self._interfaces.items()
            },
        }

    def save(self, path: str):
        data = self.to_dict()
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    @classmethod
    def load(cls, path: str) -> "Session":
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        session = cls(
            project_name=data["project_name"],
            mode=Mode(data.get("mode", "mode-a")),
        )
        session.created_at = data.get("created_at", "")
        session.last_exported = data.get("last_exported")
        session.version = data.get("version", 1)
        session.stats = data.get("stats", session.stats)
        for qn, iface_data in data.get("interfaces", {}).items():
            iface = Interface.from_dict(iface_data)
            # 如果加载的数据没有 module_path，qualified_name 会退化为短名
            session._interfaces[qn] = iface
            session._register_name(iface)
        return session

    def bump_version(self):
        self.version += 1

    # ──────────────────────────────────────
    # 统计
    # ──────────────────────────────────────

    def summary(self) -> str:
        lines = [
            f"📋 项目：{self.project_name}",
            f"   模式：{'模式A（增量）' if self.mode == Mode.A_INCREMENTAL else '模式B（全量扫描）'}",
            f"   接口总数：{len(self._interfaces)}",
            f"   已确认：{len(self.list_confirmed())}",
            f"   待确认：{len(self.list_pending())}",
            f"   版本：v{self.version}",
            f"   扫描文件数：{self.stats['total_files_scanned']}",
        ]
        if self.stats.get("scan_truncated"):
            lines.append(
                f"   ⚠️ 扫描因 max_files={self.stats['max_files_limit']} 被截断，"
                f"可能漏扫！请用 --max-files 提高上限。"
            )
        return "\n".join(lines)
