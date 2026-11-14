"""
Tests for technical_analysis_recommend package.
"""

import pytest
from datetime import date, timedelta

from technical_analysis_recommend.models import DailyBar, WeeklyCandle, MonthlyCandle
from technical_analysis_recommend.aggregation import aggregate_weekly, aggregate_monthly
from technical_analysis_recommend.indicators import sma, rsi_wilder, macd, atr, pivot_points
from technical_analysis_recommend.scoring import (
    calculate_weekly_trend_score,
    calculate_monthly_trend_score,
    calculate_momentum_quality_score,
    calculate_entry_risk_score,
    calculate_all_scores,
    determine_verdict,
)
from technical_analysis_recommend.models import WeeklyIndicators, MonthlyIndicators, Levels


class TestAggregation:
    """Test daily bar aggregation."""
    
    def make_bars(self, start_date: date, count: int) -> list:
        """Create synthetic daily bars."""
        bars = []
        for i in range(count):
            d = start_date + timedelta(days=i)
            # Skip weekends
            if d.weekday() >= 5:
                continue
            bars.append(DailyBar(
                date=d,
                open=100 + i * 0.1,
                high=101 + i * 0.1,
                low=99 + i * 0.1,
                close=100.5 + i * 0.1,
                volume=1000000,
                interpolated=False,
            ))
        return bars
    
    def test_weekly_aggregation(self):
        """Test weekly candle aggregation."""
        start = date(2024, 1, 1)  # Monday
        bars = self.make_bars(start, 30)  # ~6 weeks
        weekly = aggregate_weekly(bars)
        
        assert len(weekly) >= 4
        # First candle should be complete (not the last)
        assert weekly[0].status == "complete"
        # Check OHLC logic
        assert weekly[0].open == bars[0].open
        assert weekly[0].close == bars[4].close  # Friday
        assert weekly[0].high == max(b.high for b in bars[:5])
        assert weekly[0].low == min(b.low for b in bars[:5])
    
    def test_monthly_aggregation(self):
        """Test monthly candle aggregation."""
        start = date(2024, 1, 1)
        bars = self.make_bars(start, 90)  # ~3 months
        monthly = aggregate_monthly(bars)
        
        assert len(monthly) >= 2
        assert monthly[0].year == 2024
        assert monthly[0].month == 1
        assert monthly[0].status == "complete"


class TestIndicators:
    """Test indicator calculations."""
    
    def test_sma(self):
        """Test SMA calculation."""
        values = [10, 11, 12, 13, 14, 15]
        result = sma(values, 3)
        assert result[:2] == [None, None]
        assert result[2] == 11.0
        assert result[3] == 12.0
        assert result[4] == 13.0
        assert result[5] == 14.0
    
    def test_rsi_wilder(self):
        """Test Wilder RSI."""
        # Steadily rising prices
        closes = [100 + i for i in range(20)]
        rsi = rsi_wilder(closes, 14)
        # RSI should be high (near 100) for steady gains
        assert rsi[-1] is not None
        assert rsi[-1] > 70
        
        # Steadily falling prices
        closes = [120 - i for i in range(20)]
        rsi = rsi_wilder(closes, 14)
        assert rsi[-1] is not None
        assert rsi[-1] < 30
    
    def test_macd(self):
        """Test MACD."""
        closes = [100 + i * 0.5 for i in range(50)]
        macd_line, signal, hist = macd(closes)
        assert macd_line[-1] is not None
        assert signal[-1] is not None
        assert hist[-1] is not None
        assert abs(macd_line[-1] - signal[-1] - hist[-1]) < 0.01
    
    def test_atr(self):
        """Test ATR."""
        highs = [102, 103, 104, 105, 106] * 10
        lows = [98, 97, 96, 95, 94] * 10
        closes = [100, 100, 100, 100, 100] * 10
        atr_vals = atr(highs, lows, closes, 14)
        assert atr_vals[-1] is not None
        assert atr_vals[-1] > 0
    
    def test_pivot_points(self):
        """Test pivot point detection."""
        # Create pattern with clear pivots
        # High pivot at index 2 (105): must exceed indices 0,1 and 3,4
        highs = [100, 101, 105, 103, 102, 101, 100, 99, 104, 102, 101]
        # Low pivot at index 6 (94): must be below indices 4,5 and 7,8
        # lows[4]=98, lows[5]=99, lows[6]=94, lows[7]=95, lows[8]=96
        lows = [95, 94, 96, 97, 98, 99, 94, 95, 96, 97, 98]
        pivot_highs, pivot_lows = pivot_points(highs, lows, window=2)
        assert 2 in pivot_highs
        assert 6 in pivot_lows


