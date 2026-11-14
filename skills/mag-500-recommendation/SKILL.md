<!-- COPIED SOURCE SKILL (s777data/options-wheel-agent @0b0d64a, skills/mag-50-recommendation/SKILL.md, git blob c29b8138cbe16d70458459dbce668ac8b8ce1b64, SHA-verified 2026-11-14). This is the Mag-50 source skill kept for reference. Where it conflicts with PLAN.md / DEVIATIONS.md in this repo (Mag-500 branding, dashboard-engine scoring, batched Robinhood, Muse delivery), PLAN.md and DEVIATIONS.md govern. -->

---
name: mag-50-recommendation
description: >
  Deterministic, resumable, and auditable S&P 500 valuation and technical-analysis
  recommendation workflow. Reconciles the ranked input universe with existing
  company-valuation-score history, refreshes missing/stale/low-confidence valuations,
  updates the canonical valuation output, ranks companies using a 60/40 derived score,
  runs technical-analysis-buy-recommend on the top 10, sends valuation and final
  recommendation notifications to the configured Telegram bot, and stores exactly one
  consolidated JSONL record per workflow run ID.
---

# Mag-50 Recommendation

## Purpose

Build and maintain:

```text
/home/s777data/Mag-50-recommend/outputs/top_50_sp500_valuation.json
```

from the ranked S&P 500 input universe and the latest successful
`company-valuation-score` results, then identify the strongest candidates using:

```text
derived_score = (0.60 * business_quality.score) + (0.40 * valuation.score)
```

Run technical analysis on the top 10 derived-score candidates and send the final top 2
recommendations to the configured Telegram bot.

The workflow MUST be deterministic, resumable, idempotent, and auditable.

---

## Original Request — Preserve Verbatim

The following original request is retained verbatim for provenance. It is fenced as
literal text so the original `-->` annotation arrows do not accidentally terminate the
HTML comment early. The wording itself is unchanged; trailing whitespace is normalized. It is **not** the normative execution
contract. If it is ambiguous or conflicts with the normalized rules below, the normalized
rules below take precedence.

```text
<!--
full run
input file prompt
"create a .json file in format beloe for top 100 companies in S&P 500 .. make sure current price, date are added with all the details
example,
"            "rank": 1,
            "ticker": "NVDA",
            "name": "NVIDIA Corp",
            "sector": "Information Technology",
            "market_cap": "5.23T",
            "current_price": 217.08
        }"

INPUT:
- 📁 /home/s777data/Mag-50-recommend/
  - 📁 inputs/
    - 📄 top_50_sp500.json
OUTPUT:
- 📁 /home/s777data/Mag-50-recommend/
  - 📁 outputs/
    - 📄 top_50_sp500_valuation.json
/home/s777data/Mag-50-recommend/outputs/top_50_sp500_valuation.json
for output file look for "rank" for ticker. look for the last rank in the output file . if rank is missing look for the latest rank from inputs.  Market Capitalization keep it in "T" and "B"

for the missing rank from input ticker

look for the ticker with "outcome":"complete" in the reference file.

reference file
outputs/robinhood-wheel-agent/company-valuation-score/valuation_history.json

if entry exists
append to output file  in the following .json format
example
            "rank": 1,
            "ticker": "NVDA",
            "name": "NVIDIA Corp",
            "sector": "Information Technology",
            "market_cap": "", --> current market_cap
            "current_price": , --> current price
            --> below from reference file
            "business_quality":{"score": ,"grade":,"confidence":,}
            "valuation":{"score":,"grade":,"confidence":}
            "target_prices": {
        "A+": 148.64725879776387,
        "A": 171.44280382539412,
        "A-": 197.67329399417412,
        "price_at_valuation": 320.08224811514737
      }
        "run_id": "20260829T195640-NVDA-acf76a",

if entry does not exist
or
any of the tickers have "confidence" at low and medium

run

company-valuation-score $ticker  /model gpt-5.6-luna --provider openai-codex

make sure the above skill runs successfully


once the skill runs succesfully
write output json file in the above format using reference file.

for every successful
company-valuation-score run send a message notification to this telegram bot


from output file,
pick top 10 for derived_score 60%(business score) +40%(valuation score)

out of top 10 above run technical-analysis-buy-recommend skill in options-wheel-agent profile and share me most buy recommendations



from
#source
/home/s777data/Mag-50-recommend/outputs/top_50_sp500_valuation.json

for every ticker, run company-valuation-score sequentially and verify the completed
valuation history entry before replacing the ticker's output record.

make sure each skill run succeeds

once the skill runs successfully, write output JSON using the latest completed valuation
history entry.
example,
            "rank": 1,
            "ticker": "NVDA",
            "name": "NVIDIA Corp",
            "sector": "Information Technology",
            "market_cap": "", --> current market_cap
            "current_price": , --> current price
            --> below from reference file
            "business_quality":{"score": ,"grade":,"confidence":,}
            "valuation":{"score":,"grade":,"confidence":}
            "target_prices": {
        "A+": 148.64725879776387,
        "A": 171.44280382539412,
        "A-": 197.67329399417412,
        "price_at_valuation": 320.08224811514737
      }
        "run_id": "20260829T195640-NVDA-acf76a",

make sure the ticker in Source file is replaced with the latest run_id and details

from output file,
pick top 10 for derived_score 60%(business score) +40%(valuation score)

out of top 10 above run technical-analysis-buy-recommend skill in options-wheel-agent profile and share me most buy recommendations using Robinhood MCP

out the above share the out of top 2 as recommendations with
Ticker,"score","verdict","summary","v_derived_score" (derived_score) in a human readable message format to telegram bot configured .

create log file that appends daily run in

/home/s777data/Mag-50-recommend/logs/ Mag-50-recommend.jsonl
make sure to add other necessary logging fields .
-->
```

