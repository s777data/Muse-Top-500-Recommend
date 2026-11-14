"""Mag-500 Phase 6 valuation adapter — dashboard engine edition.

REPLACES the source's Hermes ``company-valuation-score`` invocation.
The placeholder ``company_valuation_score`` tree is NOT copied into
this repo (see INVENTORY.md). Instead this adapter calls the Muse
Business Evaluation Dashboard engine (V5.5 + GAV-Code, vendored
unmodified under ``vendor/muse-business-evaluation-dashboard/``)
in-process:

    from src.evaluator.run import evaluate
    result = evaluate(engine_symbol, cfg)

and writes a valuation-history record in the exact schema the copied
orchestrator verifies (see ``reference_validation_error`` in
mag50_auto_orchestrate.py): a NEW run_id, ``outcome="complete"``,
numeric business_quality.score / valuation.score on the 0–100 scale
(engine totals ×10), grades, confidence, and a non-empty
``target_prices`` — normally with a numeric DCF target; for
DCF-missing-but-fully-scored names, with the DCF fields null plus the
engine's ``dcf_missing_reason`` (D-12, see below).

    derived_score (Final) = 0.5×Business + 0.25×Value + 0.25×GAV-Code
    (all on the 0–100 scale; the GAV-Code score also rides inside the
    history record's business_quality dict so the orchestrator's
    build_record can compute the Final — see DEVIATIONS.md D-03.)

FAIL-CLOSED: any exception, a missing Business/Value total, or a
missing GAV-Code score produces NO history record (exit 1 as the
orchestrator's valuation child). The orchestrator then counts the
refresh failed and preserves the prior valid reference.

D-12 (approved 2026-11-14): a missing DCF fair value ALONE no longer
fails closed. The engine deliberately produces no DCF when the FCF
base cannot anchor one (``fcf_base_missing`` /
``non_positive_fcf_base`` / beta missing) while still scoring
Business/Value/GAV fully; the Final score does not use the DCF target
(the Value leg's DCF sub-score is already renormalised inside the
engine). Such names now write their history record with
``target_prices.dcf_fair_value = None`` and the engine's missing
reason recorded, and the orchestrator's validation accepts that shape
(see DEVIATIONS.md D-12).
There is deliberately NO yfinance GAV fallback in Mag-500 (the wheel's
flagged fallback was a wheel-specific approval): every score here is
EDGAR-pure engine output.

Modes:
- CLI child mode (used by the orchestrator's run_valuation_process):
  ``python3 -m scripts.valuation_adapter <TICKER>`` — evaluates one
  ticker against the main vendor tree and appends its history record
  (fcntl-locked read-modify-write). If ``MAG500_PREFETCHED=1`` and the
  history already holds a record for the ticker completed at/after
  ``MAG500_PREFETCH_CUTOFF``, it verifies and exits 0 without
  re-evaluating (the parallel prefetch already did the work).
- Parallel prefetch (PLAN design B): ``prefetch_valuations()`` runs
  evaluations on a ProcessPoolExecutor (``MAG500_VALUATION_WORKERS``,
  default 4, max 8). Each worker uses its OWN copy of the vendor tree
  (per-worker EDGAR cache directory — no shared-cache write races) and
  wraps the vendored HTTP fetcher at runtime with a cross-process
  token-bucket limiter holding SEC requests to
  ``MAG500_SEC_RATE_PER_SEC`` (default 8, SEC fair-access ceiling 10).
  Vendored files on disk are never modified. The parent process writes
  history records serially as futures complete; the orchestrator still
  assembles canonical output in input-rank order.
"""
from __future__ import annotations

import argparse
import copy
import fcntl
import hashlib
import json
import os
import shutil
import sys
import tempfile
import time
import urllib.request
import uuid
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
VENDOR = REPO_ROOT / "vendor" / "muse-business-evaluation-dashboard"
_EDGAR_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
METHODOLOGY = "dashboard-v5.5+gav-code"

_cfg_cache: Any = None
_cik_cache: dict[str, dict] | None = None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None


