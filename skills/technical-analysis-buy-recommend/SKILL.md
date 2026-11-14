<!-- COPIED SOURCE SKILL (s777data/options-wheel-agent @0b0d64a, skills/trading-hermes-generated/technical-analysis-buy-recommend/SKILL.md, git blob 52162886639596e9c4357e1de1214d54b430846e, SHA-verified 2026-11-14). In this repo the package under code/ is invoked DIRECTLY as code (scripts/technical_adapter.py); the Hermes-agent wrapper described below is NOT used. -->

---
name: technical-analysis-buy-recommend
description: Analyze one US equity ticker with Robinhood MCP regular-session data, construct weekly and monthly charts without hourly or intraday bars, calculate a deterministic 0-100 technical score and verdict, and return strict JSON. Use for single-ticker higher-timeframe technical recommendations; do not use for order placement, portfolio advice, or fundamental valuation.
---

# Technical Analysis Recommend

Analyze exactly one user-supplied equity ticker. Normalize it to uppercase and return JSON only. Do not rank it against other securities.

Use Robinhood MCP as the only market-data source. This skill is read-only: do not access accounts, positions, tax lots, watchlists, or orders, and never review, preview, place, replace, cancel, or exercise a trade. Do not substitute Yahoo Finance, TradingView, web search, or another provider when Robinhood data is unavailable.

## Required data

1. Set `request_date` to the current date in the user's timezone as `YYYY-MM-DD`.
2. Call `get_equity_quotes` for the normalized ticker. Use the regular-hours `last_trade_price` as the displayed price and preserve its timestamp. Reject a symbol whose listing state is not `active` or whose `has_traded` value is false.
3. Call `get_equity_historicals` with:
   - the single ticker;
   - `interval: day`;
   - `bounds: regular`;
   - `adjustment_type: split`;
   - a start date at least eight years before `request_date`, or the maximum available history for a younger security;
   - an end time covering `request_date`.
4. Ignore bars where `interpolated` is true. Require enough observations for a 30-week SMA and a 26-month MACD with a 9-month signal warm-up. Return `insufficient_data` rather than fabricating a score when history is inadequate.

Do not request or inspect hourly, minute, extended-hours, overnight, or other intraday bars. A quote snapshot may establish the displayed price but must not drive a chart indicator.

## Construct the charts

Aggregate the Robinhood daily bars locally:

- Weekly candles: Monday through Friday regular-session OHLCV, labeled by the Monday date.
- Monthly candles: calendar-month regular-session OHLCV, labeled `YYYY-MM`.

Use all available daily bars through `data_as_of`, including the current partial week or month, and state whether each final candle is `complete` or `provisional`. Determine completion from the US exchange calendar when available. If completion cannot be verified, conservatively label the candle `provisional`.

Calculate with full precision and round only the JSON presentation values:

### Weekly indicators

- 10-week simple moving average.
- 30-week simple moving average.
- Wilder RSI(14).
- MACD(12,26,9): line, signal, and histogram.
- ATR(14) as the simple mean of the latest 14 weekly true ranges; also return `atr_14_pct = ATR / weekly_close * 100`.
- Four-week and 13-week close-to-close returns.
- Trailing 52-week high and low.
- Weekly volume divided by the trailing 20-week average volume.

### Monthly indicators

- 10-month simple moving average.
- 20-month simple moving average.
- Wilder RSI(14).
- MACD(12,26,9): line, signal, and histogram.
- Three-month and 12-month close-to-close returns.
- Trailing 36-month high and low.
- Current monthly volume divided by the trailing 12-month average volume. Treat this cautiously when the monthly candle is provisional.

### Weekly support and resistance

Within the latest 52 weekly candles, identify two-sided swing pivots with a two-bar wing:

- A pivot high must exceed both of the two preceding and two following weekly highs.
- A pivot low must be below both of the two preceding and two following weekly lows.
- Support is the nearest pivot low below the latest weekly close; fall back to the 52-week low.
- Resistance is the nearest pivot high above the latest weekly close; fall back to the 52-week high.

## Deterministic score

Calculate the four components below. The maximum total is 100. Clamp the final integer score to `[0,100]`.

### Weekly trend: 30 points

- Close above 10-week SMA: `+8`.
- Close above 30-week SMA: `+8`.
- 10-week SMA above 30-week SMA: `+6`.
- 13-week return greater than 0%: `+4`; from -5% through 0%: `+2`; otherwise `0`.
- Weekly MACD histogram greater than 0: `+4`.

### Monthly trend: 30 points

- Close above 10-month SMA: `+8`.
- Close above 20-month SMA: `+8`.
- 10-month SMA above 20-month SMA: `+6`.
- 12-month return greater than 0%: `+4`; from -5% through 0%: `+2`; otherwise `0`.
- Monthly MACD histogram greater than 0: `+4`.

### Momentum quality: 20 points

Score weekly RSI and monthly RSI separately:

- 50 through 65: `+6`.
- Otherwise, 45 through 70: `+4`.
- Otherwise, 40 through 75: `+2`.
- Otherwise: `0`.

Score the four-week return and three-month return separately:

- 0% through 12%: `+4`.
- -5% through less than 0%: `+2`.
- Greater than 12% through 30%: `+2`.
- Otherwise: `0`.

### Entry and risk: 20 points

Let `extension_pct = (weekly_close / weekly_sma_10 - 1) * 100`:

- 0% through 5%: `+6`.
- Greater than 5% through 10%: `+4`.
- Greater than 10% through 15%: `+2`.
- -3% through less than 0%: `+4`.
- Otherwise: `0`.

Score `atr_14_pct`:

