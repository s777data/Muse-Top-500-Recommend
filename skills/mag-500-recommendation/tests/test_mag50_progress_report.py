import importlib.util
import sys
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
SCRIPT = SCRIPTS / "mag50_progress_report.py"


def _load_module():
    sys.path.insert(0, str(SCRIPTS))
    try:
        spec = importlib.util.spec_from_file_location("mag50_progress_report", SCRIPT)
        assert spec is not None
        assert spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(SCRIPTS))


def test_render_reports_exact_live_progress():
    module = _load_module()
    status = {
        "pid": 123,
        "process_running": True,
        "workflow": {
            "workflow_run_id": "MAG50-test",
            "status": "running",
            "progress": {
                "phase": "market_data",
                "current_ticker": "NVDA",
                "ticker_index": 1,
                "ticker_total": 100,
                "market_completed": 0,
                "market_failed": 0,
                "market_in_flight": 1,
                "last_heartbeat_at": "2026-01-01T00:00:15Z",
            },
            "valuation_refreshes": [],
            "technical_analysis": [],
        },
    }

    message = module.render(status)

    assert "workflow_run_id: MAG50-test" in message
    assert "phase: market_data" in message
    assert "ticker: 1/100 (NVDA)" in message
    assert "market: completed=0 failed=0 in_flight=1" in message
    assert "last_heartbeat_at: 2026-01-01T00:00:15Z" in message


def test_render_is_silent_without_live_process():
    module = _load_module()
    assert module.render({"process_running": False, "workflow": {"status": "running"}}) == ""
