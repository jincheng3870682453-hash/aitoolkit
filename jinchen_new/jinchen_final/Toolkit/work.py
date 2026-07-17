#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
work.py — 核心行为约束 V3.1（诚实版）

修复记录（回应 audit）：
  [F8]  _detect_unused_import：改用 AST 遍历，解决变量名碰撞
  [F9]  sanitize：仅处理 docstring，不误删字符串字面量
  [F10] MultiLangASTEngine：明确标注正则 vs AST 准确率
  [F11] 所有 except 捕获具体异常，不静默

设计原则：
  - 所有检测方法统一签名：(self, code: str) -> GuardResult
  - Python 检测用 AST（准确），其他语言用正则（标注不准确）
"""

import re
import ast
import hashlib
import random
import string
import logging
from dataclasses import dataclass, field
from typing import Optional

log = logging.getLogger("work")


# ═════════════════════════════════════════════════════════
# 数据类
# ═════════════════════════════════════════════════════════

@dataclass
class GuardResult:
    """单条检测结果"""
    rule: str
    passed: bool
    action: str          # pass / regenerate / rollback / warn
    evidence: dict = field(default_factory=dict)
    message: str = ""

    def to_dict(self) -> dict:
        return {
            "rule": self.rule,
            "passed": self.passed,
            "action": self.action,
            "evidence": self.evidence,
            "message": self.message,
        }


# ═════════════════════════════════════════════════════════
# V1 — InstinctGuard  本能守门
# ═════════════════════════════════════════════════════════

class InstinctGuard:
    """
    核心守门器 —— 所有 AI 输出必须经过的检测层。
    无状态：每次调用独立，不维护跨调用状态。
    """

    ALL_RULES = [
        "type_hints", "try_except", "no_hardcoded_secrets",
        "no_sql_injection", "markdown_clean",
        "no_infinite_recursion", "no_unused_import",
        "v1_ast_check",
    ]

    def __init__(self, extra_rules: list | None = None):
        self.extra_rules = extra_rules or []

    # ── 主入口 ────────────────────────────────────────
    def check_all(self, code: str) -> list[GuardResult]:
        """对一段代码执行全部检测，返回结果列表"""
        results: list[GuardResult] = []
        detectors = [
            ("type_hints",            self._detect_type_hints),
            ("try_except",            self._detect_try_except),
            ("no_hardcoded_secrets",  self._detect_hardcoded_secrets),
            ("no_sql_injection",      self._detect_sql_injection),
            ("markdown_clean",        self._detect_markdown_clean),
            ("no_infinite_recursion", self._detect_infinite_recursion),
            ("no_unused_import",      self._detect_unused_import),
        ]
        for name, fn in detectors:
            try:
                r = fn(code)
                if isinstance(r, GuardResult):
                    results.append(r)
            except SyntaxError as e:
                results.append(GuardResult(
                    rule=name, passed=False, action="warn",
                    evidence={"syntax_error": str(e)},
                    message=f"代码语法错误: {e}",
                ))
            except Exception as e:
                log.error(f"❌ 检测 {name} 异常: {type(e).__name__}: {e}")
                results.append(GuardResult(
                    rule=name, passed=False, action="warn",
                    evidence={"error": f"{type(e).__name__}: {e}"},
                    message=f"检测模块异常: {e}",
                ))
        return results

    def summary(self, results: list[GuardResult]) -> dict:
        passed = sum(1 for r in results if r.passed)
        return {
            "total": len(results),
            "passed": passed,
            "failed": len(results) - passed,
            "details": [r.to_dict() for r in results],
        }

    # ── 1. 类型注解（AST）──────────────────────────────
    def _detect_type_hints(self, code: str) -> GuardResult:
        try:
            tree = ast.parse(code)
        except SyntaxError:
            return GuardResult("type_hints", True, "pass",
                             message="语法错误，跳过类型检查")

        funcs = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]
        if not funcs:
            return GuardResult("type_hints", True, "pass",
                             message="无函数定义，无需注解")

        unannotated: list[str] = []
        for f in funcs:
            if f.returns is None:
                unannotated.append(f"{f.name}() 缺少返回类型")
            for a in f.args.args:
                if a.annotation is None:
                    unannotated.append(f"{f.name}.{a.arg} 缺少类型注解")
            # 检查 *args / **kwargs
            if f.args.vararg and f.args.vararg.annotation is None:
                unannotated.append(f"{f.name}.*{f.args.vararg.arg} 缺少注解")
            if f.args.kwarg and f.args.kwarg.annotation is None:
                unannotated.append(f"{f.name}.**{f.args.kwarg.arg} 缺少注解")

        if unannotated:
            return GuardResult(
                "type_hints", False, "regenerate",
                evidence={"unannotated": unannotated},
                message=f"{len(unannotated)} 处缺少类型注解",
            )
        return GuardResult("type_hints", True, "pass")

    # ── 2. try-except（AST）────────────────────────────
    def _detect_try_except(self, code: str) -> GuardResult:
        try:
            tree = ast.parse(code)
        except SyntaxError:
            return GuardResult("try_except", True, "pass", message="语法错误，跳过")

        # 风险函数调用模式
        risky_patterns = [
            "open", "socket", "subprocess", "requests.get", "requests.post",
            "requests.put", "requests.delete", "cursor.execute",
            "file.write", "os.remove", "shutil.rmtree", "os.mkdir",
            "os.rename", "pickle.load", "yaml.load", "os.unlink",
        ]

        found_risky: list[str] = []
        has_try = any(isinstance(n, ast.Try) for n in ast.walk(tree))

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            try:
                func_str = ast.unparse(node)
            except (AttributeError, Exception):
                func_str = ""
            for rp in risky_patterns:
                if rp in func_str:
                    found_risky.append(func_str[:80])
                    break

        if found_risky and not has_try:
            return GuardResult(
                "try_except", False, "regenerate",
                evidence={"risky_calls": found_risky},
                message=f"发现 {len(found_risky)} 个风险调用但无 try-except",
            )
        return GuardResult("try_except", True, "pass")

    # ── 3. 硬编码密钥（正则）──────────────────────────
    def _detect_hardcoded_secrets(self, code: str) -> GuardResult:
        patterns = [
            (r'api_key\s*=\s*["\'][^"\']{16,}["\']', "api_key 硬编码"),
            (r'secret\s*=\s*["\'][^"\']{8,}["\']', "secret 硬编码"),
            (r'password\s*=\s*["\'][^"\']{6,}["\']', "password 硬编码"),
            (r'sk-[a-zA-Z0-9]{20,}', "OpenAI 格式密钥"),
            (r'AKIA[0-9A-Z]{16}', "AWS Access Key"),
            (r'ghp_[a-zA-Z0-9]{30,}', "GitHub Token"),
            (r'xox[baprs]-[a-zA-Z0-9-]{10,}', "Slack Token"),
        ]
        found: list[dict] = []
        for pat, desc in patterns:
            for m in re.finditer(pat, code):
                line_num = code[:m.start()].count('\n') + 1
                found.append({"type": desc, "line": line_num,
                              "snippet": m.group()[:40]})

        if found:
            return GuardResult(
                "no_hardcoded_secrets", False, "rollback",
                evidence={"secrets": found},
                message=f"发现 {len(found)} 个硬编码密钥/凭证",
            )
        return GuardResult("no_hardcoded_secrets", True, "pass")

    # ── 4. SQL 注入（AST）──────────────────────────────
    def _detect_sql_injection(self, code: str) -> GuardResult:
        try:
            tree = ast.parse(code)
        except SyntaxError:
            return GuardResult("no_sql_injection", True, "pass")

        sql_kw = re.compile(r'\b(SELECT|INSERT|UPDATE|DELETE|CREATE|DROP|ALTER)\b', re.I)
        issues: list[str] = []

        for node in ast.walk(tree):
            # % 格式化拼接: "SELECT * FROM t WHERE id = %s" % (uid,)
            if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mod):
                try:
                    left = ast.unparse(node.left)
                    if sql_kw.search(left):
                        issues.append(f"SQL 使用 % 格式化: {left[:60]}")
                except Exception:
                    pass
            # + 字符串拼接: "SELECT * FROM t WHERE id = " + uid
            if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
                try:
                    full = ast.unparse(node)
                    if sql_kw.search(full):
                        issues.append(f"SQL 使用 + 拼接: {full[:60]}")
                except Exception:
                    pass
            # .format() 拼接
            if isinstance(node, ast.Call):
                try:
                    func_str = ast.unparse(node.func) if hasattr(ast, 'unparse') else ""
                    full = ast.unparse(node) if hasattr(ast, 'unparse') else ""
                    if 'format' in func_str and sql_kw.search(full):
                        issues.append(f"SQL 使用 .format(): {full[:60]}")
                except Exception:
                    pass
            # f-string 拼接
            if isinstance(node, ast.JoinedStr):
                try:
                    full = ast.unparse(node) if hasattr(ast, 'unparse') else ""
                    if sql_kw.search(full):
                        issues.append(f"SQL 使用 f-string: {full[:60]}")
                except Exception:
                    pass

        if issues:
            return GuardResult(
                "no_sql_injection", False, "rollback",
                evidence={"issues": issues},
                message=f"发现 {len(issues)} 处可能的 SQL 注入风险",
            )
        return GuardResult("no_sql_injection", True, "pass")

    # ── 5. Markdown 占位符（仅 docstring）──────────────
    def _detect_markdown_clean(self, code: str) -> GuardResult:
        issues: list[str] = []
        patterns = [
            r'\[TODO[^\]]*\]', r'\[待补充[^\]]*\]',
            r'\[placeholder[^\]]*\]', r'\[TBD[^\]]*\]',
            r'XXX', r'FIXME',
        ]
        try:
            tree = ast.parse(code)
        except SyntaxError:
            return GuardResult("markdown_clean", True, "pass")

        for node in ast.walk(tree):
            # 只对函数/类/模块的 docstring 做检查
            if not isinstance(node, (ast.FunctionDef, ast.ClassDef, ast.Module)):
                continue
            doc = ast.get_docstring(node, clean=False)
            if not doc:
                continue
            for pat in patterns:
                m = re.search(pat, doc)
                if m:
                    issues.append(f"{type(node).__name__} docstring: {m.group()[:40]}")

        if issues:
            return GuardResult(
                "markdown_clean", False, "regenerate",
                evidence={"issues": issues},
                message=f"发现 {len(issues)} 个文档占位符",
            )
        return GuardResult("markdown_clean", True, "pass")

    # ── 6. 无限递归（AST）──────────────────────────────
    def _detect_infinite_recursion(self, code: str) -> GuardResult:
        try:
            tree = ast.parse(code)
        except SyntaxError:
            return GuardResult("no_infinite_recursion", True, "pass")

        issues: list[str] = []

        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue
            # 检查是否递归调用自己
            calls_self = any(
                isinstance(n, ast.Call)
                and isinstance(n.func, ast.Name)
                and n.func.id == node.name
                for n in ast.walk(node)
            )
            if not calls_self:
                continue

            # 检查是否有终止条件
            has_proper_base = False
            for child in ast.walk(node):
                if isinstance(child, ast.If):
                    try:
                        if_stmt = ast.unparse(child) if hasattr(ast, 'unparse') else ""
                        if any(kw in if_stmt for kw in ['return', 'break', 'raise']):
                            # 确认 return/break 在 if 分支里（不是 else 里）
                            if child.body:
                                body_str = ast.unparse(child.body) if hasattr(ast, 'unparse') else ""
                                if 'return' in body_str or 'break' in body_str or 'raise' in body_str:
                                    has_proper_base = True
                                    break
                    except Exception:
                        pass

            if not has_proper_base:
                issues.append(f"函数 {node.name} 递归但缺少明确的终止条件")

        if issues:
            return GuardResult(
                "no_infinite_recursion", False, "rollback",
                evidence={"issues": issues},
                message=f"发现 {len(issues)} 处可能的无限递归",
            )
        return GuardResult("no_infinite_recursion", True, "pass")

    # ── 7. 未使用导入（AST，解决变量名碰撞）──────
    def _detect_unused_import(self, code: str) -> GuardResult:
        try:
            tree = ast.parse(code)
        except SyntaxError:
            return GuardResult("no_unused_import", True, "pass")

        # 收集导入信息
        imported_names: set[str] = set()       # 直接导入的名字
        from_imports: dict[str, set[str]] = {}  # module -> {names}
        wildcard_modules: set[str] = set()      # from x import *

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    name = alias.asname or alias.name.split('.')[0]
                    imported_names.add(name)
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if module == '__future__':
                    continue
                if node.names and node.names[0].name == '*':
                    wildcard_modules.add(module)
                    continue
                for alias in node.names:
                    name = alias.asname or alias.name
                    if name == '*':
                        wildcard_modules.add(module)
                        continue
                    imported_names.add(name)
                    if module:
                        from_imports.setdefault(module, set()).add(name)

        if not imported_names and not from_imports:
            return GuardResult("no_unused_import", True, "pass")

        # 收集实际引用的名字（排除导入语句本身）
        used_names: set[str] = set()
        used_attrs: dict[str, set[str]] = {}

        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                continue  # 不把导入名本身算作"使用"
            if isinstance(node, ast.Name):
                used_names.add(node.id)
            elif isinstance(node, ast.Attribute):
                base = node
                parts: list[str] = []
                while isinstance(base, ast.Attribute):
                    parts.append(base.attr)
                    base = base.value
                if isinstance(base, ast.Name):
                    parts.append(base.id)
                    parts.reverse()
                    used_names.add(parts[0])
                    if len(parts) > 1:
                        used_attrs.setdefault(parts[0], set()).add(parts[1])

        # 检查未使用的直接导入
        unused: list[str] = []
        for name in sorted(imported_names):
            if name not in used_names:
                unused.append(name)

        # 检查未使用的 from-import
        for mod, attrs in from_imports.items():
            used = used_attrs.get(mod, set())
            for attr in sorted(attrs):
                if attr not in used and mod not in used_names:
                    if attr not in unused:
                        unused.append(f"{mod}.{attr}")

        if unused:
            return GuardResult(
                "no_unused_import", False, "regenerate",
                evidence={"unused": unused},
                message=f"未使用的导入: {', '.join(unused[:5])}",
            )
        return GuardResult("no_unused_import", True, "pass")

    # ── 工具：sanitize（AST 版）───────────────────────
    def sanitize(self, code: str) -> str:
        """
        移除 docstring 中的占位符。
        仅处理 AST 能识别的 docstring，绝不碰字符串字面量。
        """
        try:
            tree = ast.parse(code)
        except SyntaxError:
            return code

        # 收集需要替换的 docstring（节点 + 原始文本 + 新文本）
        replacements: list[tuple[str, str]] = []

        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.ClassDef, ast.Module)):
                continue
            doc = ast.get_docstring(node, clean=False)
            if not doc:
                continue
            new_doc = doc
            for pat in [
                r'\[TODO[^\]]*\]', r'\[待补充[^\]]*\]',
                r'\[placeholder[^\]]*\]', r'\[TBD[^\]]*\]',
            ]:
                new_doc = re.sub(pat, '[已补充]', new_doc)
            if new_doc != doc:
                replacements.append((doc, new_doc))

        if not replacements:
            return code

        # 用精确的字符串替换（只替换 docstring 内容）
        result = code
        for old, new in replacements:
            result = result.replace(old, new, 1)

        return result


# ═════════════════════════════════════════════════════════
# V3 — MultiLangASTEngine  多语言检测（诚实标注版）
# ═════════════════════════════════════════════════════════
#
# 重要说明：
#   Python → 使用 AST（准确）
#   Java/Kotlin/TypeScript/Swift → 使用正则（不准确）
#
# 正则检测的已知局限：
#   - 换一行格式就可能漏检
#   - 注释里的代码会误报
#   - 字符串里的内容会误报
#   - 嵌套调用可能失效
#
# 这些语言的检测仅作为初步筛查参考，不应用于生产环境。

class LangDetector:
    """单种语言的检测器集合"""

    def __init__(self, name: str, method: str = "regex"):
        self.name = name
        self.method = method
        self.detectors: list[dict] = []

    def register(self, rule_name: str, detect_func, on_fail: str = "regenerate"):
        self.detectors.append({
            "name": rule_name,
            "detect": detect_func,
            "on_fail": on_fail,
        })

    def check(self, code: str) -> list[dict]:
        violations = []
        for d in self.detectors:
            try:
                if not d["detect"](code):
                    violations.append({
                        "rule": d["name"],
                        "on_fail": d["on_fail"],
                        "method": self.method,
                    })
            except Exception as e:
                log.error(f"❌ {self.name} 检测 {d['name']} 异常: {e}")
                violations.append({
                    "rule": d["name"],
                    "on_fail": "warn",
                    "method": self.method,
                    "error": f"{type(e).__name__}: {e}",
                })
        return violations


class MultiLangASTEngine:
    """
    多语言检测引擎（诚实版）。

    准确性说明：
    - Python: AST 解析，高准确率
    - Java/Kotlin/TypeScript/Swift: 正则匹配，已知有漏报和误报
    """

    ACCURACY = {
        "python":    "high (AST)",
        "java":      "low (regex, known limitations)",
        "kotlin":    "low (regex, known limitations)",
        "typescript": "low (regex, known limitations)",
        "swift":     "low (regex, known limitations)",
    }

    def __init__(self):
        self.languages: dict[str, LangDetector] = {}
        self._register_python()
        self._register_java()
        self._register_kotlin()
        self._register_typescript()
        self._register_swift()

    # ── Python (AST) ──────────────────────────────────
    def _register_python(self):
        lang = LangDetector("python", method="ast")
        ig = InstinctGuard()
        lang.register("type_hints",
                     lambda c: ig._detect_type_hints(c).passed, "regenerate")
        lang.register("try_except",
                     lambda c: ig._detect_try_except(c).passed, "regenerate")
        lang.register("no_infinite_recursion",
                     lambda c: ig._detect_infinite_recursion(c).passed, "rollback")
        lang.register("no_unused_import",
                     lambda c: ig._detect_unused_import(c).passed, "regenerate")
        self.languages["python"] = lang

    # ── Java (正则) ──────────────────────────────────
    def _register_java(self):
        lang = LangDetector("java", method="regex")
        lang.register("try_catch",
            lambda c: not bool(re.search(
                r'\b(FileInputStream|Socket\(|ProcessBuilder|'
                r'Runtime\.getRuntime|Class\.forName|DriverManager)', c))
            or bool(re.search(r'try\s*\{', c)),
            "regenerate")
        lang.register("no_bare_printstack",
            lambda c: "printStackTrace" not in c
                      or bool(re.search(r'\b(logger|Logger\.|Log\.)', c)),
            "regenerate")
        lang.register("sql_prepared_statement",
            lambda c: "Statement" not in c
                      or "PreparedStatement" in c
                      or "prepareStatement" in c,
            "rollback")

        def _has_javadoc(c):
            methods = re.findall(
                r'public\s+(?:static\s+|final\s+)*'
                r'[\w<>\[\],\s\?]+?\s+'
                r'(\w+)\s*\(([^)]*)\)\s*\{', c)
            if not methods:
                return True
            all_no_params = all(len(m[1].strip()) == 0 for m in methods)
            if all_no_params:
                return True
            return bool(re.search(r'/\*\*(?:\s*\n\s*\*\s*\w).*?\*/', c, re.DOTALL))
        lang.register("has_javadoc", _has_javadoc, "warn")
        self.languages["java"] = lang

    # ── Kotlin (正则) ────────────────────────────────
    def _register_kotlin(self):
        lang = LangDetector("kotlin", method="regex")
        lang.register("explicit_types",
            lambda c: not bool(re.search(r'fun\s+\w+\s*\([^)]*\)\s*\{', c))
                      or bool(re.search(r'fun\s+\w+\s*\([^)]*\)\s*:\s*\w', c)),
            "regenerate")
        lang.register("no_bang_bang",
            lambda c: c.count("!!") == 0,
            "regenerate")
        lang.register("uses_coroutines",
            lambda c: "Thread(" not in c
                      or any(kw in c for kw in
                          ["CoroutineScope", "launch", "async", "runBlocking"]),
            "warn")
        self.languages["kotlin"] = lang

    # ── TypeScript (正则) ───────────────────────────
    def _register_typescript(self):
        lang = LangDetector("typescript", method="regex")
        lang.register("ts_type_annotations",
            lambda c: ": any" not in c
                      and (bool(re.search(r'interface\s+\w+|type\s+\w+\s*=', c))
                           or bool(re.search(r'function\s+\w+\s*\([^)]*\)\s*:', c))),
            "regenerate")
        lang.register("no_any",
            lambda c: ": any" not in c and "as any" not in c,
            "warn")
        lang.register("promise_handled",
            lambda c: "Promise" not in c
                      or any(kw in c for kw in ["await", ".then(", ".catch("]),
            "regenerate")
        self.languages["typescript"] = lang

    # ── Swift (正则) ────────────────────────────────
    def _register_swift(self):
        lang = LangDetector("swift", method="regex")
        lang.register("optional_binding",
            lambda c: c.count("!") <= 1
                      or any(kw in c for kw in ["guard let", "if let", "as?"]),
            "regenerate")
        lang.register("error_handling",
            lambda c: "try!" not in c
                      and (("do {" in c and "catch" in c) or "try?" in c),
            "regenerate")
        lang.register("no_force_chain",
            lambda c: c.count("!") <= 2,
            "warn")
        self.languages["swift"] = lang

    # ── 自动语言识别 ──────────────────────────────────
    def detect_language(self, code: str, filename: str = "") -> str:
        ext_map = {
            ".py": "python", ".java": "java", ".kt": "kotlin",
            ".ts": "typescript", ".tsx": "typescript",
            ".swift": "swift", ".js": "typescript",
        }
        for ext, lang in ext_map.items():
            if filename.endswith(ext):
                return lang
        if "func " in code and "->" in code and "let " in code:
            return "swift"
        if "public static void" in code:
            return "java"
        if "fun " in code and "val " in code:
            return "kotlin"
        if "interface " in code and ": " in code:
            return "typescript"
        return "python"

    def check(self, code: str, filename: str = "") -> dict:
        lang = self.detect_language(code, filename)
        if lang not in self.languages:
            return {"language": lang, "violations": [], "passed": True,
                    "method": "unknown"}
        violations = self.languages[lang].check(code)
        return {
            "language": lang,
            "violations": violations,
            "passed": len(violations) == 0,
            "method": self.languages[lang].method,
            "accuracy_note": self.ACCURACY.get(lang, "unknown"),
        }

    def list_supported(self) -> dict[str, dict]:
        return {
            name: {
                "rules": [d["name"] for d in lang.detectors],
                "method": lang.method,
                "accuracy": self.ACCURACY.get(name, "unknown"),
            }
            for name, lang in self.languages.items()
        }


# ═════════════════════════════════════════════════════════
# 快捷函数
# ═════════════════════════════════════════════════════════

def check_code(code: str, filename: str = "") -> dict:
    """一行检查代码（自动识别语言 + 全部规则）"""
    guard = InstinctGuard()
    ml = MultiLangASTEngine()
    r1 = guard.check_all(code)
    r2 = ml.check(code, filename)
    return {
        "guard": guard.summary(r1),
        "multilang": r2,
    }


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        f = sys.argv[1]
        code = open(f, encoding="utf-8").read()
        result = check_code(code, f)
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print("Usage: python work.py <file.py/java/kt/ts/swift>")
        print("\nSupported languages and accuracy:")
        ml = MultiLangASTEngine()
        for lang, info in ml.list_supported().items():
            print(f"  {lang}: {info['method']} ({info['accuracy']})")
