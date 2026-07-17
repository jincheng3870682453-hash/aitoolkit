"""
github_scout.py —— 项目结构侦察兵

核心思路（金呈的原话）：
  "链接地址是 main，要查的东西就是在 main 后面加个杠，
   然后加这些。py 文件前面再加一个杠，再搜。"

功能：
  1. 从 GitHub 链接解析 user/repo/branch
  2. 从对话历史 / README / 目录树提取文件结构
  3. 自动拼出 raw.githubusercontent.com URL
  4. 拉取文件内容，带本地缓存
  5. 生成给 AI 的系统提示词（项目地图）
  6. 搜不到时生成反问话术，让 AI 问用户

零额外依赖：只用标准库 + requests（已有依赖）
"""

import re
import os
import json
import time
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional


# ──────────────────────────────────────────────
# 数据结构
# ──────────────────────────────────────────────

@dataclass
class RepoInfo:
    user: str
    repo: str
    branch: str = "main"

    @property
    def raw_base(self) -> str:
        return f"https://raw.githubusercontent.com/{self.user}/{self.repo}/{self.branch}"

    @property
    def web_base(self) -> str:
        return f"https://github.com/{self.user}/{self.repo}"


@dataclass
class FileNode:
    path: str
    url: str = ""
    content: str = ""
    size: int = 0
    fetched: bool = False
    error: str = ""


@dataclass
class ScoutResult:
    repo: str
    total_files: int
    fetched: int
    failed: int
    total_chars: int
    files: list = field(default_factory=list)
    errors: dict = field(default_factory=dict)


# ──────────────────────────────────────────────
# 常量
# ──────────────────────────────────────────────

REPO_URL_RE = re.compile(
    r'github\.com/([\w\-\.]+)/([\w\-\.]+?)(?:/tree/([\w\-\.]+))?(?:/|\b)'
)

# 内联路径匹配（非捕获组，findall 直接返回字符串）
FILE_PATH_RE = re.compile(
    r'(?:[\w\-\.]+(?:/[\w\-\.]+)*/)?[\w\-\.]+\.\w+'
)

CODE_EXTS = {
    'py', 'js', 'ts', 'tsx', 'jsx', 'java', 'kt', 'kts',
    'swift', 'go', 'rs', 'c', 'h', 'cpp', 'hpp', 'cs',
    'rb', 'php', 'scala', 'r', 'sql', 'sh', 'bash',
    'md', 'txt', 'json', 'yaml', 'yml', 'toml', 'cfg',
    'ini', 'xml', 'html', 'css', 'scss', 'less',
}

SPECIAL_FILES = {'.skill', 'dockerfile', 'makefile', 'license'}

# 分支字符（标记一个新的子项）
BRANCH_CHARS = set('├└┌┐┘')
# 所有树形字符
TREE_CHARS = set('├└│┌┐┘┬┤┴─├┴')


# ──────────────────────────────────────────────
# 目录树解析（核心函数）
# ──────────────────────────────────────────────

def parse_tree_to_paths(text: str) -> set:
    """
    把目录树文本解析成一组完整文件路径。

    输入示例：
        ├── Toolkit/
        │   ├── __init__.py
        │   ├── gateway.py
        │   └── skills/
        │       └── test.skill
        └── README.md

    算法：找每行"最后一个分支字符"的位置，
         该位置 // indent_unit = 深度。
    """
    results = set()
    lines = text.splitlines()

    # ── 第一遍：确定缩进单位 ──────────
    content_cols = []
    for line in lines:
        if not any(c in line for c in BRANCH_CHARS):
            continue
        for i, c in enumerate(line):
            if c == ' ':
                continue
            if c in TREE_CHARS:
                continue
            content_cols.append(i)
            break

    if not content_cols:
        return results

    nonzero = [c for c in content_cols if c > 0]
    indent_unit = min(nonzero) if nonzero else 4

    # ── 第二遍：解析路径 ────────────────
    stack = []

    for line in lines:
        if not any(c in line for c in BRANCH_CHARS):
            continue

        # 找最后一个分支字符的位置
        branch_pos = None
        for i, c in enumerate(line):
            if c in BRANCH_CHARS:
                branch_pos = i

        if branch_pos is None:
            continue

        # 提取名称：跳过分支字符后的所有树形符号和空格
        after = line[branch_pos + 1:]
        name_start = 0
        while name_start < len(after):
            c = after[name_start]
            if c == ' ' or c in TREE_CHARS:
                name_start += 1
            else:
                break

        name = after[name_start:].strip()
        # 去掉尾部注释
        name = name.split('#')[0].strip()

        if not name:
            continue
        # 跳过纯符号行
        if all(c in TREE_CHARS or c == ' ' for c in name):
            continue

        # 深度 = 分支字符位置 // 缩进单位
        depth = branch_pos // indent_unit

        is_dir = name.endswith('/')
        clean = name.rstrip('/')

        # 调整到正确深度
        if depth < len(stack):
            stack = stack[:depth]
        elif depth > len(stack):
            stack = stack[:len(stack)]

        stack.append(clean)

        # 只有文件才输出
        if not is_dir and '.' in clean:
            ext = clean.rsplit('.', 1)[-1].lower()
            if ext in CODE_EXTS or ('.' + ext) in SPECIAL_FILES:
                full = '/'.join(stack)
                results.add(full)
        # 无扩展名的特殊文件（LICENSE 等）
        elif not is_dir and clean.lower() in SPECIAL_FILES:
            full = '/'.join(stack)
            results.add(full)

    return results


