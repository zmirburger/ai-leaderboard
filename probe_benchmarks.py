#!/usr/bin/env python3
"""
probe_benchmarks.py — diagnostic to see what data structures are in each
benchmark site's HTML. Run from GitHub Actions to inspect what plain-requests
scrapers can reach. Temporary; delete once scrapers are written.
"""
import json
import re
import sys
import requests
from bs4 import BeautifulSoup

UA = "Mozilla/5.0 (X11; Linux x86_64; rv:120.0) Gecko/20100101 Firefox/120.0"
HEADERS = {"User-Agent": UA, "Accept": "text/html,application/xhtml+xml"}

MODEL_KEYWORDS = ["Claude", "GPT-5", "Gemini", "Grok", "claude-", "gpt-5", "gemini-", "grok-"]


def probe_lmarena():
    url = "https://lmarena.ai/leaderboard"
    print(f"\n{'='*70}\nLMArena (detail): {url}\n{'='*70}")
    try:
        r = requests.get(url, headers=HEADERS, timeout=15, allow_redirects=True)
    except Exception as e:
        print(f"  ERROR: {e}"); return
    print(f"  status: {r.status_code}, final url: {r.url}")
    if r.status_code != 200:
        return
    soup = BeautifulSoup(r.text, "html.parser")
    tables = soup.find_all("table")
    print(f"  total tables: {len(tables)}")
    for i, t in enumerate(tables[:3]):
        rows = t.find_all("tr")
        print(f"\n  --- table[{i}] ({len(rows)} rows) ---")
        for row in rows[:15]:
            cols = [td.get_text(" ", strip=True) for td in row.find_all(["td", "th"])]
            print(f"    {cols}")


def probe_metr():
    url = "https://metr.org/time-horizons/"
    print(f"\n{'='*70}\nMETR (detail): {url}\n{'='*70}")
    try:
        r = requests.get(url, headers=HEADERS, timeout=15, allow_redirects=True)
    except Exception as e:
        print(f"  ERROR: {e}"); return
    print(f"  status: {r.status_code}, body: {len(r.text)} chars")
    if r.status_code != 200:
        return
    soup = BeautifulSoup(r.text, "html.parser")
    text = soup.get_text(" ", strip=True)

    # Show text around each "Claude" and "GPT-5" mention (±100 chars)
    print("\n  === Visible text context around model mentions ===")
    for kw in ["Claude", "GPT-5", "Gemini", "Grok"]:
        for m in re.finditer(re.escape(kw), text):
            s, e = max(0, m.start()-80), min(len(text), m.end()+80)
            print(f"  [{kw}] ...{text[s:e]}...")

    # Check for script tags containing JSON-like data with model names
    print("\n  === Script tags containing model keywords ===")
    for i, script in enumerate(soup.find_all("script")):
        content = script.string or ""
        if any(kw in content for kw in ["Claude", "GPT-5", "claude-", "gpt-5"]):
            print(f"  script[{i}] ({len(content)} chars): first 800 chars:")
            print(f"    {content[:800]}")

    # Tables
    tables = soup.find_all("table")
    print(f"\n  <table> count: {len(tables)}")
    for i, t in enumerate(tables[:3]):
        rows = t.find_all("tr")
        print(f"  table[{i}]: {len(rows)} rows")
        for row in rows[:5]:
            cols = [td.get_text(" ", strip=True) for td in row.find_all(["td", "th"])]
            print(f"    {cols}")


def probe_aa_detail():
    """Check if AA JS bundles contain extractable JSON data."""
    url = "https://artificialanalysis.ai/evaluations/artificial-analysis-intelligence-index"
    print(f"\n{'='*70}\nAA-Intelligence (JS detail): {url}\n{'='*70}")
    try:
        r = requests.get(url, headers=HEADERS, timeout=20, allow_redirects=True)
    except Exception as e:
        print(f"  ERROR: {e}"); return
    print(f"  status: {r.status_code}, body: {len(r.text)} chars")
    if r.status_code != 200:
        return

    # Find the largest script tag and show segment around first claude- mention
    soup = BeautifulSoup(r.text, "html.parser")
    scripts = sorted(
        [s for s in soup.find_all("script") if s.string],
        key=lambda s: len(s.string), reverse=True
    )
    print(f"  top script sizes: {[len(s.string) for s in scripts[:5]]}")

    for i, script in enumerate(scripts[:3]):
        content = script.string
        m = re.search(r'claude-', content)
        if m:
            s = max(0, m.start() - 200)
            e = min(len(content), m.end() + 400)
            print(f"\n  script[{i}] ({len(content)} chars) — context around 'claude-':")
            print(f"    {content[s:e]}")
            break


def main():
    probe_lmarena()
    probe_metr()
    probe_aa_detail()
    return 0


if __name__ == "__main__":
    sys.exit(main())
