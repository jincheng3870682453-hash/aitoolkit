"""
verify.py —— jinchen v3.2 综合验证

覆盖：
  - work.py: 13 条 AST 规则 + CodeMap + 突变测试 + 策略引擎
  - guardian.py: 快照完整性 + 回滚 + 判决书 + 熔断
  - Archive.py: SimHash + 主题切换 + 紧急度 + 短输入保护
  - Nuwa.py: POC 报告 + 辐射检测 + 关系图谱
  - gateway.py: 意图识别 + Skill 路由 + 反馈重试 + 省 Token
  - 外部工具融合验证：
    · CodeGraph 思路（关系图谱查询）
    · Headroom 思路（compressed_view 压缩率）
    · Skill Router 分层（L1-L5）
    · 突变测试质量门禁
    · 熔断器模式
"""

import sys
import os
import re
import json
import time
import shutil
import tempfile
import hashlib
import logging
from pathlib import Path
from contextlib import redirect_stdout, redirect_stderr
from io import StringIO

# ── 加载路径 ──────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).parent))

import Toolkit
from Toolkit import work, guardian, Archive, Nuwa, gateway

log = logging.getLogger("verify")
log.setLevel(logging.WARNING)  # 安静模式

PASSED = 0
FAILED = 0
FAILURES = []

def check(name, condition, detail=""):
    global PASSED, FAILED
    if condition:
        PASSED += 1
        print(f"  ✅ {name}")
    else:
        FAILED += 1
        FAILURES.append(name)
        print(f"  ❌ {name}  {detail}")


# ════════════════════════════════════════════════════
#  work.py 验证
# ════════════════════════════════════════════════════
print("\n🔧 work.py —— 核心规则引擎\n")

# 1. 硬编码密钥
code_secret = '''
import os
API_KEY = "sk-1234567890abcdef12345678"
def call_api():
    return requests.get("https://api.example.com", headers={"Authorization": f"Bearer {API_KEY}"})
'''
r = work.check(code_secret)
v_rules = [v.rule for v in r.violations]
check("硬编码密钥检测 (critical)", "no_hardcoded_secrets" in v_rules)
check("密钥违规等级=critical", any(v.severity == "critical" for v in r.violations if v.rule == "no_hardcoded_secrets"))

# 2. SQL 注入
code_sqli = '''
import sqlite3
def get_user(user_id):
    query = "SELECT * FROM users WHERE id=" + user_id
    cursor.execute(query)
'''
r = work.check(code_sqli)
v_rules = [v.rule for v in r.violations]
check("SQL 注入检测 (critical)", "no_sql_injection" in v_rules)

# 3. 类型注解
code_no_hint = '''
def add(a, b):
    return a + b
'''
r = work.check(code_no_hint)
v_rules = [v.rule for v in r.violations]
check("缺少类型注解检测 (medium)", "type_hints" in v_rules)

# 4. try-except
code_risky = '''
def read_file(path):
    f = open(path, 'r')
    return f.read()
'''
r = work.check(code_risky)
v_rules = [v.rule for v in r.violations]
check("危险操作缺 try-except (high)", "try_except" in v_rules)

# 5. 无限递归
code_recurse = '''
def factorial(n):
    return n * factorial(n-1)
'''
r = work.check(code_recurse)
v_rules = [v.rule for v in r.violations]
check("无限递归检测 (high)", "no_infinite_recursion" in v_rules)

# 6. 未使用 import（AST 精确检测）
code_unused = '''
import json
import os
def hello():
    return "hi"
'''
r = work.check(code_unused)
v_rules = [v.rule for v in r.violations]
check("未使用 import 检测 (low)", "no_unused_import" in v_rules)
# json 和 os 都未使用 → 至少 2 条
count_unused = sum(1 for v in r.violations if v.rule == "no_unused_import")
check("精确识别 2 个未使用 import", count_unused >= 2)

