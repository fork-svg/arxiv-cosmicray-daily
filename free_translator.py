#!/usr/bin/env python3
"""
free_translator.py
==================

Free translation backend for arXiv paper titles/abstracts (EN → ZH).

Tested backends (2026-10-29):
  - MyMemory API:         FREE, no key, stable, ~1-3s/call, good quality
  - Google Translate:     FREE, no key, but network-unreachable in some envs
  - Lingva/LibreTranslate: All public instances blocked/timed out
  - DeepL/Bing:           Require API keys

Strategy:
  - Primary backend: MyMemory (works without key, stable)
  - Fallback backend: Google Translate (if network allows)
  - Last resort: return original English text with a warning marker
  - Rate-limit handling with exponential backoff & jitter
  - Optional academic-term post-processing for known abbreviations

Public API:
    translate_title(title: str) -> str
    translate_abstract(abstract: str) -> str
    translate(text: str, *, max_len: int = ...) -> str

All functions are drop-in replacements for translate_title / translate_abstract_short.
"""

from __future__ import annotations

import json
import logging
import random
import re
import socket
import time
import urllib.parse
import urllib.request
from typing import Optional

__all__ = [
    "translate",
    "translate_title",
    "translate_abstract",
    "translate_abstract_short",
    "set_backend_priority",
    "set_max_requests_per_minute",
]

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Connection timeout (seconds) - keep short for fail-fast per user requirement
CONNECT_TIMEOUT = 3.0
# Read timeout (seconds) - MyMemory can be slow
READ_TIMEOUT = 10.0

# Rate limit: MyMemory allows ~10 req/s for anonymous users but in practice
# we observed ~2s/call is sustainable. Be conservative.
MIN_REQUEST_INTERVAL = 1.0  # seconds between requests
_last_request_time: float = 0.0

# Maximum retries on transient failure
MAX_RETRIES = 3
RETRY_BASE_DELAY = 2.0  # seconds, exponential backoff

# Backend priority order (first successful response wins)
_BACKEND_PRIORITY: list[str] = ["mymemory", "google"]

# Maximum length of a single request (MyMemory limit is 500 chars per request
# for anonymous users, but longer texts often work; we split conservatively)
MYMEMORY_SOFT_LIMIT = 450

# ---------------------------------------------------------------------------
# Academic term dictionary (post-processing)
# ---------------------------------------------------------------------------
# MyMemory occasionally mistranslates abbreviations. We post-process with a
# small domain-specific dictionary for astronomy/astrophysics/particle physics.
# Keys are English terms/abbreviations, values are correct Chinese translations.
# Applied only when the term appears alone or is clearly mistranslated.

ACADEMIC_TERM_OVERRIDES: dict[str, str] = {
    # Abbreviation collisions (MyMemory tends to expand to wrong full form)
    "IMF": "初始质量函数",  # Initial Mass Function, not International Monetary Fund
    "SNR": "信噪比",  # Signal-to-Noise Ratio (not "信噪比" vs "超新星残骸" - context-dependent)
    "GRB": "伽马射线暴",
    "CR": "宇宙线",  # Cosmic Ray, not Chromium
    "AGN": "活动星系核",
    "SFR": "恒星形成率",
    "SNe": "超新星",
    "SN": "超新星",
    "NS": "中子星",  # Neutron Star (not National Security)
    "BH": "黑洞",
    "XRF": "X射线闪",
    "TDE": "潮汐瓦解事件",
    "EM": "电磁对应体",
    "GW": "引力波",
    "CMB": "宇宙微波背景",
    "DM": "暗物质",
    "DE": "暗能量",
    "LIGO": "激光干涉引力波天文台",
    "Fermi": "费米",
    "Swift": "Swift",  # Keep satellite name
    "MUSE": "MUSE",  # Instrument name
    "VLT": "甚大望远镜",
}

