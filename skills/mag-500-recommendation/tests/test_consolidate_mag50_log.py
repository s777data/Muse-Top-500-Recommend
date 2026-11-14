import importlib.util
import json
from pathlib import Path


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "consolidate_mag50_log.py"
)


def _load_module():
    spec = importlib.util.spec_from_file_location("consolidate_mag50_log", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")


def _read_jsonl(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def test_migrate_consolidates_one_line_per_workflow_run_id(tmp_path):
    module = _load_module()
    log = tmp_path / "Mag-50-recommend.jsonl"
    _write_jsonl(
        log,
        [
            {
                "timestamp": "2026-08-30T20:00:00Z",
                "workflow_run_id": "run-a",
                "event": "run_start",
                "status": "success",
            },
            {
                "timestamp": "2026-08-30T20:01:00Z",
                "workflow_run_id": "run-a",
                "event": "ticker_market_data",
                "status": "success",
                "ticker": "NVDA",
            },
            {
                "timestamp": "2026-08-30T20:02:00Z",
                "workflow_run_id": "run-a",
                "event": "run_complete",
                "status": "partial_success",
                "input_count": 1,
                "output_count": 1,
            },
            {
                "timestamp": "2026-08-30T21:00:00Z",
                "workflow_run_id": "run-b",
                "event": "run_start",
                "status": "success",
            },
        ],
    )

    backup, records = module.migrate(log)

    assert backup.exists()
    assert len(_read_jsonl(backup)) == 4
    assert len(records) == 2
    assert len({record["workflow_run_id"] for record in records}) == 2

    by_id = {record["workflow_run_id"]: record for record in records}
    assert by_id["run-a"]["status"] == "partial_success"
    assert by_id["run-a"]["summary"]["input_count"] == 1
    assert len(by_id["run-a"]["events"]) == 3
    assert by_id["run-a"]["ticker_details"][0]["ticker"] == "NVDA"
    assert by_id["run-b"]["status"] == "incomplete"


def test_migrate_preserves_already_consolidated_record(tmp_path):
    module = _load_module()
    log = tmp_path / "Mag-50-recommend.jsonl"
    record = {
        "workflow_run_id": "run-a",
        "started_at": "2026-08-30T20:00:00Z",
        "ended_at": "2026-08-30T20:01:00Z",
        "status": "success",
        "summary": {"input_count": 1},
        "ticker_details": [],
        "valuation_refreshes": [],
        "technical_analysis": [],
        "telegram_notifications": [],
        "output_writes": [],
        "events": [],
    }
    _write_jsonl(log, [record])

    _, records = module.migrate(log)

    assert records == [record]
    assert _read_jsonl(log) == [record]