---

## Canonical Paths

### Input universe

```text
/home/s777data/Mag-50-recommend/inputs/top_50_sp500.json
```

### Canonical output

```text
/home/s777data/Mag-50-recommend/outputs/top_50_sp500_valuation.json
```

### Valuation references

```text
/home/s777data/outputs/robinhood-wheel-agent/company-valuation-score/valuation_history.json
```

If an older relative path such as:

```text
outputs/robinhood-wheel-agent/company-valuation-score/valuation_history.json
```

appears anywhere, resolve it to the canonical absolute path above.

### Workflow log

```text
/home/s777data/Mag-50-recommend/logs/Mag-50-recommend.jsonl
```

Create parent directories when missing.

### Canonical runtime code

The executable implementation is the runtime source of truth for orchestration behavior:

```text
skills/mag-50-recommendation/scripts/mag50_auto_orchestrate.py
```

Launch long runs through the durable code launcher, not as a terminal/session-owned background
child:

```bash
python3 skills/mag-50-recommendation/scripts/mag50_launcher.py start
python3 skills/mag-50-recommendation/scripts/mag50_launcher.py status
python3 skills/mag-50-recommendation/scripts/mag50_progress_report.py
```

The launcher starts the orchestrator in a new OS session, detaches stdin, uses unbuffered
Python output, records the PID, and rejects a duplicate live launch. Direct execution is
reserved for foreground debugging and tests. The workflow contract in this file must not
be used as a substitute for missing process-control, timeout, heartbeat, or checkpoint code.

Every external market-data or valuation wait must be bounded in code and must atomically
refresh `progress.last_heartbeat_at`. Market-data progress is first-class: before the first
lookup and for every ticker, persist `phase: market_data`, `current_ticker`, rank, 1-based
index/total, child PID/state, completed/failed/in-flight counts, and timeout. A ledger that
remains at `initialization` while market requests are active is an implementation defect,
not an acceptable progress state.

---

## Required Capabilities

The workflow requires access to:

1. `company-valuation-score`
2. `technical-analysis-buy-recommend`
3. the `options-wheel-agent` profile
4. Robinhood MCP for current market data and technical-analysis context
5. the configured Telegram bot
6. local read/write access to all canonical paths

Do not silently substitute a different skill, profile, market-data source, or Telegram destination.
The valuation model and provider are inherited from the active Hermes runtime defaults and are
not pinned by this workflow.

---

## Non-Negotiable Invariants

1. **Input rank is authoritative.**
   - Never invent, renumber, compress, or reorder ranks.
   - Output records MUST retain the exact rank associated with the ticker in the input.

2. **One output record per ticker and rank.**
   - No duplicate tickers.
   - No duplicate ranks.
   - Output MUST be sorted ascending by `rank`.

3. **Only completed valuation runs are eligible.**
   - A valuation reference is usable only when `outcome == "complete"`.

