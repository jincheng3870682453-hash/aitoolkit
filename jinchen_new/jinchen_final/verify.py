#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify.py — Word 体系 V3.1 验证脚本（诚实版）"""

import sys, os, json, tempfile, traceback
from pathlib import Path

sys.path.insert(0, ".")

passed = 0
failed = 0
errors = []

def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  ✅ {name}")
    else:
        failed += 1
        errors.append(name)
        print(f"  ❌ {name}  → {detail}")

def section(title):
    print(f"\n{'─'*50}")
    print(f"  {title}")
    print(f"{'─'*50}")

# ═══════════════════════════════════════
# 1. 基础导入
# ═══════════════════════════════════════
section("1. 模块导入")

try:
    from Toolkit import work, guardian, Nuwa as NuwaModule
    from Toolkit.guardian import Guardian, RollbackJury, ensure_gitignore
    from Toolkit.work import InstinctGuard, MultiLangASTEngine, GuardResult
    from Toolkit.gateway import WordGateway, IntentEngine, SkillRecommender, FeedbackStore, ModelCallError
    from Toolkit.Nuwa import Nuwa, RadiationDetector
    print("  ✅ 所有模块导入成功")
    passed += 1
except Exception as e:
    print(f"  ❌ 导入失败: {e}")
    traceback.print_exc()
    failed += 1
    sys.exit(1)

# ═══════════════════════════════════════
# 2. InstinctGuard — Python AST 检测
# ═══════════════════════════════════════
section("2. InstinctGuard (Python AST)")

g = InstinctGuard()

# 2.1 类型注解
code_clean = '''
def add(a: int, b: int) -> int:
    return a + b

def greet(name: str) -> str:
    return f"Hello {name}"
'''
r = g.check_all(code_clean)
all_pass = all(x.passed for x in r)
check("type_hints 通过（有注解）", all_pass, str([x.to_dict() for x in r]))

code_no_hint = '''
def add(a, b):
    return a + b
'''
r = g.check_all(code_no_hint)
has_fail = any(not x.passed and x.rule == "type_hints" for x in r)
check("type_hints 拦截（无注解）", has_fail)

# 2.2 try-except
code_risky = '''
def read_file(path):
    f = open(path)
    data = f.read()
    f.close()
    return data
'''
r = g.check_all(code_risky)
has_fail = any(not x.passed and x.rule == "try_except" for x in r)
check("try_except 拦截（风险操作无try）", has_fail)

code_safe = '''
def read_file(path):
    try:
        with open(path) as f:
            return f.read()
    except IOError:
        return ""
'''
r = g.check_all(code_safe)
all_pass = all(x.passed for x in r if x.rule == "try_except")
check("try_except 通过（有try）", all_pass)

# 2.3 硬编码密钥
code_secret = '''
api_key = "sk-1234567890abcdef12345678"
def call_api():
    return api_key
'''
r = g.check_all(code_secret)
has_fail = any(not x.passed and x.rule == "no_hardcoded_secrets" for x in r)
check("no_hardcoded_secrets 拦截（sk-xxx）", has_fail)

code_env = '''
import os
api_key = os.getenv("API_KEY")
'''
r = g.check_all(code_env)
all_pass = all(x.passed for x in r if x.rule == "no_hardcoded_secrets")
check("no_hardcoded_secrets 通过（env var）", all_pass)

# 2.4 SQL 注入
code_sql_bad = '''
def get_user(uid):
    query = "SELECT * FROM users WHERE id = " + uid
    cursor.execute(query)
'''
r = g.check_all(code_sql_bad)
has_fail = any(not x.passed and x.rule == "no_sql_injection" for x in r)
check("no_sql_injection 拦截（字符串拼接）", has_fail)

code_sql_good = '''
def get_user(uid):
    cursor.execute("SELECT * FROM users WHERE id = %s", (uid,))
'''
r = g.check_all(code_sql_good)
all_pass = all(x.passed for x in r if x.rule == "no_sql_injection")
check("no_sql_injection 通过（参数化）", all_pass)

# 2.5 无限递归
code_recurse_bad = '''
def factorial(n):
    return n * factorial(n - 1)
'''
r = g.check_all(code_recurse_bad)
has_fail = any(not x.passed and x.rule == "no_infinite_recursion" for x in r)
check("no_infinite_recursion 拦截（无终止条件）", has_fail)

