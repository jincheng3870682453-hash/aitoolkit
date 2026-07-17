"""
test_ocr_merge.py — 测试 OCR 回流合并（Phase 3）

验证：OCR 文本 → 解析 → 匹配接口 → 合并 notes → 升级 risk_level
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from interface_notes.core.session import Session
from interface_notes.core.types import Interface, RiskLevel, Mode
from interface_notes.ocr.ocr_engine import (
    parse_handwritten_notes,
    merge_handwritten_notes,
    process_photo,
    _extract_handwritten,
    _auto_upgrade_risk,
    ocr_image,
)


def create_session_for_ocr() -> Session:
    """创建用于 OCR 测试的 Session"""
    session = Session(project_name="AI语音项目", mode=Mode.B_FULLSCAN)

    send_email = Interface(
        name="send_email",
        description="AI的理解：发送邮件通知",
        params={"to": "str", "subject": "str", "body": "str"},
        returns="bool - 是否发送成功",
        location="utils/email.py",
        dependencies=["query_database"],
        called_by=["generate_report"],
        risk_level=RiskLevel.LOW,
        notes="",
    )

    query_db = Interface(
        name="query_database",
        description="AI的理解：查询用户表",
        params={"table": "str", "condition": "dict"},
        returns="list[dict]",
        location="db/query.py",
        dependencies=[],
        called_by=["send_email", "generate_report"],
        risk_level=RiskLevel.LOW,  # 初始低风险
        notes="",
        suspicious="未设置超时",
    )

    transcribe = Interface(
        name="transcribe_audio",
        description="AI的理解：将音频转为文字",
        params={"audio_path": "str", "language": "str"},
        returns="dict",
        location="core/transcribe.py",
        dependencies=["load_model", "query_database"],
        called_by=["batch_process"],
        risk_level=RiskLevel.MEDIUM,
        notes="",
        suspicious="大文件可能阻塞",
    )

    session.add_interface(send_email)
    session.add_interface(query_db)
    session.add_interface(transcribe)

    return session


# ──────────────────────────────────────────────
# OCR 文本解析测试
# ──────────────────────────────────────────────

SAMPLE_OCR_TEXT = """
接口笔记 — AI语音项目
================================================

send_email
📝 手写区：
⚠️ 163邮箱要单独配SMTP！
密码不是登录密码，是授权码
（踩坑2026-07-16，排查了3小时）
→ 找老王问过，他说用SSL端口465
_______________________________________________________

query_database
📝 手写区：
🔴 这里超时没设！
上次生产环境卡死就是这个接口
→ 加 timeout=10 就行
→ 老王写的，他离职了，有问题问小李
_______________________________________________________

transcribe_audio
📝 手写区：
注意：超过60秒的音频会超时
→ 待优化，加分片逻辑
找小张聊过，他有方案
"""


def test_extract_handwritten():
    """手写内容提取测试"""
    print("🧪 test_extract_handwritten")

    block = """
