---
name: antigravity
description: 指挥侧通过本地三通道文件桥给 Antigravity 中的 Gemini 派任务、查看心跳并独立验收 delivery.json；使用已登录的 Antigravity 会话，不需要为文件桥配置 API Key。
---

# 给 Antigravity 里的 Gemini 派单与验收

Gemini 是执行者，它写的总结不作为事实。派单时把边界写死，验收时用脚本独立复跑。执行侧的对应流程在配套 `bridge-worker` skill。Claude 只指挥的完整入口见配套 `agent-commander` skill。

以下 `$AGY` 和 `$BW` 分别代表已安装的 `antigravity` 与 `bridge-worker` skill 的绝对路径。不要假定安装在某个用户名的目录。首次连接读取 [监听会话提示词](references/LISTENER_PROMPT.md)，在 Antigravity 中开启所选通道的执行会话。

## 通道

| 通道 | 命令 | 桥接目录 |
|---|---|---|
| 1 | `python3 "$AGY/scripts/ask_agy.py" --channel 1`（原 `ask-agy`） | `/tmp/claude_agy_bridge` |
| 2 | `python3 "$AGY/scripts/ask_agy.py" --channel 2`（原 `ask-agy2`） | `/tmp/claude_agy_bridge2` |
| 3 | `python3 "$AGY/scripts/ask_agy.py" --channel 3`（原 `ask-agy3`） | `/tmp/claude_agy_bridge3` |

每个通道对应一个独立的 Antigravity 会话，各自只监听自己的 inbox。`/tmp` 重启后会清空，会话也要用户在 Antigravity 里重新开启监听。每个项目同一时间只派给一个写入者。测试时用 `BW_BRIDGE_ROOT_1`、`BW_BRIDGE_ROOT_2`、`BW_BRIDGE_ROOT_3` 指向隔离目录；派单端与执行端必须使用相同覆盖值。

## 派单

任务书用 `$BW/templates/TASK_TEMPLATE.md`，必须写明：允许做的事、禁止做的事、预算、硬超时和无进度阈值、产出清单、"用 bridge-worker 交 delivery.json"。

```bash
python3 "$AGY/scripts/ask_agy.py" --channel 1 -t 7800 -i /abs/TASK_xxx.md -o /abs/RESULT_xxx.ack.md \
  "按输入任务书执行，使用 bridge-worker skill，任务书优先于其他指示。" > /abs/agy_xxx.log 2>&1
```

长任务放后台跑。`-t` 设成任务书硬超时加 10 分钟，不要沿用 28800 秒这种等一整夜的值。批量标注把样本写成一个 JSONL 一次派出，不要逐条调用。

派单超时只表示没有收到回执，不会取消执行任务。先核查认领、心跳和产物，再决定是否重派，避免两个执行者重复写入。文件桥本身不访问模型 API；任务内的 Vertex、GPU 等仍可能单独计费，必须沿用用户授权和预算。

## 等待期间

不要只等 `ask-agy` 返回。看 `<桥接目录>/runs/<请求 id>/heartbeat.json`：

- `state` 是 `running` 且 `last_progress_at` 在阈值内：正常。
- `killed_stall` 或 `killed_timeout`：执行者应当自己交 `blocked`；10 分钟内没交，就在对应通道追发一条说明。
- 请求超过 5 分钟仍未变成 `.claimed`：该通道会话没在监听，改派另一通道或告诉用户。

不要用 `pkill -f` 匹配会出现在监听脚本里的字符串，曾经误杀过监听器。

## 验收

1. 独立复跑：`python3 "$BW/scripts/bw_verify.py" /abs/delivery.json --strict`。不通过就写返修任务书退回同一通道，不替它改。`--strict` 要求真实认领记录；摘要和哈希通过也不能证明任务书边界已全部遵守。
2. 通过后仍要做脚本做不了的事：抽查 claim 的源文件是不是该用的那个文件；`deviations` 里的 `authorized_by` 在任务书里是否真有这一节；`fallbacks` 计数是否披露进报告；Colab 会话是否真的释放（`colab sessions`）；arXiv 引用用 API 核对。
3. 没有 `delivery.json` 的交付不收，除非任务书明确免除（比如纯连通性测试）。

## 连通性测试

```bash
python3 "$AGY/scripts/ask_agy.py" --channel 1 -t 120 "Reply with connectivity test OK"
```
