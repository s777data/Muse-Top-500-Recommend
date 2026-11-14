"""D-13 (2026-11-14): resumable valuation reuse.

Two full-run attempts died mid-prefetch on 2026-11-14 (attempt 1:
/tmp disk-full; attempt 2: external shutdown ~25 min in) and every
restart re-evaluated all 503 tickers cold, because the orchestrator's
freshness cutoff was the run's own start time. With
MAG500_PREFETCH_REUSE_HOURS > 0:

- the adapter's prefetch reuses a ticker's latest history record when
  it completed inside the window AND passes the orchestrator's
  reference validation (mirrored in the adapter); anything else is
  evaluated normally;
- the orchestrator moves MAG500_PREFETCH_CUTOFF back by the window and
  classify_refresh_result accepts the pre-seeded record as a
  successful refresh via a freshness proof (completion timestamp
  inside the window) instead of the new-record proof.

With the env unset/0, behaviour is exactly pre-D-13.
"""
import importlib.util
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
REPO = Path(__file__).resolve().parents[3]
ADAPTER = REPO / "scripts" / "valuation_adapter.py"
DRIVER = REPO / "scripts" / "run_prefetch_chunks.py"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _orchestrator():
    return _load("mag50_auto_orchestrate", SCRIPTS / "mag50_auto_orchestrate.py")


def _adapter():
    return _load("valuation_adapter_d13", ADAPTER)


def _driver():
    return _load("run_prefetch_chunks", DRIVER)


def _iso(dt: datetime) -> str:
    return dt.isoformat().replace("+00:00", "Z")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _entry(ticker="AAPL", run_id="MAG500VAL-seed-1", completed_at=None, **over):
    entry = {
        "ticker": ticker,
        "run_id": run_id,
        "outcome": "complete",
        "status": "ok",
        "completed_at": completed_at,
        "data_cutoff_at": completed_at,
        "business_quality": {"score": 80.0, "grade": "B-",
                             "confidence": "high", "gav_code": 70.0},
        "valuation": {"score": 50.0, "grade": "F", "confidence": "high"},
        "target_prices": {"dcf_fair_value": 300.0,
                          "price_at_valuation": 250.0},
        "derived_score": 65.0,
        "final_score": 65.0,
    }
    entry.update(over)
    return entry


def _seed_history(tmp_path, entries):
    history = tmp_path / "valuation_history.json"
    history.write_text(json.dumps(entries), encoding="utf-8")
    return history


def _counting_evaluate(adapter, calls):
    def fake_evaluate(ticker, vendor_root):
        calls.append(ticker)
        entry = _entry(ticker=ticker, run_id=f"MAG500VAL-eval-{ticker}",
                       completed_at=_iso(_now()))
        return entry, {"ticker": ticker, "reason": None,
                       "run_id": entry["run_id"]}
    return fake_evaluate


# --- (a) reuse on: fresh valid record is reused, not evaluated --------

def test_prefetch_reuses_fresh_valid_record(monkeypatch, tmp_path):
    adapter = _adapter()
    history = _seed_history(tmp_path, [
        _entry(completed_at=_iso(_now() - timedelta(minutes=5)))])
    calls: list[str] = []
    monkeypatch.setattr(adapter, "evaluate_to_entry",
                        _counting_evaluate(adapter, calls))
    monkeypatch.setenv("MAG500_PREFETCH_REUSE_HOURS", "12")

    results = adapter.prefetch_valuations(["AAPL"], history, workers=1)

    assert calls == []
    diag = results["AAPL"]
    assert diag["success"] is True
    assert diag["reused"] is True
    assert diag["run_id"] == "MAG500VAL-seed-1"


