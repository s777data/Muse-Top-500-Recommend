#!/usr/bin/env python3
from __future__ import annotations

import json
import math
import os
import re
import secrets
import signal
import subprocess
import sys
import tempfile
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

# D-01 (DEVIATIONS.md): MAG500_* env config with repo-relative defaults;
# host paths and the Hermes profile are gone. D-06: the pinned
# model/provider is removed (PRD 13.1) — no model runs anywhere in this
# pipeline; technicals execute as direct code (design C).
REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
BASE = Path(os.environ.get('MAG500_BASE', str(REPO_ROOT)))
INPUT = Path(os.environ.get('MAG500_INPUT', str(BASE / 'data/sp500_constituents.json')))
OUTPUT = Path(os.environ.get('MAG500_OUTPUT', str(BASE / 'outputs/top_sp500_valuation.json')))
HISTORY = Path(os.environ.get('MAG500_HISTORY', str(BASE / 'data/valuation_history.json')))
LOG = Path(os.environ.get('MAG500_LOG', str(BASE / 'logs/Mag-500-recommend.jsonl')))
RUNS = Path(os.environ.get('MAG500_RUNS', str(BASE / 'logs/.runs')))
VAL_ENV = os.environ.copy()
VAL_ENV['PYTHONPATH'] = str(REPO_ROOT) + os.pathsep + VAL_ENV.get('PYTHONPATH', '')
VAL_ENV['MAG500_HISTORY_PATH'] = str(HISTORY)
VALUATION_WORKERS = max(1, min(8, int(os.environ.get('MAG500_VALUATION_WORKERS', '4'))))
VALUATION_TIMEOUT_SECONDS = int(os.environ.get('MAG500_VALUATION_TIMEOUT_SECONDS', '900'))
VALUATION_HEARTBEAT_SECONDS = int(os.environ.get('MAG500_VALUATION_HEARTBEAT_SECONDS', '15'))
VALUATION_TERMINATE_GRACE_SECONDS = int(os.environ.get('MAG500_VALUATION_TERMINATE_GRACE_SECONDS', '5'))
MARKET_TIMEOUT_SECONDS = int(os.environ.get('MAG500_MARKET_TIMEOUT_SECONDS', '420'))
MARKET_HEARTBEAT_SECONDS = int(os.environ.get('MAG500_MARKET_HEARTBEAT_SECONDS', '15'))
SUBPROCESS_OUTPUT_TAIL_CHARS = int(os.environ.get('MAG500_SUBPROCESS_OUTPUT_TAIL_CHARS', '3000'))
ACTIVE_RUN_CONTEXT: dict[str, Any] | None = None
SHUTDOWN_REQUESTED = False

if VALUATION_TIMEOUT_SECONDS <= 0:
    raise ValueError('MAG500_VALUATION_TIMEOUT_SECONDS must be positive')
if VALUATION_HEARTBEAT_SECONDS <= 0:
    raise ValueError('MAG500_VALUATION_HEARTBEAT_SECONDS must be positive')
if VALUATION_TERMINATE_GRACE_SECONDS <= 0:
    raise ValueError('MAG500_VALUATION_TERMINATE_GRACE_SECONDS must be positive')
if MARKET_TIMEOUT_SECONDS <= 0:
    raise ValueError('MAG500_MARKET_TIMEOUT_SECONDS must be positive')
if MARKET_HEARTBEAT_SECONDS <= 0:
    raise ValueError('MAG500_MARKET_HEARTBEAT_SECONDS must be positive')
if SUBPROCESS_OUTPUT_TAIL_CHARS <= 0:
    raise ValueError('MAG500_SUBPROCESS_OUTPUT_TAIL_CHARS must be positive')


class WorkflowInterrupted(RuntimeError):
    pass


def request_shutdown(signum: int, _frame: Any) -> None:
    """Set a flag only; normal control flow owns cleanup and file I/O."""
    global SHUTDOWN_REQUESTED
    SHUTDOWN_REQUESTED = True


def raise_if_shutdown() -> None:
    if SHUTDOWN_REQUESTED:
        raise WorkflowInterrupted('shutdown requested')


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def _prefetch_reuse_hours() -> float:
    """D-13 (DEVIATIONS.md): MAG500_PREFETCH_REUSE_HOURS — resumable
    valuation reuse window in hours. Unset/empty/0/invalid/negative =
    0.0 (reuse off; pre-D-13 behaviour exactly)."""
    try:
        hours = float(os.environ.get('MAG500_PREFETCH_REUSE_HOURS', '') or 0)
    except (TypeError, ValueError):
        return 0.0
    return hours if hours > 0 else 0.0


def _prefetch_cutoff() -> tuple[str, datetime | None]:
    """(cutoff_iso, cutoff_dt) for the Phase 6 verify-mode children.

    D-13: with reuse on, the MAG500_PREFETCH_CUTOFF handed to the
    adapter children moves back by the reuse window, so records seeded
    by an earlier (possibly interrupted) attempt count as fresh and
    the children verify-and-exit instead of re-evaluating. With reuse
    off the cutoff is the run start (now) and the returned datetime is
    None, which keeps classify_refresh_result on its original
    new-record proof."""
    hours = _prefetch_reuse_hours()
    if hours > 0:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        return cutoff.isoformat().replace('+00:00', 'Z'), cutoff
    return now_iso(), None


def parse_dt(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value.replace('Z', '+00:00'))
    except Exception:
        return None


def atomic_write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f'.{path.name}.', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            json.dump(obj, handle, indent=2, ensure_ascii=False)
            handle.write('\n')
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            try:
                os.unlink(tmp)
            except FileNotFoundError:
                pass


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f'.{path.name}.', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            try:
                os.unlink(tmp)
            except FileNotFoundError:
                pass


def load_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except FileNotFoundError:
        return default


def extract_json(text: str) -> Any:
    text = (text or '').strip()
    if not text:
        raise ValueError('empty output')
    try:
        return json.loads(text)
    except Exception:
        pass
    candidates = []
    for start in [text.find('['), text.find('{')]:
        if start >= 0:
            candidates.append(text[start:])
    for candidate in candidates:
        try:
            return json.loads(candidate)
        except Exception:
            continue
    # As a final fallback, try to isolate the last JSON object/array in the text.
    for pattern in [r'(\[.*\])', r'(\{.*\})']:
        matches = re.findall(pattern, text, flags=re.S)
        for candidate in reversed(matches):
            try:
                return json.loads(candidate)
            except Exception:
                continue
    raise ValueError(f'could not parse JSON from output: {text[:500]!r}')


def hermes_json(
    prompt: str,
    *,
    model: str | None = None,
    provider: str | None = None,
    skills: list[str] | None = None,
    timeout: int = 600,
    heartbeat_seconds: int = MARKET_HEARTBEAT_SECONDS,
    heartbeat: Any = None,
) -> Any:
    cmd = ['hermes', '-p', 'options-wheel-agent']
    if model:
        cmd += ['-m', model]
    if provider:
        cmd += ['--provider', provider]
    cmd += ['-z', prompt]
    if skills:
        cmd += ['--skills', ','.join(skills)]
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    started = time.monotonic()
    stdout = ''
    stderr = ''
    try:
        if heartbeat:
            heartbeat(proc.pid)
        while True:
            raise_if_shutdown()
            remaining = timeout - (time.monotonic() - started)
            if remaining <= 0:
                raise subprocess.TimeoutExpired(cmd, timeout)
            try:
                stdout, stderr = proc.communicate(timeout=min(heartbeat_seconds, remaining))
                break
            except subprocess.TimeoutExpired:
                if heartbeat:
                    heartbeat(proc.pid)
    except (subprocess.TimeoutExpired, WorkflowInterrupted) as exc:
        terminate_process_tree(proc)
        stdout, stderr = bounded_communicate_after_termination(proc)
        if isinstance(exc, WorkflowInterrupted):
            raise
        raise TimeoutError(f'hermes command timed out after {timeout}s: {cmd[:4]!r}')
    except BaseException:
        terminate_process_tree(proc)
        bounded_communicate_after_termination(proc)
        raise
    if proc.returncode != 0:
        raise RuntimeError(f'hermes rc={proc.returncode}: {(stderr or stdout)[-2000:]}')
    return extract_json(stdout)


def run_subprocess(command: list[str], *, cwd: str | None = None, env: dict[str, str] | None = None, timeout: int = 600) -> tuple[int, str]:
    proc = subprocess.run(command, cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout)
    out = (proc.stdout or '') + (('\n' + proc.stderr) if proc.stderr else '')
    return proc.returncode, out


def fmt_cap(raw: Any) -> str | None:
    try:
        v = float(raw)
    except Exception:
        return None
    if v >= 1_000_000_000_000:
        return f'{v / 1_000_000_000_000:.2f}T'
    if v >= 1_000_000_000:
        return f'{v / 1_000_000_000:.2f}B'
    if v > 0:
        return f'{v / 1_000_000_000:.2f}B'
    return None


