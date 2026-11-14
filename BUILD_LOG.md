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

## 2026-11-14 — D-13 applied: resumable valuation reuse

Motivation (see DEVIATIONS.md D-13): two full-run attempts died on
2026-11-14 (attempt 1: /tmp disk-full, fixed operationally; attempt
2: external shutdown ~25 min in) and the run-start freshness cutoff
forced every attempt to re-evaluate all 503 tickers cold. D-13 makes
valuation work resumable across attempts inside a 12h window (the
vendored engine's own EDGAR cache TTL), controlled by
`MAG500_PREFETCH_REUSE_HOURS` (unset/0 = off, pre-D-13 behaviour
exactly).

### Changes
- `scripts/valuation_adapter.py`: `prefetch_valuations` partitions
  tickers via `_split_reusable` when reuse is on — a ticker whose
  latest in-window history record passes `_entry_reuse_error` (a
  mirror of the orchestrator's `reference_validation_error`, incl.
  failed-verification markers and the D-12 target shape) is reported
  `{success: True, reused: True, run_id: <existing>}` and NOT
  evaluated; invalid or stale records and record-less fail-closed
  names are evaluated normally.
- `skills/mag-500-recommendation/scripts/mag50_auto_orchestrate.py`:
  `_prefetch_reuse_hours` / `_prefetch_cutoff` helpers; with reuse
  on, `MAG500_PREFETCH_CUTOFF` = now − window instead of now.
  Validation adjustment (required, minimal): `classify_refresh_result`
  demanded a NEW record (`run_id != pre_run_id`), which a reused
  record can never satisfy — every reused ticker would have failed
  as `VALUATION_REFERENCE_NOT_UPDATED`. It gains an optional
  `reuse_cutoff`: only when set, child exit 0, and the verified
  run_id equals the pre-run run_id, the new-record proof is replaced
  by a freshness proof (completion timestamp ≥ the cutoff the child
  verified against). `valid_reference` and all other checks are
  unchanged; with reuse off the branch never fires.
- `scripts/run_prefetch_chunks.py` (new): chunked prefetch driver —
  universe → chunks (default 100, trailing remainder folded into the
  last chunk: 503 → [100, 100, 100, 100, 103]), per-chunk timing and
  succeeded/failed/reused counts, `--tickers` / `--offset` /
  `--limit` overrides, defaults `MAG500_PREFETCH_REUSE_HOURS=12`
  when unset. Re-running is safe (fresh tickers skip).

### Verification
- Mag suite: **37 → 53 passed** (16 new tests in
  `test_mag50_d13_reuse.py`: prefetch reuses fresh valid + fresh
  D-12 records; stale record evaluated; reuse off/0 evaluates;
  fresh-but-invalid and failed-verification-marker records
  evaluated; orchestrator cutoff with/without env; classify
  same-run-id rejected without reuse, accepted with an in-window
  cutoff, rejected with a post-completion cutoff, failed child not
  rescued, new-record path unchanged; chunk split of 503 →
  [100, 100, 100, 100, 103] + edge cases). Technical suite:
  **13 passed**. `compileall` clean. Vendor tree untouched.
- Live proof (rehearsal, /tmp scratch base, Fri 2026-11-13 closes):
  - Stage 1 — seed with reuse OFF, `prefetch_valuations` on
    [AAPL, LLY, BRK.B], wall **38.7 s**: AAPL record
    `MAG500VAL-20261114T224137Z-fa5f92`, LLY record
    `MAG500VAL-20261114T224137Z-b3cd9d` written; BRK.B fail-closed
    (`value_score_missing`), NO record. History = 2 records.
  - Stage 2 — orchestrator end-to-end on the scratch base (input
    [AAPL, LLY, BRK.B], BRK.B prior-output fixture only) with
    `MAG500_PREFETCH_REUSE_HOURS=12` and the worker vendor root on
    disk under the scratch dir, wall **107.9 s** (run
    `MAG500-20261114T224145Z-b0117a`; most of the wall is BRK.B's
    three real attempts with 30 s/60 s backoff). Evidence of reuse,
    not re-evaluation: prefetch reported AAPL/LLY success with the
    STAGE-1 run_ids; the Phase 6 children printed
    `{"prefetched": true, "run_id": <stage-1 id>}` and exited in
    0.14 s / 0.17 s (vs ~19 s per real evaluation in stage 1);
    refresh classification AAPL/LLY success with pre_run_id ==
    new_run_id == stage-1 id (the D-13 classify path); history
    still exactly 2 records afterwards (nothing re-appended);
    canonical output carries the stage-1 run_ids (AAPL Final
    52.275, LLY Final 37.625) and the labelled fixture prior for
    BRK.B. BRK.B was evaluated fresh in both prefetch and Phase 6
    and failed closed (`value_score_missing`, 3 attempts) as
    before. **Exactly 1 audit record; terminal status FAILED** —
    attributable solely to the BRK.B refresh failure, as designed.
- No GitHub push, no Space changes, no full 503 run (per tasking).

## 2026-11-14 — D-14 applied: unscored rows in output rebuild

- Chunked full run MAG500-20261114T224829Z-3c5090 (Stage A pre-seed
  189.2 s: 495 succeeded / 445 reused / 50 fresh; Stage B 17 m 53 s)
  FAILED at `output_rebuild` on BRK.B despite 495/503 scored —
  motivation for D-14 (see DEVIATIONS.md). Exactly 1 audit record;
  no output file written; technicals never ran.
- Fix in `skills/mag-500-recommendation/scripts/mag50_auto_orchestrate.py`:
  new `d14_unscored_eligible()` gate + `build_unscored_record()`
  helper; the rebuild's raise branch now emits an unscored row for
  terminal refresh failures (timeouts and missing refreshes still
  raise). Vendor tree untouched (19/19 SHA-256 re-verified).
- Tests: mag suite 53 → 61 passed (8 new D-14 tests), technical
  suite 13 passed, compileall clean.
