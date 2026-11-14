"""
Deterministic scoring logic per the specification.
"""

from typing import Optional
from .models import WeeklyIndicators, MonthlyIndicators, Levels, ScoreComponents, Recommendation


def calculate_weekly_trend_score(weekly: WeeklyIndicators) -> int:
    """Calculate weekly trend component (max 30 points)."""
    score = 0
    
    # Close above 10-week SMA: +8
    if weekly.above_sma_10:
        score += 8
    
    # Close above 30-week SMA: +8
    if weekly.above_sma_30:
        score += 8
    
    # 10-week SMA above 30-week SMA: +6
    if weekly.sma_10 > weekly.sma_30:
        score += 6
    
    # 13-week return
    if weekly.return_13w_pct > 0:
        score += 4
    elif weekly.return_13w_pct >= -5:
        score += 2
    # else: +0
    
    # Weekly MACD histogram > 0: +4
    if weekly.macd_histogram > 0:
        score += 4
    
    return min(score, 30)


def calculate_monthly_trend_score(monthly: MonthlyIndicators) -> int:
    """Calculate monthly trend component (max 30 points)."""
    score = 0
    
    # Close above 10-month SMA: +8
    if monthly.above_sma_10:
        score += 8
    
    # Close above 20-month SMA: +8
    if monthly.above_sma_20:
        score += 8
    
    # 10-month SMA above 20-month SMA: +6
    if monthly.sma_10 > monthly.sma_20:
        score += 6
    
    # 12-month return
    if monthly.return_12m_pct > 0:
        score += 4
    elif monthly.return_12m_pct >= -5:
        score += 2
    # else: +0
    
    # Monthly MACD histogram > 0: +4
    if monthly.macd_histogram > 0:
        score += 4
    
    return min(score, 30)


def score_rsi(rsi: float) -> int:
    """Score a single RSI value."""
    if 50 <= rsi <= 65:
        return 6
    elif 45 <= rsi <= 70:
        return 4
    elif 40 <= rsi <= 75:
        return 2
    return 0


def score_return(ret_pct: float) -> int:
    """Score a return percentage."""
    if 0 <= ret_pct <= 12:
        return 4
    elif -5 <= ret_pct < 0:
        return 2
    elif 12 < ret_pct <= 30:
        return 2
    return 0


def calculate_momentum_quality_score(weekly: WeeklyIndicators, monthly: MonthlyIndicators) -> int:
    """Calculate momentum quality component (max 20 points)."""
    score = 0
    
    # Weekly RSI: max 6
    score += score_rsi(weekly.rsi_14)
    
    # Monthly RSI: max 6
    score += score_rsi(monthly.rsi_14)
    
    # 4-week return: max 4
    score += score_return(weekly.return_4w_pct)
    
    # 3-month return: max 4
    score += score_return(monthly.return_3m_pct)
    
    return min(score, 20)


def calculate_entry_risk_score(weekly: WeeklyIndicators, levels: Levels) -> int:
    """Calculate entry and risk component (max 20 points)."""
    score = 0
    
    # Extension from 10-week SMA
    ext = weekly.extension_from_10w_pct if hasattr(weekly, 'extension_from_10w_pct') else levels.extension_from_10w_pct
    if 0 <= ext <= 5:
        score += 6
    elif 5 < ext <= 10:
        score += 4
    elif 10 < ext <= 15:
        score += 2
    elif -3 <= ext < 0:
        score += 4
    # else: +0
    
    # ATR 14% score
    atr_pct = weekly.atr_14_pct
    if atr_pct <= 4:
        score += 6
    elif atr_pct <= 7:
        score += 5
    elif atr_pct <= 10:
        score += 3
    else:
        score += 1
    
    # Resistance headroom
    rh = levels.resistance_headroom_pct
    if 3 <= rh <= 10:
        score += 4
    elif 0 <= rh < 3:
        score += 2
    elif 10 < rh <= 20:
        score += 3
    elif rh > 20:
        score += 1
    # else (negative): +0
    
    # Support risk
    sr = levels.support_risk_pct
    if sr <= 5:
        score += 4
    elif sr <= 8:
        score += 3
    elif sr <= 12:
        score += 2
    else:
        score += 1
    
    return min(score, 20)


