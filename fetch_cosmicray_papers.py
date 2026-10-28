#!/usr/bin/env python3
"""
fetch_cosmicray_papers.py
从 arXiv astro-ph.HE 抓取今日新论文，筛选与高能宇宙线物理相关的论文，
自动生成带中文总结、分类、重点推荐的 Markdown 报告。

Usage:
    python3 fetch_cosmicray_papers.py [output_dir]

Output:
    YYYY-MM-DD.md - 中文 Markdown 总结文件
"""

import re
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from collections import Counter


# ============================================================================
# 中英文术语对照表
# ============================================================================
TERM_ZH = {
    # 核心术语
    "cosmic ray": "宇宙线",
    "cosmic rays": "宇宙线",
    "ultra-high-energy cosmic ray": "超高能宇宙线",
    "UHECR": "超高能宇宙线",
    "air shower": "空气簇射",
    "extensive air shower": "广延大气簇射",
    "EAS": "广延大气簇射",

    # 加速机制
    "particle acceleration": "粒子加速",
    "shock acceleration": "激波加速",
    "diffusive shock acceleration": "扩散激波加速",
    "DSA": "扩散激波加速",
    "Fermi acceleration": "费米加速",
    "magnetic reconnection": "磁重联",
    "shear acceleration": "剪切加速",
    "magnetic pumping": "磁泵浦加速",
    "stochastic acceleration": "随机加速",

    # 天体源
    "blazar": "耀变体",
    "blazars": "耀变体",
    "FSRQ": "平谱射电类星体",
    "BL Lac": "BL Lacertae 天体",
    "pulsar": "脉冲星",
    "magnetar": "磁星",
    "pulsar wind nebula": "脉冲星风云",
    "PWN": "脉冲星风云",
    "supernova remnant": "超新星遗迹",
    "SNR": "超新星遗迹",
    "AGN": "活动星系核",
    "active galactic nuclei": "活动星系核",
    "GRB": "伽马射线暴",
    "gamma-ray burst": "伽马射线暴",
    "FRB": "快速射电暴",
    "fast radio burst": "快速射电暴",

    # 探测器/实验
    "Pierre Auger Observatory": "Pierre Auger 天文台",
    "Auger": "Auger",
    "Telescope Array": "望远镜阵列",
    "IceCube": "IceCube",
    "KM3NeT": "KM3NeT",
    "Fermi-LAT": "Fermi-LAT",
    "CTA": "CTA",
    "LHAASO": "LHAASO",
    "GRAND": "GRAND",

    # 辐射过程
    "synchrotron": "同步辐射",
    "inverse Compton": "逆康普顿",
    "hadronic": "强子",
    "leptonic": "轻子",
    "pair production": "对产生",
    "Bremsstrahlung": "轫致辐射",

    # 暗物质/新物理
    "dark matter": "暗物质",
    "boosted dark matter": "增强暗物质",
    "WIMP": "弱作用大质量粒子",
    "axion": "轴子",
    "neutrino": "中微子",

    # 观测手段
    "gamma-ray": "γ射线",
    "gamma ray": "γ射线",
    "X-ray": "X射线",
    "radio": "射电",
    "TeV": "TeV",
    "PeV": "PeV",
    "EeV": "EeV",
    "very high energy": "甚高能",
    "VHE": "甚高能",

    # 数值方法
    "Fokker-Planck": "Fokker-Planck",
    "MHD": "磁流体力学",
    "PIC": "粒子-in-cell",
    "Monte Carlo": "蒙特卡罗",
}