def normalize_input_rows() -> list[dict[str, Any]]:
    raw = load_json(INPUT)
    if isinstance(raw, list):
        rows = raw
    elif isinstance(raw, dict) and isinstance(raw.get('companies'), list):
        rows = raw['companies']
    else:
        raise ValueError('INPUT_JSON_INVALID')
    seen_ranks: set[Any] = set()
    seen_ticks: set[str] = set()
    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError('INPUT_REQUIRED_FIELD_MISSING')
        for key in ('rank', 'ticker', 'name', 'sector'):
            if key not in row:
                raise ValueError('INPUT_REQUIRED_FIELD_MISSING')
        rank = row['rank']
        if not isinstance(rank, (int, float)) or isinstance(rank, bool):
            raise ValueError('INPUT_REQUIRED_FIELD_MISSING')
        ticker = str(row['ticker']).strip().upper()
        if not ticker:
            raise ValueError('INPUT_REQUIRED_FIELD_MISSING')
        if rank in seen_ranks:
            raise ValueError('INPUT_DUPLICATE_RANK')
        if ticker in seen_ticks:
            raise ValueError('INPUT_DUPLICATE_TICKER')
        seen_ranks.add(rank)
        seen_ticks.add(ticker)
        copy = dict(row)
        copy['ticker'] = ticker
        out.append(copy)
    return sorted(out, key=lambda x: x['rank'])


def load_output_rows() -> list[dict[str, Any]]:
    if not OUTPUT.exists():
        return []
    raw = load_json(OUTPUT)
    if not isinstance(raw, list):
        raise ValueError('OUTPUT_JSON_INVALID')
    seen_ranks: set[Any] = set()
    seen_ticks: set[str] = set()
    for row in raw:
        if not isinstance(row, dict):
            raise ValueError('OUTPUT_JSON_INVALID')
        rank = row.get('rank')
        ticker = str(row.get('ticker', '')).upper()
        if rank in seen_ranks:
            raise ValueError('OUTPUT_DUPLICATE_RANK')
        if ticker in seen_ticks:
            raise ValueError('OUTPUT_DUPLICATE_TICKER')
        seen_ranks.add(rank)
        seen_ticks.add(ticker)
    return raw


def _is_finite_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def _reference_timestamp(entry: dict[str, Any]) -> Any:
    return (
        entry.get('completed_at')
        or entry.get('completion_timestamp')
        or entry.get('as_of')
        or entry.get('data_cutoff_at')
    )


def normalize_reference(entry: dict[str, Any]) -> dict[str, Any]:
    valuation_raw = entry.get('valuation')
    valuation: dict[str, Any] = valuation_raw if isinstance(valuation_raw, dict) else {}
    grade_raw = valuation.get('grade')
    grade: dict[str, Any] = grade_raw if isinstance(grade_raw, dict) else {}
    business_quality_raw = entry.get('business_quality')
    bq = business_quality_raw if isinstance(business_quality_raw, dict) else valuation.get('business_quality')
    if not isinstance(bq, dict):
        bq = grade.get('business_quality')
    if not isinstance(bq, dict):
        bq = {}
    valuation_obj = {
        'score': valuation.get('score', grade.get('score', entry.get('final_score'))) if not isinstance(valuation.get('grade'), dict) else grade.get('score'),
        'grade': valuation.get('grade', grade.get('grade', entry.get('grade'))) if not isinstance(valuation.get('grade'), dict) else grade.get('grade'),
        'confidence': valuation.get('confidence', grade.get('confidence', entry.get('confidence'))) if not isinstance(valuation.get('grade'), dict) else grade.get('confidence'),
    }
    if _is_finite_number(valuation.get('score')):
        valuation_obj['score'] = valuation.get('score')
    if isinstance(valuation.get('grade'), str):
        valuation_obj['grade'] = valuation.get('grade')
    if isinstance(valuation.get('confidence'), str):
        valuation_obj['confidence'] = valuation.get('confidence')
    if _is_finite_number(grade.get('score')) and valuation_obj['score'] is None:
        valuation_obj['score'] = grade.get('score')
    if isinstance(grade.get('grade'), str) and not valuation_obj['grade']:
        valuation_obj['grade'] = grade.get('grade')
    if isinstance(grade.get('confidence'), str) and not valuation_obj['confidence']:
        valuation_obj['confidence'] = grade.get('confidence')

    target_prices_raw = entry.get('target_prices')
    target_prices = target_prices_raw if isinstance(target_prices_raw, dict) else valuation.get('target_prices')
    if not isinstance(target_prices, dict):
        target_prices = grade.get('target_prices')
    if isinstance(target_prices, dict):
        target_prices = dict(target_prices)
        if 'price_at_valuation' not in target_prices and 'current' in target_prices:
            target_prices['price_at_valuation'] = target_prices.pop('current')
    else:
        target_prices = None

    return {
        'ticker': str(entry.get('ticker', '')).strip().upper(),
        'business_quality': bq,
        'valuation': valuation_obj,
        'target_prices': target_prices,
        'run_id': entry.get('run_id'),
        'valuation_last_run_at': _reference_timestamp(entry),
    }


def reference_validation_error(entry: dict[str, Any]) -> str | None:
    """Return a precise rejection reason, or None for a usable completed entry."""
    if not isinstance(entry, dict):
        return 'REFERENCE_NOT_OBJECT'
    if not str(entry.get('ticker', '')).strip():
        return 'REFERENCE_TICKER_MISSING'
    if not isinstance(entry.get('run_id'), str) or not entry['run_id'].strip():
        return 'RUN_ID_NOT_FOUND'

    outcome = entry.get('outcome')
    persisted_present = isinstance(entry.get('persisted'), dict)
    persisted = entry.get('persisted') if persisted_present else {}
    audit_outcome = persisted.get('audit_outcome')
    status = entry.get('status')
    valuation_payload = entry.get('valuation')
    grade_payload: dict[str, Any] = {}
    if isinstance(valuation_payload, dict):
        grade_candidate = valuation_payload.get('grade')
        if isinstance(grade_candidate, dict):
            grade_payload = grade_candidate
    if status is not None and status not in {'ok', 'complete'}:
        return 'REFERENCE_STATUS_NOT_OK'
    if grade_payload.get('status') is not None and grade_payload.get('status') != 'ok':
        return 'REFERENCE_GRADE_STATUS_NOT_OK'
    if outcome is not None and outcome != 'complete':
        return 'REFERENCE_OUTCOME_NOT_COMPLETE'
    if audit_outcome is not None and audit_outcome != 'complete':
        return 'REFERENCE_AUDIT_NOT_COMPLETE'
    if persisted.get('history_entry_verified') is False:
        return 'REFERENCE_HISTORY_NOT_VERIFIED'
    if persisted.get('audit_record_verified') is False:
        return 'REFERENCE_AUDIT_NOT_VERIFIED'

    # Legacy rows prove completion with top-level outcome. Current persisted-result
    # rows use audit_outcome. The current history writer intentionally stores neither;
    # its versioned shape is recognized by data_cutoff_at plus nested valuation data.
    current_history_shape = (
        outcome is None
        and audit_outcome is None
        and not persisted_present
        and bool(entry.get('data_cutoff_at'))
        and isinstance(valuation_payload, dict)
        and grade_payload.get('status') == 'ok'
    )
    if outcome != 'complete' and audit_outcome != 'complete' and not current_history_shape:
        return 'REFERENCE_COMPLETION_UNPROVEN'

    ref = normalize_reference(entry)
    bq = ref.get('business_quality')
    valuation = ref.get('valuation')
    target_prices = ref.get('target_prices')
    if not isinstance(bq, dict) or not _is_finite_number(bq.get('score')):
        return 'BUSINESS_QUALITY_SCORE_INVALID'
    if not isinstance(valuation, dict) or not _is_finite_number(valuation.get('score')):
        return 'VALUATION_SCORE_INVALID'
    if not isinstance(target_prices, dict) or not target_prices:
        return 'TARGET_PRICES_MISSING'
    readable_targets = [
        value
        for key, value in target_prices.items()
        if key not in {'current', 'price_at_valuation'} and _is_finite_number(value)
    ]
    if not readable_targets and not _dcf_missing_target_ok(target_prices):
        return 'TARGET_PRICES_INVALID'
    return None


def _dcf_missing_target_ok(target_prices: Any) -> bool:
    """D-12 (approved 2026-11-14): a target_prices object with no numeric
    target is still valid when the dashboard engine deliberately produced
    no DCF for a fully-scored name — recorded as a null dcf_fair_value
    plus a non-empty dcf_missing_reason (e.g. 'fcf_base_missing'). The
    Final/derived score never uses the DCF target. Anything else with no
    numeric target (no reason, or a non-null DCF value that is somehow
    non-numeric) stays invalid. See DEVIATIONS.md D-12."""
    if not isinstance(target_prices, dict):
        return False
    reason = target_prices.get('dcf_missing_reason')
    return (
        isinstance(reason, str)
        and bool(reason.strip())
        and 'dcf_fair_value' in target_prices
        and target_prices.get('dcf_fair_value') is None
    )


def is_completed_reference(entry: dict[str, Any]) -> bool:
    return reference_validation_error(entry) is None


