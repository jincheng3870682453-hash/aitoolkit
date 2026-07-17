#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Nuwa.py — B 端交付层（POC 报告 + 全栈辐射检测）

V1 原有功能：
  - 无侵入指标采集
  - 生成 HTML + JSON 双格式报告
  - 支持批量模式，便于审计、展示和 CI/CD 集成

V3 新增功能：
  - RadiationDetector：代码改动自动关联上下游
  - DB 辐射 / API 辐射 / 测试辐射 / 导入辐射 / 配置辐射
  - 漏一个警告一个
"""

import os
import re
import json
import logging
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass, field, asdict
from typing import Optional

log = logging.getLogger("nuwa")


# ═══════════════════════════════════════════════════════
# V1 — Nuwa  POC 报告生成器
# ═══════════════════════════════════════════════════════

@dataclass
class POCIndicator:
    """单个 POC 指标"""
    name: str
    value: float | int | str
    unit: str = ""
    status: str = "ok"  # ok / warn / fail
    detail: str = ""


@dataclass
class POCReport:
    """一份 POC 报告"""
    title: str
    generated_at: str = ""
    indicators: list[POCIndicator] = field(default_factory=list)
    summary: str = ""
    raw_data: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "generated_at": self.generated_at or datetime.now().isoformat(),
            "indicators": [asdict(i) for i in self.indicators],
            "summary": self.summary,
            "raw_data": self.raw_data,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=False)

    def to_html(self) -> str:
        rows = ""
        for i in self.indicators:
            color = {"ok": "#4caf50", "warn": "#ff9800", "fail": "#f44336"}.get(i.status, "#999")
            rows += f"""
            <tr>
              <td>{i.name}</td>
              <td><b style="color:{color}">{i.value}{i.unit}</b></td>
              <td>{i.detail}</td>
            </tr>"""
        return f"""<!DOCTYPE html>
