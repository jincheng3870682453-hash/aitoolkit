"""
test_identify.py — 测试接口识别（Phase 1）

验证代码分析器能否正确识别接口级别的函数，
并排除内部辅助函数、私有函数等。
"""

import sys
import os
import tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from interface_notes.analyzer.code_analyzer import (
    analyze_file, analyze_project,
    PythonAnalyzer, JSAnalyzer, JavaAnalyzer
)
from interface_notes.core.types import Interface, RiskLevel


# ──────────────────────────────────────────────
# Python 测试
# ──────────────────────────────────────────────

PYTHON_SAMPLE = '''
"""
示例模块 — 测试用
"""

import sqlite3
import requests


def send_email(to: str, subject: str, body: str) -> bool:
    """发送邮件通知"""
    response = requests.post("https://smtp.example.com/send", json={
        "to": to, "subject": subject, "body": body
    })
    return response.status_code == 200


def query_database(table: str, condition: dict) -> list[dict]:
    """查询数据库"""
    conn = sqlite3.connect("app.db")
    cursor = conn.cursor()
    # ... 执行查询
    return [{"id": 1, "name": "test"}]


def _format_date(dt):
    """内部辅助：格式化日期"""
    return dt.strftime("%Y-%m-%d")


def generate_report(user_id: int, report_type: str = "pdf") -> str:
    """生成用户报告"""
    data = query_database("users", {"id": user_id})
    send_email("admin@example.com", "Report", str(data))
    return f"/tmp/report_{user_id}.{report_type}"


class EmailService:
    """邮件服务类"""

    def __init__(self, smtp_host: str):
        self.host = smtp_host

    def send(self, to: str, msg: str) -> bool:
        """发送单条邮件"""
        return send_email(to, "Notification", msg)

    def _retry_logic(self, attempt: int):
        """内部重试逻辑"""
        pass
'''


def test_python_analyzer_basic():
    """基本识别测试"""
    print("🧪 test_python_analyzer_basic")
    analyzer = PythonAnalyzer(PYTHON_SAMPLE, "test_module.py")
    interfaces = analyzer.extract_interfaces()

    names = [i.name for i in interfaces]

    # 应该识别的
    assert "send_email" in names, f"send_email 未被识别, got: {names}"
    assert "query_database" in names, f"query_database 未被识别, got: {names}"
    assert "generate_report" in names, f"generate_report 未被识别, got: {names}"
    assert "EmailService.send" in names, f"EmailService.send 未被识别, got: {names}"

    # 应该排除的
    assert "_format_date" not in names, f"_format_date 不应被识别为接口"
    assert "_retry_logic" not in names, f"_retry_logic 不应被识别为接口"

    print(f"   ✅ 识别出 {len(interfaces)} 个接口: {names}")


def test_python_analyzer_params():
    """参数提取测试"""
    print("🧪 test_python_analyzer_params")
    analyzer = PythonAnalyzer(PYTHON_SAMPLE, "test_module.py")
    interfaces = {i.name: i for i in analyzer.extract_interfaces()}

    send_email = interfaces["send_email"]
    assert "to" in send_email.params, "send_email 缺少参数 to"
    assert send_email.params["to"] == "str", f"to 类型错误: {send_email.params['to']}"
    assert "subject" in send_email.params
    assert "body" in send_email.params

    query_db = interfaces["query_database"]
    assert "table" in query_db.params
    assert "condition" in query_db.params

    print(f"   ✅ 参数提取正确")


def test_python_analyzer_risk():
    """风险检测测试"""
    print("🧪 test_python_analyzer_risk")
    analyzer = PythonAnalyzer(PYTHON_SAMPLE, "test_module.py")
    interfaces = {i.name: i for i in analyzer.extract_interfaces()}

    # send_email 涉及 HTTP 请求但无 timeout → 应为 MEDIUM
    send_email = interfaces["send_email"]
    assert send_email.risk_level == RiskLevel.MEDIUM, \
        f"send_email 风险应为 MEDIUM, got: {send_email.risk_level}"
    assert "超时" in send_email.suspicious, \
        f"suspicious 应包含'超时', got: {send_email.suspicious}"

    print(f"   ✅ 风险检测正确: send_email → {send_email.risk_level.value}")


def test_python_analyzer_calls():
    """调用关系提取测试"""
    print("🧪 test_python_analyzer_calls")
    analyzer = PythonAnalyzer(PYTHON_SAMPLE, "test_module.py")
    interfaces = {i.name: i for i in analyzer.extract_interfaces()}

    generate_report = interfaces["generate_report"]
    assert "query_database" in generate_report.dependencies, \
        f"generate_report 应调用 query_database"
    assert "send_email" in generate_report.dependencies, \
        f"generate_report 应调用 send_email"

    print(f"   ✅ 调用关系正确: generate_report → {generate_report.dependencies}")