# ──────────────────────────────────────────────
# 主类
# ──────────────────────────────────────────────

class GithubScout:
    """
    项目结构侦察兵

    用法：
        scout = GithubScout("https://github.com/user/repo")
        scout.parse_structure(readme_text)
        scout.fetch_all()
        prompt = scout.to_prompt()
    """

    def __init__(self, repo_url: str = "", branch: str = "main",
                 cache_dir: str = ".scout_cache"):
        # 允许无参构造（用于 load() 恢复场景）
        self.repo = RepoInfo(user="", repo="", branch=branch)
        if repo_url:
            m = REPO_URL_RE.search(repo_url)
            if not m:
                raise ValueError(f"不是有效的 GitHub 链接: {repo_url}")
            self.repo.user = m.group(1)
            self.repo.repo = m.group(2)
            self.repo.branch = m.group(3) or branch
            self.cache_dir = Path(cache_dir) / f"{self.repo.user}_{self.repo.repo}"
        else:
            self.cache_dir = Path(cache_dir) / "_default"
        self.files = {}
        self.parsed_sources = []
        self.fetched = False
        self.last_fetch_time = 0.0
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    # ── Step 1: 解析结构 ──────────────────

    def parse_structure(self, text: str, source: str = "unknown") -> list:
        """从文本中提取所有文件路径"""
        self.parsed_sources.append(source)
        found = set(self.files.keys())

        # 方法1: 内联路径
        for m in FILE_PATH_RE.findall(text):
            path = m
            ext = path.rsplit('.', 1)[-1].lower() if '.' in path else ''
            if ext in CODE_EXTS or ext in SPECIAL_FILES:
                found.add(path)

        # 方法2: 目录树
        tree_paths = parse_tree_to_paths(text)
        found.update(tree_paths)

        # 方法3: GitHub blob URL
        blob_re = re.compile(
            r'github\.com/[\w\-\.]+\/[\w\-\.]+\/blob\/[\w\-\.]+\/(.+)'
        )
        for m in blob_re.findall(text):
            found.add(m)

        # 构建 FileNode
        for path in sorted(found):
            if path not in self.files:
                self.files[path] = FileNode(
                    path=path,
                    url=f"{self.repo.raw_base}/{path}",
                )

        return sorted(found)

    def parse_multiple(self, texts: list) -> list:
        """批量解析对话历史"""
        all_found = set()
        for msg in texts:
            content = msg.get("content", "")
            role = msg.get("role", "unknown")
            found = self.parse_structure(content, source=f"conversation:{role}")
            all_found.update(found)
        return sorted(all_found)

    # ── Step 2: 拉取内容 ──────────────────

    def fetch_all(self, timeout: int = 15, use_cache: bool = True) -> ScoutResult:
        """逐个拉取所有文件，带缓存"""
        import requests

        fetched_count = 0
        failed_count = 0
        total_chars = 0
        errors = {}

        for path, node in self.files.items():
            cache_file = self.cache_dir / path.replace('/', '__')

            if use_cache and cache_file.exists():
                try:
                    content = cache_file.read_text(encoding='utf-8')
                    node.content = content
                    node.size = len(content)
                    node.fetched = True
                    fetched_count += 1
                    total_chars += node.size
                    continue
                except Exception:
                    pass

            try:
                resp = requests.get(
                    node.url, timeout=timeout,
                    headers={"User-Agent": "jinchen-scout/1.0"}
                )
                if resp.status_code == 200:
                    node.content = resp.text
                    node.size = len(resp.text)
                    node.fetched = True
                    node.error = ""
                    fetched_count += 1
                    total_chars += node.size
                    try:
                        cache_file.write_text(resp.text, encoding='utf-8')
                    except Exception:
                        pass
                else:
                    node.error = f"HTTP {resp.status_code}"
                    node.fetched = False
                    failed_count += 1
                    errors[path] = node.error
            except Exception as e:
                node.error = str(e)
                node.fetched = False
                failed_count += 1
                errors[path] = str(e)

            time.sleep(0.3)

        self.fetched = True
        self.last_fetch_time = time.time()

        return ScoutResult(
            repo=f"{self.repo.user}/{self.repo.repo}",
            total_files=len(self.files),
            fetched=fetched_count,
            failed=failed_count,
            total_chars=total_chars,
            files=sorted(self.files.keys()),
            errors=errors,
        )

    def fetch_one(self, path: str, timeout: int = 15) -> Optional[str]:
        """拉取单个文件"""
        import requests
        url = f"{self.repo.raw_base}/{path}"
        try:
            resp = requests.get(
                url, timeout=timeout,
                headers={"User-Agent": "jinchen-scout/1.0"}
            )
            return resp.text if resp.status_code == 200 else None
        except Exception:
            return None

    # ── Step 3: 生成 prompt ──────────────────

    def to_prompt(self, max_chars: int = 12000) -> str:
        """把所有文件内容压缩成 prompt 片段"""
        if not self.fetched:
            return "⚠️ 尚未拉取文件，请先调用 fetch_all()"

        py_files = {k: v for k, v in self.files.items() if k.endswith('.py')}
        md_files = {k: v for k, v in self.files.items() if k.endswith('.md')}
        other_files = {k: v for k, v in self.files.items()
                      if not k.endswith(('.py', '.md'))}

        parts = []
        parts.append(
            f"📂 仓库: {self.repo.user}/{self.repo.repo} "
            f"(branch: {self.repo.branch})"
        )
        parts.append(
            f"📊 文件总数: {len(self.files)} | "
            f"成功: {sum(1 for f in self.files.values() if f.fetched)}"
        )
        parts.append("")

        if py_files:
            parts.append("## 🐍 Python 源文件")
            for path, node in sorted(py_files.items()):
                if node.fetched and node.content:
                    parts.append(f"\n### `{path}` ({node.size} 字符)")
                    parts.append("```python")
                    content = node.content[:2000]
                    if len(node.content) > 2000:
                        content += f"\n# ... (截断，全文 {node.size} 字符)"
                    parts.append(content)
                    parts.append("```")

        if md_files:
            parts.append("\n## 📖 文档文件")
            for path, node in sorted(md_files.items()):
                if node.fetched and node.content:
                    lines = node.content.splitlines()[:30]
                    parts.append(f"\n### `{path}` (前30行)")
                    parts.append("```")
                    parts.append('\n'.join(lines))
                    parts.append("```")

        if other_files:
            parts.append("\n## 📁 其他文件")
            for path in sorted(other_files.keys()):
                node = self.files[path]
                if node.fetched:
                    parts.append(f"  - `{path}` ({node.size} 字符)")
                else:
                    parts.append(f"  - `{path}` ❌ {node.error}")

        result = '\n'.join(parts)
        if len(result) > max_chars:
            result = result[:max_chars] + f"\n\n... (截断于 {max_chars} 字符)"
        return result

    def build_system_context(self, max_files: int = 50) -> str:
        """生成精简版 system prompt 上下文"""
        if not self.files:
            return ""

        file_items = [
            f"  - `{p}`" for p in sorted(self.files.keys())[:max_files]
        ]
        file_list = '\n'.join(file_items)

        py_count = sum(1 for f in self.files if f.endswith('.py'))
        md_count = sum(1 for f in self.files if f.endswith('.md'))

        return f"""📂 项目结构（来自 GitHub: {self.repo.user}/{self.repo.repo}）

📊 概览: {len(self.files)} 个文件 ({py_count} Python + {md_count} 文档 + 其他)

已知文件列表：
{file_list}

⚠️ 规则：
1. 修改代码时，必须使用上述路径
2. 不要编造不在列表中的文件路径
3. 如需查看文件内容，请告诉我，我会提供
"""

    def build_followup_question(self) -> str:
        """
        搜不到文件时，生成反问话术。

        金呈原话：
        "AI 要是搜不到的话，可以反问一下用户，
         就是这些文件在哪个文件夹里面，
         或者说问那个文件格式是怎么样的就可以了。"
        """
        return '\n'.join([
            "我没有在你的仓库里找到具体的文件结构信息。能帮我确认一下：",
            "",
            "1️⃣ 你的项目文件放在哪个文件夹里？",
            "   （比如：src/、app/、lib/、tool/、Toolkit/ 等）",
            "",
            "2️⃣ 你能贴一下项目的目录结构吗？",
            "   （在终端运行 `tree -L 3` 或 `find . -type f | head -50`，把输出贴给我）",
            "",
            "3️⃣ 或者告诉我你最想让我看的那几个文件的完整路径？",
            "",
            f"📌 仓库地址我已知晓：{self.repo.web_base}",
            "拿到结构后我就能精确告诉你每个文件该怎么改。🫡",
        ])

    # ── Step 4: 智能查询 ──────────────────

    def find(self, keyword: str) -> list:
        """按关键词搜索文件名"""
        keyword = keyword.lower()
        return [p for p in sorted(self.files.keys()) if keyword in p.lower()]

    def get_related(self, target_path: str) -> list:
        """给定一个文件，返回可能相关的其他文件"""
        if target_path not in self.files:
            return []
        target = Path(target_path)
        return [
            p for p in sorted(self.files.keys())
            if p != target_path and (
                Path(p).parent == target.parent or
                Path(p).stem == target.stem
            )
        ]

    def find_by_ext(self, ext: str) -> list:
        """按扩展名搜索文件"""
        ext = ext.lower().lstrip('.')
        return sorted(p for p in self.files.keys() if p.lower().endswith('.' + ext))

    def ask_user(self, missing_path: str = "") -> str:
        """搜不到文件时的反问话术（对 build_followup_question 的薄包装）"""
        base = self.build_followup_question()
        if missing_path:
            base += f"\n\n🔎 我特别找不到这个：`{missing_path}`\n"
            base += "能告诉我它在你仓库的哪个文件夹里吗？"
        return base

    def get_imports(self, path: str) -> list:
        """解析 Python 文件的 import 列表（支持相对导入）

        相对导入如 `from .work import check` 会返回 "work"。
        """
        if path not in self.files or not self.files[path].fetched:
            return []
        imports = []
        rel_from_re = re.compile(r'^from\s+(\.+)([\w\.]+)\s+import')
        abs_from_re = re.compile(r'^from\s+([\w\.]+)\s+import')
        abs_import_re = re.compile(r'^import\s+([\w\.]+)')
        for line in self.files[path].content.splitlines():
            line = line.strip()
            # 相对导入：from .work import check → "work"
            m = rel_from_re.match(line)
            if m:
                module = m.group(2)  # 去掉 leading dots
                imports.append(module)
                continue
            m = abs_from_re.match(line)
            if m:
                imports.append(m.group(1))
                continue
            m = abs_import_re.match(line)
            if m:
                imports.append(m.group(1))
        return imports

    # ── Step 5: 序列化 ──────────────────

    # ── 简写别名（方便脚本和测试调用）──
    def save(self, path: str = "scout_state.json"):
        return self.save_state(path)

    def load(self, path: str = "scout_state.json") -> bool:
        return self.load_state(path)

    def stats(self) -> dict:
        fc = sum(1 for f in self.files.values() if f.fetched)
        return {
            "total": len(self.files),
            "fetched": fc,
            "pending": len(self.files) - fc,
            "total_chars": sum(f.size for f in self.files.values()),
        }

    def has_any(self) -> bool:
        return len(self.files) > 0

    def save_state(self, path: str = "scout_state.json"):
        state = {
            "repo": {
                "user": self.repo.user,
                "repo": self.repo.repo,
                "branch": self.repo.branch,
            },
            "files": {
                p: {"url": n.url, "size": n.size,
                     "fetched": n.fetched, "error": n.error}
                for p, n in self.files.items()
            },
            "parsed_sources": self.parsed_sources,
            "last_fetch_time": self.last_fetch_time,
        }
        Path(path).write_text(
            json.dumps(state, indent=2, ensure_ascii=False),
            encoding='utf-8'
        )

    def load_state(self, path: str = "scout_state.json") -> bool:
        try:
            state = json.loads(Path(path).read_text(encoding='utf-8'))
            self.repo.user = state["repo"]["user"]
            self.repo.repo = state["repo"]["repo"]
            self.repo.branch = state["repo"].get("branch", "main")
            self.parsed_sources = state.get("parsed_sources", [])
            self.last_fetch_time = state.get("last_fetch_time", 0)
            for ps, info in state.get("files", {}).items():
                self.files[ps] = FileNode(
                    path=ps,
                    url=info.get("url", ""),
                    size=info.get("size", 0),
                    fetched=info.get("fetched", False),
                    error=info.get("error", ""),
                )
            return True
        except Exception as e:
            print(f"⚠️ 加载状态失败: {e}")
            return False

    # ── Step 6: 工厂方法 ──────────────────

    @classmethod
    def from_conversation(cls, repo_url: str, messages: list,
                         branch: str = "main"):
        scout = cls(repo_url, branch)
        scout.parse_multiple(messages)
        return scout

    def __repr__(self) -> str:
        status = "已拉取" if self.fetched else "未拉取"
        fc = sum(1 for f in self.files.values() if f.fetched)
        return (f"GithubScout(repo={self.repo.user}/{self.repo.repo}, "
                f"files={len(self.files)}, fetched={fc}, status={status})")


