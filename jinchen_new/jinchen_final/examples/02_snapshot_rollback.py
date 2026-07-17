"""
示例 2：快照回滚 —— 在 AI 搞坏代码前保护自己

运行: python examples/02_snapshot_rollback.py
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, ".")

from Toolkit.guardian import Guardian

with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    proj = tmp / "my_project"
    proj.mkdir()

    # 你辛苦写的代码
    (proj / "main.py").write_text(
        'def greet(name):\n    return f"Hello, {name}!"\n\n'
        'if __name__ == "__main__":\n    print(greet("World"))\n',
        encoding="utf-8",
    )

    print("📄 原始代码:")
    print(proj.joinpath("main.py").read_text())
    print()

    # 创建快照（AI 搞事前的保险）
    gd = Guardian(snapshot_dir=str(tmp / "snaps"))
    sid = gd.create_snapshot(str(proj))
    print(f"💾 快照已创建: {sid}")
    print()

    # AI 搞坏了你的代码（模拟）
    (proj / "main.py").write_text(
        'def greet(name):\n    return name + undefined_variable\n',
        encoding="utf-8",
    )
    print("💥 AI 搞坏了代码:")
    print(proj.joinpath("main.py").read_text())
    print()

    # 一键回滚
    result = gd.rollback(sid, str(proj))
    print(f"🔄 回滚完成: {result['status']}")
    print()
    print("✅ 恢复后的代码:")
    print(proj.joinpath("main.py").read_text())