def calculate_all_scores(weekly: WeeklyIndicators, monthly: MonthlyIndicators, levels: Levels) -> ScoreComponents:
    """Calculate all four score components."""
    weekly_trend = calculate_weekly_trend_score(weekly)
    monthly_trend = calculate_monthly_trend_score(monthly)
    momentum_quality = calculate_momentum_quality_score(weekly, monthly)
    entry_and_risk = calculate_entry_risk_score(weekly, levels)
    
    return ScoreComponents(
        weekly_trend=weekly_trend,
        monthly_trend=monthly_trend,
        momentum_quality=momentum_quality,
        entry_and_risk=entry_and_risk,
    )


def determine_verdict(total_score: int) -> str:
    """Map score to verdict."""
    if total_score >= 90:
        return "STRONG_BUY"
    elif total_score >= 85:
        return "BUY"
    elif total_score >= 75:
        return "CONDITIONAL_BUY"
    elif total_score >= 60:
        return "WATCH"
    elif total_score >= 40:
        return "WAIT"
    else:
        return "AVOID"


def calculate_recommendation(weekly: WeeklyIndicators, monthly: MonthlyIndicators, levels: Levels, verdict: str) -> Recommendation:
    """Calculate recommendation fields."""
    entry_zone_low = None
    entry_zone_high = None
    breakout_trigger = None
    invalidation = None
    
    if verdict in ("STRONG_BUY", "BUY", "CONDITIONAL_BUY"):
        entry_zone_low = round(levels.weekly_support, 2)
        entry_zone_high = round(weekly.sma_10, 2)
        if entry_zone_high < entry_zone_low:
            entry_zone_high = round(weekly.close, 2)
        
        if levels.weekly_resistance > weekly.close:
            breakout_trigger = round(levels.weekly_resistance, 2)
        
        invalidation = round(min(levels.weekly_support, weekly.sma_30), 2)
    
    elif verdict in ("WAIT", "AVOID"):
        pass
    
    else:  # WATCH
        invalidation = round(min(levels.weekly_support, weekly.sma_30), 2)
    
    # Build narrative reasoning summary
    summary = _build_reasoning_summary(weekly, monthly, levels, verdict)
    
    return Recommendation(
        entry_zone_low=entry_zone_low,
        entry_zone_high=entry_zone_high,
        breakout_trigger=breakout_trigger,
        invalidation=invalidation,
        confirmation_basis="weekly_close",
        summary=summary,
    )


