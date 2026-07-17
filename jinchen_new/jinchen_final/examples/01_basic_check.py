"""
示例 1：最小可用 —— 检测一段违规代码

运行: python examples/01_basic_check.py
"""

import sys
sys.path.insert(0, ".")

from Toolkit.work import InstinctGuard

guard = InstinctGuard()

# 一段有 3 个问题的代码
code = '''
import json
import os

api_key = "sk-1234567890abcdef12345678"

def get_user(uid):
    query = "SELECT * FROM users WHERE id = " + uid
    cursor.execute(query)
    return cursor.fetchall()
'''

results = guard.check_all(code)

print("=" * 50)
print("  🛡️ 检测结果")
print("=" * 50)

for r in results:
    icon = "❌" if not r.passed else "✅"
    print(f"  {icon} {r.rule:25s} {r.message}")

print()
print(guard.summary(results))
