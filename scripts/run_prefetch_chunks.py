"""D-13 chunked valuation prefetch driver (resumable Mag-500 runs).

WHY: a full 503-ticker Mag-500 run is a monolith — two attempts on
2026-11-14 died mid-run (attempt 1: /tmp disk-full; attempt 2:
external shutdown ~25 min in) and each restart re-evaluated every
ticker cold. This driver splits the universe into chunks and runs the
valuation adapter's parallel prefetch per chunk, appending history
records to ``data/valuation_history.json`` as it goes. With the D-13
reuse window on (this driver sets ``MAG500_PREFETCH_REUSE_HOURS=12``
when unset — the vendored engine's own EDGAR cache TTL), tickers
whose latest valid history record is inside the window are skipped,
so re-running the driver, or re-running just an interrupted chunk,
only evaluates what is missing or stale. A later orchestrator run
with the same env then verifies-and-skips the seeded records in
Phase 6 instead of re-evaluating them.

Fail-closed names (e.g. BRK.B — no history record is ever written for
them) are attempted in every chunk run and counted as failed; that is
expected. The printed counts are the authoritative result.

Usage:
    .venv/bin/python -m scripts.run_prefetch_chunks [--chunk-size 100]
        [--tickers AAPL,MSFT,...] [--offset N] [--limit M]
        [--universe PATH] [--history PATH]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

DEFAULT_UNIVERSE = REPO_ROOT / "data" / "sp500_constituents.json"
DEFAULT_HISTORY = REPO_ROOT / "data" / "valuation_history.json"
DEFAULT_REUSE_HOURS = "12"


def chunk_tickers(tickers: list[str], chunk_size: int) -> list[list[str]]:
    """Split tickers into consecutive chunks of chunk_size, preserving
    order. A trailing remainder smaller than chunk_size is folded into
    the last chunk instead of forming a runt chunk — e.g. 503 tickers
    at size 100 split as [100, 100, 100, 100, 103], so every chunk is
    a substantial unit of resumable work."""
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    chunks = [tickers[i:i + chunk_size]
              for i in range(0, len(tickers), chunk_size)]
    if len(chunks) > 1 and len(chunks[-1]) < chunk_size:
        chunks[-2].extend(chunks.pop())
    return chunks


def load_universe_tickers(universe_path: Path) -> list[str]:
    raw = json.loads(universe_path.read_text(encoding="utf-8"))
    companies = raw.get("companies") if isinstance(raw, dict) else raw
    if not isinstance(companies, list):
        raise ValueError(f"universe file has no companies list: {universe_path}")
    return [str(c["ticker"]).strip().upper() for c in companies]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chunk-size", type=int, default=100)
    parser.add_argument("--tickers", default=None,
                        help="comma-separated ticker list (overrides universe)")
    parser.add_argument("--offset", type=int, default=0,
                        help="skip the first N tickers of the list")
    parser.add_argument("--limit", type=int, default=None,
                        help="take at most N tickers after the offset")
    parser.add_argument("--universe", default=str(DEFAULT_UNIVERSE))
    parser.add_argument("--history", default=str(DEFAULT_HISTORY))
    args = parser.parse_args(argv)

    # D-13: default the reuse window on for chunked seeding; an
    # explicit env value (including "0") is always honoured.
    os.environ.setdefault("MAG500_PREFETCH_REUSE_HOURS", DEFAULT_REUSE_HOURS)

    if args.tickers:
        tickers = [t.strip().upper()
                   for t in args.tickers.split(",") if t.strip()]
    else:
        tickers = load_universe_tickers(Path(args.universe))
    if args.offset:
        tickers = tickers[args.offset:]
    if args.limit is not None:
        tickers = tickers[:args.limit]

    from scripts.valuation_adapter import prefetch_valuations

    history_path = Path(args.history)
    chunks = chunk_tickers(tickers, args.chunk_size)
    total_succeeded = total_failed = total_reused = 0
    started = time.time()
    for idx, chunk in enumerate(chunks, 1):
        chunk_started = time.time()
        results = prefetch_valuations(chunk, history_path)
        succeeded = sum(1 for d in results.values() if d.get("success"))
        reused = sum(1 for d in results.values() if d.get("reused"))
        failed = len(results) - succeeded
        total_succeeded += succeeded
        total_failed += failed
        total_reused += reused
        print(f"chunk {idx}/{len(chunks)}: {len(chunk)} tickers, "
              f"{time.time() - chunk_started:.1f}s — succeeded {succeeded} "
              f"(reused {reused}), failed {failed}", flush=True)
    print(f"total: {len(tickers)} tickers in {time.time() - started:.1f}s — "
          f"succeeded {total_succeeded} (reused {total_reused}), "
          f"failed {total_failed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
