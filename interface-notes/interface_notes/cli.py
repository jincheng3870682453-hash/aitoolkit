"""
CLI 主入口 — interface_notes 命令行工具

用法：
  python -m interface_notes mode-a --project "项目名" --path ./project
  python -m interface_notes mode-b --project "旧项目" --path ./legacy
  python -m interface_notes export --format md --output notes.md
  python -m interface_notes ocr-merge --image photo.jpg
  python -m interface_notes show
  python -m interface_notes test
"""

import sys
import os
import json
import argparse
from pathlib import Path
from datetime import datetime

# 确保能找到包
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from interface_notes.core.session import Session
from interface_notes.core.types import Mode, RiskLevel, ExportFormat
from interface_notes.analyzer.code_analyzer import analyze_project, analyze_file
from interface_notes.exporter.markdown_exporter import (
    export_markdown, export_json, export_text
)
from interface_notes.exporter.diagram import generate_mermaid, generate_legend
from interface_notes.ocr.ocr_engine import process_photo, merge_handwritten_notes


# ──────────────────────────────────────────────
# 全局状态文件
# ──────────────────────────────────────────────

STATE_DIR = Path.home() / ".interface_notes"
STATE_FILE = STATE_DIR / "current_session.json"


def _save_current_session(session: Session):
    """保存当前会话到用户目录"""
    STATE_DIR.mkdir(exist_ok=True)
    session.save(str(STATE_FILE))


def _load_current_session() -> Session:
    """加载当前会话"""
    if not STATE_FILE.exists():
        print("⚠️ 没有活跃的会话。请先运行 mode-a 或 mode-b 创建会话。")
        sys.exit(1)
    return Session.load(str(STATE_FILE))


# ──────────────────────────────────────────────
# 子命令实现
# ──────────────────────────────────────────────

def cmd_mode_a(args):
    """
    模式A：共同开发（增量记录）

    对应设计文档：边写边记，AI 实时识别新接口
    """
    project_name = args.project or "未命名项目"
    project_path = args.path or "."

    print(f"🚀 模式A：共同开发")
    print(f"   项目：{project_name}")
    print(f"   路径：{project_path}")
    print()

    # 创建会话
    session = Session(project_name=project_name, mode=Mode.A_INCREMENTAL)

    if os.path.isdir(project_path):
        print(f"📂 扫描项目目录...")
        session = analyze_project(project_path, session)
        print(f"   ✅ 扫描完成")
        print(f"   📁 文件数：{session.stats['total_files_scanned']}")
        print(f"   🔌 接口数：{len(session.interfaces)}")
        print()

    # 显示发现的接口
    if session.interfaces:
        print("📋 发现的接口：")
        for name, iface in sorted(session.interfaces.items()):
            emoji = iface.risk_level.emoji
            print(f"   {emoji} {name} — {iface.description[:40]}")
        print()

    # 交互式确认
    pending = [i for i in session.interfaces.values() if i.should_ask()]
    if pending and not args.yes:
        print("─" * 40)
        for iface in pending:
            print(f"\n📌 接口：{iface.name}")
            print(f"   功能：{iface.description}")
            if iface.params:
                params_str = ", ".join(f"{k}: {v}" for k, v in iface.params.items())
                print(f"   参数：{params_str}")
            print(f"   位置：{iface.location}")

            while True:
                ans = input("   要记到接口笔记里吗？(y/n/all/q): ").strip().lower()
                if ans in ("y", "yes"):
                    session.confirm_interface(iface.name)
                    print("   ✅ 已记录")
                    break
                elif ans in ("n", "no"):
                    session.skip_interface(iface.name)
                    print("   ⏭️ 已跳过")
                    break
                elif ans == "all":
                    for i in pending:
                        session.confirm_interface(i.name)
                    print("   ✅ 全部已记录")
                    pending = []
                    break
                elif ans == "q":
                    print("   退出确认")
                    return
                else:
                    print("   请输入 y/n/all/q")
            if ans == "all":
                break

    # 保存会话
    _save_current_session(session)

    print()
    print("─" * 40)
    print(f"📊 会话摘要：")
    print(session.summary())
    print()
    print(f"💡 下一步：")
    print(f"   - 继续开发，随时用 'add' 命令手动添加接口")
    print(f"   - 开发告一段落，用 'export' 命令导出笔记")
    print(f"   - 用 'show' 命令查看当前状态")


