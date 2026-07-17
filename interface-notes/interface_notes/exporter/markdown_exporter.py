"""
Markdown 导出器

对应设计文档 Phase 2.2：导出格式（留白充足，方便打印手写）
"""

from datetime import datetime
from typing import Optional

from ..core.session import Session
from ..core.types import Interface, Mode
from .diagram import generate_mermaid, generate_legend


def export_markdown(
    session: Session,
    include_disclaimer: bool = False,
    disclaimer_strength: str = "strong",  # strong / weak / none
    include_diagram: bool = True,
) -> str:
    """
    将 session 导出为 Markdown 格式的接口笔记。

    对应设计文档 Phase 2.2 的导出格式规范。
    """
    lines: list[str] = []

    # ── 标题 ──
    lines.append(f"# 接口笔记 — {session.project_name}")
    lines.append("")

    # ── 免责声明（模式B v1 必须加） ──
    if include_disclaimer and disclaimer_strength == "strong":
        lines.append("> **⚠️ 该内容由 AI 全量扫描生成，请仔细甄别。**")
        lines.append("> **AI 可能误判接口边界、调用关系或参数含义。**")
        lines.append("> **请打印后在手写区修正，拍照回流后生成更精准的 v2 版。**")
        lines.append(">")
        lines.append(f"> 扫描时间：{session.created_at}")
        lines.append(f"> 扫描文件数：{session.stats.get('total_files_scanned', '?')}")
        lines.append(f"> 接口数量：{len(session.interfaces)}")
        lines.append(f"> AI 置信度：中等（待人工校验）")
        lines.append("")
        lines.append("---")
        lines.append("")

    elif include_disclaimer and disclaimer_strength == "weak":
        lines.append("> *ℹ️ 本文档已通过人工校验（v2+），如有疑问请联系维护者。*")
        lines.append("")

    # ── 元信息 ──
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines.append(f"> 生成时间：{now}")
    lines.append(f"> 接口总数：{len(session.interfaces)}")
    lines.append(f"> 版本：v{session.version}")
    gen_method = "AI全量扫描" if session.mode == Mode.B_FULLSCAN else "AI增量记录"
    if any(i.notes for i in session.interfaces.values()):
        gen_method += " + 用户手写批注"
    lines.append(f"> 生成方式：{gen_method}")
    lines.append("")

    # ── 各接口详情 ──
    for name, iface in sorted(session.interfaces.items()):
        lines.extend(_render_interface(iface))
        lines.append("")
        lines.append("---")
        lines.append("")

    # ── Mermaid 关系图 ──
    if include_diagram and session.interfaces:
        lines.append("## 📊 接口关系图")
        lines.append("")
        lines.append("```mermaid")
        lines.append(generate_mermaid(session))
        lines.append("```")
        lines.append("")
        lines.append(generate_legend())
        lines.append("")

    # ── 底部弱化提示（v2+） ──
    if disclaimer_strength == "weak":
        lines.append("---")
        lines.append("")
        lines.append("> *本文档由 AI 辅助生成并经人工校验，如有错误请联系维护者。*")

    return "\n".join(lines)


def _render_interface(iface: Interface) -> list[str]:
    """渲染单个接口的 Markdown 片段"""
    lines: list[str] = []

    # 标题
    risk_emoji = iface.risk_level.emoji
    lines.append(f"## {iface.name} {risk_emoji}")

    # 功能
    lines.append(f"- **功能**：{iface.description or '（未填写）'}")

    # 参数
    if iface.params:
        lines.append("- **参数**：")
        for pname, pdesc in iface.params.items():
            lines.append(f"  - `{pname}` ({pdesc})")
    else:
        lines.append("- **参数**：（无）")

    # 返回值
    lines.append(f"- **返回**：{iface.returns or '（未确定）'}")

    # 位置
    if iface.location:
        lines.append(f"- **位置**：`{iface.location}`")

    # 调用关系
    if iface.dependencies:
        deps = ", ".join(f"`{d}`" for d in iface.dependencies)
        lines.append(f"- **调用了**：{deps}")
    else:
        lines.append("- **调用了**：（无）")

    if iface.called_by:
        callers = ", ".join(f"`{c}`" for c in iface.called_by)
        lines.append(f"- **被调用**：{callers}")

    # 风险
    risk_text = f"{iface.risk_level.emoji} {iface.risk_level.label}"
    if iface.suspicious:
        risk_text += f"（{iface.suspicious}）"
    lines.append(f"- **风险**：{risk_text}")

    # 手写区（留白充足，方便打印）
    lines.append("")
    lines.append("> 📝 手写区（打印后在此写你的理解/踩坑经验）：")
    lines.append(">")
    # 已有手写批注则显示
    if iface.notes:
        for note_line in iface.notes.split("\n"):
            lines.append(f"> {note_line}")
        lines.append(">")
    # 空白行供手写
    lines.append("> _______________________________________________________")
    lines.append(">")
    lines.append("> _______________________________________________________")
    lines.append(">")
    lines.append("> _______________________________________________________")

    return lines


def export_json(session: Session) -> str:
    """导出为 JSON 格式"""
    import json
    return json.dumps(session.to_dict(), ensure_ascii=False, indent=2)


def export_text(session: Session) -> str:
    """导出为纯文本格式（简化版）"""
    lines = [f"接口笔记 — {session.project_name}", "=" * 50, ""]
    for name, iface in sorted(session.interfaces.items()):
        lines.append(f"[{iface.risk_level.emoji}] {name}")
        lines.append(f"  功能: {iface.description}")
        if iface.params:
            params_str = ", ".join(f"{k}: {v}" for k, v in iface.params.items())
            lines.append(f"  参数: {params_str}")
        lines.append(f"  返回: {iface.returns}")
        lines.append(f"  位置: {iface.location}")
        if iface.dependencies:
            lines.append(f"  调用: {', '.join(iface.dependencies)}")
        if iface.notes:
            lines.append(f"  批注: {iface.notes}")
        lines.append("")
    return "\n".join(lines)
