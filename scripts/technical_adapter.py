"""Mag-500 Phases 9–10 technical adapter (PLAN design C).

The copied ``technical_analysis_recommend`` package is deterministic
Python; only its Hermes SKILL.md wrapper was model-driven. This adapter
invokes the package DIRECTLY as code:

- Market data comes from the batched Robinhood transport
  (``scripts/robinhood_transport.py``): quotes in chunks of 100 and
  historicals in chunks of 10 — for a Top-10 shortlist that is one
  batched call of each kind, not ten per-ticker sessions.
- The prefetched batch is served to ``TechnicalAnalysisEngine`` through
  an MCP-client shim with the exact interface the engine expects
  (``get_equity_quotes([ticker]) -> PriceData``,
  ``get_equity_historicals([ticker], start, end) -> list[DailyBar]``),
  mirroring the source's own ``run_analysis.py`` file-fed client.
- The engine's result already contains a deterministic
  ``recommendation.summary`` (from scoring.calculate_recommendation),
  so no model-written summary is needed anywhere.

``run_technical(ticker)`` returns the exact result dict the
orchestrator's technical phase consumes:
{status, ticker, score, verdict, recommendation: {summary}, warnings}.
Per-ticker calls reuse the module-level batch prefetch when
``prefetch_technicals(tickers)`` was called first (the orchestrator
does this for the whole Top 10); otherwise the single ticker is
fetched on demand (still via the batched transport functions).
"""
from __future__ import annotations

import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
_CODE_DIR = REPO_ROOT / "skills" / "technical-analysis-buy-recommend" / "code"
if str(_CODE_DIR) not in sys.path:
    sys.path.insert(0, str(_CODE_DIR))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts import robinhood_transport as transport  # noqa: E402

# Prefetch cache: {ticker: {"quote": PriceData, "bars": [DailyBar]}}
_CACHE: dict[str, dict[str, Any]] = {}
HISTORY_DAYS = 8 * 365  # the engine asks for 8+ years of daily bars


def _to_price_data(quote: dict):
    from technical_analysis_recommend.models import PriceData
    return PriceData(
        regular_last_trade=float(quote["last_trade_price"]),
        regular_last_trade_at=quote.get("venue_last_trade_time"),
        symbol=str(quote.get("symbol", "")).upper(),
        listing_state=quote.get("state"),
        has_traded=bool(quote.get("has_traded")),
    )


def _to_bars(hist: dict):
    from technical_analysis_recommend.models import DailyBar
    bars = []
    for bar in hist.get("bars") or []:
        try:
            dt = datetime.fromisoformat(
                str(bar["begins_at"]).replace("Z", "+00:00"))
            bars.append(DailyBar(
                date=dt.date(),
                open=float(bar["open_price"]),
                high=float(bar["high_price"]),
                low=float(bar["low_price"]),
                close=float(bar["close_price"]),
                volume=int(float(bar.get("volume") or 0)),
                interpolated=bool(bar.get("interpolated")),
            ))
        except Exception:
            continue
    bars.sort(key=lambda b: b.date)
    return bars


def prefetch_technicals(tickers: list[str]) -> None:
    """One batched quotes call + batched historicals calls (10/call)
    for the whole shortlist; results are cached for run_technical()."""
    start = (date.today() - timedelta(days=HISTORY_DAYS)).isoformat() \
        + "T00:00:00Z"
    quotes = transport.fetch_quotes(tickers)
    historicals = transport.fetch_historicals(tickers, start_time=start)
    for ticker in tickers:
        entry: dict[str, Any] = {}
        if ticker in quotes:
            entry["quote"] = _to_price_data(quotes[ticker])
        if ticker in historicals:
            entry["bars"] = _to_bars(historicals[ticker])
        _CACHE[ticker] = entry


class _BatchMCPClient:
    """MCP-client shim over the prefetched batch (engine interface)."""

    def get_equity_quotes(self, symbols: list):
        ticker = str(symbols[0]).upper()
        entry = _CACHE.get(ticker)
        if entry and entry.get("quote") is not None:
            return entry["quote"]
        quotes = transport.fetch_quotes([ticker])
        if ticker not in quotes:
            raise ValueError(f"no quote returned for {ticker}")
        price = _to_price_data(quotes[ticker])
        _CACHE.setdefault(ticker, {})["quote"] = price
        return price

    def get_equity_historicals(self, symbols: list, start_time: str,
                               end_time: str = None, **_kwargs):
        ticker = str(symbols[0]).upper()
        entry = _CACHE.get(ticker)
        if entry and entry.get("bars"):
            return entry["bars"]
        start = (date.today() - timedelta(days=HISTORY_DAYS)).isoformat() \
            + "T00:00:00Z"
        historicals = transport.fetch_historicals([ticker], start_time=start)
        if ticker not in historicals:
            raise ValueError(f"no historicals returned for {ticker}")
        bars = _to_bars(historicals[ticker])
        _CACHE.setdefault(ticker, {})["bars"] = bars
        return bars


def run_technical(ticker: str) -> dict:
    """Run the copied technical engine for one ticker; return the
    orchestrator's technical-result dict. Engine failures come back as
    status != 'ok' results (the engine itself fails closed); transport
    failures raise to the caller, which records TECHNICAL_ANALYSIS_FAILED."""
    from technical_analysis_recommend.engine import TechnicalAnalysisEngine
    engine = TechnicalAnalysisEngine(_BatchMCPClient())
    result = engine.run(ticker.strip().upper())
    payload = result.to_dict() if hasattr(result, "to_dict") else None
    if payload is None:
        import json as _json
        payload = _json.loads(result.to_json())
    return {
        "status": payload.get("status"),
        "ticker": payload.get("ticker"),
        "score": payload.get("score"),
        "verdict": payload.get("verdict"),
        "recommendation": payload.get("recommendation") or {},
        "warnings": payload.get("warnings") or [],
        "data_as_of": payload.get("data_as_of"),
        "indicators": payload.get("indicators"),
        "levels": payload.get("levels"),
    }
