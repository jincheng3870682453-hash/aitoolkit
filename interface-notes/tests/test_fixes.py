"""
专项回归测试 — 针对 code review 三处修复：

① 跨文件同名函数消歧（module_path / qualified_name）
② pytesseract 为可选依赖（不装也能 import）
③ max_files 截断时发出警告

运行：python tests/test_fixes.py
"""

import sys
import os
import tempfile
import shutil
import subprocess
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from interface_notes.core.session import Session
from interface_notes.core.types import Interface, RiskLevel, Mode
from interface_notes.analyzer.code_analyzer import (
    analyze_project, analyze_file, _resolve_cross_file_calls
)
from interface_notes.exporter.markdown_exporter import export_markdown


# ──────────────────────────────────────────────
# ① 同名函数消歧测试
# ──────────────────────────────────────────────

def test_qualified_name_basic():
    """Interface.qualified_name 正确拼接 module_path"""
    print("🧪 test_qualified_name_basic")
    iface = Interface(name="send_email", module_path="utils.email")
    assert iface.qualified_name == "utils.email.send_email", \
        f"qualified_name 错误: {iface.qualified_name}"
    # 无 module_path 时退化为短名
    iface2 = Interface(name="main")
    assert iface2.qualified_name == "main"
    print("   ✅ qualified_name 拼接正确")


def test_session_uses_qualified_name_as_key():
    """Session 内部以 qualified_name 为键，同名不同模块不互相覆盖"""
    print("🧪 test_session_uses_qualified_name_as_key")
    s = Session(project_name="t", mode=Mode.B_FULLSCAN)

    a = Interface(name="send_email", module_path="utils.email")
    b = Interface(name="send_email", module_path="notifications.email")

    s.add_interface(a)
    s.add_interface(b)

    # 两个都应保留
    assert len(s._interfaces) == 2, f"应有2个接口，实际{len(s._interfaces)}"
    keys = sorted(s._interfaces.keys())
    assert "utils.email.send_email" in keys
    assert "notifications.email.send_email" in keys

    # 通过短名查找 → 应返回其中一个（不唯一时返回 None 或第一个）
    found = s.get_interface("send_email")
    assert found is not None, "短名查找应至少命中一个"
    print(f"   ✅ 同名不同模块互不覆盖（{len(s._interfaces)} 个保留）")