- At most 4%: `+6`.
- Greater than 4% through 7%: `+5`.
- Greater than 7% through 10%: `+3`.
- Greater than 10%: `+1`.

Let `resistance_headroom_pct = (resistance / weekly_close - 1) * 100`:

- 3% through 10%: `+4`.
- 0% through less than 3%: `+2`.
- Greater than 10% through 20%: `+3`.
- Greater than 20%: `+1`.
- Negative: `0`.

Let `support_risk_pct = (weekly_close / support - 1) * 100`:

- At most 5%: `+4`.
- Greater than 5% through 8%: `+3`.
- Greater than 8% through 12%: `+2`.
- Greater than 12%: `+1`.

## Verdict

Map the integer score without discretionary overrides:

| Score | Verdict |
|---:|---|
| 90-100 | `STRONG_BUY` |
| 85-89 | `BUY` |
| 75-84 | `CONDITIONAL_BUY` |
| 60-74 | `WATCH` |
| 40-59 | `WAIT` |
| 0-39 | `AVOID` |

The score measures technical-chart quality, not probability of profit, intrinsic value, or suitability for the user.

## Recommendation fields

Use weekly closing confirmation, not intraday triggers.

- `entry_zone`: provide a technically defensible range only for `STRONG_BUY`, `BUY`, or `CONDITIONAL_BUY`; otherwise use `null`. Anchor it to nearby weekly support, the 10-week SMA, or the current weekly close. Do not invent false precision.
- `breakout_trigger`: use the nearest weekly resistance above price or the moving average that must be reclaimed. Use `null` when no defensible trigger exists.
- `invalidation`: use the weekly-close level that breaks the bullish thesis, normally the nearest meaningful support or 30-week SMA. Use `null` for `WAIT` or `AVOID` unless a clear recovery thesis is stated.
- `summary`: one concise sentence grounded in the returned indicator values.

## Required JSON

Return exactly one valid JSON object with no Markdown fence and no prose before or after it. Use JSON numbers, booleans, arrays, and `null`; never encode missing numeric values as strings. Round prices and indicator values to two decimals, percentages and RSI values to one decimal, and MACD values to two decimals. Do not include `rank`.

```json
{
  "request_date": "YYYY-MM-DD",
  "ticker": "TICKER",
  "status": "ok",
  "data_as_of": "YYYY-MM-DD",
  "price": {
    "regular_last_trade": 0.0,
    "regular_last_trade_at": "RFC3339 timestamp"
  },
  "score": 0,
  "verdict": "STRONG_BUY|BUY|CONDITIONAL_BUY|WATCH|WAIT|AVOID",
  "score_components": {
    "weekly_trend": 0,
    "monthly_trend": 0,
    "momentum_quality": 0,
    "entry_and_risk": 0
  },
  "indicators": {
    "weekly": {
      "candle_status": "complete|provisional",
      "close": 0.0,
      "sma_10": 0.0,
      "sma_30": 0.0,
      "above_sma_10": false,
      "above_sma_30": false,
      "rsi_14": 0.0,
      "macd_12_26_9": {
        "line": 0.0,
        "signal": 0.0,
        "histogram": 0.0
      },
      "atr_14": 0.0,
      "atr_14_pct": 0.0,
      "return_4w_pct": 0.0,
      "return_13w_pct": 0.0,
      "high_52w": 0.0,
      "low_52w": 0.0,
      "volume_vs_20w_avg": 0.0
    },
    "monthly": {
      "candle_status": "complete|provisional",
      "close": 0.0,
      "sma_10": 0.0,
      "sma_20": 0.0,
      "above_sma_10": false,
      "above_sma_20": false,
      "rsi_14": 0.0,
      "macd_12_26_9": {
        "line": 0.0,
        "signal": 0.0,
        "histogram": 0.0
      },
      "return_3m_pct": 0.0,
      "return_12m_pct": 0.0,
      "high_36m": 0.0,
      "low_36m": 0.0,
      "volume_vs_12m_avg": 0.0
    }
  },
  "levels": {
    "weekly_support": 0.0,
    "weekly_resistance": 0.0,
    "extension_from_10w_pct": 0.0,
    "resistance_headroom_pct": 0.0,
    "support_risk_pct": 0.0
  },
  "recommendation": {
    "entry_zone": {
      "low": 0.0,
      "high": 0.0
    },
    "breakout_trigger": 0.0,
    "invalidation": 0.0,
    "confirmation_basis": "weekly_close",
    "summary": "Concise indicator-grounded explanation."
  },
  "methodology": {
    "source": "Robinhood MCP",
    "source_tools": [
      "get_equity_quotes",
      "get_equity_historicals"
    ],
    "bounds": "regular",
    "adjustment_type": "split",
    "chart_timeframes": [
      "weekly",
      "monthly"
    ],
    "intraday_used": false,
    "score_is_probability": false
  },
  "warnings": []
}
```

For a terminal failure, preserve the same top-level identity and return:

```json
{
  "request_date": "YYYY-MM-DD",
  "ticker": "TICKER",
  "status": "not_found|insufficient_data|failed",
  "data_as_of": null,
  "price": null,
  "score": null,
  "verdict": null,
  "score_components": null,
  "indicators": null,
  "levels": null,
  "recommendation": null,
  "methodology": {
    "source": "Robinhood MCP",
    "source_tools": [
      "get_equity_quotes",
      "get_equity_historicals"
    ],
    "bounds": "regular",
    "adjustment_type": "split",
    "chart_timeframes": [
      "weekly",
      "monthly"
    ],
    "intraday_used": false,
    "score_is_probability": false
  },
  "warnings": [
    "Concise failure reason."
  ]
}
```