# 7. subprocess shell=True
code_shell = '''
import subprocess
subprocess.run("ls -la", shell=True)
'''
r = work.check(code_shell)
v_rules = [v.rule for v in r.violations]
check("subprocess shell=True 检测 (critical)", "no_subprocess_shell" in v_rules)

# 8. pickle 反序列化
code_pickle = '''
import pickle
data = pickle.loads(user_input)
'''
r = work.check(code_pickle)
v_rules = [v.rule for v in r.violations]
check("pickle 反序列化检测 (high)", "no_pickle_deserialize" in v_rules)

# 9. 全局可变状态
code_global = '''
config = {"debug": True}
def get_config():
    return config
'''
r = work.check(code_global)
v_rules = [v.rule for v in r.violations]
check("全局可变状态检测 (medium)", "no_global_mutable" in v_rules)

# 10. 裸 except
code_bare = '''
def risky():
    try:
        do_something()
    except:
        pass
'''
r = work.check(code_bare)
v_rules = [v.rule for v in r.violations]
check("裸 except 检测 (high)", "no_bare_except" in v_rules)

# 11. SQL 字符串拼接
code_sql_concat = '''
query = "SELECT * FROM users WHERE name='" + username + "'"
cursor.execute(query)
'''
r = work.check(code_sql_concat)
v_rules = [v.rule for v in r.violations]
check("SQL 字符串拼接检测 (critical)", "no_sql_string_concat" in v_rules)

# 12. Markdown 占位符
code_todo = '''
def process():
    return "[TODO: 实现这个功能]"
'''
r = work.check(code_todo)
v_rules = [v.rule for v in r.violations]
check("TODO 占位符检测 (low)", "markdown_clean" in v_rules)

# 13. AST 可解析性
code_syntax_error = 'def broken(('
r = work.check(code_syntax_error)
v_rules = [v.rule for v in r.violations]
check("语法错误检测 (medium)", "v1_ast_check" in v_rules)

# 14. 好代码通过
code_clean = '''
import os
from typing import List

def get_env(name: str) -> str:
    """获取环境变量"""
    try:
        return os.environ[name]
    except KeyError:
        return ""

def process_items(items: List[str]) -> int:
    """处理列表，返回数量"""
    try:
        return len(items)
    except Exception as e:
        log.error(f"Error: {e}")
        return 0
'''
r = work.check(code_clean)
check("合规代码通过", r.passed, f"违规: {[v.rule for v in r.violations]}")
check("合规代码 0 违规", len(r.violations) == 0, f"有 {len(r.violations)} 条")

# 15. CodeMap 代码地图
cm = work.CodeMap(code_clean)
check("CodeMap 提取函数", len(cm.functions) >= 2)
check("CodeMap 提取 import", len(cm.imports) >= 1)
check("CodeMap 计算圈复杂度", all('complexity' in f for f in cm.functions))
check("compressed_view 非空", bool(r.compressed_view))
# 压缩率测试（Headroom 思路验证）
original_lines = len(code_clean.strip().splitlines())
compressed_lines = len(r.compressed_view.strip().splitlines())
ratio = compressed_lines / max(original_lines, 1)
check(f"压缩率合理 ({ratio:.0%})", ratio < 0.8, f"压缩后 {compressed_lines}/{original_lines} 行")

# 16. 突变测试（mutatest 思路）
print("\n  🧪 突变测试（主动注入违规验证检测能力）:")
mutate_code = "def hello():\n    return 'world'\n"
rules_to_test = ["no_hardcoded_secrets", "no_sql_injection",
                 "no_subprocess_shell", "no_bare_except"]
result = work.mutation_test(mutate_code, rules_to_test)
check(f"突变检测 {result['detected']}/{result['total']}", 
      result['detected'] >= 3, f"missed: {result.get('missed', [])}")

# 17. 策略引擎
r_dev = work.check_with_policy(code_clean, "dev")
r_prod = work.check_with_policy(code_clean, "prod")
check("dev 策略: 合规通过", r_dev.passed)
check("prod 策略: 合规通过", r_prod.passed)

