"""
test_export.py — 测试导出功能（Phase 2）

验证 Markdown 导出、Mermaid 图生成、JSON 导出。
"""

import sys
import os
import tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from interface_notes.core.session import Session
from interface_notes.core.types import Interface, RiskLevel, Mode
from interface_notes.exporter.markdown_exporter import (
    export_markdown, export_json, export_text
)
from interface_notes.exporter.diagram import (
    generate_mermaid, generate_mermaid_full, generate_legend
)


def create_test_session() -> Session:
    """创建带测试数据的 Session"""
    session = Session(project_name="测试项目", mode=Mode.A_INCREMENTAL)

    send_email = Interface(
        name="send_email",
        description="发送邮件通知，支持HTML和纯文本",
        params={"to": "str", "subject": "str", "body": "str"},
        returns="bool - 是否发送成功",
        location="utils/email.py",
        dependencies=["query_database"],
        called_by=["generate_report", "push_notification"],
        last_used="2026-07-17 14:32",
        risk_level=RiskLevel.LOW,
        notes="",
        author="AI自动记录",
    )

    query_db = Interface(
        name="query_database",
        description="查询用户表，返回字典列表",
        params={"table": "str", "condition": "dict"},
        returns="list[dict]",
        location="db/query.py",
        dependencies=[],
        called_by=["send_email", "generate_report"],
        last_used="2026-07-17 14:35",
        risk_level=RiskLevel.MEDIUM,
        notes="⚠️ 超时未设，生产环境卡死过（手写-张三-07/18）| 加 timeout=10",
        author="AI记录 + 人工批注",
        suspicious="未设置超时",
    )

    generate_report = Interface(
        name="generate_report",
        description="生成PDF报告并发送邮件",
        params={"user_id": "int", "report_type": "str"},
        returns="str - PDF文件路径",
        location="reports/generator.py",
        dependencies=["query_database", "send_email"],
        called_by=[],
        last_used="2026-07-17 15:00",
        risk_level=RiskLevel.LOW,
        notes="模板在 templates/report.html",
        author="AI记录 + 人工批注",
    )

    push_notif = Interface(
        name="push_notification",
        description="推送实时通知给用户",
        params={"user_id": "int", "message": "str"},
        returns="bool",
        location="notifications/push.py",
        dependencies=["send_email"],
        called_by=[],
        last_used="2026-07-17 15:30",
        risk_level=RiskLevel.HIGH,
        notes="生产环境OOM风险（手写-运维-07/18）| 批量推送要分页",
        author="AI记录 + 人工批注",
    )

    session.add_interface(send_email)
    session.add_interface(query_db)
    session.add_interface(generate_report)
    session.add_interface(push_notif)
    session.version = 2

    return session


def test_export_markdown_basic():
    """基本 Markdown 导出测试"""
    print("🧪 test_export_markdown_basic")
    session = create_test_session()

    md = export_markdown(session, include_diagram=True)

    # 验证基本结构
    assert "# 接口笔记 — 测试项目" in md, "标题缺失"
    assert "## send_email" in md, "send_email 接口缺失"
    assert "## query_database" in md, "query_database 接口缺失"
    assert "## generate_report" in md, "generate_report 接口缺失"
    assert "## push_notification" in md, "push_notification 接口缺失"

    # 验证手写区
    assert "📝 手写区" in md, "手写区缺失"
    assert "___" in md, "留白下划线缺失"

    # 验证风险 emoji
    assert "🟢" in md, "绿色 emoji 缺失"
    assert "🟡" in md, "黄色 emoji 缺失"
    assert "🔴" in md, "红色 emoji 缺失"

    print(f"   ✅ Markdown 导出正确 ({len(md)} 字符)")


def test_export_markdown_disclaimer():
    """免责声明测试"""
    print("🧪 test_export_markdown_disclaimer")

    # 模式B + strong → 应有免责声明
    session = Session(project_name="旧项目", mode=Mode.B_FULLSCAN)
    iface = Interface(name="test_func", description="测试", risk_level=RiskLevel.MEDIUM)
    session.add_interface(iface)

    md = export_markdown(session, include_disclaimer=True, disclaimer_strength="strong")
    assert "⚠️" in md, "免责声明 emoji 缺失"
    assert "AI 全量扫描" in md, "免责声明内容缺失"
    assert "仔细甄别" in md, "免责声明内容缺失"

    # 模式A → 不应有免责声明
    session_a = Session(project_name="新项目", mode=Mode.A_INCREMENTAL)
    session_a.add_interface(Interface(name="func1", description="测试"))
    md_a = export_markdown(session_a, include_disclaimer=False)
    assert "⚠️" not in md_a, "模式A 不应有免责声明"

    print(f"   ✅ 免责声明逻辑正确")


