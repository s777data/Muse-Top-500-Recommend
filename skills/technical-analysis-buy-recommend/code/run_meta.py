import sys
sys.path.insert(0, '.')

from technical_analysis_recommend.engine import TechnicalAnalysisEngine
from technical_analysis_recommend.models import PriceData, DailyBar, AnalysisResult, Methodology
from datetime import datetime, date
import json

# We need to fetch data from MCP. Since we're in a terminal, we can't directly call MCP tools.
# But we can use the hermes_tools module if available, or we need to run this within the agent context.
# Let me check if we can import hermes_tools

try:
    from hermes_tools import mcp__robinhood_trading__get_equity_quotes, mcp__robinhood_trading__get_equity_historicals
    print("hermes_tools available", file=sys.stderr)
except ImportError:
    print("hermes_tools not available - must run within Hermes agent context", file=sys.stderr)
    sys.exit(1)

class MCPClient:
    def get_equity_quotes(self, symbols):
        return mcp__robinhood_trading__get_equity_quotes(symbols=symbols)
    
    def get_equity_historicals(self, symbols, start_time, end_time=None, **kwargs):
        return mcp__robinhood_trading__get_equity_historicals(
            symbols=symbols, start_time=start_time, end_time=end_time, **kwargs)

engine = TechnicalAnalysisEngine(MCPClient())
result = engine.run("META")
print(result.to_json())
