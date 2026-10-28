#!/usr/bin/env python3
"""
fetch_cosmicray_papers.py
从 arXiv astro-ph.HE 抓取今日新论文，筛选与高能宇宙线物理相关的论文。

Usage:
    python3 fetch_cosmicray_papers.py [output_dir]

输出: Markdown 格式的论文总结文件
"""

import re
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


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


# Keywords for filtering cosmic ray related papers
COSMIC_RAY_KEYWORDS = [
    "cosmic ray", "cosmic-ray", "UHECR", "ultra-high-energy",
    "air shower", "extensive air shower", "primary cosmic",
    "particle acceleration", "non-thermal", "acceleration mechanism",
    "Fermi acceleration", "diffusive shock", "shear acceleration",
    "gamma-ray source", "gamma ray source", "TeV", "blazar",
    "pulsar wind", "supernova remnant", "SNR",
    "neutrino telescope", "neutrino astronomy", "high-energy neutrino",
    "dark matter", "boosted dark matter",
    "synchrotron", "inverse Compton", "hadronic",
    "Fokker-Planck", "cosmic-ray spectrum",
    "GRAND", "Auger", "Telescope Array", "Cherenkov",
    "reconnection", "shock", "magnetic pumping",
    "radio detection", "fluorescence",
]


def is_cosmic_ray_related(paper: dict) -> bool:
    """Check if paper is related to high-energy cosmic ray physics."""
    text = (paper["title"] + " " + paper["abstract"]).lower()
    return any(kw.lower() in text for kw in COSMIC_RAY_KEYWORDS)


def generate_markdown(papers: list[dict], date: str, total_count: int) -> str:
    """Generate markdown summary."""
    lines = [
        f"# arXiv astro-ph.HE 高能宇宙线物理每日速递",
        "",
        f"**日期**: {date}",
        "",
        f"**来源**: [arXiv astro-ph.HE new listings](https://arxiv.org/list/astro-ph.HE/new)",
        "",
        f"**筛选范围**: 与高能宇宙线物理（UHECR、CR 加速机制、γ射线天文、中微子天文、暗物质探测）直接相关的论文",
        "",
        f"**今日 astro-ph.HE 总论文数**: {total_count} 篇 | **筛选出**: {len(papers)} 篇",
        "",
        "---",
        "",
    ]

    for i, p in enumerate(papers, 1):
        lines.extend([
            f"## {i}. {p['title']}",
            "",
            f"- **arXiv**: [{p['id']}](https://arxiv.org/abs/{p['id']})",
            f"- **作者**: {p['authors'][:200]}",
            "",
            f"**摘要**: {p['abstract']}",
            "",
            "---",
            "",
        ])

    lines.append(f"*本文档由 Vibe Research 于 {date} 自动生成*")
    return "\n".join(lines)


def main():
    output_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
    output_dir.mkdir(parents=True, exist_ok=True)

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    print(f"Fetching arXiv astro-ph.HE new listings...")
    html = fetch_arxiv_html()

    print("Parsing papers...")
    all_papers = parse_papers(html)
    total_count = len(all_papers)
    print(f"Found {total_count} papers total")

    print("Filtering cosmic ray related papers...")
    cr_papers = [p for p in all_papers if is_cosmic_ray_related(p)]
    print(f"Filtered {len(cr_papers)} cosmic ray related papers")

    print(f"Generating markdown for {today}...")
    md = generate_markdown(cr_papers, today, total_count)

    output_file = output_dir / f"{today}.md"
    output_file.write_text(md, encoding="utf-8")
    print(f"Written to: {output_file}")

    # Also print summary
    print("\n--- Cosmic Ray Related Papers ---")
    for p in cr_papers:
        print(f"  [{p['id']}] {p['title'][:80]}")


if __name__ == "__main__":
    main()
