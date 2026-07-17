"""
guardian.py —— 物理快照与回滚 + 违规判决书

设计思路：
  - 快照：修改前拍照，回滚时还原（借鉴 git stash 的思路）
  - 判决书：每次回滚生成可读记录（诚实标注：本地审计，非密码学防篡改）
  - 熔断：所有文件操作包裹 safe_call，失败不崩

对外接口：
    Guardian(root).snapshot(name) -> snap_id
    Guardian(root).rollback(snap_id) -> bool
    Guardian(root).list_snapshots() -> list
    RollbackJury(root).issue_verdict(...) -> Verdict
"""

import os
import re
import json
import time
import shutil
import hashlib
import logging
import zipfile
import tempfile
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Optional, Callable, Any

log = logging.getLogger("jinchen.guardian")


# ═════════════════════════════════════════════════════════
#  工具：safe_call 装饰器（全局熔断）
# ═════════════════════════════════════════════════════════
@dataclass
class SafeResult:
    """安全调用结果"""
    ok: bool
    data: Any = None
    error: str = ""
    conservative: bool = False


def safe_call(label: str, fallback=None):
    """
    装饰器：任何外部调用失败 → 返回保守结果，不崩溃

    借鉴 RASP / 熔断器模式：
    - 模型挂了 → 保守通过
    - 磁盘满了 → 返回错误但不崩
    - 文件坏了 → 记一笔，继续跑
    """
    def deco(func):
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                log.error(f"⚠️ {label} 失败: {type(e).__name__}: {e}")
                return SafeResult(ok=False, error=f"{type(e).__name__}: {e}",
                                 conservative=True, data=fallback)
        return wrapper
    return deco


# ═════════════════════════════════════════════════════════
#  ConservativePass（保守通过标记）
# ═════════════════════════════════════════════════════════
@dataclass
class ConservativePass:
    """
    拿不准就先放行，但记一笔

    借鉴 AI Code Review 的"不确定时标记而非阻断"思路。
    不阻断流程，但留审计痕迹。
    """
    reason: str
    fallback_used: str = ""
    timestamp: str = field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%S"))

    def to_dict(self) -> dict:
        return asdict(self)


# ═════════════════════════════════════════════════════════
#  Guardian —— 快照与回滚
# ═════════════════════════════════════════════════════════
class Guardian:
    """
    物理快照管理器

    设计：
    - 每次修改前 snapshot() → 打包成 zip 存到 .snapshots/
    - rollback(id) → 清空当前目录，解压快照还原
    - 预检：空快照拒绝回滚（防止清空目录）
    - 完整性：每个快照带 SHA-256 校验

    借鉴 git 的 object store 思路，但更简单：
    不用 diff，直接全量打包（小项目够用）。
    """

    SNAPSHOT_DIR = ".snapshots"

    def __init__(self, root: str = "."):
        self.root = Path(root).resolve()
        self.snap_dir = self.root / self.SNAPSHOT_DIR
        self.snap_dir.mkdir(exist_ok=True)

    def _snapshot_path(self, snap_id: str) -> Path:
        return self.snap_dir / f"{snap_id}.zip"

    def _integrity_file(self, snap_id: str) -> Path:
        return self.snap_dir / f"{snap_id}.sha256"

    @safe_call("创建快照", fallback="")
    def snapshot(self, name: str = "") -> str:
        """
        给当前目录拍照

        返回快照 ID。
        失败时返回 SafeResult（不抛异常）。
        """
        ts = time.strftime("%Y%m%d-%H%M%S")
        snap_id = f"snap-{ts}-{os.urandom(2).hex()}"
        name = name or snap_id

        zip_path = self._snapshot_path(snap_id)
        files_count = 0

        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            for f in self._iter_files():
                arcname = f.relative_to(self.root)
                zf.write(f, arcname)
                files_count += 1

        # 空目录保护：不允许创建空快照
        if files_count == 0:
            zip_path.unlink(missing_ok=True)
            raise ValueError("当前目录为空，拒绝创建空快照（防止误清目录）")

        # 写完整性校验文件
        sha = self._hash_file(zip_path)
        self._integrity_file(snap_id).write_text(
            json.dumps({
                "snapshot_id": snap_id,
                "name": name,
                "files": files_count,
                "size": zip_path.stat().st_size,
                "sha256": sha,
                "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
            }, indent=2),
            encoding="utf-8",
        )

        log.info(f"📸 快照 {snap_id} 创建完成（{files_count} 个文件）")
        return snap_id

    @safe_call("回滚快照", fallback=False)
    def rollback(self, snap_id: str) -> bool:
        """
        回滚到指定快照

        流程：
        1. 校验快照完整性
        2. 清空当前目录（保留 .snapshots/）
        3. 解压还原
        """
        zip_path = self._snapshot_path(snap_id)
        if not zip_path.exists():
            raise FileNotFoundError(f"快照不存在: {snap_id}")

        # 1. 完整性校验
        integrity = self._integrity_file(snap_id)
        if integrity.exists():
            meta = json.loads(integrity.read_text(encoding="utf-8"))
            current_sha = self._hash_file(zip_path)
            if current_sha != meta["sha256"]:
                raise ValueError(f"快照 {snap_id} 完整性校验失败（可能被篡改或损坏）")

        # 2. 清空当前目录（保留快照目录和 .git）
        for item in self.root.iterdir():
            if item.name in (self.SNAPSHOT_DIR, ".git", ".gitignore"):
                continue
            if item.is_dir():
                shutil.rmtree(item)
            else:
                item.unlink()

        # 3. 解压还原
        with zipfile.ZipFile(zip_path, 'r') as zf:
            zf.extractall(self.root)

        log.info(f"⏪ 已回滚到 {snap_id}")
        return True

    def list_snapshots(self) -> list:
        """列出所有快照"""
        snaps = []
        for f in sorted(self.snap_dir.glob("*.sha256")):
            try:
                meta = json.loads(f.read_text(encoding="utf-8"))
                snaps.append(meta)
            except Exception:
                pass
        # 兼容旧版 .json 格式
        for f in sorted(self.snap_dir.glob("*.json")):
            try:
                meta = json.loads(f.read_text(encoding="utf-8"))
                snaps.append(meta)
            except Exception:
                pass
        return snaps

    def verify_all(self) -> dict:
        """校验所有快照完整性"""
        results = {}
        for snap in self.list_snapshots():
            sid = snap["snapshot_id"]
            zip_path = self._snapshot_path(sid)
            if not zip_path.exists():
                results[sid] = {"ok": False, "reason": "zip 文件缺失"}
                continue
            current_sha = self._hash_file(zip_path)
            results[sid] = {
                "ok": current_sha == snap.get("sha256"),
                "expected": snap.get("sha256", "")[:16],
                "actual": current_sha[:16],
            }
        return results

    def _iter_files(self):
        """遍历目录下所有文件（排除快照目录和 .git）"""
        exclude = {self.SNAPSHOT_DIR, ".git", "__pycache__", ".venv", "venv", "node_modules"}
        for root, dirs, files in os.walk(self.root):
            dirs[:] = [d for d in dirs if d not in exclude and not d.startswith('.')]
            for f in files:
                if f.endswith(('.pyc', '.pyo')):
                    continue
                yield Path(root) / f

    def _hash_file(self, path: Path) -> str:
        h = hashlib.sha256()
        with open(path, 'rb') as f:
            for chunk in iter(lambda: f.read(8192), b''):
                h.update(chunk)
        return h.hexdigest()