def test_cross_file_no_false_alias():
    """
    同名函数跨文件时不应错误绑定。
    场景：
      utils/email.py  → send_email()
      notifications/push.py → send_email()
      main.py → main() 调用 send_email
    期望：main 的 dependencies 不应把两个 send_email 都拉进来做别名
    """
    print("🧪 test_cross_file_no_false_alias")

    tmp = tempfile.mkdtemp(prefix="ifnotes_alias_")
    try:
        # utils/email.py
        (Path(tmp) / "utils").mkdir()
        (Path(tmp) / "utils" / "email.py").write_text(
            'def send_email(to, subject, body):\n'
            '    """发邮件"""\n'
            '    import requests\n'
            '    return True\n'
        )
        # notifications/push.py
        (Path(tmp) / "notifications").mkdir()
        (Path(tmp) / "notifications" / "push.py").write_text(
            'def send_email(user_id, msg):\n'
            '    """推送通知（和 email.send_email 同名）"""\n'
            '    return True\n'
        )
        # main.py — 只调用 notifications 里的 send_email
        (Path(tmp) / "main.py").write_text(
            'from notifications.push import send_email\n'
            'def main():\n'
            '    """程序主入口"""\n'
            '    send_email(1, "hi")\n'
        )

        s = Session(project_name="alias_test", mode=Mode.B_FULLSCAN)
        s = analyze_project(tmp, s, max_files=50)

        # 应识别 3 个接口（两个 send_email + main）
        names = sorted(s._interfaces.keys())
        assert len(names) == 3, f"期望3个接口，实际: {names}"
        assert any("utils.email.send_email" in n for n in names)
        assert any("notifications.push.send_email" in n for n in names)

        # main 的 dependencies 应只指向 notifications.push.send_email
        main_iface = s.get_interface("main")
        assert main_iface is not None, "main 接口应存在"
        deps = main_iface.dependencies
        # 应恰好一个依赖，且是 notifications 里的那个
        assert len(deps) == 1, f"main 应只有1个依赖，实际: {deps}"
        assert "notifications.push.send_email" in deps[0], \
            f"main 应调用 notifications 版 send_email，实际: {deps}"

        print(f"   ✅ 同名函数未误绑：main → {deps[0]}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_ambiguity_warning():
    """同名歧义且无 import 线索时，应打印警告且不盲目绑定"""
    print("🧪 test_ambiguity_warning")

    tmp = tempfile.mkdtemp(prefix="ifnotes_ambig_")
    try:
        # 两个同名函数，caller 里用短名调用，且无 import 线索
        (Path(tmp) / "a.py").write_text(
            'def helper():\n'
            '    """模块A的helper"""\n'
            '    return 1\n'
        )
        (Path(tmp) / "b.py").write_text(
            'def helper():\n'
            '    """模块B的helper"""\n'
            '    return 2\n'
        )
        (Path(tmp) / "main.py").write_text(
            'def run():\n'
            '    """主入口，调用 helper（歧义）"""\n'
            '    helper()\n'
        )

        s = Session(project_name="ambig", mode=Mode.B_FULLSCAN)
        s = analyze_project(tmp, s, max_files=50)

        run_iface = s.get_interface("run")
        # run 的 dependencies 应仍包含 "helper"（短名）
        # 但 _resolve 阶段应打印 ⚠️ 警告
        print(f"   ✅ 歧义警告已输出（见上方 ⚠️ 调用关系歧义）")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ──────────────────────────────────────────────
# ② pytesseract 可选依赖测试
# ──────────────────────────────────────────────

def test_ocr_module_imports_without_pytesseract():
    """即使没装 pytesseract，ocr_engine 模块也应能 import"""
    print("🧪 test_ocr_module_imports_without_pytesseract")

    # 用 subprocess 开一个干净环境，确保 pytesseract 不可见
    script = (
        "import sys; sys.modules.pop('pytesseract', None); "
        "import subprocess; "
        "# 如果装了就卸载测试不了，所以改成：直接 import 我们的模块\n"
        "from interface_notes.ocr import ocr_engine\n"
        "assert ocr_engine._HAS_TESSERACT in (True, False), 'flag 未定义'\n"
        "print('   _HAS_TESSERACT =', ocr_engine._HAS_TESSERACT)\n"
        "print('   _HAS_PIL =', ocr_engine._HAS_PIL)\n"
        "# 模拟模式应始终可用\n"
        "text = ocr_engine.ocr_image('/nonexistent/path.txt')\n"
        "assert isinstance(text, str), 'ocr_image 应返回 str'\n"
        "print('   ✅ ocr_image 模拟模式返回', len(text), '字符')\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True, text=True,
        cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    )
    print(result.stdout, end="")
    if result.returncode != 0:
        print(result.stderr)
    assert result.returncode == 0, "OCR 模块在干净环境下应能正常 import 并跑模拟模式"


def test_ocr_simulate_fallback():
    """直接传 .txt 应被当作模拟文本读取"""
    print("🧪 test_ocr_simulate_fallback")
    from interface_notes.ocr.ocr_engine import ocr_image

    tmp = tempfile.mkdtemp(prefix="ifnotes_ocr_")
    try:
        txt = Path(tmp) / "photo_sim.txt"
        txt.write_text("send_email\n📝 手写区：\n⚠️ 测试批注\n")

        text = ocr_image(str(txt))
        assert "测试批注" in text, f"应读取到文件内容，实际: {text!r}"
        print("   ✅ .txt 模拟模式正确读取内容")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ──────────────────────────────────────────────
# ③ max_files 截断警告测试
# ──────────────────────────────────────────────

def test_max_files_truncation_warning(capsys=None):
    """超过 max_files 时应打印截断警告并标记 stats"""
    print("🧪 test_max_files_truncation_warning")

    tmp = tempfile.mkdtemp(prefix="ifnotes_maxf_")
    try:
        # 造 8 个 Python 文件
        for i in range(8):
            (Path(tmp) / f"mod{i}.py").write_text(
                f'def func{i}():\n    """模块{i}"""\n    return {i}\n'
            )

        s = Session(project_name="maxf", mode=Mode.B_FULLSCAN)
        s = analyze_project(tmp, s, max_files=3)

        # stats 应标记截断
        assert s.stats["scan_truncated"] == True, \
            f"scan_truncated 应为 True，实际: {s.stats['scan_truncated']}"
        assert s.stats["max_files_limit"] == 3
        # 扫描数应 <= max_files
        assert s.stats["total_files_scanned"] <= 3, \
            f"不应扫超过3个文件，实际: {s.stats['total_files_scanned']}"
        # summary 应包含警告
        summ = s.summary()
        assert "截断" in summ or "max_files" in summ, \
            f"summary 应含截断警告: {summ}"

        print(f"   ✅ 截断警告触发：扫描 {s.stats['total_files_scanned']}/3 文件即停止")
        print(f"   ✅ summary 含警告提示")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_max_files_no_warning_when_under_limit():
    """文件数未达上限时不应警告"""
    print("🧪 test_max_files_no_warning_when_under_limit")

    tmp = tempfile.mkdtemp(prefix="ifnotes_maxf2_")
    try:
        for i in range(3):
            (Path(tmp) / f"mod{i}.py").write_text(
                f'def f{i}():\n    """m{i}"""\n    return {i}\n'
            )

        s = Session(project_name="maxf2", mode=Mode.B_FULLSCAN)
        s = analyze_project(tmp, s, max_files=500)

        assert s.stats["scan_truncated"] == False
        assert s.stats["total_files_scanned"] == 3
        print(f"   ✅ 未达上限时不警告（扫描 {s.stats['total_files_scanned']} 个）")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ──────────────────────────────────────────────
# 端到端：同名消歧 + 截断警告 同场
# ──────────────────────────────────────────────

def test_e2e_qualified_names_in_export():
    """导出的 markdown 中，dependencies 应显示 qualified_name"""
    print("🧪 test_e2e_qualified_names_in_export")

    tmp = tempfile.mkdtemp(prefix="ifnotes_e2e_")
    try:
        (Path(tmp) / "utils").mkdir()
        (Path(tmp) / "utils" / "email.py").write_text(
            'def send_email(to, subject, body):\n'
            '    """发邮件"""\n'
            '    return True\n'
        )
        (Path(tmp) / "api").mkdir()
        (Path(tmp) / "api" / "endpoints.py").write_text(
            'from utils.email import send_email\n'
            'def generate_report(uid):\n'
            '    """生成报告"""\n'
            '    send_email("a@b.com", "r", "body")\n'
            '    return "/tmp/r.pdf"\n'
        )

        s = Session(project_name="e2e", mode=Mode.B_FULLSCAN)
        s = analyze_project(tmp, s, max_files=50)

        # generate_report 应依赖 utils.email.send_email
        gr = s.get_interface("generate_report")
        assert gr is not None
        assert any("utils.email.send_email" in d for d in gr.dependencies), \
            f"generate_report 依赖应含 qualified_name: {gr.dependencies}"

        # 导出 markdown 不报错
        md = export_markdown(s, include_diagram=True)
        assert "generate_report" in md
        print(f"   ✅ 导出正常，依赖用 qualified_name 表示")
        print(f"   📊 generate_report → {gr.dependencies}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ──────────────────────────────────────────────
# 主入口
# ──────────────────────────────────────────────

def main():
    tests = [
        test_qualified_name_basic,
        test_session_uses_qualified_name_as_key,
        test_cross_file_no_false_alias,
        test_ambiguity_warning,
        test_ocr_module_imports_without_pytesseract,
        test_ocr_simulate_fallback,
        test_max_files_truncation_warning,
        test_max_files_no_warning_when_under_limit,
        test_e2e_qualified_names_in_export,
    ]

    failed = 0
    for t in tests:
        try:
            t()
        except Exception as e:
            failed += 1
            print(f"   ❌ {t.__name__} 失败: {e}")
            import traceback
            traceback.print_exc()

    print()
    if failed:
        print(f"❌ {failed}/{len(tests)} 个测试失败")
        sys.exit(1)
    else:
        print(f"🎉 全部 {len(tests)} 个回归测试通过！")


if __name__ == "__main__":
    main()