# 18. check_file
test_file = Path("__test_tmp.py")
test_file.write_text(code_clean, encoding="utf-8")
r_file = work.check_file(str(test_file))
check("check_file 正常", r_file.passed)
test_file.unlink(missing_ok=True)

# 19. 空输入
r_empty = work.check("")
check("空输入不崩溃", r_empty.passed)

# 20. get_compressed_view
cv = work.get_compressed_view(code_clean)
check("get_compressed_view 返回字符串", isinstance(cv, str) and len(cv) > 0)


# ════════════════════════════════════════════════════
#  guardian.py 验证
# ════════════════════════════════════════════════════
print("\n💾 guardian.py —— 快照与回滚\n")

# 临时目录
tmp = Path(tempfile.mkdtemp(prefix="jinchen_test_"))
try:
    # 创建测试文件
    (tmp / "main.py").write_text("print('v1')\n", encoding="utf-8")
    (tmp / "config.json").write_text('{"key": "val"}', encoding="utf-8")

    g = guardian.Guardian(root=str(tmp))

    # 快照
    sid = g.snapshot(name="test-snap")
    check("快照创建成功", isinstance(sid, str) and sid.startswith("snap-"))
    check("快照 zip 存在", (g._snapshot_path(sid)).exists())
    check("完整性文件存在", g._integrity_file(sid).exists())

    # 修改文件后回滚
    (tmp / "main.py").write_text("print('v2')\n", encoding="utf-8")
    result = g.rollback(sid)
    check("回滚成功", result is True or (hasattr(result, 'ok') and result.ok))
    content = (tmp / "main.py").read_text()
    check("回滚内容正确", "v1" in content)

    # 空目录拒绝
    empty_dir = tmp / "empty_sub"
    empty_dir.mkdir(exist_ok=True)
    g2 = guardian.Guardian(root=str(empty_dir))
    result = g2.snapshot(name="should-fail")
    check("空目录拒绝快照", isinstance(result, guardian.SafeResult))

    # 列表
    snaps = g.list_snapshots()
    check("快照列表非空", len(snaps) >= 1)

    # 完整性校验
    verify_result = g.verify_all()
    check("完整性校验通过", all(v.get("ok") for v in verify_result.values()))

    # 判决书
    jury = guardian.RollbackJury(verdict_dir=str(tmp / "verdicts"))
    v = jury.issue_verdict(
        rule_name="no_hardcoded_secrets",
        original_code="API_KEY = 'sk-test'",
        evidence={"matched": "sk-test"},
        fix_suggestion="用环境变量",
        snapshot_id=sid,
        user="tester", env="dev", model="deepseek",
    )
    check("判决书签发", v.verdict_id.startswith("V-"))
    check("判决书 JSON 保存", (tmp / "verdicts" / f"{v.verdict_id}.json").exists())
    check("判决书 MD 保存", (tmp / "verdicts" / f"{v.verdict_id}.md").exists())
    check("判决书含严重等级", "CRITICAL" in v.to_markdown() or "critical" in v.to_markdown())

    # safe_call 装饰器
    @guardian.safe_call("测试函数", fallback="fallback_val")
    def boom():
        raise RuntimeError("kaboom")
    result = boom()
    check("safe_call 捕获异常", isinstance(result, guardian.SafeResult))
    check("safe_call 返回 fallback", result.data == "fallback_val")

finally:
    shutil.rmtree(tmp, ignore_errors=True)


# ════════════════════════════════════════════════════
#  Archive.py 验证
# ════════════════════════════════════════════════════
print("\n🧠 Archive.py —— 长对话记忆\n")

