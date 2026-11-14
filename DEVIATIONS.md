# Deviations from the verbatim source copy

Source: `s777data/options-wheel-agent` @ `0b0d64a7e2f90e41ffa406acac66bf42045f1c75`
(READ-ONLY). Everything not listed here is a SHA-verified verbatim copy
(see INVENTORY.md). Approved plan: PLAN.md (2026-11-14).

- **D-01 Config/paths (PRD §13.4).** Host paths
  (`/home/s777data/Mag-50-recommend`, the Hermes history path) and the
  `MAG50_*` env names become `MAG500_*` env config with repo-relative
  defaults: input `data/sp500_constituents.json`, output
  `outputs/top_sp500_valuation.json`, history `data/valuation_history.json`,
  log `logs/Mag-500-recommend.jsonl`, runs `logs/.runs/`. Run IDs are
  `MAG500-…`. Launcher `BASE` resolves the same way (legacy `MAG50_BASE`
  still honoured as a fallback). Internal module filenames stay
  `mag50_*` where copied tests/imports depend on them.
- **D-02 Phase 4 batched market data (design A, approved).** The
  per-ticker Hermes market loop is replaced by ONE batched fetch for
  the whole universe via `scripts/robinhood_transport.py`
  (`get_equity_quotes` chunks of 100, `get_equity_fundamentals` chunks
  of 20, reconciled, missing symbols retried singly then marked
  unavailable — never zero). The per-ticker progress/event/artifact
  loop in the orchestrator is unchanged. The source's
  `fetch_market_ticker*` helpers and `hermes_json` remain in the file
  verbatim for test compatibility but are NOT in the run path.
- **D-03 Phase 6 scoring (the core change).** The valuation child is
  `scripts/valuation_adapter.py` (subprocess, so timeout/process-group/
  heartbeat logic is unchanged), which calls the vendored Muse
  Business Evaluation Dashboard engine (V5.5 + GAV-Code) in-process and
  writes the history record the orchestrator verifies. The placeholder
  `company_valuation_score` tree is NOT copied. `derived_score` =
  Final = 0.5×Business + 0.25×Value + 0.25×GAV-Code (0–100 scale),
  replacing the source's 0.60/0.40 blend; null if any component is
  missing. The GAV-Code score rides in the history record's
  `business_quality.gav_code` field (and as `gav_code` on the canonical
  record) because the copied `normalize_reference` only carries the
  business/valuation dicts through. No yfinance GAV fallback (that was
  a wheel-specific approval): Mag-500 scores are EDGAR-pure.
