#!/usr/bin/env python3
"""
refresh.py — daily refresh for the AI Leader Dashboard.

Strategy:
- Vendor release pages are the highest-value scrape target.
- Benchmark leaderboards are JS-rendered; manual refresh on demand.
- Each (vendor, tier) pair has its own detector function.
- Downgrade guard: only accept a detected name if version is strictly newer.
- Version picking is numeric on (major, minor), so 5 beats 4.5.
- Per-priority scores are computed from raw benchmark values (see BENCHMARKS);
  nothing is hand-set. A model a board hasn't measured yet inherits the value of
  the newest older version of the same family on that board, flagged provisional.
- recompute_rankings() auto-updates best_overall and best_per_priority from scores.
"""

from __future__ import annotations
import json
import math
import os
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

def fetch(url, retries=2, extra_headers=None):
    for attempt in range(retries + 1):
        try:
            r = requests.get(url, headers={**HEADERS, **(extra_headers or {})}, timeout=TIMEOUT)
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
    DATA_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")

def _extract_iso_date(text):
    date_match = re.search(r"(\w+ \d{1,2}, \d{4})", text[:5000])
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

_UNICODE_HYPHENS = re.compile("[\u2010\u2011\u2012\u2013\u2014\u2212]")

def _find_best_match(soup, pattern, include_body=False):
    """Find ALL matches in headings (preferred) or body; pick the highest version.
    Compares versions as decimal floats so "5" beats "4.5" and "4.5" beats "4.20" —
    a tuple compare would keep the older-but-numerically-larger "4.20" forever.
    Unicode hyphens are normalized first: OpenAI writes "GPT\u20116" with a
    non-breaking hyphen, which an ASCII "GPT-" pattern silently misses.
    include_body=True searches headings AND body, for pages whose newest release
    isn't in a heading while older ones are (headings-only would never see it)."""
    headings = " | ".join(h.get_text(" ", strip=True) for h in soup.find_all(["h1", "h2", "h3"]))
    headings = _UNICODE_HYPHENS.sub("-", headings)
    body = _UNICODE_HYPHENS.sub("-", soup.get_text(" ", strip=True))
    matches = re.findall(pattern, headings)
    if include_body or not matches:
        matches += re.findall(pattern, body)
    if not matches:
        return None
    if isinstance(matches[0], tuple):
        return max(matches, key=lambda m: _parse_version(m[0]))
    return max(matches, key=_parse_version)

def _result(name, soup_text, url):
    return (name, _extract_iso_date(soup_text), "(Auto-detected from release notes - full changelog at link)", url)

_AA_LEADERBOARD_URL = "https://artificialanalysis.ai/leaderboards/models"
_AA_FREE_API_URL = "https://artificialanalysis.ai/api/v2/language/models/free"
_AA_RSC_SCORES = {
    "aa_gdp": "gdp-pdf",
    "aa_terminalbench_v4": "terminalbench-4-0",
    "aa_tau_banking": "tau3-banking",
}
_AA_MERGE_BENCHES = {"aa_gdp", "aa_terminalbench_v4", "aa_tau_banking", "aa_price"}
_aa_rsc_cache = None

def _extract_rsc_stream(html):
    """Extract concatenated Next.js RSC push payload from an HTML document."""
    chunks = []
    for m in re.finditer(r'self\.__next_f\.push\(\[1,\s*("(?:\\.|[^"\\])*")\]\)', html or ""):
        try:
            chunks.append(json.loads(m.group(1)))
        except json.JSONDecodeError:
            continue
    return "".join(chunks)

def _get_aa_rsc():
    """Fetch and decode Artificial Analysis Next.js RSC stream once per run.
    Returns (models_list, releases_list)."""
    global _aa_rsc_cache
    if _aa_rsc_cache is not None:
        return _aa_rsc_cache
    html = fetch(_AA_LEADERBOARD_URL)
    if not html:
        _aa_rsc_cache = ([], [])
        return _aa_rsc_cache
    stream = _extract_rsc_stream(html)
    decoder = json.JSONDecoder()
    models_arr, releases_arr = [], []
    i = 0
    while (idx := stream.find("[{", i)) != -1:
        try:
            arr, end = decoder.raw_decode(stream, idx)
            if isinstance(arr, list) and arr and isinstance(arr[0], dict):
                keys = arr[0].keys()
                if "scores" in keys and "name" in keys and len(arr) > len(models_arr):
                    models_arr = arr
                elif "releaseDate" in keys and "creator" in keys and len(arr) > len(releases_arr):
                    releases_arr = arr
            i = end
        except json.JSONDecodeError:
            i = idx + 2
    _aa_rsc_cache = (models_arr, releases_arr)
    return _aa_rsc_cache

def _find_aa_release(creator_names, pattern):
    """Find highest-version release matching pattern in AA's releases feed."""
    _, releases_arr = _get_aa_rsc()
    candidates = []
    for rel in releases_arr:
        cname = ((rel.get("creator") or {}).get("name") or "").strip()
        if cname not in creator_names:
            continue
        rname = _UNICODE_HYPHENS.sub("-", str(rel.get("name") or ""))
        m = re.search(pattern, rname)
        if m:
            ver_str = m.group(1)
            candidates.append((_parse_version(ver_str), ver_str, str(rel.get("releaseDate") or "")))
    if not candidates:
        return None
    _, ver_str, rdate = max(candidates, key=lambda x: (x[0], x[2]))
    return ver_str, rdate

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

