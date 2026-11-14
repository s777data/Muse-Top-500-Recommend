# Technical Analysis Recommend - Code Package

This directory contains the Python implementation for the technical-analysis-recommend skill.

## Structure

```
code/
├── technical_analysis_recommend/
│   ├── __init__.py          # Package exports
│   ├── models.py            # Data classes
│   ├── indicators.py        # Technical indicator calculations
│   ├── aggregation.py       # Daily → weekly/monthly candle aggregation
│   ├── scoring.py           # Deterministic scoring logic
│   ├── engine.py            # Main analysis engine
│   ├── cli.py               # CLI entry point
│   └── tests/
│       └── test_technical_analysis.py  # Unit tests
```

## Usage

The package is designed to run within the Hermes agent context where MCP tools are available:

```python
from technical_analysis_recommend import TechnicalAnalysisEngine, run_analysis
from hermes_tools import mcp__robinhood_trading__get_equity_quotes, mcp__robinhood_trading__get_equity_historicals

# Create a custom MCP client wrapper
class MyMCPClient:
    def get_equity_quotes(self, symbols):
        return mcp__robinhood_trading__get_equity_quotes(symbols=symbols)
    
    def get_equity_historicals(self, symbols, start_time, end_time=None, interval="day", bounds="regular", adjustment_type="split"):
        return mcp__robinhood_trading__get_equity_historicals(
            symbols=symbols,
            start_time=start_time,
            end_time=end_time,
            interval=interval,
            bounds=bounds,
            adjustment_type=adjustment_type,
        )

engine = TechnicalAnalysisEngine(MyMCPClient())
result = engine.run("META")
print(result.to_json())
```

## Running Tests

```bash
cd code
python -m pytest technical_analysis_recommend/tests/ -v
```

## MCP Integration

The CLI (`cli.py`) is a placeholder - the actual MCP integration happens when the skill is invoked via the Hermes agent, which has access to the `mcp__robinhood_trading__` tools.