def test_export_markdown_weak_disclaimer():
    """弱化免责声明测试（v2+）"""
    print("🧪 test_export_markdown_weak_disclaimer")

    session = create_test_session()
    md = export_markdown(session, include_disclaimer=True, disclaimer_strength="weak")

    assert "ℹ️" in md or "本文档已通过" in md, "弱化提示缺失"
    assert "⚠️ 该内容由 AI" not in md, "不应有强免责声明"

    print(f"   ✅ 弱化免责声明正确")


def test_generate_mermaid():
    """Mermaid 图生成测试"""
    print("🧪 test_generate_mermaid")

    session = create_test_session()
    mermaid = generate_mermaid(session)

    # 基本结构
    assert "flowchart TD" in mermaid, "flowchart 声明缺失"
    assert "send_email" in mermaid, "节点缺失"
    assert "query_database" in mermaid, "节点缺失"

    # 箭头关系
    assert "-->" in mermaid, "箭头关系缺失"
    assert "调用" in mermaid, "关系标签缺失"

    # 颜色样式
    assert "fill:" in mermaid, "样式定义缺失"
    assert "#238636" in mermaid, "绿色缺失"
    assert "#d29922" in mermaid, "黄色缺失"
    assert "#f85149" in mermaid, "红色缺失"

    print(f"   ✅ Mermaid 图生成正确")
    print(f"   📊 图内容预览：")
    for line in mermaid.split("\n")[:6]:
        print(f"      {line}")


def test_generate_mermaid_full():
    """完整 Mermaid 代码块测试"""
    print("🧪 test_generate_mermaid_full")

    session = create_test_session()
    full = generate_mermaid_full(session)

    assert full.startswith("```mermaid"), "代码块开头缺失"
    assert full.endswith("```"), "代码块结尾缺失"

    print(f"   ✅ 完整 Mermaid 代码块正确")


def test_export_json():
    """JSON 导出测试"""
    print("🧪 test_export_json")

    session = create_test_session()
    json_str = export_json(session)

    import json
    data = json.loads(json_str)

    assert data["project_name"] == "测试项目"
    assert "interfaces" in data
    assert "send_email" in data["interfaces"]
    assert data["interfaces"]["send_email"]["risk_level"] == "low"
    assert data["version"] == 2

    print(f"   ✅ JSON 导出正确")


def test_export_text():
    """纯文本导出测试"""
    print("🧪 test_export_text")

    session = create_test_session()
    text = export_text(session)

    assert "接口笔记 — 测试项目" in text
    assert "[🟢] send_email" in text or "send_email" in text
    assert "功能:" in text
    assert "参数:" in text

    print(f"   ✅ 纯文本导出正确 ({len(text)} 字符)")


def test_legend():
    """图例测试"""
    print("🧪 test_legend")
    legend = generate_legend()
    assert "红色" in legend
    assert "黄色" in legend
    assert "绿色" in legend
    print(f"   ✅ 图例正确: {legend}")


def test_save_and_load():
    """Session 持久化测试"""
    print("🧪 test_save_and_load")

    session = create_test_session()

    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        tmp_path = f.name

    try:
        session.save(tmp_path)

        loaded = Session.load(tmp_path)
        assert loaded.project_name == session.project_name
        assert len(loaded.interfaces) == len(session.interfaces)
        assert "send_email" in loaded.interfaces
        assert loaded.version == 2

        print(f"   ✅ Session 保存/加载正确")
    finally:
        os.unlink(tmp_path)


if __name__ == "__main__":
    print("=" * 50)
    print("📋 导出功能测试套件（Phase 2）")
    print("=" * 50)
    print()

    test_export_markdown_basic()
    test_export_markdown_disclaimer()
    test_export_markdown_weak_disclaimer()
    test_generate_mermaid()
    test_generate_mermaid_full()
    test_export_json()
    test_export_text()
    test_legend()
    test_save_and_load()

    print()
    print("=" * 50)
    print("🎉 全部测试通过！")
    print("=" * 50)