def _build_reasoning_summary(weekly: WeeklyIndicators, monthly: MonthlyIndicators, levels: Levels, verdict: str) -> str:
    """Build a concise narrative reasoning for the verdict."""
    parts = []
    
    # Determine weekly trend state
    weekly_below_both = not weekly.above_sma_10 and not weekly.above_sma_30
    weekly_below_30_only = weekly.above_sma_10 and not weekly.above_sma_30
    weekly_above_both = weekly.above_sma_10 and weekly.above_sma_30
    
    # Determine monthly trend state
    monthly_below_both = not monthly.above_sma_10 and not monthly.above_sma_20
    monthly_below_20_only = monthly.above_sma_10 and not monthly.above_sma_20
    monthly_above_both = monthly.above_sma_10 and monthly.above_sma_20
    
    # Weekly trend description
    if weekly_below_both:
        parts.append(f"price below both 10w/30w SMAs ({weekly.sma_10:.1f}/{weekly.sma_30:.1f})")
    elif weekly_below_30_only:
        parts.append(f"price above 10w SMA ({weekly.sma_10:.1f}) but below 30w SMA ({weekly.sma_30:.1f})")
    else:
        parts.append(f"price above both 10w/30w SMAs ({weekly.sma_10:.1f}/{weekly.sma_30:.1f})")
    
    # Weekly MACD
    if weekly.macd_histogram <= 0:
        parts.append(f"weekly MACD histogram negative ({weekly.macd_histogram:.2f})")
    else:
        parts.append(f"weekly MACD histogram barely positive ({weekly.macd_histogram:.2f})")
    
    # 13-week return
    if weekly.return_13w_pct < -5:
        parts.append(f"13w return {weekly.return_13w_pct:.1f}%")
    elif weekly.return_13w_pct < 0:
        parts.append(f"13w return slightly negative ({weekly.return_13w_pct:.1f}%)")
    else:
        parts.append(f"13w return positive ({weekly.return_13w_pct:.1f}%)")
    
    # Monthly trend description
    if monthly_below_both:
        parts.append(f"monthly price below both 10m/20m SMAs ({monthly.sma_10:.1f}/{monthly.sma_20:.1f})")
    elif monthly_below_20_only:
        parts.append(f"monthly price above 10m SMA ({monthly.sma_10:.1f}) but below 20m SMA ({monthly.sma_20:.1f})")
    else:
        parts.append(f"monthly price above both 10m/20m SMAs ({monthly.sma_10:.1f}/{monthly.sma_20:.1f})")
    
    # Monthly MACD
    if monthly.macd_histogram <= 0:
        parts.append(f"monthly MACD histogram negative ({monthly.macd_histogram:.2f})")
    else:
        parts.append(f"monthly MACD histogram positive ({monthly.macd_histogram:.2f})")
    
    # 12-month return
    if monthly.return_12m_pct < -5:
        parts.append(f"12m return {monthly.return_12m_pct:.1f}%")
    elif monthly.return_12m_pct < 0:
        parts.append(f"12m return slightly negative ({monthly.return_12m_pct:.1f}%)")
    else:
        parts.append(f"12m return positive ({monthly.return_12m_pct:.1f}%)")
    
    # RSI summary
    rsi_desc = []
    if weekly.rsi_14 < 40:
        rsi_desc.append(f"weekly RSI oversold ({weekly.rsi_14:.1f})")
    elif weekly.rsi_14 > 70:
        rsi_desc.append(f"weekly RSI overbought ({weekly.rsi_14:.1f})")
    else:
        rsi_desc.append(f"weekly RSI neutral ({weekly.rsi_14:.1f})")
    
    if monthly.rsi_14 < 40:
        rsi_desc.append(f"monthly RSI oversold ({monthly.rsi_14:.1f})")
    elif monthly.rsi_14 > 70:
        rsi_desc.append(f"monthly RSI overbought ({monthly.rsi_14:.1f})")
    else:
        rsi_desc.append(f"monthly RSI neutral ({monthly.rsi_14:.1f})")
    
    parts.append("; ".join(rsi_desc))
    
    # Extension from 10w SMA
    ext = levels.extension_from_10w_pct
    if ext < -3:
        parts.append(f"price {abs(ext):.1f}% below 10w SMA (oversold extension)")
    elif ext > 15:
        parts.append(f"price {ext:.1f}% above 10w SMA (overextended)")
    elif ext > 10:
        parts.append(f"price {ext:.1f}% above 10w SMA (moderately extended)")
    elif ext > 5:
        parts.append(f"price {ext:.1f}% above 10w SMA (slightly extended)")
    elif ext >= 0:
        parts.append(f"price {ext:.1f}% above 10w SMA")
    else:
        parts.append(f"price {abs(ext):.1f}% below 10w SMA")
    
    # Resistance headroom
    rh = levels.resistance_headroom_pct
    if rh > 20:
        parts.append(f"large resistance headroom ({rh:.1f}%)")
    elif rh > 10:
        parts.append(f"moderate resistance headroom ({rh:.1f}%)")
    elif rh > 3:
        parts.append(f"tight resistance headroom ({rh:.1f}%)")
    elif rh >= 0:
        parts.append(f"price at/near resistance ({rh:.1f}% headroom)")
    else:
        parts.append(f"price above resistance ({abs(rh):.1f}%)")
    
    # Support risk
    sr = levels.support_risk_pct
    if sr > 12:
        parts.append(f"high support risk ({sr:.1f}% to support)")
    elif sr > 8:
        parts.append(f"moderate support risk ({sr:.1f}% to support)")
    elif sr > 5:
        parts.append(f"low support risk ({sr:.1f}% to support)")
    else:
        parts.append(f"very low support risk ({sr:.1f}% to support)")
    
    # Now synthesize into narrative
    return _synthesize_narrative(parts, verdict, weekly, monthly, levels)


