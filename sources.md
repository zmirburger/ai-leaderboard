# Sources fetched by refresh.py

Every source is fetched as a full leaderboard (all models), cached in `data.json` → `raw_benchmarks`, and turned into scores by `BENCHMARKS` in refresh.py. See CLAUDE.md → "Composite calculation".

## Benchmark sources

| Source | Endpoint | Feeds | Key? |
|--------|----------|-------|------|
| Artificial Analysis API | https://artificialanalysis.ai/api/v2/data/llms/models | Intelligence Index (accuracy) · Long-Context Reasoning (long context) · Terminal-Bench 4.0, τ-Bench Banking (agent) · blended $/MTok (cost) | `AA_API_KEY` secret |
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

- Scraping AA's HTML pages, LMArena, τ-bench README, BrowseComp, Scale SEAL, and Fiction.LiveBench. They were either never fetched automatically (their top-3 lists were typed in by hand) or failed to parse on every run. The AA API replaces the AA pages. AA Omniscience isn't in the API, so it's dropped.
- AA IFBench, Terminal-Bench Hard and τ²-Bench (2026-09-30): AA stopped running them on new models (no Claude 5.x, GPT-6, Gemini 3.8 or Grok 4.7 rows), so every current model was scored on its predecessor's result. Terminal-Bench 4.0 and τ-Bench Banking replace the agent ones; IFBench has no AA successor.

## Cost vs intelligence (archived, not in composite)

- **AA model leaderboard** — https://artificialanalysis.ai/leaderboards/models. Manual screenshot transcription into `_archived_cost_efficiency` (see CLAUDE.md).
