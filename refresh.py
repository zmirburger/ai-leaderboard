#!/usr/bin/env python3
"""
refresh.py — daily refresh for the AI Leader Dashboard.

Strategy:
- Vendor release pages are the highest-value scrape target.
- Benchmark leaderboards are JS-rendered; manual refresh on demand.
- Each (vendor, tier) pair has its own detector function.
- Downgrade guard: only accept a detected name if version is strictly newer.
- Version picking is numeric on (major, minor), so 5 beats 4.5.
- recompute_rankings() auto-updates best_overall and best_per_priority from scores.
"""

from __future__ import annotations
import json
import math
import re
import sys
import time
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

def fetch(url, retries=2):
    for attempt in range(retries + 1):
        try:
            r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
            r.raise_for_status()
            return r.text
        except Exception as e:
            if attempt < retries:
                time.sleep(2 ** attempt)
                continue
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
    """Extract a comparable version number from a model name for downgrade protection.

    These are decimal-style marketing versions, not semver: "4.5" is four-point-five
    and ranks ABOVE "4.20" (four-point-two), while "5" ranks above both. Compare as a
    float so 5 > 4.5 > 4.20. A (major, minor) tuple would wrongly rank 4.20 -> (4, 20)
    above 4.5 -> (4, 5) and promote the older Grok 4.20 over the newer Grok 4.5."""
    m = re.search(r'\d+(?:\.\d+)?', name)
    if not m:
        return 0.0
    return float(m.group(0))

def _find_best_match(soup, pattern):
    """Find ALL matches in headings (preferred) or body; pick the highest version.
    Compares versions as decimal floats so "5" beats "4.5" and "4.5" beats "4.20" —
    a tuple compare would keep the older-but-numerically-larger "4.20" forever."""
    headings = " | ".join(h.get_text(" ", strip=True) for h in soup.find_all(["h1", "h2", "h3"]))
    matches = re.findall(pattern, headings)
    if not matches:
        matches = re.findall(pattern, soup.get_text(" ", strip=True))
    if not matches:
        return None
    if isinstance(matches[0], tuple):
        return max(matches, key=lambda m: _parse_version(m[0]))
    return max(matches, key=_parse_version)

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

def detect_anthropic_fable():
    soup = _get_anthropic_soup()
    if not soup:
        return None
    version = _find_best_match(soup, r"Claude Fable (\d+(?:\.\d+)?)\b(?!\d)")
    if not version:
        return None
    return _result(f"Claude Fable {version}", soup.get_text(" ", strip=True), _ANTHROPIC_URL)

def detect_anthropic_opus():
    soup = _get_anthropic_soup()
    if not soup:
        return None
    version = _find_best_match(soup, r"Claude Opus (\d+(?:\.\d+)?)\b(?!\d)")
    if not version:
        return None
    return _result(f"Claude Opus {version}", soup.get_text(" ", strip=True), _ANTHROPIC_URL)

def detect_anthropic_sonnet():
    soup = _get_anthropic_soup()
    if not soup:
        return None
    version = _find_best_match(soup, r"Claude Sonnet (\d+(?:\.\d+)?)\b(?!\d)")
    if not version:
        return None
    return _result(f"Claude Sonnet {version}", soup.get_text(" ", strip=True), _ANTHROPIC_URL)

def detect_anthropic_haiku():
    soup = _get_anthropic_soup()
    if not soup:
        return None
    version = _find_best_match(soup, r"Claude Haiku (\d+(?:\.\d+)?)\b(?!\d)")
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
    version = _find_best_match(soup, r"GPT-(\d+(?:\.\d+)?)\b(?!\d)")
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
    version = _find_best_match(soup, r"Gemini (\d+(?:\.\d+)?) Pro\b(?!\d)")
    if not version:
        return None
    return _result(f"Gemini {version} Pro", soup.get_text(" ", strip=True), _GOOGLE_URL)

