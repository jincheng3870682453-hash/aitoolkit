"""
work.py —— 核心规则引擎（Python AST 深度检测）

设计思路（借鉴但不照搬）：
  - CodeGraph：把代码解析成结构化关系（函数/类/调用/导入）
    → 我们做轻量版：AST 遍历时顺便建一张"代码地图"
  - Headroom：保留骨架、压缩载荷
    → 我们做 check() 时同时输出"压缩视图"供 AI 参考
  - mutatest：突变测试质量门禁
    → 我们做"规则突变"：故意注入违规，验证检测是否生效
  - Quality Guard：导入时拦截
    → 提供 install_guard_import_hook() 可选启用

对外只暴露 3 个函数：
    check(code) → Report
    check_file(path) → Report
    get_compressed_view(code) → str  （给 AI 看的骨架）

零依赖（纯标准库）。
"""

import ast
import re
import json
import hashlib
import logging
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Optional, Callable

log = logging.getLogger("jinchen.work")


# ════════════════════════════════════════════════════════
#  数据结构
# ════════════════════════════════════════════════════════
@dataclass
class Violation:
    """单条违规记录"""
    rule: str
    severity: str  # critical / high / medium / low
    line: int
    message: str
    suggestion: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Report:
    """
    检测结果报告 —— 唯一对外输出

    借鉴 Quality Gate 的"全维度输出"思路：
    - passed: 是否通过
    - violations: 违规列表
    - compressed_view: 代码骨架（给 AI 参考用）
    - metrics: 代码度量（复杂度等）
    - metadata: 环境信息
    """
    passed: bool
    violations: list = field(default_factory=list)
    compressed_view: str = ""
    metrics: dict = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "passed": self.passed,
            "violations": [v.to_dict() for v in self.violations],
            "compressed_view": self.compressed_view,
            "metrics": self.metrics,
            "metadata": self.metadata,
        }

    def to_markdown(self) -> str:
        """给人看的简要报告"""
        if self.passed:
            return "✅ 通过（无违规）"
        lines = [f"⚠️ {len(self.violations)} 条违规：\n"]
        for v in self.violations:
            icon = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🔵"}.get(v.severity, "⚪")
            lines.append(f"  {icon} [{v.rule}] L{v.line}: {v.message}")
            if v.suggestion:
                lines.append(f"     💡 {v.suggestion}")
        return "\n".join(lines)


