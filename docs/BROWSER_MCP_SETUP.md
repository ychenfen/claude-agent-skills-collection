# 浏览器控制配置教程

技能包里的报名填表和 Boss直聘 skill 都需要 agent 能操控浏览器。本文按你用的工具分两节，Codex 用户看第一节即可。

## Codex：Playwright MCP

Codex CLI 本身不带浏览器，靠 Playwright MCP 提供浏览器操控能力。前提：装好 Node.js（`node -v` 能出版本号）。

### 第 1 步：给 Codex 添加 Playwright MCP

方式一，命令行一句：

```bash
codex mcp add playwright -- npx "@playwright/mcp@latest"
```

方式二，手动编辑 `~/.codex/config.toml`，加上：

```toml
[mcp_servers.playwright]
command = "npx"
args = ["@playwright/mcp@latest"]
```

重启 Codex，问它"你现在能打开浏览器吗"，它列出 browser_navigate 之类的工具就说明配置成功。

### 第 2 步：解决登录态（两种模式选一种）

**模式 A：默认模式（配置简单，推荐先用这个）**

Playwright MCP 会启动一个自己的浏览器窗口，用独立的持久化档案。第一次让 Codex 打开 zhipin.com 时，你在弹出的浏览器窗口里手动登录一次（扫码即可），之后登录态一直保留，不用每次登。

缺点：这是个独立浏览器，没有你日常 Chrome 里的登录状态和插件。

**模式 B：extension 模式（直接用你日常的 Chrome，共享所有已登录网站）**

1. 给 Chrome 装 "Playwright MCP Bridge" 扩展。两种装法：
   - 直接从 Chrome 应用商店安装（搜 "Playwright MCP Bridge"，需要能访问商店）
   - 侧载安装（商店打不开时用）：
     1. 打开 https://github.com/microsoft/playwright-mcp/releases，下载最新的扩展 zip 包并解压
     2. Chrome 地址栏输入 `chrome://extensions` 回车
     3. 打开右上角的"开发者模式"开关
     4. 点左上角"加载已解压的扩展程序"，选择刚解压出来的文件夹
     5. 扩展列表里出现 Playwright MCP Bridge 即成功
2. 把 MCP 配置加上 `--extension` 参数：

```toml
[mcp_servers.playwright]
command = "npx"
args = ["@playwright/mcp@latest", "--extension"]
```

3. 重启 Codex。第一次让它操作浏览器时，Chrome 会弹出一个页面让你选择授权哪个标签页给它控制，点确认即可。

### 常见问题

- `npx` 第一次下载很慢或超时：网络问题，给 npm 配镜像（`npm config set registry https://registry.npmmirror.com`）或挂代理后重试。
- 浏览器打开了但页面上的滑块/图片验证码过不去：正常，这类验证永远由你本人完成，agent 不应该也不会绕过。
- extension 模式连不上：确认扩展已启用、Chrome 是打开状态，然后重启 Codex 再试。

## Claude Code

- 报名填表：Claude Code 桌面版/IDE 插件自带 Browser 面板，开箱即用，什么都不用装。
- Boss直聘这类需要你已登录账号的网站：装 Claude in Chrome 扩展——Chrome 应用商店搜 "Claude"（Anthropic 出品）安装，登录你的 Claude 账号后，Claude Code 就能操作你的真实 Chrome。