def test_prefetch_reuses_fresh_d12_record(monkeypatch, tmp_path):
    adapter = _adapter()
    d12 = _entry(ticker="LLY", run_id="MAG500VAL-seed-lly",
                 completed_at=_iso(_now() - timedelta(hours=1)),
                 target_prices={"dcf_fair_value": None,
                                "dcf_missing_reason": "fcf_base_missing",
                                "price_at_valuation": 1050.0})
    history = _seed_history(tmp_path, [d12])
    calls: list[str] = []
    monkeypatch.setattr(adapter, "evaluate_to_entry",
                        _counting_evaluate(adapter, calls))
    monkeypatch.setenv("MAG500_PREFETCH_REUSE_HOURS", "12")

    results = adapter.prefetch_valuations(["LLY"], history, workers=1)

    assert calls == []
    assert results["LLY"]["reused"] is True
    assert results["LLY"]["run_id"] == "MAG500VAL-seed-lly"


# --- (b) reuse on: stale record (older than window) is evaluated ------

def test_prefetch_evaluates_stale_record(monkeypatch, tmp_path):
    adapter = _adapter()
    history = _seed_history(tmp_path, [
        _entry(completed_at=_iso(_now() - timedelta(hours=48)))])
    calls: list[str] = []
    monkeypatch.setattr(adapter, "evaluate_to_entry",
                        _counting_evaluate(adapter, calls))
    monkeypatch.setenv("MAG500_PREFETCH_REUSE_HOURS", "12")

    results = adapter.prefetch_valuations(["AAPL"], history, workers=1)

    assert calls == ["AAPL"]
    assert results["AAPL"]["success"] is True
    assert not results["AAPL"].get("reused")
    assert results["AAPL"]["run_id"] == "MAG500VAL-eval-AAPL"


# --- (c) reuse off: fresh record is still evaluated --------------------

def test_prefetch_reuse_off_evaluates_fresh_record(monkeypatch, tmp_path):
    adapter = _adapter()
    history = _seed_history(tmp_path, [
        _entry(completed_at=_iso(_now() - timedelta(minutes=5)))])
    calls: list[str] = []
    monkeypatch.setattr(adapter, "evaluate_to_entry",
                        _counting_evaluate(adapter, calls))
    monkeypatch.delenv("MAG500_PREFETCH_REUSE_HOURS", raising=False)

    results = adapter.prefetch_valuations(["AAPL"], history, workers=1)

    assert calls == ["AAPL"]
    assert not results["AAPL"].get("reused")


def test_prefetch_reuse_zero_evaluates_fresh_record(monkeypatch, tmp_path):
    adapter = _adapter()
    history = _seed_history(tmp_path, [
        _entry(completed_at=_iso(_now() - timedelta(minutes=5)))])
    calls: list[str] = []
    monkeypatch.setattr(adapter, "evaluate_to_entry",
                        _counting_evaluate(adapter, calls))
    monkeypatch.setenv("MAG500_PREFETCH_REUSE_HOURS", "0")

    results = adapter.prefetch_valuations(["AAPL"], history, workers=1)

    assert calls == ["AAPL"]
    assert not results["AAPL"].get("reused")


# --- reuse on: fresh but INVALID records are evaluated, never reused --

def test_prefetch_evaluates_fresh_invalid_record(monkeypatch, tmp_path):
    adapter = _adapter()
    history = _seed_history(tmp_path, [
        _entry(completed_at=_iso(_now() - timedelta(minutes=5)),
               target_prices={})])
    calls: list[str] = []
    monkeypatch.setattr(adapter, "evaluate_to_entry",
                        _counting_evaluate(adapter, calls))
    monkeypatch.setenv("MAG500_PREFETCH_REUSE_HOURS", "12")

    results = adapter.prefetch_valuations(["AAPL"], history, workers=1)

    assert calls == ["AAPL"]
    assert not results["AAPL"].get("reused")


def test_prefetch_evaluates_record_with_failed_verification_marker(
        monkeypatch, tmp_path):
    adapter = _adapter()
    history = _seed_history(tmp_path, [
        _entry(completed_at=_iso(_now() - timedelta(minutes=5)),
               persisted={"history_entry_verified": False})])
    calls: list[str] = []
    monkeypatch.setattr(adapter, "evaluate_to_entry",
                        _counting_evaluate(adapter, calls))
    monkeypatch.setenv("MAG500_PREFETCH_REUSE_HOURS", "12")

    results = adapter.prefetch_valuations(["AAPL"], history, workers=1)

    assert calls == ["AAPL"]
    assert not results["AAPL"].get("reused")


