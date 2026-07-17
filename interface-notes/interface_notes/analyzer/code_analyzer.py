"""
代码分析器 — 静态分析源码，自动识别接口级别的函数/模块

支持语言：
- Python (.py)
- JavaScript/TypeScript (.js, .ts, .jsx, .tsx)
- Java (.java)
- Go (.go)
- Rust (.rs)

识别策略：
1. AST 解析提取函数签名
2. 启发式规则判断是否为"接口"
3. 调用关系分析
"""

import ast
import os
import re
from pathlib import Path
from typing import Optional

from ..core.types import Interface, RiskLevel
from ..core.session import Session


# ──────────────────────────────────────────────
# 工具函数
# ──────────────────────────────────────────────

def _get_python_type_annotation(node) -> str:
    """从 AST 节点提取类型注解字符串"""
    if node is None:
        return ""
    if isinstance(node, ast.Name):
        return node.id
    elif isinstance(node, ast.Subscript):
        try:
            result = ast.unparse(node)
            # ast.unparse 可能给简单类型加引号，如 'str' -> '"str"'
            if result.startswith('"') and result.endswith('"'):
                return result[1:-1]
            return result
        except:
            return ""
    elif isinstance(node, ast.Constant):
        val = node.value
        if isinstance(val, str):
            return val
        return repr(val)
    elif isinstance(node, ast.Attribute):
        try:
            return ast.unparse(node)
        except:
            return ""
    else:
        try:
            result = ast.unparse(node)
            if result.startswith('"') and result.endswith('"'):
                return result[1:-1]
            return result
        except:
            return ""


def _is_private(name: str) -> bool:
    """判断是否为私有/内部函数"""
    return name.startswith("_") and not name.startswith("__")


def _is_magic(name: str) -> bool:
    """判断是否为魔术方法"""
    return name.startswith("__") and name.endswith("__")


# ──────────────────────────────────────────────
# Python 分析器
# ──────────────────────────────────────────────

