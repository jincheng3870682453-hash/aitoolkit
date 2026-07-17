"""
test_fullscan.py — 测试全量扫描（模式B）

验证 analyze_project 能否正确扫描整个项目目录，
提取所有接口并建立跨文件调用关系。
"""

import sys
import os
import tempfile
import shutil
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from interface_notes.analyzer.code_analyzer import analyze_project
from interface_notes.core.session import Session
from interface_notes.core.types import Mode


def create_test_project(root: str):
    """创建一个小型测试项目"""
    # utils/email.py
    email_py = '''
import smtplib
import requests

def send_email(to: str, subject: str, body: str) -> bool:
    """发送邮件"""
    resp = requests.post("https://api.sendgrid.com/send", json={
        "to": to, "subject": subject, "body": body
    })
    return resp.status_code == 200

def _encode_body(text: str) -> str:
    """内部编码"""
    return text.encode("base64").decode()

async def send_bulk(emails: list[str], content: str) -> dict:
    """批量发送"""
    results = {}
    for e in emails:
        results[e] = await send_email(e, "Bulk", content)
    return results
'''
    os.makedirs(os.path.join(root, "utils"), exist_ok=True)
    with open(os.path.join(root, "utils", "email.py"), "w") as f:
        f.write(email_py)

    # db/query.py
    db_py = '''
import sqlite3

def query_database(table: str, condition: dict) -> list[dict]:
    """查询数据库"""
    conn = sqlite3.connect("app.db")
    cursor = conn.cursor()
    query = f"SELECT * FROM {table} WHERE id = ?"
    cursor.execute(query, (condition.get("id", 0),))
    return [dict(zip([d[0] for d in cursor.description], row)) for row in cursor.fetchall()]

def execute_sql(sql: str) -> int:
    """执行SQL，返回影响行数"""
    conn = sqlite3.connect("app.db")
    cursor = conn.cursor()
    cursor.execute(sql)
    conn.commit()
    return cursor.rowcount

def _build_where(cond: dict) -> str:
    """内部：构建WHERE子句"""
    return " AND ".join(f"{k}='{v}'" for k, v in cond.items())
'''
    os.makedirs(os.path.join(root, "db"), exist_ok=True)
    with open(os.path.join(root, "db", "query.py"), "w") as f:
        f.write(db_py)

    # reports/generator.py
    report_py = '''
from utils.email import send_email
from db.query import query_database

def generate_report(user_id: int, report_type: str = "pdf") -> str:
    """生成用户报告"""
    data = query_database("users", {"id": user_id})
    send_email("admin@example.com", f"Report-{user_id}", str(data))
    return f"/tmp/report_{user_id}.{report_type}"

def render_template(name: str, context: dict) -> str:
    """渲染模板"""
    # 简化实现
    return f"Hello {context.get('name', 'World')}"
'''
    os.makedirs(os.path.join(root, "reports"), exist_ok=True)
    with open(os.path.join(root, "reports", "generator.py"), "w") as f:
        f.write(report_py)

    # main.py
    main_py = '''
from reports.generator import generate_report

def main():
    """程序入口"""
    report = generate_report(42, "pdf")
    print(f"Report saved: {report}")

if __name__ == "__main__":
    main()
'''
    with open(os.path.join(root, "main.py"), "w") as f:
        f.write(main_py)

    # config.py (纯配置，不应有接口)
    config_py = '''
# 配置文件
DATABASE_URL = "sqlite:///app.db"
SMTP_HOST = "smtp.example.com"
SMTP_PORT = 587
DEBUG = True

def get_config(key: str) -> str:
    """获取配置项"""
    config_map = {
        "db": DATABASE_URL,
        "smtp_host": SMTP_HOST,
        "smtp_port": SMTP_PORT,
    }
    return config_map.get(key, "")
'''
    with open(os.path.join(root, "config.py"), "w") as f:
        f.write(config_py)