# --------------------------------------------------------------------------
# Vendored engine access (patterns adapted from the wheel's
# scripts/valuation_scorer.py — our own code).
# --------------------------------------------------------------------------

def _ensure_vendor_on_path(vendor_root: Path) -> None:
    if str(vendor_root) not in sys.path:
        sys.path.insert(0, str(vendor_root))


def _load_cfg(vendor_root: Path):
    global _cfg_cache
    if _cfg_cache is None:
        _ensure_vendor_on_path(vendor_root)
        from src.evaluator import config as cfgmod
        _cfg_cache = cfgmod.load_all()
    return _cfg_cache


def _user_agent(cfg) -> str:
    return (cfg.get("sources") or {}).get("sources", {}).get(
        "user_agent", "Muse Business Evaluation Dashboard admin@example.com")


def _resolve_cik(engine_symbol: str, cfg) -> dict | None:
    """Resolve {cik, name} for a symbol from EDGAR company_tickers.json."""
    global _cik_cache
    if _cik_cache is None:
        req = urllib.request.Request(
            _EDGAR_TICKERS_URL, headers={"User-Agent": _user_agent(cfg)})
        with urllib.request.urlopen(req, timeout=60) as fh:
            raw = json.loads(fh.read().decode("utf-8"))
        _cik_cache = {}
        for row in raw.values():
            _cik_cache[row["ticker"].upper()] = {
                "cik": str(row["cik_str"]).zfill(10), "name": row["title"]}
    return _cik_cache.get(engine_symbol.upper())


def _cfg_for(engine_symbol: str, cfg):
    """(cfg, injected, reason): inject an in-memory ticker entry via
    EDGAR CIK lookup when the symbol is not in the vendored config
    (no beta — the engine computes beta on the fly, V5.1)."""
    tickers = cfg["tickers"]["tickers"]
    if engine_symbol in tickers:
        return cfg, False, None
    info = _resolve_cik(engine_symbol, cfg)
    if info is None:
        return cfg, False, f"cik_not_found_on_edgar_for_{engine_symbol}"
    cfg2 = copy.deepcopy(cfg)
    cfg2["tickers"]["tickers"][engine_symbol] = {
        "name": info["name"], "cik": info["cik"], "exchange": "",
        "currency": "USD",
    }
    return cfg2, True, None


def _grade(score: float | None) -> str | None:
    if score is None:
        return None
    for floor, grade in ((97, "A+"), (93, "A"), (90, "A-"), (87, "B+"),
                         (83, "B"), (80, "B-"), (77, "C+"), (73, "C"),
                         (70, "C-"), (67, "D+"), (63, "D"), (60, "D-")):
        if score >= floor:
            return grade
    return "F"


def _confidence(business: dict, value: dict) -> str:
    missing = len(business.get("missing_metrics") or []) \
        + len(value.get("missing_metrics") or [])
    cov_b = business.get("weights_renormalised_over") or 0.0
    cov_v = value.get("weights_renormalised_over") or 0.0
    coverage = min(cov_b, cov_v)
    if coverage >= 0.999 and missing == 0:
        return "high"
    if coverage >= 0.7:
        return "medium"
    return "low"


# --------------------------------------------------------------------------
# Core evaluation -> history entry (fail-closed).
# --------------------------------------------------------------------------