arc_dir = Path(tempfile.mkdtemp(prefix="arc_test_"))
try:
    arc = Archive.Archive(store_path=str(arc_dir / "mem.json"))

    # 添加消息
    arc.add("conv1", "帮我写一个 Python 登录函数")
    arc.add("conv1", "要支持 OAuth2 和 JWT")
    arc.add("conv1", "还要加单元测试")
    check("添加消息", len(arc._data.get("conv1", [])) == 3)

    # 获取上下文
    ctx = arc.get_context("conv1", "帮我写测试")
    check("上下文返回列表", isinstance(ctx, list) and len(ctx) > 0)
    check("上下文限制 3 条", len(ctx) <= 3)

    # 短输入保护
    arc.add("conv1", "好")
    check("短输入不刷新", len(arc._data["conv1"]) == 3)

    # SimHash 计算
    h1 = Archive.simhash("Python 函数 类型注解")
    h2 = Archive.simhash("Python 函数 类型注解")
    h3 = Archive.simhash("Java Spring 接口 依赖注入")
    check("相同文本 hash 一致", h1 == h2)
    check("不同文本 hash 不同", h1 != h3)

    # 相似度
    sim = Archive.similarity(h1, h2)
    check("相同文本相似度=1.0", sim == 1.0)
    sim_diff = Archive.similarity(h1, h3)
    check("不同主题相似度<0.8", sim_diff < 0.8, f"sim={sim_diff:.2f}")

    # 主题切换
    switched = arc.should_switch_topic("conv1", "帮我写个 Java Spring 接口")
    check("话题切换检测", switched)

    # 紧急度
    urgent = Archive.detect_urgency("快帮我写！urgent！")
    check("紧急度检测", urgent)

    # 统计
    stats = arc.stats("conv1")
    check("统计有数据", stats.get("messages", 0) > 0)

    # 清除
    arc.clear("conv1")
    check("清除对话", len(arc._data.get("conv1", [])) == 0)

finally:
    shutil.rmtree(arc_dir, ignore_errors=True)


# ════════════════════════════════════════════════════
#  Nuwa.py 验证
# ════════════════════════════════════════════════════
print("\n📊 Nuwa.py —— POC 报告 + 辐射检测\n")

# POC 报告
n = Nuwa.Nuwa("登录接口 POC", "验证登录接口安全性")
n.add_step("用正确密码登录 → 期望 200")
n.add_step("用错误密码登录 → 期望 401")
n.add_step("SQL 注入攻击 → 期望 403")
n.set_result("成功率", "100%")
n.set_result("平均响应", "230ms")
n.verdict = "pass"

out_dir = Path(tempfile.mkdtemp(prefix="poc_test_"))
try:
    json_path, html_path = n.save(output_dir=str(out_dir))
    check("POC JSON 保存", Path(json_path).exists())
    check("POC HTML 保存", Path(html_path).exists())
    html = Path(html_path).read_text(encoding="utf-8")
    check("HTML 含标题", "POC 报告" in html)
    check("HTML 含结论", "PASS" in html.upper())
    check("HTML 含步骤", "登录" in html)

    # 辐射检测
    rd_root = Path(tempfile.mkdtemp(prefix="rad_test_"))
    try:
        # 创建项目结构
        (rd_root / "app.py").write_text(
            'import sqlite3\ndef get_user(uid):\n'
            '    query = "SELECT * FROM users WHERE id=" + uid\n'
            '    return query\n',
            encoding="utf-8")
        (rd_root / "migrations").mkdir()
        (rd_root / "migrations" / "001_init.py").write_text(
            '"""old migration"""\n', encoding="utf-8")
        (rd_root / "tests").mkdir()

        rd = Nuwa.RadiationDetector(project_root=str(rd_root))
        alerts = rd.scan(str(rd_root / "app.py"))
        check("辐射检测返回列表", isinstance(alerts, list))
        alert_types = [a.alert_type for a in alerts]
        check("检测到 db_migration", "db_migration" in alert_types, f"got: {alert_types}")

        # 关系图谱
        stats = rd.graph_stats()
        check("图谱统计有文件数", stats.get("files", 0) > 0)

        # 报告生成
        report_md = rd.generate_report(alerts)
        check("报告含警告标记", "⚠️" in report_md or "🔴" in report_md)

    finally:
        shutil.rmtree(rd_root, ignore_errors=True)