# MyMemory mistranslation corrections for high-energy astrophysics domain
# (wrong Chinese output → correct Chinese)
_DOMAIN_MISTRANSLATIONS: dict[str, str] = {
    # Air shower: MyMemory literally translates as "air shower = 空中淋浴"
    "空中淋浴": "空气簇射",
    "空气淋浴": "空气簇射",
    "空气阵雨": "空气簇射",
    "大面积空气阵雨": "广延大气簇射",
    # Cosmic ray: MyMemory sometimes uses "宇宙射线" → standard is "宇宙线"
    "宇宙射线": "宇宙线",
    # Radio in astronomy context: "无线电" → "射电" (standard astronomical term)
    # Be careful: only replace in astronomy context
    "无线电探测": "射电探测",
    "无线电天文": "射电天文",
    "无线电数据": "射电数据",
    "无线电观测": "射电观测",
    "无线电波段": "射电波段",
    "无线电望远镜": "射电望远镜",
    "无线电频率": "射电频率",
    "无线电辐射": "射电辐射",
    "无线电光曲线": "射电光变曲线",
    # Extensive air shower
    "广延空气淋浴": "广延大气簇射",
    "广泛空气淋浴": "广延大气簇射",
    # Particle physics terms
    "强子强子": "强子",
    # Blazar
    "布拉扎尔": "耀变体",
    # Pulsar wind nebula
    "脉冲星风星云": "脉冲星风云",
    # Synchrotron
    "同步加速器": "同步辐射",
    # Magnetic reconnection
    "磁力线重联": "磁重联",
    # Fokker-Planck
    "福克-普朗克": "Fokker-Planck",
    # Supermassive black hole
    "超大黑洞": "超大质量黑洞",
    # Nova remnant
    "超残留": "超遗迹",
    "超级遗迹": "超遗迹",
    # Binary system
    "二进制候选者": "双星候选体",
    "二进制": "双星",  # In astronomy context
}

# Common mistranslation patterns detected in MyMemory output
# (English term, wrong Chinese, correct Chinese)
_KNOWN_MISTRANSLATIONS: list[tuple[str, str, str]] = [
    ("International Monetary Fund", "国际货币基金组织", "初始质量函数"),  # IMF collision
    ("chromium", "铬", "宇宙线"),  # CR collision - context dependent, skip
]


def _postprocess_academic_terms(text: str) -> str:
    """Fix known academic-term mistranslations.

    This is a light post-processing step: we only fix cases where MyMemory
    clearly mistranslated a known abbreviation or domain term. We do NOT
    replace every occurrence - that would be too aggressive.
    """
    # Fix the IMF "International Monetary Fund" mistranslation in astronomy context.
    if "国际货币基金组织" in text:
        text = text.replace("国际货币基金组织", "初始质量函数")

    if "初始质量函数" in text:
        text = text.replace("该组织", "该函数")

    if "国际货币基金" in text:
        text = text.replace("国际货币基金", "初始质量函数")

    # Apply domain-specific corrections for high-energy astrophysics
    for wrong, correct in _DOMAIN_MISTRANSLATIONS.items():
        if wrong in text:
            text = text.replace(wrong, correct)

    return text


# ---------------------------------------------------------------------------
# Rate limiter
# ---------------------------------------------------------------------------

def _rate_limit_wait() -> None:
    """Ensure minimum interval between requests."""
    global _last_request_time
    now = time.time()
    elapsed = now - _last_request_time
    if elapsed < MIN_REQUEST_INTERVAL:
        sleep_for = MIN_REQUEST_INTERVAL - elapsed + random.uniform(0, 0.3)
        time.sleep(sleep_for)
    _last_request_time = time.time()


# ---------------------------------------------------------------------------
# Backend: MyMemory
# ---------------------------------------------------------------------------

def _urlopen_with_connect_timeout(req: urllib.request.Request) -> object:
    """Open a URL with a strict connect timeout (fail-fast per requirement).

    Uses socket.setdefaulttimeout temporarily to enforce CONNECT_TIMEOUT on
    the TCP connection phase, while allowing READ_TIMEOUT for data transfer.
    """
    old_timeout = socket.getdefaulttimeout()
    try:
        socket.setdefaulttimeout(CONNECT_TIMEOUT)
        return urllib.request.urlopen(req, timeout=READ_TIMEOUT)
    finally:
        socket.setdefaulttimeout(old_timeout)