class PythonAnalyzer:
    """Python 代码分析器，基于 AST"""

    IO_IMPORT_PATTERNS = [
        "requests", "urllib", "http", "socket",
        "sqlite", "mysql", "psycopg", "redis",
        "open(", "os.", "subprocess",
        "smtplib", "email", "boto3",
    ]

    def __init__(self, source_code: str, file_path: str):
        self.source = source_code
        self.file_path = file_path
        self.tree = ast.parse(source_code)

    def extract_interfaces(self) -> list[Interface]:
        """提取所有接口级别的函数"""
        interfaces = []

        # 推导模块路径（供 module_path 使用）
        fp = self.file_path.replace("\\", "/")
        stem = fp.rsplit(".", 1)[0] if "." in fp else fp
        mod_path = ".".join(stem.split("/"))

        # 第一遍：收集所有类定义
        class_methods = set()
        for node in ast.walk(self.tree):
            if isinstance(node, ast.ClassDef):
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        method_name = item.name
                        if _is_private(method_name) or _is_magic(method_name):
                            continue
                        iface = self._build_interface(
                            item, class_name=node.name, module_path=mod_path
                        )
                        interfaces.append(iface)
                        class_methods.add(iface.name)

        # 第二遍：模块级函数（排除已在类中处理过的）
        for node in ast.walk(self.tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                name = node.name
                if any(name in [m.name for m in cls.body if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef))]
                       for cls in [n for n in ast.walk(self.tree) if isinstance(n, ast.ClassDef)]):
                    continue
                if _is_private(name) or _is_magic(name):
                    continue
                if self._is_internal_helper(node):
                    continue
                iface = self._build_interface(node, module_path=mod_path)
                interfaces.append(iface)

        return interfaces

    def _is_internal_helper(self, node) -> bool:
        """判断是否为内部辅助函数（仅用于模块级函数）"""
        args = node.args
        total_args = len(args.args) + len(args.kwonlyargs)
        has_vararg = bool(args.vararg)

        # 无参数也无 vararg → 可能是辅助（但如果有 docstring 则保留）
        if total_args == 0 and not has_vararg:
            # 有 docstring 的函数视为有意图的公开接口
            docstring = ast.get_docstring(node)
            if docstring:
                return False
            # 函数体很短（< 2条语句）→ 辅助
            if len(node.body) < 2:
                return True
            return True  # 无参无docstring，仍视为辅助

        return False

    def _build_interface(self, node, class_name: str = "", module_path: str = "") -> Interface:
        """从 AST 函数节点构建 Interface 对象"""
        name = f"{class_name}.{node.name}" if class_name else node.name

        # 提取参数
        params = {}
        for arg in node.args.args:
            type_hint = _get_python_type_annotation(arg.annotation)
            params[arg.arg] = type_hint

        # 提取返回值类型
        returns = _get_python_type_annotation(node.returns)

        # 提取文档字符串
        docstring = ast.get_docstring(node) or ""
        description = docstring.split("\n")[0] if docstring else f"函数 {name}"

        # 检测 IO 操作
        source_lines = ast.unparse(node) if hasattr(ast, "unparse") else ""
        has_io = any(p in source_lines for p in self.IO_IMPORT_PATTERNS)

        # 检测调用关系
        calls = self._extract_calls(node)

        # 风险初步评估
        risk = RiskLevel.LOW
        suspicious = ""
        if has_io and "timeout" not in source_lines.lower():
            risk = RiskLevel.MEDIUM
            suspicious = "涉及IO操作但未设置超时"

        # 构建 module_path（如 utils.email / db.query）
        mod_path = module_path
        if not mod_path:
            fp = self.file_path.replace("\\", "/")
            stem = fp.rsplit(".", 1)[0] if "." in fp else fp
            mod_path = ".".join(stem.split("/"))

        # 提取本文件的 import 列表（用于跨文件消歧）
        imports = self.extract_imports()

        return Interface(
            name=name,
            description=description,
            params=params,
            returns=returns,
            location=self.file_path,
            module_path=mod_path,
            imports=imports,
            dependencies=calls,
            last_used="",
            risk_level=risk,
            suspicious=suspicious,
        )

    def _extract_calls(self, node) -> list[str]:
        """提取函数内部调用的其他函数"""
        calls = []
        for subnode in ast.walk(node):
            if isinstance(subnode, ast.Call):
                if isinstance(subnode.func, ast.Name):
                    calls.append(subnode.func.id)
                elif isinstance(subnode.func, ast.Attribute):
                    # obj.method() → 记录 method
                    calls.append(subnode.func.attr)
        return calls

    def extract_imports(self) -> list[str]:
        """提取所有 import"""
        imports = []
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append(alias.name)
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                for alias in node.names:
                    imports.append(f"{module}.{alias.name}" if module else alias.name)
        return imports


# ──────────────────────────────────────────────
# JavaScript/TypeScript 分析器
# ──────────────────────────────────────────────