<html lang="zh">
<head><meta charset="utf-8"><title>{self.title}</title>
<style>
body{{font-family:-apple-system,sans-serif;max-width:800px;margin:2em auto;padding:0 1em}}
h1{{color:#333}}table{{width:100%;border-collapse:collapse;margin-top:1em}}
th,td{{padding:8px 12px;border-bottom:1px solid #eee;text-align:left}}
th{{background:#f5f5f5}}
.status-ok{{color:#4caf50}} .status-fail{{color:#f44336}} .status-warn{{color:#ff9800}}
</style></head>
<body>
<h1>📊 {self.title}</h1>
<p><small>生成时间: {self.generated_at or datetime.now().isoformat()}</small></p>
<table>
<tr><th>指标</th><th>数值</th><th>说明</th></tr>
{rows}
</table>
<h2>📝 总结</h2>
<p>{self.summary}</p>
</body></html>"""


class Nuwa:
    """
    B 端交付层 —— 无侵入指标采集 + HTML/JSON 双格式报告。
    支持批量模式（CI/CD 集成）。
    """

    def __init__(self, report_dir: str = "poc_reports"):
        self.report_dir = Path(report_dir)
        self.report_dir.mkdir(parents=True, exist_ok=True)
        self.indicators: list[POCIndicator] = []
        self.raw_data: dict = {}

    def add(self, name: str, value, unit: str = "", status: str = "ok", detail: str = ""):
        self.indicators.append(POCIndicator(name, value, unit, status, detail))

    def collect_from_gateway(self, gateway_stats: dict) -> None:
        """从 WordGateway.stats() 自动采集指标"""
        if "rules_active" in gateway_stats:
            self.add("激活规则数", len(gateway_stats["rules_active"]), "条", "ok")
        if "skills_loaded" in gateway_stats:
            self.add("Skill 加载数", gateway_stats["skills_loaded"], "个", "ok")
        # V1 模块
        v1 = gateway_stats.get("v1_available", {})
        for mod, avail in v1.items():
            self.add(f"V1.{mod}", "✅" if avail else "❌", "", "ok" if avail else "warn")
        # 飞轮
        fw = gateway_stats.get("flywheel", {})
        if fw:
            self.add("飞轮记录数", fw.get("total", 0), "条", "ok")
        # 陪审团
        jury = gateway_stats.get("jury", {})
        if jury:
            self.add("判决书总数", jury.get("total", 0), "份", "ok")
            for sev, cnt in jury.get("by_severity", {}).items():
                self.add(f"  └ {sev}", cnt, "份", "warn" if sev == "critical" else "ok")
        # 多语言
        ml = gateway_stats.get("multilang", {})
        for lang, rules in ml.items():
            self.add(f"🌐 {lang}", f"{len(rules)} 条规则", "", "ok")

    def collect_from_jury(self, jury_stats: dict) -> None:
        """从 RollbackJury.stats() 采集"""
        self.add("判决书总数", jury_stats.get("total", 0), "份", "ok")
        for sev, cnt in jury_stats.get("by_severity", {}).items():
            icon = "🔴" if sev == "critical" else "🟡" if sev == "high" else "🔵"
            self.add(f"{icon} {sev}", cnt, "份", "fail" if sev == "critical" else "warn")

    def generate(self, title: str = "POC 报告") -> POCReport:
        """生成报告"""
        # 自动总结
        ok = sum(1 for i in self.indicators if i.status == "ok")
        warn = sum(1 for i in self.indicators if i.status == "warn")
        fail = sum(1 for i in self.indicators if i.status == "fail")
        summary = f"共 {len(self.indicators)} 项指标：✅ {ok} 通过，⚠️ {warn} 警告，❌ {fail} 失败。"

        report = POCReport(
            title=title,
            generated_at=datetime.now().isoformat(),
            indicators=self.indicators,
            summary=summary,
            raw_data=self.raw_data,
        )

        # 保存
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        (self.report_dir / f"{stamp}.json").write_text(report.to_json(), encoding="utf-8")
        (self.report_dir / f"{stamp}.html").write_text(report.to_html(), encoding="utf-8")
        log.info(f"📊 POC 报告已生成: {stamp}.html / .json")

        # 重置
        self.indicators = []
        self.raw_data = {}

        return report

    def batch(self, items: list[dict], title: str = "批量 POC 报告") -> POCReport:
        """批量模式：传入多个 gateway_stats，汇总成一份报告"""
        for item in items:
            self.collect_from_gateway(item)
        return self.generate(title)


# ═══════════════════════════════════════════════════════
# V3 — RadiationDetector  全栈辐射检测
# ═══════════════════════════════════════════════════════

@dataclass
class RadAlert:
    """一条辐射告警"""
    source_file: str
    related_file: str
    alert_type: str     # db_migration / api_doc / unit_test / import / config
    severity: str       # critical / warning / info
    message: str
    suggestion: str


class RadiationDetector:
    """
    全栈辐射检测 —— 代码改动自动关联上下游。
    DB 辐射 / API 辐射 / 测试辐射 / 导入辐射 / 配置辐射。
    """

    MIGRATION_DIRS = ["migrations", "alembic/versions", "db/migrate", "db/migrations"]

    def __init__(self, project_root: str = "."):
        self.root = Path(project_root)

    def scan(self, changed_file: str) -> list[RadAlert]:
        """分析一个改动文件，返回所有辐射告警"""
        alerts: list[RadAlert] = []
        path = Path(changed_file)
        if not path.exists():
            return alerts

        content = path.read_text(encoding="utf-8", errors="ignore")

        alerts += self._check_db(content, path)
        alerts += self._check_api(content, path)
        alerts += self._check_test(content, path)
        alerts += self._check_import(content, path)
        alerts += self._check_config(content, path)

        return alerts

    def _check_db(self, content: str, path: Path) -> list[RadAlert]:
        alerts = []
        has_sql = bool(re.search(
            r"\b(SELECT|INSERT|UPDATE|DELETE|CREATE|ALTER|DROP)\b", content, re.I))
        if not has_sql:
            return alerts

        # 找最近的 migration
        latest = None
        for d in self.MIGRATION_DIRS:
            dd = self.root / d
            if dd.exists():
                files = sorted(dd.glob("*.py"), key=lambda f: f.stat().st_mtime)
                if files:
                    latest = files[-1]

        if latest and latest.stat().st_mtime < path.stat().st_mtime:
            alerts.append(RadAlert(
                source_file=str(path),
                related_file=str(latest),
                alert_type="db_migration",
                severity="critical",
                message=f"SQL 文件已修改，但 migration ({latest.name}) 更旧",
                suggestion="创建新的 migration 文件，包含本次 SQL 变更",
            ))
        return alerts

    def _check_api(self, content: str, path: Path) -> list[RadAlert]:
        alerts = []
        has_route = bool(re.search(
            r'@app\.(get|post|put|delete|route)|@router\.(get|post|put|delete)',
            content))
        if not has_route:
            return alerts

        doc_files = (list(self.root.glob("docs/**/*.md")) +
                     list(self.root.glob("**/API*.md")) +
                     list(self.root.glob("**/api*.yaml")) +
                     list(self.root.glob("**/openapi*.json")))
        if not doc_files:
            alerts.append(RadAlert(
                source_file=str(path),
                related_file="docs/",
                alert_type="api_doc",
                severity="warning",
                message="检测到 API 路由变更，但未找到接口文档",
                suggestion="更新 docs/API.md 或生成 OpenAPI Schema",
            ))
        return alerts

    def _check_test(self, content: str, path: Path) -> list[RadAlert]:
        alerts = []
        if path.parent.name == "tests":
            return alerts

        funcs = re.findall(r"def\s+(\w+)\s*\(", content)
        if not funcs:
            return alerts

        test_files: list[Path] = []
        for td in ["tests", "test", "__tests__"]:
            tdp = self.root / td
            if tdp.exists():
                test_files.extend(list(tdp.glob("*.py")))

        if not test_files:
            alerts.append(RadAlert(
                source_file=str(path),
                related_file="tests/",
                alert_type="unit_test",
                severity="warning",
                message=f"修改了 {len(funcs)} 个函数，但未找到对应测试文件",
                suggestion=f"为以下函数添加单元测试: {', '.join(funcs[:5])}",
            ))
        else:
            test_content = " ".join(f.read_text(errors="ignore") for f in test_files)
            uncovered = [f for f in funcs if f not in test_content]
            if uncovered:
                alerts.append(RadAlert(
                    source_file=str(path),
                    related_file="tests/",
                    alert_type="unit_test",
                    severity="info",
                    message=f"可能缺少测试覆盖: {', '.join(uncovered[:5])}",
                    suggestion="补充单元测试以提高覆盖率",
                ))
        return alerts

    def _check_import(self, content: str, path: Path) -> list[RadAlert]:
        alerts = []
        if path.stem == "__init__":
            return alerts
        if not re.search(r"\bclass\s+\w+|def\s+\w+", content):
            return alerts  # 非模块文件

        for py_file in self.root.rglob("*.py"):
            if py_file == path or "tests" in py_file.parts:
                continue
            fc = py_file.read_text(errors="ignore")
            if re.search(rf"from\s+\S*{path.stem}\S*\s+import|import\s+\S*{path.stem}\S*", fc):
                alerts.append(RadAlert(
                    source_file=str(path),
                    related_file=str(py_file),
                    alert_type="import",
                    severity="info",
                    message=f"{py_file} 导入了 {path.stem}，可能需要同步适配",
                    suggestion="检查导入方的调用是否兼容本次修改",
                ))
        return alerts

    def _check_config(self, content: str, path: Path) -> list[RadAlert]:
        alerts = []
        # 修复：分别提取两种模式的变量名
        vars1 = re.findall(r'os\.getenv\("(\w+)"\)', content)
        vars2 = re.findall(r'os\.environ\["(\w+)"\]', content)
        env_vars = set(vars1 + vars2)
        if not env_vars:
            return alerts

        env_example = self.root / ".env.example"
        if not env_example.exists():
            alerts.append(RadAlert(
                source_file=str(path),
                related_file=".env.example",
                alert_type="config",
                severity="warning",
                message=f"使用了 {len(env_vars)} 个环境变量，但缺少 .env.example",
                suggestion=f"创建 .env.example 并添加: {', '.join(sorted(env_vars)[:5])}",
            ))
        else:
            existing = env_example.read_text()
            missing = [v for v in sorted(env_vars) if v not in existing]
            if missing:
                alerts.append(RadAlert(
                    source_file=str(path),
                    related_file=".env.example",
                    alert_type="config",
                    severity="info",
                    message=f".env.example 缺少变量: {', '.join(missing)}",
                    suggestion=f"补充: {', '.join(missing)}",
                ))
        return alerts

    def generate_report(self, alerts: list[RadAlert]) -> str:
        """生成辐射报告（Markdown）"""
        if not alerts:
            return "## ✅ 辐射检测通过\n\n未发现上下游遗漏。"

        lines = ["## ⚠️ 全栈辐射检测报告\n"]
        by_severity = {"critical": [], "warning": [], "info": []}
        for a in alerts:
            by_severity.setdefault(a.severity, []).append(a)

        icons = {"critical": "🔴", "warning": "🟡", "info": "🔵"}
        for sev in ["critical", "warning", "info"]:
            items = by_severity.get(sev, [])
            if not items:
                continue
            lines.append(f"\n### {icons[sev]} {sev.upper()} ({len(items)})\n")
            for a in items:
                lines.append(f"- **{a.alert_type}** `{a.source_file}`")
                lines.append(f"  - {a.message}")
                lines.append(f"  - 💡 {a.suggestion}")
        return "\n".join(lines)


if __name__ == "__main__":
    # 演示
    import tempfile, os

    tmp = tempfile.mkdtemp()
    os.chdir(tmp)

    # 写个测试文件
    Path("test_rad.py").write_text(
        "import os\nkey = os.getenv('DB_HOST')\n"
        "def query():\n    cursor.execute('SELECT * FROM users')\n",
        encoding="utf-8")

    rd = RadiationDetector(".")
    alerts = rd.scan("test_rad.py")
    print(rd.generate_report(alerts))

    # POC 报告演示
    n = Nuwa("test_poc")
    n.add("规则通过率", "92%", "", "ok")
    n.add("违规回滚数", 3, "次", "warn")
    report = n.generate("演示 POC 报告")
    print(f"\n📊 {report.summary}")
