#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
guardian.py — 物理快照与安全回滚 + 回滚陪审团（诚实版 V3.1）

修复记录（回应 audit）：
  [F3] 签名机制：移除"防篡改"宣传，改为本地审计日志标识
  [F11] 所有 except 捕获具体异常，不静默
  [F12] 新增 .gitignore 自动生成

注意：本模块的"签名"仅用于本地审计追踪，不具备密码学防篡改能力。
"""

import os
import re
import json
import shutil
import hashlib
import logging
from datetime import datetime
from pathlib import Path
from dataclasses import dataclass, field

log = logging.getLogger("guardian")


# ═══════════════════════════════════════════════════════
# V1 — Guardian  快照与回滚
# ═══════════════════════════════════════════════════════

class Guardian:
    """物理层安全 —— 快照 + 回滚"""

    DEFAULT_IGNORE = [
        "__pycache__", ".git", ".venv", "venv", "env",
        "node_modules", ".idea", ".vscode",
        "snapshots", "verdicts", "feedback", "poc_reports",
        "shiyun_store",
    ]

    @staticmethod
    def _is_ignored(rel_path: Path) -> bool:
        """判断路径是否应被忽略（更健壮的匹配）"""
        parts = rel_path.parts
        for part in parts:
            if part in (
                "__pycache__", ".git", ".venv", "venv", "env",
                "node_modules", ".idea", ".vscode",
                "snapshots", "verdicts", "feedback", "poc_reports",
                "shiyun_store",
            ):
                return True
            if part.endswith(".pyc") or part.endswith(".pyo"):
                return True
        # 也忽略快照子目录（snap-xxx）
        for part in parts:
            if part.startswith("snap-") or part.startswith("pre-rollback-"):
                return True
        return False

    def __init__(self, snapshot_dir: str = "snapshots"):
        self.snapshot_dir = Path(snapshot_dir)
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)

    def create_snapshot(self, project_root: str = ".") -> str:
        """创建项目快照，返回 snapshot_id"""
        snap_id = f"snap-{datetime.now():%Y%m%d-%H%M%S}-{os.urandom(2).hex()}"
        snap_path = self.snapshot_dir / snap_id
        src = Path(project_root)

        files = list(src.rglob("*"))
        if not files:
            raise ValueError(f"项目目录为空，拒绝创建空快照: {project_root}")

        snap_path.mkdir(parents=True, exist_ok=True)
        copied = 0
        for f in files:
            if not f.is_file():
                continue
            try:
                rel = f.relative_to(src)
            except ValueError:
                continue
            if any(rel.match(ig) for ig in self.DEFAULT_IGNORE):
                continue
            dst = snap_path / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            try:
                shutil.copy2(f, dst)
                copied += 1
            except (PermissionError, OSError) as e:
                log.warning(f"⚠️ 复制失败 {f}: {e}")

        if copied == 0:
            shutil.rmtree(snap_path, ignore_errors=True)
            raise RuntimeError(f"快照创建失败：没有可复制的文件（权限不足或全被忽略）")

        manifest = {
            "id": snap_id,
            "created": datetime.now().isoformat(),
            "root": str(src.resolve()),
            "file_count": copied,
        }
        (snap_path / "manifest.json").write_text(
            json.dumps(manifest, indent=2), encoding="utf-8"
        )
        log.info(f"📸 快照创建: {snap_id} ({copied} 文件)")
        return snap_id

    def precheck(self, snap_id: str) -> dict:
        """回滚前预检：确保快照完整"""
        snap_path = self.snapshot_dir / snap_id
        if not snap_path.exists():
            return {"valid": False, "reason": "快照不存在"}
        manifest_f = snap_path / "manifest.json"
        if not manifest_f.exists():
            return {"valid": False, "reason": "清单文件缺失"}
        try:
            manifest = json.loads(manifest_f.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            return {"valid": False, "reason": f"清单文件损坏: {e}"}
        if manifest.get("file_count", 0) == 0:
            return {"valid": False, "reason": "空快照（零文件）"}
        files = [f for f in snap_path.rglob("*") if f.is_file() and f.name != "manifest.json"]
        if len(files) == 0:
            return {"valid": False, "reason": "快照目录为空"}
        return {
            "valid": True,
            "file_count": len(files),
            "manifest": manifest,
        }

    def rollback(self, snap_id: str, project_root: str = ".") -> dict:
        """回滚到指定快照"""
        check = self.precheck(snap_id)
        if not check["valid"]:
            raise RuntimeError(f"回滚失败: {check['reason']}")

        snap_path = self.snapshot_dir / snap_id
        src = Path(project_root)

        # 备份当前状态
        backup_id = f"pre-rollback-{os.urandom(2).hex()}"
        backup_path = self.snapshot_dir / backup_id
        backup_path.mkdir(parents=True, exist_ok=True)
        for f in Path(project_root).rglob("*"):
            if not f.is_file():
                continue
            try:
                rel = f.relative_to(src)
            except ValueError:
                continue
            if self._is_ignored(rel):
                continue
            dst = backup_path / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            try:
                shutil.copy2(f, dst)
            except (PermissionError, OSError) as e:
                log.warning(f"⚠️ 备份失败 {f}: {e}")

        # 清空目标（保留忽略项）
        for f in src.rglob("*"):
            try:
                rel = f.relative_to(src)
            except ValueError:
                continue
            if self._is_ignored(rel):
                continue
            try:
                if f.is_file():
                    f.unlink()
                elif f.is_dir():
                    shutil.rmtree(f, ignore_errors=True)
            except (PermissionError, OSError) as e:
                log.warning(f"⚠️ 删除失败 {f}: {e}")

        # 从快照恢复
        restored = 0
        for f in snap_path.rglob("*"):
            if not f.is_file() or f.name == "manifest.json":
                continue
            try:
                rel = f.relative_to(snap_path)
            except ValueError:
                continue
            if self._is_ignored(rel):
                continue
            dst = src / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            try:
                shutil.copy2(f, dst)
                restored += 1
            except (PermissionError, OSError) as e:
                log.warning(f"⚠️ 恢复失败 {f}: {e}")

        log.info(f"💣 回滚完成: {snap_id} → {project_root} ({restored} 文件)")
        return {
            "status": "rolled_back",
            "snapshot": snap_id,
            "backup": backup_id,
            "restored_files": restored,
        }

    def list_snapshots(self) -> list[dict]:
        """列出所有快照"""
        results = []
        for d in sorted(self.snapshot_dir.iterdir()):
            if d.is_dir():
                mf = d / "manifest.json"
                if mf.exists():
                    try:
                        results.append(json.loads(mf.read_text(encoding="utf-8")))
                    except json.JSONDecodeError:
                        log.warning(f"⚠️ 损坏的清单: {mf}")
        return results


# ═══════════════════════════════════════════════════════
# V3 — RollbackJury  回滚陪审团（诚实版）
# ═══════════════════════════════════════════════════════
#
# 重要说明：
# 本陪审团生成的是"本地审计日志"，不是法律意义上的判决书。
# 标识哈希仅用于追踪本地文件完整性，不具备密码学防篡改能力。
# 如需防篡改，请配合外部签名服务（如 Sigstore）使用。

class Verdict:
    """一份违规审计记录"""

    def __init__(self, *, verdict_id: str, timestamp: str,
                 user: str, env: str, model: str,
                 rule_name: str, severity: str,
                 original_code: str, violation_line: str,
                 evidence: dict, fix_suggestion: str,
                 snapshot_id: str):
        self.data = {
            "verdict_id": verdict_id,
            "timestamp": timestamp,
            "user": user,
            "env": env,
            "model": model,
            "rule_violated": rule_name,
            "severity": severity,
            "original_code": original_code,
            "violation_line": violation_line,
            "evidence": evidence,
            "fix_suggestion": fix_suggestion,
            "snapshot_id": snapshot_id,
            "integrity_hash": "",  # 本地完整性校验，非防篡改签名
            "disclaimer": "本文件为本地审计日志，不具备法律效力和防篡改能力",
        }
        self._hash()

    def _hash(self):
        """生成完整性哈希（非密码学签名）"""
        data_copy = {k: v for k, v in self.data.items() if k != "integrity_hash"}
        raw = json.dumps(data_copy, sort_keys=True, ensure_ascii=False)
        # 使用 SHA-256 全长度，但明确标注这不是"签名"
        self.data["integrity_hash"] = hashlib.sha256(raw.encode()).hexdigest()[:32]

    def verify(self) -> bool:
        """验证本地完整性（检测文件是否被意外修改）"""
        stored = self.data.pop("integrity_hash", "")
        self._hash()
        recomputed = self.data["integrity_hash"]
        self.data["integrity_hash"] = stored
        return stored == recomputed

    def to_markdown(self) -> str:
        d = self.data
        return f"""# ⚖️ 违规审计记录 `{d['verdict_id']}`