4. **Newest successful valuation wins.**
   - When multiple completed entries exist for a ticker, use the newest completed run.

5. **Refreshes must be verified.**
   - A command returning control is not sufficient.
   - The workflow MUST confirm that a new completed reference entry exists for the ticker
     and capture its new `run_id`.

6. **Never overwrite a good record with incomplete data.**
   - Keep the prior valid output record if a required refresh fails.
   - Log the failure and continue with other tickers.

7. **Atomic output writes only.**
   - Write to a temporary file.
   - Validate the complete JSON.
   - Rename/replace the canonical file only after validation succeeds.

8. **No fabricated scores, grades, confidence, prices, timestamps, run IDs, or summaries.**

9. **Scores are numeric.**
   - `business_quality.score`, `valuation.score`, `derived_score`, and technical-analysis
     `score` MUST be numeric or `null`.
   - Never parse a missing value as zero.

---

## Output JSON Contract

The canonical output MUST be a JSON array.

Each record SHOULD use this normalized shape:

```json
{
  "rank": 1,
  "ticker": "NVDA",
  "name": "NVIDIA Corp",
  "sector": "Information Technology",
  "market_cap": "5.23T",
  "current_price": 217.08,
  "market_data_as_of": "2026-08-30T20:00:00Z",
  "business_quality": {
    "score": 0,
    "grade": "",
    "confidence": ""
  },
  "valuation": {
    "score": 0,
    "grade": "",
    "confidence": ""
  },
  "target_prices": {
    "A+": 148.64725879776387,
    "A": 171.44280382539412,
    "A-": 197.67329399417412,
    "price_at_valuation": 320.08224811514737
  },
  "run_id": "20260829T195640-NVDA-acf76a",
  "valuation_last_run_at": "2026-08-29T19:56:40Z",
  "derived_score": 0.0
}
```

### Field ownership

Use these sources:

| Field | Source of truth |
|---|---|
| `rank` | input JSON |
| `ticker` | input JSON |
| `name` | input JSON; preserve canonical company name |
| `sector` | input JSON |
| `market_cap` | latest current market data |
| `current_price` | latest current market price |
| `market_data_as_of` | timestamp of latest market-data lookup |
| `business_quality` | latest completed valuation reference |
| `valuation` | latest completed valuation reference |
| `target_prices` | latest completed valuation reference |
| `run_id` | latest completed valuation reference |
| `valuation_last_run_at` | timestamp stored in valuation history for selected `run_id` |
| `derived_score` | formula in this skill |

If the valuation reference does not contain a required valuation object after a successful
run, treat the run as invalid for this workflow and log the failure.

---

## Market Capitalization Format

Always store market capitalization as a string using only `T` or `B`.

Rules:

```text
>= 1,000,000,000,000  -> value in trillions + "T"
<  1,000,000,000,000  -> value in billions  + "B"
```

Examples:

```text
5,230,000,000,000 -> "5.23T"
850,000,000,000   -> "850.00B"
850,000,000       -> "0.85B"
```

Use two decimal places unless the upstream current-market-data value has a more precise
canonical display value that should be preserved.

Do not use `M`.

---

## Derived Metrics

### `derived_score`

For every record having both required numeric scores:

```text
derived_score =
    (0.60 * business_quality.score)
  + (0.40 * valuation.score)
```

Round only for presentation. Preserve at least two decimal places in the output.

If either source score is missing or non-numeric:

```text
derived_score = null
```

and exclude that ticker from top-10 ranking.

---

# Workflow

## Phase 0 — Initialize Run

Generate one workflow identifier:

```text
workflow_run_id = MAG50-<UTC_TIMESTAMP>-<short_random_suffix>
```

Capture:

- `started_at`
- input path
- output path
- reference paths
- log path
- current workflow date
- active profile/model/provider when applicable

Initialize an in-memory run ledger and an atomically updated recovery scratch file at:

```text
/home/s777data/Mag-50-recommend/logs/.runs/<workflow_run_id>.json
```

Record `run_start` in that ledger. Do **not** append an individual `run_start` line to the
canonical JSONL log. The canonical log receives exactly one consolidated object for the
workflow run during finalization.

---

## Phase 1 — Validate Input

Read:

```text
/home/s777data/Mag-50-recommend/inputs/top_50_sp500.json
```

Accept either canonical input envelope:

