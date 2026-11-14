"""
Daily bar aggregation to weekly/monthly candles.
"""

from datetime import date, timedelta
from typing import List, Optional
from collections import defaultdict

from .models import DailyBar, WeeklyCandle, MonthlyCandle


def aggregate_weekly(bars: List[DailyBar]) -> List[WeeklyCandle]:
    """Aggregate daily bars into weekly candles (Monday-Friday).
    
    Assumes bars are sorted by date ascending.
    """
    if not bars:
        return []
    
    # Group by week (Monday = week start)
    weeks = defaultdict(list)
    for bar in bars:
        # Find Monday of this week
        days_since_monday = bar.date.weekday()  # 0=Monday
        week_start = bar.date - timedelta(days=days_since_monday)
        weeks[week_start].append(bar)
    
    # Build weekly candles
    weekly_candles = []
    for week_start in sorted(weeks.keys()):
        week_bars = sorted(weeks[week_start], key=lambda b: b.date)
        
        # Only use non-interpolated bars for OHLC
        valid_bars = [b for b in week_bars if not b.interpolated]
        if not valid_bars:
            continue
        
        open_price = valid_bars[0].open
        high_price = max(b.high for b in valid_bars)
        low_price = min(b.low for b in valid_bars)
        close_price = valid_bars[-1].close
        volume = sum(b.volume for b in week_bars)
        
        # Determine if week is complete (has Friday bar and today is after Friday)
        # For now, mark as provisional if the latest bar is not Friday
        last_bar_date = week_bars[-1].date
        is_complete = last_bar_date.weekday() == 4  # Friday
        
        # If we have bars from multiple weeks and this isn't the last week, it's complete
        # (conservative: only last week can be provisional)
        
        candle = WeeklyCandle(
            week_start=week_start,
            open=open_price,
            high=high_price,
            low=low_price,
            close=close_price,
            volume=volume,
            status="complete" if is_complete else "provisional",
            bars=week_bars,
        )
        weekly_candles.append(candle)
    
    # Mark all but the last as complete
    for i in range(len(weekly_candles) - 1):
        weekly_candles[i].status = "complete"
    
    return weekly_candles


def aggregate_monthly(bars: List[DailyBar]) -> List[MonthlyCandle]:
    """Aggregate daily bars into monthly candles (calendar month).
    
    Assumes bars are sorted by date ascending.
    """
    if not bars:
        return []
    
    # Group by year-month
    months = defaultdict(list)
    for bar in bars:
        months[(bar.date.year, bar.date.month)].append(bar)
    
    # Build monthly candles
    monthly_candles = []
    for (year, month) in sorted(months.keys()):
        month_bars = sorted(months[(year, month)], key=lambda b: b.date)
        
        valid_bars = [b for b in month_bars if not b.interpolated]
        if not valid_bars:
            continue
        
        open_price = valid_bars[0].open
        high_price = max(b.high for b in valid_bars)
        low_price = min(b.low for b in valid_bars)
        close_price = valid_bars[-1].close
        volume = sum(b.volume for b in month_bars)
        
        # Determine if month is complete
        # Conservative: if it's the current month, it's provisional
        last_bar_date = month_bars[-1].date
        # Get last day of month
        if month == 12:
            month_end = date(year + 1, 1, 1) - timedelta(days=1)
        else:
            month_end = date(year, month + 1, 1) - timedelta(days=1)
        
        is_complete = last_bar_date >= month_end
        
        candle = MonthlyCandle(
            year=year,
            month=month,
            open=open_price,
            high=high_price,
            low=low_price,
            close=close_price,
            volume=volume,
            status="complete" if is_complete else "provisional",
            bars=month_bars,
        )
        monthly_candles.append(candle)
    
    # Mark all but the last as complete
    for i in range(len(monthly_candles) - 1):
        monthly_candles[i].status = "complete"
    
    return monthly_candles


def get_closes(candles) -> List[float]:
    """Extract close prices from candles."""
    return [c.close for c in candles]


def get_highs(candles) -> List[float]:
    """Extract high prices from candles."""
    return [c.high for c in candles]


def get_lows(candles) -> List[float]:
    """Extract low prices from candles."""
    return [c.low for c in candles]


def get_volumes(candles) -> List[int]:
    """Extract volumes from candles."""
    return [c.volume for c in candles]