def evaluate_to_entry(ticker: str, vendor_root: Path) -> tuple[dict | None, dict]:
    """Run the dashboard engine for one ticker.

    Returns (history_entry, diagnostics). history_entry is None on any
    fail-closed condition; diagnostics carries the reason."""
    ticker_u = (ticker or "").strip().upper()
    engine_symbol = ticker_u.replace(".", "-")
    diag: dict[str, Any] = {"ticker": ticker_u, "engine_symbol": engine_symbol}
    try:
        _ensure_vendor_on_path(vendor_root)
        from src.evaluator.run import evaluate
        cfg = _load_cfg(vendor_root)
        cfg, injected, reason = _cfg_for(engine_symbol, cfg)
        diag["cik_injected_from_edgar"] = injected
        if reason is not None:
            diag["reason"] = reason
            return None, diag
        raw = evaluate(engine_symbol, cfg)
    except Exception as exc:
        diag["reason"] = f"engine_exception: {exc!r}"
        return None, diag

    scores = raw.get("scores") or {}
    business = scores.get("business") or {}
    value = scores.get("value") or {}
    gav = raw.get("gav_code") or {}
    b_total, v_total = business.get("total"), value.get("total")
    if b_total is None:
        diag["reason"] = "business_score_missing"
        return None, diag
    if v_total is None:
        diag["reason"] = "value_score_missing"
        return None, diag
    if gav.get("score") is None:
        diag["reason"] = gav.get("missing_reason") or "gav_code_missing"
        return None, diag
    dcf = raw.get("dcf") or {}
    fair_value = dcf.get("fair_value_per_share")
    stress = (dcf.get("stress_floor") or {}).get("fair_value_per_share")
    # D-12: no DCF fair value is NOT fail-closed when Business, Value
    # and GAV-Code all scored (checked above). Record the engine's
    # missing reason and write the record with null DCF fields; the
    # orchestrator validation accepts that shape (DEVIATIONS.md D-12).
    dcf_missing_reason: str | None = None
    if not isinstance(fair_value, (int, float)):
        dcf_missing_reason = (
            (raw.get("data_quality") or {}).get("dcf_missing_reason")
            or dcf.get("stress_floor_missing_reason")
            or "dcf_target_missing"
        )

    business_100 = round(float(b_total) * 10, 4)
    value_100 = round(float(v_total) * 10, 4)
    gav_score = float(gav["score"])
    final = round(0.5 * business_100 + 0.25 * value_100 + 0.25 * gav_score, 6)
    confidence = _confidence(business, value)
    run_id = f"MAG500VAL-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:6]}"
    completed_at = _now_iso()
    target_prices: dict[str, Any] = {}
    if isinstance(fair_value, (int, float)):
        target_prices["dcf_fair_value"] = float(fair_value)
    else:
        target_prices["dcf_fair_value"] = None
        target_prices["dcf_missing_reason"] = str(dcf_missing_reason)
    if isinstance(stress, (int, float)):
        target_prices["stress_floor"] = float(stress)
    if isinstance(dcf.get("current_price"), (int, float)):
        target_prices["price_at_valuation"] = float(dcf["current_price"])
    entry = {
        "ticker": ticker_u,
        "run_id": run_id,
        "outcome": "complete",
        "status": "ok",
        "completed_at": completed_at,
        "data_cutoff_at": completed_at,
        "business_quality": {
            "score": business_100, "grade": _grade(business_100),
            "confidence": confidence, "gav_code": gav_score,
        },
        "valuation": {
            "score": value_100, "grade": _grade(value_100),
            "confidence": confidence,
        },
        "target_prices": target_prices,
        "derived_score": final,
        "final_score": final,
        "gav_code": gav,
        "engine": {
            "symbol": engine_symbol, "methodology": METHODOLOGY,
            "cik_injected_from_edgar": bool(diag.get("cik_injected_from_edgar")),
            "snapshot_date": raw.get("snapshot_date"),
        },
    }
    diag.update({"reason": None, "run_id": run_id,
                 "business_100": business_100, "value_100": value_100,
                 "gav_code": gav_score, "final": final,
                 "dcf_missing_reason": dcf_missing_reason})
    return entry, diag


# --------------------------------------------------------------------------
# History file (list format; fcntl-locked append).
# --------------------------------------------------------------------------

def _read_history(history_path: Path) -> list:
    try:
        raw = json.loads(history_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except Exception:
        return []
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict) and raw.get("ticker"):
        return [raw]
    if isinstance(raw, dict):
        out = []
        for ticker, value in raw.items():
            items = value if isinstance(value, list) else [value]
            for item in items:
                if isinstance(item, dict):
                    item = dict(item)
                    item.setdefault("ticker", ticker)
                    out.append(item)
        return out
    return []