def cmd_mode_b(args):
    """
    模式B：接手旧项目（全量扫描）

    对应设计文档：全量喂入+通读，花 Token 换精准度
    """
    project_name = args.project or "旧项目扫描"
    project_path = args.path or "."

    print(f"🔍 模式B：接手旧项目（全量扫描）")
    print(f"   项目：{project_name}")
    print(f"   路径：{project_path}")
    print()

    if not os.path.isdir(project_path):
        print(f"❌ 目录不存在：{project_path}")
        sys.exit(1)

    # 全量扫描
    print(f"📂 开始全量扫描...")
    session = Session(project_name=project_name, mode=Mode.B_FULLSCAN)
    session = analyze_project(project_path, session, max_files=args.max_files)

    scanned = session.stats['total_files_scanned']
    total = len(session.interfaces)

    print(f"   ✅ 扫描完成")
    print(f"   📁 扫描文件：{scanned}")
    print(f"   🔌 发现接口：{total}")
    print()

    # 显示接口列表（带风险标记）
    print("📋 接口清单：")
    for name, iface in sorted(session.interfaces.items()):
        emoji = iface.risk_level.emoji
        flag = " ⚠️" if iface.suspicious else ""
        print(f"   {emoji} {name} — {iface.description[:35]}{flag}")
    print()

    # 显示可疑点
    suspicious = [(n, i) for n, i in session.interfaces.items() if i.suspicious]
    if suspicious:
        print("⚠️ 可疑点 Top 列表：")
        for name, iface in suspicious[:10]:
            print(f"   🔸 {name}: {iface.suspicious}")
        print()

    # 自动导出 v1
    if args.auto_export:
        output = args.output or f"{project_name}_INTERFACE_NOTES_v1.md"
        md = export_markdown(
            session,
            include_disclaimer=True,
            disclaimer_strength="strong",
            include_diagram=True,
        )
        with open(output, "w", encoding="utf-8") as f:
            f.write(md)
        print(f"📄 v1 笔记已导出：{output}")
        print(f"   ⚠️ 记得打印后手写修正！")
        print()

    # 保存会话
    _save_current_session(session)

    print("─" * 40)
    print(f"📊 会话摘要：")
    print(session.summary())
    print()
    print(f"💡 下一步：")
    print(f"   - 打印导出的 .md 文件")
    print(f"   - 手写批注后拍照")
    print(f"   - 用 'ocr-merge --image 照片.jpg' 回流")


def cmd_export(args):
    """
    导出接口笔记

    对应设计文档 Phase 2：导出 .md / .txt / .json
    """
    session = _load_current_session()

    fmt = (args.format or "md").lower()
    output = args.output

    if not output:
        ext = fmt if fmt != "json" else "json"
        output = f"{session.project_name}_INTERFACE_NOTES.{ext}"

    # 免责声明设置
    disclaimer = session.mode == Mode.B_FULLSCAN and session.version == 1
    disc_strength = "strong" if disclaimer else ("weak" if session.version >= 2 else "none")

    if fmt == "md":
        content = export_markdown(
            session,
            include_disclaimer=disclaimer or session.version >= 2,
            disclaimer_strength=disc_strength,
            include_diagram=not args.no_diagram,
        )
    elif fmt == "json":
        content = export_json(session)
    elif fmt == "txt":
        content = export_text(session)
    else:
        print(f"❌ 不支持的格式：{fmt}（支持：md, json, txt）")
        sys.exit(1)

    with open(output, "w", encoding="utf-8") as f:
        f.write(content)

    print(f"📄 导出完成：{output}")
    print(f"   格式：{fmt}")
    print(f"   大小：{len(content)} 字符")
    if fmt == "md":
        print(f"   接口数：{len(session.interfaces)}")
        print(f"   💡 建议打印后手写批注")