# ──────────────────────────────────────────────
# JavaScript 测试
# ──────────────────────────────────────────────

JS_SAMPLE = '''
/**
 * 发送邮件通知
 */
async function sendEmail(to, subject, body) {
    const response = await fetch('/api/send', {
        method: 'POST',
        body: JSON.stringify({to, subject, body})
    });
    return response.ok;
}

/**
 * 查询用户数据
 */
function queryUser(userId) {
    return database.find({id: userId});
}

// 内部辅助
function _formatName(name) {
    return name.trim().toUpperCase();
}

export default async function generateReport(userId) {
    const user = queryUser(userId);
    await sendEmail(user.email, 'Report', JSON.stringify(user));
    return `/reports/${userId}.pdf`;
}
'''


def test_js_analyzer():
    """JavaScript 接口识别测试"""
    print("🧪 test_js_analyzer")
    analyzer = JSAnalyzer(JS_SAMPLE, "app.js")
    interfaces = analyzer.extract_interfaces()
    names = [i.name for i in interfaces]

    assert "sendEmail" in names, f"sendEmail 未被识别, got: {names}"
    assert "queryUser" in names, f"queryUser 未被识别, got: {names}"
    assert "generateReport" in names, f"generateReport 未被识别, got: {names}"
    assert "_formatName" not in names, f"_formatName 不应被识别"

    # 检查 JSDoc 提取
    send_email = next(i for i in interfaces if i.name == "sendEmail")
    assert "发送邮件" in send_email.description, f"JSDoc 未正确提取"

    print(f"   ✅ JS 识别出 {len(interfaces)} 个接口: {names}")


# ──────────────────────────────────────────────
# Java 测试
# ──────────────────────────────────────────────

JAVA_SAMPLE = '''
package com.example.service;

import java.sql.*;
import java.net.http.*;

/**
 * 用户服务类
 */
public class UserService {

    /**
     * 根据ID查询用户
     */
    public User findById(Long userId) throws SQLException {
        Connection conn = DriverManager.getConnection(DB_URL);
        Statement stmt = conn.createStatement();
        ResultSet rs = stmt.executeQuery("SELECT * FROM users WHERE id=" + userId);
        return rs.next() ? new User(rs) : null;
    }

    /**
     * 发送通知邮件
     */
    public boolean sendNotification(String email, String msg) {
        HttpClient client = HttpClient.newHttpClient();
        // ... 发送逻辑
        return true;
    }

    // 内部工具
    private String formatName(String name) {
        return name != null ? name.trim() : "";
    }

    public Report generateReport(Long userId) {
        User user = findById(userId);
        sendNotification(user.getEmail(), "Report ready");
        return new Report(user);
    }
}
'''


def test_java_analyzer():
    """Java 接口识别测试"""
    print("🧪 test_java_analyzer")
    analyzer = JavaAnalyzer(JAVA_SAMPLE, "UserService.java")
    interfaces = analyzer.extract_interfaces()
    names = [i.name for i in interfaces]

    assert "findById" in names, f"findById 未被识别, got: {names}"
    assert "sendNotification" in names, f"sendNotification 未被识别, got: {names}"
    assert "generateReport" in names, f"generateReport 未被识别, got: {names}"
    assert "formatName" not in names, f"formatName(private) 不应被识别"

    # 检查 Javadoc
    find_by_id = next(i for i in interfaces if i.name == "findById")
    assert "查询用户" in find_by_id.description, f"Javadoc 未正确提取"

    print(f"   ✅ Java 识别出 {len(interfaces)} 个接口: {names}")


# ──────────────────────────────────────────────
# 端到端测试：analyze_file
# ──────────────────────────────────────────────

def test_analyze_file_e2e():
    """端到端：写入临时文件 → analyze_file → 验证结果"""
    print("🧪 test_analyze_file_e2e")

    with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
        f.write(PYTHON_SAMPLE)
        tmp_path = f.name

    try:
        interfaces = analyze_file(tmp_path)
        names = [i.name for i in interfaces]
        assert "send_email" in names, f"E2E 失败, got: {names}"
        print(f"   ✅ E2E 测试通过: {len(interfaces)} 个接口")
    finally:
        os.unlink(tmp_path)


# ──────────────────────────────────────────────
# 主入口
# ──────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 50)
    print("📋 接口识别测试套件")
    print("=" * 50)
    print()

    test_python_analyzer_basic()
    test_python_analyzer_params()
    test_python_analyzer_risk()
    test_python_analyzer_calls()
    test_js_analyzer()
    test_java_analyzer()
    test_analyze_file_e2e()

    print()
    print("=" * 50)
    print("🎉 全部测试通过！")
    print("=" * 50)