def append_history_entry(history_path: Path, entry: dict) -> None:
    history_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = history_path.with_suffix(history_path.suffix + ".lock")
    with open(lock_path, "a+", encoding="utf-8") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        entries = _read_history(history_path)
        entries.append(entry)
        fd, tmp = tempfile.mkstemp(prefix=f".{history_path.name}.",
                                   suffix=".tmp", dir=history_path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(entries, fh, indent=2, ensure_ascii=False)
                fh.write("\n")
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, history_path)
        finally:
            if os.path.exists(tmp):
                try:
                    os.unlink(tmp)
                except FileNotFoundError:
                    pass
        fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def find_fresh_entry(history_path: Path, ticker: str,
                     cutoff_iso: str | None) -> dict | None:
    cutoff = _parse_iso(cutoff_iso) if cutoff_iso else None
    best: dict | None = None
    for entry in _read_history(history_path):
        if str(entry.get("ticker", "")).upper() != ticker.upper():
            continue
        ts = _parse_iso(entry.get("completed_at") or entry.get("data_cutoff_at"))
        if cutoff is not None and (ts is None or ts < cutoff):
            continue
        if best is None or (ts or datetime.min.replace(tzinfo=timezone.utc)) >= \
                (_parse_iso(best.get("completed_at") or best.get("data_cutoff_at"))
                 or datetime.min.replace(tzinfo=timezone.utc)):
            best = entry
    return best


# --------------------------------------------------------------------------
# Parallel prefetch (PLAN design B).
# --------------------------------------------------------------------------

class _SecRateLimiter:
    """Cross-process token bucket over SEC-bound fetches, implemented
    as an fcntl-locked JSON timestamp window in a shared state file."""

    def __init__(self, state_file: Path, rate_per_sec: float):
        self.state_file = state_file
        self.rate = rate_per_sec

    def acquire(self) -> None:
        while True:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.state_file, "a+", encoding="utf-8") as fh:
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
                fh.seek(0)
                try:
                    stamps = json.loads(fh.read() or "[]")
                except Exception:
                    stamps = []
                now = time.time()
                stamps = [s for s in stamps if now - s < 1.0]
                if len(stamps) < self.rate:
                    stamps.append(now)
                    fh.seek(0)
                    fh.truncate()
                    fh.write(json.dumps(stamps))
                    fh.flush()
                    os.fsync(fh.fileno())
                    fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
                    return
                wait = 1.0 - (now - stamps[0]) + 0.02
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
            time.sleep(max(0.02, min(wait, 0.5)))


_WORKER_VENDOR: Path | None = None


def _worker_init(worker_root: str, limiter_file: str, rate: float) -> None:
    """ProcessPool initializer: give this worker its own vendor copy
    (own EDGAR cache dir) and wrap the vendored fetcher with the shared
    SEC rate limiter (runtime wrap only — vendor files unmodified)."""
    global _WORKER_VENDOR
    base = Path(worker_root) / f"worker-{os.getpid()}"
    if not (base / "src").exists():
        tmp = Path(worker_root) / f".tmp-{os.getpid()}"
        if tmp.exists():
            shutil.rmtree(tmp, ignore_errors=True)
        shutil.copytree(VENDOR / "src", tmp / "src",
                        ignore=shutil.ignore_patterns("__pycache__", "output"))
        shutil.copytree(VENDOR / "config", tmp / "config")
        os.replace(tmp, base)
    _WORKER_VENDOR = base
    _ensure_vendor_on_path(base)
    try:
        from src.evaluator import util as _util
        limiter = _SecRateLimiter(Path(limiter_file), rate)
        orig_fetch_bytes = _util.fetch_bytes

        def limited_fetch_bytes(url, user_agent, timeout=60, delay=0.2,
                                cache_hours=12):
            # Only SEC hosts are rate-limited; the limiter is a no-op
            # cost (one file lock) for other hosts.
            if "sec.gov" in url or "www.sec.gov" in url:
                limiter.acquire()
            return orig_fetch_bytes(url, user_agent, timeout=timeout,
                                    delay=delay, cache_hours=cache_hours)

        _util.fetch_bytes = limited_fetch_bytes
    except Exception:
        pass  # engine's own per-process 0.2s pacing still applies


