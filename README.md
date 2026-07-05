# AI Leader Dashboard

Daily-refreshed view of the leading AI model across three priorities.

**Live URL:** https://airank.zmirburger.com/ — bookmark on phone home screen for one-tap access.

## Priorities & weights

| Priority | Weight |
|----------|--------|
| Accuracy & low hallucination | 45% |
| Long context & instructions | 30% |
| Autonomous agent | 25% |

To change weights, edit `data.json` and re-run `refresh.py`.

## Refresh

- **Automatic:** daily at 8am MYT (00:00 UTC) via GitHub Actions
- **Manual:** ask Claude to "refresh my AI dashboard" — runs locally and pushes

## Files

| File | Purpose |
|------|---------|
| `index.html` | The dashboard (reads data.json) |
| `data.json` | Current scores + model info |
| `refresh.py` | Scraper that updates data.json |
| `sources.md` | All source URLs being scraped |
| `backup.md` | Backup instructions |
| `CLAUDE.md` | Project context for Claude |
| `.github/workflows/daily-refresh.yml` | Cron config |

## Claude tab

A Claude-only view with two sub-tabs:

- **Capability** — every Claude tier (Fable/Opus/Sonnet) × reasoning-effort level (low → max), ranked by estimated capability. A lower model at high effort can outrank a higher model at low effort.
- **Max plan cost** — the same combos ranked by relative Claude Max quota burn (× the lightest combo).

These are hand-maintained estimates, not benchmarks. Model names + capability base come live from the `models` block (so a version bump flows through automatically); tune the effort deltas and per-tier `cost_base` in the `claude_lens` block of `data.json`.

## Tracked benchmarks

**Agent:** METR Time Horizon, τ-bench, BrowseComp
**Accuracy:** Vectara HHEM, AA Omniscience, AA Intelligence Index, Scale SEAL (RLI)
**Long context:** Fiction.LiveBench, AA Long-Context, AA IFBench
**Vibe check:** LMArena (kept but not in composite)

## Tracked vendors

Anthropic (Claude Fable/Opus/Sonnet/Haiku), OpenAI (GPT), Google (Gemini), xAI (Grok)

## Hosting

Served by **Cloudflare Pages** at https://airank.zmirburger.com/ — connected to this repo,
production branch `main`, no build command, output directory `/`. Every push to `main`
(including the daily GitHub Actions refresh commit) triggers an automatic redeploy.
GitHub Pages is no longer used.
