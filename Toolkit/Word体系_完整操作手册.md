---
title: "Word体系 · 完整操作手册"
description: "Word体系五个独立模块的详细操作指南：work、Archive、shiyun、Nuwa、Proteus"
date: 2026-07-05
version: "全模块版"
---

# 📘 Word体系 · 完整操作手册

> Word体系包含五个独立模块，可单独使用或组合使用。所有模块共用底层：AI调用层（10平台适配）、校验层、存证层。

---

## 📋 目录

- [一、通用配置](#一通用配置)
- [二、模块一：work（核心行为约束）](#二模块一work核心行为约束)
- [三、模块二：Archive（长对话记忆）](#三模块二archive长对话记忆)
- [四、模块三：shiyun（硬核叙事工厂）](#四模块三shiyun硬核叙事工厂)
- [五、模块四：Nuwa · 女娲补天框架（B端交付层）](#五模块四nuwa--女娲补天框架b端交付层)
- [六、模块五：Proteus · 统一启动入口](#六模块五proteus--统一启动入口)
- [七、如何选择模块](#七如何选择模块)
- [八、所有旧文件清理清单](#八所有旧文件清理清单)
- [九、常见问题](#九常见问题)
- [十、结束语](#十结束语)

---

## 一、通用配置

首次运行任一模块时，会自动引导配置AI服务商。

### 支持的AI提供商（10种）

| 提供商 | 英文名 |
|--------|--------|
| OpenAI | OpenAI |
| Anthropic | Anthropic |
| Gemini | Gemini |
| Ollama | Ollama |
| 通义千问 | 通义 |
| 智谱GLM | 智谱 |
| DeepSeek | DeepSeek |
| MiniMax | MiniMax |
| 百川 | 百川 |
| 腾讯混元 | 腾讯混元 |

### 配置文件位置

| 模块 | 配置文件路径 |
|------|-------------|
| work | `~/.word_fusion.json` |
| shiyun | `~/.poemcloud_config.json` |
| Nuwa | `~/.nuwa_config.json` |
| Proteus | `./.Proteus_config.json`（在核心代码/配置/目录） |

---

## 二、模块一：work（核心行为约束）

> **定位**：AI代码生成的质量保险丝

### 2.1 安装与运行

```bash
# 保存 work.py 到本地
# 安装依赖
pip install requests

# 基本用法
python work.py "你的需求"

# 示例
python work.py "帮我写一个计算器" --root ./my_project
```

### 2.2 常用命令

```bash
# 启用AI规划
python work.py "生成REST API" --planner ai --ai-provider deepseek --ai-api-key sk-xxx

# CI/CD无人值守（自动跳过硬确认）
python work.py "修复所有测试" --confirm-mode auto_confirm

# 干跑预览（不实际写入文件）
python work.py "修改配置" --dry-run

# 自定义冒烟超时（默认30秒）
python work.py "复杂计算" --smoke-timeout 60

# 追加乱码字符
python work.py "需求" --mojibake-append  ©
```

### 2.3 关键功能说明

| 功能 | 说明 |
|------|------|
| **影子执行防擦除锁** | 诱饵在隔离副本中执行，比对干净副本与诱饵副本 |
| **多态诱饵池** | 5种语义级诱饵随机注入（未导入模块、类型不匹配、递归无出口、死循环、循环依赖） |
| **AST后验比对** | 精确检测诱饵是否被修复（行号偏移漏洞已修复） |
| **三重锁画像** | 甲方新功能需求自动解锁骨架，调试场景维持铁锁 |

---

## 三、模块二：Archive（长对话记忆）

> **定位**：长对话记忆与注意力优化

### 3.1 安装与运行

```bash
# 保存 Archive.py 到本地
# 可选依赖：pip install jieba（提升分词效果）
# 运行
python Archive.py
```

### 3.2 常用命令

```bash
# 压测
python Archive.py --benchmark

# 交互模式
python Archive.py

# 单条测试
python Archive.py --test-input "帮我写一个计算器" --conversation-id demo

# 自定义参数
python Archive.py --block-size 256 --threshold 0.4
```

### 3.3 关键功能说明

| 功能 | 说明 |
|------|------|
| **回忆快照注入** | 将历史快照拼接到用户输入前 |
| **SimHash主题检测** | 64位SimHash + 分块 + MD5缓存 + 文件锁 |
| **主题切换判断** | 基于块哈希重叠率 + 短输入保护 |
| **紧急度信号** | 标点、语气词、全大写自动提升快照优先级 |

---

## 四、模块三：shiyun（硬核叙事工厂）

> **定位**：叙事创作工具，**非自动写书机器**

### 4.1 安装与运行

```bash
# 保存 shiyun.py 到本地
pip install requests
python shiyun.py
```

### 4.2 完整操作流程

#### 第一步：选题

系统提示请选择选题方式：

| 选项 | 方式 |
|------|------|
| 1 | 从热门题材库选择（30+） |
| 2 | 自由输入关键词/描述 |
| 3 | 输入网址或文档（AI提取） |
| 4 | 随机灵感 |

**操作**：输入编号 1-4，按提示完成

#### 第二步：设定维度数量

系统提示："你希望用几个核心维度来构建这个世界？"

**操作**：输入数字（建议5-15个），直接回车使用默认8个
> ⚠️ 注意：最少3个，无上限

#### 第三步：世界观审讯

系统逐维度提问，每个维度包含：名称、问题、思考方向

**操作**：
- 输入回答内容
- 输入 `skip` 跳过当前维度
- 输入 `exit` 结束审讯

每回答一个维度，AI自动生成：
1. 追问（为什么）
2. 反例测试（如果...会怎样？）
3. 矛盾提醒（指出潜在问题）

#### 第四步：选择模式

| 模式 | 说明 |
|------|------|
| **A模式** | 人类设定，AI严守：违规被记录，用户手动修复 |
| **B模式** | AI生成设定 + 逻辑毒药：最终作品暴露AI痕迹 |

#### 第五步：生成大纲

AI根据世界观生成3-5章大纲，用户可自由修改

#### 第六步：钩子处理

基于大纲生成候选钩子 → 用户自由采购 → 随时追加自定义钩子

#### 第七步：逐章扩写

AI按大纲生成正文，每章自动生成摘要

#### 第八步：校验

只报警不修复，所有违规记录在案

#### 第九步：导出

正文 + 世界观白皮书 + 钩子决算表 + 逻辑冲突附录

### 4.3 导出文件位置

```
~/poemcloud_exports/{project_id}_{timestamp}.txt
```

---

## 五、模块四：Nuwa · 女娲补天框架（B端交付层）

> **定位**：AI治理 B端交付层 · 12-Factor + POC报告 + 批量模式  
> **内部代号**：小皮鞭 · 专抽不听话的AI

### 5.1 安装与运行

```bash
# 保存 Nuwa.py 到本地（需要与 work.py / gateway.py / guardian.py / Archive.py 同目录）
# 安装依赖
pip install requests

# 基本用法（推荐：环境变量驱动）
export NUWA_AI_API_KEY=sk-xxx
export NUWA_CONFIRM_MODE=auto_confirm
python Nuwa.py "修复所有单元测试"
```

### 5.2 环境变量清单（12-Factor）

| 变量名 | 说明 | 默认值 |
|--------|------|--------|
| `NUWA_PROJECT_ROOT` | 项目根目录 | `.` |
| `NUWA_AI_PROVIDER` | AI提供商 | `ollama` |
| `NUWA_AI_MODEL` | 模型名 | `llama2` |
| `NUWA_AI_API_KEY` | API密钥 | **必须** |
| `NUWA_AI_BASE_URL` | 自定义API地址 | - |
| `NUWA_CONFIRM_MODE` | 确认模式 | `interactive` |
| `NUWA_SMOKE_TIMEOUT` | 冒烟超时秒数 | `30` |
| `NUWA_POC_OUTPUT_DIR` | POC报告输出目录 | `./poc_reports` |
| `NUWA_LOG_LEVEL` | 日志级别 | `INFO` |
| `NUWA_PLANNER` | 规划器类型 | `rule/ai` |
| `NUWA_IGNORE_PATTERNS` | 忽略文件模式 | 逗号分隔 |

### 5.3 常用命令

```bash
# 单次运行（生成POC报告）
python Nuwa.py "新增用户登录接口" --open-report

# 干跑预览
python Nuwa.py "修改配置" --dry-run

# 批量模式（从文件读取任务清单）
python Nuwa.py --batch tasks.json --open-report

# 调试模式
python Nuwa.py "复杂任务" --debug
```

### 5.4 批处理文件格式

**JSON 格式**（支持 error 字段）：

```json
[
    {"input": "修复登录报错", "error": "NameError: name 'user' is not defined"},
    {"input": "新增用户注册接口", "error": ""}
]
```

**纯文本格式**（每行一个需求，无 error_log）：

```text
修复登录报错
新增用户注册接口
优化数据库查询
```

### 5.5 POC 报告内容

| 输出格式 | 用途 | 特点 |
|----------|------|------|
| **HTML** | 给 CTO/客户看 | 卡片式排版，可折叠违规明细 |
| **JSON** | 给 CI/CD 解析 | 结构化数据，自动化处理 |

**核心指标**：

- 状态（`success`/`failed`）
- 总耗时（秒）
- 诱饵注入次数
- 诱饵触发次数
- 修复成功率（成功数/尝试数）
- 修复失败次数
- 物理回滚次数
- 修改文件数
- 验证通过/未通过
- 违规明细列表

### 5.6 关键功能说明

| 功能 | 说明 |
|------|------|
| **12-Factor 配置** | 环境变量 > 命令行参数 > 配置文件，API Key 永不落盘 |
| **无侵入指标采集** | Monkey Patch，不修改原代码 |
| **模块健康检查** | 启动时验证 work/guardian 接口是否存在 |
| **批量模式** | 自动汇总成功率、总耗时、总回滚数 |

---

## 六、模块五：Proteus · 统一启动入口

> **定位**：Word体系统一启动入口  
> **命名**：Proteus（希腊神话中千变万化的海神）  
> **内部代号**：画皮

### 6.1 安装与运行

```bash
# 双击启动（推荐）
Proteus.bat

# 或命令行
cd 核心代码
python Proteus.py
```

### 6.2 首次运行流程

1. **环境自检**
   - 检测 Python 3.10+ 是否安装
   - 检测 pip 是否可用
   - 检测 requests / pyyaml 是否安装
   - 检测 API Key 是否已配置

2. **API Key 引导**（首次使用）
   - 安全警告（必须确认 `y`）
   - 引导访问 DeepSeek 官网
   - 引导创建 API Key
   - 粘贴并保存至本地配置文件（核心代码/配置/._Proteus_config.json）

3. **记忆加载**
   - 自动加载 `.bookmark.json`（如有）

4. **进入主菜单**

### 6.3 菜单功能

| 选项 | 功能 |
|------|------|
| 1 | 完整流程（gateway 三件套） |
| 2 | 精密修复（work 行为约束） |
| 3 | 物理回滚（guardian 快照恢复） |
| 4 | 记忆加载（Archive 长对话召回） |
| 5 | 叙事创作（shiyun 硬核叙事工厂） |
| 6 | POC验证（Nuwa 单次） |
| 7 | 批量验证（Nuwa 从文件读取） |
| 8 | 查看报告（打开 poc_reports） |
| 9 | 配置 API Key |
| 10 | 查看完整公告 |
| 11 | 查看操作手册 |
| 12 | 查看免责声明 |
| 13 | 关于 / 版本信息 |
| 0 | 退出 |

### 6.4 配置文件

| 文件 | 用途 |
|------|------|
| `核心代码/配置/._Proteus_config.json` | API Key / 偏好设置 |
| `核心代码/配置/.bookmark.json` | 跨对话记忆书签 |

### 6.5 关键功能说明

| 功能 | 说明 |
|------|------|
| **环境自检** | 自动检测缺失项并引导修复 |
| **API Key 引导** | 只教 DeepSeek，安全警告硬拦截 |
| **配置持久化** | 首次配置后无需重复引导 |
| **菜单循环** | 执行完成后自动返回主菜单 |

---

## 七、如何选择模块

| 场景 | 推荐模块 | 说明 |
|------|----------|------|
| AI写代码 | work | 核心行为约束，质量保险丝 |
| 长对话失忆 | Archive | 长对话记忆与注意力优化 |
| 写小说/剧本 | shiyun | 硬核叙事工厂，自由创作 |
| B端交付/审计 | Nuwa（女娲） | 12-Factor + POC报告 + 批量模式 |
| 一键启动/入口 | Proteus | 统一启动入口，双击即用 |
| 组合使用 | 五个模块 | 独立运行，互不干扰 |

---

## 八、所有旧文件清理清单

### 可以删除的文件

以下文件已整合，可以删除：

- `公告.txt`
- `操作看这里.txt`
- `诗云_公告.txt`
- `诗云_操作手册.txt`
- `开发任务书.docx`
- 任何中间版本的公告/操作文档
- `V*.docx`（旧版设计文档）
- `模块入口.txt`（已整合入Proteus菜单）
- `README.md`（已整合入Proteus关于页面）

### 保留的最终文件

```
Word体系_完整公告.txt（本公告）
Word体系_完整操作手册.txt（本手册）
Word体系_免责声明.txt
Proteus.bat
核心代码/Proteus.py
核心代码/work.py
核心代码/Archive.py
核心代码/shiyun.py
核心代码/Nuwa.py
核心代码/gateway.py
核心代码/guardian.py
核心代码/配置/._Proteus_config.json
核心代码/配置/.bookmark.json
```

---

## 九、常见问题

**Q: 五个模块需要分别配置AI吗？**

A: work 和 shiyun 独立配置；Nuwa 从环境变量读取；Proteus 从本地配置文件读取。

**Q: 可以混合使用吗？**

A: 可以，五个模块独立运行，互不干扰。

**Q: 如何升级？**

A: 直接替换对应的 `.py` 文件即可，配置文件保留。

**Q: Proteus 需要什么额外依赖？**

A: 只需要 `requests` 和 `pyyaml`，与 work 相同。

**Q: 所有旧文件都要删吗？**

A: 只保留最终整合的 `.py` 文件和3个 `.txt` 文件，其他全删。

---

## 十、结束语

Word体系是一套完整的AI行为约束与认知增强框架。五个模块各司其职，可独立可组合。

| 模块 | 职责 |
|------|------|
| **work** | 管AI写代码的质量 |
| **Archive** | 管AI长对话的记忆 |
| **shiyun** | 管AI叙事创作的自由度 |
| **Nuwa（小皮鞭）** | 管AI治理的交付和证明 |
| **Proteus（画皮）** | 管AI工具的启动和调度 |

所有模块都遵循同一个核心原则：

> **不相信AI的自觉，只相信系统的硬规约和人类的终审权。**

—— Word体系 开发团队 · 2026.07.05

---

*本文档由 Word体系 开发团队维护。最后更新：2026-07-05*