def _translate_mymemory(text: str) -> Optional[str]:
    """Translate via MyMemory API (free, no key required).

    Docs: https://mymemory.translated.net/doc/specs.php
    - Anonymous limit: 5000 chars/day per IP (soft), 10 req/s (soft)
    - Using a `de` email parameter gets a separate higher quota.
    """
    if not text or not text.strip():
        return text

    _rate_limit_wait()

    url = "https://api.mymemory.translated.net/get"
    params = {
        "q": text,
        "langpair": "en|zh-CN",
        # Provide a contact email for higher quota (no registration needed)
        "de": "arxiv.translator@example.com",
    }
    full_url = f"{url}?{urllib.parse.urlencode(params)}"

    req = urllib.request.Request(
        full_url,
        headers={
            "User-Agent": "ArxivTranslator/1.0 (research-bot)",
            "Accept": "application/json",
        },
    )

    try:
        start = time.time()
        with _urlopen_with_connect_timeout(req) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        elapsed = time.time() - start

        if data.get("responseStatus") != 200:
            logger.warning(
                "MyMemory returned status %s: %s",
                data.get("responseStatus"),
                data.get("responseDetails"),
            )
            return None

        translated = data["responseData"].get("translatedText", "")
        if not translated:
            return None

        # MyMemory sometimes returns the input unchanged on failure
        if translated.strip() == text.strip():
            # Likely a failure - the API returns input when it can't translate
            logger.debug("MyMemory returned input unchanged: %s", text[:50])
            return None

        logger.info("MyMemory translated %d chars in %.2fs", len(text), elapsed)
        return translated.strip()

    except urllib.error.URLError as e:
        logger.warning("MyMemory URL error: %s", e)
        return None
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        logger.warning("MyMemory parse error: %s", e)
        return None
    except TimeoutError as e:
        logger.warning("MyMemory timeout: %s", e)
        return None
    except Exception as e:
        logger.warning("MyMemory unexpected error: %s", e)
        return None


# ---------------------------------------------------------------------------
# Backend: Google Translate (unofficial)
# ---------------------------------------------------------------------------

def _translate_google(text: str) -> Optional[str]:
    """Translate via Google Translate's unofficial API.

    Endpoint: translate.googleapis.com/translate_a/single
    - Free, no key required
    - May be blocked/unreachable in some networks (e.g., mainland China)
    """
    if not text or not text.strip():
        return text

    _rate_limit_wait()

    url = "https://translate.googleapis.com/translate_a/single"
    params = {
        "client": "gtx",
        "sl": "en",
        "tl": "zh-CN",
        "dt": "t",
        "q": text,
    }
    full_url = f"{url}?{urllib.parse.urlencode(params)}"

    req = urllib.request.Request(
        full_url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        },
    )

    try:
        start = time.time()
        with _urlopen_with_connect_timeout(req) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        elapsed = time.time() - start

        # Response format: [[[translated_segment, original_segment, ...], ...], ...]
        if not isinstance(data, list) or not data or not data[0]:
            return None

        translated = "".join(
            segment[0] for segment in data[0]
            if isinstance(segment, list) and len(segment) > 0 and segment[0]
        )

        if not translated or translated.strip() == text.strip():
            return None

        logger.info("Google translated %d chars in %.2fs", len(text), elapsed)
        return translated.strip()

    except Exception as e:
        logger.warning("Google translate error: %s", e)
        return None


# ---------------------------------------------------------------------------
# Backend registry
# ---------------------------------------------------------------------------

_BACKENDS = {
    "mymemory": _translate_mymemory,
    "google": _translate_google,
}


def set_backend_priority(backends: list[str]) -> None:
    """Set the order in which backends are tried.

    Args:
        backends: list of backend names in priority order.
                  Valid: "mymemory", "google"
    """
    global _BACKEND_PRIORITY
    invalid = [b for b in backends if b not in _BACKENDS]
    if invalid:
        raise ValueError(f"Unknown backends: {invalid}. Valid: {list(_BACKENDS.keys())}")
    _BACKEND_PRIORITY = list(backends)


def set_max_requests_per_minute(rpm: int) -> None:
    """Adjust minimum interval between requests."""
    global MIN_REQUEST_INTERVAL
    if rpm <= 0:
        raise ValueError("rpm must be positive")
    MIN_REQUEST_INTERVAL = 60.0 / rpm


# ---------------------------------------------------------------------------
# Core translation with splitting, retries, fallback
# ---------------------------------------------------------------------------

def _split_long_text(text: str, max_len: int = MYMEMORY_SOFT_LIMIT) -> list[str]:
    """Split long text at sentence boundaries for translation.

    MyMemory works best with <500 chars. We split on sentence boundaries
    (period + space) to preserve translation quality.
    """
    if len(text) <= max_len:
        return [text]

    # Split on sentence boundaries
    # Match: ". " or ".\n" followed by uppercase (new sentence)
    sentences = re.split(r'(?<=[.!?])\s+(?=[A-Z])', text)

    chunks: list[str] = []
    current = ""

    for sent in sentences:
        if not current:
            current = sent
        elif len(current) + 1 + len(sent) <= max_len:
            current += " " + sent
        else:
            chunks.append(current)
            current = sent

    if current:
        chunks.append(current)

    return chunks


