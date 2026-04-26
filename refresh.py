#!/usr/bin/env python3
"""
refresh.py — daily refresh for the AI Leader Dashboard.

Strategy:
- Vendor release pages are the highest-value scrape target.
- Benchmark leaderboards are JS-rendered; manual refresh on demand.
- Anti-race rule: only write data.json when something actually changed.
- Tight version regex: single-digit major.minor only (4.7, 5.5, 3.1) — rejects
  date fragments like "4.20" that come from "April 20" being concatenated.
- findall + scoring: when a page mentions both "Gemini 3 Pro" (brand) and
  "Gemini 3.1 Pro" (release), pick the most specific (longest version string).
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

def _find_best_match(soup, pattern):
    """Find ALL matches in headings (preferred) or body; pick the most specific.
    For tuple matches, scores by total length of captured groups (longer + has
    Beta suffix wins). For string matches, by length."""
    headings = " | ".join(h.get_text(" ", strip=True) for h in soup.find_all(["h1", "h2", "h3"]))
    matches = re.findall(pattern, headings)
    if not matches:
        matches = re.findall(pattern, soup.get_text(" ", strip=True))
    if not matches:
        return None
    if isinstance(matches[0], tuple):
        return max(matches, key=lambda m: sum(len(str(g).strip()) for g in m))
    return max(matches, key=len)

# ---------- vendor release detection ----------
# Tight pattern: single-digit major, optional single-digit minor.
# Rejects "4.20" etc. (date fragments). Real model versions all fit.

def detect_anthropic():
    url = "https://platform.claude.com/docs/en/release-notes/overview"
    html = fetch(url)
    if not html:
        return None
    soup = BeautifulSoup(html, "html.parser")
    version = _find_best_match(soup, r"Claude Opus (\d(?:\.\d)?)\b(?!\d)")
    if not version:
        return None
    return (
        f"Claude Opus {version}",
        _extract_iso_date(soup.get_text(" ", strip=True)),
        "(Auto-detected from release notes - full changelog at link)",
        url,
    )

def detect_openai():
    url = "https://help.openai.com/en/articles/9624314-model-release-notes"
    html = fetch(url)
    if not html:
        return None
    soup = BeautifulSoup(html, "html.parser")
    version = _find_best_match(soup, r"GPT-(\d(?:\.\d)?)\b(?!\d)")
    if not version:
        return None
    return (
        f"GPT-{version}",
        _extract_iso_date(soup.get_text(" ", strip=True)),
        "(Auto-detected from release notes - full changelog at link)",
        url,
    )

def detect_google():
    url = "https://ai.google.dev/gemini-api/docs/changelog"
    html = fetch(url)
    if not html:
        return None
    soup = BeautifulSoup(html, "html.parser")
    version = _find_best_match(soup, r"Gemini (\d(?:\.\d)?) Pro\b(?!\d)")
    if not version:
        return None
    return (
        f"Gemini {version} Pro",
        _extract_iso_date(soup.get_text(" ", strip=True)),
        "(Auto-detected from changelog - full notes at link)",
        url,
    )

def detect_xai():
    url = "https://docs.x.ai/developers/release-notes"
    html = fetch(url)
    if not html:
        return None
    soup = BeautifulSoup(html, "html.parser")
    best = _find_best_match(soup, r"Grok[ -]?(\d(?:\.\d)?)(\s+Beta)?\b(?!\d)")
    if not best:
        return None
    version, suffix = best[0], best[1].strip()
    name = f"Grok {version}" + (f" {suffix}" if suffix else "")
    return (
        name,
        _extract_iso_date(soup.get_text(" ", strip=True)),
        "(Auto-detected from release notes - full changelog at link)",
        url,
    )

# ---------- main ----------

def update_releases(data):
    changes = []
    detectors = {
        "Anthropic": detect_anthropic,
        "OpenAI": detect_openai,
        "Google": detect_google,
        "xAI": detect_xai,
    }
    for vendor, fn in detectors.items():
        print(f"Checking {vendor}...")
        result = fn()
        if not result:
            print(f"  skipped (no parse)")
            continue
        name, date, changelog, url = result
        existing = next((m for m in data["models"] if m["vendor"] == vendor), None)
        if not existing:
            print(f"  no entry for {vendor} in data.json")
            continue
        if existing["name"] != name:
            old = existing["name"]
            existing["previous"] = old
            existing["name"] = name
            if date:
                existing["released"] = date
            existing["changelog"] = changelog
            existing["release_notes_url"] = url
            changes.append(f"{vendor}: {old} -> {name}")
            print(f"  NEW RELEASE: {old} -> {name}")
        else:
            print(f"  no change ({name})")
    return changes

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

    print("\n=== Summary ===")
    if release_changes or benchmark_changes:
        data["last_updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        data["data_status"] = "auto_refreshed"
        save_data(data)
        print("Changes:")
        for c in release_changes:
            print(f"  - {c}")
        print(f"\ndata.json updated. Last refresh stamp: {data['last_updated']}")
    else:
        print("No changes detected - leaving data.json untouched (skips commit, avoids race).")
    return 0

if __name__ == "__main__":
    sys.exit(main())