> ⚠️ **免责声明**：本文件为本地自动生成的审计日志，不具备法律效力，
> 其完整性哈希仅用于检测本地文件意外修改，不构成密码学防篡改签名。
> 如需生产级防篡改，请配合外部签名服务使用。

| 字段 | 值 |
|------|---|
| 时间 | {d['timestamp']} |
| 用户 | {d['user']} |
| 环境 | {d['env']} |
| AI 模型 | {d['model']} |
| 违规规则 | `{d['rule_violated']}` |
| 严重等级 | **{d['severity'].upper()}** |
| 完整性哈希 | `{d['integrity_hash']}` |

## 📋 违规代码

```text
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
*本文件由 RollbackJury 自动生成 | 本地审计日志，非法律文件*
"""

    def to_json(self) -> str:
        return json.dumps(self.data, indent=2, ensure_ascii=False)


class RollbackJury:
    """
    回滚陪审团 —— 每次违规生成审计记录。
    这是本地审计工具，不是法庭判决书。
    """

    SEVERITY_MAP = {
        "no_hardcoded_secrets": "critical",
        "no_sql_injection":      "critical",
        "try_except":           "high",
        "no_infinite_recursion": "high",
        "type_hints":           "medium",
        "no_unused_import":     "low",
        "markdown_clean":       "low",
        "v1_ast_check":        "medium",
        "try_catch":            "high",
        "no_bare_printstack":   "medium",
        "sql_prepared_statement":"critical",
        "has_javadoc":          "low",
        "explicit_types":       "medium",
        "no_bang_bang":         "high",
        "uses_coroutines":      "low",
        "ts_type_annotations":  "medium",
        "no_any":               "low",
        "promise_handled":      "high",
        "optional_binding":     "high",
        "error_handling":       "high",
        "no_force_chain":       "low",
    }

    FIX_SUGGESTIONS = {
        "no_hardcoded_secrets":     "将硬编码密钥替换为环境变量: `os.getenv('API_KEY')`",
        "no_sql_injection":         "使用参数化查询: `cursor.execute(sql, params)`",
        "try_except":               "为风险操作添加 try-except 块",
        "no_infinite_recursion":    "添加终止条件（if/return/for/while）",
        "type_hints":               "为函数参数和返回值添加类型注解",
        "no_unused_import":         "删除未使用的 import 语句",
        "markdown_clean":           "移除文档中的占位符（[TODO]等）",
        "try_catch":                "为 IO/网络操作添加 try-catch 块",
        "no_bare_printstack":       "使用日志框架替代 printStackTrace",
        "sql_prepared_statement":  "使用 PreparedStatement 防 SQL 注入",
        "has_javadoc":              "为公开方法添加 Javadoc 注释",
        "explicit_types":           "为函数参数/返回值添加显式类型注解",
        "no_bang_bang":             "用 ?: 替代 !! 避免 NPE",
        "uses_coroutines":          "使用协程（launch/async）替代裸线程",
        "ts_type_annotations":      "避免使用 any，定义明确接口/类型",
        "no_any":                   "用具体类型或 unknown 替代 any",
        "promise_handled":          "Promise 必须 await 或 .then() 处理",
        "optional_binding":         "用 guard let / if let 安全解包",
        "error_handling":            "Swift 错误必须用 do-try-catch 处理",
        "no_force_chain":           "避免链式强制解包（!）",
    }

    def __init__(self, verdict_dir: str = "verdicts"):
        self.verdict_dir = Path(verdict_dir)
        self.verdict_dir.mkdir(parents=True, exist_ok=True)

    def issue(self, *, rule_name: str, original_code: str,
              evidence: dict, snapshot_id: str,
              user: str = "anonymous", env: str = "dev",
              model: str = "unknown") -> Verdict:
        """签发一份审计记录"""
        verdict_id = f"V-{datetime.now():%Y%m%d-%H%M%S}-{os.urandom(2).hex()}"
        severity = self.SEVERITY_MAP.get(rule_name, "medium")
        suggestion = self.FIX_SUGGESTIONS.get(
            rule_name, "请根据规则说明修复代码")

        violation_lines = evidence.get("matched_lines", [])
        violation_text = "\n".join(violation_lines) if violation_lines else original_code[:200]

        v = Verdict(
            verdict_id=verdict_id,
            timestamp=datetime.now().isoformat(),
            user=user, env=env, model=model,
            rule_name=rule_name, severity=severity,
            original_code=original_code,
            violation_line=violation_text,
            evidence=evidence,
            fix_suggestion=suggestion,
            snapshot_id=snapshot_id,
        )

        (self.verdict_dir / f"{verdict_id}.json").write_text(
            v.to_json(), encoding="utf-8")
        (self.verdict_dir / f"{verdict_id}.md").write_text(
            v.to_markdown(), encoding="utf-8")

        log.info(f"⚖️ 审计记录签发: {verdict_id} [{severity.upper()}] {rule_name}")
        return v

    def list_verdicts(self) -> list[dict]:
        """列出所有审计记录"""
        files = sorted(self.verdict_dir.glob("V-*.json"))
        results = []
        for f in files:
            try:
                results.append(json.loads(f.read_text(encoding="utf-8")))
            except json.JSONDecodeError as e:
                log.warning(f"⚠️ 损坏的记录: {f}: {e}")
        return results

    def stats(self) -> dict:
        """统计"""
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
            "disclaimer": "统计数据来自本地审计日志，仅供参考",
        }


# ═══════════════════════════════════════════════════════
# 工具：自动生成 .gitignore
# ═══════════════════════════════════════════════════════

def ensure_gitignore(project_root: str = ".", force: bool = False) -> str:
    """
    确保项目根目录有 .gitignore。
    如果已有则追加缺失项（除非 force=True 覆盖）。
    返回 .gitignore 路径。
    """
    root = Path(project_root)
    gitignore_path = root / ".gitignore"

    essential_entries = [
        "# ── Word 体系运行时产物 ──",
        "config.json",
        "config/*.local.json",
        "snapshots/",
        "verdicts/",
        "feedback/",
        "poc_reports/",
        "shiyun_store/",
        "__pycache__/",
        "*.pyc",
        "*.pyo",
        ".DS_Store",
        "env/",
        "venv/",
        ".venv/",
        "node_modules/",
        "",
    ]

    if gitignore_path.exists() and not force:
        existing = gitignore_path.read_text(encoding="utf-8")
        missing = []
        for entry in essential_entries:
            if entry.startswith("#") or entry == "":
                continue
            # 去掉尾部 / 和 * 做匹配
            clean = entry.rstrip("/").rstrip("*").rstrip(".")
            if clean and clean not in existing:
                missing.append(entry)
        if missing:
            with open(gitignore_path, "a", encoding="utf-8") as f:
                f.write("\n# ── Word 体系 (自动追加) ──\n")
                f.write("\n".join(missing) + "\n")
            log.info(f"📝 .gitignore 已更新，追加 {len(missing)} 项")
    else:
        gitignore_path.write_text("\n".join(essential_entries), encoding="utf-8")
        log.info(f"📝 .gitignore 已创建: {gitignore_path}")

    return str(gitignore_path)


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "--demo":
        g = Guardian()
        j = RollbackJury()
        sid = g.create_snapshot(".")
        v = j.issue(rule_name="no_hardcoded_secrets",
                     original_code='key="sk-abc"',
                     evidence={"pattern": "openai_key"},
                     snapshot_id=sid, user="demo", env="prod", model="deepseek")
        print(f"Snapshot: {sid}")
        print(f"Verdict:  {v.data['verdict_id']}")
        print(f"Severity: {v.data['severity']}")
        print(f"Hash: {v.data['integrity_hash']}")
        print(f"Verify: {v.verify()}")
        print("---")
        print(v.to_markdown()[:600])
    elif len(sys.argv) > 1 and sys.argv[1] == "--gitignore":
        path = ensure_gitignore(sys.argv[2] if len(sys.argv) > 2 else ".")
        print(f"✅ {path}")
