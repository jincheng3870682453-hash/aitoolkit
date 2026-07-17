# -*- coding: utf-8 -*-
"""
V4.1 修复版 - 物理层防御模块
修复: G1 - hard_rollback() 增加快照完整性预检，防止快照损坏/为空时清空原目录导致数据永久丢失
"""
import os
import re
import json
import shutil
import tempfile
import subprocess
import logging
import fnmatch
from typing import Dict, List, Optional, Callable, Any, Tuple
from pathlib import Path

# ============================================================
# 0. 日志配置（敏感信息脱敏写入文件）
# ============================================================
logging.basicConfig(
    filename='guardian.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

def log_sensitive(msg: str, level=logging.INFO):
    """记录详细日志（含路径），控制台不输出敏感信息"""
    logging.log(level, msg)

# ============================================================
# 1. 配置区（用户修改）
# ============================================================
PROJECT_ROOT = "./my_project"
USE_HARDLINK = False
IGNORE_PATTERNS = [".git", "__pycache__", "*.pyc", "*.pyo", "*.log", "*.tmp"]
MAX_SNAPSHOTS = 3
DELETE_SNAPSHOT_ON_SUCCESS = True

# ---------- 你的 AI 调用函数（独立模式用） ----------
def call_ai_to_fix(error_log: str) -> str:
    """模拟 AI 返回，实际替换为真实 API"""
    return json.dumps({
        "files": {
            "src/main.py": "def main():\n    print('fixed')\n"
        }
    })

# ---------- 本地规则修复（降级用） ----------
def local_rule_based_fix(error_log: str) -> Dict[str, str]:
    """本地正则修复，返回 {"files": {...}} 或 {}"""
    def rule_undefined_var(match, log):
        var = match.group(1)
        return {"src/main.py": f"{var} = None  # auto-fixed\n"}

    rules = [
        (re.compile(r"NameError: name '(\w+)' is not defined"), rule_undefined_var),
        (re.compile(r"ImportError: No module named '(\w+)'"), 
         lambda m, l: {"src/main.py": f"import {m.group(1)}  # auto-fixed\n"}),
    ]
    for pattern, handler in rules:
        m = pattern.search(error_log)
        if m:
            result = handler(m, error_log)
            if result:
                return {"files": result}
    return {}

# ============================================================
# 2. 核心修复函数：force_extract_payload（补全！）
# ============================================================
def force_extract_payload(raw_response: str) -> Dict[str, Any]:
    """
    暴力提取AI返回的 files 字典。
    兼容：```json ... ```、裸JSON、带注释JSON。
    若解析失败，返回空字典（触发后续降级）。
    """
    if not raw_response:
        return {"files": {}}

    # 策略1：提取 ```json ... ``` 代码块
    match = re.search(r'```json\s*(\{.*?\})\s*```', raw_response, re.DOTALL)
    if not match:
        # 策略2：提取第一个 { 到最后一个 }（裸JSON）
        match = re.search(r'(\{.*\})', raw_response, re.DOTALL)

    if not match:
        log_sensitive("force_extract_payload: 未找到任何 JSON 结构", logging.WARNING)
        return {"files": {}}

    json_str = match.group(1)
    # 清理可能的注释（// 或 #）
    json_str = re.sub(r'//.*?$', '', json_str, flags=re.MULTILINE)
    json_str = re.sub(r'#.*?$', '', json_str, flags=re.MULTILINE)

    try:
        data = json.loads(json_str)
        if "files" in data:
            return data
        # 如果有 project_map 但没有 files，返回空 files 触发 apply_fix 的占位逻辑
        if "project_map" in data:
            return {"files": {}, "project_map": data["project_map"]}
        return {"files": {}}
    except json.JSONDecodeError as e:
        log_sensitive(f"force_extract_payload JSON解析失败: {e}", logging.ERROR)
        return {"files": {}}

# ============================================================
# 3. 字节流乱码探针
# ============================================================
def encoding_scanner(text: str) -> bool:
    """检测乱码（U+FFFD 或 锟斤拷），返回 True 表示可疑"""
    if not text:
        return False
    if '\ufffd' in text or '锟斤拷' in text:
        return True
    if b'\xef\xbf\xbd' in text.encode('utf-8', errors='ignore'):
        return True
    return False

# ============================================================
# 4. 项目验证（多级）
# ============================================================
def validate_project(project_root: str, checks: List[str] = None) -> Tuple[bool, str]:
    if checks is None:
        checks = ['py_compile']
    errors = []
    for check in checks:
        if check == 'py_compile':
            ok, msg = _run_command(["python", "-m", "py_compile", project_root])
        elif check == 'pytest':
            ok, msg = _run_command(["pytest", project_root])
        else:
            ok, msg = False, f"未知检查项: {check}"
        if not ok:
            errors.append(f"{check} 失败: {msg}")
    return (not errors), "\n".join(errors) if errors else "所有检查通过"

def _run_command(cmd: List[str]) -> Tuple[bool, str]:
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        return (res.returncode == 0), res.stderr or res.stdout
    except Exception as e:
        return False, str(e)

# ============================================================
# 5. 应用修复到项目
# ============================================================
def apply_fix_to_project(project_root: str, payload: Dict[str, Any]) -> None:
    root_path = Path(project_root).resolve()
    files = payload.get("files")
    if files is None:
        # 降级：从 project_map 创建空占位文件
        for rel_path in payload.get("project_map", {}).keys():
            full = os.path.join(project_root, rel_path)
            os.makedirs(os.path.dirname(full), exist_ok=True)
            if not os.path.exists(full):
                with open(full, "w", encoding="utf-8") as f:
                    f.write("# placeholder\n")
        return
    for rel_path, content in files.items():
        full = os.path.join(project_root, rel_path)
        # 使用 Path.relative_to() 严格校验，防止 ../ 目录遍历
        target = Path(full).resolve()
        try:
            target.relative_to(root_path)
        except ValueError:
            raise ValueError(f"非法路径: {rel_path} 不在项目根目录下")
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w", encoding="utf-8") as f:
            f.write(content)
# ============================================================
# 6. 物理快照与回滚（核心类）
# ============================================================
class PhysicalCheckpoint:
    _snapshots = []

    def __init__(self, project_root: str, use_hardlink: bool = False,
                 ignore_patterns: List[str] = None, max_snapshots: int = 3):
        self.root = os.path.abspath(project_root)
        self.use_hardlink = use_hardlink
        self.ignore_patterns = ignore_patterns or []
        self.max_snapshots = max_snapshots
        self.snapshot_dir = tempfile.mkdtemp(prefix="ROLLBACK_SNAP_")
        PhysicalCheckpoint._snapshots.append(self.snapshot_dir)
        # 自动清理旧快照
        while len(PhysicalCheckpoint._snapshots) > self.max_snapshots:
            old = PhysicalCheckpoint._snapshots.pop(0)
            if os.path.exists(old):
                shutil.rmtree(old)

    def _should_ignore(self, rel_path: str) -> bool:
        for pat in self.ignore_patterns:
            if fnmatch.fnmatch(rel_path, pat):
                return True
            if pat.endswith('/') and fnmatch.fnmatch(rel_path + '/', pat):
                return True
        return False

    def take_snapshot(self) -> str:
        if os.path.exists(self.snapshot_dir):
            shutil.rmtree(self.snapshot_dir)
        os.makedirs(self.snapshot_dir)
        copy_func = os.link if self.use_hardlink else shutil.copy2
        for dirpath, _, filenames in os.walk(self.root):
            rel_dir = os.path.relpath(dirpath, self.root)
            if rel_dir == '.' or self._should_ignore(rel_dir):
                continue
            for fname in filenames:
                src = os.path.join(dirpath, fname)
                rel = os.path.relpath(src, self.root)
                if self._should_ignore(rel):
                    continue
                dst = os.path.join(self.snapshot_dir, rel)
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                try:
                    copy_func(src, dst)
                except (OSError, shutil.SameFileError):
                    shutil.copy2(src, dst)
        return self.snapshot_dir

    def hard_rollback(self):
        # ★★★ G1 修复：快照完整性预检 ★★★
        if not os.path.exists(self.snapshot_dir):
            raise RuntimeError(f"快照目录不存在: {self.snapshot_dir}，无法回滚")

        snap_files = []
        for dirpath, _, filenames in os.walk(self.snapshot_dir):
            for fname in filenames:
                src = os.path.join(dirpath, fname)
                if os.path.getsize(src) == 0:
                    raise RuntimeError(f"快照文件为空: {src}，拒绝回滚防止数据丢失")
                snap_files.append(src)

        if not snap_files:
            raise RuntimeError("快照为空目录，拒绝回滚防止清空原目录")

        # 原逻辑：清空原目录
        for item in os.listdir(self.root):
            item_path = os.path.join(self.root, item)
            if os.path.isdir(item_path):
                shutil.rmtree(item_path)
            else:
                os.remove(item_path)
        # 复制快照回来
        copy_func = os.link if self.use_hardlink else shutil.copy2
        for dirpath, _, filenames in os.walk(self.snapshot_dir):
            for fname in filenames:
                src = os.path.join(dirpath, fname)
                rel = os.path.relpath(src, self.snapshot_dir)
                dst = os.path.join(self.root, rel)
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                try:
                    copy_func(src, dst)
                except (OSError, shutil.SameFileError):
                    shutil.copy2(src, dst)

    @classmethod
    def cleanup_all(cls):
        for snap in cls._snapshots:
            if os.path.exists(snap):
                shutil.rmtree(snap)
        cls._snapshots.clear()

# ============================================================
# 7. 主控制器（支持 V4.0 托管模式）
# ============================================================
class HumanInterventionRequired(Exception):
    pass

def execute_safe_fix(
    project_path: str,
    error_log: str = "",
    fixed_payload: Optional[Dict[str, Any]] = None,  # ★ V4.0 托管模式入口
    ai_func: Callable = call_ai_to_fix,
    local_func: Callable = local_rule_based_fix,
    apply_func: Callable = apply_fix_to_project,
    max_attempts: int = 3,
    chaos_limit: int = 5,
    delete_snapshot_on_success: bool = True
) -> str:
    """
    执行安全修复。
    - 若传入 fixed_payload：进入 V4.0 托管模式（仅做快照回滚 + 落盘，不调用AI，不重复验证）。
    - 否则：进入独立模式（含AI调用、本地降级、多级验证）。
    """
    cp = PhysicalCheckpoint(project_path, USE_HARDLINK, IGNORE_PATTERNS, MAX_SNAPSHOTS)
    cp.take_snapshot()
    log_sensitive(f"快照已创建: {cp.snapshot_dir}")

    # ========== V4.0 托管模式（轻量快速） ==========
    if fixed_payload is not None:
        try:
            # 落盘
            apply_func(project_path, fixed_payload)
            log_sensitive("V4.0 托管模式：修复内容已写入")
            # 仅做最基本的乱码检测（检查内容本身）
            for rel, content in fixed_payload.get("files", {}).items():
                if encoding_scanner(content):
                    raise RuntimeError(f"文件 {rel} 包含乱码，回滚")
            # 成功，清理快照
            if delete_snapshot_on_success:
                cp.cleanup_all()
            return "✅ V4.0 修复已安全落盘（Guardian物理层确认）"
        except Exception as e:
            log_sensitive(f"V4.0 托管模式失败，执行回滚: {e}", logging.ERROR)
            cp.hard_rollback()
            raise HumanInterventionRequired(f"物理层落盘失败，已回滚。详情见 guardian.log。错误: {e}")

    # ========== 独立模式（原完整逻辑，兼容旧版） ==========
    chaos_counter = 0
    last_error = ""
    for attempt in range(1, max_attempts + 1):
        log_sensitive(f"独立模式修复尝试 {attempt}/{max_attempts}")
        cp.hard_rollback()

        try:
            payload = None
            if attempt == 1:
                raw = ai_func(error_log)
                if encoding_scanner(raw):
                    chaos_counter += 1
                    if chaos_counter >= chaos_limit:
                        raise RuntimeError(f"连续 {chaos_limit} 次乱码，强制挂起")
                    continue
                chaos_counter = 0
                payload = force_extract_payload(raw)
            elif attempt == 2:
                payload = local_func(error_log)
                if not payload:
                    continue
            else:
                raise HumanInterventionRequired("独立模式修复尝试耗尽，请查看日志")

            apply_func(project_path, payload)
            ok, msg = validate_project(project_path)
            if ok:
                if delete_snapshot_on_success:
                    cp.cleanup_all()
                return f"✅ 独立模式修复成功，验证通过。日志: guardian.log"
            else:
                last_error = msg
                log_sensitive(f"验证失败: {msg}", logging.WARNING)

        except Exception as e:
            last_error = str(e)
            log_sensitive(f"尝试异常: {e}", logging.ERROR)

    raise HumanInterventionRequired(f"所有尝试失败，已回滚至快照。错误: {last_error}")

# ============================================================
# 8. 主入口（演示）
# ============================================================
if __name__ == "__main__":
    # 测试 V4.0 托管模式
    test_payload = {
        "files": {
            "src/main.py": "def main():\n    print('Hello V4.0')\n"
        }
    }
    try:
        result = execute_safe_fix(PROJECT_ROOT, fixed_payload=test_payload)
        print(result)
    except HumanInterventionRequired as e:
        print(f"需要人工介入: {e}")