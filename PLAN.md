# Mag-500 Recommendation — Implementation Plan (approved 2026-11-14)

Source PRD: `MAG500_RECOMMENDATION_PRD.md` (Phases 0–14), from READ-ONLY
`s777data/options-wheel-agent` @ `0b0d64a7e2f90e41ffa406acac66bf42045f1c75`.
Target repo: `s777data/Muse-Top-500-Recommend` (created by BIG SANDY
2026-11-14, verified empty/public). Local working copy:
`~/workspace/muse-top-500-recommend/` (not a git checkout; pushes go
through the GitHub connector snapshot route with read-back verification,
same as the wheel repo).

## Principle

Copy-by-phase, SHA-verified, code-only. A pipeline run must burn ~0 model
tokens: no Hermes CLI, no model-backed skill invocation anywhere in the
run path. The genuinely new code is three adapters (scoring, transport,
delivery) plus the S&P 500 universe builder. Everything else is a verbatim
copy with deviations logged in `DEVIATIONS.md`.

## Approved design updates (BIG SANDY, 2026-11-14)

### A. Robinhood is batched, never per-ticker (Phase 4, 9, 10)
Verified live 2026-11-14 against the Robinhood Trading MCP tool schemas
and with real calls:
- `get_equity_quotes`: 20 symbols/call with closes; 100+/call price-only
  (107 requested → 102 returned in 1.9s; closes omitted above 20 — Phase 4
  needs only price + venue timestamp).
- `get_equity_fundamentals` (market cap): hard max 20/call (20 in 1.9s).
- `get_equity_historicals`: max 10/call. `get_equity_technical_indicators`:
  max 10/call ("pass every symbol in one call").
- Phase 4 total for ~503 tickers: ~31 calls, ~1 minute — vs 1,006 calls
  and ~1,006 MCP session handshakes in the PRD's per-ticker design.
- Every batch is reconciled: requested vs returned diffed, missing symbols
  retried singly, then marked unavailable (never zero). Batch calls run
  with bounded concurrency (max 4 in flight), retries with backoff,
  fail-closed on 429/lock responses.
- All four tools are already in the local Robinhood client allowlist;
  no allowlist change needed.

### B. Valuation runs in a bounded process pool (Phase 6)
Measured 2026-11-14: one dashboard `evaluate()` (MU) = 24.3s wall, ~3s
CPU — ~88% network wait (EDGAR / Yahoo / Stooq). Sequential ×500 ≈ 3.3h.
- `ProcessPoolExecutor`, `MAG500_VALUATION_WORKERS` default 4, max 8.
- Shared SEC rate limiter: ≤8 requests/sec across workers (SEC fair
  access ceiling is 10/sec).
- Per-worker EDGAR cache directories (no shared-cache write races).
- Results are assembled into the ledger and canonical output in
  input-rank order; per-ticker verification (new run ID in valuation
  history) and fail-closed fallback to prior valid records are unchanged.
- This deviates from the PRD's "no concurrent valuations" rule and is
  logged as a deviation; determinism (§10) is preserved because scoring
  is per-ticker independent and final ordering is by rank/derived score.
- Estimated full run on this VM (1.5 CPU / 6GB): ~45–75 min cold.

### C. Technical-recommend runs as direct code (Phases 9–11)
The source package `technical_analysis_recommend` (engine.py 16KB,
scoring.py 14.8KB, indicators.py, aggregation.py, models.py, cli.py,
plus tests) is deterministic Python on OHLCV data — its `__init__` says
so. Only the Hermes SKILL.md wrapper is model-driven. We copy the package
verbatim and invoke `cli.py` directly, fed by batched Robinhood
historicals/indicators for the Top 10 (a handful of calls, <1 min).
Any model-written summary becomes a deterministic template from the
engine's own fields (logged deviation).

## Phase mapping (PRD 0–14)

- 0 Launcher: copy `mag50_launcher.py` + tests; config via env.
- 1–3 Orchestrator init/input/prior-state: copy `mag50_auto_orchestrate.py`
  sections verbatim except config/paths/run-id (`MAG500-…`).
