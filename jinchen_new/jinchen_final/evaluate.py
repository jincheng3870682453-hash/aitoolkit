#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
evaluate.py — 准确率评估框架 V3.2

定义 BenchmarkDataset 接口，支持从 JSON 文件加载标注数据，
运行检测后输出 precision / recall / f1 / false_positive_rate。

⚠️ 内置数据集为空，等待社区贡献。
⚠️ 当前仅评估 Python 检测（AST 版），多语言正则版准确率太低不纳入评估。
"""

import json
import sys
from pathlib import Path
from dataclasses import dataclass, field


@dataclass
class BenchmarkItem:
    """单条标注样本"""
    code: str
    expected_violations: list[str] = field(default_factory=list)
    filename: str = "sample.py"
    notes: str = ""


@dataclass
class BenchmarkDataset:
    """标注数据集"""
    items: list[BenchmarkItem] = field(default_factory=list)

    @classmethod
    def load(cls, path: str) -> "BenchmarkDataset":
        """从 JSON 文件加载数据集"""
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        items = []
        for d in data:
            items.append(BenchmarkItem(
                code=d["code"],
                expected_violations=d.get("expected_violations", []),
                filename=d.get("filename", "sample.py"),
                notes=d.get("notes", ""),
            ))
        return cls(items=items)

    def __len__(self) -> int:
        return len(self.items)


@dataclass
class EvalResult:
    """单条评估结果"""
    item_idx: int
    expected: list[str]
    detected: list[str]
    true_positives: list[str]
    false_positives: list[str]
    false_negatives: list[str]

    @property
    def precision(self) -> float:
        denom = len(self.true_positives) + len(self.false_positives)
        return len(self.true_positives) / denom if denom > 0 else 0.0

    @property
    def recall(self) -> float:
        denom = len(self.true_positives) + len(self.false_negatives)
        return len(self.true_positives) / denom if denom > 0 else 0.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) > 0 else 0.0


def run_evaluation(detector, dataset: BenchmarkDataset) -> dict:
    """
    对数据集运行检测，返回汇总统计。

    Args:
        detector: 具有 check_all(code) -> list[GuardResult] 接口的对象
        dataset: BenchmarkDataset 实例

    Returns:
        dict: {precision, recall, f1, false_positive_rate, total, details: [...]}
    """
    details: list[EvalResult] = []
    total_tp = 0
    total_fp = 0
    total_fn = 0

    for i, item in enumerate(dataset.items):
        results = detector.check_all(item.code)
        detected = [r.rule for r in results if not r.passed]

        expected = set(item.expected_violations)
        found = set(detected)

        tp = expected & found
        fp = found - expected
        fn = expected - found

        total_tp += len(tp)
        total_fp += len(fp)
        total_fn += len(fn)

        details.append(EvalResult(
            item_idx=i,
            expected=sorted(expected),
            detected=sorted(found),
            true_positives=sorted(tp),
            false_positives=sorted(fp),
            false_negatives=sorted(fn),
        ))

    precision = total_tp / (total_tp + total_fp) if (total_tp + total_fp) > 0 else 0.0
    recall = total_tp / (total_tp + total_fn) if (total_tp + total_fn) > 0 else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
    fpr = total_fp / len(dataset) if len(dataset) > 0 else 0.0

    return {
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "false_positive_rate": round(fpr, 4),
        "total": len(dataset),
        "true_positives": total_tp,
        "false_positives": total_fp,
        "false_negatives": total_fn,
        "details": [d.__dict__ for d in details],
    }


def print_report(result: dict):
    """打印人类可读的评估报告"""
    print("=" * 55)
    print("  📊 准确率评估报告")
    print("=" * 55)
    print(f"  样本总数:     {result['total']}")
    print(f"  精确率 (P):   {result['precision']:.2%}")
    print(f"  召回率 (R):   {result['recall']:.2%}")
    print(f"  F1 分数:      {result['f1']:.2%}")
    print(f"  误报率 (FPR): {result['false_positive_rate']:.2%}")
    print(f"  TP={result['true_positives']}  FP={result['false_positives']}  FN={result['false_negatives']}")
    print("=" * 55)

    # 打印每条样本的详情
    print("\n  📋 逐条详情:")
    for d in result["details"]:
        status = "✅" if not d["false_positives"] and not d["false_negatives"] else "⚠️"
        print(f"  {status} 样本 {d['item_idx']}:")
        if d["true_positives"]:
            print(f"      TP: {d['true_positives']}")
        if d["false_positives"]:
            print(f"      FP (误报): {d['false_positives']}")
        if d["false_negatives"]:
            print(f"      FN (漏报): {d['false_negatives']}")


# ═════════════════════════════════════════════════════
# CLI 入口
# ═════════════════════════════════════════════════════

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python evaluate.py <dataset.json>")
        print()
        print("数据集格式 (JSON):")
        print('  [{"code": "def f(x): pass", "expected_violations": ["type_hints"]}]')
        print()
        print("⚠️ 当前内置数据集为空，请准备标注数据后运行。")
        sys.exit(0)

    dataset_path = sys.argv[1]
    if not Path(dataset_path).exists():
        print(f"❌ 文件不存在: {dataset_path}")
        sys.exit(1)

    # 加载数据集
    dataset = BenchmarkDataset.load(dataset_path)

    if len(dataset) == 0:
        print("⚠️ 数据集为空，请添加标注样本。")
        sys.exit(0)

    # 使用 Python AST 检测器
    from Toolkit.work import InstinctGuard
    detector = InstinctGuard()

    # 运行评估
    result = run_evaluation(detector, dataset)
    print_report(result)

    # 保存报告
    report_path = Path(dataset_path).stem + "_report.json"
    Path(report_path).write_text(
        json.dumps(result, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"\n📄 报告已保存: {report_path}")