finally:
    shutil.rmtree(out_dir, ignore_errors=True)


# ════════════════════════════════════════════════════
#  gateway.py 验证
# ════════════════════════════════════════════════════
print("\n🌐 gateway.py —— 统一网关\n")

# 意图识别（关键词）
intent = gateway.detect_intent_keyword("帮我写一个 Python 爬虫")
check("关键词意图: code_python", intent == "code_python")

intent2 = gateway.detect_intent_keyword("写个小说大纲")
check("关键词意图: narrative", intent2 == "narrative")

intent3 = gateway.detect_intent_keyword("帮我写 SQL 查询")
check("关键词意图: code_sql", intent3 == "code_sql")

intent4 = gateway.detect_intent_keyword("随便聊聊")
check("通用意图: general", intent4 == "general")

# Skill 注册表
skills_dir = Path(__file__).parent / "Toolkit" / "skills"
if skills_dir.exists():
    sr = gateway.SkillRegistry(skills_dir=str(skills_dir))
    skills = sr.list_all()
    check("Skill 加载", len(skills) > 0, f"loaded {len(skills)}")
    matched = sr.match_for_intent("code_python")
    check("Skill 按意图匹配", len(matched) > 0)
    rendered = sr.render_for_prompt("code_python")
    check("Skill 渲染 prompt", "python_api_design" in rendered.lower() or "规范" in rendered)

# 输入清洗
cleaned = gateway._sanitize_input("  hello world  ")
check("输入清洗", cleaned == "hello world")

cleaned_long = gateway._sanitize_input("x" * 10000)
check("超长截断", len(cleaned_long) <= 8000)

# 无效请求
check("空请求无效", not gateway._is_valid_request(""))
check("纯标点无效", not gateway._is_valid_request("！！！"))

# ConservativePass
cp = guardian.ConservativePass(reason="模型不可用")
check("ConservativePass", cp.reason == "模型不可用")

# safe_call
@guardian.safe_call("test", fallback="safe_val")
def will_fail():
    raise ConnectionError("network down")
res = will_fail()
check("safe_call 返回 SafeResult", hasattr(res, 'ok') and hasattr(res, 'conservative'))
check("safe_call conservative=True", res.conservative == True)

# WordGateway 初始化（不调模型）
gw = gateway.WordGateway(env="dev", config={"provider": "deepseek"})
check("WordGateway 初始化", gw is not None)
check("WordGateway env=dev", gw.env == "dev")
check("WordGateway 有 guardian", gw.guardian is not None)
check("WordGateway 有 flywheel", gw.flywheel is not None)

# handle 无效输入
result = gw.handle("")
check("handle 空输入返回 error", result.get("success") == False)

result2 = gw.handle("！！！")
check("handle 纯标点返回 error", result2.get("success") == False)

# handle 正常流程（模型不可用 → 保守通过）
result3 = gw.handle("帮我写一个 Python hello world")
check("handle 正常返回 dict", isinstance(result3, dict))
check("handle 有 attempts 字段", "attempts" in result3)
check("handle 有 violations 字段", "violations" in result3)

# 反馈式重试（模拟违规后修复）
good_code = "def add(a: int, b: int) -> int:\n    return a + b\n"
# 直接测守门
r_good = work.check(good_code)
check("好代码守门通过", r_good.passed)

bad_code = "def bad(n):\n    return n * bad(n-1)\n"
r_bad = work.check(bad_code)
check("坏代码守门拦截", not r_bad.passed)
check("坏代码有违规", len(r_bad.violations) > 0)

# 反馈 prompt 构建
fb = gw._build_feedback_prompt("写加法", r_bad.violations)
check("反馈 prompt 含违规信息", "type_hints" in fb.lower() or "违规" in fb)


