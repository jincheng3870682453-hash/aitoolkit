#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔═══════════════════════════════════════════════════════════════╗
║                  Nuwa · 女娲补天框架 V1.1                    ║
║           AI治理 B端交付层 · 12-Factor + POC报告             ║
║             增强：模块健康检查 + 违规明细 + 批量模式          ║
╚═══════════════════════════════════════════════════════════════╝
"""

import os
import sys
import json
import time
import uuid
import logging
import argparse
import subprocess
import webbrowser
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional, List, Tuple, Union
from dataclasses import dataclass, field

# ============================================================
# 0. 确保能导入同目录下的原有模块
# ============================================================
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

try:
    from gateway import UnifiedGateway
    from work import load_config, Context, BaitPool, detect_bait_fix
    import guardian
    import work
except ImportError as e:
    print(f"❌ 错误：缺少核心模块，请确保 nuwa.py 与 gateway.py, work.py, guardian.py, Archive.py 在同一目录。\n{e}")
    sys.exit(1)

# ============================================================
# 0.5 模块健康检查（补点 1）
# ============================================================
def assert_module_health():
    """启动时断言依赖模块的接口是否存在，防止静默失效"""
    required_checks = [
        (work, 'BaitPool', 'generate_bait'),
        (work, 'detect_bait_fix', None),
        (guardian, 'PhysicalCheckpoint', 'hard_rollback'),
        (guardian, 'validate_project', None),
    ]
    for mod, attr_name, method_name in required_checks:
        if not hasattr(mod, attr_name):
            raise ImportError(
                f"❌ Nuwa 与当前 {mod.__name__}.py 版本不兼容："
                f"找不到 {attr_name}。请确保 work/guardian 为 V8.0+ 版本。"
            )
        if method_name:
            obj = getattr(mod, attr_name)
            if not hasattr(obj, method_name):
                raise ImportError(
                    f"❌ Nuwa 与当前 {mod.__name__}.py 版本不兼容："
                    f"{attr_name}.{method_name} 不存在。请升级模块。"
                )
    logger.info("✅ Nuwa 模块健康检查通过（work/guardian 接口匹配）")


# ============================================================
# 1. 日志配置（受环境变量控制）
# ============================================================
LOG_LEVEL = os.environ.get("NUWA_LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("Nuwa")

# 健康检查在导入后立即执行
assert_module_health()


# ============================================================
# 2. 配置加载器（12-Factor 核心）
# ============================================================
@dataclass
class NuwaConfig:
    project_root: str = os.environ.get("NUWA_PROJECT_ROOT", ".")
    ai_provider: str = os.environ.get("NUWA_AI_PROVIDER", "ollama")
    ai_model: str = os.environ.get("NUWA_AI_MODEL", "llama2")
    ai_api_key: str = os.environ.get("NUWA_AI_API_KEY", "")
    ai_base_url: str = os.environ.get("NUWA_AI_BASE_URL", "")
    confirm_mode: str = os.environ.get("NUWA_CONFIRM_MODE", "interactive")
    smoke_timeout: int = int(os.environ.get("NUWA_SMOKE_TIMEOUT", "30"))
    poc_output_dir: str = os.environ.get("NUWA_POC_OUTPUT_DIR", "./poc_reports")
    planner: str = os.environ.get("NUWA_PLANNER", "rule")
    ignore_patterns: List[str] = field(
        default_factory=lambda: os.environ.get("NUWA_IGNORE_PATTERNS", ".git,__pycache__,*.pyc,*.log,*.tmp").split(",")
    )

    def __post_init__(self):
        # 优先从 NUWA_CONFIG 环境变量指定的配置文件加载
        env_config = os.environ.get("NUWA_CONFIG", "")
        if env_config and os.path.exists(env_config):
            try:
                with open(env_config, 'r', encoding='utf-8') as f:
                    cfg = json.load(f)
                # 用配置文件中的值覆盖环境变量默认值
                if cfg.get("api_key"):
                    self.ai_api_key = cfg["api_key"]
                if cfg.get("provider"):
                    self.ai_provider = cfg["provider"]
                if cfg.get("model"):
                    self.ai_model = cfg["model"]
                if cfg.get("base_url"):
                    self.ai_base_url = cfg["base_url"]
                logger.info("✅ 已从 NUWA_CONFIG 配置文件加载配置")
            except Exception as e:
                logger.warning(f"NUWA_CONFIG 配置文件读取失败: {e}")
        Path(self.poc_output_dir).mkdir(parents=True, exist_ok=True)
        Path(self.project_root).mkdir(parents=True, exist_ok=True)


# ============================================================
# 3. 指标采集器（新增 validation_details 补点2）
# ============================================================
class NuwaMetrics:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._reset()
        return cls._instance

    def _reset(self):
        self.start_time = time.time()
        self.end_time = None
        self.status = "unknown"
        self.user_input = ""
        self.error_log = ""
        self.modified_files = {}
        self.evidence_archive = None
        self.memory_topic = None
        self.logs = []

        self.baits_injected = 0
        self.baits_triggered = 0
        self.repairs_attempted = 0
        self.repairs_succeeded = 0
        self.repairs_failed = 0
        self.rollbacks_triggered = 0
        self.validation_passed = False
        self.validation_message = ""
        # ★ 补点 2：明细列表
        self.validation_details: List[str] = []

    def to_dict(self) -> Dict:
        elapsed = (self.end_time or time.time()) - self.start_time
        return {
            "timestamp": datetime.now().isoformat(),
            "status": self.status,
            "elapsed_seconds": round(elapsed, 2),
            "user_input": self.user_input[:200],
            "modified_files_count": len(self.modified_files),
            "modified_files": list(self.modified_files.keys())[:20],
            "evidence_archive": self.evidence_archive,
            "memory_topic": self.memory_topic,
            "baits_injected": self.baits_injected,
            "baits_triggered": self.baits_triggered,
            "repairs_attempted": self.repairs_attempted,
            "repairs_succeeded": self.repairs_succeeded,
            "repairs_failed": self.repairs_failed,
            "rollbacks_triggered": self.rollbacks_triggered,
            "validation_passed": self.validation_passed,
            "validation_message": self.validation_message[:500],   # 保留简短摘要
            "validation_details": self.validation_details[:50],    # ★ 补点2：完整明细列表
            "logs": self.logs[-20:],
        }

metrics = NuwaMetrics()


def _patch_work_guardian():
    import functools

    # ---- 补丁 1: BaitPool.generate_bait ----
    original_generate = work.BaitPool.generate_bait

    @staticmethod
    @functools.wraps(original_generate)
    def wrapped_generate(code: str) -> str:
        metrics.baits_injected += 1
        return original_generate(code)

    work.BaitPool.generate_bait = wrapped_generate

    # ---- 补丁 2: detect_bait_fix ----
    original_detect = work.detect_bait_fix

    @functools.wraps(original_detect)
    def wrapped_detect(final_code: str, code_with_bait: str) -> bool:
        metrics.repairs_attempted += 1
        result = original_detect(final_code, code_with_bait)
        if result:
            metrics.repairs_succeeded += 1
        else:
            metrics.repairs_failed += 1
        return result

    work.detect_bait_fix = wrapped_detect

    # ---- 补丁 3: _run_smoke ----
    original_run_smoke = work.LayerNinth._run_smoke

    @functools.wraps(original_run_smoke)
    def wrapped_run_smoke(self, code: str, ctx) -> Tuple[bool, str]:
        ok, output = original_run_smoke(self, code, ctx)
        if not ok and "[BAIT_INJECTED]" in code:
            metrics.baits_triggered += 1
        return ok, output

    work.LayerNinth._run_smoke = wrapped_run_smoke

    # ---- 补丁 4: guardian 回滚 ----
    original_rollback = guardian.PhysicalCheckpoint.hard_rollback

    @functools.wraps(original_rollback)
    def wrapped_rollback(self):
        metrics.rollbacks_triggered += 1
        return original_rollback(self)

    guardian.PhysicalCheckpoint.hard_rollback = wrapped_rollback

    # ---- 补丁 5: validate_project（补点2 明细捕获） ----
    original_validate = guardian.validate_project

    @functools.wraps(original_validate)
    def wrapped_validate(project_root: str, checks: List[str] = None) -> Tuple[bool, str]:
        ok, msg = original_validate(project_root, checks)
        metrics.validation_passed = ok
        metrics.validation_message = msg[:500] if msg else ""
        # ★ 补点2：拆分违规明细（按行或按 "- " 条目）
        if msg:
            if "\n" in msg:
                parts = [line.strip() for line in msg.split("\n") if line.strip()]
                metrics.validation_details = parts
            elif " - " in msg:
                metrics.validation_details = [item.strip() for item in msg.split(" - ") if item.strip()]
            else:
                metrics.validation_details = [msg]
        else:
            metrics.validation_details = []
        return ok, msg

    guardian.validate_project = wrapped_validate

    logger.info("✅ Nuwa 指标埋点已全部注入（含违规明细捕获）")


# ============================================================
# 4. POC 报告生成器（新增可折叠违规表格 补点2）
# ============================================================
class POCReportGenerator:
    @staticmethod
    def generate(metrics_dict: Dict, config: NuwaConfig) -> Tuple[str, str]:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        run_id = str(uuid.uuid4())[:8]
        base_name = f"poc_{run_id}_{timestamp}"

        html_path = Path(config.poc_output_dir) / f"{base_name}.html"
        json_path = Path(config.poc_output_dir) / f"{base_name}.json"

        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(metrics_dict, f, indent=2, ensure_ascii=False)

        html_content = POCReportGenerator._build_html(metrics_dict, config, run_id)
        with open(html_path, 'w', encoding='utf-8') as f:
            f.write(html_content)

        return str(html_path), str(json_path)

    @staticmethod
    def _build_html(metrics_dict: Dict, config: NuwaConfig, run_id: str) -> str:
        status_color = "#27ae60" if metrics_dict["status"] == "success" else "#e74c3c"
        status_icon = "✅" if metrics_dict["status"] == "success" else "❌"

        cards = [
            ("状态", f"{status_icon} {metrics_dict['status'].upper()}", status_color),
            ("总耗时", f"{metrics_dict['elapsed_seconds']}s", "#3498db"),
            ("诱饵注入", f"{metrics_dict['baits_injected']}", "#8e44ad"),
            ("诱饵触发", f"{metrics_dict['baits_triggered']}", "#e67e22"),
            ("修复成功率", f"{metrics_dict['repairs_succeeded']}/{metrics_dict['repairs_attempted']}", "#2ecc71"),
            ("修复失败", f"{metrics_dict['repairs_failed']}", "#e74c3c"),
            ("物理回滚", f"{metrics_dict['rollbacks_triggered']}", "#c0392b"),
            ("修改文件", f"{metrics_dict['modified_files_count']}", "#2980b9"),
            ("验证通过", "✅" if metrics_dict['validation_passed'] else "❌", "#2c3e50"),
        ]

        cards_html = "".join([
            f"""<div class="card"><div class="card-label">{label}</div><div class="card-value" style="color:{color}">{value}</div></div>"""
            for label, value, color in cards
        ])

        # ★ 补点2：可折叠的违规明细表格
        details = metrics_dict.get("validation_details", [])
        details_html = ""
        if details:
            rows = "".join([f"<tr><td>{i+1}</td><td>{d}</td></tr>" for i, d in enumerate(details[:50])])
            details_html = f"""
            <details>
                <summary style="cursor:pointer;font-weight:600;color:#c0392b;">
                    ⚠️ 查看违规明细（共 {len(details)} 条）
                </summary>
                <table style="margin-top:12px;">
                    <thead><tr><th style="width:40px;">#</th><th>违规描述</th></tr></thead>
                    <tbody>{rows}</tbody>
                </table>
                {f"<div style='margin-top:8px;font-size:13px;color:#95a5a6;'>仅显示前50条</div>" if len(details)>50 else ""}
            </details>
            """
        else:
            details_html = "<div style='color:#27ae60;'>✅ 无违规明细</div>"

        logs_html = "".join([
            f"<tr><td>{i+1}</td><td>{log}</td></tr>"
            for i, log in enumerate(metrics_dict.get("logs", [])[-15:])
        ]) or "<tr><td colspan='2'>无日志</td></tr>"

        return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <title>女娲 · POC验证报告</title>
    <style>
        * {{ margin:0;padding:0;box-sizing:border-box; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
               background: #f5f7fa; padding: 40px 20px; color: #2c3e50; }}
        .container {{ max-width: 1200px; margin: 0 auto; }}
        .header {{ background: linear-gradient(135deg, #1a1a2e, #16213e); color: #fff;
                  padding: 40px; border-radius: 16px; margin-bottom: 30px; }}
        .header h1 {{ font-size: 32px; font-weight: 300; letter-spacing: 2px; }}
        .header h1 strong {{ font-weight: 700; color: #f1c40f; }}
        .sub {{ margin-top: 10px; opacity: 0.7; font-size: 14px; }}
        .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
                gap: 16px; margin-bottom: 30px; }}
        .card {{ background: #fff; padding: 20px; border-radius: 12px; box-shadow: 0 2px 8px rgba(0,0,0,0.08);
                text-align: center; }}
        .card-label {{ font-size: 13px; color: #7f8c8d; text-transform: uppercase; }}
        .card-value {{ font-size: 28px; font-weight: 700; margin-top: 8px; }}
        .section {{ background: #fff; border-radius: 12px; padding: 24px; margin-bottom: 20px;
                    box-shadow: 0 2px 8px rgba(0,0,0,0.06); }}
        .section h2 {{ font-size: 18px; font-weight: 600; margin-bottom: 16px; border-bottom: 2px solid #ecf0f1;
                      padding-bottom: 8px; }}
        table {{ width: 100%; border-collapse: collapse; font-size: 14px; }}
        th {{ text-align: left; padding: 8px 12px; background: #f8f9fa; }}
        td {{ padding: 6px 12px; border-bottom: 1px solid #ecf0f1; font-family: monospace; font-size: 13px; }}
        .badge {{ display: inline-block; padding: 2px 10px; border-radius: 20px; font-size: 12px; font-weight: 600; }}
        .badge-success {{ background: #d5f5e3; color: #27ae60; }}
        .badge-danger {{ background: #fadbd8; color: #e74c3c; }}
        .file-list {{ font-family: monospace; font-size: 13px; background: #f8f9fa; padding: 12px; border-radius: 8px; }}
        details {{ margin: 12px 0; }}
        details summary {{ font-size: 15px; padding: 8px; background: #fef9e7; border-radius: 6px; }}
        .footer {{ text-align: center; margin-top: 30px; font-size: 13px; color: #95a5a6; }}
    </style>
</head>
<body>
<div class="container">
    <div class="header">
        <h1>🐍 女娲 · <strong>POC验证报告</strong></h1>
        <div class="sub">运行ID: {run_id} | 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</div>
        <div class="sub">项目: {config.project_root} | AI: {config.ai_provider}/{config.ai_model}</div>
    </div>

    <div class="grid">{cards_html}</div>

    <div class="section">
        <h2>📁 修改文件</h2>
        <div class="file-list">{', '.join(metrics_dict.get('modified_files', [])[:10]) or '无'}</div>
    </div>

    <div class="section">
        <h2>📋 违规明细</h2>
        {details_html}
    </div>

    <div class="section">
        <h2>📋 执行日志</h2>
        <table><thead><tr><th style="width:40px;">#</th><th>日志</th></tr></thead><tbody>{logs_html}</tbody></table>
    </div>

    <div class="section">
        <h2>📌 验证结论</h2>
        <p><span class="badge {'badge-success' if metrics_dict['validation_passed'] else 'badge-danger'}">
            {'通过' if metrics_dict['validation_passed'] else '未通过'}
        </span> &nbsp; {metrics_dict.get('validation_message', '无')[:200]}</p>
        <p style="margin-top:12px;font-size:13px;color:#7f8c8d;">
            修复成功率: {metrics_dict['repairs_succeeded']}/{max(metrics_dict['repairs_attempted'],1)}
            ({round(metrics_dict['repairs_succeeded']/max(metrics_dict['repairs_attempted'],1)*100, 1)}%)
            &nbsp;|&nbsp; 回滚: {metrics_dict['rollbacks_triggered']}
        </p>
    </div>
    <div class="footer">女娲补天 · AI治理 B端交付层</div>
</div>
</body>
</html>
"""


