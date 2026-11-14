#!/usr/bin/env python3
"""Durable launcher/status helper for the Mag-500 orchestrator (copied from the Mag-50 source; D-01 config).

The launcher deliberately starts the workflow in a new OS session with stdin detached.
This keeps the workflow alive if the initiating Hermes chat/gateway session restarts.
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BASE = Path(os.environ.get("MAG500_BASE", os.environ.get("MAG50_BASE", str(Path(__file__).resolve().parents[3]))))  # D-01
RUNS = BASE / "logs/.runs"
LOG_DIR = BASE / "logs"
PID_FILE = RUNS / "mag50-orchestrator.pid.json"
LOCK_FILE = RUNS / "mag50-orchestrator.lock"
STDOUT_LOG = LOG_DIR / "mag50-live.stdout.log"
ORCHESTRATOR = Path(__file__).with_name("mag50_auto_orchestrate.py")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def atomic_write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(obj, handle, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def load_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    return value if isinstance(value, dict) else None


def process_is_alive(pid: Any) -> bool:
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    try:
        command_line = Path(f"/proc/{pid}/cmdline").read_bytes()
    except OSError:
        return True
    return str(ORCHESTRATOR).encode() in command_line


def newest_run_ledger() -> dict[str, Any] | None:
    candidates = [
        path for path in RUNS.glob("MAG500-*.json")
        if not any(path.name.endswith(suffix) for suffix in (
            "-market.json", "-plan.json", "-valuation-results.json",
            "-top10.json", "-technical.json",
        ))
    ]
    if not candidates:
        return None
    newest = max(candidates, key=lambda path: path.stat().st_mtime_ns)
    ledger = load_json(newest)
    if ledger is not None:
        ledger["ledger_path"] = str(newest)
    return ledger


def status_payload() -> dict[str, Any]:
    launch = load_json(PID_FILE) or {}
    pid = launch.get("pid")
    ledger = newest_run_ledger()
    return {
        "launcher_pid_file": str(PID_FILE),
        "pid": pid,
        "process_running": process_is_alive(pid),
        "launched_at": launch.get("launched_at"),
        "command": launch.get("command"),
        "stdout_log": str(STDOUT_LOG),
        "workflow": ledger,
    }


def start(*, popen_factory: Any = subprocess.Popen) -> dict[str, Any]:
    if not ORCHESTRATOR.exists():
        raise FileNotFoundError(ORCHESTRATOR)
    RUNS.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with LOCK_FILE.open("a+", encoding="utf-8") as lock_handle:
        try:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("another Mag-500 launch attempt is already in progress") from exc
        current = load_json(PID_FILE) or {}
        if process_is_alive(current.get("pid")):
            raise RuntimeError(f"Mag-500 is already running as PID {current['pid']}")
        command = [sys.executable, "-u", str(ORCHESTRATOR)]
        with STDOUT_LOG.open("a", encoding="utf-8") as output:
            proc = popen_factory(
                command,
                cwd=str(ORCHESTRATOR.parents[3]),
                stdin=subprocess.DEVNULL,
                stdout=output,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                close_fds=True,
            )
        launch = {
            "pid": proc.pid,
            "launched_at": now_iso(),
            "command": command,
            "orchestrator": str(ORCHESTRATOR),
            "stdout_log": str(STDOUT_LOG),
        }
        atomic_write_json(PID_FILE, launch)
        return {**launch, "process_running": process_is_alive(proc.pid)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("start", "status"))
    args = parser.parse_args()
    payload = start() if args.action == "start" else status_payload()
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
