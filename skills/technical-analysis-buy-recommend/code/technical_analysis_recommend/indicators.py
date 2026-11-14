"""
Technical indicator calculations.
"""

from typing import List, Optional
import math


def sma(values: List[float], period: int) -> List[Optional[float]]:
    """Simple Moving Average. Returns list aligned with input (None for insufficient data)."""
    result = [None] * len(values)
    if len(values) < period:
        return result
    for i in range(period - 1, len(values)):
        result[i] = sum(values[i - period + 1:i + 1]) / period
    return result


def ema(values: List[float], period: int) -> List[Optional[float]]:
    """Exponential Moving Average."""
    result = [None] * len(values)
    if len(values) < period:
        return result
    multiplier = 2.0 / (period + 1)
    # Start with SMA for first value
    result[period - 1] = sum(values[:period]) / period
    for i in range(period, len(values)):
        result[i] = (values[i] - result[i - 1]) * multiplier + result[i - 1]
    return result


def rsi_wilder(closes: List[float], period: int = 14) -> List[Optional[float]]:
    """Wilder's RSI (smoothed)."""
    result = [None] * len(closes)
    if len(closes) < period + 1:
        return result
    
    gains = []
    losses = []
    for i in range(1, len(closes)):
        change = closes[i] - closes[i - 1]
        gains.append(max(change, 0))
        losses.append(max(-change, 0))
    
    # Initial average
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    
    for i in range(period, len(gains)):
        if i == period:
            rs = avg_gain / avg_loss if avg_loss != 0 else float('inf')
        else:
            avg_gain = (avg_gain * (period - 1) + gains[i]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i]) / period
            rs = avg_gain / avg_loss if avg_loss != 0 else float('inf')
        
        if rs == float('inf'):
            result[i + 1] = 100.0
        else:
            result[i + 1] = 100.0 - (100.0 / (1.0 + rs))
    
    return result


def macd(closes: List[float], fast: int = 12, slow: int = 26, signal: int = 9) -> tuple:
    """MACD line, signal, histogram."""
    ema_fast = ema(closes, fast)
    ema_slow = ema(closes, slow)
    
    macd_line = [None] * len(closes)
    for i in range(len(closes)):
        if ema_fast[i] is not None and ema_slow[i] is not None:
            macd_line[i] = ema_fast[i] - ema_slow[i]
    
    # Signal line is EMA of MACD line
    macd_values = [v for v in macd_line if v is not None]
    if len(macd_values) < signal:
        signal_line = [None] * len(closes)
        histogram = [None] * len(closes)
    else:
        signal_ema = ema(macd_values, signal)
        # Align signal line
        signal_line = [None] * len(closes)
        offset = slow - 1  # MACD starts at slow-1
        for i, v in enumerate(signal_ema):
            idx = i + offset + signal - 1
            if idx < len(signal_line):
                signal_line[idx] = v
        
        histogram = [None] * len(closes)
        for i in range(len(closes)):
            if macd_line[i] is not None and signal_line[i] is not None:
                histogram[i] = macd_line[i] - signal_line[i]
    
    return macd_line, signal_line, histogram


def atr(highs: List[float], lows: List[float], closes: List[float], period: int = 14) -> List[Optional[float]]:
    """Average True Range (Wilder's smoothing)."""
    result = [None] * len(closes)
    if len(closes) < period + 1:
        return result
    
    true_ranges = []
    for i in range(1, len(closes)):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1])
        )
        true_ranges.append(tr)
    
    # Initial ATR is simple average
    atr_val = sum(true_ranges[:period]) / period
    result[period] = atr_val
    
    for i in range(period + 1, len(true_ranges)):
        atr_val = (atr_val * (period - 1) + true_ranges[i]) / period
        result[i + 1] = atr_val
    
    return result


def pivot_points(highs: List[float], lows: List[float], window: int = 2) -> tuple:
    """Find swing pivots with given wing window.
    
    Returns (pivot_highs_indices, pivot_lows_indices) where each is a list of indices.
    """
    pivot_highs = []
    pivot_lows = []
    
    for i in range(window, len(highs) - window):
        # Pivot high
        is_pivot_high = all(highs[i] > highs[i - j] for j in range(1, window + 1)) and \
                       all(highs[i] > highs[i + j] for j in range(1, window + 1))
        if is_pivot_high:
            pivot_highs.append(i)
        
        # Pivot low
        is_pivot_low = all(lows[i] < lows[i - j] for j in range(1, window + 1)) and \
                      all(lows[i] < lows[i + j] for j in range(1, window + 1))
        if is_pivot_low:
            pivot_lows.append(i)
    
    return pivot_highs, pivot_lows