def _worker_evaluate(ticker: str) -> tuple[str, dict | None, dict]:
    global _WORKER_VENDOR
    vendor = _WORKER_VENDOR or VENDOR
    return (ticker, *evaluate_to_entry(ticker, vendor))


def prefetch_valuations(tickers: list[str], history_path: Path,
                        workers: int | None = None,
                        on_complete=None) -> dict[str, dict]:
    """Evaluate tickers on a bounded process pool; parent appends
    history records serially as futures complete.

    Returns {ticker: diagnostics} (diagnostics['success'] bool)."""
    if workers is None:
        workers = int(os.environ.get("MAG500_VALUATION_WORKERS", "4"))
    workers = max(1, min(8, workers))
    rate = float(os.environ.get("MAG500_SEC_RATE_PER_SEC", "8"))
    worker_root = os.environ.get(
        "MAG500_WORKER_VENDOR_ROOT",
        str(Path(tempfile.gettempdir()) / "mag500-vendor-workers"))
    limiter_file = str(Path(worker_root) / "sec-rate-limiter.json")
    results: dict[str, dict] = {}
    if workers <= 1 or len(tickers) <= 1:
        for ticker in tickers:
            entry, diag = evaluate_to_entry(ticker, VENDOR)
            diag["success"] = entry is not None
            if entry is not None:
                append_history_entry(history_path, entry)
            results[ticker] = diag
            if on_complete:
                on_complete(ticker, diag)
        return results
    _started = time.time()
    try:
        with ProcessPoolExecutor(max_workers=workers, initializer=_worker_init,
                                 initargs=(worker_root, limiter_file, rate)) as pool:
            futures = {pool.submit(_worker_evaluate, t): t for t in tickers}
            for fut in as_completed(futures):
                ticker = futures[fut]
                try:
                    _t, entry, diag = fut.result()
                except Exception as exc:
                    entry, diag = None, {"ticker": ticker,
                                         "reason": f"worker_exception: {exc!r}"}
                diag["success"] = entry is not None
                if entry is not None:
                    append_history_entry(history_path, entry)
                results[ticker] = diag
                if on_complete:
                    on_complete(ticker, diag)
    finally:
        # Worker vendor copies are run-scoped (per-worker EDGAR caches).
        # Remove the ones this prefetch created so /tmp cannot grow by
        # ~0.5 GB per run (observed 2026-11-14: 20 stale dirs, 509 MB).
        root = Path(worker_root)
        if root.exists():
            for child in root.glob("worker-*"):
                try:
                    if child.stat().st_mtime >= _started - 5:
                        shutil.rmtree(child, ignore_errors=True)
                except OSError:
                    pass
    return results


# --------------------------------------------------------------------------
# CLI child mode (the orchestrator's valuation command).
# --------------------------------------------------------------------------

def _default_history_path() -> Path:
    env = os.environ.get("MAG500_HISTORY_PATH")
    if env:
        return Path(env)
    return REPO_ROOT / "data" / "valuation_history.json"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ticker")
    parser.add_argument("--history", default=None)
    args = parser.parse_args(argv)
    ticker = args.ticker.strip().upper()
    history_path = Path(args.history) if args.history else _default_history_path()

    if os.environ.get("MAG500_PREFETCHED") == "1":
        fresh = find_fresh_entry(
            history_path, ticker, os.environ.get("MAG500_PREFETCH_CUTOFF"))
        if fresh is not None:
            print(json.dumps({"ticker": ticker, "status": "ok",
                              "prefetched": True,
                              "run_id": fresh.get("run_id")}))
            return 0

    entry, diag = evaluate_to_entry(ticker, VENDOR)
    if entry is None:
        print(json.dumps({"ticker": ticker, "status": "insufficient_data",
                          **diag}))
        return 1
    append_history_entry(history_path, entry)
    print(json.dumps({"ticker": ticker, "status": "ok", **diag}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
