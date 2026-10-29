# arXiv astro-ph.HE 高能宇宙线物理每日速递

🤖 **全自动** | 每个工作日 UTC 21:00（北京时间 05:00）自动抓取

自动从 [arXiv astro-ph.HE](https://arxiv.org/list/astro-ph.HE/new) 抓取新论文，筛选与**高能宇宙线物理**相关的论文并生成中文总结。

## 📋 目录

| 日期 | 文件 |
| 2026-10-29 | [今日总结](./2026-10-29.md) |
|------|------|
| 2026-10-28 | [今日总结](./2026-10-28.md) |

## 🔍 筛选标准

从 astro-ph.HE 所有新论文中，筛选与以下方向**直接相关**的论文：

- **UHECR 探测**: GRAND, Auger, Telescope Array 等
- **宇宙线加速机制**: 激波加速、磁重联、剪切加速等
- **γ 射线天文**: TeV 耀变体、脉冲星风云等
- **中微子天文**: 高能中微子源、中微子探测
- **暗物质-宇宙线交叉**: 增强暗物质、宇宙线散射等
- **CR 能谱模拟**: Fokker-Planck 求解、传播模型

## 📂 仓库结构

```
arxiv-cosmicray-daily/
├── README.md                       # 本文件
├── YYYY-MM-DD.md                   # 每日论文总结
├── fetch_cosmicray_papers.py       # 抓取脚本
└── .github/workflows/daily-fetch.yml  # GitHub Actions 自动任务
```

## 🚀 自动化说明

通过 GitHub Actions 实现全自动运行：

- **触发时间**: 每个工作日 UTC 21:00（arXiv 更新后 1 小时）
- **流程**: 抓取 → 筛选 → 生成 Markdown → 自动提交
- **手动触发**: Actions 页面 → Daily Cosmic Ray Papers → Run workflow

## 🛠️ 本地使用

```bash
# 手动抓取今天的论文
python3 fetch_cosmicray_papers.py .
```

---

*由 [Vibe Research](https://github.com/fork-svg) 自动维护*
