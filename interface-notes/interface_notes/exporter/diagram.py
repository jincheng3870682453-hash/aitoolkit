"""
Mermaid 图表生成器

对应设计文档 Phase 2：自动生成接口关系图
"""

from ..core.session import Session
from ..core.types import RiskLevel, Interface


def generate_mermaid(session: Session) -> str:
    """
    根据 session 中的接口数据生成 Mermaid flowchart。

    规则（来自设计文档 2.3）：
    - 每个接口是一个节点，显示接口名 + 一句话功能
    - 箭头方向：A → B 表示 "A 调用 B"
    - 颜色：low=绿, medium=黄, high=红
    """
    interfaces = list(session.interfaces.values())
    if not interfaces:
        return "flowchart TD\n    A[\"暂无接口数据\"]"

    lines = ["flowchart TD"]

    # 节点定义
    for iface in interfaces:
        node_id = _safe_id(iface.name)
        label = _short_desc(iface.description)
        lines.append(f'    {node_id}["{iface.name}<br/>{label}"]')

    lines.append("")  # 空行分隔

    # 调用关系箭头
    for iface in interfaces:
        caller_id = _safe_id(iface.name)
        for dep in iface.dependencies:
            callee_id = _safe_id(dep)
            if callee_id in [_safe_id(i.name) for i in interfaces]:
                lines.append(f"    {caller_id} -->|调用| {callee_id}")

    lines.append("")  # 空行分隔

    # 样式（颜色）
    for iface in interfaces:
        node_id = _safe_id(iface.name)
        color = iface.risk_level.color
        lines.append(f"    style {node_id} fill:{color},stroke:#fff,color:#fff")

    return "\n".join(lines)


def generate_mermaid_full(session: Session) -> str:
    """生成完整的 Mermaid 代码块（带 ``` 包裹）"""
    diagram = generate_mermaid(session)
    return f"```mermaid\n{diagram}\n```"


def _safe_id(name: str) -> str:
    """将接口名转为 Mermaid 安全的节点 ID"""
    # 替换 . 为 _ (如 Class.method → Class_method)
    safe = name.replace(".", "_").replace("-", "_")
    # 确保以字母开头
    if safe and safe[0].isdigit():
        safe = "n_" + safe
    return safe or "unknown"


def _short_desc(desc: str, max_len: int = 12) -> str:
    """截断描述文字"""
    if not desc:
        return ""
    desc = desc.replace("\n", " ").strip()
    if len(desc) > max_len:
        desc = desc[:max_len] + "..."
    return desc


# ──────────────────────────────────────────────
# 图例说明
# ──────────────────────────────────────────────

def generate_legend() -> str:
    """生成 Mermaid 图例"""
    return (
        "> 🔴 红色 = 高风险 | "
        "🟡 黄色 = 中风险 | "
        "🟢 绿色 = 稳定"
    )
