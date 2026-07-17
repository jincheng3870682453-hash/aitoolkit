"""
Proteus.py —— 统一启动入口（交互菜单）

启动后显示菜单，选择要用的模块。
每个模块独立运行，互不干扰。

零依赖（纯标准库）。
"""

import os
import sys
import json
import logging
from pathlib import Path

log = logging.getLogger("jinchen.proteus")

# ── 菜单定义 ─────────────────────────────────────────────
MENU = """
╔════════════════════════════════════════════╗
║   jinchen  ·  AI 治理工具集  v3.2          ║
╠════════════════════════════════════════════╣
║  1) 🛡️  代码守门（work.py）              ║
║  2) 💾  快照管理（guardian.py）            ║
║  3) 🧠  长对话记忆（Archive.py）          ║
║  4) 📖  叙事创作（shiyun.py）             ║
║  5) 📊  POC 报告（Nuwa.py）              ║
║  6) 🌐  启动网关（gateway.py）            ║
║  7) 📈  全栈辐射检测（Nuwa.py）          ║
║  8) 🧪  自检（mutate + verify）           ║
║  0) 👋  退出                              ║
╚════════════════════════════════════════════╝
"""


def _prompt(prompt: str, default: str = "") -> str:
    try:
        ans = input(prompt).strip()
    except (KeyboardInterrupt, EOFError):
        return ""
    return ans or default


def _run_work():
    from . import work
    path = _prompt("📂 输入要检查的文件路径: ")
    if not path or not Path(path).exists():
        print("  ❌ 文件不存在")
        return
    report = work.check_file(path)
    print(f"\n  {report.to_markdown()}")
    print(f"\n  📊 度量: {json.dumps(report.metrics, ensure_ascii=False)}")
    if report.compressed_view:
        print(f"\n  🗺️ 代码骨架:\n{report.compressed_view[:500]}")


def _run_guardian():
    from . import guardian
    action = _prompt("动作 [snapshot/rollback/list/verify]: ", "list")
    g = guardian.Guardian()
    if action == "snapshot":
        name = _prompt("快照名称: ", f"snap-{os.urandom(2).hex()}")
        result = g.snapshot(name)
        if isinstance(result, guardian.SafeResult):
            print(f"  ❌ {result.error}")
        else:
            print(f"  ✅ 快照: {result}")
    elif action == "rollback":
        sid = _prompt("快照 ID: ")
        result = g.rollback(sid)
        if isinstance(result, guardian.SafeResult):
            print(f"  ❌ {result.error}")
        else:
            print(f"  ✅ 已回滚到 {sid}")
    elif action == "list":
        for s in g.list_snapshots():
            print(f"  📸 {s['snapshot_id']}  {s.get('name','')}  ({s['files']} files)")
    elif action == "verify":
        for sid, r in g.verify_all().items():
            icon = "✅" if r["ok"] else "❌"
            print(f"  {icon} {sid}: {r}")


def _run_archive():
    from . import Archive
    arc = Archive.Archive()
    action = _prompt("动作 [add/get/clear/stats]: ", "stats")
    cid = _prompt("对话 ID: ", "default")
    if action == "add":
        text = _prompt("输入内容: ")
        arc.add(cid, text)
        print("  ✅ 已记录")
    elif action == "get":
        text = _prompt("当前输入（用于匹配上下文）: ", "")
        for i, c in enumerate(arc.get_context(cid, text)):
            print(f"  [{i+1}] {c[:80]}")
    elif action == "clear":
        arc.clear(cid)
        print("  🧹 已清除")
    elif action == "stats":
        print(f"  {json.dumps(arc.stats(cid), ensure_ascii=False)}")


def _run_shiyun():
    try:
        from . import shiyun
        print("  📖 叙事工厂已加载")
        print("  （直接运行 python -m Toolkit.shiyun 体验完整功能）")
    except ImportError:
        print("  ⚠️ shiyun 模块未就绪")


def _run_nuwa():
    from . import Nuwa
    title = _prompt("POC 标题: ", "未命名 POC")
    scenario = _prompt("场景描述: ", "")
    n = Nuwa.Nuwa(title, scenario)
    print("  输入测试步骤（空行结束）：")
    while True:
        line = input("    > ").strip()
        if not line:
            break
        n.add_step(line)
    verdict = _prompt("结论 [pass/fail/partial]: ", "pass")
    n.verdict = verdict
    paths = n.save()
    print(f"  ✅ 报告: {paths}")


def _run_gateway():
    from . import gateway
    print("  🌐 启动交互网关（输入 'quit' 退出）")
    gw = gateway.WordGateway(env=os.getenv("NUWA_ENV", "dev"))
    while True:
        try:
            user = input("  👤 你: ").strip()
        except (KeyboardInterrupt, EOFError):
            break
        if user.lower() in ("quit", "exit", "q"):
            break
        if not user:
            continue
        result = gw.handle(user)
        print(f"  🤖 [{result['intent']}]: {result['output'][:500]}")
        if result['violations']:
            print(f"  ⚠️ {result['violations']}")


def _run_radiate():
    from . import Nuwa
    path = _prompt("📂 改动文件路径: ")
    if not path or not Path(path).exists():
        print("  ❌ 文件不存在")
        return
    rd = Nuwa.RadiationDetector(project_root=".")
    alerts = rd.scan(path)
    print(f"\n  {rd.generate_report(alerts)}")


def _run_self_test():
    from . import work
    print("  🧪 自检模式")
    my_code = Path(__file__).read_text(encoding="utf-8")
    rules = ["no_hardcoded_secrets", "no_sql_injection",
             "no_subprocess_shell", "no_bare_except"]
    result = work.mutation_test(my_code, rules)
    print(f"  检测: {result['detected']}/{result['total']}")
    for k, v in result["details"].items():
        icon = "✅" if v.get("status") == "detected" else "❌"
        print(f"    {icon} {k}: {v.get('status','')}")
    # 对自己做 check
    report = work.check(my_code)
    print(f"\n  自身检查: {'✅ 通过' if report.passed else f'⚠️ {len(report.violations)} 条'}")


# ── 主循环 ──────────────────────────────────────────────
def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    print("")
    while True:
        print(MENU)
        try:
            choice = input("  选择 > ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\n  👋 再见")
            break
        if choice == "1":
            _run_work()
        elif choice == "2":
            _run_guardian()
        elif choice == "3":
            _run_archive()
        elif choice == "4":
            _run_shiyun()
        elif choice == "5":
            _run_nuwa()
        elif choice == "6":
            _run_gateway()
        elif choice == "7":
            _run_radiate()
        elif choice == "8":
            _run_self_test()
        elif choice == "0":
            print("  👋 再见")
            break
        else:
            print("  ❓ 无效选项")
        input("\n  按回车继续...")


if __name__ == "__main__":
    main()
