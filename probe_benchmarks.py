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

SITES = [
    ("AA-Intelligence",  "https://artificialanalysis.ai/evaluations/artificial-analysis-intelligence-index"),
    ("AA-LongContext",   "https://artificialanalysis.ai/evaluations/artificial-analysis-long-context-reasoning"),
    ("AA-IFBench",       "https://artificialanalysis.ai/evaluations/ifbench"),
    ("AA-Omniscience",   "https://artificialanalysis.ai/evaluations/omniscience"),
    ("Epoch-Fiction",    "https://epoch.ai/benchmarks/fictionlivebench"),
    ("METR",             "https://metr.org/time-horizons/"),
    ("LMArena",          "https://lmarena.ai/leaderboard"),
    ("Scale-RLI",        "https://scale.com/leaderboard/rli"),
    ("Vectara-HHEM",     "https://huggingface.co/spaces/vectara/leaderboard"),
]

MODEL_KEYWORDS = ["Claude", "GPT-5", "Gemini", "Grok", "claude-", "gpt-5", "gemini-", "grok-"]


def probe(name, url):
    print(f"\n{'=' * 70}\n{name}: {url}\n{'=' * 70}")
    try:
        r = requests.get(url, headers=HEADERS, timeout=15, allow_redirects=True)
    except Exception as e:
        print(f"  ERROR: {e}")
        return
    print(f"  status: {r.status_code}, final url: {r.url}, body: {len(r.text)} chars")
    if r.status_code != 200:
        return

    soup = BeautifulSoup(r.text, "html.parser")

    # __NEXT_DATA__
    next_data = soup.find("script", {"id": "__NEXT_DATA__"})
    if next_data and next_data.string:
        size = len(next_data.string)
        print(f"  __NEXT_DATA__: present, {size} chars")
        try:
            parsed = json.loads(next_data.string)
            # Look for model-like keys recursively (shallow probe)
            keys_seen = set()
            def walk(obj, depth=0):
                if depth > 4:
                    return
                if isinstance(obj, dict):
                    for k, v in obj.items():
                        keys_seen.add(k)
                        walk(v, depth + 1)
                elif isinstance(obj, list) and obj:
                    walk(obj[0], depth + 1)
            walk(parsed)
            interesting = [k for k in keys_seen if any(t in k.lower() for t in
                          ["model", "score", "benchmark", "eval", "result", "data"])]
            print(f"  __NEXT_DATA__ interesting keys: {sorted(interesting)[:25]}")
        except json.JSONDecodeError as e:
            print(f"  __NEXT_DATA__ JSON parse failed: {e}")
    else:
        print("  __NEXT_DATA__: NOT present")

    # Other embedded scripts (look for huge JSON blobs)
    big_scripts = [s for s in soup.find_all("script") if s.string and len(s.string) > 5000]
    print(f"  large <script> tags (>5KB): {len(big_scripts)}")

    # <table> elements
    tables = soup.find_all("table")
    print(f"  <table> count: {len(tables)}")
    for i, t in enumerate(tables[:3]):
        rows = t.find_all("tr")
        first_row_text = rows[0].get_text(" ", strip=True)[:120] if rows else ""
        print(f"    table[{i}]: {len(rows)} rows. first: {first_row_text!r}")

    # Model keyword counts in body
    text = soup.get_text(" ", strip=True)
    counts = {kw: len(re.findall(re.escape(kw), text)) for kw in MODEL_KEYWORDS}
    nonzero = {k: v for k, v in counts.items() if v > 0}
    print(f"  model keyword hits in visible text: {nonzero}")

    # Same but in raw HTML (catches embedded JSON strings)
    raw_counts = {kw: len(re.findall(re.escape(kw), r.text)) for kw in MODEL_KEYWORDS}
    raw_nonzero = {k: v for k, v in raw_counts.items() if v > 0}
    print(f"  model keyword hits in raw HTML:     {raw_nonzero}")


def main():
    for name, url in SITES:
        probe(name, url)
    return 0


if __name__ == "__main__":
    sys.exit(main())