# ──────────────────────────────────────────────
# 便捷函数
# ──────────────────────────────────────────────

def quick_scan(repo_url: str, conversation: list = None,
               text: str = "", branch: str = "main") -> str:
    """一键扫描：链接 + 对话 → prompt 或反问话术"""
    scout = GithubScout(repo_url, branch)
    if conversation:
        scout.parse_multiple(conversation)
    if text:
        scout.parse_structure(text, source="direct")
    if not scout.files:
        return scout.build_followup_question()
    result = scout.fetch_all()
    if result.fetched == 0:
        # 文件识别到了，但拉不下来（网络/权限）→ 给文件列表 + 反问
        listing = scout.build_system_context()
        followup = scout.build_followup_question()
        return listing + "\n\n" + followup
    return scout.to_prompt()


def build_context_for_ai(repo_url: str, conversation: list = None,
                         branch: str = "main") -> str:
    """轻量版：只构建文件列表上下文"""
    scout = GithubScout(repo_url, branch)
    if conversation:
        scout.parse_multiple(conversation)
    if not scout.files:
        return scout.build_followup_question()
    return scout.build_system_context()


# ──────────────────────────────────────────────
# CLI 入口
# ──────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("用法: python github_scout.py <github_repo_url> [branch]")
        sys.exit(1)

    url = sys.argv[1]
    branch = sys.argv[2] if len(sys.argv) > 2 else "main"

    scout = GithubScout(url, branch)

    print(f"🔍 解析仓库: {scout.repo.user}/{scout.repo.repo} ({scout.repo.branch})")
    print(f"🔗 Raw base: {scout.repo.raw_base}")
    print()

    if len(sys.argv) > 3:
        conv_file = sys.argv[3]
        try:
            with open(conv_file, 'r') as f:
                conversation = json.load(f)
            found = scout.parse_multiple(conversation)
            print(f"📋 从对话历史提取到 {len(found)} 个文件")
        except Exception as e:
            print(f"⚠️ 读取对话文件失败: {e}")

    if not scout.files:
        print()
        print(scout.build_followup_question())
    else:
        print(f"📋 共 {len(scout.files)} 个文件:")
        for f in sorted(scout.files.keys()):
            print(f"  📄 {f}")

        print()
        print("📥 开始拉取...")
        result = scout.fetch_all()
        print(f"  ✅ 成功: {result.fetched}")
        print(f"  ❌ 失败: {result.failed}")
        print(f"  📊 总字符: {result.total_chars}")

        if result.errors:
            print()
            print("⚠️ 失败详情:")
            for fp, err in result.errors.items():
                print(f"  {fp}: {err}")

        print()
        print("=" * 60)
        print(scout.to_prompt())
