# AI Leader Dashboard

Daily-refreshed view of the leading AI model across four priorities.

**Live URL:** https://airank.zmirburger.com/ — bookmark on phone home screen for one-tap access.

## Priorities & weights

| Priority | Weight |
|----------|--------|
| Accuracy & low hallucination | 25% |
| Long context & instructions | 25% |
| Autonomous agent | 25% |
| Cost efficiency (cost / task) | 25% |

To change weights, edit `data.json` and re-run `refresh.py` (or adjust custom weight sliders in the dashboard UI).

## Refresh

- **Automatic:** daily at 8am MYT (00:00 UTC) via GitHub Actions
- **Manual:** ask Claude / Antigravity to "refresh my AI dashboard" — runs locally and pushes

## Files

| File | Purpose |
|------|---------|
| `index.html` | The dashboard (reads data.json) |
| `data.json` | Current scores + model info |
| `refresh.py` | Scraper that updates data.json |
| `sources.md` | All source URLs being scraped |
| `CLAUDE.md` | Project context |
| `.github/workflows/daily-refresh.yml` | Cron config |

## Tracked benchmarks

**Agent:** DeepSWE, Terminal-Bench 4.0 (AA), τ-Bench Banking (AA), METR Time Horizon
**Accuracy:** AA Intelligence Index, BenchLM
**Long context:** AA Long-Context Reasoning
**Cost:** DeepSWE $/task, AA blended $/MTok

## Tracked vendors

Anthropic (Claude Fable/Opus/Sonnet/Haiku), OpenAI (GPT Astra/Sol/Luna), Google (Gemini Carbon/Argon/Pro/Flash), xAI (Grok)

## Hosting

Served by **Cloudflare Pages** at https://airank.zmirburger.com/ — connected to this repo,
production branch `main`, no build command, output directory `/`. Every push to `main`
(including the daily GitHub Actions refresh commit) triggers an automatic redeploy.
GitHub Pages is no longer used.