# ============================================================
# 5. 批量请求加载器（补点3）
# ============================================================
def load_batch_requests(filepath: str) -> List[Dict[str, str]]:
    """支持纯文本（每行一个需求）或 JSON 数组（含 error 字段）"""
    path = Path(filepath)
    if not path.exists():
        raise FileNotFoundError(f"批量文件不存在: {filepath}")

    content = path.read_text(encoding='utf-8').strip()
    if not content:
        return []

    # 尝试 JSON 解析
    try:
        data = json.loads(content)
        if isinstance(data, list):
            # 标准格式：[{"input": "xxx", "error": "yyy"}]
            return data
        elif isinstance(data, dict):
            return [data]
    except json.JSONDecodeError:
        pass

    # 降级为纯文本（每行一个需求）
    lines = [line.strip() for line in content.splitlines() if line.strip()]
    return [{"input": line, "error": ""} for line in lines]


# ============================================================
# 6. 主控制器（新增 batch 模式）
# ============================================================
class NuwaOrchestrator:
    def __init__(self):
        self.config = NuwaConfig()
        self.metrics = metrics
        self._patching_applied = False

    def _ensure_patch(self):
        if not self._patching_applied:
            _patch_work_guardian()
            self._patching_applied = True

    def run(self, user_input: str, error_log: str = "", dry_run: bool = False,
            open_report: bool = False) -> Dict[str, Any]:
        self._ensure_patch()
        self.metrics._reset()
        self.metrics.user_input = user_input
        self.metrics.error_log = error_log

        logger.info(f"🚀 女娲运行: {user_input[:50]}...")

        gw = UnifiedGateway(
            project_root=self.config.project_root,
            confirm_mode=self.config.confirm_mode,
            planner=self.config.planner,
            ai_provider=self.config.ai_provider,
            ai_model=self.config.ai_model,
            ai_api_key=self.config.ai_api_key,
            ai_base_url=self.config.ai_base_url,
            smoke_timeout=self.config.smoke_timeout,
            ignore_patterns=self.config.ignore_patterns,
            debug=(LOG_LEVEL == "DEBUG")
        )

        try:
            result = gw.run(
                user_input=user_input,
                error_log=error_log,
                conversation_id=f"nuwa_{uuid.uuid4().hex[:8]}",
                enable_memory=False,
                enable_guardian=True,
                dry_run=dry_run
            )
            self.metrics.status = result.get("status", "failed")
            self.metrics.modified_files = result.get("modified_files", {})
            self.metrics.evidence_archive = result.get("evidence_archive")
            self.metrics.memory_topic = result.get("memory_topic")
            self.metrics.logs = result.get("logs", [])
            if self.metrics.status == "success":
                logger.info("✅ 执行成功")
            else:
                logger.error(f"❌ 执行失败: {result.get('error', '未知')}")
        except Exception as e:
            self.metrics.status = "failed"
            self.metrics.logs.append(f"EXCEPTION: {str(e)}")
            logger.error(f"❌ 异常: {e}")
            result = {"status": "failed", "error": str(e), "modified_files": {}}
        finally:
            self.metrics.end_time = time.time()

        html_path, json_path = POCReportGenerator.generate(
            self.metrics.to_dict(),
            self.config
        )
        self.metrics.logs.append(f"报告: {html_path}")
        if open_report:
            try:
                webbrowser.open(html_path)
            except:
                pass
        result["poc_report_html"] = html_path
        result["poc_report_json"] = json_path
        return result

    # ★ 补点3：批量模式
    def run_batch(self, batch_file: str, dry_run: bool = False, open_report: bool = False) -> Dict[str, Any]:
        requests = load_batch_requests(batch_file)
        if not requests:
            logger.error("批量文件为空或无有效条目")
            return {"total": 0, "success": 0, "reports": []}

        logger.info(f"📦 批量模式启动，共 {len(requests)} 个任务")
        results = []
        total_success = 0
        total_time = 0.0
        total_rollbacks = 0
        total_repairs_attempt = 0
        total_repairs_success = 0

        for idx, req in enumerate(requests, 1):
            inp = req.get("input", "").strip()
            err = req.get("error", "")
            if not inp:
                logger.warning(f"跳过第 {idx} 条：输入为空")
                continue
            logger.info(f"\n--- 批量 [{idx}/{len(requests)}] ---")
            try:
                res = self.run(inp, err, dry_run=dry_run, open_report=False)
                results.append(res)
                if res.get("status") == "success":
                    total_success += 1
                total_time += self.metrics.to_dict().get("elapsed_seconds", 0)
                total_rollbacks += self.metrics.rollbacks_triggered
                total_repairs_attempt += self.metrics.repairs_attempted
                total_repairs_success += self.metrics.repairs_succeeded
            except Exception as e:
                logger.error(f"批量第 {idx} 条异常: {e}")
                results.append({"status": "failed", "error": str(e)})

        # 生成汇总报告
        summary = {
            "mode": "batch",
            "total_requests": len(requests),
            "processed": len(results),
            "success_count": total_success,
            "success_rate": f"{round(total_success/max(len(results),1)*100, 1)}%",
            "total_elapsed_seconds": round(total_time, 2),
            "avg_elapsed_seconds": round(total_time / max(len(results), 1), 2),
            "total_rollbacks": total_rollbacks,
            "repair_success_rate": f"{total_repairs_success}/{max(total_repairs_attempt,1)}",
            "individual_reports": [r.get("poc_report_html") for r in results if r.get("poc_report_html")]
        }

        summary_path = Path(self.config.poc_output_dir) / f"batch_summary_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
        summary_json_path = summary_path.with_suffix(".json")
        with open(summary_json_path, 'w', encoding='utf-8') as f:
            json.dump(summary, f, indent=2, ensure_ascii=False)

        # 简单的汇总 HTML
        html_content = f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><title>女娲批量汇总</title>
