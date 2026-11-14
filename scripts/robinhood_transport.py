"""Batched Robinhood transport for Mag-500 (PLAN design A).

The ONLY Robinhood transport in this repo. Pattern adapted from
``muse-options-wheel-agent/scripts/robinhood_transport.py`` (our own
code): each call shells out to the local Robinhood MCP client

    python3 ~/workspace/custom-connectors/custom.robinhood/bin/client.py \
        call-tool --name <tool> --arguments-file <tmp.json>

and returns the parsed payload inside the MCP text content
(``{"data": {"results": [...]}}``).

BATCHED ONLY (approved design A, 2026-11-14): this module never issues
one call per ticker for quotes/fundamentals/historicals/indicators.
Chunk sizes come from the live MCP tool schemas verified 2026-11-14:

- ``get_equity_quotes``: chunks of 100 for price+timestamp (closes are
  omitted above 20 symbols; chunks of 20 when closes are needed).
- ``get_equity_fundamentals``: hard max 20/call.
- ``get_equity_historicals``: max 10/call.
- ``get_equity_technical_indicators``: max 10/call.

Every batch is reconciled (requested vs returned diffed); symbols a
batch did not return are retried singly; symbols still missing are
marked unavailable by the caller — never zero-filled here.

Bounded concurrency: batch calls run on a ThreadPool with at most
``MAG500_MARKET_CONCURRENCY`` (default 4) in flight. Transient errors
retry with exponential backoff. A 429 / rate-limit response is a HARD
STOP for the whole fetch (raised as ``RateLimitStop``): no retries, no
workaround via another route.
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

CLIENT = Path.home() / "workspace/custom-connectors/custom.robinhood/bin/client.py"

READ_TOOLS = {
    "get_equity_quotes",
    "get_equity_fundamentals",
    "get_equity_historicals",
    "get_equity_technical_indicators",
}

MAX_CONCURRENCY = max(1, min(8, int(os.environ.get("MAG500_MARKET_CONCURRENCY", "4"))))
QUOTE_CHUNK = 100
QUOTE_CHUNK_WITH_CLOSES = 20
FUNDAMENTALS_CHUNK = 20
HISTORICALS_CHUNK = 10
INDICATORS_CHUNK = 10


class RobinhoodTransportError(RuntimeError):
    pass


class RateLimitStop(RobinhoodTransportError):
    """429 / rate-limit response: hard stop for this fetch (no retry)."""


def _chunks(items: list, size: int) -> list[list]:
    return [items[i:i + size] for i in range(0, len(items), size)]


def call_robinhood_tool(name: str, arguments: dict | None = None,
                        timeout_seconds: int = 180) -> dict:
    """Call one allowlisted read tool via the local client; return the
    parsed ``data`` payload dict. Raises on any failure — never invents
    data."""
    if name not in READ_TOOLS:
        raise RobinhoodTransportError(f"tool not allowlisted in Mag-500 transport: {name}")
    args_file = None
    try:
        with tempfile.NamedTemporaryFile(
                "w", suffix=".json", prefix="mag500_rh_", delete=False) as fh:
            json.dump(arguments or {}, fh)
            args_file = fh.name
        proc = subprocess.run(
            ["python3", str(CLIENT), "call-tool", "--name", name,
             "--arguments-file", args_file],
            capture_output=True, text=True, timeout=timeout_seconds)
    finally:
        if args_file:
            try:
                os.unlink(args_file)
            except FileNotFoundError:
                pass
    raw = (proc.stdout or "") + (proc.stderr or "")
    if proc.returncode != 0:
        # Only an actual error response can be a rate-limit stop —
        # successful payloads legitimately contain words like "rate"
        # in company descriptions.
        if "429" in raw or "rate_limit" in raw.lower() or "rate limit" in raw.lower():
            raise RateLimitStop(f"{name}: rate-limit response: {raw[-500:]}")
        raise RobinhoodTransportError(
            f"{name} rc={proc.returncode}: {raw[-1000:]}")
    try:
        outer = json.loads(proc.stdout)
        text = outer["content"][0]["text"]
        inner = json.loads(text)
    except Exception as exc:
        raise RobinhoodTransportError(f"{name}: unparseable response: {exc}") from exc
    if isinstance(inner, dict) and inner.get("error"):
        raise RobinhoodTransportError(f"{name}: {inner['error']}")
    data = inner.get("data") if isinstance(inner, dict) else None
    if not isinstance(data, dict):
        raise RobinhoodTransportError(f"{name}: missing data payload")
    return data


def _call_with_backoff(name: str, arguments: dict, attempts: int = 3) -> dict:
    last: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return call_robinhood_tool(name, arguments)
        except RateLimitStop:
            raise
        except Exception as exc:  # transient: bounded exponential backoff
            last = exc
            if attempt < attempts:
                time.sleep(2 * (2 ** (attempt - 1)))
    raise RobinhoodTransportError(f"{name} failed after {attempts} attempts: {last}")


def _batched(tool: str, tickers: list[str], chunk_size: int,
             extra_args: dict, result_key: str) -> dict[str, dict]:
    """Run `tool` over `tickers` in chunks (bounded concurrency).

    Returns {ticker: result_object}. Reconciles requested vs returned;
    missing symbols are retried singly; symbols still missing are
    simply absent from the result (caller marks them unavailable)."""
    found: dict[str, dict] = {}

    def one_chunk(chunk: list[str]) -> dict[str, dict]:
        data = _call_with_backoff(tool, {"symbols": chunk, **extra_args})
        out: dict[str, dict] = {}
        for item in data.get(result_key) or []:
            if isinstance(item, dict):
                # get_equity_quotes nests the symbol inside item["quote"];
                # the other tools carry it at the top level.
                sym = str(item.get("symbol")
                          or (item.get("quote") or {}).get("symbol")
                          or "").upper()
                if sym:
                    out[sym] = item
        return out

    chunks = _chunks(list(tickers), chunk_size)
    if len(chunks) <= 1:
        for chunk in chunks:
            found.update(one_chunk(chunk))
    else:
        with ThreadPoolExecutor(max_workers=MAX_CONCURRENCY) as pool:
            for part in pool.map(one_chunk, chunks):
                found.update(part)

    missing = [t for t in tickers if t not in found]
    for ticker in missing:  # single-symbol reconciliation retry
        try:
            found.update(one_chunk([ticker]))
        except RateLimitStop:
            raise
        except Exception:
            continue
    return found


def fetch_quotes(tickers: list[str], *, with_closes: bool = False) -> dict[str, dict]:
    """{ticker: quote-object} from get_equity_quotes (batched)."""
    chunk = QUOTE_CHUNK_WITH_CLOSES if with_closes else QUOTE_CHUNK
    raw = _batched("get_equity_quotes", tickers, chunk, {}, "results")
    out: dict[str, dict] = {}
    for ticker, item in raw.items():
        quote = item.get("quote") if isinstance(item.get("quote"), dict) else item
        out[ticker] = quote
    return out


def fetch_fundamentals(tickers: list[str]) -> dict[str, dict]:
    """{ticker: fundamentals-object} from get_equity_fundamentals (20/call)."""
    return _batched("get_equity_fundamentals", tickers, FUNDAMENTALS_CHUNK, {}, "results")


def fetch_historicals(tickers: list[str], start_time: str,
                      end_time: str | None = None, interval: str = "day") -> dict[str, dict]:
    """{ticker: historicals-object with 'bars'} (10/call)."""
    extra: dict[str, Any] = {"start_time": start_time, "interval": interval}
    if end_time:
        extra["end_time"] = end_time
    return _batched("get_equity_historicals", tickers, HISTORICALS_CHUNK, extra, "results")


def fetch_technical_indicators(tickers: list[str], indicator_type: str,
                               start_time: str, *, interval: str = "day",
                               period: int | None = None,
                               output: str = "latest") -> dict[str, dict]:
    """{ticker: indicators-object} from get_equity_technical_indicators (10/call)."""
    extra: dict[str, Any] = {"type": indicator_type, "interval": interval,
                             "start_time": start_time, "output": output}
    if period is not None:
        extra["period"] = period
    return _batched("get_equity_technical_indicators", tickers,
                    INDICATORS_CHUNK, extra, "results")


def fetch_market_data(tickers: list[str]) -> dict[str, dict]:
    """Phase 4 market snapshot for every ticker, batched.

    Returns {ticker: market-dict} in the exact shape the orchestrator's
    market phase consumes:
    {ticker, current_price, market_cap_raw, quote_state, has_traded,
     market_data_as_of, market_data_attempts[, market_data_error]}.
    A ticker whose quote/fundamentals never came back is present with
    None fields and a market_data_error — unavailable, never zero."""
    quotes = fetch_quotes(tickers)
    fundamentals = fetch_fundamentals(tickers)
    out: dict[str, dict] = {}
    for ticker in tickers:
        q = quotes.get(ticker)
        f = fundamentals.get(ticker)
        if q is None and f is None:
            out[ticker] = {
                "ticker": ticker, "current_price": None, "market_cap_raw": None,
                "quote_state": None, "has_traded": None, "market_data_as_of": None,
                "market_data_attempts": [{"attempt": 1, "success": False,
                                          "error": "batch+solo retry returned no quote or fundamentals"}],
                "market_data_error": "MARKET_DATA_UNAVAILABLE",
            }
            continue
        price = None
        if q is not None:
            try:
                price = float(q.get("last_trade_price"))
            except (TypeError, ValueError):
                price = None
        cap = None
        if f is not None:
            try:
                cap = float(f.get("market_cap"))
            except (TypeError, ValueError):
                cap = None
        out[ticker] = {
            "ticker": ticker,
            "current_price": price,
            "market_cap_raw": cap,
            "quote_state": (q or {}).get("state"),
            "has_traded": (q or {}).get("has_traded"),
            "market_data_as_of": (q or {}).get("venue_last_trade_time"),
            "market_data_attempts": [{"attempt": 1, "success": True, "batched": True}],
        }
    return out
