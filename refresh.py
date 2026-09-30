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

_OPENAI_URL = "https://help.openai.com/en/articles/9624314-model-release-notes"
_openai_soup = None

def _get_openai_soup():
    global _openai_soup
    if _openai_soup is None:
        html = fetch(_OPENAI_URL)
        _openai_soup = BeautifulSoup(html, "html.parser") if html else None
    return _openai_soup

def _detect_openai_tier(tier):
    """GPT-6 ships as three tiers (Astra > Sol > Luna), versioned independently
    (e.g. GPT-6.1 Sol next to GPT-6 Astra)."""
    soup = _get_openai_soup()
    if not soup:
        return None
    version = _find_best_match(soup, rf"GPT-(\d+(?:\.\d+)?)[ -]{tier}\b", include_body=True)
    if not version:
        return None
    return _result(f"GPT-{version} {tier}", soup.get_text(" ", strip=True), _OPENAI_URL)

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
            print(f"  NEW RELEASE: {old} -> {name} (scores inherit from older versions until benchmarked)")
        else:
            print(f"  no change ({name})")
    return changes

# ---------- benchmark sources ----------
# Each fetcher returns {bench_id: {board_model_name: value}} covering EVERY model on
# the board (not just a top 3), or None when the fetch/parse fails. Values are in
# natural units: percentages 0-100, hours, USD.

AA_URL = "https://artificialanalysis.ai/api/v2/data/llms/models"
AA_EVAL_KEYS = {
    "aa_intelligence_index": ["artificial_analysis_intelligence_index"],
    "aa_lcr": ["lcr", "aa_lcr"],
    "aa_terminalbench_v4": ["terminalbench_v4_0"],
    "aa_tau_banking": ["tau_banking"],
}

def fetch_aa():
    """Artificial Analysis free data API. Needs AA_API_KEY (repo secret)."""
    key = os.environ.get("AA_API_KEY")
    if not key:
        print("  skipped (AA_API_KEY not set)")
        return None
    raw = fetch(AA_URL, extra_headers={"x-api-key": key})
    if not raw:
        return None
    try:
        items = json.loads(raw).get("data") or []
    except (json.JSONDecodeError, AttributeError):
        return None
    out = {b: {} for b in list(AA_EVAL_KEYS) + ["aa_price"]}
    seen_keys = set()
    for it in items:
        name = it.get("name")
        if not name:
            continue
        evals = it.get("evaluations") or {}
        seen_keys.update(evals.keys())
        for bench, candidates in AA_EVAL_KEYS.items():
            v = next((evals[k] for k in candidates if isinstance(evals.get(k), (int, float))), None)
            if v is not None:
                out[bench][name] = float(v)
        price = (it.get("pricing") or {}).get("price_1m_blended_3_to_1")
        if isinstance(price, (int, float)) and price > 0:
            out["aa_price"][name] = float(price)
    print(f"  {len(items)} models; evaluation fields: {sorted(seen_keys)}")
    # AA reports most evals as 0-1 fractions; store as percentages.
    for bench in ("aa_lcr", "aa_terminalbench_v4", "aa_tau_banking"):
        vals = out[bench]
        if vals and max(vals.values()) <= 1.0:
            out[bench] = {k: v * 100 for k, v in vals.items()}
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
    """pass@1 per model (best reasoning effort) and, when published, the $/task of that same run."""
    raw = fetch("https://deepswe.datacurve.ai/artifacts/v1.1/leaderboard-live.json")
    if not raw:
        return None
    try:
        rows = json.loads(raw).get("rows") or []
    except (json.JSONDecodeError, AttributeError):
        return None
    if rows:
        print(f"  row fields: {sorted(rows[0].keys())}")
    best = {}
    for r in rows:
        name, p1 = r.get("model"), r.get("pass_at_1")
        if not name or not isinstance(p1, (int, float)):
            continue
        if name not in best or p1 > best[name].get("pass_at_1", -1):
            best[name] = r
    pass1, cost = {}, {}
    for name, r in best.items():
        pass1[name] = r["pass_at_1"] * 100 if r["pass_at_1"] <= 1 else float(r["pass_at_1"])
        c = r.get("mean_cost_usd")
        if isinstance(c, (int, float)) and c > 0:
            cost[name] = float(c)
    return {"deepswe": pass1, "deepswe_cost": cost}

