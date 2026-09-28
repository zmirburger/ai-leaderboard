# Sources fetched by refresh.py

Every source is fetched as a full leaderboard (all models), cached in `data.json` → `raw_benchmarks`, and turned into scores by `BENCHMARKS` in refresh.py. See CLAUDE.md → "Composite calculation".

## Benchmark sources

| Source | Endpoint | Feeds | Key? |
|--------|----------|-------|------|
| Artificial Analysis API | https://artificialanalysis.ai/api/v2/data/llms/models | Intelligence Index, Omniscience (accuracy) · Long-Context Reasoning, IFBench (long context) · Terminal-Bench Hard, τ²-Bench (agent) · blended $/MTok (cost) | `AA_API_KEY` secret |
| BenchLM | https://benchlm.ai/api/leaderboard | accuracy | no |
| DeepSWE | https://deepswe.datacurve.ai/artifacts/v1.1/leaderboard-live.json | agent (pass@1) · cost ($/task, if the row publishes it) | no |
| METR | https://metr.org/time-horizons/ (`thData` JSON) | agent (50% time horizon) | no |
| Vectara HHEM | https://raw.githubusercontent.com/vectara/hallucination-leaderboard/main/README.md | accuracy (factual consistency) | no |

## Vendor release pages

- **Anthropic** — https://platform.claude.com/docs/en/release-notes/overview
- **OpenAI** — https://help.openai.com/en/articles/9624314-model-release-notes
- **Google DeepMind** — https://ai.google.dev/gemini-api/docs/changelog
- **xAI** — https://docs.x.ai/developers/release-notes

## Dropped

- Scraping AA's HTML pages, LMArena, τ-bench README, BrowseComp, Scale SEAL, and Fiction.LiveBench. They were either never fetched automatically (their top-3 lists were typed in by hand) or failed to parse on every run. The AA API replaces the AA pages and supplies τ²-Bench.

## Cost vs intelligence (archived, not in composite)

- **AA model leaderboard** — https://artificialanalysis.ai/leaderboards/models. Manual screenshot transcription into `_archived_cost_efficiency` (see CLAUDE.md).
