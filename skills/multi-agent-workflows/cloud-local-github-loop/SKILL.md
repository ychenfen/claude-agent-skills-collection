---
name: cloud-local-github-loop
description: 云端 AI Agent（Claude on the Web / Claude Code Cloud / Codex Cloud）与本地自托管 GitHub Runner（macOS / Linux）协同执行任务闭环：通过 GitHub Actions（remote-cmd.yml / ai-loop.yml）安全派发本地计算任务、拉取 Artifact 结果、遵守 5MB 单文件与密钥红线门禁，并在宿主机休眠离线时自动写入 .ai/next_task.md 排队。Use whenever the user asks to 让本地机器跑、派发 GitHub runner 任务、云端大脑+本地手脚协同、用 self-hosted runner 执行本地脚本、写 .ai/next_task.md。
---

# 云端大脑 × 本地手脚：GitHub Self-Hosted Runner 协同闭环

当大规模数据集（数十至数百 GB）、本地 GPU/Apple Silicon 算力或受保护的本地环境无法直接上传到云端沙盒时，将**云端 AI Agent 作为规划与代码审计大脑**，将**本地机器上的 GitHub Self-Hosted Runner（或本地 Codex/Claude 守护进程）作为执行手脚**，通过 GitHub 仓库分支与 Actions Artifact 完成异步闭环。

## 一、三层安全与容量红线（必须严格执行）

无论在云端提交任务还是从本地回传结果，必须先运行 `scripts/check_guardrails.py` 验证以下门禁：

1. **单文件 5 MB 上限（Git 跟踪区）**：
   - 严禁将原始大型数据集、模型权重（`.pt`/`.onnx`/`.parquet`）或超过 `5 MB` 的未压缩日志直接 `git add` 进仓库；
   - 本地 Runner 产出的结果只回传轻量汇总指标（`result.json`、统计表 CSV、矢量图 PDF/PNG）或通过 GitHub Actions Artifact（上限 50 MB）传递。
2. **零凭证 / 零密钥泄漏**：
   - 严禁回传 `.env`、`*.pem`、`*.key`、`id_rsa`、`*cookie*`、`*token*`、`*secret*` 或包含明文 API Key 的配置文件；
   - macOS 本地执行建议包裹在 `sandbox-exec` 最小权限配置中（仅开放当前任务目录与显式声明的数据只读目录，见 [references/guardrails-and-templates.md](references/guardrails-and-templates.md)）。
3. **触发人身份白名单（Actor Gate）**：
   - `remote-cmd.yml` 与 `ai-loop.yml` 必须包含前置 `authorize` Job，校验 `github.actor` 与 `github.triggering_actor` 为仓库所有者且分支受控，防止外部 PR 触发本地自托管 Runner。

## 二、标准双通道工作流

### 通道 A：Runner 在线 —— 实时派发 `workflow_dispatch`

1. **检查 Runner 在线状态**：
   ```bash
   gh api repos/<owner>/<repo>/actions/runners --jq '.runners[] | {name, status, busy}'
   ```
2. **提交任务代码并派发工作流**（携带唯一 `request_id`）：
   ```bash
   REQ_ID="req-$(date -u +%Y%m%dT%H%M%SZ)"
   gh api -X POST repos/<owner>/<repo>/actions/workflows/remote-cmd.yml/dispatches \
     -f ref=main \
     -f "inputs[command]=python3 scripts/run_experiment.py" \
     -f "inputs[request_id]=$REQ_ID"
   ```
3. **轮询对应的 Run ID 并验证执行宿主机**：
   - 确认 `head_sha` 与 `request_id` 匹配；
   - 确认 Job 的 `runner_name` 为目标本地自托管节点（绝不能把云端容器里跑的冒充本地执行结果）。
4. **下载并解压 Artifact**：
   - 拉取 `remote-cmd-result`，读取 `meta.json`、`output.txt` 与汇总文件。

### 通道 B：宿主机休眠 / Runner 离线 —— 写入 `.ai/next_task.md` 异步队列

当笔记本合盖休眠或自托管 Runner 处于 `offline` 状态时，**不要死循环轮询等待**，立即切换为离线任务单模式：

1. 使用 `scripts/queue_next_task.py` 生成标准化的 `.ai/next_task.md`：
   ```bash
   python3 scripts/queue_next_task.py \
     --task-id "exp-042" \
     --title "全量基准数据集交叉验证与耗时统计" \
     --command "python3 experiments/run_cv.py --folds 5 --out results/exp042.json" \
     --expected-output "results/exp042.json" \
     --out .ai/next_task.md
   ```
2. 运行回传门禁自检：
   ```bash
   python3 scripts/check_guardrails.py .
   ```
3. 提交并推送到协同分支（如 `ai-loop` 或 `main`）。本地机器唤醒后由定时任务或本地 Agent 自动读取 `.ai/next_task.md` 执行并把结果写回 `.ai/last_result.json`。

## 三、捆绑脚本与参考文件

- `scripts/check_guardrails.py`：提交或打包前扫描目录，拦截 `>5 MB` 文件、缓存目录与疑似密钥/Cookie 文件，输出 JSON 审计报告。
- `scripts/queue_next_task.py`：生成或校验 `.ai/next_task.md` 异步任务契约文件。
- [references/guardrails-and-templates.md](references/guardrails-and-templates.md)：`remote-cmd.yml` / `ai-loop.yml` 完整工作流模板、macOS `sandbox-exec` 隔离配置与防踩坑指南。
