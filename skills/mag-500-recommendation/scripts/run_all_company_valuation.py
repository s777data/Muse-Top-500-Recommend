"""DEPRECATED — DO NOT USE (PRD 13.3, DEVIATIONS D-08).

Copied verbatim from the Mag-50 source for reference only. This direct
valuation helper is stale relative to the orchestrator interface (it
imports a `valuation_command` symbol that does not exist) and is NOT
wired into the Mag-500 pipeline. The durable launcher +
mag50_auto_orchestrate.py (with scripts/valuation_adapter.py) are the
authoritative path.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = Path('/home/s777data')
RUNS = ROOT / 'logs' / '.runs'
RUNS.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(ROOT / 'scripts'))
from mag50_auto_orchestrate import load_json, valuation_command  # noqa: E402

INPUT = ROOT / 'inputs' / 'top_50_sp500.json'
raw = load_json(INPUT)
rows = raw['companies'] if isinstance(raw, dict) else raw
tickers = [str(row['ticker']).upper() for row in rows]
run_id = time.strftime('DIRECT-%Y%m%dT%H%M%SZ', time.gmtime())


def run(ticker: str) -> dict:
    started = time.time()
    attempts = []
    max_attempts = 3
    for attempt in range(1, max_attempts + 1):
        code, output = valuation_command(ticker)
        attempts.append({'attempt': attempt, 'exit_code': code, 'output_tail': output[-1000:]})
        if code == 0:
            break
        if attempt < max_attempts:
            time.sleep(30 * (2 ** (attempt - 1)))
    path = RUNS / f'{run_id}-{ticker}.valuation.out'
    path.write_text(output, encoding='utf-8')
    return {
        'ticker': ticker,
        'exit_code': code,
        'attempts': attempts,
        'duration_seconds': round(time.time() - started, 2),
        'output_path': str(path),
        'ok': code == 0,
        'error_tail': None if code == 0 else output[-1000:],
    }


results = []
# Sequential execution is intentional: complete/retry one ticker before starting the next.
for ticker in tickers:
    result = run(ticker)
    results.append(result)
    print(json.dumps(result, separators=(',', ':')), flush=True)

results.sort(key=lambda x: tickers.index(x['ticker']))
summary = {
    'run_id': run_id,
    'input_count': len(tickers),
    'succeeded': sum(x['ok'] for x in results),
    'failed': sum(not x['ok'] for x in results),
    'results': results,
}
summary_path = RUNS / f'{run_id}-summary.json'
summary_path.write_text(json.dumps(summary, indent=2), encoding='utf-8')
print(json.dumps({'summary_path': str(summary_path), 'run_id': run_id, 'input_count': len(tickers), 'succeeded': summary['succeeded'], 'failed': summary['failed']}), flush=True)
