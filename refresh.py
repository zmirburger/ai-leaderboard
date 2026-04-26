#!/usr/bin/env python3
"""
refresh.py — daily refresh for the AI Leader Dashboard.

Strategy (honest version):
- Vendor release pages are the highest-value, most-reliable scrape target.
  When a new flagship drops (GPT-5.6, Opus 4.8, Gemini 3.2, Grok 5), this
  is what tells you within 24 hours.
- Benchmark leaderboards are heavily JS-rendered. Plain requests doesn't
  see most of them. We stub these with clear TODOs and rely on Claude
  to manually refresh benchmark scores when asked. This keeps the daily
  cron simple and reliable.

Outputs:
- Updates data.json in place
- Prints a status report (what succeeded, what was skipped)
- Exits 0 even on partial failure (we want the cron to complete and commit
  whatever it got)
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

def fetch(url: str) -> str | None:
    try:
        r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
        return r.text
    except Exception as e:
        print(f"  ✗ fetch failed: {url} — {e}", file=sys.stderr)
        return None

def load_data() -> dict:
    return json.loads(DATA_PATH.read_text(encoding="utf-8"))

def save_data(data: dict) -> None:
    DATA_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

# ---------- vendor release detection ----------
# Each function returns (latest_name, release_date_iso, changelog_summary, release_notes_url) or None.

def _extract_iso_date(text: str) -> str:
    """Find first 'Month DD, YYYY' date in the first 2000 chars, return ISO. Empty string if none."""
    date_match = re.search(r"(\w+ \d{1,2}, \d{4})", text[:2000])
    if not date_match:
        return ""
    try:
        return datetime.strptime(date_match.group(1), "%B %d, %Y").date().isoformat()
    except ValueError:
        return ""

def _search_headings_then_body(soup: BeautifulSoup, pattern: str) -> re.Match | None:
    """Try the regex against heading text first (where versions actually live), then full body."""
    headings = " | ".join(h.get_text(" ", strip=True) for h in soup.find_all(["h1", "h2", "h3"]))
    m = re.search(pattern, headings)
    if m:
        return m
    return re.search(pattern, soup.get_text(" ", strip=True))

def detect_anthropic() -> tuple[str, str, str, str] | None:
    """Anthropic publishes release notes as markdown-ish HTML."""
    url = "https://platform.claude.com/docs/en/release-notes/overview"
    html = fetch(url)
    if not html:
        return None
    soup = BeautifulSoup(html, "html.parser")
    # Tight pattern: 1-2 digits for major, optional .1-2 digits for minor, no trailing digit (rejects "4.20" from dates).
    m = _search_headings_then_body(soup, r"Claude Opus (\d{1,2}(?:\.\d{1,2})?)\b(?!\d)")
    if not m:
        return None
    return (
        f"Claude Opus {m.group(1)}",
        _extract_iso_date(soup.get_text(" ", strip=True)),
        "(Auto-detected from release notes — full changelog at link)",
        url,
    )

def detect_openai() -> tuple[str, str, str, str] | None:
    url = "https://help.openai.com/en/articles/9624314-model-release-notes"
    html = fetch(url)
    if not html:
        return None
    soup = BeautifulSoup(html, "html.parser")
    m = _search_headings_then_body(soup, r"GPT-(\d{1,2}(?:\.\d{1,2})?)\b(?!\d)")
    if not m:
        return None
    return (
        f"GPT-{m.group(1)}",
        _extract_iso_date(soup.get_text(" ", strip=True)),
        "(Auto-detected from release notes — full changelog at link)",
        url,
    )

def detect_google() -> tuple[str, str, str, str] | None:
    url = "https://ai.google.dev/gemini-api/docs/changelog"
    html = fetch(url)
    if not html:
        return None
    soup = BeautifulSoup(html, "html.parser")
    m = _search_headings_then_body(soup, r"Gemini (\d{1,2}(?:\.\d{1,2})?) Pro\b(?!\d)")
    if not m:
        return None
    return (
        f"Gemini {m.group(1)} Pro",
        _extract_iso_date(soup.get_text(" ", strip=True)),
        "(Auto-detected from changelog — full notes at link)",
        url,
    )

def detect_xai() -> tuple[str, str, str, str] | None:
    url = "https://docs.x.ai/developers/release-notes"
    html = fetch(url)
    if not html:
        return None
    soup = BeautifulSoup(html, "html.parser")
    # Accepts "Grok 4", "Grok 4.3", "Grok 4.3 Beta", "Grok-4.3"; rejects "Grok 4.20" (date misread).
    m = _search_headings_then_body(soup, r"Grok[ -]?(\d{1,2}(?:\.\d{1,2})?)(\s+Beta)?\b(?!\d)")
    if not m:
        return None
    version = m.group(1)
    suffix = (m.group(2) or "").strip()
    name = f"Grok {version}" + (f" {suffix}" if suffix else "")
    return (
        name,
        _extract_iso_date(soup.get_text(" ", strip=True)),
        "(Auto-detected from release notes — full changelog at link)",
        url,
    )

# ---------- benchmark scrapers (stubs) ----------
# Most leaderboard sites are JS-rendered React apps. Plain requests doesn't
# see the data. To implement properly, use Playwright (heavy) or each site's
# underlying API (varies). For now: stubs that log TODO. Manual benchmark
# refresh: ask Claude "refresh benchmark scores" and Claude will scrape +
# parse using the latest available method.

BENCHMARK_STUBS = [
    "metr_time_horizon",
    "tau_bench",
    "browsecomp",
    "vectara_hhem",
    "aa_omniscience",
    "aa_intelligence_index",
    "scale_seal_rli",
    "fiction_livebench",
    "aa_long_context",
    "aa_ifbench",
]

# ---------- main refresh logic ----------

def update_releases(data: dict) -> list[str]:
    """Detect new model releases and update data['models']. Returns list of changes."""
    changes = []
    detectors = {
        "Anthropic": detect_anthropic,
        "OpenAI": detect_openai,
        "Google": detect_google,
        "xAI": detect_xai,
    }
    for vendor, fn in detectors.items():
        print(f"Checking {vendor}…")
        result = fn()
        if not result:
            print(f"  ⚠ skipped (no parse)")
            continue
        name, date, changelog, url = result
        # Find the model entry for this vendor
        existing = next((m for m in data["models"] if m["vendor"] == vendor), None)
        if not existing:
            print(f"  ⚠ no entry for {vendor} in data.json")
            continue
        if existing["name"] != name:
            old = existing["name"]
            existing["previous"] = old
            existing["name"] = name
            if date:
                existing["released"] = date
            existing["changelog"] = changelog
            existing["release_notes_url"] = url
            changes.append(f"{vendor}: {old} → {name}")
            print(f"  ✓ NEW RELEASE: {old} → {name}")
        else:
            print(f"  ✓ no change ({name})")
    return changes

def update_benchmarks(data: dict) -> list[str]:
    """Stub: would refresh top-3 per benchmark. Currently not implemented."""
    print("\nBenchmark scores — manual refresh recommended (sites are JS-rendered).")
    print("To refresh: ask Claude 'refresh benchmark scores' in chat.")
    return []

def main() -> int:
    data = load_data()
    print(f"Loaded data.json (last updated: {data['last_updated']})\n")

    print("=== Vendor release detection ===")
    release_changes = update_releases(data)

    print("\n=== Benchmark scores ===")
    benchmark_changes = update_benchmarks(data)

    data["last_updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    if release_changes:
        data["data_status"] = "auto_refreshed"
    save_data(data)

    print("\n=== Summary ===")
    if release_changes:
        print("Changes:")
        for c in release_changes:
            print(f"  • {c}")
    else:
        print("No new model releases detected.")
    print(f"\ndata.json updated. Last refresh stamp: {data['last_updated']}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
