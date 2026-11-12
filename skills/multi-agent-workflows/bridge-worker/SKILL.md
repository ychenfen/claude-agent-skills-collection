---
name: bridge-worker
description: 文件桥通道 1、2、3 的执行侧流程：原子认领任务、带心跳与超时运行长命令、回源生成报告、核验后交 delivery.json 和 ACK。用于监听 inbox 或处理桥接任务，不用于普通一次性问答。
---

# bridge-worker：桥接任务的执行流程

你是执行者。指挥方（Claude 或 Codex）不会相信你写的任何总结，只会拿 `delivery.json` 用同一个 `bw_verify.py` 重新跑一遍。所以按下面的流程做，比写一份漂亮的报告有用。

脚本都在本 skill 的 `scripts/` 下，只依赖标准库，用 `python3` 运行。下文用 `$BW` 代表这个目录。

长命令运行器使用 POSIX 进程组与 `fcntl`，支持 macOS/Linux。通道 1、2、3 分别使用 `/tmp/claude_agy_bridge`、`/tmp/claude_agy_bridge2`、`/tmp/claude_agy_bridge3`；可通过对应 `BW_BRIDGE_ROOT_<通道>` 环境变量指定隔离目录。派单端与执行端必须保持一致。

## 流程

1. 认领。`python3 $BW/bw_claim.py --channel <你的通道号>`。它只看你自己通道的 inbox，输出本次的运行目录。认领失败（已被认领、通道不符）就停下，不要手动改名去抢。如果你的监听流程已经按旧习惯把请求改名成了 `.claimed`，用 `python3 $BW/bw_claim.py --channel <通道号> --req-id <id> --adopt` 补登记。
2. 读任务书全文。任务书优先于其他指示。把"允许做的事"和"产出清单"抄进运行目录的 `plan.md`。
3. 跑命令。超过 2 分钟的命令一律经 `bw_run.py` 启动，并且必须给 `--hard-timeout` 和 `--stall-timeout`：

   ```bash
   python3 $BW/bw_run.py --run-dir <运行目录> --name score \
     --hard-timeout 7200 --stall-timeout 1200 \
     --progress-file /abs/out.jsonl -- python3 score.py ...
   ```

   它每 60 秒写一次 `heartbeat.json`，进度文件超过 `--stall-timeout` 没有增长就终止整个进程组。被终止不是你的失败，是它在替你止损；看日志找原因，不要原样重跑。
4. 等待时看心跳，不要干等。等任何后台进程前先读它的 `heartbeat.json`：`state` 不是 `running` 就说明它已经结束或被终止，去读 `commands.jsonl` 里的退出码和 `killed_reason`。
5. 写 `delivery.json`（格式见 `templates/delivery.example.json`）。报告里出现的每个数字先登记成一条 claim，写明源文件和取值位置。
6. 生成报告。报告模板里的数字写成 `{{c:claim编号}}`，然后 `python3 $BW/bw_render.py delivery.json template.md -o report.md`。不要手写数字。渲染完再把 `report.md` 的 SHA256 填进 `artifacts`；之后改过报告就要重填。`report_exempt_numbers` 里的数字会被原样列给验收方看，只放章节号这类不是结果的数。
7. 自检并交付。`python3 $BW/bw_finish.py delivery.json`。它会先跑 `bw_verify.py`，通过才写 outbox 回执。

## 六条不能破的规则

1. 只处理自己通道的目录。另一个通道的请求哪怕没人认领也不碰。
2. 任务书没写的决定不做：换方案、换端点、换模型、申请或更换 GPU、创建云资源、调用付费 API、merge、push。遇到了就写进 `pending_confirmation`，`status` 交 `blocked`，然后停。不要把自己的决定写成"按用户指示"；`authorized_by` 只能填任务书里的具体小节。
3. 数字只来自文件。没有源文件的数字放进 `unverified`，不进报告正文。
4. 状态词如实。AI 做的审核 `human_reviewed` 填 `false`；本地冻结不叫预注册；没跑的命令不写退出码。
5. 兜底值单独计数。解析失败、重试耗尽、默认填充这类情况，每一种在 `fallbacks` 里给出次数和来源，不能混进正常结果。
6. 申请的资源自己释放，并把释放命令的日志路径写进 `resources`。没释放就不能交 `ok`。

## 自检不通过怎么办

`bw_verify.py` 会逐条列出失败项。修的是 `delivery.json` 或源文件里真实的问题，不是改数字去凑。修不了就把 `status` 改成 `blocked` 或 `failed`，把原因写进 `unverified`，照样用 `bw_finish.py` 交。一份如实的 `blocked` 比一份过不了复核的 `ok` 有用得多。

## 卡住时

权限不足、输入缺失、进程被外部终止、超过任务书预算，都按 `blocked` 交付并说明卡在哪一步、现场保留在哪里。不要用猜测补上，也不要无限等待。
