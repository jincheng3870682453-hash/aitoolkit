#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Proteus.py — 统一启动入口（交互式菜单）

零门槛使用，菜单式调度所有模块。
首次运行引导配置 API Key。
"""

import os
import sys
import json
import subprocess
from pathlib import Path

CONFIG_PATH = Path("config/config_template.json")
PROTEUS_CONFIG = Path("config/.proteus_config.json")


def load_config() -> dict:
    """加载配置，不存在则引导创建"""
    if PROTEUS_CONFIG.exists():
        return json.loads(PROTEUS_CONFIG.read_text(encoding="utf-8"))
    # 尝试从模板创建
    if CONFIG_PATH.exists():
        cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    else:
        cfg = {
            "env": "dev",
            "model": {"provider": "deepseek", "model": "deepseek-coder", "api_key": ""},
        }
    return cfg


def save_config(cfg: dict):
    PROTEUS_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    PROTEUS_CONFIG.write_text(
        json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")


def interactive_config(cfg: dict) -> dict:
    """交互式配置向导"""
    print("\n🔧 首次配置向导")
    print("─" * 40)

    provider = input(f"  AI 提供商 [deepseek]: ").strip() or "deepseek"
    model = input(f"  模型名 [deepseek-coder]: ").strip() or "deepseek-coder"
    api_key = input(f"  API Key: ").strip()

    env = input(f"  环境 [dev/test/prod]: ").strip() or "dev"

    cfg["env"] = env
    cfg["model"] = {
        "provider": provider,
        "model": model,
        "api_key": api_key,
    }
    save_config(cfg)
    print("✅ 配置已保存到 config/.proteus_config.json")
    return cfg


def show_menu(cfg: dict):
    print("\n" + "═" * 50)
    print("  🛡️  Word 体系 — Proteus 启动器")
    print("═" * 50)
    print(f"  当前环境: {cfg.get('env', 'dev')}")
    print(f"  AI 提供商: {cfg.get('model', {}).get('provider', '?')}")
    print()
    print("  [1] 🚀 启动网关（交互模式）")
    print("  [2] 🧪 运行行为约束检测（work）")
    print("  [3] 💾 创建快照 / 回滚")
    print("  [4] 🧠 长对话记忆测试（Archive）")
    print("  [5] 📖 叙事工厂（shiyun）")
    print("  [6] 📊 生成 POC 报告（Nuwa）")
    print("  [7] ⚖️  查看判决书（RollbackJury）")
    print("  [8] ☢️  辐射检测（RadiationDetector）")
    print("  [9] 🌐 多语言检测测试")
    print("  [a] ⚙️  配置 / 切换环境")
    print("  [q] 退出")
    print("─" * 50)


def run_gateway(cfg: dict):
    """启动网关"""
    sys.path.insert(0, '.')
    from Toolkit import gateway
    gw = gateway.WordGateway(cfg)
    print(f"\n🛡️  网关已启动 | 环境: {gw.env_name} | 模型: {gw.model.provider}")
    print(f"📋 激活规则: {gw.policy.active_rule_names(gateway.work.InstinctGuard.ALL_RULES)}")
    print(f"🎯 Skills: {len(gw.skill_recommender.skills)} 个")
    print(f"{'─'*50}")
    print("💬 输入需求开始对话（'quit' 退出, 'stats' 查统计）:\n")

    while True:
        try:
            user_input = input("👤 > ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\n👋 再见！")
            break
        if not user_input:
            continue
        if user_input.lower() in ("quit", "exit", "q"):
            print("👋 再见！")
            break
        if user_input.lower() == "stats":
            print(json.dumps(gw.stats(), indent=2, ensure_ascii=False))
            continue

        result = gw.handle(user_input, interactive=True)
        print(f"\n{'═'*50}")
        print(f"📊 意图: {result.intent.get('category','?')}")
        print(f"🎯 Skills: {result.skills_used}")
        print(f"🛡️  守门: {result.guard_summary}")
        print(f"🔄 重试: {result.retries} | 最终: {result.final_action}")
        if result.verdict_id:
            print(f"⚖️  判决书: {result.verdict_id}")
        print(f"{'─'*50}")
        print(f"📤 输出:\n{result.model_output[:800]}")
        print()


def run_work(cfg: dict):
    """行为约束检测"""
    sys.path.insert(0, '.')
    from Toolkit import work
    ig = work.InstinctGuard()
    print("\n🧪 行为约束检测")
    print("─" * 40)
    print("输入要检测的代码（结束输入 Ctrl+D）:")
    try:
        code = sys.stdin.read()
    except KeyboardInterrupt:
        return
    results = ig.check_all(code)
    summary = ig.summary(results)
    print(f"\n📊 总计: {summary['total']} | ✅ {summary['passed']} | ❌ {summary['failed']}")
    for r in results:
        icon = "✅" if r.passed else "❌"
        print(f"  {icon} {r.rule}: {r.message}")


def run_snapshot(cfg: dict):
    """快照/回滚"""
    sys.path.insert(0, '.')
    from Toolkit import guardian
    g = guardian.Guardian()
    print("\n💾 快照管理")
    print("─" * 40)
    print("  [1] 创建快照")
    print("  [2] 列出快照")
    print("  [3] 回滚到指定快照")
    choice = input("选择: ").strip()
    if choice == "1":
        root = input("项目目录 [.]: ").strip() or "."
        sid = g.create_snapshot(root)
        print(f"✅ 快照创建: {sid}")
    elif choice == "2":
        snaps = g.list_snapshots()
        for s in snaps:
            print(f"  {s['id']}  {s.get('created','')}  ({s.get('file_count',0)} 文件)")
    elif choice == "3":
        sid = input("快照 ID: ").strip()
        root = input("回滚到目录 [.]: ").strip() or "."
        try:
            r = g.rollback(sid, root)
            print(f"✅ 回滚完成: {r}")
        except Exception as e:
            print(f"❌ 回滚失败: {e}")


def run_archive(cfg: dict):
    """Archive 测试"""
    sys.path.insert(0, '.')
    from Toolkit import Archive
    a = Archive.Archive("test_archive")
    print("\n🧠 长对话记忆测试")
    print("─" * 40)
    print("输入对话内容（Ctrl+D 结束）:")
    try:
        texts = sys.stdin.read().strip().split("\n")
    except KeyboardInterrupt:
        return
    for t in texts:
        t = t.strip()
        if t:
            r = a.remember("demo", t)
            flag = ""
            if r.get("urgency"):
                flag += "⚡"
            if r.get("topic_shift"):
                flag += "🔄"
            if r.get("short_input"):
                flag += "📝"
            print(f"  {flag} {t[:50]}")
    print(f"\n📤 上下文注入:\n{a.context_inject('demo')}")


def run_shiyun(cfg: dict):
    """叙事工厂"""
    sys.path.insert(0, '.')
    from Toolkit import shiyun
    s = shiyun.Shiyun()
    genres = s.list_genres()
    print(f"\n📖 叙事工厂 — 共 {len(genres)} 种题材")
    print("─" * 40)
    for i, g in enumerate(genres, 1):
        print(f"  [{i}] {g}")
    choice = input(f"\n选择题材 (1-{len(genres)}): ").strip()
    try:
        idx = int(choice) - 1
        g = genres[idx]
    except (ValueError, IndexError):
        print("无效选择")
        return
    hooks = s.generate_hooks(g, 3)
    conflicts = s.list_conflicts(g)
    print(f"\n🎲 题材: {g}")
    print(f"  钩子: {hooks}")
    print(f"  冲突: {conflicts}")


def run_nuwa(cfg: dict):
    """POC 报告"""
    sys.path.insert(0, '.')
    from Toolkit import Nuwa, gateway
    n = Nuwa.Nuwa()
    # 启动一个临时网关采集指标
    gw = gateway.WordGateway(cfg)
    n.collect_from_gateway(gw.stats())
    report = n.generate("POC 报告")
    print(f"\n📊 {report.summary}")
    print(f"📄 HTML + JSON 已保存到 poc_reports/")


def run_jury(cfg: dict):
    """查看判决书"""
    sys.path.insert(0, '.')
    from Toolkit import guardian
    j = guardian.RollbackJury("verdicts")
    verdicts = j.list_verdicts()
    if not verdicts:
        print("\n⚖️  暂无判决书")
        return
    stats = j.stats()
    print(f"\n⚖️  判决书统计: {stats['total']} 份")
    print("─" * 40)
    for v in verdicts[-10:]:
        print(f"  {v['verdict_id']}  [{v['severity'].upper()}] {v['rule_violated']}")


def run_radiation(cfg: dict):
    """辐射检测"""
    sys.path.insert(0, '.')
    from Toolkit import Nuwa
    rd = Nuwa.RadiationDetector(".")
    f = input("\n☢️  输入要检测的文件路径: ").strip()
    if not f or not Path(f).exists():
        print("文件不存在")
        return
    alerts = rd.scan(f)
    if not alerts:
        print("✅ 无辐射告警")
        return
    print(rd.generate_report(alerts))


def run_multilang(cfg: dict):
    """多语言检测测试"""
    sys.path.insert(0, '.')
    from Toolkit import work
    ml = work.MultiLangASTEngine()
    print(f"\n🌐 支持语言: {list(ml.languages.keys())}")
    f = input("输入要检测的文件路径: ").strip()
    if not f or not Path(f).exists():
        print("文件不存在")
        return
    code = Path(f).read_text(encoding="utf-8")
    result = ml.check(code, f)
    print(f"  语言: {result['language']}")
    print(f"  通过: {result['passed']}")
    if result['violations']:
        for v in result['violations']:
            print(f"  ❌ {v['rule']} ({v['on_fail']})")


def main():
    cfg = load_config()
    if not cfg.get("model", {}).get("api_key"):
        cfg = interactive_config(cfg)

    while True:
        show_menu(cfg)
        try:
            choice = input("👉 选择: ").strip().lower()
        except (KeyboardInterrupt, EOFError):
            print("\n👋 再见！")
            break

        if choice == "q" or choice == "quit":
            print("👋 再见！")
            break
        elif choice == "1":
            run_gateway(cfg)
        elif choice == "2":
            run_work(cfg)
        elif choice == "3":
            run_snapshot(cfg)
        elif choice == "4":
            run_archive(cfg)
        elif choice == "5":
            run_shiyun(cfg)
        elif choice == "6":
            run_nuwa(cfg)
        elif choice == "7":
            run_jury(cfg)
        elif choice == "8":
            run_radiation(cfg)
        elif choice == "9":
            run_multilang(cfg)
        elif choice == "a":
            cfg = interactive_config(cfg)
        else:
            print("无效选择")


if __name__ == "__main__":
    main()