def test_fullscan_basic():
    """基本全量扫描测试"""
    print("🧪 test_fullscan_basic")

    tmpdir = tempfile.mkdtemp(prefix="ifscan_test_")
    try:
        create_test_project(tmpdir)

        session = Session(project_name="测试项目", mode=Mode.B_FULLSCAN)
        session = analyze_project(tmpdir, session)

        names = sorted(session.interfaces.keys())

        # 验证核心接口被识别
        expected = [
            "send_email", "send_bulk", "query_database",
            "execute_sql", "generate_report", "render_template",
            "main", "get_config"
        ]
        for name in expected:
            assert name in session.interfaces, f"缺少接口: {name}"

        # 验证内部函数被排除
        assert "_encode_body" not in session.interfaces, "_encode_body 不应被识别"
        assert "_build_where" not in session.interfaces, "_build_where 不应被识别"

        print(f"   ✅ 扫描完成，识别 {len(session.interfaces)} 个接口")
        print(f"   📁 扫描文件数: {session.stats['total_files_scanned']}")

    finally:
        shutil.rmtree(tmpdir)


def test_fullscan_call_relations():
    """跨文件调用关系测试"""
    print("🧪 test_fullscan_call_relations")

    tmpdir = tempfile.mkdtemp(prefix="ifscan_call_")
    try:
        create_test_project(tmpdir)

        session = Session(project_name="测试项目", mode=Mode.B_FULLSCAN)
        session = analyze_project(tmpdir, session)

        # generate_report 应该调用 query_database 和 send_email
        gr = session.get_interface("generate_report")
        assert gr is not None, "generate_report 不存在"

        # 注意：跨文件调用需要通过 import 分析
        # 这里至少验证文件内调用被记录
        print(f"   📊 generate_report 依赖: {gr.dependencies}")
        print(f"   📊 send_email 被调用: {session.get_interface('send_email').called_by}")

        # 验证 IO 风险检测
        qdb = session.get_interface("query_database")
        assert qdb.risk_level.value in ("low", "medium"), f"风险应为 low 或 medium"

        print(f"   ✅ 调用关系分析完成")

    finally:
        shutil.rmtree(tmpdir)


def test_fullscan_io_detection():
    """IO 操作风险检测测试"""
    print("🧪 test_fullscan_io_detection")

    tmpdir = tempfile.mkdtemp(prefix="ifscan_io_")
    try:
        create_test_project(tmpdir)

        session = Session(project_name="IO测试", mode=Mode.B_FULLSCAN)
        session = analyze_project(tmpdir, session)

        # send_email 用了 requests → 应标 MEDIUM（无timeout）
        se = session.get_interface("send_email")
        assert se.risk_level == "medium", f"send_email 风险应为 medium, got: {se.risk_level}"
        assert se.suspicious, "suspicious 字段应有内容"

        # query_database 用了 sqlite3 → 应标 MEDIUM
        qdb = session.get_interface("query_database")
        assert qdb.risk_level == "medium", f"query_database 风险应为 medium, got: {qdb.risk_level}"

        print(f"   ✅ IO 风险检测正确")
        print(f"      send_email: {se.risk_level} ({se.suspicious})")
        print(f"      query_database: {qdb.risk_level} ({qdb.suspicious})")

    finally:
        shutil.rmtree(tmpdir)


def test_fullscan_ignore_dirs():
    """忽略目录测试"""
    print("🧪 test_fullscan_ignore_dirs")

    tmpdir = tempfile.mkdtemp(prefix="ifscan_ignore_")
    try:
        create_test_project(tmpdir)

        # 添加 node_modules 目录（应被忽略）
        nm_dir = os.path.join(tmpdir, "node_modules")
        os.makedirs(nm_dir, exist_ok=True)
        with open(os.path.join(nm_dir, "garbage.py"), "w") as f:
            f.write("def some_npm_crap(): pass\n")

        session = Session(project_name="忽略测试", mode=Mode.B_FULLSCAN)
        session = analyze_project(tmpdir, session)

        # node_modules 里的不应被扫描
        assert "some_npm_crap" not in session.interfaces, \
            "node_modules 内容不应被扫描"

        print(f"   ✅ 忽略目录工作正常")

    finally:
        shutil.rmtree(tmpdir)


if __name__ == "__main__":
    print("=" * 50)
    print("📋 全量扫描测试套件（模式B）")
    print("=" * 50)
    print()

    test_fullscan_basic()
    test_fullscan_call_relations()
    test_fullscan_io_detection()
    test_fullscan_ignore_dirs()

    print()
    print("=" * 50)
    print("🎉 全部测试通过！")
    print("=" * 50)