- 4 Market data: orchestrator logic copied, transport replaced with
  batched Robinhood (design A).
- 5 Valuation plan: verbatim.
- 6 Valuation: child command replaced — adapter subprocess calls the
  vendored dashboard engine in-process and writes a history record in the
  schema the orchestrator verifies. The placeholder
  `company_valuation_score` tree is NOT copied.
  `derived_score` = Final = 0.5×Business×10 + 0.25×Value×10 +
  0.25×GAV-Code; null if Business/Value missing (never zero-filled at
  the orchestrator level; the engine's own V5.4 missing-leg policy
  applies inside the engine).
- 7 Canonical output: verbatim + read-back verification (PRD §13.8);
  path `outputs/top_sp500_valuation.json`.
- 8 Top 10 by derived score: verbatim.
- 9–11 Technicals + Top 2: design C; verdict set and sort order verbatim.
- 12 Delivery: Telegram/Hermes replaced with Muse delivery — payloads
  written to run artifacts and surfaced in Muse chat; structured
  success/skipped/failed accounting preserved (codes renamed from
  `TELEGRAM_*` to delivery equivalents, logged).
- 13 Audit log: verbatim upsert semantics; path
  `logs/Mag-500-recommend.jsonl`; terminal status `SUCCESS`/`FAILED`
  only (PRD §13.2, source `partial_success` reconciled, tests updated).
- 14 Operator summary: verbatim fields.

## Vendored dashboard engine

Fresh byte copy of `src/evaluator/` + `config/` from the LOCAL
`~/workspace/muse-business-evaluation-dashboard` working copy (engine
V5.5 + GAV-Code, V5.4 missing-leg policy) into
`vendor/muse-business-evaluation-dashboard/`, never edited, with
`VENDOR.md` recording per-file hashes. Controls are re-baselined on V5.5
before adapter sign-off (V5.3 wheel controls do not carry over; e.g. MU
now Biz 66.8 / Val 63.4 / GAV 79.2 / Final 69.0, measured 2026-11-14).

## S&P 500 universe (Phase 2 input)

`scripts/build_sp500_universe.py`: Wikipedia "List of S&P 500 companies"
table as primary source (ticker, name, GICS sector; updated within days
of index changes), cross-checked against the S&P Dow Jones official
constituents file when reachable. Committed snapshot
`data/sp500_constituents.json` in the PRD envelope + provenance file.
Rank = market-cap descending at snapshot time (via batched Robinhood
fundamentals); tickers keep dot form (BRK.B, BF.B); ~503 rows expected
(dual share classes); duplicates fail validation.

## Other reconciliations (PRD §13)

Host paths and the pinned model/provider become `MAG500_*` env config
with repo-relative defaults. `run_all_company_valuation.py` is copied,
marked deprecated, never the operator path. Internal module names stay
`mag50_*` where copied tests/imports depend on them; product branding,
run IDs, and output paths are Mag-500.

## Build sequence

0. Inventory: fetch every needed source file at 0b0d64a via the GitHub
   connector (`call-tool get_file_contents`; content arrives in the
   result's resource text), verify each by recomputing its git blob
   SHA-1, record in `INVENTORY.md`. Excluded: the
   `company_valuation_score` tree (listed as excluded).
1. Scaffold: README, requirements, .gitignore, DEVIATIONS, BUILD_LOG.
2. Copy launcher/progress/consolidator + their tests; run tests.
3. Copy orchestrator; patch only logged deviations.
4. Vendor dashboard engine; write valuation adapter + parallel runner;
   re-baselined controls pass.
5. Batched Robinhood transport.
6. Universe builder + snapshot.
7. Technical package copy + direct-code adapter.
8. `.venv` + pip install; full test suite green.
9. Smoke runs: 3 tickers (incl. BRK.B fail-closed case), then 10.
10. Push via GitHub snapshot route; read-back verify head.
11. Rename Space "Top 50 Score Comparison Heatmap" → "Top 500 Score
    Comparison Heatmap" (display only; slug kept) via the Space builder.
    Populating 500 rows waits for the first full Mag-500 run; new rows
    will be code-only columns (no Gemini/OpenAI data exists for them).