def fetch_metr():
    """50%-reliability time horizon in hours. Pre-release '(early)' entries are skipped."""
    html = fetch("https://metr.org/time-horizons/")
    if not html:
        return None
    m = re.search(r'var\s+thData\s*=\s*(\{.*?\})\s*;', html, re.DOTALL)
    if not m:
        return None
    try:
        agents = json.loads(m.group(1)).get("agents", {})
    except json.JSONDecodeError:
        return None
    out = {}
    for name, info in agents.items():
        coef, intercept = info.get("coefficient"), info.get("intercept")
        if "(early)" in name.lower() or not coef or intercept is None:
            continue
        try:
            out[name] = math.exp(-intercept / coef) / 60
        except (OverflowError, ValueError):
            continue
    return {"metr": out}

def fetch_vectara():
    """Factual consistency rate (100 - hallucination rate) from the HHEM README table."""
    text = fetch("https://raw.githubusercontent.com/vectara/hallucination-leaderboard/main/README.md")
    if not text:
        return None
    out = {}
    for line in text.splitlines():
        cols = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cols) < 3 or "/" not in cols[0]:
            continue
        m = re.match(r"([\d.]+)\s*%", cols[2])
        if m:
            out[cols[0]] = float(m.group(1))
    return {"vectara": out}

SOURCES = [
    ("Artificial Analysis API", fetch_aa),
    ("BenchLM", fetch_benchlm),
    ("DeepSWE", fetch_deepswe),
    ("METR time horizons", fetch_metr),
    ("Vectara HHEM", fetch_vectara),
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
         url="https://artificialanalysis.ai/evaluations/terminalbench", description="Agentic terminal tasks"),
    dict(id="aa_tau_banking", priority="agent", name="τ-Bench Banking (AA)", unit="pct", scale="linear", higher_better=True, reference="board",
         url="https://artificialanalysis.ai/evaluations/tau2-bench", description="Tool use in banking customer-service flows"),
    dict(id="aa_intelligence_index", priority="accuracy", name="AA Intelligence Index", unit="score", scale="linear", higher_better=True, reference="board",
         url="https://artificialanalysis.ai/evaluations/artificial-analysis-intelligence-index", description="Composite of 10 hard evals"),
    dict(id="vectara", priority="accuracy", name="Vectara HHEM", unit="pct", scale="linear", higher_better=True, reference="board",
         url="https://github.com/vectara/hallucination-leaderboard", description="Factual consistency when summarizing (100 − hallucination rate)"),
    dict(id="benchlm", priority="accuracy", name="BenchLM", unit="score", scale="linear", higher_better=True, reference="board",
         url="https://benchlm.ai/compare", description="Composite across verified benchmarks"),
    dict(id="aa_lcr", priority="long_context", name="AA Long-Context Reasoning", unit="pct", scale="linear", higher_better=True, reference="board",
         url="https://artificialanalysis.ai/evaluations/artificial-analysis-long-context-reasoning", description="Reasoning over ~100k-token document sets"),
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

# ---------- model-name matching ----------

_NOISE_WORDS = {"low", "medium", "high", "xhigh", "max", "minimal", "none", "thinking", "reasoning",
                "non", "adaptive", "preview", "latest", "exp", "experimental", "instruct", "inspect"}

def norm_name(s):
    """Canonical form shared by every board: 'anthropic/claude-opus-4-7-20260101 (max)' and
    'Claude 4.7 Opus' both become 'claude opus 4.7'. Effort/preview/date suffixes are dropped,
    so a board's variants of one model collapse together (best value kept)."""
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
    """{norm_name: (value, board_name)}, keeping each model's best variant."""
    idx = {}
    for name, v in values.items():
        k = norm_name(name)
        if not k:
            continue
        if k not in idx or ((v > idx[k][0]) if bench["higher_better"] else (v < idx[k][0])):
            idx[k] = (v, name)
    return idx

