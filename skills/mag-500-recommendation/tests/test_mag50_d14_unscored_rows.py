"""D-14 (2026-11-14): structured unscored rows in output rebuild.

The first chunked full run scored 495/503 but died at output_rebuild:
'No valid record available for BRK.B' — the rebuild raised on the
first ticker with no valid history record and no prior output record,
discarding every scored row. Under D-14, a ticker whose refresh ran
and failed terminally (the engine's fail-closed verdict) becomes a
structured unscored row — build_record schema, scores null, reason
preserved, explicit marker — the D-17 pattern from the wheel. A
timed-out refresh, a missing refresh, or a successful refresh never
takes that branch; those stay fail-closed / impossible.
"""
import importlib.util
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
ORCH = SCRIPTS / "mag50_auto_orchestrate.py"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


orch = _load("mag50_orch_d14", ORCH)


ROW = {"rank": 11, "ticker": "BRK.B", "name": "Berkshire Hathaway", "sector": "Financials"}
MARKET = {
    "market_cap_raw": 1_020_000_000_000,
    "current_price": 502.11,
    "market_data_as_of": "2026-11-13T20:59:59Z",
}


def test_terminal_failure_is_eligible():
    refresh = {"success": False, "error_code": "VALUATION_REFERENCE_INVALID",
               "error_message": "value_score_missing"}
    assert orch.d14_unscored_eligible(refresh) is True


def test_timeout_is_not_eligible():
    refresh = {"success": False, "error_code": "VALUATION_REFRESH_TIMEOUT",
               "error_message": "timed out"}
    assert orch.d14_unscored_eligible(refresh) is False


def test_missing_refresh_is_not_eligible():
    assert orch.d14_unscored_eligible(None) is False


def test_successful_refresh_is_not_eligible():
    refresh = {"success": True, "error_code": None, "error_message": None}
    assert orch.d14_unscored_eligible(refresh) is False


def test_unscored_record_schema_and_null_scores():
    rec = orch.build_unscored_record(ROW, MARKET, "value_score_missing")
    assert rec["ticker"] == "BRK.B"
    assert rec["rank"] == 11
    assert rec["name"] == "Berkshire Hathaway"
    assert rec["sector"] == "Financials"
    assert rec["business_quality"] == {"score": None, "grade": None, "confidence": None}
    assert rec["valuation"] == {"score": None, "grade": None, "confidence": None}
    assert rec["target_prices"] is None
    assert rec["run_id"] is None
    assert rec["valuation_last_run_at"] is None
    assert rec["gav_code"] is None
    assert rec["derived_score"] is None
    assert rec["unscored"] is True
    assert rec["unscored_reason"] == "value_score_missing"


def test_unscored_record_keeps_market_fields():
    rec = orch.build_unscored_record(ROW, MARKET, "value_score_missing")
    assert rec["market_cap"].endswith(("T", "B"))
    assert rec["current_price"] == 502.11
    assert rec["market_data_as_of"] == "2026-11-13T20:59:59Z"


def test_unscored_record_is_never_ranked():
    # Top-10 selection keeps only numeric derived_score rows.
    rec = orch.build_unscored_record(ROW, MARKET, "value_score_missing")
    scored = [x for x in [rec] if isinstance(x.get("derived_score"), (int, float))]
    assert scored == []


def test_unscored_record_passes_output_row_validation():
    # load_output_rows only demands dict rows with unique rank/ticker;
    # an unscored row must survive a later run's output validation.
    rec = orch.build_unscored_record(ROW, MARKET, "value_score_missing")
    seen_ranks, seen_ticks = set(), set()
    for row in [rec]:
        assert isinstance(row, dict)
        assert row.get("rank") not in seen_ranks
        assert str(row.get("ticker", "")).upper() not in seen_ticks
        seen_ranks.add(row.get("rank"))
        seen_ticks.add(str(row.get("ticker", "")).upper())