# ═════════════════════════════════════════════════════════
#  RollbackJury —— 违规判决书
# ═════════════════════════════════════════════════════════
@dataclass
class Verdict:
    """一份违规判决书（本地审计日志）"""
    verdict_id: str
    timestamp: str
    user: str
    env: str
    model: str
    rule_violated: str
    severity: str
    original_code: str
    violation_line: str
    evidence: dict
    fix_suggestion: str
    snapshot_id: str
    integrity_hash: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    def to_markdown(self) -> str:
        """给人看的判决书"""
        d = self.to_dict()
        return f"""# ⚖️ 违规记录 `{d['verdict_id']}`

| 字段 | 值 |
|------|---|
| 时间 | {d['timestamp']} |
| 用户 | {d['user']} |
| 环境 | {d['env']} |
| AI 模型 | {d['model']} |
| 违规规则 | `{d['rule_violated']}` |
| 严重等级 | **{d['severity'].upper()}** |

## 📋 违规代码

```python
{d['violation_line'][:500]}
```

## 🔍 证据

```json
{json.dumps(d['evidence'], indent=2, ensure_ascii=False)[:1000]}
```

## 🔧 修复建议

{d['fix_suggestion']}

## 💾 快照恢复

```
guardian rollback --snapshot {d['snapshot_id']}
```

---
> ⚠️ 本文件为**本地自动生成审计日志**，使用 SHA-256 做完整性校验。
> 不具备密码学级别的防篡改能力，请勿用于法律举证。
> 完整性哈希: `{d['integrity_hash'][:16]}...`
"""


