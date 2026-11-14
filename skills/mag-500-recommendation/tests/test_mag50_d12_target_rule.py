"""D-12 (approved 2026-11-14): DCF-missing-but-fully-scored names.

The dashboard engine deliberately produces no DCF when the FCF base
cannot anchor one (fcf_base_missing / non_positive_fcf_base) while
still scoring Business/Value/GAV fully. The valuation adapter writes
such names' history records with target_prices = {dcf_fair_value:
None, dcf_missing_reason: <engine reason>, ...}, and the orchestrator
accepts that shape. Everything else about reference validity is
unchanged: no numeric target AND no recorded reason still fails, and
a missing Business/Value score still fails closed with no record.
"""
import importlib.util
import sys
import types
from pathlib import Path

import pytest


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
ADAPTER = Path(__file__).resolve().parents[3] / "scripts" / "valuation_adapter.py"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _orchestrator():
    return _load("mag50_auto_orchestrate", SCRIPTS / "mag50_auto_orchestrate.py")


def _adapter():
    return _load("valuation_adapter_d12", ADAPTER)


def _d12_entry(**overrides):
    entry = {
        "ticker": "LLY",
        "run_id": "MAG500VAL-d12-test",
        "outcome": "complete",
        "status": "ok",
        "completed_at": "2026-11-14T00:00:00Z",
        "data_cutoff_at": "2026-11-14T00:00:00Z",
        "business_quality": {
            "score": 46.2, "grade": "F", "confidence": "medium",
            "gav_code": 46.0,
        },
        "valuation": {"score": 12.1, "grade": "F", "confidence": "medium"},
        "target_prices": {
            "dcf_fair_value": None,
            "dcf_missing_reason": "fcf_base_missing",
            "price_at_valuation": 1050.0,
        },
    }
    entry.update(overrides)
    return entry


# --- (a) DCF-missing reference with recorded reason validates ----------

def test_d12_reference_validates_and_builds_record_with_final():
    module = _orchestrator()
    entry = _d12_entry()

    assert module.reference_validation_error(entry) is None
    assert module.is_completed_reference(entry)

    ref = module.normalize_reference(entry)
    assert module.valid_reference(ref)

    record = module.build_record(
        {"rank": 9, "ticker": "LLY", "name": "Eli Lilly and Company",
         "sector": "Health Care"},
        {"market_cap_raw": 950_000_000_000.0},
        ref,
        {},
    )
    # Final = 0.5*46.2 + 0.25*12.1 + 0.25*46.0 — DCF target never used.
    assert record["derived_score"] == pytest.approx(37.625)
    assert record["gav_code"] == 46.0
    assert record["target_prices"]["dcf_fair_value"] is None
    assert record["target_prices"]["dcf_missing_reason"] == "fcf_base_missing"
    assert record["run_id"] == "MAG500VAL-d12-test"


def test_d12_reference_selected_as_output_reference():
    module = _orchestrator()
    ref = module.normalize_reference(_d12_entry())
    selected = module.select_output_reference(True, ref, None)
    assert selected is ref


# --- (b) No numeric target AND no missing reason still fails -----------

def test_target_prices_without_target_or_reason_still_invalid():
    module = _orchestrator()
    for bad_tp in (
        {"dcf_fair_value": None},                                  # no reason
        {"dcf_fair_value": None, "dcf_missing_reason": ""},        # empty reason
        {"dcf_fair_value": None, "dcf_missing_reason": "   "},     # blank reason
        {"dcf_missing_reason": "fcf_base_missing"},                # DCF key absent
        {"dcf_fair_value": "n/a", "dcf_missing_reason": "x"},      # non-null non-numeric
        {"price_at_valuation": 1050.0},                            # price only
    ):
        entry = _d12_entry(target_prices=bad_tp)
        assert module.reference_validation_error(entry) == "TARGET_PRICES_INVALID", bad_tp
        assert not module.valid_reference(module.normalize_reference(entry)), bad_tp

    empty = _d12_entry(target_prices={})
    assert module.reference_validation_error(empty) == "TARGET_PRICES_MISSING"