<style>body{{font-family:sans-serif;background:#f5f7fa;padding:40px;}}
.container{{max-width:900px;margin:0 auto;background:#fff;border-radius:16px;padding:30px;}}
h1{{color:#1a1a2e;}} .stats{{display:grid;grid-template-columns:repeat(4,1fr);gap:16px;margin:20px 0;}}
.stat-card{{background:#f8f9fa;padding:20px;border-radius:12px;text-align:center;}}
.num{{font-size:32px;font-weight:700;color:#16213e;}}
.label{{font-size:14px;color:#7f8c8d;}}
ul{{list-style:none;padding:0;}} li{{padding:8px;border-bottom:1px solid #ecf0f1;font-family:monospace;}}
</style></head>
<body>
<div class="container">
<h1>📊 女娲批量汇总报告</h1>
<div class="stats">
<div class="stat-card"><div class="num">{summary['processed']}</div><div class="label">处理总数</div></div>
<div class="stat-card"><div class="num">{summary['success_count']}</div><div class="label">成功数</div></div>
<div class="stat-card"><div class="num">{summary['success_rate']}</div><div class="label">成功率</div></div>
<div class="stat-card"><div class="num">{summary['avg_elapsed_seconds']}s</div><div class="label">平均耗时</div></div>
</div>
<p><strong>总回滚数:</strong> {summary['total_rollbacks']} &nbsp;|&nbsp; <strong>修复:</strong> {summary['repair_success_rate']}</p>
<h3>📄 子报告列表</h3>
<ul>{''.join([f"<li><a href='{Path(r).name}' target='_blank'>{Path(r).name}</a></li>" for r in summary['individual_reports']])}</ul>
</div></body></html>
"""
        with open(summary_path, 'w', encoding='utf-8') as f:
            f.write(html_content)

        logger.info(f"📊 批量汇总报告: {summary_path}")
        if open_report:
            try:
                webbrowser.open(str(summary_path))
            except:
                pass

        return summary


# ============================================================
# 7. 命令行入口（增加 --batch）
# ============================================================
def main():
    parser = argparse.ArgumentParser(
        description="女娲 · AI治理B端交付层 (12-Factor + POC报告 + 批量)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
环境变量（优先级最高）：
  NUWA_PROJECT_ROOT, NUWA_AI_PROVIDER, NUWA_AI_API_KEY, NUWA_CONFIRM_MODE ...

批量模式文件格式：
  JSON数组: [{"input":"修复登录","error":"NameError"}, ...]
  纯文本: 每行一个需求（无 error_log）
        """
    )
    parser.add_argument("user_input", nargs="?", help="单次运行的用户需求")
    parser.add_argument("error_log", nargs="?", default="", help="单次运行的错误日志（可选）")
    parser.add_argument("--batch", "-b", metavar="FILE", help="批量模式：从文件读取任务清单")
    parser.add_argument("--open-report", action="store_true", help="生成后自动打开报告")
    parser.add_argument("--dry-run", action="store_true", help="干跑预览")
    parser.add_argument("--debug", action="store_true", help="调试日志")

    args = parser.parse_args()

    if args.debug:
        os.environ["NUWA_LOG_LEVEL"] = "DEBUG"

    orchestrator = NuwaOrchestrator()

    # ★ 补点3：批量路由
    if args.batch:
        summary = orchestrator.run_batch(
            batch_file=args.batch,
            dry_run=args.dry_run,
            open_report=args.open_report
        )
        print(json.dumps(summary, indent=2, ensure_ascii=False))
        sys.exit(0)

    # 单次运行
    if not args.user_input:
        parser.print_help()
        sys.exit(1)

    result = orchestrator.run(
        user_input=args.user_input,
        error_log=args.error_log or "",
        dry_run=args.dry_run,
        open_report=args.open_report
    )
    print(json.dumps({
        "status": result.get("status"),
        "poc_report": result.get("poc_report_html"),
        "modified_files_count": len(result.get("modified_files", {})),
        "rollbacks": metrics.rollbacks_triggered,
        "repair_rate": f"{metrics.repairs_succeeded}/{max(metrics.repairs_attempted,1)}"
    }, indent=2))
    sys.exit(0 if result.get("status") == "success" else 1)


if __name__ == "__main__":
    main()