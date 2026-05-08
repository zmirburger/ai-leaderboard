#!/usr/bin/env python3
"""
refresh.py — daily refresh for the AI Leader Dashboard.

Strategy:
- Vendor release pages are the highest-value scrape target.
- Benchmark leaderboards are JS-rendered; manual refresh on demand.
- Each (vendor, tier) pair has its own detector function.
- Downgrade guard: only accept a detected name if version is strictly newer.
- Tiebreaker: when version string lengths tie, numerically higher version wins.
- recompute_rankings() auto-updates best_overall and best_per_priority from scores.
"""

from __future__ import annotations
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

DATA_PATH = Path(__file__).parent / "data.json"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; AILeaderDashboard/1.0; +https://github.com/zmirburger/ai-leaderboard)"
}
TIMEOUT = 20

# ---------- helpers ----------

def fetch(url):
    try:
        r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
        return r.text
    except Exception as e:
        print(f"  fetch failed: {url} - {e}", file=sys.stderr)
        return None

def load_data():
    return json.loads(DATA_PATH.read_text(encoding="utf-8"))

def save_data(data):
    DATA_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

def _extract_iso_date(text):
    date_match = re.search(r"(\w+ \d{1,2}, \d{4})", text[:2000])
    if not date_match:
        return ""
    try:
        return datetime.strptime(date_match.group(1), "%B %d, %Y").date().isoformat()
    except ValueError:
        return ""

def _parse_version(name):
    """Extract (major, minor) from a model name for downgrade protection."""
    m = re.search(r'(\d+)(?:\.(\d+))?', name)
    if not m:
        return (0, 0)
    return (int(m.group(1)), int(m.group(2)) if m.group(2) else 0)

def _find_best_match(soup, pattern):
    """Find ALL matches in headings (preferred) or body; pick the most specific.
    For tuple matches, scores by string length then numeric version as tiebreaker."""
    headings = " | ".join(h.get_text(" ", strip=True) for h in soup.find_all(["h1", "h2", "h3"]))
    matches = re.findall(pattern, headings)
    if not matches:
        matches = re.findall(pattern, soup.get_text(" ", strip=True))
    if not matches:
        return None
    if isinstance(matches[0], tuple):
        return max(matches, key=lambda m: (sum(len(str(g).strip()) for g in m), _parse_version(m[0])))
    return max(matches, key=len)

def _result(name, soup_text, url):
    return (name, _extract_iso_date(soup_text), "(Auto-detected from release notes - full changelog at link)", url)

# ---------- Anthropic ----------

_ANTHROPIC_URL = "https://platform.claude.com/docs/en/release-notes/overview"
_anthropic_soup = None

def _get_anthropic_soup():
    global _anthropic_soup
    if _anthropic_soup is None:
        html = fetch(_ANTHROPIC_URL)
        _anthropic_soup = BeautifulSoup(html, "html.parser") if html else None
    return _anthropic_soup

def detect_anthropic_opus():
    soup = _get_anthropic_soup()
    if not soup:
        return None
    version = _find_best_match(soup, r"Claude Opus (\d(?:\.\d)?)\b(?!\d)")
    if not version:
        return None
    return _result(f"Claude Opus {version}", soup.get_text(" ", strip=True), _ANTHROPIC_URL)

def detect_anthropic_sonnet():
    soup = _get_anthropic_soup()
    if not soup:
        return None
    version = _find_best_match(soup, r"Claude Sonnet (\d(?:\.\d)?)\b(?!\d)")
    if not version:
        return None
    return _result(f"Claude Sonnet {version}", soup.get_text(" ", strip=True), _ANTHROPIC_URL)

def detect_anthropic_haiku():
    soup = _get_anthropic_soup()
    if not soup:
        return None
    version = _find_best_match(soup, r"Claude Haiku (\d(?:\.\d)?)\b(?!\d)")
    if not version:
        return None
    return _result(f"Claude Haiku {version}", soup.get_text(" ", strip=True), _ANTHROPIC_URL)

# ---------- OpenAI ----------

def detect_openai():
    url = "https://help.openai.com/en/articles/9624314-model-release-notes"
    html = fetch(url)
    if not html:
        return None
    soup = BeautifulSoup(html, "html.parser")
    version = _find_best_match(soup, r"GPT-(\d(?:\.\d)?)\b(?!\d)")
    if not version:
        return None
    return _result(f"GPT-{version}", soup.get_text(" ", strip=True), url)

# ---------- Google ----------

_GOOGLE_URL = "https://ai.google.dev/gemini-api/docs/changelog"
_google_soup = None

def _get_google_soup():
    global _google_soup
    if _google_soup is None:
        html = fetch(_GOOGLE_URL)
        _google_soup = BeautifulSoup(html, "html.parser") if html else None
    return _google_soup

def detect_gemini_pro():
    soup = _get_google_soup()
    if not soup:
        return None
    version = _find_best_match(soup, r"Gemini (\d(?:\.\d)?) Pro\b(?!\d)")
    if not version:
        return None
    return _result(f"Gemini {version} Pro", soup.get_text(" ", strip=True), _GOOGLE_URL)