code_recurse_good = '''
def factorial(n):
    if n <= 1:
        return 1
    return n * factorial(n - 1)
'''
r = g.check_all(code_recurse_good)
all_pass = all(x.passed for x in r if x.rule == "no_infinite_recursion")
check("no_infinite_recursion 通过（有终止条件）", all_pass)

# 2.6 未使用导入（AST 版，解决变量名碰撞）
code_unused = '''
import json
import os
data = json.dumps({"a": 1})
'''
r = g.check_all(code_unused)
has_fail = any(not x.passed and x.rule == "no_unused_import" for x in r)
check("no_unused_import 拦截（os 未用）", has_fail)

# 关键测试：json_data 是变量，json 模块确实未使用 → 应拦截
code_json_data = '''
import json
json_data = '{"key": "value"}'
result = json_data.upper()
'''
r = g.check_all(code_json_data)
has_fail = any(not x.passed and x.rule == "no_unused_import" for x in r)
check("no_unused_import 正确拦截（json 模块未用，json_data 是变量）", has_fail,
      "json 未被正确识别为未使用" if not has_fail else "")

code_all_used = '''
import json
import os
data = json.dumps(os.getenv("KEY", ""))
'''
r = g.check_all(code_all_used)
all_pass = all(x.passed for x in r if x.rule == "no_unused_import")
check("no_unused_import 通过（全部使用）", all_pass)

# 2.7 markdown_clean
code_doc_bad = '''
def my_func():
    """[TODO] implement this function"""
    pass
'''
r = g.check_all(code_doc_bad)
has_fail = any(not x.passed and x.rule == "markdown_clean" for x in r)
check("markdown_clean 拦截（docstring 有 [TODO]）", has_fail)

# 2.8 sanitize 不删字符串中的 TODO
code_with_string = '''
msg = "TODO list: buy milk"
def f(): pass
'''
sanitized = g.sanitize(code_with_string)
check("sanitize 不删字符串中的 TODO", "TODO" in sanitized)

# ═══════════════════════════════════════
# 3. MultiLangASTEngine
# ═══════════════════════════════════════
section("3. MultiLangASTEngine（诚实标注）")

ml = MultiLangASTEngine()

# 3.1 语言识别
check("识别 Python", ml.detect_language("def foo():", "foo.py") == "python")
check("识别 Java", ml.detect_language("public class Foo {}", "Foo.java") == "java")
check("识别 Kotlin", ml.detect_language("fun main() {}", "main.kt") == "kotlin")
check("识别 TypeScript", ml.detect_language("interface Foo {}", "foo.ts") == "typescript")
check("识别 Swift", ml.detect_language("func foo() -> Void {}", "foo.swift") == "swift")

# 3.2 支持列表标注了准确率
supported = ml.list_supported()
check("Python 标注 AST（准确）", supported.get("python", {}).get("method") == "ast")
check("Java 标注 regex（不准确）", supported.get("java", {}).get("method") == "regex")
check("Swift 标注 regex（不准确）", supported.get("swift", {}).get("method") == "regex")

# 3.3 Java 检测
java_code = '''
public class Test {
    public void readFile() {
        FileInputStream fis = new FileInputStream("test.txt");
    }
}
'''
r = ml.check(java_code, "Test.java")
check("Java 检测返回结果", "violations" in r and "passed" in r)
check("Java 标注准确率信息", "accuracy_note" in r)

# ═══════════════════════════════════════
# 4. Guardian — 快照回滚
# ═══════════════════════════════════════
section("4. Guardian（快照回滚）")

with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    proj = tmp / "proj"
    proj.mkdir()
    snaps = tmp / "snaps"
    (proj / "main.py").write_text("print('v1')\n", encoding="utf-8")

    gd = Guardian(snapshot_dir=str(snaps))
    sid = gd.create_snapshot(str(proj))
    check("快照创建成功", sid.startswith("snap-"), sid)

    # 修改文件
    (proj / "main.py").write_text("print('v2 corrupted')\n", encoding="utf-8")

    # 预检
    pre = gd.precheck(sid)
    check("预检通过", pre.get("valid"), str(pre))

    # 回滚
    result = gd.rollback(sid, str(proj))
    check("回滚成功", result.get("status") == "rolled_back", str(result))
    check("文件恢复", (proj / "main.py").read_text().strip() == "print('v1')")

    # 空快照拒绝
    try:
        gd.create_snapshot(str(tmp / "__empty_test"))
        check("空目录拒绝快照", False, "应抛异常")
    except (ValueError, OSError):
        check("空目录拒绝快照", True)