class JSAnalyzer:
    """JS/TS 代码分析器（基于正则，无需 Node.js 依赖）"""

    FUNC_PATTERNS = [
        # function name(params) { ... }
        r"function\s+([a-zA-Z_$][\w$]*)\s*\(([^)]*)\)",
        # const name = (params) => { ... }
        r"(?:const|let|var)\s+([a-zA-Z_$][\w$]*)\s*=\s*(?:\([^)]*\)|[\w$]+)\s*=>",
        # name(params) { ... } inside objects
        r"^\s*([a-zA-Z_$][\w$]*)\s*\([^)]*\)\s*[:{]",
        # export function name
        r"export\s+(?:default\s+)?function\s+([a-zA-Z_$][\w$]*)\s*\(([^)]*)\)",
        # async function name
        r"async\s+function\s+([a-zA-Z_$][\w$]*)\s*\(([^)]*)\)",
    ]

    IO_PATTERNS = [
        "fetch(", "axios", "http.", "https.", "request(",
        "fs.", "readFile", "writeFile", "database", "query(",
        "exec(", "spawn(", "smtp", "email",
    ]

    def __init__(self, source_code: str, file_path: str):
        self.source = source_code
        self.file_path = file_path
        self.lines = source_code.split("\n")

    def extract_interfaces(self) -> list[Interface]:
        interfaces = []
        seen_names = set()

        # 推导模块路径
        fp = self.file_path.replace("\\", "/")
        stem = fp.rsplit(".", 1)[0] if "." in fp else fp
        mod_path = ".".join(stem.split("/"))

        for pattern in self.FUNC_PATTERNS:
            for match in re.finditer(pattern, self.source, re.MULTILINE):
                name = match.group(1)
                if name in seen_names:
                    continue
                if _is_private(name) or _is_magic(name):
                    continue
                seen_names.add(name)

                # 提取参数
                params = {}
                if len(match.groups()) > 1 and match.group(2):
                    param_str = match.group(2)
                    for p in param_str.split(","):
                        p = p.strip()
                        if p:
                            type_match = re.match(r"(\w+)\s*:\s*([\w<>\[\]{}]+)", p)
                            if type_match:
                                params[type_match.group(1)] = type_match.group(2)
                            else:
                                params[p] = ""

                # 检测 IO
                has_io = any(p in self.source for p in self.IO_PATTERNS)

                # 找 JSDoc 注释
                description = self._find_jsdoc(match.start())

                risk = RiskLevel.LOW
                suspicious = ""
                if has_io and "timeout" not in self.source.lower():
                    risk = RiskLevel.MEDIUM
                    suspicious = "涉及IO操作但未设置超时"

                iface = Interface(
                    name=name,
                    description=description or f"函数 {name}",
                    params=params,
                    returns="",
                    location=self.file_path,
                    module_path=mod_path,
                    dependencies=[],
                    last_used="",
                    risk_level=risk,
                    suspicious=suspicious,
                )
                interfaces.append(iface)

        return interfaces

    def _find_jsdoc(self, pos: int) -> str:
        """在位置前查找 JSDoc 注释"""
        before = self.source[:pos]
        # 找最近的 /** ... */ 块
        match = re.findall(r"/\*\*([\s\S]*?)\*/", before)
        if match:
            doc = match[-1].strip()
            # 取第一行有效内容
            for line in doc.split("\n"):
                line = line.strip().lstrip("*").strip()
                if line and not line.startswith("@"):
                    return line
        return ""


# ──────────────────────────────────────────────
# Java 分析器
# ──────────────────────────────────────────────

class JavaAnalyzer:
    """Java 代码分析器"""

    # 匹配完整方法签名，捕获可见性、返回类型、方法名、参数
    # 注意：visibility 捕获组放在前面
    FUNC_PATTERN = (
        r"(public|private|protected)\s+"
        r"(?:static\s+)?(?:final\s+)?"
        r"([\w<>\[\].,\s]+?)\s+"  # 返回类型（非贪婪）
        r"([a-zA-Z_$][\w$]*)\s*"    # 方法名
        r"\(([^)]*)\)"               # 参数列表
        r"\s*(?:throws\s+[\w,\s]+)?\s*\{"
    )

    IO_PATTERNS = [
        "Connection", "Statement", "ResultSet", "PreparedStatement",
        "HttpClient", "HttpRequest", "HttpResponse",
        "FileReader", "FileWriter", "BufferedReader",
        "Socket", "ServerSocket", "DatagramSocket",
    ]

    def __init__(self, source_code: str, file_path: str):
        self.source = source_code
        self.file_path = file_path

    def extract_interfaces(self) -> list[Interface]:
        interfaces = []
        seen = set()

        # 推导模块路径
        fp = self.file_path.replace("\\", "/")
        stem = fp.rsplit(".", 1)[0] if "." in fp else fp
        mod_path = ".".join(stem.split("/"))

        for match in re.finditer(self.FUNC_PATTERN, self.source):
            visibility = match.group(1)
            return_type = match.group(2).strip()
            name = match.group(3)
            params_str = match.group(4)

            if visibility == "private":
                continue
            if name in seen or _is_private(name):
                continue
            if name in ("if", "for", "while", "switch", "catch", "synchronized", "return"):
                continue
            seen.add(name)

            params = {}
            if params_str.strip():
                for p in params_str.split(","):
                    p = p.strip()
                    parts = p.split()
                    if len(parts) >= 2:
                        params[parts[-1]] = parts[-2]
                    elif len(parts) == 1:
                        params[parts[0]] = ""

            has_io = any(p in self.source for p in self.IO_PATTERNS)

            description = self._find_javadoc(match.start())

            risk = RiskLevel.LOW
            suspicious = ""
            if has_io and "timeout" not in self.source.lower() and "setTimeout" not in self.source:
                risk = RiskLevel.MEDIUM
                suspicious = "涉及IO操作但未设置超时"

            iface = Interface(
                name=name,
                description=description or f"方法 {name}",
                params=params,
                returns="",
                location=self.file_path,
                module_path=mod_path,
                dependencies=[],
                last_used="",
                risk_level=risk,
                suspicious=suspicious,
            )
            interfaces.append(iface)

        return interfaces

    def _find_javadoc(self, pos: int) -> str:
        before = self.source[:pos]
        match = re.findall(r"/\*\*([\s\S]*?)\*/", before)
        if match:
            doc = match[-1].strip()
            for line in doc.split("\n"):
                line = line.strip().lstrip("*").strip()
                if line and not line.startswith("@"):
                    return line
        return ""


