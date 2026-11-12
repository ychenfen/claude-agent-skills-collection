---
name: agent-commander
description: 当用户要求 Claude 只做指挥、由 Gemini 或 Codex 实施时，拆解任务、限定唯一写入者、派单、监督、独立验收并退回返修，保留原有授权边界。
---

# Claude 指挥，Gemini / Codex 执行

Claude 负责理解目标、写任务书、选择执行者、监督进度、审核和汇报。Gemini 或 Codex 负责项目代码、数据处理、实验与文稿的实际修改。Claude 可以写调度材料、交接和审核意见，可以只读核验、运行验证命令；不要在执行者工作中顺手修改项目实现，验收失败退回原执行者。

## 派单前

读当前项目规则、git 状态和交接，确认现有写入者是否仍在工作。用配套 `bridge-worker` 的 `templates/TASK_TEMPLATE.md` 写目标、输入、可写路径、禁止项、资源预算、两种超时、交付清单和验收条件。不得把其他项目的历史授权复制到当前任务。

每个项目或相互重叠的工作树同时只允许一个写入者。独立项目可分通道；同一项目换执行者前先确认旧任务退出并保留未提交内容。不要让 Gemini 再调用 Codex 实施，或让执行者递归派生另一个写入者，除非用户明确授权这种拓扑。

## Gemini 执行

读取配套 `antigravity` skill，使用随附 `scripts/ask_agy.py --channel 1|2|3` 派单。执行会话先加载 `bridge-worker`，认领自己的通道，交付 `delivery.json`。指挥侧看真实心跳、日志和文件，不把 ACK 或总结当作完成。派单超时不会取消执行任务，不能据此直接重派。

## Codex 执行

使用已安装并登录的 Codex CLI；先核对 `codex exec --help`，使用当前版本支持的参数。不固定模型或提权选项，沿用用户配置和任务授权。

下面是直接 CLI 模式示例，`TASK.md` 须包含明确的绝对工作目录、产物和报告路径。`$RUN` 为项目外独立的调度目录，避免与执行者同时写入。先创建该目录。

```bash
codex exec -C /abs/project --json \
  -o "$RUN/codex-last-message.md" - \
  < "$RUN/TASK.md" > "$RUN/codex-events.jsonl" 2> "$RUN/codex-stderr.log"
```

长任务可用配套 `bridge-worker/scripts/bw_run.py` 包裹上述命令，指定 `--hard-timeout`、`--stall-timeout` 和实际进度文件。`bw_run.py` 不负责模型认证或提升权限。直接 CLI 模式没有 inbox 请求，不应伪造认领记录或调用 `bw_finish.py`；要求执行者按任务书交变更清单、真实命令/退出码、产物路径、SHA-256、未完成项和必要的数字来源。`codex-last-message.md` 只是线索。

如需让 Codex 完整使用文件桥交付，先按 `antigravity` 协议派一个请求到专用空闲通道，再明确要求 Codex 以该通道的唯一执行者运行 `bw_claim.py`、实施和 `bw_finish.py`。该通道不能同时有 Gemini 监听；不得伪造桥接请求已由模型执行的证据。

## 独立验收与返修

1. 确认执行者已结束，检查 diff、实际输入输出、测试日志和资源状态。桥接模式独立跑 `bw_verify.py /abs/delivery.json --strict`；CLI 模式按任务书逐项核对，不能把进程退出码当作产物验收。
2. 抽查数字与引用的真实来源、冻结协议身份、兜底计数和资源释放。哈希一致只能证明文件身份，不能证明来源正确。AI 审核不称人工审核，本地冻结不称外部预注册。
3. 不通过时写出具体失败项和原始证据，退回同一执行者。重复同一阻塞且无新证据时停止原样重试，报告所缺条件。
4. 验收通过后，仅在用户已授权的门内合并、推送或上传。上传成功与对方接受分开记录。更新项目交接，简报最高已证实阶段、剩余问题和下一动作。