# ════════════════════════════════════════════════════
#  外部工具融合验证
# ════════════════════════════════════════════════════
print("\n🔗 外部工具融合验证\n")

# 1. CodeGraph 思路：关系图谱查询
print("  📌 CodeGraph 思路（关系图谱查询）:")
test_proj = Path(tempfile.mkdtemp(prefix="cg_test_"))
try:
    (test_proj / "utils.py").write_text(
        "def helper(x):\n    return x * 2\n", encoding="utf-8")
    (test_proj / "main.py").write_text(
        "from utils import helper\n\ndef main():\n    return helper(5)\n",
        encoding="utf-8")
    rd = Nuwa.RadiationDetector(project_root=str(test_proj))
    related = rd.get_related("main.py")
    check("  main.py 关联 utils.py", any("utils" in r for r in related), f"got: {related}")
    check("  图谱边数 > 0", rd.graph_stats()["edges"] > 0)
finally:
    shutil.rmtree(test_proj, ignore_errors=True)

# 1b. db_migration 辐射检测
print("  📌 db_migration 辐射检测:")
db_proj = Path(tempfile.mkdtemp(prefix="db_test_"))
try:
    (db_proj / "user_model.py").write_text(
        "import sqlite3\n"
        "def save_user(name, email):\n"
        "    db = sqlite3.connect('app.db')\n"
        "    db.execute(\"INSERT INTO users VALUES (?, ?)\", (name, email))\n"
        "    db.commit()\n",
        encoding="utf-8")
    rd2 = Nuwa.RadiationDetector(project_root=str(db_proj))
    alerts = rd2.scan(str(db_proj / "user_model.py"))
    has_db_alert = any(a.alert_type == "db_migration" for a in alerts)
    check("  SQL 改动触发 db_migration 告警", has_db_alert, f"alerts: {[a.alert_type for a in alerts]}")
finally:
    shutil.rmtree(db_proj, ignore_errors=True)

# 2. Headroom 思路：压缩率
print("  📌 Headroom 思路（AST 压缩视图）:")
big_code = '''"""模块文档"""
import os
import sys
from typing import List, Dict

class UserService:
    """用户服务"""
    def __init__(self, db):
        self.db = db

    def get_user(self, uid: int) -> dict:
        """获取用户"""
        try:
            return self.db.query(uid)
        except Exception:
            return {}

    def create_user(self, data: dict) -> bool:
        """创建用户"""
        try:
            return self.db.insert(data)
        except Exception:
            return False

def process_users(users: List[dict]) -> int:
    """批量处理"""
    count = 0
    for u in users:
        if u.get("active"):
            count += 1
    return count
'''
r_big = work.check(big_code)
orig_lines = len(big_code.strip().splitlines())
comp_lines = len(r_big.compressed_view.strip().splitlines())
ratio = comp_lines / max(orig_lines, 1)
check(f"  原始 {orig_lines} 行 → 压缩 {comp_lines} 行 ({ratio:.0%})",
      ratio < 0.7, f"压缩率不够: {ratio:.0%}")

# 3. Skill Router 分层：L1-L5
print("  📌 Skill Router 分层架构:")
check("  L1 流量过滤: 清洗+无效拦截", gateway._sanitize_input(" test ") == "test")
check("  L2 规则匹配: 关键词快速分类", gateway.detect_intent_keyword("Python 函数") == "code_python")
check("  L3 语义识别: 接口存在", callable(gateway.detect_intent_semantic))
check("  L4 后置校验: check() 返回 Report", isinstance(work.check("x=1"), work.Report))
fb_l5 = gw._build_feedback_prompt("test", r_bad.violations)
check("  L5 反馈闭环: 违规注入 prompt", "type_hints" in fb_l5.lower() or "no_infinite" in fb_l5.lower() or "⚠" in fb_l5)