📝 手写区：
⚠️ 163邮箱要单独配SMTP！
密码不是登录密码，是授权码
→ 找老王问过，他说用SSL端口465
_______________________________________________________
    """

    result = _extract_handwritten(block)
    assert "163邮箱" in result, f"内容提取失败: {result}"
    assert "授权码" in result, f"内容提取失败: {result}"
    assert "老王" in result, f"内容提取失败: {result}"
    assert "___" not in result, "下划线应被过滤"

    print(f"   ✅ 手写内容提取正确")
    print(f"      内容: {result[:50]}...")


def test_parse_handwritten_notes():
    """解析 OCR 文本并匹配接口测试"""
    print("🧪 test_parse_handwritten_notes")

    session = create_session_for_ocr()
    notes_map = parse_handwritten_notes(SAMPLE_OCR_TEXT, session)

    assert "send_email" in notes_map, f"send_email 未匹配"
    assert "query_database" in notes_map, f"query_database 未匹配"
    assert "transcribe_audio" in notes_map, f"transcribe_audio 未匹配"

    # 验证 send_email 手写内容
    se_notes = notes_map["send_email"]
    assert "163邮箱" in se_notes, f"send_email 内容错误: {se_notes}"
    assert "授权码" in se_notes, f"send_email 内容错误: {se_notes}"

    # 验证 query_database 手写内容
    qd_notes = notes_map["query_database"]
    assert "超时" in qd_notes, f"query_database 内容错误: {qd_notes}"
    assert "小李" in qd_notes, f"query_database 内容错误: {qd_notes}"

    print(f"   ✅ 接口匹配正确")
    for name, notes in notes_map.items():
        print(f"      {name}: {notes[:40]}...")


def test_merge_notes_basic():
    """合并手写批注到 Session 测试"""
    print("🧪 test_merge_notes_basic")

    session = create_session_for_ocr()
    original_version = session.version

    updated = merge_handwritten_notes(
        session, SAMPLE_OCR_TEXT, author="张三"
    )

    # 版本应 +1
    assert updated.version == original_version + 1, \
        f"版本未递增: {updated.version}"

    # send_email 应有手写内容
    se = updated.get_interface("send_email")
    assert "163邮箱" in se.notes, f"send_email notes 未更新: {se.notes}"
    assert "张三" in se.notes, f"作者名未记录: {se.notes}"
    assert "人工批注" in se.author, f"author 未更新: {se.author}"

    print(f"   ✅ 批注合并正确")
    print(f"      send_email.notes: {se.notes[:60]}...")


def test_auto_upgrade_risk():
    """风险自动升级测试"""
    print("🧪 test_auto_upgrade_risk")

    session = create_session_for_ocr()

    # query_database: 手写提到"超时"+"生产环境卡死" → 应升为 HIGH
    updated = merge_handwritten_notes(session, SAMPLE_OCR_TEXT, author="张三")

    qd = updated.get_interface("query_database")
    assert qd.risk_level == RiskLevel.HIGH, \
        f"query_database 风险应升为 HIGH, got: {qd.risk_level}"
    assert "风险升级" in qd.notes or "timeout" in qd.notes.lower(), \
        f"升级原因未记录: {qd.notes}"

    # transcribe_audio: 手写提到"超时" → 应升为 HIGH
    ta = updated.get_interface("transcribe_audio")
    assert ta.risk_level == RiskLevel.HIGH, \
        f"transcribe_audio 风险应升为 HIGH, got: {ta.risk_level}"

    # send_email: 手写提到"踩坑" → 关键词检测
    se = updated.get_interface("send_email")
    # "踩坑" 属于高风险关键词
    assert se.risk_level == RiskLevel.HIGH, \
        f"send_email 风险应升为 HIGH (踩坑), got: {se.risk_level}"

    print(f"   ✅ 风险自动升级正确")
    print(f"      query_database: {qd.risk_level.value}")
    print(f"      transcribe_audio: {ta.risk_level.value}")
    print(f"      send_email: {se.risk_level.value}")


def test_risk_keyword_medium():
    """中风险关键词测试"""
    print("🧪 test_risk_keyword_medium")

    iface = Interface(name="test_func", risk_level=RiskLevel.LOW)
    _auto_upgrade_risk(iface, "注意：这里可能有问题，待优化")
    assert iface.risk_level == RiskLevel.MEDIUM, \
        f"应升为 MEDIUM, got: {iface.risk_level}"

    print(f"   ✅ 中风险关键词检测正确")


def test_ocr_image_simulate():
    """OCR 图片模拟模式测试"""
    print("🧪 test_ocr_image_simulate")

    # 使用 .txt 模拟 OCR 结果
    with open("/tmp/sim_ocr.txt", "w") as f:
        f.write(SAMPLE_OCR_TEXT)

    try:
        text = ocr_image("/tmp/sim_ocr.txt")
        assert "send_email" in text, "OCR 文本读取失败"
        assert "手写区" in text, "OCR 文本读取失败"
        print(f"   ✅ OCR 模拟模式正常 ({len(text)} 字符)")
    finally:
        os.unlink("/tmp/sim_ocr.txt")


def test_process_photo_e2e():
    """端到端：模拟拍照回流完整流程"""
    print("🧪 test_process_photo_e2e")

    # 写入模拟 OCR 文本
    with open("/tmp/photo_sim.txt", "w") as f:
        f.write(SAMPLE_OCR_TEXT)

    try:
        session = create_session_for_ocr()
        original_notes = {n: i.notes for n, i in session.interfaces.items()}

        # 处理"照片"
        updated = process_photo("/tmp/photo_sim.txt", session, author="李四")

        # 验证变更
        for name, iface in updated.interfaces.items():
            if iface.notes != original_notes[name]:
                print(f"      📝 {name}: 已更新")

        assert updated.get_interface("query_database").risk_level == RiskLevel.HIGH
        assert "李四" in updated.get_interface("send_email").notes

        print(f"   ✅ 拍照回流 E2E 成功")
        print(f"      版本: v{session.version} → v{updated.version}")

    finally:
        os.unlink("/tmp/photo_sim.txt")


def test_merge_preserves_existing_notes():
    """合并时保留已有 notes 测试"""
    print("🧪 test_merge_preserves_existing_notes")

    session = create_session_for_ocr()

    # 先手动加一条 note
    se = session.get_interface("send_email")
    se.notes = "之前的批注：用SSL"
    se.author = "AI记录 + 人工批注"

    updated = merge_handwritten_notes(session, SAMPLE_OCR_TEXT, author="张三")

    se_new = updated.get_interface("send_email")
    assert "之前的批注" in se_new.notes, f"原有批注被覆盖: {se_new.notes}"
    assert "163邮箱" in se_new.notes, f"新批注未合并: {se_new.notes}"

    print(f"   ✅ 已有 notes 保留并合并")
    print(f"      send_email.notes: {se_new.notes[:80]}...")


if __name__ == "__main__":
    print("=" * 50)
    print("📋 OCR 回流测试套件（Phase 3）")
    print("=" * 50)
    print()

    test_extract_handwritten()
    test_parse_handwritten_notes()
    test_merge_notes_basic()
    test_auto_upgrade_risk()
    test_risk_keyword_medium()
    test_ocr_image_simulate()
    test_process_photo_e2e()
    test_merge_preserves_existing_notes()

    print()
    print("=" * 50)
    print("🎉 全部测试通过！")
    print("=" * 50)