def resolve(model, idx):
    """Exact match on name/aliases -> measured. Otherwise the newest OLDER version of the
    same family on this board -> inherited (provisional). None if neither exists."""
    keys = [norm_name(model["name"])] + [norm_name(a) for a in model.get("aliases", [])]
    for k in keys:
        if k in idx:
            return idx[k][0], idx[k][1], False
    mine = _parse_version(model["name"])
    fams = {_family(k) for k in keys}
    # Only inherit across a gap of less than one major version (Opus 4.7 -> 5.5 yes,
    # Grok 3 -> 4.7 no): an older-generation model says little about a new one.
    older = [(k, _parse_version(k)) for k in idx
             if _family(k) in fams and 0 < _parse_version(k) < mine and mine - _parse_version(k) < 1.0]
    if not older:
        return None
    k = max(older, key=lambda kv: kv[1])[0]
    return idx[k][0], idx[k][1], True

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
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    changes = []
    for label, fn in SOURCES:
        print(f"Fetching {label}...")
        result = fn()
        if not result:
            print("  kept cached values (no data)")
            continue
        for bench_id, values in result.items():
            old = cache.get(bench_id, {}).get("values", {})
            if not values:
                print(f"  {bench_id}: empty, kept cache ({len(old)} rows)")
                continue
            if old and len(values) < len(old) / 2:
                print(f"  {bench_id}: only {len(values)} rows vs {len(old)} cached, looks like a broken parse; kept cache")
                continue
            values = {k: round(v, 4) for k, v in values.items()}
            if values != old:
                changes.append(f"{bench_id}: {len(values)} rows")
            cache[bench_id] = {"fetched_at": now, "values": values}
            print(f"  {bench_id}: {len(values)} rows")
    return changes

def compute_scores(data):
    cache = data.get("raw_benchmarks", {})
    today = datetime.now(timezone.utc).date()
    models = data["models"]
    for m in models:
        m.pop("needs_calibration", None)
        m.pop("previous_scores", None)
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
            resolved = {m["id"]: resolve(m, idx) for m in models}
            if recent and not any(resolved[m["id"]] and not resolved[m["id"]][2] for m in recent):
                data["dropped_benchmarks"][b["name"]] = f"hasn't tested any tracked model released in the last {LIVE_BOARD_DAYS} days"
                continue
            benches.append(b)
            pool = [r[0] for r in resolved.values() if r] if b["reference"] == "tracked" else [v for v, _ in idx.values()]
            if not pool:
                continue
            best = max(pool) if b["higher_better"] else min(pool)
            worst = min(pool) if b["higher_better"] else max(pool)
            as_of = entry["fetched_at"]
            stale = (today - datetime.fromisoformat(as_of).date()).days > STALE_DAYS
            for m in models:
                r = resolved[m["id"]]
                if not r:
                    continue
                v, board_name, inherited = r
                per_model[m["id"]].append({
                    "bench": b["id"], "name": b["name"], "value": v, "display": fmt_value(b, v),
                    "score": round(normalize(b, v, best, worst), 1), "board_name": board_name,
                    "inherited": inherited, "as_of": as_of, "stale": stale,
                })
            # Details-tab card: top 3 on the board (or among tracked models for cost).
            ranked = sorted(((v, n) for v, n in idx.values()), reverse=b["higher_better"])
            if b["reference"] == "tracked":
                ranked = sorted(((r[0], m["name"]) for m in models if (r := resolved[m["id"]])), reverse=b["higher_better"])
            data["benchmarks"].setdefault(dim, []).append({
                "id": b["id"], "name": b["name"], "url": b["url"], "description": b["description"],
                "lower_better": not b["higher_better"], "as_of": as_of, "stale": stale,
                "scope": "tracked models" if b["reference"] == "tracked" else "whole board",
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
                elif len(inputs) < len(benches):
                    status = "partial"
                else:
                    status = "measured"
            measured_ids = {i["bench"] for i in inputs}
            missing = [b["name"] for b in benches if b["id"] not in measured_ids]
            m["per_priority"][dim] = score
            m["score_detail"][dim] = {"status": status, "inputs": inputs, "missing": missing}
            parts = []
            for i in inputs:
                p = f"{i['name']} {i['display']} → {i['score']:.0f}"
                if i["inherited"]:
                    p += f" (inherited from {i['board_name']})"
                if i["stale"]:
                    p += f" (as of {i['as_of']})"
                parts.append(p)
            if missing:
                parts.append("not on " + ", ".join(missing))
            m["score_basis"][dim] = " · ".join(parts) if parts else "No benchmark data yet."

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
        runners = "; ".join(f"{m['name']} {raw[m['name']]:.2f}" for m in ranked[1:3])
        prov = [k for k in included if best["score_detail"][k]["status"] == "provisional"]
        note = f" Provisional on {', '.join(labels[k] for k in prov)} (inherited benchmark values)." if prov else ""
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
    gaps = [f"{m['name']} {dim}: {d['status']}" for m in data["models"]
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
