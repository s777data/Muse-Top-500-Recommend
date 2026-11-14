#!/usr/bin/env python3
"""Migrate Mag-500 legacy event-per-line JSONL to one consolidated line per run ID."""

from __future__ import annotations

import argparse
import json
import os
import shutil
from collections import Counter, OrderedDict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"line {line_number} is not a JSON object")
            run_id = value.get("workflow_run_id")
            if not isinstance(run_id, str) or not run_id.strip():
                raise ValueError(f"line {line_number} has no valid workflow_run_id")
            records.append(value)
    return records


def _terminal_event(events: list[dict[str, Any]]) -> dict[str, Any] | None:
    terminal = [event for event in events if event.get("event") in {"run_complete", "run_failure"}]
    return terminal[-1] if terminal else None


def _details(events: list[dict[str, Any]], names: set[str]) -> list[dict[str, Any]]:
    return [event for event in events if event.get("event") in names]


def _consolidate(run_id: str, events: list[dict[str, Any]]) -> dict[str, Any]:
    if len(events) == 1 and isinstance(events[0].get("summary"), dict) and isinstance(events[0].get("events"), list):
        return events[0]

    terminal = _terminal_event(events)
    start = next((event for event in events if event.get("event") == "run_start"), events[0])
    final = terminal or events[-1]
    status = final.get("status") if terminal else "incomplete"
    excluded = {"timestamp", "workflow_run_id", "event", "status"}
    summary = {key: value for key, value in final.items() if key not in excluded}
    summary.setdefault("event_counts", dict(Counter(str(event.get("event")) for event in events)))
    summary.setdefault("legacy_line_count", len(events))

    return {
        "workflow_run_id": run_id,
        "started_at": start.get("started_at") or start.get("timestamp"),
        "ended_at": final.get("ended_at") or final.get("timestamp"),
        "status": status,
        "summary": summary,
        "ticker_details": _details(events, {"ticker_market_data", "ticker_reconciled"}),
        "valuation_refreshes": _details(events, {"valuation_refresh_start", "valuation_refresh_success", "valuation_refresh_failure"}),
        "technical_analysis": _details(events, {"technical_analysis_start", "technical_analysis_success", "technical_analysis_failure", "top10_selected", "top2_selected"}),
        "delivery_notifications": _details(events, {"delivery_send_success", "delivery_send_failure", "telegram_send_success", "telegram_send_failure"}),
        "output_writes": _details(events, {"output_write_success", "output_write_failure"}),
        "events": events,
    }


def migrate(path: Path) -> tuple[Path, list[dict[str, Any]]]:
    rows = _read_jsonl(path)
    groups: OrderedDict[str, list[dict[str, Any]]] = OrderedDict()
    for row in rows:
        groups.setdefault(row["workflow_run_id"], []).append(row)

    consolidated = [_consolidate(run_id, events) for run_id, events in groups.items()]
    run_ids = [record["workflow_run_id"] for record in consolidated]
    if len(run_ids) != len(set(run_ids)):
        raise ValueError("consolidated workflow_run_id values are not unique")

    backup = path.with_name(f"{path.name}.bak-{_timestamp()}")
    shutil.copy2(path, backup)
    temp = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    try:
        with temp.open("w", encoding="utf-8") as handle:
            for record in consolidated:
                handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        _read_jsonl(temp)
        os.replace(temp, path)
    finally:
        if temp.exists():
            temp.unlink()

    verified = _read_jsonl(path)
    verified_ids = [record["workflow_run_id"] for record in verified]
    if len(verified) != len(groups) or len(verified_ids) != len(set(verified_ids)):
        raise RuntimeError("post-write uniqueness verification failed")
    return backup, verified


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    backup, records = migrate(args.path)
    print(json.dumps({
        "path": str(args.path),
        "backup": str(backup),
        "consolidated_lines": len(records),
        "unique_run_ids": len({record["workflow_run_id"] for record in records}),
        "runs": [{"workflow_run_id": record["workflow_run_id"], "status": record["status"]} for record in records],
    }, indent=2))


if __name__ == "__main__":
    main()
