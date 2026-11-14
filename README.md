# Muse-Top-500-Recommend

Mag-500 Recommendation: a deterministic, sequential-reporting,
resumable research workflow over the full S&P 500 — market data for
every constituent, a fundamental valuation for every ticker, a Top 10
shortlist by Final score, technical buy analysis on the Top 10, and a
final Top 2, delivered in Muse chat with a consolidated audit log.

Copy-by-phase implementation of `MAG500_RECOMMENDATION_PRD.md`
(Phases 0–14) from READ-ONLY `s777data/options-wheel-agent` @ `0b0d64a`
— with the PRD's placeholder valuation replaced: **Phase 6 calls the
Muse Business Evaluation Dashboard engine (V5.5 + GAV-Code) in-process**
and the Final score is

    Final = 0.5×Business + 0.25×Value + 0.25×GAV-Code
    (Business/Value are the engine's 0–10 totals ×10; GAV-Code is 0–100)

A run is **code-only: ~0 model tokens**. No Hermes, no model-backed
skill invocation anywhere in the run path (see PLAN.md, DEVIATIONS.md).

## Design highlights (approved 2026-11-14)

- **Robinhood is batched, never per-ticker** — quotes in chunks of 100,
  fundamentals 20/call, historicals/indicators 10/call: ~31 MCP calls
  for Phase 4 instead of 1,006 (`scripts/robinhood_transport.py`).
- **Valuation runs in a bounded process pool** — `ProcessPoolExecutor`,
  `MAG500_VALUATION_WORKERS` default 4 (max 8), shared SEC rate limiter
  ≤8 req/s, per-worker EDGAR cache dirs; canonical output is still
  assembled in input-rank order (`scripts/valuation_adapter.py`).
- **Technicals run as direct code** — the copied
  `technical_analysis_recommend` package is invoked by
  `scripts/technical_adapter.py` on batched Robinhood data.
- **Delivery is Muse delivery** — Phase 12 payloads are written to the
  run delivery directory (`scripts/delivery.py`); no Telegram.

## Run it (code-only, no model)

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

# Build/refresh the S&P 500 universe snapshot (Wikipedia primary,
# Robinhood-batched market-cap ranking):
.venv/bin/python -m scripts.build_sp500_universe

# Full run via the durable launcher (detached, survives the session):
MAG500_BASE=$PWD .venv/bin/python skills/mag-500-recommendation/scripts/mag50_launcher.py start
MAG500_BASE=$PWD .venv/bin/python skills/mag-500-recommendation/scripts/mag50_progress_report.py

# Or run the orchestrator directly (env overrides: MAG500_INPUT,
# MAG500_OUTPUT, MAG500_HISTORY, MAG500_LOG, MAG500_RUNS,
# MAG500_VALUATION_WORKERS, MAG500_VALUATION_TIMEOUT_SECONDS, ...):
.venv/bin/python skills/mag-500-recommendation/scripts/mag50_auto_orchestrate.py

# Valuation controls (dashboard engine through the adapter):
.venv/bin/python -m scripts.valuation_adapter MU --history /tmp/controls_history.json
```

Outputs: canonical `outputs/top_sp500_valuation.json`, audit log
`logs/Mag-500-recommend.jsonl` (exactly one record per run), recovery
ledgers + intermediate artifacts in `logs/.runs/`, valuation history
in `data/valuation_history.json`.

## Layout

- `skills/mag-500-recommendation/` — copied Mag-50 skill (SKILL.md,
  orchestrator/launcher/progress/consolidator + tests), patched only
  per DEVIATIONS.md
- `skills/technical-analysis-buy-recommend/` — copied skill + the
  deterministic `technical_analysis_recommend` package (verbatim)
- `scripts/` — the new code: `valuation_adapter.py` (Phase 6 +
  parallel runner), `robinhood_transport.py` (batched Phase 4/9/10),
  `technical_adapter.py` (Phases 9–10), `delivery.py` (Phase 12),
  `build_sp500_universe.py` (Phase 2 input)
- `vendor/muse-business-evaluation-dashboard/` — pinned dashboard
  engine (V5.5 + GAV-Code; see its VENDOR.md — do not edit)
- `data/` — S&P 500 snapshot + provenance, valuation history
- `PLAN.md` / `INVENTORY.md` / `DEVIATIONS.md` / `BUILD_LOG.md` — the
  approved plan, the SHA-verified copy inventory, every intentional
  difference from the source, and the build record

Research recommendations only — this workflow never places, replaces,
cancels, or approves brokerage orders.
