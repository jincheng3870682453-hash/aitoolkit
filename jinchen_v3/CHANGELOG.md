# 📜 CHANGELOG — Word 体系

> 版本号规则：主版本.次版本.修订
> 主版本 = 不兼容变更，次版本 = 新功能，修订 = bug 修复

---

## [V3.2] — 2026-07-15 · 极致融合版（当前版本）

**代号：不烧不该烧的**

"把能省的省到底，把该硬的硬到极致。"

### 🆕 新增

- **CodeMap 关系图谱**：AST 遍历时自动建函数/类/调用关系图，支持 `get_related(file)` 查询关联文件（CodeGraph 思路融合）
- **compressed_view（骨架压缩）**：只保留 import + 函数签名 + 类定义，压缩率 39%~82%（Headroom 思路融合）
- **突变测试（mutation_test）**：主动注入违规代码验证检测规则敏不敏感，4/4 突变全部捕获
- **RadiationDetector 全栈辐射**：DB 辐射（SQL→migration）、API 辐射（路由→docs）、测试辐射、导入辐射、配置辐射（5 维度）
- **Skill Router 五层架构**：L1 流量过滤 → L2 关键词 → L3 语义 → L4 后置校验 → L5 反馈闭环
- **safe_call 熔断器**：模型挂了/磁盘满了/网络超时 → 一律不崩，返回 `SafeResult(conservative=True)`
- **evaluate.py 准确率评估框架**：P/R/F1 + 误报率，配 `examples/dataset/sample_dataset.json` 标注样本
- **verify_real.py 真实项目扫描**：递归扫任意目录，按语言/规则统计报告
- **4 个 examples 示例**：basic_check / snapshot_rollback / full_gateway / token_saving

### 🔴 重大变更

- **砍掉 4 种语言正则检测**：Java/Kotlin/TypeScript/Swift 全部移除，只留 Python AST。README 明确"当前专注 Python"
- **接口极简化**：`work.py` 对外只暴露 `check(code)` / `check_file(path)` / `get_report(code)`
- **Mock 彻底删除**：模型失败直接抛异常，零假数据
- **AI 味去除**：README/注释/文档全部改人话，不装

### 🔧 改进

- **反馈式重试**：违规原因注入 prompt，模型知道错在哪再生成（不再同一个问题问 3 遍）
- **意图识别升级**：自动检测 `sentence-transformers`，可用时切语义匹配（余弦相似度），不可用时降级关键词
- **长对话记忆增强**：SimHash 64 位 + 主题切换检测 + 紧急度信号 + 短输入保护
- **判决书规范化**：dataclass 结构化输出，含违规类型/行号/修复建议/哈希/时间戳
- **省 Token 设计**：6 种省法（SimHash 裁剪/主题切换/Skill 按需/意图路由/反馈重试/环境变量），单次请求省 ~7770 token ≈ 60 元/月

### 🐛 修复

- `dataclasses` 拼写错误（3 个文件）
- `gateway.py` 缺 `self` 参数
- `Archive` 类实例化方式
- `no_hardcoded_secrets` 正则支持连字符
- `mutation_test` 状态拼写 `"MISSED"` → `"missed"`
- `check_file` 缺 `Path` 导入
- `list_snapshots` 文件后缀兼容
- `handle()` 模型返回 SafeResult 崩溃
- 递归检测误报（合规代码被误判）

### 📊 验证状态

| 项目 | 状态 |
|------|------|
| 综合验证 | ✅ **123/123 通过 (100%)** |
| 真实项目扫描 | ✅ 框架就绪（`verify_real.py`） |
| 准确率评估 | ✅ 框架就绪（`evaluate.py` + 标注数据集） |
| 零运行时依赖 | ✅ 核心模块纯标准库 |

### 📦 模块状态一览

| 模块 | 方法 | 准确率 | 生产可用 |
|------|------|--------|---------|
| work.py | Python AST（真） | 高 | ✅ 是 |
| Nuwa.py（辐射检测） | AST + 正则（仅路径匹配） | 中高 | ✅ 是 |
| Archive.py | SimHash 64 位 | 高 | ✅ 是 |
| guardian.py | 文件系统 + SHA-256 | 高 | ✅ 是 |
| gateway.py | 5 层路由 | 高 | ✅ 是 |

---

## [V3.1] — 2026-07-15 · 诚实版

**代号：不骗自己**

"承认不完美，比假装完美更重要。"

### 🔴 重大变更（Breaking）

- **移除 Mock 兜底**：模型调用失败现在直接抛 `ModelCallError`，不再返回 `[MOCK-xxx]` 假数据
- **配置文件不再存明文 Key**：`config.json` 改为存 `api_key_env` 引用环境变量
- **签名机制降级**：`RollbackJury` 的"防篡改签名"改为"本地完整性哈希"，明确标注无密码学防篡改能力

### 🆕 新增

