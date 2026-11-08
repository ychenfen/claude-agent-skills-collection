---
name: short-video-to-notes
description: 将短视频分享链接（抖音、微信视频号、B站）或本地录屏/音视频文件（.mp4/.mov/.m4a）通过本地语音转写（douyin_workflow / SenseVoice / FunASR / Whisper + ffmpeg）转化为带 YAML frontmatter 的结构化学习笔记（.md）与时间轴字幕（.srt）。Use whenever the user asks to 把短视频转成笔记、抖音链接转文字、视频号转写、录屏整理成 Markdown 笔记、提取视频字幕和核心要点。
---

# 短视频与本地音视频转结构化笔记（Short Video to Notes）

将口播短视频、课程录屏或讲座音频转为**可检索、带内容哈希、修正同音错字**的 Markdown 结构化笔记与 `.srt` 字幕。

## 一、输入源路由（3 条通道）

按用户提供的输入类型自动选择获取通道，优先使用本地已部署的转写工具链：

1. **抖音分享口令 / 短链（`v.douyin.com`）**
   - 若本机已部署 `douyin_workflow`：
     ```bash
     python3 -m douyin_workflow run "<分享文本或链接>" --json
     ```
   - 自动走匿名浏览器 / `iesdouyin` / `yt-dlp` 降级链下载并调用本地 SenseVoice 转写，按作品 ID 缓存。
2. **微信视频号分享链接（`weixin.qq.com/sph/...`）**
   - 视频号公开页无裸流，若环境变量已配置受限 `WECHAT_YUANBAO_COOKIE`，可由 `douyin_workflow run` 解析；
   - **严禁将任何 Cookie 写入笔记、日志或代码库**；若无有效凭证或解析受限，引导用户提供本地视频文件（如录屏或本地下载的 `.mp4`）走通道 3。
3. **本地视频 / 音频文件（`.mp4`, `.mov`, `.mkv`, `.m4a`, `.mp3`, `.wav`）**
   - 先用本技能自带脚本 `scripts/extract_and_format.py` 计算文件前 16 位 SHA-256 指纹、用 `ffmpeg` 抽取 16kHz 单声道 WAV，再交给本地 ASR（`douyin_workflow file`、`funasr` 或 `whisper`）。

## 二、标准执行流程

### 步骤 1：抽取音频与元数据（或读取转写 JSON）

使用捆绑脚本对本地媒体或已生成的转写 JSON 进行预处理：

```bash
# 从本地视频抽取 16kHz 单声道音频并生成笔记骨架
python3 scripts/extract_and_format.py input.mp4 \
  --title "课程主题" \
  --out-dir ./notes_out \
  --extract-audio
```

若已有分段转写 JSON（含 `text` 或 `segments: [{start, end, text}]`），直接生成 `.srt` 与带 YAML frontmatter 的 Markdown 初稿：

```bash
python3 scripts/extract_and_format.py input.mp4 \
  --transcript-json raw_asr.json \
  --title "课程主题" \
  --source-url "https://..." \
  --out-dir ./notes_out
```

### 步骤 2：ASR 同音字修复与去口水化（关键增效步骤）

口播视频的原始 ASR 文本充满口头禅（“那么”“就是说”“对吧”“家人们”）与专业术语同音错字。生成最终笔记前，必须按 [references/note-schema.md](references/note-schema.md) 完成三件事：

1. **术语同音校正**：根据视频主题（数学、计算机、工程、人文等），修正被拼音同音打烂的专有名词（如“马尔可夫链”“鲁棒性”“梯度下降”“泛函”）。
2. **保留事实与数字，剔除填充词**：删除开场求赞、直播话术与重复句，但**完整保留所有定量指标、公式推导条件、反例与书名/论文名**。
3. **双层结构输出**：
   - 上半部分为**结构化提炼**（核心结论、逻辑推演/步骤清单、易错点/边界条件）；
   - 下半部分为 `<details>` 折叠的**校对后逐字稿**（方便回查原话）。

### 步骤 3：合规与版权标记

- 下载或转写的素材仅用于个人学习归档，笔记 YAML frontmatter 中默认标记 `rights_status: personal-study-only`。
- 公开分享或二次创作前提醒用户核验原作者版权与平台规则。

## 三、脚本与参考文件

- `scripts/extract_and_format.py`：计算媒体 SHA-256、调用 `ffmpeg` 抽 16kHz WAV、将时间戳片段转为 `.srt` 字幕，并生成带标准 YAML frontmatter 的 Markdown 笔记模板。
- [references/note-schema.md](references/note-schema.md)：YAML frontmatter 字段规范、ASR 常见学科同音错字对照表、口播稿结构化提炼清单。