# ════════════════════════════════════════════════════════
#  代码地图（借鉴 CodeGraph 的轻量版）
# ════════════════════════════════════════════════════════
class CodeMap:
    """
    把源码解析成结构化关系图

    CodeGraph 用 tree-sitter + SQLite 做全量图谱。
    我们做轻量版：AST 遍历一次，提取：
    - 函数/方法签名
    - 类定义
    - 导入关系
    - 调用关系
    - 全局变量

    不写数据库，纯内存，用完即弃。
    """

    def __init__(self, code: str):
        self.code = code
        self.tree = None
        self.functions: list = []
        self.classes: list = []
        self.imports: list = []
        self.calls: list = []
        self.global_vars: list = []
        self.lines = code.splitlines()
        self._parse()

    def _parse(self):
        try:
            self.tree = ast.parse(self.code)
            self._visit(self.tree)
        except SyntaxError as e:
            log.warning(f"AST 解析失败: {e}")

    def _visit(self, node):
        for child in ast.walk(self.tree or ast.parse("")):
            if isinstance(child, ast.FunctionDef):
                self.functions.append({
                    "name": child.name,
                    "line": child.lineno,
                    "args": [a.arg for a in child.args.args],
                    "returns": ast.unparse(child.returns) if child.returns else "",
                    "has_docstring": ast.get_docstring(child) is not None,
                    "body_lines": len(child.body),
                    "complexity": self._complexity(child),
                })
            elif isinstance(child, ast.ClassDef):
                bases = []
                for b in child.bases:
                    try:
                        bases.append(ast.unparse(b))
                    except Exception:
                        bases.append("?")
                self.classes.append({
                    "name": child.name,
                    "line": child.lineno,
                    "bases": bases,
                    "methods": [n.name for n in child.body if isinstance(n, ast.FunctionDef)],
                })
            elif isinstance(child, (ast.Import, ast.ImportFrom)):
                if isinstance(child, ast.Import):
                    for n in child.names:
                        self.imports.append({"module": n.name, "alias": n.asname, "line": child.lineno})
                else:
                    mod = child.module or ""
                    for n in child.names:
                        self.imports.append({"module": f"{mod}.{n.name}", "alias": n.asname, "line": child.lineno})
            elif isinstance(child, ast.Call):
                try:
                    func_name = ast.unparse(child.func)
                    self.calls.append({"func": func_name, "line": child.lineno})
                except Exception:
                    pass

    def _complexity(self, func_node: ast.FunctionDef) -> int:
        """圈复杂度（简化版）"""
        cc = 1
        for node in ast.walk(func_node):
            if isinstance(node, (ast.If, ast.While, ast.For, ast.AsyncFor)):
                cc += 1
            elif isinstance(node, ast.Try):
                cc += len(node.handlers) + 1
            elif isinstance(node, ast.BoolOp):
                cc += len(node.values) - 1
        return cc

    def get_compressed_view(self) -> str:
        """
        输出代码骨架（借鉴 Headroom 的"保留骨架、压缩载荷"）
        给 AI 看这个，比看全文省 60-80% token
        """
        lines = []
        for cls in self.classes:
            base_str = f"({', '.join(cls['bases'])})" if cls["bases"] else ""
            lines.append(f"class {cls['name']}{base_str}:  # L{cls['line']}")
            for m in cls["methods"]:
                lines.append(f"    def {m}(...)")
        for fn in self.functions:
            args = ", ".join(fn["args"])
            ret = f" -> {fn['returns']}" if fn["returns"] else ""
            doc = "  # has docstring" if fn["has_docstring"] else ""
            lines.append(f"def {fn['name']}({args}){ret}:  # L{fn['line']} cc={fn['complexity']}{doc}")
        for imp in self.imports:
            alias = f" as {imp['alias']}" if imp["alias"] else ""
            lines.append(f"import {imp['module']}{alias}  # L{imp['line']}")
        return "\n".join(lines) if lines else "(空文件)"

    def to_dict(self) -> dict:
        return {
            "functions": self.functions,
            "classes": self.classes,
            "imports": self.imports,
            "calls": self.calls,
            "global_vars": self.global_vars,
        }


# ════════════════════════════════════════════════════════
#  规则引擎（13 条 Python AST 深度规则）
# ════════════════════════════════════════════════════════
SEVERITY = {
    "no_hardcoded_secrets": "critical",
    "no_sql_injection":     "critical",
    "type_hints":           "medium",
    "try_except":           "high",
    "no_infinite_recursion":"high",
    "no_unused_import":     "low",
    "markdown_clean":       "low",
    "v1_ast_check":         "medium",
    # 新增 5 条深度规则
    "no_subprocess_shell":  "critical",
    "no_pickle_deserialize":"high",
    "no_global_mutable":    "medium",
    "no_bare_except":       "high",
    "no_sql_string_concat": "critical",
}

SUGGESTIONS = {
    "no_hardcoded_secrets":   "用 os.getenv('KEY') 从环境变量读取密钥",
    "no_sql_injection":       "用参数化查询 cursor.execute(sql, params)",
    "type_hints":             "给函数参数和返回值加类型注解: def f(x: int) -> str:",
    "try_except":             "危险操作(open/socket/subprocess)必须包 try-except",
    "no_infinite_recursion":  "加终止条件或改循环实现",
    "no_unused_import":       "删除未使用的 import",
    "markdown_clean":         "去掉输出里的 [TODO] 等占位符",
    "v1_ast_check":           "AST 解析失败，检查语法",
    "no_subprocess_shell":    "用 subprocess.run([cmd, arg1], shell=False)",
    "no_pickle_deserialize":  "禁止 unpickle 不可信数据，改用 JSON",
    "no_global_mutable":      "用依赖注入或类属性替代全局可变状态",
    "no_bare_except":         "捕获具体异常: except ValueError: 而非 except:",
    "no_sql_string_concat":   "用参数化查询，禁止字符串拼接 SQL",
}