class RollbackJury:
    """
    回滚陪审团 —— 每次回滚/违规生成记录

    诚实标注：
    - 用 SHA-256 做完整性校验（不是签名）
    - 没有私钥参与，不能防伪
    - 定位是"本地审计参考"，不是"法律证据"
    """

    SEVERITY_MAP = {
        "no_hardcoded_secrets":   "critical",
        "no_sql_injection":       "critical",
        "no_subprocess_shell":    "critical",
        "no_sql_string_concat":   "critical",
        "no_pickle_deserialize":  "high",
        "try_except":             "high",
        "no_infinite_recursion":  "high",
        "no_bare_except":         "high",
        "type_hints":             "medium",
        "no_global_mutable":      "medium",
        "v1_ast_check":           "medium",
        "no_unused_import":       "low",
        "markdown_clean":         "low",
    }

    def __init__(self, verdict_dir: str = "verdicts"):
        self.verdict_dir = Path(verdict_dir)
        self.verdict_dir.mkdir(exist_ok=True)

    def issue_verdict(self, *, rule_name: str, original_code: str = "",
                     evidence: Optional[dict] = None,
                     fix_suggestion: str = "",
                     snapshot_id: str = "",
                     user: str = "anonymous",
                     env: str = "dev",
                     model: str = "unknown") -> Verdict:
        """签发一份判决书"""
        evidence = evidence or {}
        severity = self.SEVERITY_MAP.get(rule_name, "medium")

        # 提取违规行
        violation_lines = evidence.get("matched_lines", [])
        violation_text = "\n".join(violation_lines) if violation_lines else original_code[:200]

        # 生成 ID
        vid = f"V-{time.strftime('%Y%m%d-%H%M%S')}-{os.urandom(2).hex()[:4]}"

        # 完整性哈希（诚实标注：不是签名）
        raw = json.dumps({
            "id": vid, "rule": rule_name, "code": original_code[:200],
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }, sort_keys=True, ensure_ascii=False)
        integrity = hashlib.sha256(raw.encode()).hexdigest()

        v = Verdict(
            verdict_id=vid,
            timestamp=time.strftime("%Y-%m-%dT%H:%M:%S"),
            user=user, env=env, model=model,
            rule_violated=rule_name, severity=severity,
            original_code=original_code[:1000],
            violation_line=violation_text[:500],
            evidence=evidence,
            fix_suggestion=fix_suggestion,
            snapshot_id=snapshot_id,
            integrity_hash=integrity,
        )

        # 保存 JSON
        with open(self.verdict_dir / f"{vid}.json", "w", encoding="utf-8") as f:
            json.dump(v.to_dict(), f, indent=2, ensure_ascii=False)

        # 保存 Markdown（人读版）
        with open(self.verdict_dir / f"{vid}.md", "w", encoding="utf-8") as f:
            f.write(v.to_markdown())

        log.info(f"⚖️ 判决书签发: {vid} [{severity}] {rule_name}")
        return v

    def list_verdicts(self) -> list:
        """列出所有判决书"""
        files = sorted(self.verdict_dir.glob("V-*.json"))
        return [json.loads(f.read_text(encoding="utf-8")) for f in files]

    def stats(self) -> dict:
        """统计（用于 README / POC 报告）"""
        verdicts = self.list_verdicts()
        by_severity: dict = {}
        by_rule: dict = {}
        for v in verdicts:
            s = v.get("severity", "unknown")
            by_severity[s] = by_severity.get(s, 0) + 1
            r = v.get("rule_violated", "unknown")
            by_rule[r] = by_rule.get(r, 0) + 1
        return {
            "total": len(verdicts),
            "by_severity": by_severity,
            "by_rule": by_rule,
        }

    def verify_integrity(self) -> dict:
        """校验所有判决书完整性"""
        results = {}
        for v in self.list_verdicts():
            vid = v["verdict_id"]
            raw = json.dumps({
                "id": vid, "rule": v["rule_violated"],
                "code": v.get("original_code", "")[:200],
                "ts": v["timestamp"],
            }, sort_keys=True, ensure_ascii=False)
            expected = hashlib.sha256(raw.encode()).hexdigest()
            actual = v.get("integrity_hash", "")
            results[vid] = {
                "ok": expected == actual,
                "severity": v.get("severity"),
                "rule": v.get("rule_violated"),
            }
        return results


# ═════════════════════════════════════════════════════════
#  CLI 入口
# ═════════════════════════════════════════════════════════
if __name__ == "__main__":
    import argparse
    import sys

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    parser = argparse.ArgumentParser(description="Guardian —— 快照与回滚")
    parser.add_argument("action", choices=["snapshot", "rollback", "list", "verify"])
    parser.add_argument("--snapshot", "-s", help="快照 ID")
    parser.add_argument("--name", "-n", default="", help="快照名称")
    parser.add_argument("--root", "-r", default=".", help="项目根目录")
    args = parser.parse_args()

    g = Guardian(root=args.root)
    jury = RollbackJury(verdict_dir=Path(args.root) / "verdicts")

    if args.action == "snapshot":
        result = g.snapshot(name=args.name)
        if isinstance(result, SafeResult):
            print(f"❌ 快照失败: {result.error}")
            sys.exit(1)
        print(f"✅ 快照创建: {result}")

    elif args.action == "rollback":
        if not args.snapshot:
            print("❌ 请指定 --snapshot <id>")
            sys.exit(1)
        result = g.rollback(args.snapshot)
        if isinstance(result, SafeResult):
            print(f"❌ 回滚失败: {result.error}")
            sys.exit(1)
        print(f"✅ 已回滚到 {args.snapshot}")

    elif args.action == "list":
        snaps = g.list_snapshots()
        if not snaps:
            print("（无快照）")
        for s in snaps:
            print(f"  {s['snapshot_id']}  {s['name']}  "
                  f"({s['files']} files, {s['size']} bytes)")

    elif args.action == "verify":
        results = g.verify_all()
        for sid, r in results.items():
            status = "✅" if r["ok"] else "❌"
            print(f"  {status} {sid}: {r}")
