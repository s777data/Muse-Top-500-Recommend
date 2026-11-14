import importlib.util
import json
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "mag50_launcher.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("mag50_launcher", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _Process:
    pid = 24680


def test_start_detaches_workflow_and_persists_pid(tmp_path, monkeypatch):
    module = _load_module()
    runs = tmp_path / "logs/.runs"
    stdout = tmp_path / "logs/live.log"
    orchestrator = tmp_path / "repo/skills/mag/scripts/mag50_auto_orchestrate.py"
    orchestrator.parent.mkdir(parents=True)
    orchestrator.write_text("print('ok')\n", encoding="utf-8")
    monkeypatch.setattr(module, "RUNS", runs)
    monkeypatch.setattr(module, "LOG_DIR", stdout.parent)
    monkeypatch.setattr(module, "PID_FILE", runs / "pid.json")
    monkeypatch.setattr(module, "LOCK_FILE", runs / "launch.lock")
    monkeypatch.setattr(module, "STDOUT_LOG", stdout)
    monkeypatch.setattr(module, "ORCHESTRATOR", orchestrator)
    monkeypatch.setattr(module, "process_is_alive", lambda pid: pid == 24680)
    captured = {}

    def fake_popen(command, **kwargs):
        captured["command"] = command
        captured.update(kwargs)
        return _Process()

    result = module.start(popen_factory=fake_popen)

    saved = json.loads((runs / "pid.json").read_text(encoding="utf-8"))
    assert result["pid"] == 24680
    assert result["process_running"] is True
    assert saved["pid"] == 24680
    assert captured["start_new_session"] is True
    assert captured["close_fds"] is True
    assert captured["stdin"] is not None
    assert captured["command"][1] == "-u"


def test_start_rejects_duplicate_live_process(tmp_path, monkeypatch):
    module = _load_module()
    pid_file = tmp_path / "pid.json"
    pid_file.write_text(json.dumps({"pid": 123}), encoding="utf-8")
    monkeypatch.setattr(module, "RUNS", tmp_path)
    monkeypatch.setattr(module, "PID_FILE", pid_file)
    monkeypatch.setattr(module, "LOCK_FILE", tmp_path / "launch.lock")
    monkeypatch.setattr(module, "process_is_alive", lambda pid: pid == 123)

    try:
        module.start()
    except RuntimeError as exc:
        assert "already running" in str(exc)
    else:
        raise AssertionError("duplicate launch was not rejected")


def test_start_rejects_concurrent_launch_lock(tmp_path, monkeypatch):
    module = _load_module()
    orchestrator = tmp_path / "mag50_auto_orchestrate.py"
    orchestrator.write_text("print('ok')\n", encoding="utf-8")
    monkeypatch.setattr(module, "RUNS", tmp_path)
    monkeypatch.setattr(module, "LOG_DIR", tmp_path)
    monkeypatch.setattr(module, "PID_FILE", tmp_path / "pid.json")
    monkeypatch.setattr(module, "LOCK_FILE", tmp_path / "launch.lock")
    monkeypatch.setattr(module, "ORCHESTRATOR", orchestrator)
    monkeypatch.setattr(
        module.fcntl,
        "flock",
        lambda *_args: (_ for _ in ()).throw(BlockingIOError()),
    )

    try:
        module.start()
    except RuntimeError as exc:
        assert "launch attempt" in str(exc)
    else:
        raise AssertionError("concurrent launch lock was not rejected")