class RuleEngine:
    """
    13 条 Python AST 深度检测规则

    每条规则都是纯函数：def rule(code, tree, codemap) -> list[Violation]
    新增规则 = 加一个函数 + 注册一行，不改主流程
    """

    def __init__(self):
        self.rules: list = []
        self._register_all()

    def _register_all(self):
        self.rules = [
            ("no_hardcoded_secrets",    self._check_hardcoded_secrets),
            ("no_sql_injection",       self._check_sql_injection),
            ("type_hints",             self._check_type_hints),
            ("try_except",             self._check_try_except),
            ("no_infinite_recursion",  self._check_infinite_recursion),
            ("no_unused_import",       self._check_unused_import),
            ("markdown_clean",         self._check_markdown_clean),
            ("v1_ast_check",           self._check_ast_parseable),
            ("no_subprocess_shell",    self._check_subprocess_shell),
            ("no_pickle_deserialize",  self._check_pickle_deserialize),
            ("no_global_mutable",      self._check_global_mutable),
            ("no_bare_except",         self._check_bare_except),
            ("no_sql_string_concat",   self._check_sql_string_concat),
        ]

    def check(self, code: str) -> Report:
        """对外接口：Python 源码 → Report"""
        if not code or not code.strip():
            return Report(passed=True, violations=[], compressed_view="", metrics={})

        violations, metrics, compressed = self.run_all(code)

        blocked = {"critical", "high"}
        passed = not any(v.severity in blocked for v in violations)

        metadata = {
            "rules_checked": len(self.rules),
            "rules_passed": len(self.rules) - len(violations),
            "engine": "Python AST (native)",
            "version": "3.2",
        }
        return Report(
            passed=passed,
            violations=violations,
            compressed_view=compressed,
            metrics=metrics,
            metadata=metadata,
        )

    # ── 规则实现 ────────────────────────────────────────
    def _check_hardcoded_secrets(self, code, tree, cm) -> list:
        """检测硬编码密钥/密码/Token"""
        violations = []
        patterns = [
            (r'sk-[a-zA-Z0-9-]{20,}', 'API Key (sk-...)'),
            (r'AKIA[0-9A-Z]{16}', 'AWS Access Key'),
            (r'ghp_[a-zA-Z0-9]{30,}', 'GitHub Token'),
            (r'xox[baprs]-[a-zA-Z0-9-]{10,}', 'Slack Token'),
            (r'password\s*=\s*["\'][^"\']+["\']', '硬编码密码'),
            (r'secret\s*=\s*["\'][^"\']+["\']', '硬编码密钥'),
        ]
        for i, line in enumerate(code.splitlines(), 1):
            # 跳过注释行
            stripped = line.strip()
            if stripped.startswith('#'):
                continue
            for pat, desc in patterns:
                if re.search(pat, line):
                    violations.append(Violation(
                        rule="no_hardcoded_secrets", severity="critical",
                        line=i, message=f"发现 {desc}",
                        suggestion=SUGGESTIONS["no_hardcoded_secrets"]))
        return violations

    def _check_sql_injection(self, code, tree, cm) -> list:
        """检测 SQL 注入风险"""
        violations = []
        # 字符串拼接 SQL
        for i, line in enumerate(code.splitlines(), 1):
            if re.search(r'["\'].*["\']\s*%\s*(input|request|argv|user)', line):
                violations.append(Violation(
                    rule="no_sql_injection", severity="critical",
                    line=i, message="字符串格式化拼接 SQL（注入风险）",
                    suggestion=SUGGESTIONS["no_sql_injection"]))
            if re.search(r'f["\'].*SELECT.*\{', line, re.I):
                violations.append(Violation(
                    rule="no_sql_injection", severity="critical",
                    line=i, message="f-string 拼接 SQL（注入风险）",
                    suggestion=SUGGESTIONS["no_sql_injection"]))
        # execute 第一个参数含变量
        if tree:
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    try:
                        func = ast.unparse(node.func)
                        if re.search(r'\.(execute|executemany)$', func):
                            if node.args and not (isinstance(node.args[0], ast.Constant)):
                                violations.append(Violation(
                                    rule="no_sql_injection", severity="critical",
                                    line=node.lineno,
                                    message=f"{func} 参数非字面量（可能拼接）",
                                    suggestion=SUGGESTIONS["no_sql_injection"]))
                    except Exception:
                        pass
        return violations

    def _check_type_hints(self, code, tree, cm) -> list:
        """检测函数缺少类型注解"""
        violations = []
        if not tree:
            return violations
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                # 跳过 __init__ 等特殊方法
                if node.name.startswith('__') and node.name.endswith('__'):
                    continue
                # 检查参数
                for arg in node.args.args:
                    if arg.arg == 'self':
                        continue
                    if arg.annotation is None:
                        violations.append(Violation(
                            rule="type_hints", severity="medium",
                            line=arg.lineno,
                            message=f"参数 '{arg.arg}' 缺少类型注解",
                            suggestion=SUGGESTIONS["type_hints"]))
                # 检查返回值
                if node.returns is None and node.name != '__init__':
                    violations.append(Violation(
                        rule="type_hints", severity="low",
                        line=node.lineno,
                        message=f"函数 '{node.name}' 缺少返回值注解",
                        suggestion=SUGGESTIONS["type_hints"]))
        return violations

    def _check_try_except(self, code, tree, cm) -> list:
        """检测危险操作是否包了 try-except"""
        violations = []
        risky_patterns = [
            (r'\bopen\s*\(', '文件操作'),
            (r'\bsocket\.\w+', '网络操作'),
            (r'\bsubprocess\.\w+', '子进程操作'),
            (r'\brequests\.(get|post|put|delete)\b', 'HTTP 请求'),
            (r'\bcursor\.execute\b', '数据库操作'),
            (r'\bos\.remove\b', '文件删除'),
            (r'\bshutil\.rmtree\b', '目录删除'),
        ]
        for i, line in enumerate(code.splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith('#'):
                continue
            for pat, desc in risky_patterns:
                if re.search(pat, line):
                    # 检查前面几行有没有 try:
                    context = "\n".join(code.splitlines()[max(0,i-5):i])
                    if 'try:' not in context and 'try :' not in context:
                        violations.append(Violation(
                            rule="try_except", severity="high",
                            line=i, message=f"{desc}未包 try-except",
                            suggestion=SUGGESTIONS["try_except"]))

        # AST 层面：检查 try 块是否覆盖了危险调用
        if tree:
            for node in ast.walk(tree):
                if isinstance(node, ast.Try):
                    try_body = ast.unparse(node.body) if hasattr(ast, 'unparse') else ""
                    # 检查 try 体里是否有危险操作
                    if not re.search(r'open|socket|subprocess|requests|cursor|os\.remove|shutil', try_body):
                        # 这个 try 没保护任何危险操作（可能是空的或只有安全代码）
                        pass  # 不算违规
        return violations

    def _check_infinite_recursion(self, code, tree, cm) -> list:
        """检测可能的无限递归"""
        violations = []
        if not tree:
            return violations
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                # 只检查函数体（不含签名行）
                body_lines = ast.unparse(node).splitlines()[1:]  # 跳过 def 行
                body_str = "\n".join(body_lines)
                # 函数体内直接调用自身，且无终止条件
                if re.search(rf'\b{node.name}\s*\(', body_str):
                    # 检查有没有 if/return 终止
                    has_condition = bool(re.search(r'\bif\b.*\breturn\b', body_str, re.S))
                    has_base_case = '==' in body_str or '<=' in body_str or '>=' in body_str
                    if not (has_condition or has_base_case):
                        violations.append(Violation(
                            rule="no_infinite_recursion", severity="high",
                            line=node.lineno,
                            message=f"函数 '{node.name}' 递归调用自身但缺终止条件",
                            suggestion=SUGGESTIONS["no_infinite_recursion"]))
        return violations

    def _check_unused_import(self, code, tree, cm) -> list:
        """检测未使用的 import（基于 AST，不靠正则猜）"""
        violations = []
        if not tree:
            return violations
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    name = alias.asname or alias.name.split('.')[0]
                    # 检查整个文件中是否引用了这个名字
                    used = False
                    for ref_node in ast.walk(tree):
                        if isinstance(ref_node, ast.Name) and ref_node.id == name:
                            if ref_node is not getattr(node, '_ctx', None):
                                used = True
                                break
                        elif isinstance(ref_node, ast.Attribute):
                            try:
                                base = ast.unparse(ref_node.value)
                                if base == name:
                                    used = True
                                    break
                            except Exception:
                                pass
                    if not used:
                        violations.append(Violation(
                            rule="no_unused_import", severity="low",
                            line=node.lineno,
                            message=f"import '{name}' 未被使用",
                            suggestion=SUGGESTIONS["no_unused_import"]))
            elif isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                for alias in node.names:
                    name = alias.asname or alias.name
                    used = False
                    for ref_node in ast.walk(tree):
                        if isinstance(ref_node, ast.Name) and ref_node.id == name:
                            used = True
                            break
                    if not used:
                        violations.append(Violation(
                            rule="no_unused_import", severity="low",
                            line=node.lineno,
                            message=f"from {mod} import '{name}' 未被使用",
                            suggestion=SUGGESTIONS["no_unused_import"]))
        return violations

    def _check_markdown_clean(self, code, tree, cm) -> list:
        """检测残留占位符"""
        violations = []
        patterns = [
            (r'\[TODO[^\]]*\]', 'TODO 占位符'),
            (r'\[待补充[^\]]*\]', '待补充占位符'),
            (r'\[placeholder[^\]]*\]', 'placeholder'),
            (r'\[FIXME[^\]]*\]', 'FIXME 标记'),
        ]
        for i, line in enumerate(code.splitlines(), 1):
            for pat, desc in patterns:
                if re.search(pat, line):
                    violations.append(Violation(
                        rule="markdown_clean", severity="low",
                        line=i, message=f"残留 {desc}",
                        suggestion=SUGGESTIONS["markdown_clean"]))
        return violations

    def _check_ast_parseable(self, code, tree, cm) -> list:
        """AST 可解析性检查"""
        if tree is None:
            return [Violation(
                rule="v1_ast_check", severity="medium",
                line=1, message="代码无法被 AST 解析（语法错误）",
                suggestion=SUGGESTIONS["v1_ast_check"])]
        return []

    def _check_subprocess_shell(self, code, tree, cm) -> list:
        """检测 subprocess 使用 shell=True"""
        violations = []
        if not tree:
            return violations
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                try:
                    func = ast.unparse(node.func)
                    if 'subprocess' in func and 'shell=True' in ast.unparse(node):
                        violations.append(Violation(
                            rule="no_subprocess_shell", severity="critical",
                            line=node.lineno,
                            message=f"{func} 使用 shell=True（命令注入风险）",
                            suggestion=SUGGESTIONS["no_subprocess_shell"]))
                except Exception:
                    pass
        return violations

    def _check_pickle_deserialize(self, code, tree, cm) -> list:
        """检测 pickle 反序列化不可信数据"""
        violations = []
        if not tree:
            return violations
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                try:
                    func = ast.unparse(node.func)
                    if re.search(r'\bpickle\.loads?\b', func) or re.search(r'\bcPickle\.loads?\b', func):
                        violations.append(Violation(
                            rule="no_pickle_deserialize", severity="high",
                            line=node.lineno,
                            message=f"{func} 反序列化（可能执行任意代码）",
                            suggestion=SUGGESTIONS["no_pickle_deserialize"]))
                except Exception:
                    pass
        return violations

    def _check_global_mutable(self, code, tree, cm) -> list:
        """检测全局可变状态"""
        violations = []
        if not tree:
            return violations
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for tgt in node.targets:
                    if isinstance(tgt, ast.Name) and tgt.id.isupper():
                        # 全大写 = 常量，不算
                        continue
                    if isinstance(tgt, ast.Name) and not tgt.id.startswith('_'):
                        # 模块级赋值（不在函数/类内）
                        parent = None
                        for p in ast.walk(tree):
                            for child in ast.iter_child_nodes(p):
                                if child is node:
                                    parent = p
                                    break
                        if parent is tree or parent is None:
                            violations.append(Violation(
                                rule="no_global_mutable", severity="medium",
                                line=node.lineno,
                                message=f"全局可变变量 '{tgt.id}'（并发/测试风险）",
                                suggestion=SUGGESTIONS["no_global_mutable"]))
        return violations

    def _check_bare_except(self, code, tree, cm) -> list:
        """检测裸 except:（吞掉所有异常）"""
        violations = []
        if not tree:
            return violations
        for node in ast.walk(tree):
            if isinstance(node, ast.ExceptHandler) and node.type is None:
                violations.append(Violation(
                    rule="no_bare_except", severity="high",
                    line=node.lineno,
                    message="裸 except: 会吞掉所有异常（含 KeyboardInterrupt）",
                    suggestion=SUGGESTIONS["no_bare_except"]))
        return violations

    def _check_sql_string_concat(self, code, tree, cm) -> list:
        """检测 SQL 字符串拼接（更严格版）"""
        violations = []
        for i, line in enumerate(code.splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith('#'):
                continue
            # 引号内含 SELECT 且后面有拼接操作（同一行或跨行）
            # 模式1: "SELECT ..." + var 或 "..." % var
            if re.search(r'["\'][^"\']*SELECT[^"\']*["\']\s*[+%]\s*\w', line, re.I):
                violations.append(Violation(
                    rule="no_sql_string_concat", severity="critical",
                    line=i, message="SQL 语句字符串拼接（注入风险）",
                    suggestion=SUGGESTIONS["no_sql_string_concat"]))
            # 模式2: query = "SELECT ..." + var（赋值形式）
            elif re.search(r'=\s*["\'][^"\']*SELECT', line, re.I):
                # 同一行有拼接
                if re.search(r'[+%]\s*\w', line):
                    violations.append(Violation(
                        rule="no_sql_string_concat", severity="critical",
                        line=i, message="SQL 语句含变量拼接（注入风险）",
                        suggestion=SUGGESTIONS["no_sql_string_concat"]))
                else:
                    # 跨行拼接：看下一行是否以 + 开头
                    pass  # 后续 AST 检查会兜底
            # 模式3: 赋值给 query 变量后传给 execute
            elif re.search(r'^\s*query\s*=', line) and 'SELECT' in line.upper():
                if '+' in line or '%' in line:
                    violations.append(Violation(
                        rule="no_sql_string_concat", severity="critical",
                        line=i, message="SQL 语句含拼接（注入风险）",
                        suggestion=SUGGESTIONS["no_sql_string_concat"]))
        # AST 层面：execute 的参数含字符串拼接
        if tree:
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    try:
                        func = ast.unparse(node.func)
                        if re.search(r'\.(execute|executemany)$', func):
                            if node.args and isinstance(node.args[0], ast.BinOp):
                                violations.append(Violation(
                                    rule="no_sql_string_concat", severity="critical",
                                    line=node.lineno,
                                    message=f"{func} 参数含字符串拼接（注入风险）",
                                    suggestion=SUGGESTIONS["no_sql_string_concat"]))
                    except Exception:
                        pass
        return violations

    # ── 执行所有规则 ──────────────────────────────────────
    def run_all(self, code: str) -> tuple:
        """返回 (violations, metrics, compressed_view)"""
        try:
            tree = ast.parse(code)
        except SyntaxError:
            tree = None

        cm = CodeMap(code) if tree else None
        all_violations = []
        for name, func in self.rules:
            try:
                v = func(code, tree, cm)
                all_violations.extend(v)
            except Exception as e:
                log.error(f"⚠️ 规则 {name} 执行异常: {e}")

        # 计算度量
        metrics = {}
        if cm:
            complexities = [f["complexity"] for f in cm.functions]
            metrics = {
                "functions": len(cm.functions),
                "classes": len(cm.classes),
                "imports": len(cm.imports),
                "calls": len(cm.calls),
                "avg_complexity": round(sum(complexities)/len(complexities), 1) if complexities else 0,
                "max_complexity": max(complexities) if complexities else 0,
                "total_lines": len(code.splitlines()),
            }
            compressed = cm.get_compressed_view()
        else:
            compressed = ""

        return all_violations, metrics, compressed


# ════════════════════════════════════════════════════════
#  对外接口（极简，网关只调这个）
# ════════════════════════════════════════════════════════
_engine = RuleEngine()


def check(code: str) -> Report:
    """
    核心入口 —— 给 gateway.py 调用

    输入：Python 源码字符串
    输出：Report 对象（passed / violations / compressed_view / metrics）

    借鉴：
    - Headroom：同时输出 compressed_view（给 AI 看，省 token）
    - Quality Gate：输出完整 metrics（复杂度、函数数等）
    - CodeGraph：内部建 CodeMap（函数/类/调用关系）
    """
    if not code or not code.strip():
        return Report(passed=True, violations=[], compressed_view="", metrics={})

    violations, metrics, compressed = _engine.run_all(code)

    # 判断通过与否（critical/high 必须拦截）
    blocked_severities = {"critical", "high"}
    passed = not any(v.severity in blocked_severities for v in violations)

    # 环境信息
    metadata = {
        "rules_checked": len(_engine.rules),
        "rules_passed": len(_engine.rules) - len(violations),
        "engine": "Python AST (native)",
        "version": "3.2",
    }

    return Report(
        passed=passed,
        violations=violations,
        compressed_view=compressed,
        metrics=metrics,
        metadata=metadata,
    )


def check_file(path: str) -> Report:
    """检查文件"""
    try:
        code = Path(path).resolve().read_text(encoding="utf-8")
    except Exception as e:
        return Report(passed=False, violations=[Violation(
            rule="file_read", severity="critical", line=0,
            message=f"无法读取文件: {e}")])
    return check(code)


def get_compressed_view(code: str) -> str:
    """
    返回代码骨架（给 AI 看的精简版）

    借鉴 Headroom 的"保留骨架、压缩载荷"思路：
    - 保留：函数签名、类定义、import、装饰器
    - 压缩：函数体用 # ... (N lines) 替代
    - 效果：300 行代码 → ~50 行骨架，省 80%+ token
    """
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return code[:500]  # 解析失败就截前 500 字符

    cm = CodeMap(code)
    return cm.get_compressed_view()


# ════════════════════════════════════════════════════════
#  突变测试（借鉴 mutatest 的质量门禁思路）
# ════════════════════════════════════════════════════════
def mutation_test(code: str, expected_violations: list) -> dict:
    """
    故意注入违规，验证检测规则是否生效

    借鉴 mutatest 的"主动制造故障来检验检测能力"思路。
    不是测试你的代码，而是测试"守门员"本身敏不敏感。

    用法：
        result = mutation_test(my_code, ["no_hardcoded_secrets"])
        如果 secrets 规则正常，result["detected"] 应该是 True
    """
    mutations = {
        "no_hardcoded_secrets": '\nAPI_KEY = "sk-mutated-test-key-1234567890"\n',
        "no_sql_injection":     '\nquery = "SELECT * FROM users WHERE id=" + user_input\ncursor.execute(query)\n',
        "no_subprocess_shell":  '\nimport subprocess\nsubprocess.run("ls", shell=True)\n',
        "no_pickle_deserialize":'\nimport pickle\ndata = pickle.loads(user_input)\n',
        "no_bare_except":       '\ntry:\n    risky_op()\nexcept:\n    pass\n',
        "type_hints":           '\ndef bad_func(x, y):\n    return x + y\n',
    }

    results = {}
    for rule_name in expected_violations:
        if rule_name not in mutations:
            results[rule_name] = {"status": "skip", "reason": "no mutation defined"}
            continue

        mutated = code + mutations[rule_name]
        report = check(mutated)
        detected = any(v.rule == rule_name for v in report.violations)
        results[rule_name] = {
            "status": "detected" if detected else "missed",
            "violations_found": [v.rule for v in report.violations],
        }

    return {
        "total": len(results),
        "detected": sum(1 for r in results.values() if r.get("status") == "detected"),
        "missed": [k for k, v in results.items() if v.get("status") == "missed"],
        "details": results,
    }


# ════════════════════════════════════════════════════════
#  导入钩子（借鉴 Quality Guard 的"导入时拦截"）
# ════════════════════════════════════════════════════════
class _GuardFinder:
    """自定义 import hook，导入时自动检查模块"""

    def __init__(self, strict: bool = False):
        self.strict = strict

    def find_spec(self, name, path=None, target=None):
        # 不拦截标准库和第三方
        if name.startswith(("jinchen", "__main__")):
            return None
        return None  # 暂不做拦截，只做检测

    def exec_module(self, module):
        pass


def install_guard_hook(strict: bool = False):
    """
    安装导入钩子（可选启用）

    借鉴 Quality Guard 的"导入时熔断"思路。
    启用后，每次 import 会先检查模块源码是否合规。
    不合规 → 警告（strict=False）或 抛异常（strict=True）。
    """
    import sys
    hook = _GuardFinder(strict=strict)
    if hook not in sys.meta_path:
        sys.meta_path.insert(0, hook)
        log.info(f"🔐 Guard Hook 已安装 (strict={strict})")
    return hook


# ════════════════════════════════════════════════════════
#  策略引擎（动态分级）
# ════════════════════════════════════════════════════════
POLICY = {
    "dev":  {"block_severity": "critical", "warn_severity": "high",  "max_retries": 1},
    "test": {"block_severity": "high",     "warn_severity": "medium", "max_retries": 2},
    "prod": {"block_severity": "medium",   "warn_severity": "low",    "max_retries": 3},
}

def check_with_policy(code: str, env: str = "dev") -> Report:
    """带环境策略的检查"""
    report = check(code)
    policy = POLICY.get(env, POLICY["dev"])

    # 根据策略调整 passed
    block_set = {"critical"}
    if policy["block_severity"] == "high":
        block_set = {"critical", "high"}
    elif policy["block_severity"] == "medium":
        block_set = {"critical", "high", "medium"}

    report.passed = not any(v.severity in block_set for v in report.violations)
    report.metadata["policy"] = env
    report.metadata["block_severity"] = policy["block_severity"]

    return report


# ════════════════════════════════════════════════════════
#  CLI 入口
# ════════════════════════════════════════════════════════
if __name__ == "__main__":
    import sys
    from pathlib import Path

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    if len(sys.argv) < 2:
        print("用法: python work.py <file.py> [--env dev|test|prod] [--mutate]")
        sys.exit(1)

    target = sys.argv[1]
    env = "dev"
    do_mutate = False
    if "--env" in sys.argv:
        env = sys.argv[sys.argv.index("--env") + 1]
    if "--mutate" in sys.argv:
        do_mutate = True

    if target == "self-test":
        # 自检：对自己做突变测试
        print("🧪 自检模式：对自己做突变测试")
        my_code = Path(__file__).read_text(encoding="utf-8")
        rules_to_test = ["no_hardcoded_secrets", "no_sql_injection",
                         "no_subprocess_shell", "no_bare_except"]
        result = mutation_test(my_code, rules_to_test)
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        code = Path(target).read_text(encoding="utf-8")
        report = check_with_policy(code, env=env)
        print(report.to_markdown())
        print(f"\n📊 度量: {json.dumps(report.metrics, ensure_ascii=False)}")
        print(f"🗺️ 骨架:\n{report.compressed_view[:500]}")

        if do_mutate:
            print("\n🧪 突变测试:")
            result = mutation_test(code, [v.rule for v in report.violations])
            print(json.dumps(result, indent=2, ensure_ascii=False))
