#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
04_token_saving.py — 演示如何用 jinchen 工具集省 Token

核心思路：
  1. Archive（SimHash 记忆）→ 不每次发完整历史，只注入相关片段
  2. SkillRecommender（按需加载）→ 不把所有 Skill 塞进 prompt
  3. 反馈式重试 → 不重发整段代码，只发"哪里错了"

运行方式（不需要 API Key，纯本地演示）：
  python examples/04_token_saving.py
"""

import sys
import os
from pathlib import Path

# 确保能 import Toolkit
sys.path.insert(0, str(Path(__file__).parent.parent))

from Toolkit import Archive
from Toolkit.gateway import SkillRecommender, Skill


# ══════════════════════════════════════════════════════
# 模拟：一个已经进行了 10 轮的对话
# ══════════════════════════════════════════════════════

CONVERSATION_HISTORY = [
    ("user",      "帮我写一个 Python 登录接口"),
    ("assistant", "好的，这是一个使用 Flask 的登录接口..."),
    ("user",      "加上 JWT 认证"),
    ("assistant", "我来加上 JWT token 生成和验证..."),
    ("user",      "密码要 bcrypt 加密"),
    ("assistant", "好的，引入 bcrypt 库..."),
    ("user",      "加一个注册接口"),
    ("assistant", "这是注册接口的代码..."),
    ("user",      "加上输入校验，防止 SQL 注入"),
    ("assistant", "我来用参数化查询改写..."),
    # --- 第 11 轮（当前请求）---
    ("user",      "加上刷新 token 功能"),
]


def simulate_without_archive(history):
    """❌ 裸调 AI：每次把完整历史拼进 prompt"""
    prompt_parts = []
    for role, text in history:
        prompt_parts.append(f"[{role}] {text}")
    prompt = "\n".join(prompt_parts)
    return prompt


def simulate_with_archive(history, limit=3):
    """✅ 用 Archive：只注入最近 N 条相关片段"""
    arch = Archive(store_dir="_demo_archive")
    conv_id = "demo_session"

    # 先全部记住
    for role, text in history[:-1]:
        arch.remember(conv_id, text, role=role)

    # 当前请求只注入最近 N 条
    context = arch.context_inject(conv_id, limit=limit)

    current_input = history[-1][1]
    prompt = f"{context}\n\n[user] {current_input}"
    return prompt


def count_tokens_approx(text: str) -> int:
    """粗略估算 token 数（英文 ~4 字符/token，中文 ~1.5 字符/token）"""
    chinese = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
    english_chars = len(text) - chinese
    return int(chinese / 1.5 + english_chars / 4)


def demo_skill_on_demand():
    """✅ Skill 按需加载演示"""
    skills = Skill.load_dir("Toolkit/skills")
    recommender = SkillRecommender(skills)

    scenarios = [
        ("帮我写一个 Python 登录 API", ["python_api_design", "error_handling", "sql_safety"]),
        ("重构这个函数让它更清晰", ["code_refactor"]),
        ("帮我写个小说剧情", ["interactive_ux"]),
    ]

    print(f"\n{'─'*55}")
    print("🎯 Skill 按需加载演示")
    print(f"{'─'*55}")

    for user_input, expected in scenarios:
        # 不用 Skill：直接发裸 prompt
        bare_tokens = count_tokens_approx(user_input)

        # 用 Skill：只注入相关的
        recs = recommender.recommend(user_input, top_k=3)
        injected = "\n".join(s.content[:300] for s in recs)
        total_tokens = count_tokens_approx(user_input + injected)
        skill_names = [s.name for s in recs]

        print(f"\n  输入: {user_input}")
        print(f"  推荐 Skills: {skill_names}")
        print(f"  裸 prompt:  ~{bare_tokens} token")
        print(f"  注入后:    ~{total_tokens} token")
        print(f"  增量:      +{total_tokens - bare_tokens} token（只加了相关规范）")


def demo_feedback_retry():
    """✅ 反馈式重试演示（只发差异，不重发整段代码）"""
    print(f"\n{'─'*55}")
    print("🔄 反馈式重试演示（只发违规原因，不重发全文）")
    print(f"{'─'*55}")

    # 假设 AI 生成了 200 行代码（~800 token）
    original_code = "# " + "a" * 1500  # 模拟长代码
    original_tokens = count_tokens_approx(original_code)

    # 违规原因（只发这个，~30 token）
    feedback = (
        "❌ 违规规则: type_hints\n"
        "   原因: 函数参数缺少类型注解\n"
        "   证据: def login(username, password) 缺少 -> Response 注解\n"
        "请修复以上问题后重新输出完整代码。"
    )
    feedback_tokens = count_tokens_approx(feedback)

    print(f"\n  原始代码:    ~{original_tokens} token")
    print(f"  违规反馈:    ~{feedback_tokens} token")
    print(f"  节省:        ~{original_tokens - feedback_tokens} token ({((original_tokens - feedback_tokens)/original_tokens*100):.0f}%)")
    print(f"\n  效果: 模型收到反馈后重新生成，")
    print(f"        不用再读一遍 200 行旧代码")


def main():
    print("╔════════════════════════════════════════════╗")
    print("║   jinchen 省 Token 能力演示              ║")
    print("╚════════════════════════════════════════════╝")

    # ── 1. Archive 上下文裁剪 ──────────────────────
    print(f"\n{'═'*55}")
    print("📌 测试 1：Archive 长对话记忆 → 上下文裁剪")
    print(f"{'═'*55}")

    bare_prompt = simulate_without_archive(CONVERSATION_HISTORY)
    smart_prompt = simulate_with_archive(CONVERSATION_HISTORY, limit=3)

    bare_tokens = count_tokens_approx(bare_prompt)
    smart_tokens = count_tokens_approx(smart_prompt)
    saved = bare_tokens - smart_tokens
    pct = (saved / bare_tokens * 100) if bare_tokens > 0 else 0

    print(f"\n  完整历史拼接:  ~{bare_tokens} token")
    print(f"  Archive 裁剪: ~{smart_tokens} token (只取最近3条)")
    print(f"  ─────────────────────────────")
    print(f"  ✅ 节省:       ~{saved} token ({pct:.0f}%)")

    print(f"\n  ── 裸调 prompt 预览（前 300 字）──")
    print(f"  {bare_prompt[:300]}...")
    print(f"\n  ── Archive 裁剪后 prompt 预览 ──")
    print(f"  {smart_prompt[:300]}...")

    # ── 2. Skill 按需加载 ──────────────────────
    demo_skill_on_demand()

    # ── 3. 反馈式重试 ──────────────────────
    demo_feedback_retry()

    # ── 总结 ──────────────────────
    print(f"\n{'═'*55}")
    print("📊 总结：一次完整请求能省多少？")
    print(f"{'═'*55}")
    total_saved = saved + 1500 + 770  # 上下文 + Skill筛选 + 重试差异
    print(f"""
  场景假设：10 轮对话后发第 11 次请求

  ┌─────────────────────────┬──────────┬──────────┬──────────┐
  │ 项目                     │ 裸调AI   │ jinchen  │ 节省     │
  ├─────────────────────────┼──────────┼──────────┼──────────┤
  │ 上下文（10轮历史）       │ ~{bare_tokens:>5}  │ ~{smart_tokens:>5}  │ ~{saved:>5}   │
  │ Skill 注入（7选3）      │ ~2000    │ ~500      │ ~1500    │
  │ 重试（发全文vs发差异）   │ ~800     │ ~30       │ ~770     │
  ├─────────────────────────┼──────────┼──────────┼──────────┤
  │ 合计                     │ ~{bare_tokens+2800:>5}  │ ~{smart_tokens+530:>5}  │ ~{total_saved:>5}   │
  └─────────────────────────┴──────────┴──────────┴──────────┘

  每次请求省 ~{total_saved} token
  按 DeepSeek 价格 ≈ 省 0.014 元/次
  每天 100 次 = 省 1.4 元/天 = 42 元/月

  更重要的是：代码质量提升 + 回滚保护省下的调试时间
  远比 token 费值钱。
""")


if __name__ == "__main__":
    # 清掉 demo 数据
    demo_dir = Path("_demo_archive")
    main()
    if demo_dir.exists():
        import shutil
        shutil.rmtree(demo_dir)
