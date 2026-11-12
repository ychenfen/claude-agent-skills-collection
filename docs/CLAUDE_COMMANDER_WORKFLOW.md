# Claude 只指挥，Gemini / Codex 执行

这是本地文件桥与 CLI 调度版本。原有 [cloud-local-github-loop](../skills/multi-agent-workflows/cloud-local-github-loop/SKILL.md) 继续用于 GitHub Actions / 自托管 Runner 场景。

## 安装

```bash
git clone https://github.com/ychenfen/claude-agent-skills-collection.git
cd claude-agent-skills-collection
./install.sh --skill agent-commander --target both
./install.sh --skill antigravity --target both
./install.sh --skill bridge-worker --target both
```

安装器在覆盖已有同名 skill 前会保留带时间戳的副本。安装不会修改 Claude/Codex 的全局规则，不会自动启动执行会话，也不会安装或替换 `~/.local/bin/ask-agy*`。用随附 Python 脚本即可派单。

## 三个角色

| 角色 | 入口 | 职责 |
|---|---|---|
| Claude 指挥 | [agent-commander](../skills/multi-agent-workflows/agent-commander/SKILL.md) | 拆任务、选择执行者、监督、回源验收与返修 |
| Gemini 派单 | [antigravity](../skills/multi-agent-workflows/antigravity/SKILL.md) | 向已登录的 Antigravity 会话发送本地文件请求，三个隔离通道 |
| 文件桥执行者 | [bridge-worker](../skills/multi-agent-workflows/bridge-worker/SKILL.md) | 认领、心跳、两种超时、报告取数、SHA-256、结构化交付 |

Claude 可以写任务书和审核意见，但项目实现交给唯一执行者。Codex 直接 CLI 模式与文件桥模式的交付要求不同，见 `agent-commander`。不要让同一通道同时由 Gemini 与 Codex 监听。

## Gemini 快速开始

需要 Python 3.9+、macOS/Linux，以及能读写同一本地文件系统的 Antigravity 执行会话。运行器依赖 POSIX 进程组和 `fcntl`；本版本未验证原生 Windows。文件桥本身没有模型 API 调用，实际任务使用的模型服务、GPU 和 API 费用仍受用户权限和预算约束。

1. 在 Antigravity 会话中发送 [监听提示词](../skills/multi-agent-workflows/antigravity/references/LISTENER_PROMPT.md)，替换通道和 skill 路径，等待真实就绪回执。
2. Claude 使用 [任务书模板](../skills/multi-agent-workflows/bridge-worker/templates/TASK_TEMPLATE.md) 填写任务。
3. 向相应通道派单；下面以 Claude 安装目录和通道 1 为例：

```bash
AGY="$HOME/.claude/skills/antigravity"
BW="$HOME/.claude/skills/bridge-worker"
python3 "$AGY/scripts/ask_agy.py" --channel 1 -t 7800 \
  -i /abs/TASK.md -o /abs/RESULT.ack.md \
  "按任务书执行，使用 bridge-worker 交 delivery.json。"
```

4. 指挥侧查看该请求 `runs/<id>/heartbeat.json`、日志与产物。收到回执后独立运行：

```bash
python3 "$BW/scripts/bw_verify.py" /abs/delivery.json --strict
```

校验通过后仍需人工式回源审核：输入身份、授权依据、测试覆盖、资源释放和真实结果。检查器不构成权限沙箱。派单超时不会取消执行；先查现场再重派。`/tmp` 可能在重启后清空，应将正式交付材料保存在任务书约定的持久目录。

## 本地验证

```bash
python3 scripts/validate_skills.py
python3 -m unittest discover -s skills/multi-agent-workflows/bridge-worker/tests -v
python3 -m unittest discover -s skills/multi-agent-workflows/antigravity/tests -v
```

测试用隔离目录模拟文件请求与回执，覆盖三通道的派单、认领、严格校验和交付，不调用模型或真实 IDE。CLI 参数已与整理时安装的 `codex exec --help` 核对；仓库测试不证明某台机器的模型认证、后台监听或真实任务执行正常。
