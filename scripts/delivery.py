"""Muse delivery for Mag-500 (Phase 12, PLAN deviation D-05).

Replaces the source's Telegram/Hermes sends. There are no Telegram
credentials and no invented destinations: each notification payload is
written as a file into the run's delivery directory (under the run
artifacts, ``logs/.runs/<run-id>-delivery/`` by default, overridable
with ``MAG500_DELIVERY_DIR``) where it is surfaced in Muse chat /
artifacts by the operator session.

Structured accounting is preserved from the PRD: a send counts as
successful ONLY when the payload file was actually written and
read back. When delivery is disabled (``MAG500_DELIVERY_DISABLED=1``)
the send is reported as skipped — and skipped is a FAILURE with the
reason preserved (PRD §12), never a success.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def delivery_dir() -> Path:
    override = os.environ.get("MAG500_DELIVERY_DIR")
    if override:
        return Path(override)
    return _REPO_ROOT / "logs" / ".runs" / "delivery"


def send_delivery(message: str) -> tuple[bool, str]:
    """Deliver one notification payload. Returns (success, raw_result_json).

    Drop-in replacement for the source's ``send_telegram`` signature."""
    if os.environ.get("MAG500_DELIVERY_DISABLED") == "1":
        raw = json.dumps({
            "success": False, "skipped": True,
            "reason": "delivery_disabled_by_MAG500_DELIVERY_DISABLED",
            "channel": "claude_artifacts",
        })
        return False, raw
    try:
        target_dir = delivery_dir()
        target_dir.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256(message.encode("utf-8")).hexdigest()[:12]
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        path = target_dir / f"delivery-{stamp}-{digest}.txt"
        path.write_text(message, encoding="utf-8")
        # Read back: only a verified write counts as delivered.
        if path.read_text(encoding="utf-8") != message:
            raise OSError("delivery payload read-back mismatch")
        raw = json.dumps({
            "success": True, "skipped": False,
            "channel": "claude_artifacts",
            "path": str(path), "delivered_at": _now_iso(),
        })
        return True, raw
    except Exception as exc:
        raw = json.dumps({
            "success": False, "skipped": False,
            "reason": f"delivery_write_failed: {exc!r}",
            "channel": "claude_artifacts",
        })
        return False, raw