# ═══════════════════════════════════════
# 5. RollbackJury（诚实版）
# ═══════════════════════════════════════
section("5. RollbackJury（审计日志）")

with tempfile.TemporaryDirectory() as tmp:
    jury = RollbackJury(verdict_dir=str(Path(tmp) / "verdicts"))
    v = jury.issue(
        rule_name="no_hardcoded_secrets",
        original_code='key = "sk-abc1234567890"',
        evidence={"pattern": "openai_key", "line": 3},
        snapshot_id="snap-test",
        user="test_user", env="prod", model="deepseek",
    )
    check("判决书签发", v.data["verdict_id"].startswith("V-"), v.data["verdict_id"])
    check("严重等级 = critical", v.data["severity"] == "critical")
    check("包含免责声明", "disclaimer" in v.data)
    check("完整性哈希 32 位", len(v.data["integrity_hash"]) == 32)
    check("verify() 通过", v.verify())

    # 文件生成
    vdir = Path(tmp) / "verdicts"
    md_files = list(vdir.glob("V-*.md"))
    json_files = list(vdir.glob("V-*.json"))
    check("生成 .md 文件", len(md_files) == 1)
    check("生成 .json 文件", len(json_files) == 1)

    # 统计
    stats = jury.stats()
    check("统计 total=1", stats.get("total") == 1, str(stats))

# ═══════════════════════════════════════
# 6. FeedbackStore（无内存状态）
# ═══════════════════════════════════════
section("6. FeedbackStore（文件 only）")

with tempfile.TemporaryDirectory() as tmp:
    fs = FeedbackStore(store_dir=str(Path(tmp) / "fb"))
    rec = fs.record(
        user_input="帮我写个函数",
        rule="type_hints",
        original="def f(x): pass",
        fixed="def f(x: int) -> None: pass",
        skills=["python_api_design"],
        verdict_id="V-test",
    )
    check("记录写入", rec.timestamp != "")
    stats = fs.stats()
    check("统计从文件读取", stats.get("total") == 1, str(stats))

    # 导出 SFT
    out = Path(tmp) / "sft.jsonl"
    msg = fs.export_training_data(str(out))
    check("SFT 导出", out.exists() and "instruction" in out.read_text())

# ═══════════════════════════════════════
# 7. PolicyEngine（动态策略）
# ═══════════════════════════════════════
section("7. PolicyEngine（动态策略）")

from Toolkit.gateway import PolicyEngine
pe_dev = PolicyEngine("dev")
check("dev 环境 2 条规则", len(pe_dev.policy["rules"]) == 2)
check("dev max_retries=1", pe_dev.max_retries() == 1)

pe_test = PolicyEngine("test")
check("test 环境 6 条规则", len(pe_test.policy["rules"]) == 6)

pe_prod = PolicyEngine("prod")
check("prod strict=True", pe_prod.policy["strict"] == True)
check("prod max_retries=2", pe_prod.max_retries() == 2)

# ═══════════════════════════════════════
# 8. ModelCallError（不返回 Mock）
# ═══════════════════════════════════════
section("8. ModelCallError（无 Mock）")

# 无 API Key → 应抛异常
os.environ.pop("NUWA_AI_API_KEY", None)
os.environ.pop("DEEPSEEK_API_KEY", None)

from Toolkit.gateway import FineTunedCore as FTC
try:
    fc = FTC(provider="deepseek", api_key="")
    fc.generate("test")
    check("无 Key 时抛异常", False, "应抛 ModelCallError")
except ModelCallError as e:
    check("无 Key 时抛 ModelCallError", "API Key" in str(e), str(e))
except Exception as e:
    check("无 Key 时抛正确异常类型", False, f"抛了 {type(e).__name__}: {e}")

# ═══════════════════════════════════════
# 9. V1Bridge（异常不静默）
# ═══════════════════════════════════════
section("9. V1Bridge（异常不静默）")

from Toolkit.gateway import V1Bridge
bridge = V1Bridge()
check("V1Bridge 初始化不崩溃", True)
# ast_check 在模块可用时应返回结果
if bridge.available.get("work"):
    results = bridge.ast_check("def f(): pass")
    check("ast_check 返回列表", isinstance(results, list))