def test_numeric_target_still_validates_without_reason():
    module = _orchestrator()
    entry = _d12_entry(target_prices={"dcf_fair_value": 812.5,
                                      "price_at_valuation": 1050.0})
    assert module.reference_validation_error(entry) is None
    assert module.valid_reference(module.normalize_reference(entry))


# --- (c) Missing-score names still fail closed --------------------------

def test_missing_value_score_reference_still_invalid_even_with_d12_targets():
    module = _orchestrator()
    entry = _d12_entry()
    entry["valuation"] = {"score": None, "grade": None, "confidence": "low"}
    assert module.reference_validation_error(entry) == "VALUATION_SCORE_INVALID"
    entry2 = _d12_entry()
    entry2["business_quality"] = {"score": None, "grade": None,
                                  "confidence": "low", "gav_code": 46.0}
    assert module.reference_validation_error(entry2) == "BUSINESS_QUALITY_SCORE_INVALID"


def _stub_engine(monkeypatch, adapter, raw):
    """Make the adapter's evaluate() return `raw` without the vendor
    engine or EDGAR. _load_cfg/_cfg_for are stubbed; the src.evaluator.run
    module is replaced in sys.modules."""
    fake_run = types.ModuleType("src.evaluator.run")
    fake_run.evaluate = lambda symbol, cfg: raw
    monkeypatch.setitem(sys.modules, "src.evaluator.run", fake_run)
    monkeypatch.setattr(adapter, "_load_cfg", lambda vendor_root: {})
    monkeypatch.setattr(adapter, "_cfg_for",
                        lambda engine_symbol, cfg: (cfg, False, None))


def test_adapter_writes_record_for_dcf_missing_fully_scored(monkeypatch):
    adapter = _adapter()
    raw = {
        "scores": {
            "business": {"total": 4.62, "missing_metrics": [],
                         "weights_renormalised_over": 1.0},
            "value": {"total": 1.21, "missing_metrics": [],
                      "weights_renormalised_over": 1.0},
        },
        "gav_code": {"score": 46.0},
        "dcf": {"fair_value_per_share": None, "stress_floor": None,
                "stress_floor_missing_reason": "fcf_base_missing",
                "current_price": 1050.0},
        "data_quality": {"dcf_missing_reason": "fcf_base_missing"},
        "snapshot_date": "2026-11-14",
    }
    _stub_engine(monkeypatch, adapter, raw)
    entry, diag = adapter.evaluate_to_entry("LLY", adapter.VENDOR)

    assert entry is not None
    assert entry["target_prices"]["dcf_fair_value"] is None
    assert entry["target_prices"]["dcf_missing_reason"] == "fcf_base_missing"
    assert entry["business_quality"]["score"] == pytest.approx(46.2)
    assert entry["valuation"]["score"] == pytest.approx(12.1)
    assert entry["derived_score"] == pytest.approx(37.625)
    assert diag["dcf_missing_reason"] == "fcf_base_missing"


def test_adapter_brkb_class_missing_value_writes_no_record(monkeypatch):
    adapter = _adapter()
    raw = {
        "scores": {
            "business": {"total": 7.5, "missing_metrics": [],
                         "weights_renormalised_over": 1.0},
            "value": {"total": None, "missing_metrics": [],
                      "weights_renormalised_over": 0.0},
        },
        "gav_code": {"score": None, "missing_reason": "value_score_missing"},
        "dcf": {"fair_value_per_share": None, "current_price": 592.8},
        "data_quality": {"dcf_missing_reason": "fcf_base_missing"},
        "snapshot_date": "2026-11-14",
    }
    _stub_engine(monkeypatch, adapter, raw)
    entry, diag = adapter.evaluate_to_entry("BRK.B", adapter.VENDOR)

    assert entry is None
    assert diag["reason"] == "value_score_missing"