# ──────────────────────────────────────────────
# 通用文件分析器（调度器）
# ──────────────────────────────────────────────

# 文件扩展名 → 分析器映射
ANALYZER_MAP = {
    ".py": PythonAnalyzer,
    ".js": JSAnalyzer,
    ".jsx": JSAnalyzer,
    ".ts": JSAnalyzer,
    ".tsx": JSAnalyzer,
    ".java": JavaAnalyzer,
    ".go": None,   # 预留
    ".rs": None,   # 预留
}


def analyze_file(file_path: str, source_code: Optional[str] = None) -> list[Interface]:
    """
    分析单个文件，返回发现的接口列表。

    对应设计文档 Phase 1.1：AI 判断"这是个接口"
    """
    if source_code is None:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            source_code = f.read()

    ext = Path(file_path).suffix.lower()
    analyzer_cls = ANALYZER_MAP.get(ext)

    if analyzer_cls is None:
        return []

    analyzer = analyzer_cls(source_code, file_path)
    return analyzer.extract_interfaces()


def analyze_project(
    project_path: str,
    session: Session,
    ignore_dirs: list[str] = None,
    max_files: int = 500,
) -> Session:
    """
    全量扫描项目目录，提取所有接口。

    对应设计文档 模式B：全量扫描流程。
    """
    if ignore_dirs is None:
        ignore_dirs = [
            "node_modules", ".git", "__pycache__", ".venv", "venv",
            "dist", "build", ".next", ".nuxt", "target", "vendor",
            ".idea", ".vscode", "test", "tests", "__tests__",
        ]

    project_root = Path(project_path)
    supported_exts = list(ANALYZER_MAP.keys())

    files_scanned = 0
    truncated = False
    for root, dirs, files in os.walk(project_root):
        # 过滤忽略目录
        dirs[:] = [d for d in dirs if d not in ignore_dirs and not d.startswith(".")]

        for fname in files:
            if files_scanned >= max_files:
                truncated = True
                break
            ext = Path(fname).suffix.lower()
            if ext not in supported_exts:
                continue

            file_path = os.path.join(root, fname)
            try:
                rel_path = os.path.relpath(file_path, project_root)
                interfaces = analyze_file(file_path)
                files_scanned += 1

                for iface in interfaces:
                    iface.location = rel_path
                    session.add_interface(iface)

            except Exception as e:
                print(f"  ⚠️ 解析失败 {file_path}: {e}")
                continue

        # 目录遍历完也要检查（防止遗漏子目录）
        if files_scanned >= max_files:
            truncated = True
            break

    session.stats["total_files_scanned"] = files_scanned
    session.stats["scan_truncated"] = truncated
    session.stats["max_files_limit"] = max_files

    if truncated:
        print(
            f"  ⚠️ 扫描文件数已达上限（{max_files}），扫描已提前终止！\n"
            f"     可能漏扫部分文件。建议增大 --max-files 参数后重新扫描。"
        )

    # 解析调用关系（跨文件）
    _resolve_cross_file_calls(session, project_root)

    return session