# ============================================================================
# 分类规则
# ============================================================================
CATEGORIES = {
    "UHECR 探测": [
        r"\bUHECR\b", r"\bUHE\b", r"ultra[- ]high[- ]energy cosmic",
        r"extensive air shower", r"\bEAS\b", r"air shower",
        r"arrival direction", r"energy spectrum.*cosmic", r"composition.*cosmic",
        r"\bAuger\b", r"\bTelescope Array\b", r"\bTA\b(?!\w)",
        r"\bGRAND\b", r"fluorescence.*detector", r"surface detector",
        r"radio.*shower", r"shower.*radio",
    ],
    "宇宙线加速": [
        r"particle acceleration", r"particle acceleration",
        r"shock acceleration", r"diffusive shock", r"\bDSA\b",
        r"Fermi acceleration", r"shear acceleration",
        r"magnetic pumping", r"stochastic acceleration",
        r"maximum.*energy.*proton", r"maximum.*energy.*nucle",
        r"acceleration.*mechanism", r"acceleration.*site",
        r"cosmic[- ]ray.*origin", r"origin.*cosmic[- ]ray",
    ],
    "γ射线天文": [
        r"\bTeV blazar", r"\bblazar\b", r"\bFSRQ\b", r"\bBL Lac",
        r"\bFermi[- ]LAT\b", r"gamma[- ]ray source", r"γ[- ]ray source",
        r"\bCTA\b", r"\bLHAASO\b", r"TeV.*source",
        r"pulsar wind nebula", r"\bPWN\b", r"supernova remnant",
        r"\bSNR\b(?!\w)", r"\bAGN\b",
    ],
    "中微子天文": [
        r"high[- ]energy neutrino", r"cosmogenic neutrino",
        r"neutrino telescope", r"\bIceCube\b", r"\bKM3NeT\b",
        r"neutrino.*flux", r"neutrino.*source",
        r"tau neutrino", r"muon neutrino",
        r"neutrino.*oscillation",
    ],
    "暗物质与宇宙线": [
        r"boosted dark matter", r"\bDM\b(?=\s|[-(])",
        r"dark matter.*cosmic", r"cosmic.*dark matter",
        r"WIMP", r"axion",
        r"dark matter.*decay", r"dark matter.*annihil",
        r"superheavy dark", r"exotic.*particle",
    ],
    "CR 能谱与传播": [
        r"cosmic[- ]ray.*spectrum", r"spectrum.*cosmic[- ]ray",
        r"cosmic[- ]ray.*propagation", r"propagation.*cosmic[- ]ray",
        r"\bFokker[- ]Planck\b", r"transport.*cosmic",
        r"diffusion.*cosmic", r"cosmic[- ]ray.*diffusion",
        r"energy loss", r"cooling.*electron", r"electron.*cooling",
        r"secondary.*nucle", r"secondary.*production",
    ],
}


# ============================================================================
# 重点论文评分规则
# ============================================================================
HIGHLIGHT_PATTERNS = [
    # 实验结果/发现
    (r"\b(first|discovery|evidence|detection|observation)\b", 3),
    (r"\b(candidates|first look|inaugural)\b", 2),
    # 大型实验相关
    (r"\b(Auger|GRAND|IceCube|LHAASO|CTA|Telescope Array|KM3NeT|Fermi-LAT)\b", 2),
    # 重大物理结论
    (r"\b(break|tension|anomaly|challenge|paradigm)\b", 2),
    (r"\b(constrain|limit|upper bound)\b.*(new|first)\b", 2),
    # 新机制/新模型
    (r"\b(new|novel|first)\b.*(mechanism|model|method|approach)\b", 2),
    # 综述
    (r"\b(review|comprehensive)\b", 1),
]


