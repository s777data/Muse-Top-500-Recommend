# Build log — Muse-Top-500-Recommend (Mag-500)

## 2026-11-14 — build session (steps 0–9 of PLAN.md)

- Read PLAN.md (approved, incl. designs A/B/C) + PRD phases 0–14.
- STEP 0 INVENTORY: directory listings for all needed source paths at
  0b0d64a recorded; 22 files fetched via GitHub connector call-tool and
  verified by git blob SHA-1 — **22/22 OK** (one transient MCP 503 on
  test_mag50_progress_report.py, retried OK). company_valuation_score
  tree listed as EXCLUDED. See INVENTORY.md.
- STEP 1 SCAFFOLD: README, requirements.txt (pyyaml + pytest — every
  copied/vendored module is otherwise stdlib-only, verified by import
  scan), .gitignore, DEVIATIONS.md (D-01…D-10), this log.
- Vendor: byte copy of dashboard src/evaluator + config (19 files,
  SHA-256 table in vendor VENDOR.md); diff vs source working copy
  verified identical (excluding __pycache__/output).
- .venv created; pyyaml 6.0.3 + pytest 9.2.0 (+ requests/httpx, unused
  by the pipeline) installed cleanly.

(controls, tests, universe, smoke results appended below as they run)

## Results (appended at end of build, 2026-11-14)

### Controls on the vendored V5.5 engine (via the adapter)
| Ticker | Biz | Val | GAV | Final | Note |
|---|---|---|---|---|---|
| MU | 66.8 | 63.4 | 79.2 | 69.05 | matches wheel measurement (69.0 = 1-dp rounding there; adapter keeps PRD §6.3 precision) |
| NVDA | 88.4 | 28.5 | 61.8 | 66.775 | |
| V | 60.0 | 19.9 | 35.0 | 43.725 | CIK injected from EDGAR tickers file |
| BRK.B | — | — | — | fail closed | `value_score_missing`, exit 1, NO history record ✓ |

History entries validated through the orchestrator's own
`load_reference_entries`/`valid_reference`.

### Universe snapshot
`data/sp500_constituents.json` built 2026-11-14T19:29:03Z: **503
companies**, market-cap-desc (top: AAPL, NVDA, MSFT, GOOGL, GOOG), no
missing market caps; builder wall ~14 s. Provenance:
`data/sp500_provenance.json` — Wikipedia primary OK; S&P DJI export
unreachable/unparseable at build time (recorded honestly).

### Tests (.venv: pyyaml 6.0.3, pytest 9.2.0; everything else stdlib)
- Mag-500 copied+adapted suite: **30 passed** (1 test updated, D-07).
- Technical package suite: **13 passed**. `compileall` clean.
- Vendor re-verified byte-identical (`diff -r`) at end of build.

### Smoke A — 3 tickers [AAPL, BRK.B, MU], BRK.B prior seeded
Run `MAG500-20261114T193338Z-dd1f55`, wall ≈ 131 s. AAPL/MU refreshed
(Final 52.275 / 69.05; prices $356.40 / $778.40 = Fri closes); BRK.B
failed-closed after 3 attempts, seeded prior preserved (derived
recomputed 59.75 under the new formula). Technicals 3/3 (AAPL 87 BUY,
BRK.B 77 CONDITIONAL_BUY, MU 43 WAIT); Top 2 = AAPL, BRK.B.
Deliveries 3/3; audit JSONL exactly 1 record; status FAILED (correct:
BRK.B refresh failed, PRD §13.7). Artifacts: `outputs/smoke_a/`.

