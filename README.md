# t3-model-combo

> Artificial Analysis model value combo ranker skill for **T3 Code** — compare 2-model and 3-model combinations across your enabled providers by Intelligence Index and Cost per Task.

当你同时接入了多个模型渠道（例如官方 API、聚合中转、多厂商账号）时，选单个模型往往不够用：主力写代码或推理需要高智力模型，日常改写或子任务又希望便宜好用。**`t3-model-combo`** 会自动读取你当前在 T3 Code 里已经启用的渠道与模型，结合 **Artificial Analysis** 权威榜单的智力指数（Intelligence Index）与单次任务成本（Cost per Task），直接在对话里生成交互式性价比排行榜，帮你挑出最划算的 2 模型或 3 模型黄金组合。

---

## 核心特性

- **自动同步 T3 渠道**：自动获取你当前 T3 Code 已启用的全部提供商与可用模型，只推荐你真能用上的组合。
- **三种视角切换对比**：支持按 **T3 渠道（Provider）**、**模型原厂（Model Creator）** 或 **自定义分组（Custom Group）** 横向对比。
- **2 / 3 模型避重配对**：自动避免同一模型或同质档位重复配对，兼顾“主力强模型 + 轻量高性价比模型”的协同分工。
- **偏能力 ↔ 偏省钱滑块**：在卡片内实时调节权重偏好，并支持设置智力下限与单任务预算上限。
- **帕累托前沿散点图**：直观标出“同成本下最聪明、同智力下最省钱”的最优前沿组合，一眼避开低性价比选项。
- **对话内一键闭环**：支持保存常用分组、收藏默认黄金组合，并在挑中模型后直接一键切换当前会话的模型。

---

## 安装方式

### 方式一：使用 `npx skills`（推荐）

```bash
npx skills add xujianjun95/t3-model-combo
```

### 方式二：使用安装脚本 `./install.sh`

如果你已经克隆了本仓库：

```bash
git clone https://github.com/xujianjun95/t3-model-combo.git
cd t3-model-combo
./install.sh
```

或者直接远程一键安装：

```bash
curl -fsSL https://raw.githubusercontent.com/xujianjun95/t3-model-combo/main/install.sh | bash
```

安装脚本会自动识别本机已存在的 Agent Skill 目录（如 `~/.agents/skills`、`~/.codex/skills`、`~/.claude/skills`、`~/.cursor/skills`）并建立软链；也支持 `--target <dir>` 指定目录、`--copy` 拷贝安装以及 `--uninstall` 卸载。

安装完成后，**在 T3 Code 里重启会话即可通过 `/` 或 `$` 使用 `t3-model-combo`**。

---

## 常用示例

在 T3 Code 对话中可以直接输入命令或用自然语言提问：

- `/t3-model-combo` — 对比当前已启用渠道的 2 模型 / 3 模型性价比排行
- `帮我按原厂对比一下我现有模型里最划算的 3 模型组合，预算别太高`
- `只看智力分 60 以上的 2 模型组合，偏向省钱一些`
- `把「OpenAI + Anthropic」保存成一个自定义分组，方便以后对比`
- `把排第一的组合设为默认黄金组合，以后派子任务优先参考`
- `把当前对话切换到榜单里推荐的主力模型`

---

## English Overview

**`t3-model-combo`** is a T3 Code Agent Skill that connects your live `orchestrator_capabilities` with **Artificial Analysis** benchmark data:

- Syncs enabled T3 Code providers and models automatically
- Ranks non-redundant 2-model and 3-model combinations across providers, model creators, or saved custom groups
- Provides interactive controls for Intelligence vs. Cost preference, minimum Intelligence Index, budget caps, and a Pareto frontier scatter chart
- Supports saving custom groups, saving favorite golden combos (`~/.config/t3-model-combo/config.json`), and switching the active thread model via `t3_thread_configure`

---

## 数据来源与开源协议

- **基准数据致谢**：模型智力指数与任务成本数据来自 [Artificial Analysis](https://artificialanalysis.ai/)。
- **开源协议**：本项目基于 [MIT License](LICENSE) 开源。