def cmd_ocr_merge(args):
    """
    OCR 拍照回流

    对应设计文档 Phase 3：拍照 → OCR → 合并 → 升级
    """
    session = _load_current_session()

    image_path = args.image
    if not os.path.exists(image_path):
        print(f"❌ 文件不存在：{image_path}")
        sys.exit(1)

    author = args.author or "手写批注"

    print(f"📸 OCR 回流处理")
    print(f"   图片：{image_path}")
    print(f"   作者：{author}")
    print()

    # 处理
    updated = process_photo(image_path, session, author=author)

    # 保存更新后的会话
    _save_current_session(updated)

    # 自动导出 v2
    output = args.output or f"{session.project_name}_INTERFACE_NOTES_v{updated.version}.md"
    md = export_markdown(
        updated,
        include_disclaimer=True,
        disclaimer_strength="weak",  # v2 用弱化提示
        include_diagram=True,
    )
    with open(output, "w", encoding="utf-8") as f:
        f.write(md)

    print()
    print(f"📄 v{updated.version} 笔记已导出：{output}")
    print(f"   🔄 版本：v{session.version} → v{updated.version}")
    print(f"   ✅ 手写批注已合并")


def cmd_show(args):
    """显示当前会话状态"""
    session = _load_current_session()

    print("=" * 50)
    print(session.summary())
    print("=" * 50)
    print()

    if not session.interfaces:
        print("（暂无接口记录）")
        return

    print(f"{'接口名':<25} {'风险':<6} {'位置':<30} {'状态'}")
    print("─" * 70)
    for name, iface in sorted(session.interfaces.items()):
        status = "✅已确认" if iface.confirmed else ("⏭️已跳过" if iface.skipped else "❓待确认")
        loc = iface.location[:28] if iface.location else "-"
        print(f"  {iface.risk_level.emoji} {name:<23} {iface.risk_level.value:<6} {loc:<30} {status}")

    print()
    print(f"📊 调用关系图：")
    graph = session.get_call_graph()
    if graph:
        for caller, callees in graph.items():
            for callee in callees:
                print(f"   {caller} → {callee}")
    else:
        print("   （暂无调用关系）")


def cmd_add(args):
    """手动添加一个接口记录"""
    session = _load_current_session()

    name = args.name
    description = args.description or f"接口 {name}"

    iface = session.get_interface(name)
    if iface is None:
        iface = __import__(
            "interface_notes.core.types", fromlist=["Interface"]
        ).Interface(name=name, description=description)
        session.add_interface(iface)
        print(f"✅ 新增接口：{name}")
    else:
        print(f"⚠️ 接口已存在：{name}")

    # 更新字段
    if args.location:
        iface.location = args.location
    if args.returns:
        iface.returns = args.returns
    if args.params:
        for p in args.params.split(","):
            p = p.strip()
            if ":" in p:
                pn, pt = p.split(":", 1)
                iface.add_param(pn.strip(), pt.strip())
            else:
                iface.add_param(p, "")

    iface.confirmed = True
    _save_current_session(session)
    print(f"   📝 描述：{iface.description}")
    print(f"   📍 位置：{iface.location}")
    print(f"   🔙 返回：{iface.returns}")
    print(f"   📋 参数：{list(iface.params.keys())}")


def cmd_diagram(args):
    """只输出 Mermaid 图"""
    session = _load_current_session()
    diagram = generate_mermaid(session)
    print("```mermaid")
    print(diagram)
    print("```")
    print()
    print(generate_legend())


def cmd_test(args):
    """运行测试套件"""
    import subprocess

    test_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tests")

    tests = ["test_identify.py", "test_fullscan.py", "test_export.py", "test_ocr_merge.py"]

    if args.test_name:
        tests = [t for t in tests if args.test_name in t]
        if not tests:
            print(f"❌ 没找到匹配的测试：{args.test_name}")
            print(f"   可用：{', '.join(t.replace('.py','') for t in tests)}")
            sys.exit(1)

    print("🧪 运行测试套件...")
    print()

    failed = 0
    for test in tests:
        test_path = os.path.join(test_dir, test)
        print(f"▶ 运行 {test}...")
        result = subprocess.run(
            [sys.executable, test_path],
            capture_output=False,
        )
        if result.returncode != 0:
            failed += 1
        print()

    if failed:
        print(f"❌ {failed} 个测试套件失败")
        sys.exit(1)
    else:
        print(f"🎉 全部测试通过！")


