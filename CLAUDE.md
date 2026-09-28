# AI Leader Dashboard — project context

Personal dashboard tracking the current leading AI model across Zmir's four priorities:

1. **Accuracy & low hallucination** — 25% weight
2. **Long context & instructions** — 25% weight
3. **Autonomous agent capability** — 25% weight
4. **Cost efficiency (cost / task)** — 25% weight

## How it works

- `data.json` — single source of truth (all scores, model release info, weights, computed composites)
- `index.html` — static dashboard, fetches data.json on load
- `refresh.py` — Python scraper that hits all sources in `sources.md`, recomputes composites, writes new data.json
- `.github/workflows/daily-refresh.yml` — runs refresh.py daily at 00:00 UTC (8am MYT) via GitHub Actions, commits any changes
- Hosted at: https://airank.zmirburger.com/ (Cloudflare Pages, auto-deploys on every push to main)

## Common requests from Zmir

| Request | What to do |
|---------|-----------|
| "Refresh my AI dashboard" | `cd C:\Users\User\cowork\ai_leaderboard && python refresh.py && git add -A && git commit -m "manual refresh" && git push` |
| "Change weights to X/Y/Z" | Edit `weights` block in data.json, then run `python refresh.py` (it recomputes composites) |
| "Add benchmark Y" | Add a fetcher returning `{bench_id: {model_name: value}}` for the whole board to `SOURCES`, and a `BENCHMARKS` entry (priority, unit, scale, direction) in refresh.py |
| "Drop benchmark Z" | Remove its `BENCHMARKS` entry (and fetcher if unused) in refresh.py; its `raw_benchmarks` cache entry is then ignored |
| "A score looks wrong" | Open the dashboard's Score breakdown tab: it lists every raw input. Fix the source or name matching (add to the model's `aliases` in data.json); never hand-edit `per_priority` |
| "Change schedule" | Edit cron expression in `.github/workflows/daily-refresh.yml` |
| "Update the cost/value table" (paste an Artificial Analysis leaderboard screenshot) | Transcribe rows into `data.json`'s `cost_efficiency.entries` (model, vendor, context_window, intelligence_index, cost_per_task_usd), bump `last_manual_update`. Frontier/dominated-option logic is computed client-side in index.html — no manual ranking needed. |

## Composite calculation

All scores are computed by `refresh.py`; nothing in `per_priority` is hand-set.

1. **Raw values:** each source's full leaderboard goes into `data.json` → `raw_benchmarks` (a cache with `fetched_at`). A failed fetch, or one that returns fewer than half the cached rows, keeps the old values, which are shown with "as of <date>" once more than 14 days old.
2. **Name matching:** `norm_name()` strips vendor prefixes, dates, effort/preview suffixes and reorders "Claude 4.5 Haiku" → "claude haiku 4.5". Board variants of one model keep the best value. Use a model's `aliases` in data.json for naming mismatches (e.g. GPT-6 ↔ "GPT-6 Astra").
3. **Normalization (0–100):** linear benchmarks = value ÷ best on the whole board × 100. Log-scale ones (METR hours, cost) = −25 per doubling from the best. Cost's "best" is the cheapest tracked model.
4. **Priority score** = mean of that priority's benchmark scores. Status is `measured`, `partial` (some boards don't list the model), `provisional` (uses inherited values) or `none`.
5. **New model / slow board:** if a board doesn't list a model, it inherits the newest older version of the same family on that board, but only when that version is less than 1.0 older (Opus 4.7 → 5.5 yes, Grok 3 → 4.7 no). It's flagged Provisional and replaced automatically once the board lists the model.
6. **Composite** = weighted mean over the priorities that every model has a score for (`composite_basis.included`), with the weights rescaled. A priority missing for any model is excluded for all models, so everyone is compared on the same basis.

Artificial Analysis data needs the `AA_API_KEY` repo secret (free key from artificialanalysis.ai). Without it the AA benchmarks keep their cached values, and long context has no source at all.

The dashboard's "Score breakdown" tab renders `score_detail` for every model × priority.

## Cost vs intelligence (`data.json` → `_archived_cost_efficiency`) [Archived / Hidden]

Separate from the composite — this is a "given two options of similar capability, which one is wasting money" lens, sourced from Artificial Analysis' model leaderboard (Intelligence Index vs $/task per model×reasoning-effort row). Manually refreshed (the AA page is JS-rendered) by pasting a fresh screenshot and transcribing rows into `cost_efficiency.entries`. The dashboard's "Cost vs intelligence" tab computes the cost/intelligence Pareto frontier client-side and flags every dominated entry with which frontier option beats it outright (cheaper, smarter, or both) — e.g. it's how "Opus xhigh over Fable 5" or "Opus medium over Sonnet max" type calls get surfaced automatically instead of eyeballed. It also ranks the frontier by intelligence-per-dollar to surface a "Top 3 for everyday tasks" pick.

**Scope: Zmir's shortlist only** — Claude Sonnet & Opus (every reasoning effort: low/medium/high/xhigh/max) vs Gemini vs Grok. Not the full AA roster (no GPT, Kimi, Qwen, GLM, etc.) and not Claude Fable — leave those out even if they're in the screenshot. When AA doesn't publish a given Claude effort level (or a Gemini/Grok row), set `"estimated": true` and write a one-line `estimate_basis` explaining the interpolation — don't silently guess. Replace estimated entries with real numbers the next time a screenshot covers them.

## Stack

- Static HTML/CSS/JS, no build step
- Python 3.11+ for scraper (requests, beautifulsoup4, lxml)
- Cloudflare Pages for hosting at airank.zmirburger.com (free)
- GitHub Actions for daily cron (free for public repos)

## Repo

https://github.com/zmirburger/ai-leaderboard