1. a root JSON array of company rows; or
2. a root JSON object whose `companies` field is an array of company rows (optional `metadata` is descriptive only).

Normalize either envelope to the in-memory company-row array before validation. Requirements for each input row:

- `rank`
- `ticker`
- `name`
- `sector`

Normalize ticker to uppercase for matching, but do not alter the source file.

Reject the workflow before valuation processing if:

- input is not valid JSON
- root is neither an array nor an object containing a `companies` array
- rank is missing/non-numeric
- ticker is missing
- duplicate input ranks exist
- duplicate input tickers exist

Sort the in-memory universe by ascending input rank.

The filename says `top_50_sp500.json`; process every valid row in the file rather than
hard-coding an exact record count.

---

## Phase 2 — Load and Validate Existing Output

If the canonical output exists:

1. Parse it.
2. Validate it as a JSON array.
3. Index records by ticker and rank.
4. Detect duplicates.
5. Preserve the last known valid record for recovery.

If the output does not exist, initialize an empty in-memory output list.

### Resume behavior

Do **not** rely only on the largest rank in the output.

Instead:

```text
pending ticker = first input ticker, in ascending input rank,
                 that does not have a valid output record
```

This prevents a partially written or gapped output from skipping a missing rank.

The "last rank" may be logged as a progress indicator, but the input file remains the
authoritative source for every rank.

---

## Phase 3 — Read Valuation History

Read:

```text
/home/s777data/outputs/robinhood-wheel-agent/company-valuation-score/valuation_history.json
```

Create lookup indexes by ticker, run ID, outcome, and completion timestamp using the
history file only. A candidate is eligible only when:

```text
outcome == "complete"
```

If multiple completed entries exist, select the newest completed entry using the
completion timestamp stored in valuation history. Do not read or require a separate audit
log.

---

## Phase 4 — Get Current Market Data

For every input ticker, obtain current market data sequentially before valuation runs.

Required values:

- current market price
- current market capitalization
- market-data timestamp

Use Robinhood MCP where the requested market value is available. Do not use a stale stored
output price as the current price. If a ticker's market data is unavailable, log the
failure, preserve its prior valid record when possible, and continue safely.

---

## Phase 5 — Run `company-valuation-score` Sequentially

Run `company-valuation-score` once for every input ticker, in ascending input-rank order.
Do not calculate age-based refresh requirements, price-drift thresholds, or confidence-
based refresh decisions. This workflow intentionally performs a direct sequential
valuation pass.

For each ticker:

1. Run the `company-valuation-score` skill.
2. Verify the process reports successful completion.
3. Re-read `valuation_history.json`.
4. Confirm a new completed entry exists for the ticker.
5. Confirm the selected entry has a run ID.
6. Confirm `business_quality`, `valuation`, and `target_prices` are readable.
7. Confirm required scores are numeric.
8. Only then replace the ticker's valuation data in the output.
9. Send one Telegram notification for the verified successful valuation run.
10. Record the result in the recovery ledger.

A failed ticker valuation must not overwrite a prior valid record. Log the failure and
continue with the next ticker.

---

## Phase 6 — Atomic Output Write and Validation

Before replacing the canonical output:

1. sort records by `rank`
2. ensure unique `rank`
3. ensure unique `ticker`
4. ensure every output ticker exists in input
5. ensure every output `rank` matches its input ticker
6. validate numeric score fields
7. validate JSON serialization
8. write a temporary file
9. fsync/close when supported
10. atomically rename the temporary file to:

```text
/home/s777data/Mag-50-recommend/outputs/top_50_sp500_valuation.json
```

Never leave a truncated canonical JSON file.

---

## Phase 7 — Select Top 10 by `derived_score`

After the sequential valuation pass and output reconciliation:

1. load the final canonical output
2. exclude records where `derived_score == null`
3. sort by:
   1. `derived_score` descending
   2. `business_quality.score` descending
   3. `valuation.score` descending
   4. `rank` ascending
4. select up to 10 records

The tie-breakers above make selection deterministic.

Log the complete ordered top-10 set.

---

## Phase 8 — Run Technical Analysis Sequentially

For each selected ticker, in top-10 order, run:

```text
technical-analysis-buy-recommend
```

using:

```text
profile: options-wheel-agent
market/account context: Robinhood MCP
```

Do not run technical-analysis requests concurrently. A failed technical-analysis run for
one ticker must be logged and must not erase other successful candidates.

