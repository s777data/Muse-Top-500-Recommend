#!/usr/bin/env python3
"""Print one exact Mag-500 progress message, or nothing when no run is active."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from mag50_launcher import status_payload


def count_results(items: Any, key: str, value: Any) -> int:
    if not isinstance(items, list):
        return 0
    return sum(1 for item in items if isinstance(item, dict) and item.get(key) == value)


def render(status: dict[str, Any]) -> str:
    workflow = status.get("workflow")
    if not status.get("process_running") or not isinstance(workflow, dict):
        return ""
    if workflow.get("status") != "running":
        return ""
    progress_value = workflow.get("progress")
    progress: dict[str, Any] = progress_value if isinstance(progress_value, dict) else {}
    refreshes_value = workflow.get("valuation_refreshes")
    refreshes: list[Any] = refreshes_value if isinstance(refreshes_value, list) else []
    technical_value = workflow.get("technical_analysis")
    technical: list[Any] = technical_value if isinstance(technical_value, list) else []
    succeeded = count_results(refreshes, "success", True)
    timed_out = count_results(refreshes, "error_code", "VALUATION_REFRESH_TIMEOUT")
    failed = sum(
        1 for item in refreshes
        if isinstance(item, dict)
        and not item.get("success")
        and item.get("error_code") != "VALUATION_REFRESH_TIMEOUT"
    )
    tech_failed = sum(
        1 for item in technical
        if isinstance(item, dict) and item.get("error_code") is not None
    )
    tech_succeeded = len(technical) - tech_failed
    index = progress.get("ticker_index")
    total = progress.get("ticker_total")
    ticker_progress = f"{index}/{total}" if index is not None and total is not None else "unavailable"
    current = progress.get("current_ticker") or "none"
    return "\n".join([
        "Mag-500 workflow progress:",
        f"- workflow_run_id: {workflow.get('workflow_run_id')}",
        f"- process_pid: {status.get('pid')}",
        f"- phase: {progress.get('phase') or 'unavailable'}",
        f"- ticker: {ticker_progress} ({current})",
        f"- market: completed={progress.get('market_completed', 'unavailable')} failed={progress.get('market_failed', 'unavailable')} in_flight={progress.get('market_in_flight', 0)}",
        f"- valuation: succeeded={succeeded} failed={failed} timed_out={timed_out} in_flight={progress.get('valuation_in_flight', 0)}",
        f"- technical: succeeded={tech_succeeded} failed={tech_failed} in_flight={progress.get('technical_in_flight', 0)}",
        f"- last_heartbeat_at: {progress.get('last_heartbeat_at') or 'unavailable'}",
    ])


def main() -> int:
    message = render(status_payload())
    if message:
        print(message)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
