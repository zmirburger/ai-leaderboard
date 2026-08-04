# AI Leader Dashboard — project context

Personal dashboard tracking the current leading AI model across Zmir's three priorities:

1. **Accuracy & low hallucination** — 45% weight
2. **Long context & instructions** — 30% weight
3. **Autonomous agent capability** — 25% weight

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
| "Change weights to X/Y/Z" | Edit `weights` block in data.json, then recompute composite_overall for each model |
| "Add benchmark Y" | Add entry to benchmarks block in data.json (under right category), add scraper logic in refresh.py |
| "Drop benchmark Z" | Remove entry from data.json + scraper |
| "Change schedule" | Edit cron expression in `.github/workflows/daily-refresh.yml` |
| "Update the cost/value table" (paste an Artificial Analysis leaderboard screenshot) | Transcribe rows into `data.json`'s `cost_efficiency.entries` (model, vendor, context_window, intelligence_index, cost_per_task_usd), bump `last_manual_update`. Frontier/dominated-option logic is computed client-side in index.html — no manual ranking needed. |

## Composite calculation

```
composite_overall = (accuracy_score * 0.45) + (long_context_score * 0.30) + (agent_score * 0.25)
```

Per-priority scores are normalized to 0-100 from each benchmark's raw output. Default weighting is in data.json.

## Cost vs intelligence (`data.json` → `cost_efficiency`)

Separate from the composite — this is a "given two options of similar capability, which one is wasting money" lens, sourced from Artificial Analysis' model leaderboard (Intelligence Index vs $/task per model×reasoning-effort row). Manually refreshed (the AA page is JS-rendered) by pasting a fresh screenshot and transcribing rows into `cost_efficiency.entries`. The dashboard's "Cost vs intelligence" tab computes the cost/intelligence Pareto frontier client-side and flags every dominated entry with which frontier option beats it outright (cheaper, smarter, or both) — e.g. it's how "Opus xhigh over Fable 5" or "Opus medium over Sonnet max" type calls get surfaced automatically instead of eyeballed.

## Stack

- Static HTML/CSS/JS, no build step
- Python 3.11+ for scraper (requests, beautifulsoup4, lxml)
- Cloudflare Pages for hosting at airank.zmirburger.com (free)
- GitHub Actions for daily cron (free for public repos)

## Repo

https://github.com/zmirburger/ai-leaderboard