---

## Phase 9 — Choose Final Top 2 Recommendations

---

## Phase 11 — Choose Final Top 2 Recommendations

Choose from successfully completed technical-analysis results.

Selection priority:

1. verdict representing a positive buy recommendation, ordered by technical `score`
   descending
2. `derived_score` descending
3. input `rank` ascending

If fewer than two results have a buy-positive verdict, fill remaining slots with the
highest technical-analysis scores from the successful results, while preserving and
reporting their actual verdict. Never relabel a non-buy verdict as BUY.

For the final message, rename `derived_score` to:

```text
v_derived_score
```

for presentation only.

---

## Telegram Notifications

Use the Telegram bot and home destination configured in the active
`options-wheel-agent` profile. Resolve that profile destination at runtime (for example,
with `hermes send --list telegram`) and send through `hermes send --to telegram` or the
resolved profile destination. Do not substitute another profile, bot, or recipient.

### Scheduled-run delivery requirement

The workflow's valuation-refresh and final recommendation notifications are separate,
required messages. Never rely on the cron scheduler's automatic final-response delivery
as a substitute for them.

When this skill runs as a cron job and the explicit Telegram destination is also the
cron's delivery target, configure the cron job with `deliver: local`. This prevents
Hermes' `cron_auto_delivery_duplicate_target` guard from suppressing the explicit
messages. The skill MUST then explicitly send all required notifications and the final
workflow summary using the Telegram bot configured in `options-wheel-agent`.

For every send, inspect the structured result. Count it as sent only when delivery reports
success and `skipped` is not `true`. A result with `skipped: true`, including
`cron_auto_delivery_duplicate_target`, is **not delivered**: record
`TELEGRAM_SEND_SKIPPED`, preserve the exact skip reason, count it in `telegram_failed`,
and report the delivery defect in the final summary. Do not report a skipped send as a
successful notification.

If no Telegram destination is configured, log `TELEGRAM_NOT_CONFIGURED`; do not invent a
chat ID, bot token, recipient, or alternate destination.

### Notification A — Every successful valuation refresh

Send exactly one notification after each verified successful
`company-valuation-score` run.

Recommended human-readable structure:

```text
✅ Mag-50 valuation refreshed

Ticker: NVDA
Rank: 1
Run ID: 20260829T195640-NVDA-acf76a
Business Quality: 88.0 (A)
Valuation: 72.0 (B+)
Derived Score: 81.60
Refresh Reason: PRICE_DRIFT_10_PERCENT
```

Do not send this notification for reused/non-refreshed reference data.

### Notification B — Final top 2

After technical analysis, send one final human-readable Telegram message.

Required fields for each recommendation:

- `Ticker`
- `score`
- `verdict`
- `summary`
- `v_derived_score`

Example:

```text
🏆 Mag-50 Top Recommendations

1) NVDA
Technical Score: 91
Verdict: BUY
Summary: Strong trend and favorable buy setup.
v_derived_score: 84.60

2) META
Technical Score: 88
Verdict: BUY
Summary: Constructive momentum with favorable confirmation.
v_derived_score: 82.15
```

Use actual skill output. Do not use the example values as defaults.

Telegram send failures MUST be logged but MUST NOT roll back an otherwise valid valuation
output file.

---

# Logging Contract

Store workflow records in:

```text
/home/s777data/Mag-50-recommend/logs/Mag-50-recommend.jsonl
```

Use UTF-8 JSON Lines with **exactly one valid JSON object per `workflow_run_id`**. A run
must never occupy multiple canonical lines. The consolidated object contains the run
summary plus nested arrays for ticker-level, valuation, technical-analysis, output-write,
and Telegram details.

## In-run persistence and crash recovery

During execution, maintain one recovery scratch file:

```text
/home/s777data/Mag-50-recommend/logs/.runs/<workflow_run_id>.json
```

Update this scratch object atomically after each material action. It may contain an
`events` array for detailed chronology, but those events MUST NOT be appended as separate
lines to the canonical JSONL file. If execution stops unexpectedly, a later resume may
load this scratch file and finalize the same `workflow_run_id`.

## Canonical finalization

At `run_complete` or `run_failure`:

1. Build one consolidated run object.
2. Include `workflow_run_id`, `started_at`, `ended_at`, `status`, counters, top 10, top 2,
   output/log paths, and nested detail arrays.
