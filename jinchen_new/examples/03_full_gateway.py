"""
示例 3：完整网关调用 —— 从意图识别到守门的全流程

运行: python examples/03_full_gateway.py
（需要配置 API Key 才能实际调用模型）
"""

import sys
import os
sys.path.insert(0, ".")

# 如果没有真实 API Key，用环境变量模拟
if not os.environ.get("NUWA_AI_API_KEY"):
    os.environ["NUWA_AI_API_KEY"] = "sk-test-key-for-demo"
    print("⚠️ 未检测到 NUWA_AI_API_KEY，使用测试 Key（模型调用会失败）")
    print("   设置真实 Key: export NUWA_AI_API_KEY=sk-xxx")
    print()

from Toolkit.gateway import WordGateway, ModelCallError

# 初始化网关（dev 环境 = 宽松策略）
config = {
    "env": "dev",
    "user": "demo_user",
    "skill_dir": "Toolkit/skills",
}

print("🚀 初始化 WordGateway (dev 环境)...")
try:
    gw = WordGateway(config)
    print("  ✅ 初始化成功")
    print(f"  环境: {gw.env}")
    print(f"  Skill 数量: {len(gw.skill_recommender.skills)}")
    print(f"  意图引擎: {gw.intent.method}")
    print()

    # 模拟一次调用（会失败，因为没有真实 Key，但流程完整）
    print("📡 发起请求: '帮我写一个 Python 登录验证函数'")
    print()

    try:
        result = gw.handle("帮我写一个 Python 登录验证函数")
        print("📤 结果:")
        print(result[:500])
    except ModelCallError as e:
        print(f"⚠️ 模型调用失败（预期行为）: {e}")
        print()
        print("   这说明系统正常工作——没有 Key 就不返回假数据。")
        print("   配置真实 Key 后就能正常调用了。")

except Exception as e:
    print(f"❌ 初始化失败: {e}")
    sys.exit(1)

print()
print("📊 网关统计:")
stats = gw.stats()
for k, v in stats.items():
    print(f"  {k}: {v}")
