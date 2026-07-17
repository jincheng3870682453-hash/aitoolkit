"""
examples/05_github_scout.py —— 演示 github_scout 的完整用法

模拟场景：
  用户给了 GitHub 链接 + README 里的目录结构
  → 自动拼 URL → 拉取文件 → 压缩成 prompt → 搜不到时反问用户
"""

import sys
import logging
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from Toolkit import github_scout as gs


# ═══════════════════════════════════════════
#  模拟的 README 目录结构（从 GitHub 页面抓到的文本）
# ═══════════════════════════════════════════
FAKE_README = """
├── Toolkit/
│   ├── __init__.py
│   ├── gateway.py
│   ├── work.py
│   ├── guardian.py
│   ├── Archive.py
│   ├── shiyun.py
│   ├── Nuwa.py
│   ├── Proteus.py
│   ├── enhancements.py
│   └── skills/
│       ├── python_api_design.skill
│       ├── error_handling.skill
│       ├── sql_safety.skill
│       ├── code_refactor.skill
│       ├── markdown_format.skill
│       ├── interactive_ux.skill
│       └── fiction_writing.skill
├── config/
│   └── config_template.json
├── examples/
│   ├── 01_basic_check.py
│   ├── 02_snapshot_rollback.py
│   ├── 03_full_gateway.py
│   ├── 04_token_saving.py
│   └── dataset/
│       └── sample_dataset.json
├── .gitignore
├── .gitattributes
├── CHANGELOG.md
├── CONTRIBUTING.md
├── README.md
├── LICENSE
├── config.json
├── evaluate.py
├── verify.py
├── verify_real.py
├── requirements.txt
└── snapshots/

jimcheng3870682453-hash/jinchen
https://github.com/jimcheng3870682453-hash/jinchen
"""


def main():
    print("=" * 60)
    print("  🔍 GithubScout 演示")
    print("  模拟：用户给了 GitHub 链接 + README 目录结构")
    print("=" * 60)
    print()

    # ── Step 1: 解析 GitHub 链接 ──────────────────
    print("📌 Step 1: 解析 GitHub 链接")
    scout = gs.GithubScout("https://github.com/jimcheng3870682453-hash/jinchen")
    print(f"  user:   {scout.repo.user}")
    print(f"  repo:   {scout.repo.repo}")
    print(f"  branch: {scout.repo.branch}")
    print(f"  raw:    {scout.repo.raw_base}")
    print()

    # ── Step 2: 从 README 文本提取文件列表 ────────
    print("📌 Step 2: 从 README 目录树提取文件列表")
    files = scout.parse_structure(FAKE_README)
    print(f"  提取到 {len(files)} 个文件:")
    for f in files[:15]:
        print(f"    📄 {f}")
    if len(files) > 15:
        print(f"    ... 还有 {len(files)-15} 个")
    print()

    # ── Step 3: 展示拼出来的 URL ────────────────
    print("📌 Step 3: 自动拼出的文件 URL（前5个）")
    for path in sorted(scout.files.keys())[:5]:
        node = scout.files[path]
        print(f"  {path}")
        print(f"    → {node.url}")
    print()

    # ── Step 4: 搜索文件演示 ──────────────────────
    print("📌 Step 4: 搜索文件")
    query = "gateway"
    results = scout.find(query)
    print(f"  搜 '{query}' → {results}")
    print()

    query2 = ".py"
    results2 = scout.find_by_ext("py")
    print(f"  所有 .py 文件 ({len(results2)} 个):")
    for r in results2[:10]:
        print(f"    🐍 {r}")
    print()

    # ── Step 5: 搜不到时反问用户 ──────────────────
    print("📌 Step 5: 搜不到时反问用户")
    question = scout.ask_user("nonexistent_file.py")
    print(question)
    print()

    # ── Step 6: 生成给 AI 的系统上下文 ──────────
    print("📌 Step 6: 生成 system prompt 上下文（短版）")
    sys_ctx = scout.build_system_context()
    print(sys_ctx)
    print()

    # ── Step 7: 统计信息 ──────────────────────────
    print("📌 Step 7: 统计")
    s = scout.stats()
    print(f"  {s}")
    print()

    # ── Step 8: 如果有 requests，尝试真实拉取 ──────
    print("📌 Step 8: 尝试拉取真实文件")
    try:
        import requests  # noqa
        results = scout.fetch_all(timeout=8)
        ok = sum(1 for v in results.values() if v)
        total = len(results)
        print(f"  拉取结果: {ok}/{total} 成功")
        for path, ok_flag in list(results.items())[:8]:
            icon = "✅" if ok_flag else "❌"
            node = scout.files[path]
            info = f"{node.size} chars" if ok_flag else node.error
            print(f"    {icon} {path} ({info})")

        if ok > 0:
            print()
            print("📌 Step 9: 生成完整 prompt（截取前1500字）")
            prompt = scout.to_prompt()
            print(prompt[:1500])
            print("...")
    except ImportError:
        print("  ⚠️ requests 未安装，跳过真实拉取")
        print("  安装: pip install requests")
    except Exception as e:
        print(f"  ⚠️ 拉取失败: {e}")

    print()
    print("=" * 60)
    print("  ✅ 演示完毕")
    print("=" * 60)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="  %(message)s")
    main()