3. Read the canonical JSONL and validate every existing line.
4. Remove any existing line having the same `workflow_run_id`.
5. Append the new consolidated object in memory.
6. Verify all `workflow_run_id` values are present, non-empty, and unique.
7. Write the full JSONL to a temporary file, `fsync`, and atomically replace the canonical
   log.
8. Read the canonical log back and verify exactly one line matches the current
   `workflow_run_id`.
9. Delete the recovery scratch file only after read-back verification succeeds.

This is atomic **upsert** behavior, not event-by-event append behavior. Historical run
records remain unchanged except when deliberately migrating legacy multi-line runs into
the consolidated schema. For that migration, use:

```bash
python3 scripts/consolidate_mag50_log.py \
  /home/s777data/Mag-50-recommend/logs/Mag-50-recommend.jsonl
```

The migration helper creates a timestamped backup, writes atomically, and verifies one
line per unique `workflow_run_id`.

## Consolidated run object

Each canonical line MUST contain at least:

```json
{
  "workflow_run_id": "MAG50-20260830T200000Z-a1b2c3",
  "started_at": "2026-08-30T20:00:00Z",
  "ended_at": "2026-08-30T20:10:00Z",
  "status": "success",
  "summary": {},
  "ticker_details": [],
  "valuation_refreshes": [],
  "technical_analysis": [],
  "telegram_notifications": [],
  "output_writes": [],
  "events": []
}
```

The nested `events` array may use these event names where applicable:

```text
run_start
input_validated
output_loaded
ticker_market_data
ticker_reconciled
valuation_refresh_start
valuation_refresh_success
valuation_refresh_failure
output_write_success
output_write_failure
telegram_send_success
telegram_send_failure
top10_selected
technical_analysis_start
technical_analysis_success
technical_analysis_failure
top2_selected
run_complete
run_failure
```

The detailed event history is nested inside the one run object; it is never emitted as
separate canonical JSONL lines.

## Ticker-level logging fields

For ticker-specific events, include as many of these as apply:

```json
{
  "ticker": "NVDA",
  "rank": 1,
  "previous_run_id": "old-run-id",
  "selected_run_id": "new-run-id",
  "valuation_last_run_at": "2026-08-29T19:56:40Z",
  "latest_price": 217.08,
  "market_cap": "5.23T",

  "business_quality_score": 88.0,
  "business_quality_grade": "A",
  "business_quality_confidence": "high",
  "valuation_score": 72.0,
  "valuation_grade": "B+",
  "valuation_confidence": "high",
  "derived_score": 81.6,
  "duration_ms": 0,
  "error_code": null,
  "error_message": null
}
```

## Technical-analysis logging fields

For technical-analysis events, include:

```json
{
  "ticker": "NVDA",
  "rank": 1,
  "derived_score": 81.6,
  "technical_score": 91,
  "technical_verdict": "BUY",
  "technical_summary": "Strong trend and favorable buy setup.",
  "profile": "options-wheel-agent",
  "robinhood_mcp_used": true,
  "duration_ms": 0,
  "error_code": null,
  "error_message": null
}
```

## Consolidated `summary` fields

Place one final summary object inside the canonical run record. Do not append it as a
separate line:

```json
{
  "timestamp": "2026-08-30T20:10:00Z",
  "workflow_run_id": "MAG50-20260830T200000Z-a1b2c3",
  "event": "run_complete",
  "status": "success",
  "started_at": "2026-08-30T20:00:00Z",
  "ended_at": "2026-08-30T20:10:00Z",
  "duration_ms": 600000,
  "input_count": 50,
  "output_count": 50,
  "tickers_checked": 50,
  "valuation_refresh_attempted": 4,
  "valuation_refresh_succeeded": 4,
  "valuation_refresh_failed": 0,
  "top10": ["NVDA", "META"],
  "technical_analysis_attempted": 10,
  "technical_analysis_succeeded": 10,
  "technical_analysis_failed": 0,
  "top2": ["NVDA", "META"],
  "telegram_sent": 5,
  "telegram_failed": 0,
  "output_path": "/home/s777data/Mag-50-recommend/outputs/top_50_sp500_valuation.json"
}
```

`top10` SHOULD contain all selected top-10 tickers; the abbreviated example above is only
illustrative.

---

## Standard Error Codes

Use stable machine-readable codes whenever possible:

