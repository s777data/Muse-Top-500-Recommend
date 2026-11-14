"""
Main Technical Analysis Engine.
"""

from datetime import date, datetime, timedelta
from typing import Optional, List

from .models import (
    PriceData, DailyBar, WeeklyCandle, MonthlyCandle,
    WeeklyIndicators, MonthlyIndicators, Levels,
    AnalysisResult, create_error_result, ScoreComponents, Recommendation
)
from .indicators import (
    sma, rsi_wilder, macd, atr, pivot_points,
    ema
)
from .aggregation import (
    aggregate_weekly, aggregate_monthly,
    get_closes, get_highs, get_lows, get_volumes
)
from .scoring import (
    calculate_all_scores, determine_verdict, calculate_recommendation
)


class TechnicalAnalysisEngine:
    """Main engine for technical analysis."""
    
    def __init__(self, mcp_client=None):
        self.mcp_client = mcp_client
    
    def run(self, ticker: str, request_date: Optional[str] = None) -> AnalysisResult:
        """Run full technical analysis for a ticker."""
        
        if request_date is None:
            request_date = date.today().isoformat()
        
        # Normalize ticker
        ticker = ticker.upper().strip()
        
        # Step 1: Get quote data
        try:
            quote_data = self._get_quote(ticker)
            if not quote_data or quote_data.listing_state != "active" or not quote_data.has_traded:
                return create_error_result(request_date, ticker, "not_found", f"Invalid or inactive symbol: {ticker}")
        except Exception as e:
            return create_error_result(request_date, ticker, "failed", f"Quote fetch failed: {e}")
        
        # Step 2: Get historical data (8+ years)
        try:
            start_date = date.fromisoformat(request_date) - timedelta(days=8*365)
            bars = self._get_historicals(ticker, start_date.isoformat(), request_date)
            if not bars or len(bars) < 160:  # Need ~30 weeks + MACD warmup
                return create_error_result(request_date, ticker, "insufficient_data", 
                    f"Insufficient history: {len(bars) if bars else 0} bars (need ~160+)")
        except Exception as e:
            return create_error_result(request_date, ticker, "failed", f"Historicals fetch failed: {e}")
        
        # Step 3: Filter interpolated bars
        valid_bars = [b for b in bars if not b.interpolated]
        if len(valid_bars) < 160:
            return create_error_result(request_date, ticker, "insufficient_data",
                f"Insufficient non-interpolated bars: {len(valid_bars)} (need ~160+)")
        
        # Step 4: Aggregate to weekly/monthly
        weekly_candles = aggregate_weekly(valid_bars)
        monthly_candles = aggregate_monthly(valid_bars)
        
        # Need at least 30 weekly candles for SMA30, 26 monthly for MACD
        if len(weekly_candles) < 30 or len(monthly_candles) < 26:
            return create_error_result(request_date, ticker, "insufficient_data",
                f"Insufficient candles: {len(weekly_candles)} weekly, {len(monthly_candles)} monthly")
        
        # Step 5: Calculate indicators
        weekly_ind = self._calculate_weekly_indicators(weekly_candles)
        monthly_ind = self._calculate_monthly_indicators(monthly_candles)
        levels = self._calculate_levels(weekly_candles, weekly_ind)
        
        # Step 6: Calculate scores
        score_components = calculate_all_scores(weekly_ind, monthly_ind, levels)
        total_score = sum([
            score_components.weekly_trend,
            score_components.monthly_trend,
            score_components.momentum_quality,
            score_components.entry_and_risk,
        ])
        total_score = max(0, min(100, total_score))
        
        # Step 7: Determine verdict
        verdict = determine_verdict(total_score)
        
        # Step 8: Build recommendation
        recommendation = calculate_recommendation(weekly_ind, monthly_ind, levels, verdict)
        
        # Step 9: Build result
        data_as_of = weekly_candles[-1].week_start.isoformat() if weekly_candles else request_date
        
        result = AnalysisResult(
            request_date=request_date,
            ticker=ticker,
            status="ok",
            data_as_of=data_as_of,
            price={
                "regular_last_trade": quote_data.regular_last_trade,
                "regular_last_trade_at": quote_data.regular_last_trade_at,
            },
            score=total_score,
            verdict=verdict,
            score_components=score_components,
            indicators={
                "weekly": {
                    "candle_status": weekly_ind.candle_status,
                    "close": round(weekly_ind.close, 2),
                    "sma_10": round(weekly_ind.sma_10, 2),
                    "sma_30": round(weekly_ind.sma_30, 2),
                    "above_sma_10": weekly_ind.above_sma_10,
                    "above_sma_30": weekly_ind.above_sma_30,
                    "rsi_14": round(weekly_ind.rsi_14, 1),
                    "macd_12_26_9": {
                        "line": round(weekly_ind.macd_line, 2),
                        "signal": round(weekly_ind.macd_signal, 2),
                        "histogram": round(weekly_ind.macd_histogram, 2),
                    },
                    "atr_14": round(weekly_ind.atr_14, 2),
                    "atr_14_pct": round(weekly_ind.atr_14_pct, 1),
                    "return_4w_pct": round(weekly_ind.return_4w_pct, 1),
                    "return_13w_pct": round(weekly_ind.return_13w_pct, 1),
                    "high_52w": round(weekly_ind.high_52w, 2),
                    "low_52w": round(weekly_ind.low_52w, 2),
                    "volume_vs_20w_avg": round(weekly_ind.volume_vs_20w_avg, 2),
                },
                "monthly": {
                    "candle_status": monthly_ind.candle_status,
                    "close": round(monthly_ind.close, 2),
                    "sma_10": round(monthly_ind.sma_10, 2),
                    "sma_20": round(monthly_ind.sma_20, 2),
                    "above_sma_10": monthly_ind.above_sma_10,
                    "above_sma_20": monthly_ind.above_sma_20,
                    "rsi_14": round(monthly_ind.rsi_14, 1),
                    "macd_12_26_9": {
                        "line": round(monthly_ind.macd_line, 2),
                        "signal": round(monthly_ind.macd_signal, 2),
                        "histogram": round(monthly_ind.macd_histogram, 2),
                    },
                    "return_3m_pct": round(monthly_ind.return_3m_pct, 1),
                    "return_12m_pct": round(monthly_ind.return_12m_pct, 1),
                    "high_36m": round(monthly_ind.high_36m, 2),
                    "low_36m": round(monthly_ind.low_36m, 2),  # This should be low_36m - bug!
                    "volume_vs_12m_avg": round(monthly_ind.volume_vs_12m_avg, 2),
                },
            },
            levels={
                "weekly_support": round(levels.weekly_support, 2),
                "weekly_resistance": round(levels.weekly_resistance, 2),
                "extension_from_10w_pct": round(levels.extension_from_10w_pct, 1),
                "resistance_headroom_pct": round(levels.resistance_headroom_pct, 1),
                "support_risk_pct": round(levels.support_risk_pct, 1),
            },
            recommendation={
                "entry_zone": {
                    "low": recommendation.entry_zone_low,
                    "high": recommendation.entry_zone_high,
                },
                "breakout_trigger": recommendation.breakout_trigger,
                "invalidation": recommendation.invalidation,
                "confirmation_basis": recommendation.confirmation_basis,
                "summary": recommendation.summary,
            },
            methodology={
                "source": "Robinhood MCP",
                "source_tools": ["get_equity_quotes", "get_equity_historicals"],
                "bounds": "regular",
                "adjustment_type": "split",
                "chart_timeframes": ["weekly", "monthly"],
                "intraday_used": False,
                "score_is_probability": False,
            },
            warnings=[],
        )
        
        return result
    
    def _get_quote(self, ticker: str) -> Optional[PriceData]:
        """Get quote from MCP. Uses mcp_client if provided."""
        if self.mcp_client is not None:
            return self.mcp_client.get_equity_quotes([ticker])
        raise NotImplementedError("MCP client not configured")
    
    def _get_historicals(self, ticker: str, start_date: str, end_date: str) -> List[DailyBar]:
        """Get historicals from MCP. Uses mcp_client if provided."""
        if self.mcp_client is not None:
            return self.mcp_client.get_equity_historicals([ticker], start_date, end_date)
        raise NotImplementedError("MCP client not configured")
    
    def _calculate_weekly_indicators(self, candles: List[WeeklyCandle]) -> WeeklyIndicators:
        """Calculate all weekly indicators."""
        closes = get_closes(candles)
        highs = get_highs(candles)
        lows = get_lows(candles)
        volumes = get_volumes(candles)
        
        # SMAs
        sma_10 = sma(closes, 10)
        sma_30 = sma(closes, 30)
        
        # RSI
        rsi_14 = rsi_wilder(closes, 14)
        
        # MACD
        macd_line, macd_signal, macd_histogram = macd(closes, 12, 26, 9)
        
        # ATR
        atr_14 = atr(highs, lows, closes, 14)
        
        # Returns
        return_4w = 0.0
        if len(closes) >= 5:
            return_4w = ((closes[-1] / closes[-5]) - 1) * 100
        
        return_13w = 0.0
        if len(closes) >= 14:
            return_13w = ((closes[-1] / closes[-14]) - 1) * 100
        
        # 52-week high/low
        high_52w = max(highs[-52:]) if len(highs) >= 52 else max(highs)
        low_52w = min(lows[-52:]) if len(lows) >= 52 else min(lows)
        
        # Volume vs 20-week average
        volume_vs_20w = 1.0
        if len(volumes) >= 20:
            avg_20w = sum(volumes[-20:]) / 20
            volume_vs_20w = volumes[-1] / avg_20w if avg_20w > 0 else 1.0
        
        # Latest values (last candle)
        idx = -1
        latest_close = closes[idx]
        latest_sma_10 = sma_10[idx] if sma_10[idx] is not None else latest_close
        latest_sma_30 = sma_30[idx] if sma_30[idx] is not None else latest_close
        latest_rsi = rsi_14[idx] if rsi_14[idx] is not None else 50.0
        latest_macd = macd_line[idx] if macd_line[idx] is not None else 0.0
        latest_signal = macd_signal[idx] if macd_signal[idx] is not None else 0.0
        latest_hist = macd_histogram[idx] if macd_histogram[idx] is not None else 0.0
        latest_atr = atr_14[idx] if atr_14[idx] is not None else 0.0
        latest_atr_pct = (latest_atr / latest_close * 100) if latest_close > 0 else 0.0
        
        return WeeklyIndicators(
            candle_status=candles[-1].status,
            close=latest_close,
            sma_10=latest_sma_10,
            sma_30=latest_sma_30,
            above_sma_10=latest_close > latest_sma_10,
            above_sma_30=latest_close > latest_sma_30,
            rsi_14=latest_rsi,
            macd_line=latest_macd,
            macd_signal=latest_signal,
            macd_histogram=latest_hist,
            atr_14=latest_atr,
            atr_14_pct=latest_atr_pct,
            return_4w_pct=return_4w,
            return_13w_pct=return_13w,
            high_52w=high_52w,
            low_52w=low_52w,
            volume_vs_20w_avg=volume_vs_20w,
        )
    
    def _calculate_monthly_indicators(self, candles: List[MonthlyCandle]) -> MonthlyIndicators:
        """Calculate all monthly indicators."""
        closes = get_closes(candles)
        highs = get_highs(candles)
        lows = get_lows(candles)
        volumes = get_volumes(candles)
        
        # SMAs
        sma_10 = sma(closes, 10)
        sma_20 = sma(closes, 20)
        
        # RSI
        rsi_14 = rsi_wilder(closes, 14)
        
        # MACD
        macd_line, macd_signal, macd_histogram = macd(closes, 12, 26, 9)
        
        # Returns
        return_3m = 0.0
        if len(closes) >= 4:
            return_3m = ((closes[-1] / closes[-4]) - 1) * 100
        
        return_12m = 0.0
        if len(closes) >= 13:
            return_12m = ((closes[-1] / closes[-13]) - 1) * 100
        
        # 36-month high/low
        high_36m = max(highs[-36:]) if len(highs) >= 36 else max(highs)
        low_36m = min(lows[-36:]) if len(lows) >= 36 else min(lows)
        
        # Volume vs 12-month average
        volume_vs_12m = 1.0
        if len(volumes) >= 12:
            avg_12m = sum(volumes[-12:]) / 12
            volume_vs_12m = volumes[-1] / avg_12m if avg_12m > 0 else 1.0
        
        # Latest values
        idx = -1
        latest_close = closes[idx]
        latest_sma_10 = sma_10[idx] if sma_10[idx] is not None else latest_close
        latest_sma_20 = sma_20[idx] if sma_20[idx] is not None else latest_close
        latest_rsi = rsi_14[idx] if rsi_14[idx] is not None else 50.0
        latest_macd = macd_line[idx] if macd_line[idx] is not None else 0.0
        latest_signal = macd_signal[idx] if macd_signal[idx] is not None else 0.0
        latest_hist = macd_histogram[idx] if macd_histogram[idx] is not None else 0.0
        
        return MonthlyIndicators(
            candle_status=candles[-1].status,
            close=latest_close,
            sma_10=latest_sma_10,
            sma_20=latest_sma_20,
            above_sma_10=latest_close > latest_sma_10,
            above_sma_20=latest_close > latest_sma_20,
            rsi_14=latest_rsi,
            macd_line=latest_macd,
            macd_signal=latest_signal,
            macd_histogram=latest_hist,
            return_3m_pct=return_3m,
            return_12m_pct=return_12m,
            high_36m=high_36m,
            low_36m=low_36m,
            volume_vs_12m_avg=volume_vs_12m,
        )
    
    def _calculate_levels(self, candles: List[WeeklyCandle], weekly_ind: WeeklyIndicators) -> Levels:
        """Calculate support/resistance and risk levels."""
        highs = get_highs(candles)
        lows = get_lows(candles)
        closes = get_closes(candles)
        
        # Find pivot points in last 52 weeks
        lookback = min(52, len(candles))
        recent_highs = highs[-lookback:]
        recent_lows = lows[-lookback:]
        
        pivot_highs, pivot_lows = pivot_points(recent_highs, recent_lows, window=2)
        
        latest_close = closes[-1]
        
        # Support: nearest pivot low below close, fallback to 52w low
        support = weekly_ind.low_52w
        for p_idx in reversed(pivot_lows):
            abs_idx = len(candles) - lookback + p_idx
            if abs_idx < len(lows) and lows[abs_idx] < latest_close:
                support = lows[abs_idx]
                break
        
        # Resistance: nearest pivot high above close, fallback to 52w high
        resistance = weekly_ind.high_52w
        for p_idx in pivot_highs:
            abs_idx = len(candles) - lookback + p_idx
            if abs_idx < len(highs) and highs[abs_idx] > latest_close:
                resistance = highs[abs_idx]
                break
        
        # Extension from 10w SMA
        extension_pct = ((latest_close / weekly_ind.sma_10) - 1) * 100 if weekly_ind.sma_10 > 0 else 0.0
        
        # Resistance headroom
        resistance_headroom = ((resistance / latest_close) - 1) * 100 if latest_close > 0 else 0.0
        
        # Support risk
        support_risk = ((latest_close / support) - 1) * 100 if support > 0 else 0.0
        
        return Levels(
            weekly_support=support,
            weekly_resistance=resistance,
            extension_from_10w_pct=extension_pct,
            resistance_headroom_pct=resistance_headroom,
            support_risk_pct=support_risk,
        )


def run_analysis(ticker: str, mcp_client=None, request_date: Optional[str] = None) -> AnalysisResult:
    """Convenience function to run analysis."""
    engine = TechnicalAnalysisEngine(mcp_client)
    return engine.run(ticker, request_date)