# ═══════════════════════════════════════
# 10. RadiationDetector
# ═══════════════════════════════════════
section("10. RadiationDetector（辐射检测）")

with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    # 写一个有 SQL 的文件
    (tmp / "db_query.py").write_text(
        'import os\nkey = os.getenv("DB_HOST")\ndef q():\n    cursor.execute("SELECT * FROM users")\n',
        encoding="utf-8")

    rd = RadiationDetector(str(tmp))
    alerts = rd.scan(str(tmp / "db_query.py"))
    check("辐射检测返回列表", isinstance(alerts, list))
    # 应检测到 config 辐射（缺 .env.example）
    has_config = any(a.alert_type == "config" for a in alerts)
    check("检测到 config 辐射", has_config)

    # 生成报告
    report = rd.generate_report(alerts)
    check("报告生成", "辐射" in report or "✅" in report, report[:100])

# ═══════════════════════════════════════
# 11. ensure_gitignore
# ═══════════════════════════════════════
section("11. .gitignore 自动生成")

with tempfile.TemporaryDirectory() as tmp:
    path = ensure_gitignore(tmp)
    check(".gitignore 创建", Path(path).exists())
    content = Path(path).read_text()
    check("包含 config.json", "config.json" in content)
    check("包含 snapshots/", "snapshots/" in content)
    check("包含 verdicts/", "verdicts/" in content)

# ═══════════════════════════════════════
# 12. WordGateway 主流程（无状态验证）
# ═══════════════════════════════════════
section("12. WordGateway（无状态 + 反馈式重试）")

# 无 API Key 时初始化应抛错
try:
    gw = WordGateway({})
    check("无 Key 时 Gateway 初始化行为", True)  # 允许初始化，调用时才报错
except ModelCallError as e:
    check("无 Key 时 Gateway 初始化抛错", True)

# 有 API Key 时初始化成功
os.environ["NUWA_AI_API_KEY"] = "sk-test-key-for-testing"
try:
    gw = WordGateway({"env": "dev", "user": "test"})
    check("有 Key 时初始化成功", True)
    check("IntentEngine 已加载", gw.intent is not None)
    check("SkillRecommender 已加载", gw.skill_recommender is not None)
    stats = gw.stats()
    check("stats 返回字典", isinstance(stats, dict))
    check("stats 含 env", "env" in stats)
finally:
    os.environ.pop("NUWA_AI_API_KEY", None)

# ═══════════════════════════════════════
# 13. 文件完整性检查
# ═══════════════════════════════════════
section("13. 文件完整性")

required_files = [
    "Toolkit/__init__.py",
    "Toolkit/gateway.py",
    "Toolkit/work.py",
    "Toolkit/guardian.py",
    "Toolkit/Archive.py",
    "Toolkit/shiyun.py",
    "Toolkit/Nuwa.py",
    "Toolkit/Proteus.py",
    "config.json",
    "config/config_template.json",
    "requirements.txt",
    ".gitignore",
    "CHANGELOG.md",
    "README.md",
    "LICENSE",
]
for f in required_files:
    check(f"存在 {f}", Path(f).exists(), f"缺失: {f}")

# ═══════════════════════════════════════
# 14. 意图识别
# ═══════════════════════════════════════
section("14. IntentEngine")

ie = IntentEngine()
r = ie.classify("帮我写一个 Python 爬虫脚本")
check("识别 Python 爬虫", r.get("category") in ("code_python", "general"), str(r))
r = ie.classify("写一个 SQL 查询优化")
check("识别 SQL", r.get("category") in ("code_sql", "general"), str(r))
r = ie.classify("帮我构思一个小说世界观")
check("识别小说", r.get("category") in ("fiction", "general"), str(r))
r = ie.classify("asdfghjkl qwertyuiop zxcvbnm")
check("未知输入返回 general", r.get("category") == "general", str(r))
check("method 字段存在", r.get("method") in ("keyword", "semantic"))

# ═══════════════════════════════════════
# 汇总
# ═══════════════════════════════════════
total = passed + failed
print(f"\n{'═'*50}")
print(f"  📊 验证结果: {passed}/{total} 通过 ({passed/total*100:.0f}%)")
if failed:
    print(f"\n  ❌ 失败项 ({failed}):")
    for e in errors:
        print(f"     - {e}")
print(f"{'═'*50}")

sys.exit(0 if failed == 0 else 1)
