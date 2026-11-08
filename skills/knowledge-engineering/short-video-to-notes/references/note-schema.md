# 短视频学习笔记 Schema 与 ASR 校对规范

## 1. Markdown YAML Frontmatter 规范

生成的每篇 `.md` 笔记顶部必须包含如下字段，便于 Obsidian / MarginNote / 本地知识库索引：

```yaml
---
title: "清晰反映核心议题的标题（去标题党）"
source_type: "local_file | douyin | wechat_channels | bilibili"
source_url: "原始分享链接（本地文件填 local://<filename>）"
media_sha256_prefix: "16位文件哈希前缀（防重）"
duration_sec: 185.4
asr_engine: "SenseVoice / FunASR / Whisper"
created_at: "2026-11-08"
rights_status: "personal-study-only"
tags:
  - 视频笔记
---
```

## 2. 正文四段式结构

1. **核心结论（TL;DR，3–5 条）**：每条一句话，直接给出结论、数值或判断标准，不写“视频主要讲了……”。
2. **方法与推导要点**：按逻辑顺序而非主播闲聊顺序重组，使用三级标题 `###` 与列表，补充公式（行内 `$...$`）与适用前提。
3. **提及的工具 / 文献 / 关键数据表**：把口播中一闪而过的书名、包名、参数、时间节点集中成表。
4. **折叠校对逐字稿**：
   ```markdown
   <details>
   <summary>展开校对后完整逐字稿</summary>

   [00:00] 校对后的分段正文……
   </details>
   ```

## 3. 常见 ASR 同音错字修复对照表

| 原始 ASR 误识 | 正确术语 | 领域 |
|---|---|---|
| 鲁棒性 / 撸棒性 / 路傍性 | 鲁棒性（Robustness） | 数学建模 / 机器学习 |
| 马尔科夫 / 马尔可夫链子 | 马尔可夫链（Markov Chain） | 概率统计 |
| 梯度下将 / 剃度下降 | 梯度下降（Gradient Descent） | 优化算法 |
| 范函 / 泛含 | 泛函（Functional） | 数学分析 |
| 柯西不等式 / 科西不等式 | 柯西不等式（Cauchy Inequality） | 高等数学 |
| 拉格朗日乘子 / 拉个朗日 | 拉格朗日乘子（Lagrange Multiplier） | 最优化 |
| 泰勒展式 / 太勒展开 | 泰勒展开（Taylor Expansion） | 微积分 |
| 蒙特卡洛 / 蒙特卡罗摸拟 | 蒙特卡罗模拟（Monte Carlo） | 统计模拟 |
| 帕累托最优 / 怕累托 | 帕累托最优（Pareto Optimality） | 多目标优化 |
| 异方差 / 一方差 | 异方差（Heteroscedasticity） | 计量与统计建模 |
