# browser-form-registration 使用说明（Claude Code 版）

让 Claude Code 帮你报名：先把材料丢进一个文件夹让它解析成资料包，之后打开报名网页自动填写，提交前停下来等你确认。

## 安装

把 `browser-form-registration` 整个文件夹放到：

```
~/.claude/skills/
```

没有这个目录就先建一个。放好后重启 Claude Code，输入 `/browser` 能看到 `browser-form-registration` 补全即安装成功。

## 前提

Claude Code 需要有浏览器操控能力，二选一：

- 内置 Browser 面板（桌面版 / IDE 插件自带）
- Claude in Chrome 扩展（需要用你已登录账号的网站时用这个）

## 使用

第一次（建资料包）：

1. 新建一个文件夹，把报名可能用到的材料都放进去：身份证扫描件、证件照、简历、学历证书、学信网报告、以前填过的报名表等。
2. 对 Claude 说：

```
用 /browser-form-registration 解析我的报名材料文件夹 ~/Desktop/报名材料，建立资料包
```

3. Claude 会解析所有文件，生成 `registration-profile.yaml`，列出缺失和冲突的信息让你补充核对。

以后每次报名：

```
用 /browser-form-registration 打开 https://某报名网站，用我的资料包帮我填报名表
```

Claude 会读取资料包、打开网页、自动匹配填写、上传材料，只问资料包里没有的信息。

## 安全边界

- 密码、短信验证码、图片验证码、支付信息始终由你本人输入，Claude 不代填也不保存
- 最终提交、勾选声明、电子签名、付款前 Claude 会停下来等你逐项确认
- 资料包是明文文件，身份证号等敏感字段可以选择不落盘，标记"现场提供"即可
