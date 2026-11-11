# Sources fetched by refresh.py

Every source is fetched as a full leaderboard (all models), cached in `data.json` → `raw_benchmarks`, and turned into scores by `BENCHMARKS` in refresh.py. See CLAUDE.md → "Composite calculation".

## Benchmark sources

| Source | Endpoint | Feeds | Key? |
|--------|----------|-------|------|
| Artificial Analysis | https://artificialanalysis.ai/leaderboards/models (RSC stream) + `/api/v2/language/models/free` | Intelligence Index v5.0 (accuracy) · Long-Context Reasoning (long context) · Terminal-Bench 4.0, τ-Bench Banking (agent) · 3:1 blended $/MTok (cost) | optional (`AA_API_KEY` supplements historical rows) |
| BenchLM | https://benchlm.ai/api/leaderboard | accuracy | no |
| DeepSWE | https://deepswe.datacurve.ai/artifacts/v1.1/leaderboard-live.json | agent (pass@1) · cost ($/task, if the row publishes it) | no |
| METR | https://metr.org/time-horizons/ (`benchmarkDataV1_1` / `benchmark_results_1_1.yaml`) | agent (50% time horizon, v1.1) | no |

## Vendor release pages

- **Anthropic** — https://platform.claude.com/docs/en/release-notes/overview
- **OpenAI** — https://artificialanalysis.ai/leaderboards/models (`releases` metadata; `help.openai.com` returns `403`)
- **Google DeepMind** — https://ai.google.dev/gemini-api/docs/changelog
- **xAI** — https://docs.x.ai/developers/release-notes (+ AA `releases` ISO date fallback)

## Dropped

- **Vectara HHEM** (2026-10-12): Stalled on legacy versions (only listed Claude 4.7 and Gemini 3 Preview), causing persistent provisional scores across all current models. Accuracy is now evaluated via AA Intelligence Index and BenchLM.
- Scraping AA's HTML pages, LMArena, τ-bench README, BrowseComp, Scale SEAL, and Fiction.LiveBench. They were either never fetched automatically (their top-3 lists were typed in by hand) or failed to parse on every run. The AA API replaces the AA pages. AA Omniscience isn't in the API, so it's dropped.
- AA IFBench, Terminal-Bench Hard and τ²-Bench (2026-09-30): AA stopped running them on new models (no Claude 5.x, GPT-6, Gemini 3.8 or Grok 4.7 rows), so every current model was scored on its predecessor's result. Terminal-Bench 4.0 and τ-Bench Banking replace the agent ones; IFBench has no AA successor.
