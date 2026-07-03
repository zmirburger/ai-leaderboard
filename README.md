# AI Leader Dashboard

Daily-refreshed view of the leading AI model across three priorities.

**Live URL:** https://zmirburger.github.io/ai-leaderboard/ — bookmark on phone home screen for one-tap access.

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

## Tracked benchmarks

**Agent:** METR Time Horizon, τ-bench, BrowseComp
**Accuracy:** Vectara HHEM, AA Omniscience, AA Intelligence Index, Scale SEAL (RLI)
**Long context:** Fiction.LiveBench, AA Long-Context, AA IFBench
**Vibe check:** LMArena (kept but not in composite)

## Tracked vendors

Anthropic (Claude Fable/Opus/Sonnet/Haiku), OpenAI (GPT), Google (Gemini), xAI (Grok)

## Custom domain (airank.zmirburger.com via Cloudflare)

No code changes needed — the site is plain static files. Two options:

**Option A — Cloudflare Pages (recommended, everything lives in Cloudflare):**
1. Cloudflare dashboard → Workers & Pages → Create → Pages → Connect to Git → pick `zmirburger/ai-leaderboard`
2. Build settings: no framework, no build command, output directory `/`
3. After first deploy: Custom domains → add `airank.zmirburger.com` (Cloudflare creates the DNS record automatically)
4. Daily GitHub Actions commits trigger automatic redeploys — no other changes needed

**Option B — keep GitHub Pages, point the domain at it:**
1. Cloudflare DNS: add `CNAME` record, name `airank`, target `zmirburger.github.io`
2. GitHub repo → Settings → Pages → Custom domain → `airank.zmirburger.com`, enable "Enforce HTTPS"
3. In Cloudflare, set SSL/TLS mode to "Full" for the zone (avoids redirect loops)