- **D-04 Phase 6 parallel prefetch (design B, approved; deviates from
  the PRD's "no concurrent valuations" rule).** With
  `MAG500_VALUATION_WORKERS` > 1 (default 4, max 8), evaluations run on
  a ProcessPool before the sequential Phase 6 loop: per-worker vendor
  copies (own EDGAR cache dirs), a cross-process token bucket limiting
  SEC requests to ≤8/sec (SEC fair-access ceiling 10/sec), history
  records appended serially by the parent as futures complete. The
  loop's adapter children then run in verify mode
  (`MAG500_PREFETCHED`) and exit 0 on the fresh record; a prefetch
  failure gets a real sequential evaluation from its child.
  Determinism (PRD §10) is preserved: scoring is per-ticker
  independent and canonical output is assembled in input-rank order.
- **D-05 Phase 12 delivery (PRD MUSE_NOTE).** Telegram/Hermes sends
  are replaced by Muse delivery (`scripts/delivery.py`): payloads are
  written to the run delivery directory and surfaced in Muse chat;
  success only on verified write; skipped delivery
  (`MAG500_DELIVERY_DISABLED=1`) is a failure with the reason
  preserved. Error code `TELEGRAM_SEND_FAILED` → `DELIVERY_SEND_FAILED`;
  scratch/summary keys `telegram_*` → `delivery_*`; consolidate helper
  emits `delivery_notifications` (legacy `telegram_send_*` events are
  still collected for old logs).
- **D-06 Model pinning removed (PRD §13.1) + technicals as code
  (design C).** `TECH_MODEL`/`TECH_PROVIDER` and the Hermes technical
  invocation are gone. Phase 10 calls
  `scripts/technical_adapter.py`, which runs the copied
  `technical_analysis_recommend` package directly on batched Robinhood
  historicals/quotes. The engine's own deterministic
  `recommendation.summary` is used — no model-written text anywhere.
- **D-07 Terminal status (PRD §13.2).** Only `SUCCESS` / `FAILED`.
  The source's `partial_success` is reconciled: any valuation failure/
  timeout, technical failure, delivery failure, OR market-data failure
  (PRD §13.7) makes the run `FAILED`; an interrupted run finalizes as
  `FAILED`. Legacy statuses are still recognised when reading old logs
  (non-degradation check). Test change: the keyboard-interrupt test in
  `test_mag50_auto_orchestrate.py` now asserts `FAILED` (was
  `partial_success`). The consolidate tests keep `partial_success` as
  legacy fixture data (migration of old logs), unchanged.
- **D-08 `run_all_company_valuation.py` deprecated (PRD §13.3).**
  Copied, header-marked DEPRECATED (it imports a `valuation_command`
  symbol that does not exist — stale in the source too), never wired
  into the pipeline and never imported by tests.
- **D-09 Canonical output read-back (PRD §13.8).** After the atomic
  write of `outputs/top_sp500_valuation.json`, the orchestrator reads
  it back and verifies the ticker sequence; a mismatch raises
  `OUTPUT_WRITE_FAILED`. The output-write event records
  `readback_verified: true`.
- **D-11 History bootstrap.** A *missing* valuation-history file loads
  as an empty history (the first-ever Mag-500 run has none; the
  adapter creates it on first success). A present but malformed file
  still raises `REFERENCE_FILE_UNAVAILABLE` (fail-closed, PRD §9.1).
  Found by smoke run B (fresh base) — smoke A had a seeded history.
- **D-10 Copied SKILL.md headers.** The two copied SKILL.md files carry
  an HTML-comment header noting provenance and that PLAN.md/this file
  govern where they conflict. The technical package's own files are
  byte-identical to the source (no header added — they are code).
- **D-12 DCF-missing target rule relaxed (approved by BIG SANDY,
  2026-11-14).** The copied history validation required
  `target_prices` to contain at least one numeric target. The
  dashboard engine deliberately produces NO DCF for names whose FCF
  base cannot anchor one (`fcf_base_missing` /
  `non_positive_fcf_base` / beta missing) while still scoring
  Business/Value/GAV fully — e.g. LLY (Biz 46.2 / Val 12.1 / GAV
  46.0) — so such names failed closed in the adapter and, with no
  prior, a first full run hard-failed at output rebuild (PRD §7
  rule 4). Scope: ONLY fully-scored names (numeric Business, Value
  and GAV-Code) that are DCF-missing. The valuation adapter now
  writes their history record with `target_prices` =
  `{dcf_fair_value: null, dcf_missing_reason: <engine reason>, ...}`
  (same keys as the DCF-present case, null values, plus the reason;
  a numeric stress floor is still recorded when the engine produces
  one). Orchestrator validation — `reference_validation_error` and
  `valid_reference`, via the `_dcf_missing_target_ok` helper —
  accepts a non-empty `target_prices` with no numeric target ONLY
  when it carries a non-empty `dcf_missing_reason` AND an explicitly
  null `dcf_fair_value`. All other validity requirements unchanged:
  missing Business/Value scores still fail closed with NO history
  record (BRK.B behaviour unchanged), and a `target_prices` with
  neither a numeric target nor a recorded reason still returns
  `TARGET_PRICES_INVALID`. The Final/derived score is unaffected —
  it never uses the DCF target (the Value leg's DCF sub-score is
  already renormalised inside the engine).
- **D-13 Resumable valuation reuse (2026-11-14).** Motivation: two
  full 503-ticker run attempts died on 2026-11-14 — attempt 1 on the
  /tmp disk-full (fixed operationally by pointing
  `MAG500_WORKER_VENDOR_ROOT` at disk), attempt 2 killed by an
  external shutdown ~25 min in. The orchestrator set
  `MAG500_PREFETCH_CUTOFF` to the run's own start time, so only
  records written during the current run counted as fresh and every
  attempt re-evaluated all 503 tickers cold. D-13 adds an opt-in
  reuse window, `MAG500_PREFETCH_REUSE_HOURS` (float hours;
  unset/empty/0/invalid/negative = OFF, and with it off behaviour is
  exactly pre-D-13 everywhere). The window aligns with the vendored
  engine's own 12h EDGAR cache TTL (`cache_hours=12`).
  - *Adapter* (`prefetch_valuations`): with reuse on, each ticker's
    latest history record completed at/after now − window is reused
    — reported as success with `reused: True` and the existing
    record's run_id — instead of evaluated, but ONLY when the record
    passes `_entry_reuse_error`, a mirror of the orchestrator's
    `reference_validation_error` (same checks, same reason strings:
    run_id present, status/outcome/audit completion proof,
    failed-verification markers `persisted.*_verified is False`
    rejected, finite Business/Value scores, `target_prices` numeric
    or the D-12 shape). The mirror is a pre-filter; the orchestrator
    remains the authoritative validator and re-validates everything
    it loads. Fail-closed names (BRK.B class) write no record, so
    there is nothing to reuse and they are evaluated normally; a
    latest in-window record that is invalid is likewise evaluated
    (fail-safe direction), never reused.
  - *Orchestrator*: with reuse on, `MAG500_PREFETCH_CUTOFF` becomes
    now − window (`_prefetch_cutoff` helper) so the Phase 6
    verify-mode children accept the pre-seeded records as fresh.
  - *Validation adjustment (the one semantic change)*:
    `classify_refresh_result` required `verified_ref.run_id !=
    pre_run_id` — proof the child produced a NEW record. A reused
    record IS the pre-run record by construction, so every reused
    ticker would have classified `VALUATION_REFERENCE_NOT_UPDATED`
    and failed the whole run under D-07 even though reuse worked.
    The function gains an optional `reuse_cutoff` parameter (None
    unless reuse is on and the prefetch ran): only when it is set,
    the child exited 0, and the verified run_id EQUALS the pre-run
    run_id, the new-record proof is replaced by a freshness proof —
    the record's completion timestamp must be at/after the same
    cutoff the child verified against. Nothing else is weakened:
    `valid_reference` (numeric scores, `target_prices` incl. the
    D-12 shape, run_id present) is still enforced, timed-out or
    failed children still fail, a stale same-id record still fails,
    and with reuse off the new branch never fires.
  - *Chunk driver* (`scripts/run_prefetch_chunks.py`): splits the
    universe into chunks (default 100; a trailing remainder folds
    into the last chunk — 503 → [100, 100, 100, 100, 103]) and runs
    `prefetch_valuations` per chunk against
    `data/valuation_history.json`, defaulting
    `MAG500_PREFETCH_REUSE_HOURS=12` when unset (an explicit env
    value, including "0", is honoured). Re-running it is safe:
    already-fresh tickers skip via the same reuse check, so an
    interrupted chunk costs only its unfinished tickers.
- **D-14 Structured unscored rows in output rebuild (2026-11-14).**
  Motivation: the first chunked full run scored 495/503, then died at
  `output_rebuild` — `RuntimeError: No valid record available for
  BRK.B` — because the rebuild raised on the first ticker with no
  valid history record and no prior output record, discarding all 495
  scored rows, the technical phase, and the Top 2. Approved by
  BIG SANDY 2026-11-14 ("Yes, build D-14 and finish the run").
  - *Rule*: in the rebuild loop's no-reference/no-prior-record branch,
    when this run's refresh for the ticker ran and failed terminally
    (`d14_unscored_eligible`: refresh exists, not success, error_code
    is not `VALUATION_REFRESH_TIMEOUT`), the rebuild emits a
    structured unscored row via `build_unscored_record` — the
    `build_record` schema with every score null (Business/Value/GAV/
    derived), `target_prices`/`run_id`/`valuation_last_run_at` null,
    market fields from this run's market data, `unscored: true`, and
    `unscored_reason` = the refresh's error message or code. An
    `output_unscored_row` event is recorded per row. This is the D-17
    pattern from the options wheel (terminal fail-closed verdict →
    structured unscored row, reason preserved).
  - *Still fail-closed*: a timed-out refresh (transient, not a
    verdict), a missing refresh entry, or any invalid scored record
    keeps the original raise / validation behaviour. Scored records
    are untouched — strict reference validation (incl. the D-12
    target shape) still applies, and Final stays null when any
    component is missing.
  - *Never ranked*: unscored rows carry `derived_score: null`; Top-10
    selection already requires a numeric derived score, so unscored
    names cannot enter technicals or the Top 2.
  - *Status unchanged*: D-07 still marks the run FAILED when any
    refresh failed — D-14 changes what the run PRODUCES (full output,
    technicals, Top 2), not how it is labelled.
  - *Tests*: `tests/test_mag50_d14_unscored_rows.py` (8 tests:
    eligibility gate incl. timeout/missing/success exclusions,
    unscored schema + null scores, market fields preserved, never
    ranked, passes output-row validation). Mag suite 53 → 61.