def _resolve_cross_file_calls(session: Session, project_root: Path):
    """
    解析跨文件调用关系（歧义安全版 v2）。

    消歧优先级：
    1. 短名唯一 → 直接绑定。
    2. 短名多义 → 检查 caller 的 imports 列表：
       - 若 caller 有 `from X import dep`，优先匹配 X.dep。
       - 若 caller 有 `import X` 且调用形如 `X.dep()`，匹配 X.dep。
    3. 仍无法消歧 → 打印 ⚠️ 警告，不绑定。
    """
    from collections import defaultdict
    short_to_qns: dict[str, list[str]] = defaultdict(list)
    for qn, iface in session._interfaces.items():
        short_to_qns[iface.name].append(qn)

    for qn, iface in session._interfaces.items():
        resolved_qns: set[str] = set()

        for dep in iface.dependencies:
            candidates = short_to_qns.get(dep, [])

            if len(candidates) == 0:
                continue  # 标准库/外部依赖
            elif len(candidates) == 1:
                resolved_qns.add(candidates[0])
            else:
                # ── 同名歧义：用 imports 做精确消歧 ──
                best = _disambiguate(dep, candidates, iface, session)
                if best is None:
                    cands_str = ", ".join(candidates)
                    print(
                        f"  ⚠️ 调用关系歧义：'{iface.name}' 调用 '{dep}' "
                        f"匹配到 {len(candidates)} 个同名接口：[{cands_str}]。"
                        f"已跳过，建议手动确认。"
                    )
                    continue
                resolved_qns.add(best)

        iface.dependencies = sorted(resolved_qns)
        for callee_qn in resolved_qns:
            cb = session._interfaces[callee_qn].called_by
            if qn not in cb:
                cb.append(qn)


def _disambiguate(
    dep_name: str,
    candidates: list[str],
    caller_iface,
    session: Session,
) -> Optional[str]:
    """
    根据 caller 的 imports 列表，从同名候选中选出最匹配的 qualified_name。
    返回 None 表示无法消歧。
    """
    caller_imports = set(caller_iface.imports or [])

    # 辅助：把 tmp 前缀等"项目根路径"部分剥离，只留模块路径
    def _strip_root(qn: str) -> str:
        import re
        s = qn.lstrip(".")
        parts = s.split(".")
        # 形态: "tmp.<hash>.<real_module>..."
        # hash 形如 "dbg4_ef_kccoo" / "ifnotes_alias_xxx" — 含字母、数字、下划线
        if len(parts) >= 3 and parts[0] == "tmp" and re.match(r"^\w*_", parts[1]):
            return ".".join(parts[2:])
        # 形态: "tmp.<real_module>..."
        if len(parts) >= 2 and parts[0] == "tmp":
            return ".".join(parts[1:])
        return s

    # ① 直接命中（先试原始，再试去前缀）
    for cq in candidates:
        if cq in caller_imports:
            return cq
    # 构造 "去根前缀" 的候选集合
    stripped = {cq: _strip_root(cq) for cq in candidates}
    for cq, s in stripped.items():
        if s in caller_imports:
            return cq

    # ② 模块路径前缀匹配
    for cq, s in stripped.items():
        mod = s.rsplit(".", 1)[0] if "." in s else s
        if mod and (mod in caller_imports or any(mod == c.rsplit(".", 1)[0] for c in caller_imports)):
            return cq

    # ③ 同模块优先
    caller_mod = caller_iface.module_path
    caller_mod_stripped = _strip_root(caller_mod)
    for cq in candidates:
        c_mod = session._interfaces[cq].module_path
        if c_mod == caller_mod or _strip_root(c_mod) == caller_mod_stripped:
            return cq

    return None