def load_reference_entries() -> tuple[list[dict[str, Any]], dict[str, list[tuple[datetime, dict[str, Any]]]]]:
    # D-11: a MISSING history file is an empty history (first-ever run;
    # the valuation adapter creates the file on its first successful
    # valuation). A present but malformed file still fails closed with
    # REFERENCE_FILE_UNAVAILABLE below.
    if not HISTORY.exists():
        return [], {}
    hist_raw = load_json(HISTORY)
    hist_entries: list[dict[str, Any]] = []
    if isinstance(hist_raw, list):
        hist_entries = [x for x in hist_raw if isinstance(x, dict)]
    elif isinstance(hist_raw, dict):
        if hist_raw.get('ticker') and hist_raw.get('run_id'):
            hist_entries = [dict(hist_raw)]
        else:
            for ticker, value in hist_raw.items():
                if isinstance(value, list):
                    for item in value:
                        if isinstance(item, dict):
                            item = dict(item)
                            item.setdefault('ticker', ticker)
                            hist_entries.append(item)
                elif isinstance(value, dict):
                    item = dict(value)
                    item.setdefault('ticker', ticker)
                    hist_entries.append(item)
    else:
        raise ValueError('REFERENCE_FILE_UNAVAILABLE')

    latest_by_ticker: dict[str, list[tuple[datetime, dict[str, Any]]]] = {}
    for entry in hist_entries:
        ticker = str(entry.get('ticker', '')).strip().upper()
        if not is_completed_reference(entry):
            continue
        ts = _reference_timestamp(entry)
        dt = parse_dt(ts) or datetime.min.replace(tzinfo=timezone.utc)
        latest_by_ticker.setdefault(ticker, []).append((dt, entry))
    for ticker in latest_by_ticker:
        latest_by_ticker[ticker].sort(key=lambda item: (item[0], str(item[1].get('run_id', ''))))
    return hist_entries, latest_by_ticker


def valid_reference(ref: dict[str, Any]) -> bool:
    bq = ref.get('business_quality') or {}
    val = ref.get('valuation') or {}
    tp = ref.get('target_prices')
    return (
        isinstance(bq, dict)
        and isinstance(val, dict)
        and isinstance(tp, dict)
        and _is_finite_number(bq.get('score'))
        and _is_finite_number(val.get('score'))
        and (
            any(
                key not in {'current', 'price_at_valuation'} and _is_finite_number(value)
                for key, value in tp.items()
            )
            # D-12: DCF-missing-but-fully-scored shape (null DCF +
            # recorded missing reason) is equally valid.
            or _dcf_missing_target_ok(tp)
        )
        and bool(ref.get('run_id'))
    )


def fetch_market_ticker(ticker: str, *, heartbeat: Any = None) -> dict[str, Any]:
    prompt = (
        'Use Robinhood MCP only. Fetch current quotes and fundamentals for symbols '
        f'{json.dumps([ticker])}. Return a JSON array with one object for the symbol containing '
        'keys ticker, current_price from last_trade_price, market_cap_raw from fundamentals, '
        'quote_state, has_traded, and market_data_as_of as the quote timestamp. Return JSON only.'
    )
    data = hermes_json(
        prompt,
        timeout=MARKET_TIMEOUT_SECONDS,
        heartbeat_seconds=MARKET_HEARTBEAT_SECONDS,
        heartbeat=heartbeat,
    )
    if not isinstance(data, list) or len(data) != 1 or not isinstance(data[0], dict):
        raise ValueError(f'market response must contain exactly one object for {ticker}')
    item = data[0]
    returned_ticker = str(item.get('ticker', '')).upper()
    if returned_ticker != ticker:
        raise ValueError(f'market response ticker mismatch: expected {ticker}, got {returned_ticker}')
    return {
        'ticker': returned_ticker,
        'current_price': item.get('current_price'),
        'market_cap_raw': item.get('market_cap_raw'),
        'quote_state': item.get('quote_state'),
        'has_traded': item.get('has_traded'),
        'market_data_as_of': item.get('market_data_as_of'),
    }


