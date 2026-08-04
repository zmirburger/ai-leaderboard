# Sources scraped by refresh.py

## Benchmark leaderboards

### Agent (25% weight)
- **METR Time Horizon** — https://metr.org/time-horizons/
- **τ-bench** — https://github.com/sierra-research/tau-bench (README) + cross-check on Artificial Analysis if listed
- **BrowseComp** — https://artificialanalysis.ai/ (search) + https://openai.com/index/browsecomp/

### Accuracy & low hallucination (45% weight)
- **Vectara HHEM** — https://huggingface.co/spaces/vectara/leaderboard
- **AA Omniscience** — https://artificialanalysis.ai/evaluations/omniscience
- **AA Intelligence Index** — https://artificialanalysis.ai/evaluations/artificial-analysis-intelligence-index
- **Scale SEAL (RLI)** — https://scale.com/leaderboard/rli

### Long context & instructions (30% weight)
- **Fiction.LiveBench** — https://epoch.ai/benchmarks/fictionlivebench
- **AA Long-Context Reasoning** — https://artificialanalysis.ai/evaluations/artificial-analysis-long-context-reasoning
- **AA IFBench** — https://artificialanalysis.ai/evaluations/ifbench

### Vibe check (not in composite)
- **LMArena** — https://lmarena.ai/leaderboard

### Cost vs intelligence (not in composite — separate "is the spend worth it" lens)
- **AA model leaderboard** — https://artificialanalysis.ai/leaderboards/models — Intelligence Index + $/task per model×reasoning-effort row. JS-rendered, not scraped by refresh.py; refresh manually by pasting a new screenshot into `data.json`'s `cost_efficiency.entries` (see CLAUDE.md). The dashboard computes the cost/intelligence Pareto frontier and flags dominated options client-side — no manual "which one wins" judgment needed once the raw numbers are in.

## Vendor release pages

- **Anthropic** — https://platform.claude.com/docs/en/release-notes/overview
- **OpenAI** — https://help.openai.com/en/articles/9624314-model-release-notes
- **Google DeepMind** — https://ai.google.dev/gemini-api/docs/changelog
- **xAI** — https://docs.x.ai/developers/release-notes

## Notes

- Several leaderboards render via JavaScript and may require headless browser scraping (Playwright) instead of plain requests.
- HHEM publishes a CSV under the hood — easier to parse than DOM.
- LMArena exposes Elo via their public API endpoint.
- Vendor changelog pages change formats — scraper uses tolerant parsing and falls back to "release detected, manual update needed" if parse fails.