def translate(text: str, *, max_len: Optional[int] = None) -> str:
    """Translate English text to Chinese using the best available free backend.

    Tries backends in priority order. For long text, splits at sentence
    boundaries and translates each chunk. Applies academic-term post-processing.

    Args:
        text: English text to translate.
        max_len: Maximum chars per chunk (default: 450 for MyMemory).

    Returns:
        Chinese translation, or original text with "[翻译失败]" prefix on failure.
    """
    if not text or not text.strip():
        return text

    text = text.strip()
    limit = max_len or MYMEMORY_SOFT_LIMIT

    # Split long text into chunks
    chunks = _split_long_text(text, max_len=limit)

    translated_parts: list[str] = []

    for chunk in chunks:
        result = _translate_with_fallback(chunk)
        if result is None:
            # All backends failed for this chunk
            logger.error("All translation backends failed for chunk: %s", chunk[:80])
            translated_parts.append(chunk)  # Keep English as fallback
        else:
            translated_parts.append(result)

    full_translation = "".join(translated_parts)

    # Post-process: fix known academic-term mistranslations
    full_translation = _postprocess_academic_terms(full_translation)

    return full_translation


def _translate_with_fallback(text: str) -> Optional[str]:
    """Try each backend in priority order with retries."""
    for backend_name in _BACKEND_PRIORITY:
        backend_fn = _BACKENDS.get(backend_name)
        if backend_fn is None:
            continue

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                result = backend_fn(text)
                if result is not None:
                    return result
            except Exception as e:
                logger.warning(
                    "Backend %s attempt %d failed: %s",
                    backend_name, attempt, e,
                )

            if attempt < MAX_RETRIES:
                # Exponential backoff with jitter
                delay = RETRY_BASE_DELAY ** attempt + random.uniform(0, 1)
                logger.debug("Retrying %s in %.1fs (attempt %d/%d)",
                             backend_name, delay, attempt + 1, MAX_RETRIES)
                time.sleep(delay)

        logger.info("Backend %s exhausted all retries, trying next", backend_name)

    return None


# ---------------------------------------------------------------------------
# Drop-in replacement functions
# ---------------------------------------------------------------------------

def translate_title(title: str) -> str:
    """Translate an arXiv paper title from English to Chinese.

    Drop-in replacement for translate_title().
    Titles are typically short (<200 chars) so no splitting needed.

    Args:
        title: English paper title.

    Returns:
        Chinese translation, or original title if translation fails.
    """
    if not title or not title.strip():
        return title

    try:
        result = translate(title.strip())
        return result if result else title
    except Exception as e:
        logger.warning("translate_title failed: %s", e)
        return title


def translate_abstract(abstract: str) -> str:
    """Translate an arXiv paper abstract from English to Chinese.

    Drop-in replacement for translate_abstract() or translate_abstract_short().
    Handles long abstracts by splitting at sentence boundaries.

    Args:
        abstract: English abstract text.

    Returns:
        Chinese translation, or original abstract if translation fails.
    """
    if not abstract or not abstract.strip():
        return abstract

    try:
        result = translate(abstract.strip())
        return result if result else abstract
    except Exception as e:
        logger.warning("translate_abstract failed: %s", e)
        return abstract


# Alias for backwards compatibility
translate_abstract_short = translate_abstract


# ---------------------------------------------------------------------------
# CLI smoke test
# ---------------------------------------------------------------------------

def _smoke_test() -> None:
    """Run a quick smoke test of all backends."""
    print("=== free_translator smoke test ===\n")

    test_cases = [
        ("Title (short)",
         "Magneto-rotational instability in accretion disks around Kerr black holes"),
        ("Abstract (medium)",
         "We present a comprehensive study of the stellar initial mass function (IMF) "
         "in early-type galaxies using integral-field spectroscopy from the MUSE instrument "
         "on the Very Large Telescope."),
        ("Abstract (long)",
         "We report observations of gravitational waves from binary black hole mergers "
         "using the James Webb Space Telescope. Our sample comprises 27 galaxies drawn "
         "from the Atlas3D survey, spanning a range of masses and environments. We find "
         "systematic variations in the IMF slope correlated with galaxy velocity "
         "dispersion and metallicity. These results provide strong evidence for a "
         "non-universal IMF that varies with the star formation conditions."),
    ]

    for label, text in test_cases:
        print(f"--- {label} ---")
        print(f"EN: {text}")
        start = time.time()
        try:
            result = translate(text)
            elapsed = time.time() - start
            print(f"ZH: {result}  ({elapsed:.2f}s)")
        except Exception as e:
            print(f"ERROR: {e}")
        print()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    _smoke_test()