def _detect_openai_tier(tier):
    """GPT-6 ships as three tiers (Astra > Sol > Luna), versioned independently
    (e.g. GPT-6.1 Sol next to GPT-6 Astra). Uses AA releases feed since help.openai.com returns 403."""
    hit = _find_aa_release(("OpenAI",), rf"\bGPT-(\d+(?:\.\d+)?)[ -]{tier}\b")
    if not hit:
        return None
    version, rdate = hit
    return (f"GPT-{version} {tier}", rdate, "(Auto-detected from Artificial Analysis releases)", _AA_LEADERBOARD_URL)

def detect_openai_astra():
    return _detect_openai_tier("Astra")

def detect_openai_sol():
    return _detect_openai_tier("Sol")

def detect_openai_luna():
    return _detect_openai_tier("Luna")

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

def detect_gemini_flash_lite():
    soup = _get_google_soup()
    if not soup:
        return None
    # Exclude specialized TTS/Image/Live/Audio Flash-Lite variants (e.g. Gemini 3.8 Flash-Lite TTS)
    best = _find_best_match(soup, r"Gemini (\d+(?:\.\d+)?) Flash[- ]Lite\b(?!\s+(?:TTS|Image|Live|Audio)\b)", include_body=True)
    if not best:
        return None
    version = best if isinstance(best, str) else best[0]
    return _result(f"Gemini {version} Flash-Lite", soup.get_text(" ", strip=True), _GOOGLE_URL)

def detect_gemini_carbon():
    soup = _get_google_soup()
    if not soup:
        return None
    best = _find_best_match(soup, r"Gemini (\d+(?:\.\d+)?) Carbon\b", include_body=True)
    if not best:
        best = _find_best_match(soup, r"Carbon (\d+(?:\.\d+)?)", include_body=True)
        if best:
            version = best if isinstance(best, str) else best[0]
            return _result(f"Gemini {version} Carbon", soup.get_text(" ", strip=True), _GOOGLE_URL)
        return None
    version = best if isinstance(best, str) else best[0]
    return _result(f"Gemini {version} Carbon", soup.get_text(" ", strip=True), _GOOGLE_URL)

def detect_gemini_argon():
    soup = _get_google_soup()
    if not soup:
        return None
    best = _find_best_match(soup, r"Gemini (\d+(?:\.\d+)?) Argon\b", include_body=True)
    if not best:
        best = _find_best_match(soup, r"Argon (\d+(?:\.\d+)?)", include_body=True)
        if best:
            version = best if isinstance(best, str) else best[0]
            return _result(f"Gemini {version} Argon", soup.get_text(" ", strip=True), _GOOGLE_URL)
        return None
    version = best if isinstance(best, str) else best[0]
    return _result(f"Gemini {version} Argon", soup.get_text(" ", strip=True), _GOOGLE_URL)

def detect_gemini_hydrogen():
    soup = _get_google_soup()
    if not soup:
        return None
    best = _find_best_match(soup, r"Gemini (\d+(?:\.\d+)?) Hydrogen\b", include_body=True)
    if not best:
        best = _find_best_match(soup, r"Hydrogen (\d+(?:\.\d+)?)", include_body=True)
        if best:
            version = best if isinstance(best, str) else best[0]
            return _result(f"Gemini {version} Hydrogen", soup.get_text(" ", strip=True), _GOOGLE_URL)
        return None
    version = best if isinstance(best, str) else best[0]
    return _result(f"Gemini {version} Hydrogen", soup.get_text(" ", strip=True), _GOOGLE_URL)

def detect_gemini_neon():
    soup = _get_google_soup()
    if not soup:
        return None
    best = _find_best_match(soup, r"Gemini (\d+(?:\.\d+)?) Neon\b", include_body=True)
    if not best:
        best = _find_best_match(soup, r"Neon (\d+(?:\.\d+)?)", include_body=True)
        if best:
            version = best if isinstance(best, str) else best[0]
            return _result(f"Gemini {version} Neon", soup.get_text(" ", strip=True), _GOOGLE_URL)
        return None
    version = best if isinstance(best, str) else best[0]
    return _result(f"Gemini {version} Neon", soup.get_text(" ", strip=True), _GOOGLE_URL)

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
    aa_hit = _find_aa_release(("SpaceXAI", "xAI"), r"\bGrok[ -]?(\d+(?:\.\d+)?)(?!\.?\d)(?!\s+(?:Expert|Fast|Build)\b)")
    soup = _get_xai_soup()
    soup_ver, soup_date = None, ""
    if soup:
        best = _find_best_match(soup, r"Grok[ -]?(\d+(?:\.\d+)?)(?!\.?\d)(?!\s+(?:Expert|Fast)\b)")
        if best:
            soup_ver = best if isinstance(best, str) else best[0]
            soup_date = _extract_iso_date(soup.get_text(" ", strip=True))
    if aa_hit and (not soup_ver or _parse_version(aa_hit[0]) > _parse_version(soup_ver)):
        return (f"Grok {aa_hit[0]}", aa_hit[1], "(Auto-detected from Artificial Analysis releases)", _XAI_URL)
    if soup_ver:
        rdate = soup_date or (aa_hit[1] if aa_hit and _parse_version(aa_hit[0]) == _parse_version(soup_ver) else "")
        return (f"Grok {soup_ver}", rdate, "(Auto-detected from release notes - full changelog at link)", _XAI_URL)
    return None

# ---------- tier detector registry ----------

