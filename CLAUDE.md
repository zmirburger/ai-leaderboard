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

## Composite calculation

All scores are computed by `refresh.py`; nothing in `per_priority` is hand-set.

1. **Raw values:** each source's full leaderboard goes into `data.json` → `raw_benchmarks` (a cache with `fetched_at`). A failed fetch, or one that returns fewer than half the cached rows, keeps the old values, which are shown with "as of <date>" once more than 14 days old.
2. **Name matching & reasoning effort:** `norm_name()` canonicalizes names. Each model targets Zmir's configured reasoning effort: **medium** for heavyweight tiers (`Opus`, `Fable`, `Carbon`, `Neon`, `Grok`, `Sol`, `Astra`); **high** for fast/cheaper or single-effort tiers (`Sonnet`, `Haiku`, `Luna`, `Argon`, `Hydrogen`, `Flash-Lite`, `Gemini`). Scrapers pick the target effort run, falling back to the closest available or board default.
3. **Normalization (0–100):** linear benchmarks = value ÷ best on the whole board × 100. METR hours = −25 per doubling from the best. Cost is log-scaled across the tracked models only: cheapest 100, priciest 0 (a fixed −25/doubling clamped everyone to 0 once $0.20 GPT-6 Luna joined).
4. **Priority score** = mean of that priority's benchmark scores. Status is `measured`, `partial` (some boards don't list the model), `provisional` (uses inherited values) or `none`. Coverage ratios (`measured/total`) are computed overall and per priority.
5. **New model / slow board:** if a board doesn't list a model, it inherits the newest older version of the same family on that board within the same major version (`Opus 5 → 5.5` yes, `Gemini 3.1 → 4.0` no). It's flagged Provisional with its coverage ratio (e.g. `5/8`) and replaced automatically once the board lists the model. A board that hasn't directly tested any tracked model released in the last 90 days (`LIVE_BOARD_DAYS`) is dropped (`dropped_benchmarks` in data.json) instead of feeding inherited values forever — AA retired IFBench/Terminal-Bench Hard/τ²-Bench, and Vectara HHEM was dropped on 2026-10-12.
6. **Composite** = weighted mean over the priorities at least half the models have a score for (`composite_basis.included`), with the weights rescaled. A model missing one of those priorities is unranked (`composite_basis.unranked`) rather than scored on fewer priorities, so every ranked model is compared on the same mix.

Artificial Analysis data is fetched directly from AA's public `leaderboards/models` Next.js RSC stream (Intelligence Index v5.0, LCR, GDP.pdf, Terminal-Bench 4.0, τ-Bench Banking, and 3:1 blended pricing), optionally supplemented by `AA_API_KEY` on `/api/v2/language/models/free`.

The dashboard's "Score breakdown" tab renders `score_detail` for every model × priority.

## Stack

- Static HTML/CSS/JS, no build step
- Python 3.11+ for scraper (requests, beautifulsoup4, lxml)
- Cloudflare Pages for hosting at airank.zmirburger.com (free)
- GitHub Actions for daily cron (free for public repos)

## Repo

https://github.com/zmirburger/ai-leaderboard
