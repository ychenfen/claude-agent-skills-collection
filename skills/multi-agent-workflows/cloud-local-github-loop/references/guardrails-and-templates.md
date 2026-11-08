# Cloud-Local GitHub Loop 工作流模板与安全门禁参考

## 1. `.github/workflows/remote-cmd.yml` 标准模板

```yaml
name: Remote Local Runner Command
run-name: Remote cmd ${{ inputs.request_id }}
on:
  workflow_dispatch:
    inputs:
      command:
        description: "Command to execute on local self-hosted runner"
        required: true
        type: string
      workdir:
        description: "Working directory (default repo root)"
        required: false
        default: ""
        type: string
      timeout_minutes:
        description: "Timeout in minutes (1-120)"
        required: false
        default: "30"
        type: string
      request_id:
        description: "Caller-chosen correlation ID"
        required: true
        type: string

permissions:
  contents: read

concurrency:
  group: local-self-hosted-runner
  cancel-in-progress: false

jobs:
  authorize:
    runs-on: ubuntu-latest
    steps:
      - name: Verify repository owner and trusted branch
        env:
          ACTOR: ${{ github.actor }}
          TRIGGER: ${{ github.triggering_actor }}
          OWNER: ${{ github.repository_owner }}
          REF: ${{ github.ref }}
        run: |
          test "$ACTOR" = "$OWNER"
          test "$TRIGGER" = "$OWNER"
          case "$REF" in
            refs/heads/main|refs/heads/ai-loop) ;;
            *) exit 1 ;;
          esac

  execute:
    needs: authorize
    runs-on: [self-hosted, macOS, ARM64]
    timeout-minutes: 130
    steps:
      - uses: actions/checkout@v4
        with:
          persist-credentials: false
      - name: Execute command with timeout
        id: cmd
        env:
          CMD: ${{ inputs.command }}
          TIMEOUT_MIN: ${{ inputs.timeout_minutes }}
        run: |
          OUT="$RUNNER_TEMP/remote-run"
          rm -rf "$OUT" && mkdir -p "$OUT"
          set +e
          perl -e 'alarm shift; exec @ARGV' "$((TIMEOUT_MIN * 60))" /bin/zsh -l -c "$CMD" > "$OUT/output.txt" 2>&1
          CODE=$?
          set -e
          echo "code=$CODE" >> "$GITHUB_OUTPUT"
          tail -n 120 "$OUT/output.txt"
      - uses: actions/upload-artifact@v4
        if: always()
        with:
          name: remote-cmd-result
          path: ${{ runner.temp }}/remote-run/
          retention-days: 7
```

## 2. macOS `sandbox-exec` 最小权限隔离模板

在 macOS 自托管 Runner 上运行实验脚本时，使用 `sandbox-exec` 阻止任务意外读写 `/Users` 下的私人目录，仅开放当前任务目录与结果输出目录：

```scheme
(version 1)
(allow default)
(deny file-read* file-write* (subpath "/Users"))
(allow file-read-metadata)
(allow file-read* (subpath (param "TASK_DIR")))
(allow file-read* file-write* (subpath (param "OUT_DIR")))
(allow file-read* file-write* (subpath (param "TMP_DIR")))
```

## 3. 常见工程坑与排错指南

- **macOS 无 `timeout` 命令**：GNU coreutils 的 `timeout` 在原生 macOS 上默认不存在，使用 `perl -e 'alarm shift; exec @ARGV' <seconds> <cmd>` 可零依赖实现硬超时（超时退出码为 `142`）。
- **切勿在远程脚本中用 `pkill -f <script_name>`**：执行该命令的父 Shell 命令行参数中也包含 `<script_name>`，会把自己先杀掉导致 GitHub Action 异常中断。停止子进程一律记录并按 PID 终止。
- **防止云端环境伪造本地执行**：如果 API 权限不足（HTTP 403）或自托管 Runner 离线，**绝不能在云端容器里跑一遍脚本冒充本地结果**；必须如实报告 Runner 状态并切换为 `.ai/next_task.md` 队列模式。
