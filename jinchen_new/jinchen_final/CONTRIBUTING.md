# 🤝 贡献指南

感谢你考虑为「Word 体系」做贡献！这个项目是作者业余时间的实验性工具集，
**欢迎任何形式的帮助**——代码、文档、数据集、Issue 反馈都可以。

---

## 🚀 快速上手

1. Fork 本仓库
2. `git clone your-fork-url`
3. `cd jinchen && pip install -r requirements.txt`
4. `python verify.py` → 看到 83/83 通过就说明环境 OK

---

## 📋 我能贡献什么？

### 🔴 高优先级（作者搞不定的）

| 需求 | 说明 | 怎么贡献 |
|------|------|---------|
| **标注数据集** | 100+ 条 Python 代码 + 已知违规标记 | 准备 JSON 文件，提交到 `examples/datasets/` |
| **tree-sitter 绑定** | Java/Kotlin 的 Python 绑定在 Windows/ARM 上编译失败 | 提 PR 或写 Issue 说明你的环境怎么装的 |
| **真实项目扫描结果** | 在真实项目上跑 `verify_real.py` 的结果 | 提交 JSON 报告，标注误报/漏报 |

### 🟡 中优先级

| 需求 | 说明 |
|------|------|
| 新 Skill 文件 | 在 `Toolkit/skills/` 下新增 `.skill` 文件 |
| 新检测规则 | 给 `InstinctGuard` 加 AST 检测函数 |
| 文档改进 | README / CHANGELOG 写得不清楚的地方 |
| Bug 报告 | 任何你觉得"这不对劲"的地方，开 Issue |

### 🟢 低优先级

| 需求 | 说明 |
|------|------|
| Star 本项目 | 最简单的方式，让更多人看到 |
| 写使用体验 | 在 Discussions 里分享你怎么用的 |
| 翻译 README | 英文版目前没有 |

---

## 📊 数据集格式

`evaluate.py` 需要以下 JSON 格式：

```json
[
  {
    "code": "def add(a, b):\n    return a + b\n",
    "expected_violations": ["type_hints"],
    "filename": "test_add.py",
    "notes": "简单函数缺少类型注解"
  },
  {
    "code": "key = 'sk-1234567890abcdef'\ndef f(): pass\n",
    "expected_violations": ["no_hardcoded_secrets", "no_unused_import"],
    "filename": "test_secret.py",
    "notes": "硬编码密钥 + json 导入未使用"
  }
]
```

提交方式：
1. 在 `examples/datasets/` 下创建 `your_name_dataset.json`
2. 至少 20 条样本（越多越好）
3. 开 PR

---

## 🧪 代码贡献流程

1. 创建分支：`git checkout -b fix/my-fix`
2. 改代码，**务必跑通 `python verify.py`**
3. 如果加了新功能，加对应的 verify 用例
4. 提交：`git commit -m "fix: 修复 xxx 问题"`
5. 推到你的 Fork，开 Pull Request

### 代码规范

- Python 3.10+ 语法（用 `list[str]` 不用 `List[str]`）
- 函数加 docstring（一行也行）
- 不要引入重依赖（保持 `requests` 为核心唯一硬依赖）
- 所有检测函数统一签名：`def _detect_xxx(self, code: str) -> GuardResult`

---

## 💬 不会写代码也能帮忙

- **开 Issue**：遇到 bug、觉得哪里难用、有想法想聊 → 直接开 Issue
- **真实项目测试**：在你的项目上跑 `verify_real.py`，把结果贴到 Discussions
- **帮我涨 star**：点一下 star 按钮，让更多人看到这个项目

---

## ⚠️ 作者坦白

这个项目目前只有 1 个 star、1 个 contributor（就是我）。
代码质量还有很大提升空间，文档可能不完整，有些功能就是个壳。

**但这正是你需要贡献的原因**——它不会因为你提交了一个 PR 就变得更烂，
只会因为你的参与变得更好。

---

**让 AI 守规矩，需要更多人一起。🛡️**