def _synthesize_narrative(parts: list, verdict: str, weekly: WeeklyIndicators, monthly: MonthlyIndicators, levels: Levels) -> str:
    """Synthesize raw parts into a coherent narrative paragraph."""
    
    # Determine overall trend assessment
    weekly_downtrend = not weekly.above_sma_10 and not weekly.above_sma_30
    monthly_downtrend = not monthly.above_sma_10 and not monthly.above_sma_20
    weekly_uptrend = weekly.above_sma_10 and weekly.above_sma_30
    monthly_uptrend = monthly.above_sma_10 and monthly.above_sma_20
    
    # Build narrative
    narrative_parts = []
    
    # Opening: overall trend assessment
    if weekly_downtrend and monthly_downtrend:
        narrative_parts.append(f"{verdict}: in a confirmed downtrend on both weekly and monthly timeframes")
    elif weekly_downtrend and not monthly_downtrend:
        narrative_parts.append(f"{verdict}: weekly downtrend but monthly trend mixed")
    elif not weekly_downtrend and monthly_downtrend:
        narrative_parts.append(f"{verdict}: monthly downtrend but weekly trend mixed")
    elif weekly_uptrend and monthly_uptrend:
        narrative_parts.append(f"{verdict}: in a confirmed uptrend on both weekly and monthly timeframes")
    else:
        narrative_parts.append(f"{verdict}: mixed trend signals across timeframes")
    
    # Key drivers
    drivers = []
    
    # Price vs MAs
    if weekly_downtrend:
        drivers.append("price below all key weekly MAs")
    elif weekly_uptrend:
        drivers.append("price above all key weekly MAs")
    
    if monthly_downtrend:
        drivers.append("price below all key monthly MAs")
    elif monthly_uptrend:
        drivers.append("price above all key monthly MAs")
    
    # MACD
    if monthly.macd_histogram < -10:
        drivers.append("strongly negative monthly MACD")
    elif monthly.macd_histogram < 0:
        drivers.append("negative monthly MACD")
    elif monthly.macd_histogram > 10:
        drivers.append("strongly positive monthly MACD")
    elif monthly.macd_histogram > 0:
        drivers.append("positive monthly MACD")
    
    if weekly.macd_histogram > 0 and weekly.macd_histogram < 1:
        drivers.append("weekly MACD histogram barely positive")
    elif weekly.macd_histogram <= 0:
        drivers.append("negative weekly MACD")
    
    # Returns
    if monthly.return_12m_pct < -15:
        drivers.append(f"{abs(monthly.return_12m_pct):.0f}% yearly decline")
    elif monthly.return_12m_pct < -5:
        drivers.append(f"{abs(monthly.return_12m_pct):.0f}% yearly decline")
    elif monthly.return_12m_pct > 15:
        drivers.append(f"{monthly.return_12m_pct:.0f}% yearly gain")
    
    # Counter-signals (positive signals in a negative context, or vice versa)
    counter_signals = []
    
    if weekly_downtrend and weekly.macd_histogram > 0:
        counter_signals.append("weekly MACD histogram ticking positive")
    
    ext = levels.extension_from_10w_pct
    if weekly_downtrend and ext < -3:
        counter_signals.append(f"modest oversold extension vs 10w SMA ({abs(ext):.1f}%)")
    elif weekly_uptrend and ext > 10:
        counter_signals.append(f"overextended above 10w SMA ({ext:.1f}%)")
    
    if weekly.rsi_14 < 40 and weekly_downtrend:
        counter_signals.append("weekly RSI oversold")
    
    # Assemble final narrative
    if drivers:
        narrative_parts.append("(" + "; ".join(drivers) + ")")
    
    if counter_signals:
        narrative_parts.append("The only slightly positive signal" if len(counter_signals) == 1 else "The only slightly positive signals")
        narrative_parts.append("are " + " and ".join(counter_signals) + ".")
    else:
        narrative_parts.append("No meaningful counter-signals present.")
    
    return " ".join(narrative_parts)