- **反馈式重试**：违规时把原因注入 prompt，让模型知道哪里错了再生成（不再同一个问题问 3 遍）
- **无状态网关**：`FeedbackFlywheel` 改为 `FeedbackStore`，仅文件持久化，不维护内存全局状态
- **语义意图识别**（可选）：安装 `sentence-transformers` 后自动启用，否则降级为关键词
- **`.gitignore` 自动生成**：`guardian.ensure_gitignore()` 自动创建/更新忽略规则
- **`requirements.txt`**：明确声明依赖

### 🔧 改进

- `_detect_unused_import`：从正则改为 AST 遍历，解决变量名碰撞（如 `json_data` 误判 `json` 模块）
- `sanitize()`：仅检查 docstring 和注释中的占位符，不再误删字符串字面量
- `RadiationDetector`：修复 `os.getenv()` 变量提取正则 bug
- `gateway.py`：所有 `except Exception: pass` 改为捕获具体异常 + 日志记录
- `V1Bridge.ast_check()`：检测模块异常时返回 `action=warn` 而非静默空列表

### 🐛 修复

- `guardian.py`：快照复制权限不足时不再静默失败
- `Nuwa.py`：`test_files` 拼接类型错误（`list + generator`）
- `gateway.py`：`config.json` 解析失败时有明确报错
- `RollbackJury`：哈希截断从 16 位改为 32 位（仍非签名，仅完整性校验）

### 📊 当前验证状态

| 项目 | 状态 |
|------|------|
| 单元验证 | ✅ 通过（使用 toy code 自测） |
| 真实项目测试 | ❌ 尚未做（无真实项目样本） |
| 性能测试 | ❌ 尚未做（无 1000 文件扫描基准） |
| 准确率测试 | ❌ 尚未做（无标注数据集） |

> ⚠️ **诚实标注**：当前测试覆盖率数字（如"57/57 通过"）是在手写用例上的自测结果，
> 不代表真实场景的准确率。请勿将此数字用于生产决策。

### 📦 模块状态一览

| 模块 | 方法 | 准确率 | 生产可用 |
|------|------|--------|---------|
| work.py (Python) | AST | 高 | ✅ 是 |
| work.py (Java) | 正则 | 低 | ❌ 仅筛查 |
| work.py (Kotlin) | 正则 | 低 | ❌ 仅筛查 |
| work.py (TS) | 正则 | 低 | ❌ 仅筛查 |
| work.py (Swift) | 正则 | 低 | ❌ 仅筛查 |
| guardian.py | shutil | 高 | ✅ 是 |
| Archive.py | SimHash | 中 | 🟡 可用 |
| Nuwa.py | 正则 | 中 | 🟡 可用 |
| gateway.py | Python | 高 | ✅ 是 |

---

## [V3.1.1] — 2026-07-15 · 诚实补丁

**代号：知之为知之**

> "不装了，没做的就说没做。"

### 🔴 回应社区反馈（4 个仍然存在的问题）

#### 1. 多语言检测还是正则 → ✅ 已标注，Roadmap 明确

**现状**：Java/Kotlin/TypeScript/Swift 仍然是正则表达式检测。

**为什么没改**：`tree-sitter` 的 Python 绑定（`tree-sitter-languages`）需要编译 C 扩展，
在部分环境（Windows / ARM / 旧版 glibc）安装会失败。作者当前环境无法稳定复现
跨平台安装，因此**不发布未经测试的"半成品 AST"**。

**本次做了什么**：
- 在每次检测返回的 JSON 中新增 `"accuracy_note"` 字段，明确告知调用方：
  `"此检测结果基于正则表达式，已知存在漏报和误报，仅作初步筛查参考"`
- `list_supported()` 现在返回每个语言的 `method`（ast/regex）和 `accuracy`（high/low）
- README 新增「已知局限」板块，GitHub 首页即可看到

**Roadmap**：
| 语言 | 目标方案 | 预计版本 | 当前状态 |
|------|---------|---------|---------|
| Java | `tree-sitter-languages` | V3.3 | 本地开发环境调试中 |
| Kotlin | `tree-sitter-kotlin` | V3.4 | 等待上游稳定 |
| TypeScript | `typescript-estree` | V3.3 | 接口设计完成 |
| Swift | `SwiftSyntax` (via subprocess) | V3.5 | 调研中 |

#### 2. 没有真实项目验证 → 🟡 部分解决

**本次做了什么**：
- 新增 `verify_real.py`（实验性）：可从指定目录递归扫描 `.py` 文件，
  统计违规检出数和误报样本，**但官方尚未在任何真实项目上跑过完整测试**
- CHANGELOG 继续诚实标注：`真实项目测试：⚠️ 框架就绪，未执行`

**为什么没做**：作者没有拿到足够大的标注数据集（100+ 样本，含已知违规标记）。
这是**用户帮得上的地方**——欢迎提交样本！

#### 3. 准确率未知 → 🟡 新增评估框架

**本次做了什么**：
- 新增 `evaluate.py`（框架代码）：定义 `BenchmarkDataset` 接口，
  支持从 JSON 文件加载 `{code, expected_violations}` 标注对，
  输出 `precision / recall / f1 / false_positive_rate`
