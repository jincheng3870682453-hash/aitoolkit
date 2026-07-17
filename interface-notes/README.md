<p align="center">
  <img src="docs/badges/python.svg" alt="Python 3.10+">
  <img src="docs/badges/license.svg" alt="MIT License">
  <img src="docs/badges/status.svg" alt="Active">
</p>

<h1 align="center">Interface Notes</h1>

<p align="center">
  <b>AI-powered interface documentation tool — scan, print, handwrite, OCR back.</b><br/>
  <b>AI 驱动的代码接口文档工具 —— 扫描、打印、手写、OCR 回流。</b>
</p>

<p align="center">
  <a href="README_EN.md"><img src="docs/badges/lang-en.svg" alt="English"></a>
  &nbsp;|&nbsp;
  <a href="README_ZH.md"><img src="docs/badges/lang-zh.svg" alt="中文"></a>
</p>

---

## 🇬🇧 English

### What is this?

**Interface Notes** is a CLI tool that helps teams understand and document a codebase's interfaces (functions / methods) through a human-in-the-loop workflow:

| # | Step | What happens |
|---|------|-------------|
| 1 | **AI scans** | Identifies public interfaces, parameters, return types, IO risks, and call relationships |
| 2 | **AI exports** | A clean Markdown doc with built-in handwriting zones (optimized for A4 printing) |
| 3 | **You print → handwrite** | Notes, warnings, pitfalls go directly on paper — zero tab-switching |
| 4 | **OCR flows back** | Photograph your notes, run the tool, and handwritten context merges into the digital doc with risk levels auto-upgraded |

The result is not a static doc — it's a **growing team brain** that lives between code, paper, and AI.

### Two Modes

| Mode | Scenario | Token Cost | Precision |
|------|-----------|-------------|-----------|
| **Mode A — Co-develop** | New project / active development | Low (incremental) | High (real-time confirmation) |
| **Mode B — Inherit** | Legacy code / previous dev left / onboarding | High (one-shot full scan) | Medium → High (after human correction) |

### Quick Start

```bash
# Install (stdlib only — no mandatory third-party deps)
pip install -r requirements.txt

# Optional: enable real OCR (requires tesseract binary + lang packs)
pip install pytesseract pillow
# Ubuntu:  sudo apt-get install tesseract-ocr tesseract-ocr-chi-sim
# macOS:    brew install tesseract tesseract-lang
```

**Mode B — Inherit a legacy project:**

```bash
# 1. Full scan + auto-export v1
python -m interface_notes mode-b \
  --project "LegacyProject" \
  --path ./legacy_code \
  --auto-export \
  --output INTERFACE_NOTES_v1.md

# 2. Print v1 → handwrite → photograph → OCR merge → v2
python -m interface_notes ocr-merge \
  --image handwritten_notes.jpg \
  --author "Alice" \
  --output INTERFACE_NOTES_v2.md
```

**Mode A — Co-develop (incremental):**

```bash
python -m interface_notes mode-a \
  --project "NewProject" \
  --path ./src
```

### Supported Languages

| Language | Status | Extracts |
|----------|:------:|----------|
| Python (.py) | ✅ | Signature, type hints, IO detection, call graph |
| JavaScript (.js/.jsx) | ✅ | Function decl/expr, params, IO detection |
| TypeScript (.ts/.tsx) | ✅ | Above + type annotations |
| Java (.java) | ✅ | Public methods, Javadoc, param types |
| Go / Rust | 🔜 | Planned |

### Design Principles

| Principle | Explanation |
|-----------|-------------|
| **AI → skeleton, Human → flesh** | AI records objective facts; humans add subjective experience |
| **Don't annoy** | Each interface is asked at most once; silence on uncertainty |
| **Print-friendly** | Exports optimized for A4 paper, not screen reading |
| **Closed loop** | Handwrite → photo → OCR → merged → upgraded export |
| **Cross-session** | Notes export as files; new Sessions can import them |

### Roadmap

- [x] v1 — Mode A: incremental identify + ask + record + export .md
- [x] v1b — Mode B: full scan + disclaimer + export .md
- [x] v2 — Auto-generate Mermaid interface call graphs
- [x] v3 — OCR photo merge + auto risk-level upgrade
- [x] Cross-file same-name disambiguation (qualified_name + import-aware)
- [x] Optional OCR deps (works without pytesseract)
- [x] `max_files` truncation warning
- [ ] v4 — Multi-project merge → personal tech dictionary
- [ ] v5 — IDE plugin (pop-up like Copilot)

