#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
verify_real.py — 真实项目扫描框架 V3.2

⚠️ 框架就绪，但作者尚未在任何真实项目上跑过完整测试。

用法:
    python verify_real.py /path/to/your/project [--ext .py .java .kt]
    python verify_real.py /path/to/your/project --output report.json

功能:
    递归扫描指定目录下的代码文件，运行检测，输出统计报告。
    不修改任何文件，纯只读扫描。
"""

import sys
import json
import time
import argparse
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Optional


@dataclass
class ScanResult:
    """单个文件的扫描结果"""
    file: str = ""
    language: str = "unknown"
    total_violations: int = 0
    violations: list[dict] = field(default_factory=list)
    error: str = ""
    scan_time_ms: float = 0.0


@dataclass
class ScanReport:
    """完整扫描报告"""
    target_dir: str
    total_files: int = 0
    scanned_files: int = 0
    total_violations: int = 0
    files_with_violations: int = 0
    errors: int = 0
    total_time_ms: float = 0.0
    by_language: dict = field(default_factory=dict)
    by_rule: dict = field(default_factory=dict)
    results: list[ScanResult] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        return d

    def print_summary(self):
        print("=" * 55)
        print("  📊 真实项目扫描报告")
        print("=" * 55)
        print(f"  目标目录:     {self.target_dir}")
        print(f"  文件总数:     {self.total_files}")
        print(f"  成功扫描:     {self.scanned_files}")
        print(f"  扫描失败:     {self.errors}")
        print(f"  违规总数:     {self.total_violations}")
        print(f"  有违规的文件: {self.files_with_violations}")
        print(f"  总耗时:       {self.total_time_ms:.0f} ms")
        print()
        if self.by_language:
            print("  📋 按语言统计:")
            for lang, stats in sorted(self.by_language.items()):
                print(f"     {lang:12s} 文件={stats['files']:3d}  违规={stats['violations']:3d}")
        if self.by_rule:
            print()
            print("  📋 按规则统计:")
            for rule, count in sorted(self.by_rule.items(), key=lambda x: -x[1]):
                print(f"     {rule:25s} {count:3d}")
        print("=" * 55)
        print()
        print("  ⚠️ 注意：非 Python 语言的检测基于正则，")
        print("     准确率很低，以下数据仅供参考。")


def scan_directory(
    target: str,
    extensions: Optional[list[str]] = None,
    max_files: int = 5000,
) -> ScanReport:
    """
    递归扫描目录，对代码文件运行检测。

    Args:
        target: 目标目录路径
        extensions: 要扫描的文件扩展名列表（含点号）
        max_files: 最大扫描文件数（防止扫到 node_modules 等）

    Returns:
        ScanReport
    """
    if extensions is None:
        extensions = [".py", ".java", ".kt", ".ts", ".swift"]

    target_path = Path(target)
    if not target_path.exists() or not target_path.is_dir():
        raise ValueError(f"目录不存在: {target}")

    # 收集文件
    all_files = []
    for ext in extensions:
        all_files.extend(target_path.rglob(f"*{ext}"))

    # 排除常见无关目录
    skip_dirs = {"node_modules", ".git", "__pycache__", "venv", "env",
                 "build", "dist", ".idea", ".vscode", "target"}
    filtered = []
    for f in all_files:
        if any(part in skip_dirs for part in f.parts):
            continue
        filtered.append(f)

    filtered = filtered[:max_files]

    # 初始化报告
    report = ScanReport(
        target_dir=str(target_path),
        total_files=len(filtered),
    )

    # 延迟导入（避免影响其他模块）
    from Toolkit.work import InstinctGuard, MultiLangASTEngine

    ig = InstinctGuard()
    ml = MultiLangASTEngine()

    start = time.time()

    for f in filtered:
        rel_path = str(f.relative_to(target_path))
        result = ScanResult(file=rel_path)

        t0 = time.time()
        try:
            code = f.read_text(encoding="utf-8", errors="ignore")

            # 判断语言
            lang = ml.detect_language(code, str(f))
            result.language = lang

            # 运行检测
            if lang == "python":
                guard_results = ig.check_all(code)
                for gr in guard_results:
                    if not gr.passed:
                        result.violations.append({
                            "rule": gr.rule,
                            "message": gr.message,
                        })
                        report.by_rule[gr.rule] = report.by_rule.get(gr.rule, 0) + 1
            else:
                ml_results = ml.check(code, str(f))
                for v in ml_results.get("violations", []):
                    result.violations.append({
                        "rule": v["rule"],
                        "method": v.get("method", "regex"),
                    })
                    report.by_rule[v["rule"]] = report.by_rule.get(v["rule"], 0) + 1

            result.total_violations = len(result.violations)

        except Exception as e:
            result.error = f"{type(e).__name__}: {e}"
            report.errors += 1

        result.scan_time_ms = (time.time() - t0) * 1000
        report.results.append(result)
        report.scanned_files += 1
        report.total_violations += result.total_violations

        if result.total_violations > 0:
            report.files_with_violations += 1

        # 按语言统计
        lang = result.language or "unknown"
        if lang not in report.by_language:
            report.by_language[lang] = {"files": 0, "violations": 0}
        report.by_language[lang]["files"] += 1
        report.by_language[lang]["violations"] += result.total_violations

    report.total_time_ms = (time.time() - start) * 1000

    return report


# ═════════════════════════════════════════════════════
# CLI 入口
# ═════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="真实项目扫描框架（V3.2 诚实版）"
    )
    parser.add_argument("target", help="要扫描的目录路径")
    parser.add_argument(
        "--ext", nargs="+", default=[".py", ".java", ".kt", ".ts", ".swift"],
        help="要扫描的文件扩展名（默认: .py .java .kt .ts .swift）"
    )
    parser.add_argument("--output", "-o", help="输出报告到 JSON 文件")
    parser.add_argument(
        "--top", type=int, default=20,
        help="显示违规最多的前 N 个文件（默认 20）"
    )

    args = parser.parse_args()

    if not Path(args.target).exists():
        print(f"❌ 目录不存在: {args.target}")
        sys.exit(1)

    print(f"🔍 扫描目录: {args.target}")
    print(f"   扩展名: {', '.join(args.ext)}")
    print()

    try:
        report = scan_directory(args.target, extensions=args.ext)
    except Exception as e:
        print(f"❌ 扫描失败: {e}")
        sys.exit(1)

    report.print_summary()

    # 显示违规最多的文件
    sorted_files = sorted(
        report.results,
        key=lambda r: r.total_violations,
        reverse=True,
    )
    top_files = [r for r in sorted_files if r.total_violations > 0][:args.top]

    if top_files:
        print(f"\n  📋 违规最多的前 {len(top_files)} 个文件:")
        for r in top_files:
            lang_tag = f"[{r.language}]"
            print(f"     {r.total_violations:3d} {lang_tag:8s} {r.file}")
            for v in r.violations[:3]:
                rule = v.get("rule", "?")
                method = v.get("method", "")
                tag = f" ({method})" if method else ""
                print(f"            └─ {rule}{tag}")

    # 保存报告
    if args.output:
        Path(args.output).write_text(
            json.dumps(report.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        print(f"\n📄 报告已保存: {args.output}")

    print()
    print("  ⚠️ 免责声明：本扫描结果仅供参考。")
    print("     非 Python 语言的检测基于正则，误报率很高。")


if __name__ == "__main__":
    main()