def fetch_market_ticker_with_retry(
    ticker: str,
    *,
    heartbeat: Any = None,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Fetch one ticker with bounded retries without aborting the whole snapshot."""
    attempts: list[dict[str, Any]] = []
    last_error: str | None = None
    for attempt in range(1, 4):
        try:
            market = fetch_market_ticker(ticker, heartbeat=heartbeat)
            attempts.append({'attempt': attempt, 'success': True})
            market['market_data_attempts'] = attempts
            return market, None
        except WorkflowInterrupted:
            raise
        except Exception as exc:
            last_error = repr(exc)
            attempts.append({
                'attempt': attempt,
                'success': False,
                'error': last_error,
            })
            if attempt < 3:
                time.sleep(30 * (2 ** (attempt - 1)))

    return {
        'ticker': ticker,
        'current_price': None,
        'market_cap_raw': None,
        'quote_state': None,
        'has_traded': None,
        'market_data_as_of': None,
        'market_data_attempts': attempts,
        'market_data_error': last_error,
    }, {
        'ticker': ticker,
        'error_code': 'MARKET_DATA_UNAVAILABLE',
        'error_message': last_error,
        'attempts': attempts,
    }


def send_notification(message: str) -> tuple[bool, str]:
    """D-05: Muse delivery replaces Telegram/Hermes sends. Payloads are
    written to the run delivery directory (scripts/delivery.py); success
    only on a verified write, skipped delivery is a failure with the
    reason preserved (PRD Phase 12)."""
    from scripts.delivery import send_delivery
    return send_delivery(message)


def valuation_command_args(ticker: str) -> list[str]:
    # D-03: the valuation child is the dashboard-engine adapter
    # (scripts/valuation_adapter.py), invoked as a subprocess so the
    # timeout / process-group / heartbeat logic below works unchanged.
    # The placeholder company_valuation_score skill is never invoked.
    return [sys.executable, '-m', 'scripts.valuation_adapter', ticker]


def terminate_process_tree(proc: subprocess.Popen[str]) -> None:
    """Terminate the child process group, escalating after a bounded grace period."""
    if proc.poll() is not None:
        return
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    except Exception:
        proc.terminate()
    try:
        proc.wait(timeout=VALUATION_TERMINATE_GRACE_SECONDS)
        return
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        return
    except Exception:
        proc.kill()
    try:
        proc.wait(timeout=VALUATION_TERMINATE_GRACE_SECONDS)
    except subprocess.TimeoutExpired:
        return


def bounded_communicate_after_termination(proc: subprocess.Popen[str]) -> tuple[str, str]:
    try:
        stdout, stderr = proc.communicate(timeout=VALUATION_TERMINATE_GRACE_SECONDS)
        return stdout or '', stderr or ''
    except subprocess.TimeoutExpired as exc:
        stdout = exc.output.decode(errors='replace') if isinstance(exc.output, bytes) else (exc.output or '')
        stderr = exc.stderr.decode(errors='replace') if isinstance(exc.stderr, bytes) else (exc.stderr or '')
        return stdout, stderr


def run_valuation_process(
    ticker: str,
    *,
    timeout_seconds: int = VALUATION_TIMEOUT_SECONDS,
    heartbeat_seconds: int = VALUATION_HEARTBEAT_SECONDS,
    heartbeat: Any = None,
    popen_factory: Any = subprocess.Popen,
) -> dict[str, Any]:
    """Run one valuation with heartbeat callbacks and a hard wall-clock timeout."""
    started_at = now_iso()
    started_monotonic = time.monotonic()
    proc = popen_factory(
        valuation_command_args(ticker),
        cwd=str(REPO_ROOT),
        env=VAL_ENV,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    stdout = ''
    stderr = ''
    timed_out = False
    try:
        if heartbeat:
            heartbeat(proc.pid)
        while True:
            if SHUTDOWN_REQUESTED:
                raise WorkflowInterrupted('shutdown requested')
            elapsed = time.monotonic() - started_monotonic
            remaining = timeout_seconds - elapsed
            if remaining <= 0:
                timed_out = True
                break
            try:
                stdout, stderr = proc.communicate(timeout=min(heartbeat_seconds, remaining))
                break
            except subprocess.TimeoutExpired:
                if heartbeat:
                    heartbeat(proc.pid)
    except WorkflowInterrupted:
        terminate_process_tree(proc)
        bounded_communicate_after_termination(proc)
        raise
    except BaseException:
        terminate_process_tree(proc)
        bounded_communicate_after_termination(proc)
        raise

    if timed_out:
        terminate_process_tree(proc)
        stdout, stderr = bounded_communicate_after_termination(proc)

    ended_at = now_iso()
    output = (stdout or '') + (('\n' + stderr) if stderr else '')
    return {
        'ticker': ticker,
        'exit_code': proc.returncode,
        'timed_out': timed_out,
        'started_at': started_at,
        'ended_at': ended_at,
        'elapsed_seconds': round(time.monotonic() - started_monotonic, 6),
        'timeout_seconds': timeout_seconds,
        'child_pid': proc.pid,
        'stdout_tail': (stdout or '')[-SUBPROCESS_OUTPUT_TAIL_CHARS:],
        'stderr_tail': (stderr or '')[-SUBPROCESS_OUTPUT_TAIL_CHARS:],
        'output': output,
    }


def set_current_progress(
    scratch_obj: dict[str, Any],
    scratch_path: Path,
    *,
    ticker: str,
    rank: Any,
    ticker_index: int,
    ticker_total: int,
    started_at: str,
    previous_run_id: str | None,
    child_pid: int | None,
) -> None:
    refreshes = scratch_obj.get('valuation_refreshes') or []
    succeeded = sum(1 for item in refreshes if item.get('success'))
    timed_out = sum(1 for item in refreshes if item.get('error_code') == 'VALUATION_REFRESH_TIMEOUT')
    failed = len(refreshes) - succeeded - timed_out
    scratch_obj['progress'] = {
        'phase': 'valuation',
        'current_ticker': ticker,
        'current_rank': rank,
        'ticker_index': ticker_index,
        'ticker_total': ticker_total,
        'previous_run_id': previous_run_id,
        'started_at': started_at,
        'last_heartbeat_at': now_iso(),
        'timeout_seconds': VALUATION_TIMEOUT_SECONDS,
        'child_pid': child_pid,
        'child_process_state': 'running' if child_pid is not None else 'starting',
        'valuation_completed': succeeded,
        'valuation_failed': failed,
        'valuation_timed_out': timed_out,
        'valuation_in_flight': 1,
    }
    atomic_write_json(scratch_path, scratch_obj)


def clear_current_progress(scratch_obj: dict[str, Any]) -> None:
    progress = scratch_obj.setdefault('progress', {})
    refreshes = scratch_obj.get('valuation_refreshes') or []
    succeeded = sum(1 for item in refreshes if item.get('success'))
    timed_out = sum(1 for item in refreshes if item.get('error_code') == 'VALUATION_REFRESH_TIMEOUT')
    failed = len(refreshes) - succeeded - timed_out
    progress.update({
        'phase': None,
        'current_ticker': None,
        'current_rank': None,
        'ticker_index': None,
        'started_at': None,
        'last_heartbeat_at': now_iso(),
        'child_pid': None,
        'child_process_state': None,
        'valuation_completed': succeeded,
        'valuation_failed': failed,
        'valuation_timed_out': timed_out,
        'valuation_in_flight': 0,
        'market_in_flight': 0,
        'technical_in_flight': 0,
    })


def checkpoint_phase(scratch_obj: dict[str, Any], scratch_path: Path, phase: str) -> None:
    clear_current_progress(scratch_obj)
    scratch_obj['progress']['phase'] = phase
    scratch_obj['progress']['last_heartbeat_at'] = now_iso()
    atomic_write_json(scratch_path, scratch_obj)


def set_market_progress(
    scratch_obj: dict[str, Any],
    scratch_path: Path,
    *,
    ticker: str,
    rank: Any,
    ticker_index: int,
    ticker_total: int,
    started_at: str,
    child_pid: int | None,
    completed: int,
    failed: int,
    in_flight: bool = True,
) -> None:
    """Persist market-data progress before and while an external lookup runs."""
    scratch_obj['progress'] = {
        'phase': 'market_data',
        'current_ticker': ticker,
        'current_rank': rank,
        'ticker_index': ticker_index,
        'ticker_total': ticker_total,
        'started_at': started_at,
        'last_heartbeat_at': now_iso(),
        'timeout_seconds': MARKET_TIMEOUT_SECONDS,
        'child_pid': child_pid,
        'child_process_state': (
            'running' if child_pid is not None else 'starting' if in_flight else 'complete'
        ),
        'market_completed': completed,
        'market_failed': failed,
        'market_in_flight': int(in_flight),
        'valuation_completed': 0,
        'valuation_failed': 0,
        'valuation_timed_out': 0,
        'valuation_in_flight': 0,
    }
    atomic_write_json(scratch_path, scratch_obj)


def set_technical_progress(
    scratch_obj: dict[str, Any],
    scratch_path: Path,
    *,
    ticker: str,
    rank: Any,
    ticker_index: int,
    ticker_total: int,
    started_at: str,
    child_pid: int | None,
) -> None:
    completed = len(scratch_obj.get('technical_analysis') or [])
    failed = sum(
        1 for item in (scratch_obj.get('technical_analysis') or [])
        if item.get('error_code') is not None
    )
    scratch_obj['progress'] = {
        'phase': 'technical_analysis',
        'current_ticker': ticker,
        'current_rank': rank,
        'ticker_index': ticker_index,
        'ticker_total': ticker_total,
        'started_at': started_at,
        'last_heartbeat_at': now_iso(),
        'timeout_seconds': 600,
        'child_pid': child_pid,
        'child_process_state': 'running' if child_pid is not None else 'starting',
        'technical_completed': completed,
        'technical_succeeded': completed - failed,
        'technical_failed': failed,
        'technical_in_flight': 1,
    }
    atomic_write_json(scratch_path, scratch_obj)


def upsert_canonical_record(log_path: Path, record: dict[str, Any]) -> None:
    run_id = record.get('workflow_run_id')
    if not run_id:
        raise RuntimeError('cannot finalize without workflow_run_id')
    lines: list[dict[str, Any]] = []
    record_to_write = record
    if log_path.exists():
        for line_no, line in enumerate(log_path.read_text(encoding='utf-8').splitlines(), 1):
            if not line.strip():
                continue
            obj = json.loads(line)
            existing_id = obj.get('workflow_run_id')
            if not existing_id:
                raise RuntimeError(f'empty workflow_run_id on line {line_no}')
            if existing_id == run_id:
                existing_is_complete = (
                    obj.get('status') in {'success', 'partial_success', 'SUCCESS'}
                    and not obj.get('failure')
                    and isinstance(obj.get('summary'), dict)
                )
                if existing_is_complete and record.get('failure'):
                    record_to_write = obj
                continue
            lines.append(obj)
    lines.append(record_to_write)
    ids = [item['workflow_run_id'] for item in lines]
    if len(ids) != len(set(ids)):
        raise RuntimeError('duplicate workflow_run_id in canonical log')
    atomic_write_text(
        log_path,
        ''.join(json.dumps(item, ensure_ascii=False, separators=(',', ':')) + '\n' for item in lines),
    )
    reread = [
        json.loads(line)
        for line in log_path.read_text(encoding='utf-8').splitlines()
        if line.strip()
    ]
    if sum(1 for item in reread if item.get('workflow_run_id') == run_id) != 1:
        raise RuntimeError('canonical log verification failed')


def finalize_record(
    scratch_obj: dict[str, Any],
    scratch_path: Path,
    log_path: Path,
    *,
    status: str,
    failure: dict[str, Any] | None = None,
) -> None:
    """Persist one terminal record and remove scratch only after verified upsert."""
    ended_at = now_iso()
    in_flight = dict(scratch_obj.get('progress') or {})
    refreshes = scratch_obj.get('valuation_refreshes') or []
    succeeded = sum(1 for item in refreshes if item.get('success'))
    timed_out = sum(1 for item in refreshes if item.get('error_code') == 'VALUATION_REFRESH_TIMEOUT')
    failed = sum(
        1 for item in refreshes
        if not item.get('success') and item.get('error_code') != 'VALUATION_REFRESH_TIMEOUT'
    )
    scratch_obj['ended_at'] = ended_at
    scratch_obj['status'] = status
    if failure:
        scratch_obj['failure'] = {
            **failure,
            'failure_stage': in_flight.get('phase') or failure.get('failure_stage'),
            'current_ticker': in_flight.get('current_ticker'),
            'current_rank': in_flight.get('current_rank'),
            'last_heartbeat_at': in_flight.get('last_heartbeat_at'),
            'completed_ticker_count': succeeded + failed + timed_out,
            'valuation_succeeded': succeeded,
            'valuation_failed': failed,
            'valuation_timed_out': timed_out,
            'output_path': str(OUTPUT),
            'log_path': str(log_path),
        }
    clear_current_progress(scratch_obj)
    event = 'run_complete' if status in {'success', 'partial_success', 'SUCCESS'} and not failure else 'run_failure'
    scratch_obj.setdefault('events', []).append({
        'event': event,
        'timestamp': ended_at,
        'status': status,
    })
    atomic_write_json(scratch_path, scratch_obj)
    upsert_canonical_record(log_path, scratch_obj)
    scratch_path.unlink(missing_ok=True)


def finalize_active_failure(exc: BaseException) -> str | None:
    """Best-effort outer failure finalization; return a secondary error if any."""
    context = ACTIVE_RUN_CONTEXT
    if context is None or context.get('finalizing'):
        return None
    scratch_obj = context['scratch_obj']
    completed = len(scratch_obj.get('valuation_refreshes') or [])
    terminal_status = 'FAILED'  # D-07: an interrupted run is FAILED (PRD 13.2)
    try:
        finalize_record(
            scratch_obj,
            context['scratch_path'],
            context['log_path'],
            status=terminal_status,
            failure={
                'exception_type': type(exc).__name__,
                'exception_message': str(exc),
                'failure_stage': (scratch_obj.get('progress') or {}).get('phase'),
            },
        )
    except Exception as finalize_exc:
        return repr(finalize_exc)
    return None


def latest_reference(ticker: str, latest_by_ticker: dict[str, list[tuple[datetime, dict[str, Any]]]]) -> dict[str, Any] | None:
    entries = latest_by_ticker.get(ticker)
    if not entries:
        return None
    return normalize_reference(entries[-1][1])


def classify_refresh_result(
    result: dict[str, Any],
    pre_run_id: str | None,
    verified_ref: dict[str, Any] | None,
    reuse_cutoff: datetime | None = None,
) -> tuple[bool, str | None]:
    updated = bool(
        verified_ref
        and verified_ref.get('run_id')
        and verified_ref.get('run_id') != pre_run_id
    )
    reused = False
    if (
        reuse_cutoff is not None
        and verified_ref
        and verified_ref.get('run_id')
        and verified_ref.get('run_id') == pre_run_id
    ):
        # D-13: in reuse mode the adapter child exits 0 in verify mode
        # on a pre-seeded record, so the verified reference IS the
        # pre-run record. The original new-record proof (run_id must
        # differ) is replaced — only in this branch — by a freshness
        # proof: the record's completion timestamp must lie inside the
        # reuse window (at/after the same cutoff the child verified
        # against). valid_reference below is still enforced, and with
        # reuse_cutoff None this branch never fires.
        ts = parse_dt(verified_ref.get('valuation_last_run_at'))
        reused = ts is not None and ts >= reuse_cutoff
    success = bool(
        not result.get('timed_out')
        and result.get('exit_code') == 0
        and verified_ref
        and verified_ref.get('run_id')
        and (updated or reused)
        and valid_reference(verified_ref)
    )
    if result.get('timed_out'):
        return False, 'VALUATION_REFRESH_TIMEOUT'
    if result.get('exit_code') != 0:
        return False, 'VALUATION_REFRESH_FAILED'
    if not success:
        return False, 'VALUATION_REFERENCE_NOT_UPDATED'
    return True, None


def select_output_reference(
    refresh_succeeded: bool,
    latest_reference_after_run: dict[str, Any] | None,
    prior_valid_reference: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Never promote a post-run reference after a failed or timed-out refresh."""
    if refresh_succeeded and latest_reference_after_run and valid_reference(latest_reference_after_run):
        return latest_reference_after_run
    if prior_valid_reference and valid_reference(prior_valid_reference):
        return prior_valid_reference
    return None


def safe_numeric(v: Any) -> float | None:
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _derived_from(bs: float | None, vs: float | None, gav: float | None) -> float | None:
    """D-03: derived_score = Final = 0.5*Business + 0.25*Value +
    0.25*GAV-Code (all 0-100). Null when any component is missing —
    never zero-filled at the orchestrator level."""
    if bs is None or vs is None or gav is None:
        return None
    return round(0.5 * bs + 0.25 * vs + 0.25 * gav, 12)


def build_record(row: dict[str, Any], market: dict[str, Any], ref: dict[str, Any], plan_item: dict[str, Any]) -> dict[str, Any]:
    bq = ref['business_quality']
    val = ref['valuation']
    stored_price = plan_item.get('stored_price')
    latest_price = plan_item.get('latest_price')
    rec = {
        'rank': row['rank'],
        'ticker': row['ticker'],
        'name': row['name'],
        'sector': row['sector'],
        'market_cap': fmt_cap(market.get('market_cap_raw')),
        'current_price': latest_price if latest_price is not None else stored_price,
        'market_data_as_of': market.get('market_data_as_of'),
        'business_quality': {
            'score': bq.get('score'),
            'grade': bq.get('grade'),
            'confidence': bq.get('confidence'),
        },
        'valuation': {
            'score': val.get('score'),
            'grade': val.get('grade'),
            'confidence': val.get('confidence'),
        },
        'target_prices': ref['target_prices'],
        'run_id': ref['run_id'],
        'valuation_last_run_at': ref['valuation_last_run_at'],
    }
    bs = safe_numeric(rec['business_quality']['score'])
    vs = safe_numeric(rec['valuation']['score'])
    gav = safe_numeric(bq.get('gav_code'))
    rec['gav_code'] = gav
    rec['derived_score'] = _derived_from(bs, vs, gav)
    return rec


def d14_unscored_eligible(refresh: dict[str, Any] | None) -> bool:
    """D-14 gate: a refresh that ran and failed terminally (the engine's
    fail-closed verdict — no usable 10-K, or Business/Value missing) may
    become a structured unscored output row. A timed-out refresh may
    not: a timeout is transient, not a verdict, and stays fail-closed.
    A missing or successful refresh never reaches the unscored branch."""
    return (
        refresh is not None
        and not refresh.get('success')
        and refresh.get('error_code') != 'VALUATION_REFRESH_TIMEOUT'
    )


def build_unscored_record(row: dict[str, Any], market: dict[str, Any], reason: Any) -> dict[str, Any]:
    """D-14: structured unscored output row — the build_record schema
    with every score null, the fail-closed reason preserved, and an
    explicit unscored marker (the D-17 pattern from the wheel). Never
    ranked: derived_score is None and Top-10 selection requires a
    number. Market fields still come from this run's market data."""
    return {
        'rank': row['rank'],
        'ticker': row['ticker'],
        'name': row['name'],
        'sector': row['sector'],
        'market_cap': fmt_cap(market.get('market_cap_raw')),
        'current_price': market.get('current_price'),
        'market_data_as_of': market.get('market_data_as_of'),
        'business_quality': {'score': None, 'grade': None, 'confidence': None},
        'valuation': {'score': None, 'grade': None, 'confidence': None},
        'target_prices': None,
        'run_id': None,
        'valuation_last_run_at': None,
        'gav_code': None,
        'derived_score': None,
        'unscored': True,
        'unscored_reason': reason,
    }


def build_valuation_notification(record: dict[str, Any], reasons: list[str]) -> str:
    return (
        '✅ Mag-500 valuation refreshed\n\n'
        f"Ticker: {record['ticker']}\n"
        f"Rank: {record['rank']}\n"
        f"Run ID: {record['run_id']}\n"
        f"Business Quality: {record['business_quality']['score']:.2f} ({record['business_quality']['grade']})\n"
        f"Valuation: {record['valuation']['score']:.2f} ({record['valuation']['grade']})\n"
        f"Derived Score: {record['derived_score']:.2f}\n"
        f"Refresh Reason: {', '.join(reasons)}"
    )


def main() -> int:
    global ACTIVE_RUN_CONTEXT
    RUN_ID = f"MAG500-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{secrets.token_hex(3)}"
    RUNS.mkdir(parents=True, exist_ok=True)
    scratch = RUNS / f'{RUN_ID}.json'
    market_file = RUNS / f'{RUN_ID}-market.json'
    plan_file = RUNS / f'{RUN_ID}-plan.json'
    valuation_results_file = RUNS / f'{RUN_ID}-valuation-results.json'
    top10_file = RUNS / f'{RUN_ID}-top10.json'
    tech_file = RUNS / f'{RUN_ID}-technical.json'

    started_at = now_iso()
    scratch_obj: dict[str, Any] = {
        'workflow_run_id': RUN_ID,
        'started_at': started_at,
        'status': 'running',
        'paths': {
            'input': str(INPUT),
            'output': str(OUTPUT),
            'history': str(HISTORY),
            'log': str(LOG),
            'market': str(market_file),
            'plan': str(plan_file),
            'valuation_results': str(valuation_results_file),
            'top10': str(top10_file),
            'technical': str(tech_file),
        },
        'runtime': {
            'delivery': 'claude_artifacts',
            'valuation_workers': VALUATION_WORKERS,
            'valuation_methodology': 'dashboard-v5.5+gav-code',
            'orchestrator_pid': os.getpid(),
            'market_timeout_seconds': MARKET_TIMEOUT_SECONDS,
            'market_heartbeat_seconds': MARKET_HEARTBEAT_SECONDS,
            'valuation_timeout_seconds': VALUATION_TIMEOUT_SECONDS,
            'valuation_heartbeat_seconds': VALUATION_HEARTBEAT_SECONDS,
        },
        'progress': {
            'phase': 'initialization',
            'current_ticker': None,
            'current_rank': None,
            'ticker_index': None,
            'ticker_total': None,
            'started_at': started_at,
            'last_heartbeat_at': started_at,
            'child_pid': None,
        },
        'ticker_details': [],
        'valuation_refreshes': [],
        'technical_analysis': [],
        'delivery_notifications': [],
        'output_writes': [],
        'events': [{'event': 'run_start', 'timestamp': started_at}],
    }
    atomic_write_json(scratch, scratch_obj)
    ACTIVE_RUN_CONTEXT = {
        'scratch_obj': scratch_obj,
        'scratch_path': scratch,
        'log_path': LOG,
    }
    checkpoint_phase(scratch_obj, scratch, 'input_validation')
    rows = normalize_input_rows()
    scratch_obj['progress']['ticker_total'] = len(rows)
    checkpoint_phase(scratch_obj, scratch, 'output_validation')
    output_rows = load_output_rows()
    checkpoint_phase(scratch_obj, scratch, 'history_validation')
    hist_entries, latest_by_ticker = load_reference_entries()

    # D-02 (design A): market data is fetched BATCHED for the whole
    # universe up front (quotes in chunks of 100, fundamentals in chunks
    # of 20 — never one MCP session per ticker). The per-ticker loop
    # below only records progress, events, and artifacts in input order.
    tickers = [row['ticker'] for row in rows]
    checkpoint_phase(scratch_obj, scratch, 'market_data')
    _batched_market: dict[str, tuple[dict[str, Any], dict[str, Any] | None]] = {}
    try:
        from scripts.robinhood_transport import fetch_market_data as _fetch_batched
        _batch = _fetch_batched(tickers)
    except Exception as _batch_exc:  # transport-level failure: every
        # ticker is marked unavailable below; the run finalizes FAILED
        # (market failures count toward terminal status, PRD 13.7).
        _batch = {}
        scratch_obj['events'].append({
            'event': 'market_data_batch_failure', 'timestamp': now_iso(),
            'error_message': repr(_batch_exc),
        })
    for _t in tickers:
        _m = _batch.get(_t) or {
            'ticker': _t, 'current_price': None, 'market_cap_raw': None,
            'quote_state': None, 'has_traded': None,
            'market_data_as_of': None,
            'market_data_attempts': [{'attempt': 1, 'success': False,
                                      'error': 'not returned by batched fetch'}],
            'market_data_error': 'MARKET_DATA_UNAVAILABLE',
        }
        _failure = None
        if _m.get('market_data_error'):
            _failure = {
                'ticker': _t, 'error_code': 'MARKET_DATA_UNAVAILABLE',
                'error_message': str(_m.get('market_data_error')),
                'attempts': _m.get('market_data_attempts') or [],
            }
        _batched_market[_t] = (_m, _failure)
    market_results: list[dict[str, Any]] = []
    market_failures: list[dict[str, Any]] = []
    for market_index, row in enumerate(rows, 1):
        raise_if_shutdown()
        ticker = row['ticker']
        market_started_at = now_iso()
        set_market_progress(
            scratch_obj,
            scratch,
            ticker=ticker,
            rank=row['rank'],
            ticker_index=market_index,
            ticker_total=len(rows),
            started_at=market_started_at,
            child_pid=None,
            completed=len(market_results) - len(market_failures),
            failed=len(market_failures),
        )

        def market_heartbeat(child_pid: int) -> None:
            set_market_progress(
                scratch_obj,
                scratch,
                ticker=ticker,
                rank=row['rank'],
                ticker_index=market_index,
                ticker_total=len(rows),
                started_at=market_started_at,
                child_pid=child_pid,
                completed=len(market_results) - len(market_failures),
                failed=len(market_failures),
            )

        market, failure = _batched_market[ticker]
        market_results.append(market)
        if failure:
            market_failures.append(failure)
        scratch_obj['events'].append({
            'event': 'market_data_failure' if failure else 'market_data_success',
            'timestamp': now_iso(),
            'ticker': ticker,
            'rank': row['rank'],
            'ticker_index': market_index,
            'ticker_total': len(rows),
            'error_code': failure.get('error_code') if failure else None,
            'error_message': failure.get('error_message') if failure else None,
        })
        atomic_write_json(market_file, market_results)
        set_market_progress(
            scratch_obj,
            scratch,
            ticker=ticker,
            rank=row['rank'],
            ticker_index=market_index,
            ticker_total=len(rows),
            started_at=market_started_at,
            child_pid=None,
            completed=len(market_results) - len(market_failures),
            failed=len(market_failures),
            in_flight=False,
        )
    atomic_write_json(market_file, market_results)

    market_by_ticker = {x['ticker']: x for x in market_results}
    output_by_ticker = {str(x.get('ticker', '')).upper(): x for x in output_rows}

    checkpoint_phase(scratch_obj, scratch, 'planning')
    scratch_obj['progress']['ticker_total'] = len(rows)
    scratch_obj['events'].extend([
        {'event': 'input_validated', 'timestamp': now_iso(), 'count': len(rows)},
        {'event': 'output_loaded', 'timestamp': now_iso(), 'count': len(output_rows)},
        {'event': 'ticker_market_data', 'timestamp': now_iso(), 'count': len(market_results)},
    ])
    for failure in market_failures:
        scratch_obj['events'].append({
            'event': 'market_data_failure',
            'timestamp': now_iso(),
            **failure,
        })

    # Direct valuation mode: every input ticker is sent through the
    # dashboard-engine valuation adapter. No age, price-drift, confidence,
    # missing-field, run-id, or market-cap decider is used.
    plan: list[dict[str, Any]] = []
    prior_reference_by_ticker: dict[str, dict[str, Any]] = {}
    for row in rows:
        ticker = row['ticker']
        old = output_by_ticker.get(ticker)
        market = market_by_ticker.get(ticker, {})
        ref = latest_reference(ticker, latest_by_ticker)
        if ref and valid_reference(ref):
            prior_reference_by_ticker[ticker] = ref
        latest_price = market.get('current_price')
        market_cap = fmt_cap(market.get('market_cap_raw'))
        plan_item = {
            'ticker': ticker,
            'rank': row['rank'],
            'previous_run_id': old.get('run_id') if old else None,
            'previous_history_run_id': ref.get('run_id') if ref else None,
            'valuation_last_run_at': None,
            'stored_price': old.get('current_price') if old else None,
            'latest_price': latest_price,
            'market_cap': market_cap,
            'market_data_as_of': market.get('market_data_as_of'),
            'category': 'DIRECT',
            'reasons': ['DIRECT_DASHBOARD_ENGINE_VALUATION'],
            'refresh_command': 'scripts.valuation_adapter',
            'error_code': None,
            'error_message': None,
        }
        scratch_obj['ticker_details'].append(plan_item)
        plan.append(plan_item)

    atomic_write_json(plan_file, plan)
    atomic_write_json(scratch, scratch_obj)

    # D-04 (design B): parallel valuation prefetch. With workers > 1 the
    # evaluations run NOW on a bounded process pool (per-worker EDGAR
    # cache dirs, shared SEC rate limiter <=8 req/s); each successful
    # evaluation appends its history record immediately. The sequential
    # Phase 6 loop below then invokes the adapter child in verify mode
    # (MAG500_PREFETCHED) — it exits 0 on the fresh prefetched record
    # without re-evaluating, so per-ticker verification, heartbeat,
    # notification, and rank-order assembly are exactly the copied
    # logic. A ticker whose prefetch failed is evaluated for real by
    # its child (a second, sequential chance).
    # D-13: the in-process prefetch reads MAG500_PREFETCH_REUSE_HOURS
    # from this process's environment itself (see valuation_adapter),
    # so with reuse on it skips tickers whose valid history record is
    # inside the window; the moved-back cutoff below then lets the
    # Phase 6 children verify those same records as fresh.
    reuse_cutoff_dt: datetime | None = None
    if VALUATION_WORKERS > 1 and plan:
        checkpoint_phase(scratch_obj, scratch, 'valuation_prefetch')
        VAL_ENV['MAG500_PREFETCHED'] = '1'
        # D-13: reuse on -> cutoff = now - window (pre-seeded records
        # verify as fresh); reuse off -> cutoff = now (run start).
        _cutoff_iso, reuse_cutoff_dt = _prefetch_cutoff()
        VAL_ENV['MAG500_PREFETCH_CUTOFF'] = _cutoff_iso
        from scripts.valuation_adapter import prefetch_valuations as _prefetch

        def _prefetch_cb(_ticker: str, _diag: dict[str, Any]) -> None:
            scratch_obj['events'].append({
                'event': 'valuation_prefetch_success' if _diag.get('success')
                         else 'valuation_prefetch_failure',
                'timestamp': now_iso(), 'ticker': _ticker,
                'reason': _diag.get('reason'), 'run_id': _diag.get('run_id'),
            })
            atomic_write_json(scratch, scratch_obj)

        _prefetch_results = _prefetch(
            [item['ticker'] for item in plan], HISTORY,
            workers=VALUATION_WORKERS, on_complete=_prefetch_cb)
        scratch_obj['valuation_prefetch'] = {
            t: {'success': bool(d.get('success')), 'reason': d.get('reason'),
                'run_id': d.get('run_id')}
            for t, d in _prefetch_results.items()
        }
        atomic_write_json(scratch, scratch_obj)

    # Execute valuation refreshes.
    valuation_results: list[dict[str, Any]] = []
    for ticker_index, item in enumerate(plan, 1):
        raise_if_shutdown()
        ticker = item['ticker']
        out_path = RUNS / f'{RUN_ID}-{ticker}.valuation.out'
        refresh_started_at = now_iso()
        set_current_progress(
            scratch_obj,
            scratch,
            ticker=ticker,
            rank=item['rank'],
            ticker_index=ticker_index,
            ticker_total=len(plan),
            started_at=refresh_started_at,
            previous_run_id=item.get('previous_history_run_id'),
            child_pid=None,
        )
        scratch_obj['events'].append({
            'event': 'valuation_refresh_start',
            'timestamp': refresh_started_at,
            'workflow_run_id': RUN_ID,
            'ticker': ticker,
            'rank': item['rank'],
            'ticker_index': ticker_index,
            'ticker_total': len(plan),
            'previous_run_id': item.get('previous_history_run_id'),
            'timeout_seconds': VALUATION_TIMEOUT_SECONDS,
            'phase': 'valuation',
            'child_pid': None,
        })
        atomic_write_json(scratch, scratch_obj)

        def heartbeat(child_pid: int) -> None:
            set_current_progress(
                scratch_obj,
                scratch,
                ticker=ticker,
                rank=item['rank'],
                ticker_index=ticker_index,
                ticker_total=len(plan),
                started_at=refresh_started_at,
                previous_run_id=item.get('previous_history_run_id'),
                child_pid=child_pid,
            )

        attempts: list[dict[str, Any]] = []
        result: dict[str, Any] = {}
        max_attempts = 3
        for attempt in range(1, max_attempts + 1):
            try:
                process_result = run_valuation_process(ticker, heartbeat=heartbeat)
            except WorkflowInterrupted:
                raise
            except Exception as exc:
                process_result = {
                    'ticker': ticker,
                    'exit_code': None,
                    'timed_out': False,
                    'started_at': refresh_started_at,
                    'ended_at': now_iso(),
                    'elapsed_seconds': 0.0,
                    'timeout_seconds': VALUATION_TIMEOUT_SECONDS,
                    'child_pid': None,
                    'stdout_tail': '',
                    'stderr_tail': repr(exc)[-SUBPROCESS_OUTPUT_TAIL_CHARS:],
                    'output': repr(exc),
                }
            attempts.append({
                'attempt': attempt,
                'exit_code': process_result.get('exit_code'),
                'timed_out': process_result.get('timed_out', False),
                'started_at': process_result.get('started_at'),
                'ended_at': process_result.get('ended_at'),
                'elapsed_seconds': process_result.get('elapsed_seconds'),
                'timeout_seconds': process_result.get('timeout_seconds'),
                'stdout_tail': process_result.get('stdout_tail'),
                'stderr_tail': process_result.get('stderr_tail'),
            })
            result = process_result
            if process_result.get('exit_code') == 0 or process_result.get('timed_out'):
                break
            if attempt < max_attempts:
                time.sleep(30 * (2 ** (attempt - 1)))

        atomic_write_text(out_path, str(result.get('output') or ''))
        result['rank'] = item['rank']
        result['attempts'] = attempts
        result['duration_ms'] = int(sum(float(a.get('elapsed_seconds') or 0) for a in attempts) * 1000)
        result['output_path'] = str(out_path)
        result['error_summary'] = None if result.get('exit_code') == 0 else (
            (result.get('stderr_tail') or result.get('stdout_tail') or '')[-SUBPROCESS_OUTPUT_TAIL_CHARS:]
        )
        valuation_results.append(result)

        # Always reload the authoritative history after the child reaches a terminal state.
        hist_entries2, latest_by_ticker2 = load_reference_entries()
        latest_by_ticker.clear()
        latest_by_ticker.update(latest_by_ticker2)
        hist_entries[:] = hist_entries2
        verified_ref = latest_reference(ticker, latest_by_ticker)
        success, error_code = classify_refresh_result(
            result,
            item.get('previous_history_run_id'),
            verified_ref,
            reuse_cutoff=reuse_cutoff_dt,
        )
        value = {
            'ticker': ticker,
            'rank': item['rank'],
            'ticker_index': ticker_index,
            'ticker_total': len(plan),
            'reasons': item['reasons'],
            'command': item['refresh_command'],
            'category': item['category'],
            'exit_code': result.get('exit_code'),
            'pre_run_id': item.get('previous_history_run_id'),
            'new_run_id': verified_ref.get('run_id') if verified_ref else None,
            'success': success,
            'error_code': error_code,
            'error_message': result.get('error_summary'),
            'started_at': refresh_started_at,
            'ended_at': result.get('ended_at'),
            'elapsed_seconds': result.get('elapsed_seconds'),
            'duration_ms': result['duration_ms'],
            'timeout_seconds': VALUATION_TIMEOUT_SECONDS,
            'output_path': str(out_path),
            'stdout_tail': result.get('stdout_tail'),
            'stderr_tail': result.get('stderr_tail'),
            'attempts': attempts,
        }
        scratch_obj['valuation_refreshes'].append(value)
        terminal_event = (
            'valuation_refresh_success' if success
            else 'valuation_refresh_timeout' if error_code == 'VALUATION_REFRESH_TIMEOUT'
            else 'valuation_refresh_failure'
        )
        scratch_obj['events'].append({'event': terminal_event, 'timestamp': now_iso(), **value})
        clear_current_progress(scratch_obj)
        if success and verified_ref:
            ticker_market = market_by_ticker[ticker]
            record = build_record(
                next(row for row in rows if row['ticker'] == ticker),
                ticker_market,
                verified_ref,
                item,
            )
            msg = build_valuation_notification(record, item['reasons'])
            sent, raw = send_notification(msg)
            note = {
                'type': 'valuation_refresh',
                'ticker': ticker,
                'run_id': record['run_id'],
                'timestamp': now_iso(),
                'success': sent,
                'error_code': None if sent else 'DELIVERY_SEND_FAILED',
                'result': raw,
            }
            scratch_obj['delivery_notifications'].append(note)
            scratch_obj['events'].append({'event': 'delivery_send_success' if sent else 'delivery_send_failure', 'timestamp': now_iso(), **note})
        atomic_write_json(scratch, scratch_obj)
    atomic_write_json(valuation_results_file, valuation_results)

    # Build final output (use refreshed refs when successful, otherwise the prior valid reference).
    checkpoint_phase(scratch_obj, scratch, 'output_rebuild')
    final_records: list[dict[str, Any]] = []
    refresh_success_by_ticker = {x['ticker']: x for x in scratch_obj['valuation_refreshes'] if x.get('success')}
    refresh_by_ticker = {x['ticker']: x for x in scratch_obj['valuation_refreshes']}
    for row in rows:
        ticker = row['ticker']
        market = market_by_ticker.get(ticker, {})
        old = output_by_ticker.get(ticker)
        ref = latest_reference(ticker, latest_by_ticker)
        selected_ref = select_output_reference(
            ticker in refresh_success_by_ticker,
            ref,
            prior_reference_by_ticker.get(ticker),
        )
        if selected_ref:
            plan_item = next(x for x in scratch_obj['ticker_details'] if x['ticker'] == ticker)
            record = build_record(row, market, selected_ref, plan_item)
        elif old:
            record = dict(old)
            record['market_cap'] = fmt_cap(market.get('market_cap_raw')) or old.get('market_cap')
            if market.get('current_price') is not None:
                record['current_price'] = market.get('current_price')
            record['market_data_as_of'] = market.get('market_data_as_of') or old.get('market_data_as_of')
            bs = safe_numeric((record.get('business_quality') or {}).get('score'))
            vs = safe_numeric((record.get('valuation') or {}).get('score'))
            gav = safe_numeric((record.get('business_quality') or {}).get('gav_code'))
            if gav is None:
                gav = safe_numeric(record.get('gav_code'))
            record['derived_score'] = _derived_from(bs, vs, gav)
        else:
            # D-14: no valid reference and no prior output record. When
            # this run's refresh failed terminally, emit a structured
            # unscored row (reason preserved) instead of aborting the
            # whole rebuild; otherwise stay fail-closed.
            refresh = refresh_by_ticker.get(ticker)
            if not d14_unscored_eligible(refresh):
                raise RuntimeError(f'No valid record available for {ticker}')
            reason = refresh.get('error_message') or refresh.get('error_code') or 'valuation_refresh_failed'
            record = build_unscored_record(row, market, reason)
            scratch_obj['events'].append({
                'event': 'output_unscored_row', 'timestamp': now_iso(),
                'ticker': ticker, 'rank': row['rank'], 'reason': reason,
            })
        final_records.append(record)

    final_records.sort(key=lambda x: x['rank'])
    assert len({x['rank'] for x in final_records}) == len(final_records)
    assert len({x['ticker'] for x in final_records}) == len(final_records)
    assert all(x['ticker'] in tickers for x in final_records)
    for rec in final_records:
        if rec.get('market_cap') is not None:
            assert str(rec['market_cap']).endswith(('T', 'B'))

    atomic_write_json(OUTPUT, final_records)
    _reread = load_json(OUTPUT)
    if not isinstance(_reread, list) or \
            [x.get('ticker') for x in _reread] != [x['ticker'] for x in final_records]:
        raise RuntimeError('OUTPUT_WRITE_FAILED: canonical output read-back verification failed')
    scratch_obj['output_writes'].append({'timestamp': now_iso(), 'path': str(OUTPUT), 'count': len(final_records), 'success': True, 'readback_verified': True})
    scratch_obj['events'].append({'event': 'output_write_success', 'timestamp': now_iso(), 'path': str(OUTPUT), 'count': len(final_records)})
    atomic_write_json(scratch, scratch_obj)

    # Top 10 selection.
    scored = [x for x in final_records if isinstance(x.get('derived_score'), (int, float))]
    top10 = sorted(
        scored,
        key=lambda x: (-x['derived_score'], -x['business_quality']['score'], -x['valuation']['score'], x['rank']),
    )[:10]
    atomic_write_json(top10_file, [{'ticker': x['ticker'], 'rank': x['rank'], 'derived_score': x['derived_score'], 'business_quality_score': x['business_quality']['score'], 'valuation_score': x['valuation']['score']} for x in top10])
    scratch_obj['events'].append({'event': 'top10_selected', 'timestamp': now_iso(), 'tickers': [x['ticker'] for x in top10]})
    atomic_write_json(scratch, scratch_obj)

    # Technical analysis for the top 10.
    checkpoint_phase(scratch_obj, scratch, 'technical_analysis')
    tech_results: list[dict[str, Any]] = []
    if top10:
        def one_tech(item: dict[str, Any], heartbeat: Any = None) -> dict[str, Any]:
            # D-06 (design C): the copied technical_analysis_recommend
            # package runs DIRECTLY as code on batched Robinhood data
            # (scripts/technical_adapter.py). No Hermes, no model.
            from scripts.technical_adapter import run_technical
            data = run_technical(item['ticker'])
            if not isinstance(data, dict):
                raise ValueError(f'bad technical response for {item["ticker"]}: {data!r}')
            data['rank'] = item['rank']
            data['derived_score'] = item['derived_score']
            return data

        # Batched prefetch for the whole shortlist (quotes 100/call,
        # historicals 10/call); per-ticker on-demand fetch remains as
        # the fallback inside the adapter if this fails.
        try:
            from scripts.technical_adapter import prefetch_technicals
            prefetch_technicals([x['ticker'] for x in top10])
        except Exception as _tech_prefetch_exc:
            scratch_obj['events'].append({
                'event': 'technical_prefetch_failure', 'timestamp': now_iso(),
                'error_message': repr(_tech_prefetch_exc),
            })

        for technical_index, item in enumerate(top10, 1):
            raise_if_shutdown()
            started = time.time()
            technical_started_at = now_iso()
            set_technical_progress(
                scratch_obj,
                scratch,
                ticker=item['ticker'],
                rank=item['rank'],
                ticker_index=technical_index,
                ticker_total=len(top10),
                started_at=technical_started_at,
                child_pid=None,
            )

            def technical_heartbeat(child_pid: int) -> None:
                set_technical_progress(
                    scratch_obj,
                    scratch,
                    ticker=item['ticker'],
                    rank=item['rank'],
                    ticker_index=technical_index,
                    ticker_total=len(top10),
                    started_at=technical_started_at,
                    child_pid=child_pid,
                )

            try:
                result = one_tech(item, heartbeat=technical_heartbeat)
                result.setdefault('status', 'ok')
                result.setdefault('ticker', item['ticker'])
                result.setdefault('score', None)
                result.setdefault('verdict', None)
                result.setdefault('recommendation', {})
                result.setdefault('warnings', [])
                ok = result.get('status') == 'ok'
                rec = {
                    'ticker': item['ticker'],
                    'rank': item['rank'],
                    'derived_score': item['derived_score'],
                    'technical_score': result.get('score'),
                    'technical_verdict': result.get('verdict'),
                    'technical_summary': (result.get('recommendation') or {}).get('summary'),
                    'profile': 'mag-500-direct-code',
                    'robinhood_mcp_used': True,
                    'duration_ms': int((time.time() - started) * 1000),
                    'error_code': None if ok else 'TECHNICAL_ANALYSIS_FAILED',
                    'error_message': None if ok else '; '.join(result.get('warnings') or []),
                }
            except Exception as exc:
                result = {
                    'request_date': now_iso()[:10],
                    'ticker': item['ticker'],
                    'status': 'failed',
                    'warnings': [repr(exc)],
                }
                rec = {
                    'ticker': item['ticker'],
                    'rank': item['rank'],
                    'derived_score': item['derived_score'],
                    'technical_score': None,
                    'technical_verdict': None,
                    'technical_summary': None,
                    'profile': 'mag-500-direct-code',
                    'robinhood_mcp_used': True,
                    'duration_ms': int((time.time() - started) * 1000),
                    'error_code': 'TECHNICAL_ANALYSIS_FAILED',
                    'error_message': repr(exc),
                }
            tech_results.append({'raw': result, 'log': rec})
            scratch_obj['technical_analysis'].append(rec)
            scratch_obj['events'].append({'event': 'technical_analysis_success' if rec['error_code'] is None else 'technical_analysis_failure', 'timestamp': now_iso(), **rec})
            checkpoint_phase(scratch_obj, scratch, 'technical_analysis')
    atomic_write_json(tech_file, [x['raw'] for x in tech_results])

    # Choose final top 2 recommendations.
    positive = {'STRONG_BUY', 'BUY', 'CONDITIONAL_BUY'}
    tech_ok = [x['raw'] for x in tech_results if isinstance(x['raw'].get('score'), (int, float)) and x['raw'].get('status') == 'ok']
    ordered = sorted(
        tech_ok,
        key=lambda x: (0 if x.get('verdict') in positive else 1, -x['score'], -x['derived_score'], x['rank']),
    )
    top2 = ordered[:2]
    scratch_obj['events'].append({'event': 'top2_selected', 'timestamp': now_iso(), 'tickers': [x['ticker'] for x in top2]})
    atomic_write_json(scratch, scratch_obj)

    final_msg = '🏆 Mag-500 Top Recommendations\n'
    for idx, item in enumerate(top2, 1):
        summary = (item.get('recommendation') or {}).get('summary')
        final_msg += (
            f'\n{idx}) {item["ticker"]}\n'
            f'Technical Score: {item["score"]}\n'
            f'Verdict: {item["verdict"]}\n'
            f'Summary: {summary}\n'
            f'v_derived_score: {item["derived_score"]:.2f}\n'
        )
    raise_if_shutdown()
    final_sent, final_raw = send_notification(final_msg)
    final_note = {
        'type': 'final_top2',
        'timestamp': now_iso(),
        'success': final_sent,
        'error_code': None if final_sent else 'DELIVERY_SEND_FAILED',
        'result': final_raw,
    }
    scratch_obj['delivery_notifications'].append(final_note)
    scratch_obj['events'].append({'event': 'delivery_send_success' if final_sent else 'delivery_send_failure', 'timestamp': now_iso(), **final_note})

    ended_at = now_iso()
    success_count = sum(1 for x in scratch_obj['valuation_refreshes'] if x.get('success'))
    timeout_count = sum(1 for x in scratch_obj['valuation_refreshes'] if x.get('error_code') == 'VALUATION_REFRESH_TIMEOUT')
    fail_count = sum(
        1 for x in scratch_obj['valuation_refreshes']
        if not x.get('success') and x.get('error_code') != 'VALUATION_REFRESH_TIMEOUT'
    )
    tech_success = sum(1 for x in scratch_obj['technical_analysis'] if x.get('error_code') is None)
    tech_fail = sum(1 for x in scratch_obj['technical_analysis'] if x.get('error_code') is not None)
    delivery_sent = sum(1 for x in scratch_obj['delivery_notifications'] if x.get('success'))
    delivery_fail = sum(1 for x in scratch_obj['delivery_notifications'] if not x.get('success'))
    # D-07 (PRD 13.2): terminal status is SUCCESS or FAILED only.
    # Market-data failures also fail the run (PRD 13.7).
    status = 'SUCCESS'
    if fail_count or timeout_count or tech_fail or delivery_fail or market_failures:
        status = 'FAILED'
    scratch_obj['ended_at'] = ended_at
    scratch_obj['status'] = status
    scratch_obj['summary'] = {
        'timestamp': ended_at,
        'workflow_run_id': RUN_ID,
        'event': 'run_complete',
        'status': status,
        'started_at': started_at,
        'ended_at': ended_at,
        'duration_ms': int((parse_dt(ended_at) - parse_dt(started_at)).total_seconds() * 1000) if parse_dt(ended_at) and parse_dt(started_at) else None,
        'input_count': len(rows),
        'output_count': len(final_records),
        'tickers_checked': len(rows),
        'valuation_refresh_attempted': len(plan),
        'valuation_refresh_succeeded': success_count,
        'valuation_refresh_failed': fail_count,
        'valuation_refresh_timed_out': timeout_count,
        'valuation_refresh_in_flight': 0,
        'top10': [x['ticker'] for x in top10],
        'technical_analysis_attempted': len(top10),
        'technical_analysis_succeeded': tech_success,
        'technical_analysis_failed': tech_fail,
        'top2': [x['ticker'] for x in top2],
        'delivery_sent': delivery_sent,
        'delivery_failed': delivery_fail,
        'market_data_failed': len(market_failures),
        'output_path': str(OUTPUT),
    }
    if ACTIVE_RUN_CONTEXT is not None:
        ACTIVE_RUN_CONTEXT['finalizing'] = True
    finalize_record(scratch_obj, scratch, LOG, status=status)
    ACTIVE_RUN_CONTEXT = None

    print(json.dumps({
        'workflow_run_id': RUN_ID,
        'status': status,
        'input_tickers': [x['ticker'] for x in rows],
        'output_tickers': [x['ticker'] for x in final_records],
        'valuations_refreshed': [x['ticker'] for x in scratch_obj['valuation_refreshes'] if x.get('success')],
        'valuation_refresh_failures': [x['ticker'] for x in scratch_obj['valuation_refreshes'] if not x.get('success')],
        'valuation_refresh_succeeded_count': success_count,
        'valuation_refresh_failed_count': fail_count,
        'valuation_refresh_timed_out_count': timeout_count,
        'valuation_refresh_in_flight_count': 0,
        'top10': [x['ticker'] for x in top10],
        'technical_analysis_successes': [x['ticker'] for x in scratch_obj['technical_analysis'] if x.get('error_code') is None],
        'technical_analysis_failures': [x['ticker'] for x in scratch_obj['technical_analysis'] if x.get('error_code') is not None],
        'top2': [{'ticker': x['ticker'], 'score': x['score'], 'verdict': x['verdict'], 'summary': (x.get('recommendation') or {}).get('summary'), 'v_derived_score': x['derived_score']} for x in top2],
        'delivery_notifications_sent': delivery_sent,
        'delivery_notification_failures': delivery_fail,
        'output_file': str(OUTPUT),
        'log_file': str(LOG),
    }, indent=2))
    return 0


if __name__ == '__main__':
    signal.signal(signal.SIGTERM, request_shutdown)
    try:
        exit_code = main()
    except BaseException as exc:
        finalization_error = finalize_active_failure(exc)
        print(json.dumps({
            'error': repr(exc),
            'finalization_error': finalization_error,
        }, indent=2))
        raise
    raise SystemExit(exit_code)