### Contributing & License

Issues and PRs welcome. Please run `python -m interface_notes test` before submitting.
MIT License — see [LICENSE](LICENSE) for details.

---

## 🇨🇳 中文说明

### 这是什么？

**Interface Notes** 是一个 CLI 工具，通过"人在回路"的工作流，帮助团队理解并记录代码库中的接口（函数 / 方法）：

| 阶段 | 谁主导 | 做什么 |
|------|---------|---------|
| 1 | **AI 扫描** | 识别公开接口、参数、返回值类型、IO 风险、调用关系 |
| 2 | **AI 导出** | 生成带手写区的 Markdown 文档（为 A4 打印优化） |
| 3 | **你打印 → 手写** | 把批注、警告、踩坑直接写在纸上 —— 零切换 |
| 4 | **OCR 回流** | 拍照 → 运行工具 → 手写内容合并进数字文档，风险等级自动升级 |

最终产物不是一份静态文档，而是一本**会生长的团队大脑**，游走于代码、纸张和 AI 之间。

### 两种模式

| 模式 | 场景 | Token 开销 | 精准度 |
|------|------|-----------|--------|
| **模式 A — 共同开发** | 新项目 / 正在活跃开发 | 低（增量记录） | 高（实时确认） |
| **模式 B — 接手旧项目** | 屎山代码 / 前任跑路 / 新人入职 | 高（一次性全量通读） | 中→高（人工修正后） |

### 快速开始

```bash
# 安装（核心仅依赖标准库）
pip install -r requirements.txt

# 可选：启用真实 OCR（需安装 tesseract 二进制及语言包）
pip install pytesseract pillow
# Ubuntu:  sudo apt-get install tesseract-ocr tesseract-ocr-chi-sim
# macOS:    brew install tesseract tesseract-lang
```

**模式 B — 接手旧项目：**

```bash
# 1. 全量扫描 + 自动导出 v1
python -m interface_notes mode-b \
  --project "旧项目" \
  --path ./legacy_code \
  --auto-export \
  --output INTERFACE_NOTES_v1.md

# 2. 打印 v1 → 手写批注 → 拍照 → OCR 回流 → v2
python -m interface_notes ocr-merge \
  --image handwritten_notes.jpg \
  --author "张三" \
  --output INTERFACE_NOTES_v2.md
```

**模式 A — 共同开发（增量记录）：**

```bash
python -m interface_notes mode-a \
  --project "新项目" \
  --path ./src
```

### 支持的语言

| 语言 | 状态 | 识别能力 |
|------|:----:|---------|
| Python (.py) | ✅ | 函数签名、类型注解、IO 检测、调用图 |
| JavaScript (.js/.jsx) | ✅ | 函数声明/表达式、参数、IO 检测 |
| TypeScript (.ts/.tsx) | ✅ | 同上 + 类型注解 |
| Java (.java) | ✅ | public 方法、Javadoc、参数类型 |
| Go / Rust | 🔜 | 规划中 |

### 设计原则

| 原则 | 说明 |
|------|------|
| **AI 记骨架，人填血肉** | AI 记客观事实，人加主观经验，互不干扰 |
| **不烦人** | 每个接口只问一次，不确定就沉默 |
| **为打印而生** | 导出格式为 A4 纸优化，不是为屏幕阅读 |
| **回路闭合** | 手写 → 拍照 → OCR → 回流 → 升级版导出 |
| **跨会话持久** | 笔记导出为文件，新 Session 可导入 |

### 路线图

- [x] v1 — 模式 A：增量识别 + 询问 + 记录 + 导出 .md
- [x] v1b — 模式 B：全量扫描 + 免责声明 + 导出 .md
- [x] v2 — 自动生成 Mermaid 接口调用关系图
- [x] v3 — OCR 拍照回流 + 风险等级自动升级
- [x] 跨文件同名函数消歧（qualified_name + import 感知）
- [x] OCR 依赖可选化（不装 pytesseract 也能跑）
- [x] `max_files` 截断警告
- [ ] v4 — 多项目合并 → 个人技术词典
- [ ] v5 — IDE 插件（像 Copilot 一样弹窗询问）

### 贡献与协议

欢迎提交 Issue 和 PR。提交前请先运行 `python -m interface_notes test`。
MIT 协议 — 详见 [LICENSE](LICENSE)。

---

<p align="center">
  Made with ❤️ for teams who still believe in the power of paper + pen.<br/>
  为相信"纸笔力量"的团队而作 ❤️
</p>