def detect_gemini_thinking():
    soup = _get_google_soup()
    if not soup:
        return None
    best = _find_best_match(soup, r"Gemini (\d(?:\.\d)?) Flash Thinking\b")
    if not best:
        return None
    version = best if isinstance(best, str) else best[0]
    return _result(f"Gemini {version} Flash Thinking", soup.get_text(" ", strip=True), _GOOGLE_URL)

def detect_gemini_flash():
    soup = _get_google_soup()
    if not soup:
        return None
    # Exclude "Flash Thinking" matches — only plain Flash
    best = _find_best_match(soup, r"Gemini (\d(?:\.\d)?) Flash\b(?! Thinking)")
    if not best:
        return None
    version = best if isinstance(best, str) else best[0]
    return _result(f"Gemini {version} Flash", soup.get_text(" ", strip=True), _GOOGLE_URL)

# ---------- xAI ----------

_XAI_URL = "https://docs.x.ai/developers/release-notes"
_xai_soup = None

def _get_xai_soup():
    global _xai_soup
    if _xai_soup is None:
        html = fetch(_XAI_URL)
        _xai_soup = BeautifulSoup(html, "html.parser") if html else None
    return _xai_soup

def detect_grok_expert():
    soup = _get_xai_soup()
    if not soup:
        return None
    best = _find_best_match(soup, r"Grok[ -]?(\d(?:\.\d)?)\s+Expert\b(?!\d)")
    if not best:
        return None
    version = best if isinstance(best, str) else best[0]
    return _result(f"Grok {version} Expert", soup.get_text(" ", strip=True), _XAI_URL)

def detect_grok_fast():
    soup = _get_xai_soup()
    if not soup:
        return None
    best = _find_best_match(soup, r"Grok[ -]?(\d(?:\.\d)?)\s+Fast\b(?!\d)")
    if not best:
        return None
    version = best if isinstance(best, str) else best[0]
    return _result(f"Grok {version} Fast", soup.get_text(" ", strip=True), _XAI_URL)

# ---------- tier detector registry ----------

TIER_DETECTORS = {
    ("Anthropic", "Opus"):    detect_anthropic_opus,
    ("Anthropic", "Sonnet"):  detect_anthropic_sonnet,
    ("Anthropic", "Haiku"):   detect_anthropic_haiku,
    ("Google",    "Pro"):     detect_gemini_pro,
    ("Google",    "Thinking"):detect_gemini_thinking,
    ("Google",    "Flash"):   detect_gemini_flash,
    ("OpenAI",    "GPT"):     detect_openai,
    ("xAI",       "Expert"):  detect_grok_expert,
    ("xAI",       "Fast"):    detect_grok_fast,
}

# ---------- main logic ----------

def update_releases(data):
    changes = []
    for (vendor, tier), fn in TIER_DETECTORS.items():
        print(f"Checking {vendor} / {tier}...")
        result = fn()
        if not result:
            print(f"  skipped (no parse)")
            continue
        name, date, changelog, url = result
        existing = next(
            (m for m in data["models"] if m["vendor"] == vendor and m.get("tier") == tier),
            None,
        )
        if not existing:
            print(f"  no entry for {vendor}/{tier} in data.json")
            continue
        if existing["name"] != name:
            old = existing["name"]
            if _parse_version(name) <= _parse_version(old):
                print(f"  detected {name} but keeping {old} (not a newer version)")
                continue
            existing["previous"] = old
            existing["name"] = name
            if date:
                existing["released"] = date
            existing["changelog"] = changelog
            existing["release_notes_url"] = url
            changes.append(f"{vendor}/{tier}: {old} -> {name}")
            print(f"  NEW RELEASE: {old} -> {name}")
        else:
            print(f"  no change ({name})")
    return changes

def recompute_rankings(data):
    """Recompute composite_overall for all models and update best_overall/best_per_priority."""
    w = data["weights"]
    for m in data["models"]:
        pp = m["per_priority"]
        m["composite_overall"] = round(
            pp["accuracy"] * w["accuracy"]
            + pp["long_context"] * w["long_context"]
            + pp["agent"] * w["agent"]
        )
    best = max(data["models"], key=lambda m: m["composite_overall"])
    data["best_overall"]["model"] = best["name"]
    data["best_overall"]["composite"] = best["composite_overall"]
    for priority in ["agent", "accuracy", "long_context"]:
        top = max(data["models"], key=lambda m: m["per_priority"][priority])
        data["best_per_priority"][priority]["model"] = top["name"]

def update_benchmarks(data):
    print("\nBenchmark scores - manual refresh recommended (sites are JS-rendered).")
    return []

def main():
    data = load_data()
    print(f"Loaded data.json (last updated: {data['last_updated']})\n")

    print("=== Vendor release detection ===")
    release_changes = update_releases(data)

    print("\n=== Benchmark scores ===")
    benchmark_changes = update_benchmarks(data)

    print("\n=== Rankings ===")
    recompute_rankings(data)

    print("\n=== Summary ===")
    # Always update last_updated so the dashboard shows today's check date,
    # even when no model releases changed.
    data["last_updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    data["data_status"] = "auto_refreshed"
    save_data(data)
    if release_changes or benchmark_changes:
        print("Changes:")
        for c in release_changes:
            print(f"  - {c}")
    else:
        print("No model changes detected.")
    print(f"\ndata.json updated. Last refresh stamp: {data['last_updated']}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
