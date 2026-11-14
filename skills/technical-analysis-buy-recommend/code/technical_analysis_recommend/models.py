"""
Data models for technical analysis.
"""

from dataclasses import dataclass, field
from typing import Optional, List
from datetime import date, datetime
import json


@dataclass
class PriceData:
    """Price data from get_equity_quotes."""
    regular_last_trade: float
    regular_last_trade_at: str
    symbol: str
    listing_state: str
    has_traded: bool


@dataclass
class DailyBar:
    """Daily OHLCV bar from get_equity_historicals."""
    date: date
    open: float
    high: float
    low: float
    close: float
    volume: int
    interpolated: bool


@dataclass
class WeeklyCandle:
    """Aggregated weekly candle (Monday-Friday)."""
    week_start: date  # Monday date
    open: float
    high: float
    low: float
    close: float
    volume: int
    status: str  # "complete" or "provisional"
    bars: List[DailyBar] = field(default_factory=list)


@dataclass
class MonthlyCandle:
    """Aggregated monthly candle (calendar month)."""
    year: int
    month: int
    open: float
    high: float
    low: float
    close: float
    volume: int
    status: str  # "complete" or "provisional"
    bars: List[DailyBar] = field(default_factory=list)


@dataclass
class WeeklyIndicators:
    """Weekly technical indicators."""
    candle_status: str
    close: float
    sma_10: float
    sma_30: float
    above_sma_10: bool
    above_sma_30: bool
    rsi_14: float
    macd_line: float
    macd_signal: float
    macd_histogram: float
    atr_14: float
    atr_14_pct: float
    return_4w_pct: float
    return_13w_pct: float
    high_52w: float
    low_52w: float
    volume_vs_20w_avg: float


@dataclass
class MonthlyIndicators:
    """Monthly technical indicators."""
    candle_status: str
    close: float
    sma_10: float
    sma_20: float
    above_sma_10: bool
    above_sma_20: bool
    rsi_14: float
    macd_line: float
    macd_signal: float
    macd_histogram: float
    return_3m_pct: float
    return_12m_pct: float
    high_36m: float
    low_36m: float
    volume_vs_12m_avg: float


@dataclass
class Levels:
    """Support/resistance and risk levels."""
    weekly_support: float
    weekly_resistance: float
    extension_from_10w_pct: float
    resistance_headroom_pct: float
    support_risk_pct: float


@dataclass
class ScoreComponents:
    """Score breakdown."""
    weekly_trend: int
    monthly_trend: int
    momentum_quality: int
    entry_and_risk: int


@dataclass
class Recommendation:
    """Trading recommendation fields."""
    entry_zone_low: Optional[float]
    entry_zone_high: Optional[float]
    breakout_trigger: Optional[float]
    invalidation: Optional[float]
    confirmation_basis: str
    summary: str


@dataclass
class Methodology:
    """Methodology metadata."""
    source: str = "Robinhood MCP"
    source_tools: List[str] = field(default_factory=lambda: ["get_equity_quotes", "get_equity_historicals"])
    bounds: str = "regular"
    adjustment_type: str = "split"
    chart_timeframes: List[str] = field(default_factory=lambda: ["weekly", "monthly"])
    intraday_used: bool = False
    score_is_probability: bool = False


@dataclass
class AnalysisResult:
    """Complete analysis result."""
    request_date: str
    ticker: str
    status: str  # "ok", "not_found", "insufficient_data", "failed"
    data_as_of: Optional[str]
    price: Optional[dict]
    score: Optional[int]
    verdict: Optional[str]
    score_components: Optional[ScoreComponents]
    indicators: Optional[dict]
    levels: Optional[Levels]
    recommendation: Optional[Recommendation]
    methodology: Methodology
    warnings: List[str]

    def to_json(self) -> str:
        """Convert to JSON string."""
        return json.dumps(self._to_dict(), separators=(',', ':'), ensure_ascii=False)

    def _to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        d = {
            "request_date": self.request_date,
            "ticker": self.ticker,
            "status": self.status,
            "data_as_of": self.data_as_of,
            "price": self.price,
            "score": self.score,
            "verdict": self.verdict,
            "score_components": self.score_components.__dict__ if hasattr(self.score_components, '__dict__') else self.score_components,
            "indicators": self.indicators,
            "levels": self.levels.__dict__ if hasattr(self.levels, '__dict__') else self.levels,
            "recommendation": self.recommendation.__dict__ if hasattr(self.recommendation, '__dict__') else self.recommendation,
            "methodology": self.methodology.__dict__ if hasattr(self.methodology, '__dict__') else self.methodology,
            "warnings": self.warnings,
        }
        # Remove None values except for required fields
        return d


def create_error_result(request_date: str, ticker: str, status: str, reason: str) -> AnalysisResult:
    """Create an error result."""
    return AnalysisResult(
        request_date=request_date,
        ticker=ticker,
        status=status,
        data_as_of=None,
        price=None,
        score=None,
        verdict=None,
        score_components=None,
        indicators=None,
        levels=None,
        recommendation=None,
        methodology=Methodology(),
        warnings=[reason],
    )