```text
INPUT_JSON_INVALID
INPUT_DUPLICATE_RANK
INPUT_DUPLICATE_TICKER
INPUT_REQUIRED_FIELD_MISSING
OUTPUT_JSON_INVALID
OUTPUT_DUPLICATE_RANK
OUTPUT_DUPLICATE_TICKER
REFERENCE_FILE_UNAVAILABLE
NO_COMPLETED_REFERENCE
RUN_ID_NOT_FOUND
VALUATION_FIELDS_MISSING
BUSINESS_CONFIDENCE_LOW
BUSINESS_CONFIDENCE_MEDIUM
VALUATION_CONFIDENCE_LOW
VALUATION_REFRESH_FAILED
VALUATION_REFERENCE_NOT_UPDATED
MARKET_PRICE_UNAVAILABLE
MARKET_CAP_UNAVAILABLE
STORED_PRICE_INVALID
TECHNICAL_ANALYSIS_FAILED
TELEGRAM_NOT_CONFIGURED
TELEGRAM_SEND_FAILED
TELEGRAM_SEND_SKIPPED
OUTPUT_WRITE_FAILED
```

Multiple refresh reasons may apply to one ticker. Store them as an array.

---

## Idempotency and Resume Rules

A rerun on the same day MUST be safe.

1. Never duplicate output records.
2. Never duplicate ranks.
3. Never append a second output record for a ticker already present; update/replace it.
4. A valuation refresh should occur only when a refresh condition is currently true.
5. After a successful refresh, re-read the reference and use the new completed `run_id`.
6. Do not re-send a valuation-success notification in the same workflow run for the same
   successful valuation `run_id`.
7. Log every workflow execution with a unique `workflow_run_id` and exactly one consolidated canonical JSONL line.
8. Finalization MUST atomically upsert by `workflow_run_id`; never append a second canonical line for the same run.
9. If a prior workflow stopped midway, resume by reconciling all input tickers, not by
   blindly starting after the maximum output rank.
10. Existing valid records may be retained when a ticker-specific refresh fails.
11. The final top 10/top 2 must always be derived from the latest valid canonical output
    available at the end of the run.

---

## Failure Policy

### Fatal failures

Stop the workflow and atomically finalize one consolidated run record with `status: "failure"` when safe execution is impossible, including:

- invalid input JSON
- duplicate input rank/ticker
- canonical output cannot be parsed and no safe recovery copy exists
- log path cannot be created/written
- required valuation reference files are completely unavailable
- output cannot be safely written atomically

### Non-fatal ticker failures

Log and continue for:

- one ticker market-data failure
- one ticker valuation refresh failure
- one ticker technical-analysis failure
- one Telegram notification failure

A workflow with non-fatal failures may complete with:

```text
status: "partial_success"
```

The final log summary MUST report failure counts.

---

## Final Verification Checklist

Before declaring the daily workflow complete, confirm:

- [ ] input JSON parsed successfully
- [ ] input ranks/tickers are unique
- [ ] every output ticker maps to the correct input rank
- [ ] output JSON is valid
- [ ] output contains no duplicate ticker/rank
- [ ] market caps use only `T` or `B`
- [ ] current market prices were refreshed where available
- [ ] every attempted valuation refresh was verified in the reference data
- [ ] successful refreshes replaced old `run_id` and valuation details
- [ ] `derived_score` uses 60% business quality + 40% valuation
- [ ] top 10 was selected deterministically
- [ ] technical analysis was attempted for each eligible top-10 ticker
- [ ] final top 2 was selected from actual technical-analysis results
- [ ] required Telegram valuation notifications were attempted
- [ ] final top-2 Telegram notification was attempted
- [ ] all event details were consolidated into one canonical JSONL object for this `workflow_run_id`
- [ ] the canonical log contains exactly one line for this `workflow_run_id`
- [ ] all canonical `workflow_run_id` values are unique
- [ ] the consolidated record contains final `run_complete` or `run_failure` status

---

## Final Console/Agent Response

At the end of the workflow, return a concise summary containing:

```text
Workflow Run ID:
Status:
Input Tickers:
Output Tickers:
Valuations Refreshed:
Valuation Refresh Failures:
Top 10:
Technical Analysis Successes:
Technical Analysis Failures:
Top 2:
Telegram Notifications Sent:
Telegram Notification Failures:
Output File:
Log File:
```

Do not claim success for any action that was not verified.
