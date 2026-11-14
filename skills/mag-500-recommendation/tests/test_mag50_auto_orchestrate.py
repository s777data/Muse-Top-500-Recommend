import importlib.util
import json
import subprocess
from pathlib import Path

import pytest


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "mag50_auto_orchestrate.py"
)


def _load_module():
    spec = importlib.util.spec_from_file_location("mag50_auto_orchestrate", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _legacy_entry(run_id="legacy-1", timestamp="2026-01-01T00:00:00Z"):
    return {
        "ticker": "slb",
        "run_id": run_id,
        "outcome": "complete",
        "completed_at": timestamp,
        "business_quality": {"score": 61.0, "grade": "C+", "confidence": "high"},
        "valuation": {"score": 67.0, "grade": "B-", "confidence": "high"},
        "target_prices": {"A": 31.3, "price_at_valuation": 53.2},
    }


def _current_entry(run_id="current-1", timestamp="2026-02-01T00:00:00Z"):
    return {
        "ticker": "SLB",
        "run_id": run_id,
        "data_cutoff_at": timestamp,
        "valuation": {
            "grade": {"status": "ok", "score": 67.161, "grade": "B-", "confidence": "high"},
            "business_quality": {"score": 61.451, "grade": "C+", "confidence": "high"},
            "target_prices": {"A+": 26.99, "A": 31.30, "A-": 36.39, "current": 53.21},
        },
        "persisted": {
            "audit_outcome": "complete",
            "history_entry_verified": True,
            "audit_record_verified": True,
        },
    }


def _slb_history_entry():
    """Minimal fixture copied from run 20261024T012037-SLB-96a193."""
    entry = _current_entry(
        run_id="20261024T012037-SLB-96a193",
        timestamp="2026-10-24T01:19:29.406883+00:00",
    )
    entry.pop("persisted")
    return entry


def _slb_recorded_output_entry():
    """Minimal fields from MAG50-20261023T213412Z-f18e2c-SLB.valuation.out."""
    return {
        "ticker": "SLB",
        "run_id": "20261024T012037-SLB-96a193",
        "data_cutoff_at": "2026-10-24T01:19:29.406883+00:00",
        "status": "ok",
        "final_score": 67.16168607164717,
        "grade": "B-",
        "confidence": "high",
        "business_quality": {
            "status": "ok",
            "score": 61.4509895905621,
            "grade": "C+",
            "confidence": "high",
        },
        "target_prices": {
            "target_price_aplus": 26.994707262193835,
            "target_price_a": 31.30327049461571,
            "target_price_a-": 36.39048973289696,
        },
        "persisted": {
            "history_entry_verified": True,
            "audit_record_verified": True,
            "audit_outcome": "complete",
        },
    }


def test_legacy_completed_reference_is_accepted():
    module = _load_module()
    assert module.is_completed_reference(_legacy_entry())


def test_current_persisted_completed_reference_is_accepted():
    module = _load_module()
    assert module.is_completed_reference(_current_entry())

    nested = {
        "ticker": "SLB",
        "run_id": "nested-current",
        "data_cutoff_at": "2026-02-01T00:00:00Z",
        "valuation": {
            "grade": {
                "status": "ok",
                "score": 67.0,
                "grade": "B-",
                "confidence": "high",
                "business_quality": {"score": 61.0, "grade": "C+"},
                "target_prices": {"A": 31.3},
            }
        },
        "persisted": {"audit_outcome": "complete"},
    }
    assert module.is_completed_reference(nested)


def test_current_unverified_reference_is_rejected_precisely():
    module = _load_module()
    entry = _current_entry()
    entry["persisted"]["history_entry_verified"] = False
    assert module.reference_validation_error(entry) == "REFERENCE_HISTORY_NOT_VERIFIED"


def test_current_history_rejects_non_ok_nested_grade():
    module = _load_module()
    entry = _current_entry()
    entry.pop("persisted")
    entry["valuation"]["grade"]["status"] = "failed"
    assert module.reference_validation_error(entry) == "REFERENCE_GRADE_STATUS_NOT_OK"


def test_flat_current_history_document_is_loaded(tmp_path, monkeypatch):
    module = _load_module()
    entry = _current_entry()
    entry.pop("persisted")
    history_path = tmp_path / "valuation_history.json"
    history_path.write_text(json.dumps(entry), encoding="utf-8")
    monkeypatch.setattr(module, "HISTORY", history_path)

    entries, by_ticker = module.load_reference_entries()

    assert entries == [entry]
    assert by_ticker["SLB"][-1][1]["run_id"] == "current-1"


def test_missing_run_id_and_non_numeric_scores_are_rejected():
    module = _load_module()
    missing = _current_entry()
    missing["run_id"] = ""
    assert module.reference_validation_error(missing) == "RUN_ID_NOT_FOUND"

    malformed = _current_entry()
    malformed["valuation"]["grade"]["score"] = "67.1"
    assert module.reference_validation_error(malformed) == "VALUATION_SCORE_INVALID"


def test_newest_valid_reference_wins_deterministically(tmp_path, monkeypatch):
    module = _load_module()
    history = tmp_path / "history.json"
    invalid_newest = _current_entry("bad-newest", "2026-04-01T00:00:00Z")
    invalid_newest["valuation"]["business_quality"]["score"] = None
    history.write_text(
        json.dumps([
            _legacy_entry("old", "2026-01-01T00:00:00Z"),
            _current_entry("new", "2026-03-01T00:00:00Z"),
            invalid_newest,
        ]),
        encoding="utf-8",
    )
    monkeypatch.setattr(module, "HISTORY", history)

    _, index = module.load_reference_entries()
    selected = module.latest_reference("SLB", index)

    assert selected["run_id"] == "new"


def test_actual_slb_history_shape_is_accepted_and_refresh_is_success():
    module = _load_module()
    history_entry = _slb_history_entry()
    recorded_output = _slb_recorded_output_entry()
    assert module.is_completed_reference(history_entry)
    assert module.is_completed_reference(recorded_output)
    entry = recorded_output
    assert module.is_completed_reference(entry)
    ref = module.normalize_reference(entry)

    success, error_code = module.classify_refresh_result(
        {"exit_code": 0, "timed_out": False},
        "20261022T001719-SLB-185602",
        ref,
    )

    assert success is True
    assert error_code is None


def test_refresh_classification_distinguishes_failure_timeout_and_stale_reference():
    module = _load_module()
    ref = module.normalize_reference(_slb_history_entry())
    assert module.classify_refresh_result(
        {"exit_code": 1, "timed_out": False}, None, ref
    ) == (False, "VALUATION_REFRESH_FAILED")
    assert module.classify_refresh_result(
        {"exit_code": -15, "timed_out": True}, None, ref
    ) == (False, "VALUATION_REFRESH_TIMEOUT")
    assert module.classify_refresh_result(
        {"exit_code": 0, "timed_out": False}, ref["run_id"], ref
    ) == (False, "VALUATION_REFERENCE_NOT_UPDATED")


def test_failed_refresh_preserves_prior_valid_reference():
    module = _load_module()
    prior = module.normalize_reference(_legacy_entry("prior"))
    newer = module.normalize_reference(_current_entry("newer"))

    assert module.select_output_reference(False, newer, prior)["run_id"] == "prior"
    assert module.select_output_reference(True, newer, prior)["run_id"] == "newer"


class _FakeProcess:
    def __init__(self, returncode: int | None = 0, stdout="ok", stderr=""):
        self.pid = 4321
        self.returncode = returncode
        self.stdout_value = stdout
        self.stderr_value = stderr

    def communicate(self, timeout=None):
        return self.stdout_value, self.stderr_value

    def poll(self):
        return self.returncode


class _TimeoutProcess(_FakeProcess):
    def __init__(self, stdout="partial-stdout", stderr="partial-stderr"):
        super().__init__(returncode=None, stdout=stdout, stderr=stderr)

    def communicate(self, timeout=None):
        if self.returncode is None and timeout is not None:
            raise subprocess.TimeoutExpired("valuation", timeout)
        return self.stdout_value, self.stderr_value


def test_hermes_json_uses_managed_process_and_emits_initial_heartbeat(monkeypatch):
    module = _load_module()
    process = _FakeProcess(0, '[{"ticker":"NVDA"}]', "")
    captured = {}

    def fake_popen(command, **kwargs):
        captured["command"] = command
        captured.update(kwargs)
        return process

    monkeypatch.setattr(module.subprocess, "Popen", fake_popen)
    heartbeats = []

    result = module.hermes_json("return JSON", heartbeat=heartbeats.append)

    assert result == [{"ticker": "NVDA"}]
    assert heartbeats == [4321]
    assert captured["start_new_session"] is True
    assert captured["stdout"] == subprocess.PIPE
    assert captured["stderr"] == subprocess.PIPE


def test_valuation_process_success_nonzero_and_output_tail(monkeypatch):
    module = _load_module()
    monkeypatch.setattr(module, "SUBPROCESS_OUTPUT_TAIL_CHARS", 5)
    heartbeats = []

    success = module.run_valuation_process(
        "SLB",
        popen_factory=lambda *args, **kwargs: _FakeProcess(0, "123456789", "abcdef"),
        heartbeat=heartbeats.append,
    )
    failure = module.run_valuation_process(
        "EOG",
        popen_factory=lambda *args, **kwargs: _FakeProcess(7, "stdout", "stderr"),
    )

    assert success["exit_code"] == 0
    assert success["timed_out"] is False
    assert success["stdout_tail"] == "56789"
    assert success["stderr_tail"] == "bcdef"
    assert heartbeats == [4321]
    assert failure["exit_code"] == 7
    assert failure["timed_out"] is False


def test_timeout_is_bounded_and_next_ticker_can_succeed(monkeypatch):
    module = _load_module()
    timeout_process = _TimeoutProcess()

    def terminate(proc):
        proc.returncode = -15

    monkeypatch.setattr(module, "terminate_process_tree", terminate)
    timed_out = module.run_valuation_process(
        "SLB",
        timeout_seconds=0.005,
        heartbeat_seconds=0.001,
        popen_factory=lambda *args, **kwargs: timeout_process,
    )
    next_result = module.run_valuation_process(
        "EOG",
        popen_factory=lambda *args, **kwargs: _FakeProcess(0),
    )

    assert timed_out["timed_out"] is True
    assert timed_out["timeout_seconds"] == 0.005
    assert timed_out["stdout_tail"] == "partial-stdout"
    assert timed_out["stderr_tail"] == "partial-stderr"
    assert next_result["exit_code"] == 0


def test_shutdown_request_terminates_child_before_interrupting(monkeypatch):
    module = _load_module()
    process = _TimeoutProcess()
    terminated = []

    def terminate(proc):
        terminated.append(proc.pid)
        proc.returncode = -15

    monkeypatch.setattr(module, "terminate_process_tree", terminate)
    module.request_shutdown(15, None)
    assert module.SHUTDOWN_REQUESTED is True
    with pytest.raises(module.WorkflowInterrupted, match="shutdown requested"):
        module.run_valuation_process(
            "SLB",
            popen_factory=lambda *args, **kwargs: process,
        )
    assert terminated == [4321]


def _scratch(run_id="run-1"):
    return {
        "workflow_run_id": run_id,
        "started_at": "2026-01-01T00:00:00Z",
        "status": "running",
        "progress": {
            "phase": "valuation",
            "current_ticker": "EOG",
            "current_rank": 85,
            "ticker_index": 85,
            "ticker_total": 100,
            "last_heartbeat_at": "2026-01-01T00:05:00Z",
            "child_pid": 123,
        },
        "valuation_refreshes": [
            {"ticker": "SLB", "success": True, "error_code": None}
        ],
        "events": [],
    }


def test_progress_checkpoint_identifies_exact_in_flight_ticker(tmp_path):
    module = _load_module()
    path = tmp_path / "scratch.json"
    obj = _scratch()

    module.set_current_progress(
        obj,
        path,
        ticker="EOG",
        rank=85,
        ticker_index=85,
        ticker_total=100,
        started_at="2026-01-01T00:05:00Z",
        previous_run_id="old-eog",
        child_pid=321,
    )

    persisted = json.loads(path.read_text(encoding="utf-8"))
    assert persisted["progress"]["current_ticker"] == "EOG"
    assert persisted["progress"]["ticker_index"] == 85
    assert persisted["progress"]["ticker_total"] == 100
    assert persisted["progress"]["child_pid"] == 321
    assert persisted["progress"]["last_heartbeat_at"]
    progress = persisted["progress"]
    assert progress["ticker_index"] <= progress["ticker_total"]
    assert (
        progress["valuation_completed"]
        + progress["valuation_failed"]
        + progress["valuation_timed_out"]
        + progress["valuation_in_flight"]
        <= progress["ticker_total"]
    )


def test_market_progress_is_persisted_before_first_lookup(tmp_path):
    module = _load_module()
    path = tmp_path / "scratch.json"
    obj = _scratch()

    module.set_market_progress(
        obj,
        path,
        ticker="NVDA",
        rank=1,
        ticker_index=1,
        ticker_total=100,
        started_at="2026-01-01T00:00:00Z",
        child_pid=987,
        completed=0,
        failed=0,
    )

    persisted = json.loads(path.read_text(encoding="utf-8"))
    progress = persisted["progress"]
    assert progress["phase"] == "market_data"
    assert progress["current_ticker"] == "NVDA"
    assert progress["ticker_index"] == 1
    assert progress["ticker_total"] == 100
    assert progress["child_pid"] == 987
    assert progress["market_completed"] == 0
    assert progress["market_in_flight"] == 1


def test_failure_finalization_is_idempotent_and_clears_progress(tmp_path):
    module = _load_module()
    scratch_path = tmp_path / "run.json"
    log_path = tmp_path / "runs.jsonl"
    obj = _scratch()
    module.atomic_write_json(scratch_path, obj)

    module.finalize_record(
        obj,
        scratch_path,
        log_path,
        status="partial_success",
        failure={"exception_type": "RuntimeError", "exception_message": "boom"},
    )

    assert not scratch_path.exists()
    rows = [json.loads(line) for line in log_path.read_text().splitlines()]
    assert len(rows) == 1
    assert rows[0]["failure"]["current_ticker"] == "EOG"
    assert rows[0]["failure"]["valuation_succeeded"] == 1
    assert rows[0]["progress"]["current_ticker"] is None

    replacement = _scratch()
    module.atomic_write_json(scratch_path, replacement)
    module.finalize_record(
        replacement,
        scratch_path,
        log_path,
        status="failure",
        failure={"exception_type": "ValueError", "exception_message": "again"},
    )
    rows = [json.loads(line) for line in log_path.read_text().splitlines()]
    assert len(rows) == 1
    assert rows[0]["workflow_run_id"] == "run-1"


def test_scratch_is_retained_when_canonical_finalization_fails(tmp_path, monkeypatch):
    module = _load_module()
    scratch_path = tmp_path / "run.json"
    log_path = tmp_path / "runs.jsonl"
    obj = _scratch()
    module.atomic_write_json(scratch_path, obj)

    def fail_upsert(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(module, "upsert_canonical_record", fail_upsert)
    with pytest.raises(OSError, match="disk full"):
        module.finalize_record(
            obj,
            scratch_path,
            log_path,
            status="failure",
            failure={"exception_type": "RuntimeError", "exception_message": "boom"},
        )

    assert scratch_path.exists()
    persisted = json.loads(scratch_path.read_text())
    assert persisted["status"] == "failure"


def test_failure_upsert_does_not_degrade_existing_complete_record(tmp_path):
    module = _load_module()
    log_path = tmp_path / "runs.jsonl"
    complete = _scratch()
    complete.update({"status": "success", "summary": {"event": "run_complete"}})
    module.upsert_canonical_record(log_path, complete)

    degraded = _scratch()
    degraded.update({"status": "failure", "failure": {"exception_type": "RuntimeError"}})
    module.upsert_canonical_record(log_path, degraded)

    rows = [json.loads(line) for line in log_path.read_text().splitlines()]
    assert len(rows) == 1
    assert rows[0]["status"] == "success"
    assert "failure" not in rows[0]


def test_keyboard_interrupt_uses_outer_failure_finalization(tmp_path):
    module = _load_module()
    scratch_path = tmp_path / "run.json"
    log_path = tmp_path / "runs.jsonl"
    obj = _scratch()
    module.atomic_write_json(scratch_path, obj)
    setattr(module, "ACTIVE_RUN_CONTEXT", {
        "scratch_obj": obj,
        "scratch_path": scratch_path,
        "log_path": log_path,
    })

    assert module.finalize_active_failure(KeyboardInterrupt()) is None

    rows = [json.loads(line) for line in log_path.read_text().splitlines()]
    assert len(rows) == 1
    assert rows[0]["status"] == "FAILED"  # D-07: SUCCESS/FAILED only (PRD 13.2)
    assert rows[0]["failure"]["exception_type"] == "KeyboardInterrupt"
    assert not scratch_path.exists()


def test_hermes_json_cleans_up_child_when_heartbeat_write_fails(monkeypatch):
    module = _load_module()
    process = _FakeProcess(returncode=0, stdout='{}')
    terminated = []
    monkeypatch.setattr(module.subprocess, "Popen", lambda *args, **kwargs: process)
    monkeypatch.setattr(module, "terminate_process_tree", lambda proc: terminated.append(proc))
    monkeypatch.setattr(module, "bounded_communicate_after_termination", lambda proc: ("", ""))

    with pytest.raises(OSError, match="ledger unavailable"):
        module.hermes_json(
            "prompt",
            model="model",
            timeout=5,
            heartbeat=lambda _pid: (_ for _ in ()).throw(OSError("ledger unavailable")),
        )

    assert terminated == [process]


def test_market_terminal_progress_is_not_in_flight(tmp_path):
    module = _load_module()
    scratch = tmp_path / "run.json"
    state = {"progress": {}}

    module.set_market_progress(
        state,
        scratch,
        ticker="NVDA",
        rank=1,
        ticker_index=1,
        ticker_total=100,
        started_at="2026-01-01T00:00:00Z",
        child_pid=None,
        completed=1,
        failed=0,
        in_flight=False,
    )

    persisted = json.loads(scratch.read_text(encoding="utf-8"))
    assert persisted["progress"]["market_in_flight"] == 0
    assert persisted["progress"]["child_process_state"] == "complete"


def test_clear_current_progress_resets_technical_in_flight():
    module = _load_module()
    state = {"progress": {"technical_in_flight": 1, "market_in_flight": 1}}

    module.clear_current_progress(state)

    assert state["progress"]["technical_in_flight"] == 0
    assert state["progress"]["market_in_flight"] == 0