TIER_DETECTORS = {
    ("Anthropic", "Fable"):   detect_anthropic_fable,
    ("Anthropic", "Opus"):    detect_anthropic_opus,
    ("Anthropic", "Sonnet"):  detect_anthropic_sonnet,
    ("Anthropic", "Haiku"):   detect_anthropic_haiku,
    ("Google",    "Pro"):      detect_gemini_pro,
    ("Google",    "Carbon"):   detect_gemini_carbon,
    ("Google",    "Neon"):     detect_gemini_neon,
    ("Google",    "Argon"):    detect_gemini_argon,
    ("Google",    "Hydrogen"): detect_gemini_hydrogen,
    ("Google",    "Flash"):    detect_gemini_flash,
    ("Google",    "Flash-Lite"): detect_gemini_flash_lite,
    ("OpenAI",    "Astra"):   detect_openai_astra,
    ("OpenAI",    "Sol"):     detect_openai_sol,
    ("OpenAI",    "Luna"):    detect_openai_luna,
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
        matching = [m for m in data["models"] if m["vendor"] == vendor and m.get("tier") == tier]
        if not matching:
            print(f"  no entry for {vendor}/{tier} in data.json")
            continue
        for existing in matching:
            has_effort_suffix = " (high)" in existing["name"].lower() or " (medium)" in existing["name"].lower()
            target_name = f"{name} ({existing['target_effort'].capitalize()})" if has_effort_suffix else name
            if existing["name"] != target_name:
                old = existing["name"]
                if _parse_version(name) <= _parse_version(old):
                    print(f"  detected {name} but keeping {old} (not a newer version)")
                    continue
                existing["previous"] = old
                existing["name"] = target_name
                if "base_name" in existing:
                    existing["base_name"] = name
                if date:
                    existing["released"] = date
                else:
                    print(f"  WARNING: {vendor}/{tier} renamed to {target_name} but no release date parsed - "
                          f"'released' left at stale value {existing['released']}, check {url} manually")
                existing["changelog"] = changelog
                existing["release_notes_url"] = url
                changes.append(f"{vendor}/{tier}: {old} -> {target_name}")
                print(f"  NEW RELEASE: {old} -> {target_name} (scores inherit from older versions until benchmarked)")
            else:
                print(f"  no change ({existing['name']})")
    return changes

# ---------- benchmark sources ----------
# Each fetcher returns {bench_id: {board_model_name: value}} covering EVERY model on
# the board (not just a top 3), or None when the fetch/parse fails. Values are in
# natural units: percentages 0-100, hours, USD.

def _supplement_aa_free_api(out, key):
    """Optionally backfill historical Intelligence Index v5.0 & blended price via AA Free V2 API."""
    for page in range(1, 10):
        raw = fetch(f"{_AA_FREE_API_URL}?page={page}", retries=1, extra_headers={"x-api-key": key})
        if not raw:
            break
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            break
        for it in payload.get("data") or []:
            name = it.get("name")
            if not name:
                continue
            ii = (it.get("evaluations") or {}).get("artificial_analysis_intelligence_index")
            if isinstance(ii, (int, float)):
                out["aa_intelligence_index"].setdefault(name, float(ii))
            pricing = it.get("pricing") or {}
            inp, outp = pricing.get("price_1m_input_tokens"), pricing.get("price_1m_output_tokens")
            if isinstance(inp, (int, float)) and isinstance(outp, (int, float)):
                blended = (3.0 * float(inp) + float(outp)) / 4.0
                if blended > 0:
                    out["aa_price"].setdefault(name, blended)
        if not (payload.get("pagination") or {}).get("has_more"):
            break

def _supplement_aa_model_gdp(out_gdp, releases_arr):
    """Backfill GDP.pdf scores from AA model pages for tracked releases hidden by deprecated=true."""
    if not DATA_PATH.exists():
        return
    present = {norm_name(k) for k in out_gdp}
    tracked_groups = [
        [norm_name(m["name"])] + [norm_name(a) for a in m.get("aliases", [])]
        for m in load_data().get("models", [])
    ]
    missing = {k for keys in tracked_groups if not any(k in present for k in keys) for k in keys if k}
    if not missing:
        return
    seen_slugs = set()
    decoder = json.JSONDecoder()
    for rel in releases_arr:
        slug = rel.get("slug")
        if not slug or slug in seen_slugs:
            continue
        rel_keys = [norm_name(rel.get("name") or "")] + [norm_name(mn) for mn in (rel.get("modelNames") or [])]
        if not any(k in missing for k in rel_keys):
            continue
        seen_slugs.add(slug)
        html = fetch(f"https://artificialanalysis.ai/models/{slug}")
        if not html:
            continue
        stream = _extract_rsc_stream(html)
        page_gdp = {}
        i = 0
        while (idx := stream.find("[{", i)) != -1:
            try:
                arr, end = decoder.raw_decode(stream, idx)
                if isinstance(arr, list) and arr and isinstance(arr[0], dict) and "gdpPdfAllPass" in arr[0]:
                    for r in arr:
                        rname, val = r.get("name"), r.get("gdpPdfAllPass")
                        if rname and isinstance(val, (int, float)):
                            page_gdp[rname] = float(val)
                i = end
            except json.JSONDecodeError:
                i = idx + 2
        if page_gdp:
            if max(page_gdp.values()) <= 1.0:
                page_gdp = {k: v * 100.0 for k, v in page_gdp.items()}
            for k, v in page_gdp.items():
                out_gdp.setdefault(k, v)

def fetch_aa():
    """Artificial Analysis leaderboard RSC stream (+ optional Free V2 API supplement)."""
    models_arr, releases_arr = _get_aa_rsc()
    out = {b: {} for b in ("aa_intelligence_index", "aa_gdp", "aa_terminalbench_v4", "aa_tau_banking", "aa_price")}
    for it in models_arr:
        name = it.get("name")
        if not name:
            continue
        ii = it.get("intelligenceIndex")
        if isinstance(ii, (int, float)):
            out["aa_intelligence_index"][name] = float(ii)
        scores = it.get("scores") or {}
        for bench, score_key in _AA_RSC_SCORES.items():
            v = scores.get(score_key)
            if isinstance(v, (int, float)):
                out[bench][name] = float(v)
        inp, outp = it.get("price1mInputTokens"), it.get("price1mOutputTokens")
        if isinstance(inp, (int, float)) and isinstance(outp, (int, float)):
            blended = (3.0 * float(inp) + float(outp)) / 4.0
            if blended > 0:
                out["aa_price"][name] = blended
    for bench in _AA_RSC_SCORES:
        vals = out[bench]
        if vals and max(vals.values()) <= 1.0:
            out[bench] = {k: v * 100.0 for k, v in vals.items()}
    _supplement_aa_model_gdp(out["aa_gdp"], releases_arr)
    key = os.environ.get("AA_API_KEY")
    if key:
        _supplement_aa_free_api(out, key)
    print(f"  {len(models_arr)} RSC models; counts: " + ", ".join(f"{k}={len(v)}" for k, v in out.items()))
    if not any(bool(v) for v in out.values()):
        return {}
    return out

def fetch_benchlm():
    raw = fetch("https://benchlm.ai/api/leaderboard")
    if not raw:
        return None
    try:
        models = json.loads(raw).get("models") or []
    except (json.JSONDecodeError, AttributeError):
        return None
    vals = {m["model"].strip(): float(m["overallScore"]) for m in models
            if m.get("model") and isinstance(m.get("overallScore"), (int, float))}
    return {"benchlm": vals}

def fetch_deepswe():
    """pass@1 and $/task per model x reasoning effort."""
    raw = fetch("https://deepswe.datacurve.ai/artifacts/v1.1/leaderboard-live.json")
    if not raw:
        return None
    try:
        rows = json.loads(raw).get("rows") or []
    except (json.JSONDecodeError, AttributeError):
        return None
    runs = {}
    for r in rows:
        name, p1 = r.get("model"), r.get("pass_at_1")
        if not name or not isinstance(p1, (int, float)):
            continue
        effort = (r.get("reasoning_effort") or "").strip().lower()
        key = f"{name} ({effort})" if effort and effort != "none" else name
        if key not in runs or p1 > runs[key].get("pass_at_1", -1):
            runs[key] = r
    pass1, cost = {}, {}
    for key, r in runs.items():
        p1 = r["pass_at_1"]
        pass1[key] = p1 * 100 if p1 <= 1 else float(p1)
        c = r.get("mean_cost_usd")
        if isinstance(c, (int, float)) and c > 0:
            cost[key] = float(c)
    return {"deepswe": pass1, "deepswe_cost": cost}

def _format_metr_key(raw_key):
    """Convert METR v1.1 snake_case model key (e.g. claude_opus_4_6_inspect) to display name."""
    k = re.sub(r"_inspect$", "", raw_key.strip())
    date_tag = ""
    dm = re.search(r"_(20\d\d)[_]?(\d\d)[_]?(\d\d)$", k)
    if dm:
        date_tag = f" ({dm.group(1)}-{dm.group(2)}-{dm.group(3)})"
        k = k[:dm.start()]
    k = re.sub(r"(?<=\d)_(?=\d)", ".", k)
    if k.startswith("claude_"):
        rest = " ".join(w.capitalize() for w in k[len("claude_"):].split("_"))
        return f"Claude {rest}{date_tag}"
    if k.startswith("gpt_"):
        parts = k[len("gpt_"):].split("_")
        ver = parts[0]
        tail = " " + " ".join("4o" if w == "4o" else w.capitalize() for w in parts[1:]) if len(parts) > 1 else ""
        return f"GPT-{ver}{tail}{date_tag}"
    if k == "gpt2":
        return "GPT-2"
    if k.startswith("gemini_"):
        rest = " ".join(w.capitalize() for w in k[len("gemini_"):].split("_"))
        return f"Gemini {rest}{date_tag}"
    if k.startswith("davinci_"):
        return k.replace("_", "-") + date_tag
    if k in ("o1", "o3", "o1_preview"):
        return k.replace("_", "-") + date_tag
    return k.replace("_", " ") + date_tag

def fetch_metr():
    """50%-reliability time horizon in hours (METR-Horizon-v1.1). Pre-release 'early' entries are skipped."""
    out = {}
    html = fetch("https://metr.org/time-horizons/")
    if html:
        pos = html.find("benchmarkDataV1_1")
        if pos != -1:
            brace = html.find("{", pos)
            if brace != -1:
                try:
                    obj, _ = json.JSONDecoder().raw_decode(html, brace)
                    for raw_key, info in (obj.get("results") or {}).items():
                        if raw_key in ("all_time_stitched", "from_2023_on") or "early" in raw_key.lower():
                            continue
                        p50 = ((info.get("metrics") or {}).get("p50_horizon_length") or {}).get("estimate")
                        if isinstance(p50, (int, float)) and p50 > 0:
                            out[_format_metr_key(raw_key)] = float(p50) / 60.0
                except json.JSONDecodeError:
                    pass
    if not out:
        yaml_raw = fetch("https://metr.org/assets/benchmark_results_1_1.yaml")
        if yaml_raw:
            cur = None
            in_p50 = False
            for line in yaml_raw.splitlines():
                km = re.match(r"^  ([a-z0-9_]+):\s*$", line)
                if km:
                    cur = km.group(1)
                    in_p50 = False
                elif re.match(r"^\s+p50_horizon_length:\s*$", line):
                    in_p50 = True
                elif in_p50 and cur:
                    em = re.match(r"^\s+estimate:\s*([0-9.]+)\s*$", line)
                    if em:
                        if cur not in ("all_time_stitched", "from_2023_on") and "early" not in cur.lower():
                            val = float(em.group(1))
                            if val > 0:
                                out[_format_metr_key(cur)] = val / 60.0
                        in_p50 = False
    return {"metr": out} if out else None

fetch_artificial_analysis = fetch_aa

SOURCES = [
    ("Artificial Analysis", fetch_aa),
    ("BenchLM", fetch_benchlm),
    ("DeepSWE", fetch_deepswe),
    ("METR time horizons", fetch_metr),
]

# scale: "linear" -> score = value / best x 100.
#        "log"    -> -25 points per doubling away from best (for metrics spanning
#                    orders of magnitude: time horizons, prices).
# reference: "board" = best on the whole leaderboard; "tracked" = the dashboard's own
#            models (cost: the board's cheapest is a tiny model). A tracked log bench
#            spans its range on a log scale instead: cheapest 100, priciest 0, so one
#            tiny model (GPT-6 Luna at $0.20/MTok) can't clamp everyone else to 0.
BENCHMARKS = [
    dict(id="deepswe", priority="agent", name="DeepSWE", unit="pct", scale="linear", higher_better=True, reference="board",
         url="https://deepswe.datacurve.ai/", description="Long-horizon real-world SWE tasks (pass@1, best effort)"),
    dict(id="metr", priority="agent", name="METR Time Horizon", unit="hours", scale="log", higher_better=True, reference="board",
         url="https://metr.org/time-horizons/", description="Task length completed at 50% reliability"),
    dict(id="aa_terminalbench_v4", priority="agent", name="Terminal-Bench 4.0 (AA)", unit="pct", scale="linear", higher_better=True, reference="board",
         url="https://artificialanalysis.ai/evaluations/terminalbench-4-0", description="Agentic terminal tasks"),
    dict(id="aa_tau_banking", priority="agent", name="τ-Bench Banking (AA)", unit="pct", scale="linear", higher_better=True, reference="board",
         url="https://artificialanalysis.ai/evaluations/tau3-banking", description="Tool use in banking customer-service flows"),
    dict(id="aa_intelligence_index", priority="accuracy", name="AA Intelligence Index", unit="score", scale="linear", higher_better=True, reference="board",
         url="https://artificialanalysis.ai/evaluations/artificial-analysis-intelligence-index", description="Composite of 10 hard evals"),
    dict(id="benchlm", priority="accuracy", name="BenchLM", unit="score", scale="linear", higher_better=True, reference="board",
         url="https://benchlm.ai/compare", description="Composite across verified benchmarks"),
    dict(id="aa_gdp", priority="long_context", name="GDP.pdf (AA)", unit="pct", scale="linear", higher_better=True, reference="board",
         url="https://artificialanalysis.ai/evaluations/gdp-pdf", description="Reasoning & granular instruction following over long professional PDFs"),
    dict(id="deepswe_cost", priority="cost", name="DeepSWE $/task", unit="usd", scale="log", higher_better=False, reference="tracked",
         url="https://deepswe.datacurve.ai/", description="Cost per task on the model's best DeepSWE run"),
    dict(id="aa_price", priority="cost", name="AA blended price", unit="usd_mtok", scale="log", higher_better=False, reference="tracked",
         url="https://artificialanalysis.ai/models", description="$/1M tokens, 3:1 input:output blend"),
]
BENCH_BY_ID = {b["id"]: b for b in BENCHMARKS}
STALE_DAYS = 14
# A board that hasn't directly tested any tracked model released in this window has
# stopped testing current models (AA retired IFBench, Terminal-Bench Hard and τ²-Bench
# this way). It is dropped instead of feeding inherited values forever.
LIVE_BOARD_DAYS = 90

def fmt_value(bench, v):
    u = bench["unit"]
    if u == "pct":
        return f"{v:.1f}%"
    if u == "hours":
        return f"{v:.0f}h" if v >= 10 else (f"{v:.1f}h" if v >= 1 else f"{v * 60:.0f}m")
    if u == "usd":
        return f"${v:.2f}"
    if u == "usd_mtok":
        return f"${v:.2f}/MTok"
    return f"{v:.1f}"

# ---------- model-name matching & reasoning effort ----------

TARGET_EFFORT_MAP = {
    "opus": "medium",
    "fable": "medium",
    "grok": "medium",
    "sol": "medium",
    "astra": "medium",
    "sonnet": "high",
    "haiku": "high",
    "luna": "high",
    "gemini": "high",
    "carbon": "medium",
    "neon": "medium",
    "argon": "high",
    "hydrogen": "high",
    "flash-lite": "high",
}

def get_target_effort(model):
    if "target_effort" in model and model["target_effort"]:
        return model["target_effort"].lower()
    name = model.get("name", "").lower()
    tier = model.get("tier", "").lower()
    for kw, eff in TARGET_EFFORT_MAP.items():
        if kw in name or kw in tier:
            return eff
    return "medium"

def get_target_efforts(model):
    return [get_target_effort(model)]

def extract_effort(name):
    s = str(name).lower()
    for eff in ["xhigh", "medium", "high", "max", "low", "minimal"]:
        if re.search(r'\b' + eff + r'\b', s):
            return "high" if eff == "minimal" else eff
    return None

EFFORT_RANKS = {"low": 1, "medium": 2, "high": 3, "xhigh": 4, "max": 5}

def pick_variants(variants, targets, higher_better):
    """Picks variants matching target reasoning efforts (supports dual high-med).
    Falls back to closest effort or best available when exact targets are absent."""
    if not variants:
        return []
    if len(targets) == 1:
        t = targets[0]
        exact = [v for v in variants if v[2] == t]
        if exact:
            return [max(exact, key=lambda x: x[0] if higher_better else -x[0])]
        t_rank = EFFORT_RANKS.get(t, 3)
        with_effort = [v for v in variants if v[2] in EFFORT_RANKS]
        if with_effort:
            return [min(with_effort, key=lambda v: (abs(EFFORT_RANKS[v[2]] - t_rank), -v[0] if higher_better else v[0]))]
        return [max(variants, key=lambda x: x[0] if higher_better else -x[0])]

    exact_runs = []
    seen = set()
    for t in targets:
        exact = [v for v in variants if v[2] == t]
        if exact:
            best = max(exact, key=lambda x: x[0] if higher_better else -x[0])
            if best[1] not in seen:
                seen.add(best[1])
                exact_runs.append(best)
    if exact_runs:
        return exact_runs

    no_effort = [v for v in variants if v[2] is None]
    if no_effort:
        return [max(no_effort, key=lambda x: x[0] if higher_better else -x[0])]

    t_rank = EFFORT_RANKS.get(targets[0], 3)
    with_effort = [v for v in variants if v[2] in EFFORT_RANKS]
    if with_effort:
        return [min(with_effort, key=lambda v: (abs(EFFORT_RANKS[v[2]] - t_rank), -v[0] if higher_better else v[0]))]
    return [max(variants, key=lambda x: x[0] if higher_better else -x[0])]

def pick_variant(variants, target_effort, higher_better):
    targets = [target_effort] if isinstance(target_effort, str) else target_effort
    runs = pick_variants(variants, targets, higher_better)
    return runs[0] if runs else None

_NOISE_WORDS = {"low", "medium", "high", "xhigh", "max", "minimal", "none", "thinking", "reasoning",
                "non", "adaptive", "preview", "latest", "exp", "experimental", "instruct", "inspect"}

def norm_name(s):
    """Canonical form shared by every board: 'anthropic/claude-opus-4-7-20260101 (max)' and
    'Claude 4.7 Opus' both become 'claude opus 4.7'. Effort/preview/date suffixes are dropped,
    so variants of one model collapse to the same canonical key for indexing."""
    s = _UNICODE_HYPHENS.sub("-", str(s)).lower().split("/")[-1]
    s = re.sub(r"\(.*?\)", " ", s)
    s = re.sub(r"\b20\d\d-?\d\d-?\d\d\b", " ", s)
    s = re.sub(r"(?<=\d)[-_](?=\d)", ".", s)
    s = re.sub(r"[-_:]", " ", s)
    s = " ".join(w for w in s.split() if w not in _NOISE_WORDS)
    return re.sub(r"^claude (\d+(?:\.\d+)?) (opus|sonnet|haiku|fable)\b", r"claude \2 \1", s)

def _family(n):
    return " ".join(re.sub(r"\b\d+(?:\.\d+)?\b", " ", n).split())

def build_index(bench, values):
    """{norm_name: list of (value, board_name, effort)}"""
    idx = {}
    for name, v in values.items():
        k = norm_name(name)
        if not k:
            continue
        eff = extract_effort(name)
        idx.setdefault(k, []).append((v, name, eff))
    return idx

def resolve(model, idx, bench):
    """Target-effort match on name/aliases -> measured. Otherwise the newest OLDER version of the
    same family on this board at target effort -> inherited (provisional). Empty list if neither exists.
    Returns list of (value, board_name, inherited) tuples to support dual reasoning effort."""
    targets = get_target_efforts(model)
    hb = bench["higher_better"]
    keys = [norm_name(model["name"])] + [norm_name(a) for a in model.get("aliases", [])]
    for k in keys:
        if k in idx:
            chosen = pick_variants(idx[k], targets, hb)
            if chosen:
                return [(v[0], v[1], False) for v in chosen]
    mine = _parse_version(model["name"])
    fams = {_family(k) for k in keys}
    # Only inherit within the same major version (Opus 5 -> 5.5 yes, Gemini 3.1 -> 4.0 no):
    # an older major generation says little about a new architecture.
    older = [(k, _parse_version(k)) for k in idx
             if _family(k) in fams and 0 < _parse_version(k) < mine and int(_parse_version(k)) == int(mine)]
    if not older:
        return []
    k = max(older, key=lambda kv: kv[1])[0]
    chosen = pick_variants(idx[k], targets, hb)
    if not chosen:
        return []
    return [(v[0], v[1], True) for v in chosen]

def normalize(bench, v, best, worst):
    if bench["scale"] == "log" and bench["reference"] == "tracked":
        span = math.log(worst / best) if best > 0 and worst > 0 else 0
        return 100.0 if span == 0 else max(0.0, min(100.0, 100 * math.log(worst / v) / span))
    if bench["scale"] == "log":
        ratio = (best / v) if bench["higher_better"] else (v / best)
        return max(0.0, min(100.0, 100 - 25 * math.log2(max(ratio, 1e-9))))
    return max(0.0, min(100.0, 100 * v / best)) if best > 0 else 0.0

# ---------- pipeline ----------

def update_benchmarks(data):
    """Fetch every source into data['raw_benchmarks'] (a cache). A failed or suspiciously
    short fetch keeps the previous values and their original date, so a slow or broken
    board shows as 'as of <date>' instead of silently vanishing."""
    cache = data.setdefault("raw_benchmarks", {})
    cache.pop("aa_lcr", None)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    changes = []
    sources_succeeded = 0
    for label, fn in SOURCES:
        print(f"Fetching {label}...")
        result = fn()
        if fn in (fetch_aa, fetch_artificial_analysis) and os.environ.get("AA_API_KEY"):
            if not result or result == {} or not any(bool(v) for v in result.values()):
                print(f"ERROR: AA_API_KEY is set in env, but {label} returned no data ({result})", file=sys.stderr)
                sys.exit(1)
        if not result or not any(bool(v) for v in result.values()):
            print("  kept cached values (no data)")
            continue
        sources_succeeded += 1
        for bench_id, values in result.items():
            old = cache.get(bench_id, {}).get("values", {})
            if not values:
                print(f"  {bench_id}: empty, kept cache ({len(old)} rows)")
                continue
            if bench_id == "aa_intelligence_index":
                if len(values) < 50:
                    print(f"  {bench_id}: only {len(values)} rows, looks like a broken parse; kept cache")
                    continue
                if old and max(old.values(), default=0) >= 58.0:
                    values = {**old, **values}
            elif bench_id in _AA_MERGE_BENCHES:
                if len(values) < 25:
                    print(f"  {bench_id}: only {len(values)} rows, looks like a broken parse; kept cache")
                    continue
                values = {**old, **values}
            elif old and len(values) < len(old) / 2:
                print(f"  {bench_id}: only {len(values)} rows vs {len(old)} cached, looks like a broken parse; kept cache")
                continue
            values = {k: round(v, 4) for k, v in values.items()}
            if values != old:
                changes.append(f"{bench_id}: {len(values)} rows")
            cache[bench_id] = {"fetched_at": now, "values": values}
            print(f"  {bench_id}: {len(values)} rows")
    if sources_succeeded == 0:
        print("ERROR: 0 benchmark sources succeeded.", file=sys.stderr)
        sys.exit(1)
    return changes

def compute_scores(data):
    cache = data.get("raw_benchmarks", {})
    today = datetime.now(timezone.utc).date()
    models = data["models"]
    for m in models:
        m.pop("needs_calibration", None)
        m.pop("previous_scores", None)
        m["target_effort"] = get_target_effort(m)
        m["per_priority"], m["score_detail"], m["score_basis"] = {}, {}, {}

    recent = [m for m in models if m.get("released")
              and (today - datetime.fromisoformat(m["released"]).date()).days <= LIVE_BOARD_DAYS]
    data["benchmarks"] = {}
    data["dropped_benchmarks"] = {}
    for dim in data["weights"]:
        per_model = {m["id"]: [] for m in models}
        benches = []
        for b in BENCHMARKS:
            if b["priority"] != dim or not cache.get(b["id"], {}).get("values"):
                continue
            entry = cache[b["id"]]
            idx = build_index(b, entry["values"])
            resolved = {m["id"]: resolve(m, idx, b) for m in models}
            if recent and not any(any(not r[2] for r in resolved[m["id"]]) for m in recent if resolved[m["id"]]):
                data["dropped_benchmarks"][b["name"]] = f"hasn't tested any tracked model released in the last {LIVE_BOARD_DAYS} days"
                continue
            benches.append(b)
            if b["reference"] == "tracked":
                pool = [r[0] for runs in resolved.values() for r in runs]
            else:
                pool = [max(v[0] for v in vars) if b["higher_better"] else min(v[0] for v in vars) for vars in idx.values() if vars]
            if not pool:
                continue
            best = max(pool) if b["higher_better"] else min(pool)
            worst = min(pool) if b["higher_better"] else max(pool)
            as_of = entry["fetched_at"]
            stale = (today - datetime.fromisoformat(as_of).date()).days > STALE_DAYS
            for m in models:
                runs = resolved[m["id"]]
                if not runs:
                    continue
                for v, board_name, inherited in runs:
                    eff = extract_effort(board_name)
                    per_model[m["id"]].append({
                        "bench": b["id"], "name": b["name"], "value": v, "display": fmt_value(b, v),
                        "score": round(normalize(b, v, best, worst), 1), "board_name": board_name,
                        "effort": eff, "inherited": inherited, "as_of": as_of, "stale": stale,
                    })
            # Details-tab card: top 5 on the board (or among tracked models for cost).
            if b["reference"] == "tracked":
                ranked = []
                for m in models:
                    runs = resolved[m["id"]]
                    if runs:
                        best_run = max(runs, key=lambda r: r[0] if b["higher_better"] else -r[0])
                        ranked.append((best_run[0], m["name"]))
                ranked.sort(reverse=b["higher_better"])
            else:
                best_per_model = [max(vars, key=lambda x: x[0] if b["higher_better"] else -x[0]) for vars in idx.values() if vars]
                ranked = sorted(((v, n) for v, n, _ in best_per_model), reverse=b["higher_better"])
            data["benchmarks"].setdefault(dim, []).append({
                "id": b["id"], "name": b["name"], "url": b["url"], "description": b["description"],
                "lower_better": not b["higher_better"], "as_of": as_of, "stale": stale,
                "scope": "tracked models" if b["reference"] == "tracked" else "whole board",
                "top5": [{"model": n, "value": fmt_value(b, v)} for v, n in ranked[:5]],
                "top3": [{"model": n, "value": fmt_value(b, v)} for v, n in ranked[:3]],
            })

        for m in models:
            inputs = per_model[m["id"]]
            if not inputs:
                status, score = "none", None
            else:
                score = round(sum(i["score"] for i in inputs) / len(inputs))
                if any(i["inherited"] for i in inputs):
                    status = "provisional"
                elif len({i["bench"] for i in inputs}) < len(benches):
                    status = "partial"
                else:
                    status = "measured"
            measured_ids = {i["bench"] for i in inputs}
            missing = [b["name"] for b in benches if b["id"] not in measured_ids]
            dim_meas = sum(1 for i in inputs if not i["inherited"])
            dim_tot = len(inputs)
            m["per_priority"][dim] = score
            m["score_detail"][dim] = {
                "status": status,
                "inputs": inputs,
                "missing": missing,
                "coverage": {
                    "measured": dim_meas,
                    "total": dim_tot,
                    "provisional": dim_tot - dim_meas,
                },
            }
            parts = []
            for i in inputs:
                eff_tag = f" ({i['effort']})" if i.get("effort") else ""
                p = f"{i['name']}{eff_tag} {i['display']} → {i['score']:.0f}"
                if i["inherited"]:
                    p += f" (inherited from {i['board_name']})"
                if i["stale"]:
                    p += f" (as of {i['as_of']})"
                parts.append(p)
            if missing:
                parts.append("not on " + ", ".join(missing))
            m["score_basis"][dim] = " · ".join(parts) if parts else "No benchmark data yet."

    for m in models:
        all_inputs = [i for det in m["score_detail"].values() for i in det.get("inputs", [])]
        tot_meas = sum(1 for i in all_inputs if not i.get("inherited"))
        tot_all = len(all_inputs)
        m["coverage"] = {
            "measured": tot_meas,
            "total": tot_all,
            "provisional": tot_all - tot_meas,
        }

def recompute_rankings(data):
    """Composite = weighted mean over the priorities at least half the models have a
    score for, so every ranked model is compared on the same mix. A model missing one
    of those priorities is left unranked (composite None) rather than ranked on fewer
    priorities; a priority most models lack is left out for everyone. Both are listed
    in composite_basis. Ranked on the unrounded value."""
    w = data["weights"]
    labels = {"accuracy": "accuracy", "long_context": "long context", "agent": "agent", "cost": "cost"}
    models = data["models"]
    has = lambda m, k: m["per_priority"].get(k) is not None
    included = {k: wt for k, wt in w.items() if sum(has(m, k) for m in models) * 2 >= len(models) and any(has(m, k) for m in models)}
    unranked = {m["name"]: [k for k in included if not has(m, k)] for m in models}
    unranked = {n: ks for n, ks in unranked.items() if ks}
    data["composite_basis"] = {
        "included": list(included),
        "excluded": {k: [m["name"] for m in models if not has(m, k)] for k in w if k not in included},
        "unranked": unranked,
    }
    total_w = sum(included.values())
    raw = {}
    for m in models:
        ok = total_w and m["name"] not in unranked
        raw[m["name"]] = sum(m["per_priority"][k] * wt for k, wt in included.items()) / total_w if ok else None
        m["composite_unrounded"] = round(raw[m["name"]], 2) if ok else None
        m["composite_overall"] = round(raw[m["name"]]) if ok else None

    ranked = sorted((m for m in data["models"] if raw[m["name"]] is not None), key=lambda m: -raw[m["name"]])
    if ranked:
        best = ranked[0]
        pp = best["per_priority"]
        dims = ", ".join(f"{labels.get(k, k)} {pp[k]}" for k in included)
        runners = "; ".join(f"{m['name']} {raw[m['name']]:.2f}" for m in ranked[1:5])
        prov = [k for k in included if best["score_detail"][k]["status"] == "provisional"]
        cov = best.get("coverage", {})
        note = f" Provisional on {', '.join(labels[k] for k in prov)} ({cov.get('measured', 0)}/{cov.get('total', 0)} benchmarks measured, {cov.get('provisional', 0)} inherited)." if prov else ""
        if unranked:
            note += " Not ranked (missing data): " + "; ".join(f"{n} ({', '.join(labels[k] for k in ks)})" for n, ks in unranked.items()) + "."
        if data["composite_basis"]["excluded"]:
            note += f" Not in composite (missing for most models): {', '.join(labels[k] for k in data['composite_basis']['excluded'])}."
        data["best_overall"] = {
            "model": best["name"], "composite": best["composite_overall"],
            "rationale": f"Computed from benchmarks: {dims} → {raw[best['name']]:.2f}. Next: {runners}.{note}",
        }

    data["best_per_priority"] = {}
    for dim in w:
        scoreable = [m for m in data["models"] if m["per_priority"].get(dim) is not None]
        if not scoreable:
            continue
        top = max(scoreable, key=lambda m: m["per_priority"][dim])
        data["best_per_priority"][dim] = {
            "model": top["name"],
            "summary": top["score_basis"][dim],
            "supporting": " · ".join(b["name"] for b in data["benchmarks"].get(dim, [])),
        }

def report_gaps(data):
    gaps = [f"{m['name']} {dim}: {d['status']} ({d.get('coverage', {}).get('measured', 0)}/{d.get('coverage', {}).get('total', 0)} measured)"
            for m in data["models"]
            for dim, d in m["score_detail"].items() if d["status"] in ("provisional", "none")]
    if gaps:
        print("\n=== Not fully measured ===")
        for g in gaps:
            print(f"  [~] {g}")
    for name, why in data.get("dropped_benchmarks", {}).items():
        print(f"  [x] {name} not scored: {why}")

def main():
    data = load_data()
    print(f"Loaded data.json (last updated: {data['last_updated']})\n")

    print("=== Vendor release detection ===")
    release_changes = update_releases(data)

    print("\n=== Benchmark data ===")
    benchmark_changes = update_benchmarks(data)

    print("\n=== Scores & rankings ===")
    compute_scores(data)
    recompute_rankings(data)
    for m in sorted(data["models"], key=lambda m: -(m["composite_unrounded"] or -1)):
        print(f"  {m['name']:<20} {m['composite_unrounded']}  {m['per_priority']}")
    report_gaps(data)

    print("\n=== Summary ===")
    data["last_updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    data["data_status"] = "auto_refreshed"
    save_data(data)
    for c in release_changes + benchmark_changes:
        print(f"  - {c}")
    if not (release_changes or benchmark_changes):
        print("No source changes detected.")
    print(f"\ndata.json updated. Last refresh stamp: {data['last_updated']}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