class TestScoring:
    """Test scoring logic."""
    
    def make_weekly(self, **kwargs) -> WeeklyIndicators:
        defaults = {
            "candle_status": "complete",
            "close": 100.0,
            "sma_10": 98.0,
            "sma_30": 95.0,
            "above_sma_10": True,
            "above_sma_30": True,
            "rsi_14": 55.0,
            "macd_line": 1.0,
            "macd_signal": 0.5,
            "macd_histogram": 0.5,
            "atr_14": 2.0,
            "atr_14_pct": 2.0,
            "return_4w_pct": 3.0,
            "return_13w_pct": 10.0,
            "high_52w": 110.0,
            "low_52w": 90.0,
            "volume_vs_20w_avg": 1.0,
        }
        defaults.update(kwargs)
        return WeeklyIndicators(**defaults)
    
    def make_monthly(self, **kwargs) -> MonthlyIndicators:
        defaults = {
            "candle_status": "complete",
            "close": 100.0,
            "sma_10": 97.0,
            "sma_20": 94.0,
            "above_sma_10": True,
            "above_sma_20": True,
            "rsi_14": 58.0,
            "macd_line": 2.0,
            "macd_signal": 1.0,
            "macd_histogram": 1.0,
            "return_3m_pct": 5.0,
            "return_12m_pct": 15.0,
            "high_36m": 115.0,
            "low_36m": 85.0,
            "volume_vs_12m_avg": 1.0,
        }
        defaults.update(kwargs)
        return MonthlyIndicators(**defaults)
    
    def make_levels(self, **kwargs) -> Levels:
        defaults = {
            "weekly_support": 92.0,
            "weekly_resistance": 108.0,
            "extension_from_10w_pct": 2.0,
            "resistance_headroom_pct": 8.0,
            "support_risk_pct": 8.0,
        }
        defaults.update(kwargs)
        return Levels(**defaults)
    
    def test_weekly_trend_max_score(self):
        """Test weekly trend with all bullish conditions."""
        weekly = self.make_weekly(
            above_sma_10=True,
            above_sma_30=True,
            return_13w_pct=10.0,
            macd_histogram=0.5,
        )
        score = calculate_weekly_trend_score(weekly)
        # 8 + 8 + 6 + 4 + 4 = 30
        assert score == 30
    
    def test_monthly_trend_max_score(self):
        """Test monthly trend with all bullish conditions."""
        monthly = self.make_monthly(
            above_sma_10=True,
            above_sma_20=True,
            return_12m_pct=15.0,
            macd_histogram=1.0,
        )
        score = calculate_monthly_trend_score(monthly)
        # 8 + 8 + 6 + 4 + 4 = 30
        assert score == 30
    
    def test_momentum_quality_max_score(self):
        """Test momentum quality max score."""
        weekly = self.make_weekly(rsi_14=55.0, return_4w_pct=5.0)
        monthly = self.make_monthly(rsi_14=58.0, return_3m_pct=5.0)
        score = calculate_momentum_quality_score(weekly, monthly)
        # 6 + 6 + 4 + 4 = 20
        assert score == 20
    
    def test_entry_risk_max_score(self):
        """Test entry and risk max score."""
        weekly = self.make_weekly(atr_14_pct=3.0)
        levels = self.make_levels(
            extension_from_10w_pct=2.0,
            resistance_headroom_pct=5.0,
            support_risk_pct=3.0,
        )
        score = calculate_entry_risk_score(weekly, levels)
        # 6 + 6 + 4 + 4 = 20
        assert score == 20
    
    def test_all_scores_integration(self):
        """Test full score calculation."""
        weekly = self.make_weekly()
        monthly = self.make_monthly()
        levels = self.make_levels()
        
        components = calculate_all_scores(weekly, monthly, levels)
        total = sum([components.weekly_trend, components.monthly_trend, 
                    components.momentum_quality, components.entry_and_risk])
        
        assert total <= 100
        assert total >= 0
    
    def test_verdict_mapping(self):
        """Test verdict mapping."""
        assert determine_verdict(95) == "STRONG_BUY"
        assert determine_verdict(87) == "BUY"
        assert determine_verdict(80) == "CONDITIONAL_BUY"
        assert determine_verdict(70) == "WATCH"
        assert determine_verdict(50) == "WAIT"
        assert determine_verdict(20) == "AVOID"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])