# ──────────────────────────────────────────────
# ArgumentParser 构建
# ──────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="interface_notes",
        description="AI 接口笔记工作流工具 — 让 AI 自动记接口、画图、吸收手写批注",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 模式A：共同开发
  python -m interface_notes mode-a --project "我的项目" --path ./src

  # 模式B：全量扫描旧项目
  python -m interface_notes mode-b --project "屎山项目" --path ./legacy --auto-export

  # 查看当前状态
  python -m interface_notes show

  # 导出笔记
  python -m interface_notes export --format md --output notes.md

  # OCR 回流
  python -m interface_notes ocr-merge --image photo.jpg --author "张三"

  # 运行测试
  python -m interface_notes test
        """,
    )

    subparsers = parser.add_subparsers(dest="command", help="可用命令")

    # mode-a
    p_a = subparsers.add_parser("mode-a", help="模式A：共同开发（增量记录）")
    p_a.add_argument("--project", "-p", help="项目名称")
    p_a.add_argument("--path", "-d", help="项目路径（默认当前目录）")
    p_a.add_argument("--yes", "-y", action="store_true", help="自动确认所有接口")

    # mode-b
    p_b = subparsers.add_parser("mode-b", help="模式B：全量扫描旧项目")
    p_b.add_argument("--project", "-p", help="项目名称")
    p_b.add_argument("--path", "-d", help="项目路径（默认当前目录）")
    p_b.add_argument("--max-files", type=int, default=500, help="最大扫描文件数")
    p_b.add_argument("--auto-export", action="store_true", help="扫描后自动导出 v1")
    p_b.add_argument("--output", "-o", help="导出文件路径")

    # export
    p_e = subparsers.add_parser("export", help="导出接口笔记")
    p_e.add_argument("--format", "-f", default="md", choices=["md", "json", "txt"], help="导出格式")
    p_e.add_argument("--output", "-o", help="输出文件路径")
    p_e.add_argument("--no-diagram", action="store_true", help="不包含 Mermaid 图")

    # ocr-merge
    p_o = subparsers.add_parser("ocr-merge", help="OCR 拍照回流")
    p_o.add_argument("--image", "-i", required=True, help="照片/文本文件路径")
    p_o.add_argument("--author", "-a", help="手写人姓名")
    p_o.add_argument("--output", "-o", help="导出 v2 文件路径")

    # show
    subparsers.add_parser("show", help="显示当前会话状态")

    # add
    p_add = subparsers.add_parser("add", help="手动添加接口")
    p_add.add_argument("--name", "-n", required=True, help="接口名")
    p_add.add_argument("--description", "-d", help="功能描述")
    p_add.add_argument("--location", "-l", help="文件路径")
    p_add.add_argument("--returns", "-r", help="返回值类型")
    p_add.add_argument("--params", "-p", help="参数列表 (name:type,name:type)")

    # diagram
    subparsers.add_parser("diagram", help="只输出 Mermaid 关系图")

    # test
    p_t = subparsers.add_parser("test", help="运行测试套件")
    p_t.add_argument("test_name", nargs="?", help="只运行匹配的测试")

    return parser


# ──────────────────────────────────────────────
# 主入口
# ──────────────────────────────────────────────

def main():
    parser = build_parser()
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    # 路由到对应命令
    commands = {
        "mode-a": cmd_mode_a,
        "mode-b": cmd_mode_b,
        "export": cmd_export,
        "ocr-merge": cmd_ocr_merge,
        "show": cmd_show,
        "add": cmd_add,
        "diagram": cmd_diagram,
        "test": cmd_test,
    }

    handler = commands.get(args.command)
    if handler:
        handler(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
