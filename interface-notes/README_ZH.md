<p align="center">
  <img src="docs/badges/python.svg" alt="Python 3.10+">
  <img src="docs/badges/license.svg" alt="MIT License">
  <img src="docs/badges/status.svg" alt="Active">
</p>

<h1 align="center">Interface Notes</h1>

<p align="center">
  <b>AI 驱动的代码接口文档工具 —— 扫描、打印、手写、OCR 回流。</b>
</p>

---

## 这是什么？

**Interface Notes** 是一个 CLI 工具，通过"人在回路"的工作流，帮助团队理解并记录代码库中的接口（函数 / 方法）：

| 阶段 | 谁主导 | 做什么 |
|------|---------|---------|
| 1 | **AI 扫描** | 识别公开接口、参数、返回值类型、IO 风险、调用关系 |
| 2 | **AI 导出** | 生成带手写区的 Markdown 文档（为 A4 打印优化） |
| 3 | **你打印 → 手写** | 把批注、警告、踩坑直接写在纸上 —— 零切换 |
| 4 | **OCR 回流** | 拍照 → 运行工具 → 手写内容合并进数字文档，风险等级自动升级 |

最终产物不是一份静态文档，而是一本**会生长的团队大脑**，游走于代码、纸张和 AI 之间。

---

## 两种模式

| 模式 | 场景 | Token 开销 | 精准度 |
|------|------|-----------|--------|
| **模式 A — 共同开发** | 新项目 / 正在活跃开发 | 低（增量记录） | 高（实时确认） |
| **模式 B — 接手旧项目** | 屎山代码 / 前任跑路 / 新人入职 | 高（一次性全量通读） | 中→高（人工修正后） |

---

## 四阶段生命周期

| 阶段 | 谁主导 | 核心动作 | 产出物 |
|--------|---------|---------|--------|
| 1 | AI | 识别接口 → 询问 → 记录 | `Session`（JSON） |
| 2 | AI + 你 | 复盘 → 导出 .md → 自动画图 | `INTERFACE_NOTES.md` |
| 3 | 你 | 打印 → 手写批注 → 拍照 → OCR 回流 | 手写内容合入笔记 |
| 4 | 你 + AI | 新人读笔记 → 新 Session 导入 → AI 秒回状态 | 团队知识沉淀 |

---

## 快速开始

### 安装

```bash
# 核心（仅依赖标准库，无强制第三方依赖）
pip install -r requirements.txt

# 可选：启用真实 OCR（需安装 tesseract 二进制及语言包）
pip install pytesseract pillow
# Ubuntu:  sudo apt-get install tesseract-ocr tesseract-ocr-chi-sim
# macOS:    brew install tesseract tesseract-lang
```

### 模式 B — 接手旧项目

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

### 模式 A — 共同开发（增量记录）

```bash
python -m interface_notes mode-a \
  --project "新项目" \
  --path ./src
```

### 其他命令

```bash
python -m interface_notes show           # 查看会话状态
python -m interface_notes add --name my_func --description "我的函数" --location "src/main.py"
python -m interface_notes diagram       # 只输出 Mermaid 图
python -m interface_notes export --format json --output notes.json
python -m interface_notes test         # 运行全部测试
```

---

## 支持的语言

| 语言 | 状态 | 识别能力 |
|------|:----:|---------|
| Python (.py) | ✅ | 函数签名、类型注解、IO 检测、调用图 |
| JavaScript (.js/.jsx) | ✅ | 函数声明/表达式、参数、IO 检测 |
| TypeScript (.ts/.tsx) | ✅ | 同上 + 类型注解 |
| Java (.java) | ✅ | public 方法、Javadoc、参数类型 |
| Go / Rust | 🔜 | 规划中 |

---

## 项目结构

```
interface-notes/
├── README.md                # 默认入口（中英文双语）
├── README_EN.md             # 纯英文版
├── README_ZH.md             # 本文件（纯中文版）
├── LICENSE
├── .gitignore
├── requirements.txt
├── REPOSITORY_DESCRIPTION.txt
├── .github/
│   ├── workflows/tests.yml
│   ├── ISSUE_TEMPLATE/
│   └── pull_request_template.md
├── interface_notes/         # 主包
│   ├── __main__.py
│   ├── cli.py
│   ├── core/
│   ├── analyzer/
│   ├── exporter/
│   └── ocr/
├── prompts/                 # AI Prompt 模板
├── examples/                # 示例输出
└── tests/                   # 测试套件（36 用例，全通过）
```

---

## 设计原则

| 原则 | 说明 |
|------|------|
| **AI 记骨架，人填血肉** | AI 记客观事实，人加主观经验，互不干扰 |
| **不烦人** | 每个接口只问一次，不确定就沉默 |
| **为打印而生** | 导出格式为 A4 纸优化，不是为屏幕阅读 |
| **回路闭合** | 手写 → 拍照 → OCR → 回流 → 升级版导出 |
| **跨会话持久** | 笔记导出为文件，新 Session 可导入 |
| **渐进增强** | v1 记录 + 导出；v2 加图；v3 加 OCR |

---

## 路线图

- [x] v1 — 模式 A：增量识别 + 询问 + 记录 + 导出 .md
- [x] v1b — 模式 B：全量扫描 + 免责声明 + 导出 .md
- [x] v2 — 自动生成 Mermaid 接口调用关系图
- [x] v3 — OCR 拍照回流 + 风险等级自动升级
- [x] 跨文件同名函数消歧（qualified_name + import 感知）
- [x] OCR 依赖可选化（不装 pytesseract 也能跑）
- [x] `max_files` 截断警告
- [ ] v4 — 多项目合并 → 个人技术词典
- [ ] v5 — IDE 插件（像 Copilot 一样弹窗询问）

---

## GitHub Topics 推荐

仓库 Settings → Topics 添加以下标签：

`ai` `documentation` `code-analysis` `static-analysis` `cli-tool` `mermaid` `ocr` `developer-tools` `python` `codebase-visualization`

---

## 贡献

欢迎提交 Issue 和 PR。提交前请先运行 `python -m interface_notes test`。

---

## 协议

MIT License — 详见 [LICENSE](LICENSE)。

---

<p align="center">
  为相信"纸笔力量"的团队而作 ❤️
</p>