### Smoke B — 10 tickers (universe top 10), LLY prior seeded
Run `MAG500-20261114T193954Z-2862f7`, wall ≈ 154 s. 9/10 refreshed in
one parallel prefetch (10 evaluations ≈ 52 s wall in the first
attempt's audit trail). Top 10 by Final: NVDA 66.775, META 60.325,
MSFT 56.775, GOOG 56.225, GOOGL 56.075, AVGO 54.675, AAPL 52.275,
AMZN 38.1, LLY 37.625 (prior), TSLA 35.475. Technicals 10/10; Top 2 =
AAPL (87 BUY), MSFT (84 CONDITIONAL_BUY). Deliveries 10/10; audit
exactly 1 record; status FAILED (LLY). Artifacts: `outputs/smoke_b/`.
First B attempt without an LLY prior failed at output rebuild with
`No valid record available for LLY` (PRD §7 fail-don't-fabricate) and
exposed the D-11 history-bootstrap fix.

### Bugs found and fixed during the build
1. Transport rate-limit substring false positive on fundamentals text
   → RateLimitStop only from error responses.
2. Orchestrator could not import `scripts.*` when launched by path →
   REPO_ROOT sys.path insertion (the failed run still wrote exactly
   one FAILED audit record — finalization verified).
3. `build_record` read GAV from the trimmed record dict (always None)
   → notification crash on derived=None; now from the reference.
4. Quote results nest symbol in `quote.symbol` → batch keying missed
   all quotes (prices None; technical quote fetch failed). Fixed in
   `_batched`.
5. D-11 history bootstrap (missing file = empty history).
6. One transient environment kill of a smoke-B attempt (~8 s in,
   during prefetch, no traceback) did not recur after clearing
   509 MB of stale per-worker vendor copies in /tmp; prefetch now
   cleans up its own worker copies after each run.

### ⚠ Open design tension for the parent (not a build defect)
**LLY-class names block first runs.** The engine scores LLY fully
(Biz 46.2 / Val 12.1 / GAV 46.0) but produces **no DCF at all**
(`fcf_base_missing` — no fair value, no stress floor). The copied
history schema requires a numeric target in `target_prices`, so the
adapter fails LLY closed; with no prior, the workflow fails at output
rebuild (PRD §7 rule 4). On the first full 503 run, every
DCF-missing name behaves this way until (a) priors are seeded by a
bootstrap, (b) BIG SANDY approves relaxing the target rule (schema
change to copied validation), or (c) engine DCF coverage improves.
Smokes used labelled fixture priors carrying the real engine scores
with a fixture target, to exercise the preservation path. Decision
needed before the step-10 full run.

### Not done (out of scope, steps 10–11 are the parent's)
No GitHub push. No Space/heatmap changes. No full 503 run.

## 2026-11-14 — D-12 applied: DCF-missing target rule relaxed

Decision (BIG SANDY, 2026-11-14): relax the target_prices rule for
DCF-missing-but-fully-scored names — see DEVIATIONS.md D-12. This
resolves the open design tension flagged at the end of the build
session: a first full 503 run is no longer blocked by LLY-class
names.

### Changes
- `scripts/valuation_adapter.py`: a missing DCF fair value alone no
  longer fails closed. The record is written with
  `target_prices.dcf_fair_value = null` plus
  `dcf_missing_reason` from the engine
  (`data_quality.dcf_missing_reason`, falling back to the DCF
  block's `stress_floor_missing_reason`, then `dcf_target_missing`);
  a numeric stress floor and `price_at_valuation` are recorded as
  before. Missing Business/Value/GAV-Code still produces NO record.
  Module docstring updated (fail-closed list + D-12 note).
- `skills/mag-500-recommendation/scripts/mag50_auto_orchestrate.py`:
  new `_dcf_missing_target_ok` helper; `reference_validation_error`
  and `valid_reference` accept the D-12 shape (non-empty
  target_prices, non-empty `dcf_missing_reason`, explicitly null
  `dcf_fair_value`) in place of a numeric target. No other
  validation behaviour changed.
- Tests: new `skills/mag-500-recommendation/tests/test_mag50_d12_target_rule.py`
  (7 tests): D-12 reference validates and builds a canonical record
  with Final computed from scores (37.625 for the LLY fixture);
  D-12 reference is selectable as the output reference; six
  no-target/no-reason target_prices shapes still return
  `TARGET_PRICES_INVALID` (and `{}` still `TARGET_PRICES_MISSING`);
  numeric-target references still validate; missing Value/Business
  scores still invalid; adapter (stubbed engine) writes the D-12
  record for a DCF-missing fully-scored name and writes NO record
  for a BRK.B-class missing-Value name.

### Verification
- Mag suite: **30 → 37 passed**. Technical suite: **13 passed**
  (run from `skills/technical-analysis-buy-recommend/code`).
  `compileall` clean. Vendor tree untouched (`vendor/**` unmodified).
- Live adapter, LLY standalone (fresh history file): exit 0, record
  `MAG500VAL-20261114T200527Z-c64026` written — Biz 46.2 / Val 12.1 /
  GAV 46.0 / Final 37.625, exactly the smoke-B engine numbers;
  `target_prices = {dcf_fair_value: null, dcf_missing_reason:
  "fcf_base_missing", price_at_valuation: 1443.5}` (the engine's own
  price feed; scores are price-independent here).
- Smoke C (rehearsal — weekend, Fri 2026-11-13 Robinhood closes;
  artifacts `outputs/smoke_c/`): FRESH base with NO history file
  and NO seeded/fixture prior for LLY. Universe [AAPL, MSFT, MU,
  LLY]; run `MAG500-20261114T200546Z-89dd1b`, wall ≈ 46.5 s.
  Valuations **4/4 succeeded, including LLY**; canonical output
  contains LLY with Final 37.625 and the null-DCF target object;
  technicals 4/4; Top 2 = AAPL (87 BUY), MSFT (84
  CONDITIONAL_BUY); deliveries 5 sent / 0 failed; **exactly 1
  audit record**; terminal status **SUCCESS** (every stage
  succeeded — correct under D-07).