# --- (d) orchestrator cutoff + classify --------------------------------

def test_orchestrator_cutoff_without_reuse_is_now(monkeypatch):
    module = _orchestrator()
    monkeypatch.delenv("MAG500_PREFETCH_REUSE_HOURS", raising=False)
    before = _now()
    iso, cutoff_dt = module._prefetch_cutoff()
    after = _now()
    assert cutoff_dt is None
    parsed = module.parse_dt(iso)
    assert before - timedelta(seconds=5) <= parsed <= after + timedelta(seconds=5)


def test_orchestrator_cutoff_with_reuse_moves_back(monkeypatch):
    module = _orchestrator()
    monkeypatch.setenv("MAG500_PREFETCH_REUSE_HOURS", "12")
    before = _now()
    iso, cutoff_dt = module._prefetch_cutoff()
    after = _now()
    assert cutoff_dt is not None
    assert module.parse_dt(iso) == cutoff_dt
    low = before - timedelta(hours=12) - timedelta(seconds=5)
    high = after - timedelta(hours=12) + timedelta(seconds=5)
    assert low <= cutoff_dt <= high


def _classify_ref(module, completed_at):
    entry = _entry(run_id="MAG500VAL-seed-1", completed_at=completed_at)
    return module.normalize_reference(entry)


def test_classify_same_run_id_without_reuse_still_not_updated():
    module = _orchestrator()
    ref = _classify_ref(module, _iso(_now()))
    result = {"exit_code": 0, "timed_out": False}
    success, error_code = module.classify_refresh_result(
        result, "MAG500VAL-seed-1", ref)
    assert success is False
    assert error_code == "VALUATION_REFERENCE_NOT_UPDATED"


def test_classify_same_run_id_with_reuse_cutoff_succeeds():
    module = _orchestrator()
    ref = _classify_ref(module, _iso(_now() - timedelta(hours=1)))
    result = {"exit_code": 0, "timed_out": False}
    success, error_code = module.classify_refresh_result(
        result, "MAG500VAL-seed-1", ref,
        reuse_cutoff=_now() - timedelta(hours=12))
    assert success is True
    assert error_code is None


def test_classify_same_run_id_with_reuse_cutoff_after_completion_fails():
    module = _orchestrator()
    ref = _classify_ref(module, _iso(_now() - timedelta(hours=1)))
    result = {"exit_code": 0, "timed_out": False}
    success, error_code = module.classify_refresh_result(
        result, "MAG500VAL-seed-1", ref,
        reuse_cutoff=_now() + timedelta(hours=1))
    assert success is False
    assert error_code == "VALUATION_REFERENCE_NOT_UPDATED"


def test_classify_reuse_does_not_rescue_failed_child():
    module = _orchestrator()
    ref = _classify_ref(module, _iso(_now() - timedelta(hours=1)))
    success, error_code = module.classify_refresh_result(
        {"exit_code": 1, "timed_out": False}, "MAG500VAL-seed-1", ref,
        reuse_cutoff=_now() - timedelta(hours=12))
    assert success is False
    assert error_code == "VALUATION_REFRESH_FAILED"


def test_classify_new_record_still_succeeds_without_reuse():
    module = _orchestrator()
    ref = _classify_ref(module, _iso(_now()))
    success, error_code = module.classify_refresh_result(
        {"exit_code": 0, "timed_out": False}, "MAG500VAL-older", ref)
    assert success is True
    assert error_code is None


# --- (e) chunk driver splitting -----------------------------------------

def test_chunk_driver_splits_503_like_universe():
    driver = _driver()
    tickers = [f"T{i:03d}" for i in range(503)]
    chunks = driver.chunk_tickers(tickers, 100)
    assert [len(c) for c in chunks] == [100, 100, 100, 100, 103]
    assert [t for chunk in chunks for t in chunk] == tickers


def test_chunk_driver_edge_cases():
    driver = _driver()
    assert driver.chunk_tickers([], 100) == []
    assert driver.chunk_tickers(["A"], 100) == [["A"]]
    with pytest.raises(ValueError):
        driver.chunk_tickers(["A"], 0)