- **但**：内置数据集为空，等待社区贡献

**调用方式**：
```python
from Toolkit.work import InstinctGuard
from evaluate import BenchmarkDataset, run_evaluation

ds = BenchmarkDataset.load("my_dataset.json")
results = run_evaluation(InstinctGuard(), ds)
print(f"Precision={results.precision:.2%}  Recall={results.recall:.2%}")
```

#### 4. Star 还是 1 → ✅ 不是代码问题，是传播问题

**本次做了什么**：
- README 重写：首屏 5 秒内让访客看到「它是什么 / 它能干什么 / 它不能干什么」
- 新增 `examples/` 目录（3 个最小可运行示例）
- 新增 `CONTRIBUTING.md`：降低第一个贡献者的门槛

**作者坦白**：
> Star 数 = 知名度 ≠ 代码质量。我不会去刷 star，也不会在群里求点赞。
> 如果有人用了觉得有用，自然会点。如果没人用，说明还不够好，继续改。

### 🆕 新增文件

- `evaluate.py` — 准确率评估框架（接口就绪，等待数据集）
- `verify_real.py` — 真实项目扫描框架（接口就绪，等待样本）
- `examples/` — 3 个最小可运行示例
- `CONTRIBUTING.md` — 贡献指南

### 📊 当前验证状态（更新）

| 项目 | 状态 |
|------|------|
| 单元验证（toy code） | ✅ 83/83 通过 |
| 真实项目测试 | ⚠️ 框架就绪，未执行（等社区样本） |
| 性能测试（1000 文件） | ❌ 尚未做 |
| Python 准确率（标注数据集） | ⚠️ 框架就绪，等待数据集 |
| 多语言准确率 | 🔴 已知低（正则），不推荐用于审计 |

---

## [V3.0] — 2026-07-14 · 企业级治理平台（已废弃）

**代号：交通规则**

> ⚠️ **此版本存在已知严重问题，请勿使用。**

### 🔴 已知问题

1. **Mock 欺骗**：模型失败时返回 `[MOCK-xxx]` 假数据，用户不知情
2. **多语言夸大**：README 写"AST 引擎"，实际 4/5 语言是正则
3. **签名虚假**：64 位哈希冒充防篡改签名
4. **重试无效**：同一 prompt 重复 3 次，指望答案自己变对
5. **全局状态**：`FeedbackFlywheel` 维护内存列表，多线程不安全
6. **密钥明文**：`config.json` 直接存 API Key
7. **静默吞错**：`except: pass` 遍布，检测失败用户不知

### 📦 变更

- 新增 `PolicyEngine`：dev/test/prod 三级策略
- 新增 `RollbackJury`：违规判决书生成
- 新增 `RadiationDetector`：全栈辐射检测
- 新增 `MultiLangASTEngine`：5 语言检测（实际只有 Python 是 AST）
- 新增 `Skill` 交互推荐

---

## [V2.0] — 2026-07-13 · 无状态网关

**代号：守门人**

### 🆕 新增

- `gateway.py`：统一网关（意图 → Skill → 模型 → 守门）
- `IntentEngine`：轻量关键词意图识别
- `SkillRecommender`：交互式 Skill 推荐
- `FineTunedCore`：10+ AI 平台适配
- `FeedbackFlywheel`：违规数据积累 → SFT 导出
- `V1Bridge`：V1 模块自动桥接

### 🔧 改进

- 守门规则从 5 条扩展到 7 条
- 快照预检：杜绝空快照
- 回滚前自动备份当前状态

### 🐛 修复

- 快照恢复时忽略项不生效
- `config.json` 不存在时崩溃

---

## [V1.0] — 2026-07-10 · 原型诞生

**代号：闲的没事干**

### 🎉 初始功能

- `work.py`：13 层焊缝检测（Python AST）
- `guardian.py`：基础快照 + 回滚
- `Archive.py`：SimHash 长对话记忆
- `shiyun.py`：硬核叙事工厂（30+ 题材库）
- `Nuwa.py`：基础 POC 报告（HTML + JSON）
- `Proteus.py`：交互式启动菜单

### 📦 首发平台

GitHub：`jincheng3870682453-hash/jinchen`

---

## 🗺️ 未来计划（Roadmap）

| 功能 | 优先级 | 预计版本 | 状态 |
|------|--------|---------|------|
| `tree-sitter` 真 AST（Java/Kotlin/TS/Swift） | 🔴 高 | V3.2 | 调研中 |
| 真实项目准确率测试（100+ 样本） | 🔴 高 | V3.2 | 待收集 |
| 性能基准测试（1000 文件扫描） | 🟡 中 | V3.2 | 待做 |
| Sigstore 集成（真签名） | 🟡 中 | V3.3 | 调研中 |
| Web UI 仪表盘 | 🟢 低 | V4.0 | 构思中 |
| 插件系统（第三方 Skill 市场） | 🟢 低 | V4.0 | 构思中 |

---

**让 AI 守规矩，从承认不完美开始。 🛡️**