def detect_gemini_flash():
    soup = _get_google_soup()
    if not soup:
        return None
    # Exclude "Flash Thinking" matches — only plain Flash
    best = _find_best_match(soup, r"Gemini (\d+(?:\.\d+)?) Flash\b(?! Thinking)")
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

def detect_grok():
    # xAI dropped the Expert/Fast split with Grok 4.5 — one unified model line.
    # Suffixed legacy names ("Grok 4.1 Fast") are excluded so they can't win.
    soup = _get_xai_soup()
    if not soup:
        return None
    best = _find_best_match(soup, r"Grok[ -]?(\d+(?:\.\d+)?)(?!\.?\d)(?!\s+(?:Expert|Fast)\b)")
    if not best:
        return None
    version = best if isinstance(best, str) else best[0]
    return _result(f"Grok {version}", soup.get_text(" ", strip=True), _XAI_URL)

# ---------- tier detector registry ----------

TIER_DETECTORS = {
    ("Anthropic", "Fable"):   detect_anthropic_fable,
    ("Anthropic", "Opus"):    detect_anthropic_opus,
    ("Anthropic", "Sonnet"):  detect_anthropic_sonnet,
    ("Anthropic", "Haiku"):   detect_anthropic_haiku,
    ("Google",    "Pro"):     detect_gemini_pro,
    ("Google",    "Flash"):   detect_gemini_flash,
    ("OpenAI",    "GPT"):     detect_openai,
    ("xAI",       "Grok"):    detect_grok,
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
            else:
                print(f"  WARNING: {vendor}/{tier} renamed to {name} but no release date parsed - "
                      f"'released' left at stale value {existing['released']}, check {url} manually")
            existing["changelog"] = changelog
            existing["release_notes_url"] = url
            changes.append(f"{vendor}/{tier}: {old} -> {name}")
            print(f"  NEW RELEASE: {old} -> {name}")
        else:
            print(f"  no change ({name})")
    return changes

def recompute_rankings(data):
    """Recompute composite_overall for all models and update best_overall/best_per_priority.
    Null per_priority scores are skipped (weight→0); composite is None when all scores are null."""
    w = data["weights"]
    for m in data["models"]:
        pp = m["per_priority"]
        total = 0
        for dim, weight in w.items():
            score = pp.get(dim)
            if score is not None:
                total += score * weight
        has_any = any(v is not None for v in pp.values())
        m["composite_overall"] = round(total) if has_any else None

    ranked = [m for m in data["models"] if m["composite_overall"] is not None]
    if ranked:
        best = max(ranked, key=lambda m: m["composite_overall"])
        if data["best_overall"]["model"] != best["name"]:
            # New leader: the hand-written rationale describes the old one, replace
            # with a factual auto-generated line rather than leave stale claims.
            pp = best["per_priority"]
            data["best_overall"]["rationale"] = (
                f"Auto-ranked leader: accuracy {pp.get('accuracy', '—')}, "
                f"long context {pp.get('long_context', '—')}, agent {pp.get('agent', '—')}. "
                "Edit this rationale in data.json for a hand-written take."
            )
        data["best_overall"]["model"] = best["name"]
        data["best_overall"]["composite"] = best["composite_overall"]
    for priority in ["agent", "accuracy", "long_context"]:
        scoreable = [m for m in data["models"] if m["per_priority"].get(priority) is not None]
        if scoreable:
            top = max(scoreable, key=lambda m: m["per_priority"][priority])
            entry = data["best_per_priority"][priority]
            if entry["model"] != top["name"]:
                entry["summary"] = f"Score {top['per_priority'][priority]} (auto-ranked; edit summary in data.json)"
            entry["model"] = top["name"]

# ---------- benchmark scrapers ----------

def _set_top3(data, category, bench_id, new_top3):
    """Replace top3 for a given benchmark id; returns change description or None."""
    for bench in data["benchmarks"].get(category, []):
        if bench["id"] == bench_id:
            old = bench.get("top3", [])
            if old == new_top3:
                return None
            bench["top3"] = new_top3
            return f"{category}/{bench_id}: top3 updated ({len(new_top3)} entries)"
    return None

def _fmt_minutes(mins):
    if mins >= 60:
        hours = mins / 60
        if hours >= 10:
            return f"~{hours:.0f}h"
        return f"~{hours:.1f}h"
    if mins >= 1:
        return f"~{int(round(mins))}m"
    return f"~{mins:.1f}m"

def _looks_like_model_name(s):
    """A real model name contains letters, not just a rank digit or icon."""
    return bool(re.search(r"[A-Za-z]{2,}", s))

def _looks_like_arena_score(s):
    """Arena scores are Elo-style integers, roughly 900-3000."""
    return s.isdigit() and 900 <= int(s) <= 3000

def scrape_lmarena():
    """Returns top-10 from LMArena overall text leaderboard as list of {model, score}.

    Scans every table and every column layout; only accepts rows where the model
    cell contains an actual name and the score cell is a plausible Elo. Previously
    this trusted fixed column positions and wrote junk like {model: "1", score: "3"}
    when the page layout shifted. Requires >=3 valid rows or returns None."""
    url = "https://lmarena.ai/leaderboard"
    html = fetch(url)
    if not html:
        return None
    soup = BeautifulSoup(html, "html.parser")
    for table in soup.find_all("table"):
        out = []
        for row in table.find_all("tr"):
            cols = [td.get_text(" ", strip=True) for td in row.find_all(["td", "th"])]
            score = next((c for c in cols if _looks_like_arena_score(c)), None)
            model = next((c for c in cols if _looks_like_model_name(c)), None)
            if score and model:
                out.append({"model": model, "score": score})
        if len(out) >= 3:
            return out[:10]
    return None

def scrape_metr():
    """Parses METR's `var thData` JSON and returns top agents by 50%-reliability horizon.
    Filters out pre-release '(early)' models which have unreliable extrapolated estimates."""
    url = "https://metr.org/time-horizons/"
    html = fetch(url)
    if not html:
        return None
    m = re.search(r'var\s+thData\s*=\s*(\{.*?\})\s*;', html, re.DOTALL)
    if not m:
        return None
    try:
        thdata = json.loads(m.group(1))
    except json.JSONDecodeError:
        return None
    horizons = []
    for name, info in thdata.get("agents", {}).items():
        # Skip pre-release models — their coefficients are extrapolated from limited data
        if "(early)" in name.lower():
            continue
        coef = info.get("coefficient")
        intercept = info.get("intercept")
        if not coef or coef == 0 or intercept is None:
            continue
        try:
            mins = math.exp(-intercept / coef)
        except (OverflowError, ValueError):
            continue
        horizons.append((name, mins))
    if not horizons:
        return None
    horizons.sort(key=lambda x: x[1], reverse=True)
    return [{"model": name, "value": _fmt_minutes(mins)} for name, mins in horizons[:10]]

def _extract_aa_models(html, field):
    """Regex-extract (model_family_slug, field_value) pairs from AA's JS bundle.
    Each model object is escaped JSON inside the React bundle; we match nearby
    field/slug pairs without trying to parse the whole object."""
    results = {}
    pattern = re.compile(
        r'\\"' + re.escape(field) + r'\\":([\d.]+)[^{}]{0,800}?\\"model_family_slug\\":\\"([^"\\]+)\\"'
        r'|\\"model_family_slug\\":\\"([^"\\]+)\\"[^{}]{0,800}?\\"' + re.escape(field) + r'\\":([\d.]+)'
    )
    for m in pattern.finditer(html):
        if m.group(2):
            slug, val = m.group(2), m.group(1)
        else:
            slug, val = m.group(3), m.group(4)
        try:
            val_f = float(val)
        except ValueError:
            continue
        # Keep best score per family
        if slug not in results or val_f > results[slug]:
            results[slug] = val_f
    return results

def scrape_aa_field(url, field, value_fmt=lambda v: f"{v:.1f}", scale=1.0):
    """Fetch an AA evaluation page, regex-extract model_family_slug→field, return top 10."""
    html = fetch(url)
    if not html:
        return None
    extracted = _extract_aa_models(html, field)
    if not extracted:
        return None
    sorted_models = sorted(extracted.items(), key=lambda kv: kv[1], reverse=True)
    return [{"model": slug, "value": value_fmt(score * scale)} for slug, score in sorted_models[:10]]

def update_benchmarks(data):
    changes = []

    print("Scraping LMArena leaderboard...")
    lmarena = scrape_lmarena()
    if lmarena:
        old = data["lmarena_vibe_check"].get("top3", [])
        if old != lmarena[:3]:
            data["lmarena_vibe_check"]["top3"] = lmarena[:3]
            changes.append(f"lmarena_vibe_check: top3 updated -> {lmarena[0]['model']} @ {lmarena[0]['score']}")
            print(f"  updated. top: {lmarena[0]['model']} ({lmarena[0]['score']})")
        else:
            print("  no change")
    else:
        print("  skipped (no parse)")

    print("Scraping METR time horizons...")
    metr = scrape_metr()
    if metr:
        ch = _set_top3(data, "agent", "metr_time_horizon", metr[:3])
        if ch:
            changes.append(ch); print(f"  updated. top: {metr[0]['model']} ({metr[0]['value']})")
        else:
            print("  no change")
    else:
        print("  skipped (no parse)")

    print("Scraping AA Intelligence Index...")
    aa_intel = scrape_aa_field(
        "https://artificialanalysis.ai/evaluations/artificial-analysis-intelligence-index",
        "intelligence_index",
        value_fmt=lambda v: f"~{v:.0f}",
    )
    if aa_intel:
        ch = _set_top3(data, "accuracy", "aa_intelligence_index", aa_intel[:3])
        if ch:
            changes.append(ch); print(f"  updated. top: {aa_intel[0]['model']} ({aa_intel[0]['value']})")
        else:
            print("  no change")
    else:
        print("  skipped (no parse)")

    print("Scraping AA Omniscience...")
    aa_omni = None
    omni_url = "https://artificialanalysis.ai/evaluations/omniscience"
    omni_html = fetch(omni_url)
    if omni_html:
        # Values must be in 0–100 range (normalized benchmark, not Elo-style)
        for field_candidate in ["omniscience", "omniscience_index", "omniscience_score", "knowledge"]:
            extracted = _extract_aa_models(omni_html, field_candidate)
            in_range = {s: v for s, v in extracted.items() if 0 <= v <= 100}
            if in_range:
                sorted_models = sorted(in_range.items(), key=lambda kv: kv[1], reverse=True)
                aa_omni = [{"model": slug, "value": f"~{score:.0f}"} for slug, score in sorted_models[:10]]
                print(f"  matched field: {field_candidate!r}")
                break
    if aa_omni:
        ch = _set_top3(data, "accuracy", "aa_omniscience", aa_omni[:3])
        if ch:
            changes.append(ch); print(f"  updated. top: {aa_omni[0]['model']} ({aa_omni[0]['value']})")
        else:
            print("  no change")
    else:
        # Dump a sample of field-like keys visible in the bundle to help identify the right name
        if omni_html:
            keys_found = re.findall(r'\\"([a-z][a-z0-9_]{3,30})\\":\d', omni_html)
            unique_keys = sorted(set(keys_found))[:30]
            print(f"  skipped (no match). Numeric field names in bundle: {unique_keys}")
        else:
            print("  skipped (fetch failed)")

    print("Scraping AA IFBench...")
    aa_if = scrape_aa_field(
        "https://artificialanalysis.ai/evaluations/ifbench",
        "ifbench",
        value_fmt=lambda v: f"~{v*100:.0f}%",
    )
    if aa_if:
        ch = _set_top3(data, "long_context", "aa_ifbench", aa_if[:3])
        if ch:
            changes.append(ch); print(f"  updated. top: {aa_if[0]['model']} ({aa_if[0]['value']})")
        else:
            print("  no change")
    else:
        print("  skipped (no parse)")

    return changes

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