# ============================================================================
# 数据抓取
# ============================================================================
def fetch_arxiv_html(category: str = "astro-ph.HE") -> str:
    """Fetch arXiv new listings HTML."""
    url = f"https://arxiv.org/list/{category}/new"
    req = urllib.request.Request(url, headers={"User-Agent": "arxiv-cosmicray-daily/1.0"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        return resp.read().decode("utf-8")


def parse_papers(html: str) -> list[dict]:
    """Parse paper entries from arXiv HTML."""
    blocks = re.findall(r'<dt>(.*?)</dt>\s*<dd>(.*?)</dd>', html, re.DOTALL)
    papers = []
    for dt, dd in blocks:
        id_match = re.search(r'arXiv:(\d+\.\d+)', dt)
        if not id_match:
            continue

        arxiv_id = id_match.group(1)

        title_match = re.search(r"list-title.*?Title:</span>\s*(.*?)</div>", dd, re.DOTALL)
        title = re.sub(r'\s+', ' ', title_match.group(1).strip()) if title_match else ""
        title = re.sub(r'<[^>]+>', '', title)

        auth_match = re.search(r"list-authors'>(.*?)</div>", dd, re.DOTALL)
        if auth_match:
            authors = re.findall(r'>([^<]+)</a>', auth_match.group(1))
            authors_str = ", ".join(authors)
        else:
            authors_str = "Unknown"

        subj_match = re.search(r"list-subjects.*?Subjects:</span>\s*(.*?)</div>", dd, re.DOTALL)
        subjects = re.sub(r'<[^>]+>', '', subj_match.group(1)).strip() if subj_match else ""
        subjects = re.sub(r'\s+', ' ', subjects)

        abs_match = re.search(r'<p class=["\']mathjax["\']>\s*(.*?)\s*</p>', dd, re.DOTALL)
        abstract = re.sub(r'<[^>]+>', '', abs_match.group(1)).strip() if abs_match else ""
        abstract = re.sub(r'\s+', ' ', abstract)

        papers.append({
            "id": arxiv_id,
            "title": title,
            "authors": authors_str,
            "subjects": subjects,
            "abstract": abstract,
        })
    return papers


# ============================================================================
# 筛选与分类
# ============================================================================
def matches_any(text: str, patterns: list[str]) -> bool:
    """Check if text matches any of the regex patterns."""
    return any(re.search(p, text, re.IGNORECASE) for p in patterns)


def get_categories(paper: dict) -> list[str]:
    """Determine which categories a paper belongs to."""
    text = paper["title"] + " " + paper["abstract"]
    cats = []
    for cat_name, patterns in CATEGORIES.items():
        if matches_any(text, patterns):
            cats.append(cat_name)
    return cats if cats else ["其他相关"]


def score_paper(paper: dict) -> int:
    """Score a paper for highlight priority."""
    text = paper["title"] + " " + paper["abstract"]
    score = 0
    for pattern, weight in HIGHLIGHT_PATTERNS:
        matches = re.findall(pattern, text, re.IGNORECASE)
        score += len(matches) * weight
    return score


def filter_and_enrich(papers: list[dict]) -> list[dict]:
    """Filter cosmic-ray related papers and enrich with metadata."""
    result = []
    for p in papers:
        text = p["title"] + " " + p["abstract"]

        # Basic keyword filter
        basic_keywords = [
            "cosmic ray", "cosmic-ray", "UHECR", "air shower",
            "particle acceleration", "acceleration mechanism",
            "gamma-ray", "γ-ray", "TeV", "blazar",
            "pulsar wind", "supernova remnant",
            "high-energy neutrino", "neutrino telescope",
            "dark matter", "Fokker-Planck", "shear acceleration",
            "magnetic reconnection", "synchrotron", "inverse Compton",
            "Auger", "Telescope Array", "IceCube", "GRAND", "KM3NeT",
            "LHAASO", "CTA", "Fermi-LAT",
            "non-thermal", "hadronic", "cosmogenic",
        ]
        if not any(kw.lower() in text.lower() for kw in basic_keywords):
            continue

        cats = get_categories(p)
        score = score_paper(p)
        is_highlight = score >= 3

        result.append({
            **p,
            "categories": cats,
            "score": score,
            "highlight": is_highlight,
        })

    # Sort by score descending
    result.sort(key=lambda x: x["score"], reverse=True)
    return result


# ============================================================================
# 中文翻译 / 摘要提取
# ============================================================================
def translate_abstract_short(abstract: str, max_sentences: int = 2) -> str:
    """Extract key sentences from abstract and translate common terms to Chinese."""
    if not abstract:
        return ""

    # Take first N sentences
    sentences = re.split(r'(?<=[.!?])\s+', abstract)
    key_sents = sentences[:max_sentences]
    text = " ".join(key_sents)

    # Apply term mapping (longest first to avoid partial replacements)
    sorted_terms = sorted(TERM_ZH.keys(), key=len, reverse=True)
    for en, zh in [(t, TERM_ZH[t]) for t in sorted_terms]:
        # Use word boundaries for English terms
        pattern = r'\b' + re.escape(en) + r'\b'
        text = re.sub(pattern, zh, text, flags=re.IGNORECASE)

    return text


def translate_title(title: str) -> str:
    """Translate title using term dictionary."""
    sorted_terms = sorted(TERM_ZH.keys(), key=len, reverse=True)
    result = title
    for en in sorted_terms:
        zh = TERM_ZH[en]
        pattern = r'\b' + re.escape(en) + r'\b'
        result = re.sub(pattern, zh, result, flags=re.IGNORECASE)
    return result


def build_category_description(cat: str) -> str:
    """Get Chinese description for each category."""
    return {
        "UHECR 探测": "超高能宇宙线直接探测实验与方法",
        "宇宙线加速": "宇宙线在天体物理源中的加速机制",
        "γ射线天文": "TeV/γ射线源观测与研究",
        "中微子天文": "高能中微子源与探测",
        "暗物质与宇宙线": "暗物质与宇宙线物理的交叉研究",
        "CR 能谱与传播": "宇宙线能谱测量、传播模型与辐射机制",
        "其他相关": "与高能宇宙线物理间接相关的论文",
    }.get(cat, "")


# ============================================================================
# Markdown 生成
# ============================================================================
def generate_markdown(papers: list[dict], date: str, total_count: int) -> str:
    """Generate a structured Chinese markdown summary."""
    highlights = [p for p in papers if p["highlight"]]
    if not highlights and papers:
        # Take top 3 by score as highlights
        highlights = papers[:min(3, len(papers))]

    lines = [
        f"# arXiv astro-ph.HE 高能宇宙线物理每日速递",
        "",
        f"**日期**: {date}",
        "",
        f"**来源**: [arXiv astro-ph.HE new listings](https://arxiv.org/list/astro-ph.HE/new)",
        "",
        f"**筛选范围**: 与高能宇宙线物理直接相关的论文（UHECR、CR 加速、γ射线天文、中微子天文、暗物质-宇宙线交叉等）",
        "",
        f"**统计**: astro-ph.HE 共 {total_count} 篇 → 筛选出 **{len(papers)}** 篇相关论文",
        "",
        "---",
        "",
        "## 📋 今日总览",
        "",
        f"今日共 {len(papers)} 篇与高能宇宙线物理直接相关的论文。",
    ]

    # Category overview
    cat_counter = Counter()
    for p in papers:
        for c in p["categories"]:
            cat_counter[c] += 1

    lines.append("")
    lines.append("**方向分布**:")
    for cat, count in cat_counter.most_common():
        lines.append(f"- {cat}: {count} 篇")

    lines.extend(["", "---", ""])

    # Highlights section
    if highlights:
        lines.append(f"## 🔥 今日重点 ({len(highlights)} 篇)")
        lines.append("")
        for i, p in enumerate(highlights, 1):
            zh_title = translate_title(p["title"])
            zh_abs = translate_abstract_short(p["abstract"], 2)
            cats_str = " / ".join(p["categories"])

            lines.extend([
                f"### {i}. {p['title']}",
                "",
                f"**中文标题**: {zh_title}",
                f"**arXiv**: [{p['id']}](https://arxiv.org/abs/{p['id']})",
                f"**作者**: {p['authors'][:150]}{'...' if len(p['authors']) > 150 else ''}",
                f"**分类**: {cats_str}",
                "",
                f"**摘要要点**: {zh_abs}",
                "",
                "---",
                "",
            ])

    # Category sections
    lines.append("## 📚 按方向分类")
    lines.append("")

    for cat in list(CATEGORIES.keys()) + ["其他相关"]:
        cat_papers = [p for p in papers if cat in p["categories"]]
        if not cat_papers:
            continue

        cat_desc = build_category_description(cat)
        lines.extend([
            f"### {cat} ({len(cat_papers)} 篇)",
            "",
            f"*{cat_desc}*",
            "",
        ])

        for p in cat_papers:
            zh_abs = translate_abstract_short(p["abstract"], 1)
            lines.extend([
                f"- **[{p['id']}]** {p['title']}",
                f"  - {p['authors'][:80]}{'...' if len(p['authors']) > 80 else ''}",
                f"  - {zh_abs[:250]}{'...' if len(zh_abs) > 250 else ''}",
                "",
            ])

    lines.extend([
        "---",
        "",
        "## 📊 统计表格",
        "",
        "| 方向 | 论文数 |",
        "|------|--------|",
    ])
    for cat, count in cat_counter.most_common():
        lines.append(f"| {cat} | {count} |")
    lines.extend([
        f"| **总计** | **{len(papers)}** |",
        "",
        "---",
        "",
        "## 🔗 相关链接",
        "",
        "- [arXiv astro-ph.HE 今日新论文](https://arxiv.org/list/astro-ph.HE/new)",
        "- [arXiv astro-ph 全部今日论文](https://arxiv.org/list/astro-ph/new)",
        "",
        "---",
        "",
        f"*本文档由 GitHub Actions 自动生成于 {date}*",
        f"*自动筛选 + 分类 + 中文术语翻译*",
    ])

    return "\n".join(lines)


# ============================================================================
# Main
# ============================================================================
def main():
    output_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
    output_dir.mkdir(parents=True, exist_ok=True)

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    print(f"[1/5] Fetching arXiv astro-ph.HE new listings...")
    html = fetch_arxiv_html()

    print(f"[2/5] Parsing papers...")
    all_papers = parse_papers(html)
    total_count = len(all_papers)
    print(f"       Found {total_count} papers total")

    print(f"[3/5] Filtering & classifying cosmic ray related papers...")
    cr_papers = filter_and_enrich(all_papers)
    print(f"       Filtered {len(cr_papers)} papers")
    print(f"       Highlighted {sum(1 for p in cr_papers if p['highlight'])} papers")

    print(f"[4/5] Generating Chinese markdown summary for {today}...")
    md = generate_markdown(cr_papers, today, total_count)

    output_file = output_dir / f"{today}.md"
    output_file.write_text(md, encoding="utf-8")
    print(f"[5/5] Written to: {output_file}")

    # Print summary
    print("\n" + "=" * 60)
    print(f" SUMMARY for {today}")
    print("=" * 60)
    for p in cr_papers:
        marker = "🔥" if p["highlight"] else "  "
        cats = ", ".join(p["categories"])
        print(f"{marker} [{p['id']}] ({cats})")
        print(f"   {p['title'][:80]}")


if __name__ == "__main__":
    main()