# 4. 熔断器模式
print("  📌 熔断器模式:")
@guardian.safe_call("熔断测试", fallback="circuit_open")
def circuit_breaker():
    raise TimeoutError("API timeout")
res = circuit_breaker()
check("  异常→SafeResult", isinstance(res, guardian.SafeResult))
check("  ok=False", res.ok == False)
check("  conservative=True", res.conservative == True)
check("  data=fallback", res.data == "circuit_open")

# 5. 突变测试质量门禁
print("  📌 突变测试（mutatest 思路）:")
mcode = "def calc(a, b):\n    return a + b\n"
mresult = work.mutation_test(mcode, ["no_hardcoded_secrets", "no_sql_injection"])
check(f"  突变检测 {mresult['detected']}/{mresult['total']}",
      mresult['detected'] >= 2)


# ════════════════════════════════════════════════════
#  文件完整性
# ════════════════════════════════════════════════════
print("\n📁 文件完整性\n")

base = Path(__file__).parent
required = [
    "Toolkit/__init__.py",
    "Toolkit/gateway.py",
    "Toolkit/work.py",
    "Toolkit/guardian.py",
    "Toolkit/Archive.py",
    "Toolkit/Nuwa.py",
    "Toolkit/Proteus.py",
    "Toolkit/shiyun.py",
    "config.json",
    "README.md",
    "LICENSE",
    ".gitignore",
    "requirements.txt",
]
for f in required:
    check(f"存在: {f}", (base / f).exists(), f"缺失: {f}")

# Skills
skills_dir = base / "Toolkit" / "skills"
if skills_dir.exists():
    skill_files = list(skills_dir.glob("*.skill"))
    check(f"Skills 文件 ≥ 5", len(skill_files) >= 5, f"只有 {len(skill_files)} 个")

# 代码行数统计
total_lines = 0
for py in (base / "Toolkit").glob("*.py"):
    lines = len(py.read_text().splitlines())
    total_lines += lines
check(f"Toolkit 总代码 {total_lines} 行", total_lines > 0, f"{total_lines} 行")

# 零依赖检查（核心模块不应依赖第三方）
import ast as ast_mod
for py in ["work.py", "guardian.py", "Archive.py", "Nuwa.py"]:
    path = base / "Toolkit" / py
    if path.exists():
        tree = ast_mod.parse(path.read_text())
        imports = set()
        for node in ast_mod.walk(tree):
            if isinstance(node, ast_mod.Import):
                for n in node.names:
                    imports.add(n.name.split('.')[0])
            elif isinstance(node, ast_mod.ImportFrom):
                if node.module:
                    imports.add(node.module.split('.')[0])
        # 过滤标准库
        stdlib = {'os', 'sys', 're', 'json', 'time', 'hashlib', 'logging',
                  'pathlib', 'dataclasses', 'typing', 'collections', 'tempfile',
                  'shutil', 'zipfile', 'argparse', 'subprocess', 'ast', 'random',
                  'string', 'math', 'itertools', 'functools', 'contextlib',
                  'io', 'uuid', 'datetime', 'inspect', 'importlib', 'enum'}
        third_party = imports - stdlib - {'Toolkit'}
        check(f"{py} 零第三方依赖", len(third_party) == 0, f"第三方: {third_party}")


# ════════════════════════════════════════════════════
#  总结
# ════════════════════════════════════════════════════
total = PASSED + FAILED
print(f"\n{'═' * 50}")
print(f"  总计: {total} 项")
print(f"  ✅ 通过: {PASSED} ({PASSED/max(total,1)*100:.0f}%)")
if FAILED:
    print(f"  ❌ 失败: {FAILED}")
    for f in FAILURES[:10]:
        print(f"      - {f}")
print(f"{'═' * 50}")

if FAILED == 0:
    print(f"\n  🎉 全部通过！jinchen v{Toolkit.__version__} 验证完成")
else:
    print(f"\n  ⚠️ {FAILED} 项失败，请检查")

sys.exit(0 if FAILED == 0 else 1)
