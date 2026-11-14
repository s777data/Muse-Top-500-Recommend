#!/usr/bin/env python3
"""
CLI entry point for technical-analysis-recommend.

Usage:
    python -m technical_analysis_recommend META
    python -m technical_analysis_recommend META --model tencent/hy3 --provider nous
"""

import argparse
import json
import sys
from datetime import date

from .engine import TechnicalAnalysisEngine
from .models import AnalysisResult


class MCPClient:
    """MCP client wrapper for Robinhood tools."""
    
    def __init__(self):
        pass
    
    def get_equity_quotes(self, symbols: list) -> dict:
        """Call get_equity_quotes MCP tool."""
        # This will be called from the agent context where MCP tools are available
        # For CLI testing, we'll need to implement a way to call MCP tools
        # For now, raise NotImplementedError
        raise NotImplementedError("MCP client not available in standalone CLI. Run via Hermes agent.")
    
    def get_equity_historicals(self, symbols: list, start_time: str, end_time: str = None,
                                interval: str = "day", bounds: str = "regular", 
                                adjustment_type: str = "split") -> dict:
        """Call get_equity_historicals MCP tool."""
        raise NotImplementedError("MCP client not available in standalone CLI. Run via Hermes agent.")


class HermesMCPClient(MCPClient):
    """MCP client that works within Hermes agent context."""
    
    def __init__(self, mcp_tools):
        self.mcp_tools = mcp_tools
    
    def get_equity_quotes(self, symbols: list) -> dict:
        return self.mcp_tools.get_equity_quotes(symbols=symbols)
    
    def get_equity_historicals(self, symbols: list, start_time: str, end_time: str = None,
                                interval: str = "day", bounds: str = "regular", 
                                adjustment_type: str = "split") -> dict:
        return self.mcp_tools.get_equity_historicals(
            symbols=symbols,
            start_time=start_time,
            end_time=end_time,
            interval=interval,
            bounds=bounds,
            adjustment_type=adjustment_type,
        )


def main():
    parser = argparse.ArgumentParser(description="Technical Analysis Recommend - Deterministic technical analysis for US equities")
    parser.add_argument("ticker", help="Stock ticker symbol (e.g., META)")
    parser.add_argument("--model", help="Model name (for reference only)")
    parser.add_argument("--provider", help="Provider name (for reference only)")
    parser.add_argument("--date", help="Request date YYYY-MM-DD (default: today)")
    parser.add_argument("--json", action="store_true", help="Output raw JSON (default)")
    
    args = parser.parse_args()
    
    request_date = args.date or date.today().isoformat()
    
    # Create engine - will fail without MCP client
    # In Hermes agent context, the mcp_tools are available
    try:
        # Try to import hermes_tools if running in Hermes context
        from hermes_tools import web_search, terminal, read_file, write_file, search_files, patch
        # We need to use the mcp__robinhood_trading__ tools
        # This is a placeholder - actual MCP integration happens in agent context
        print("Running in Hermes agent context - use the skill via agent", file=sys.stderr)
        sys.exit(1)
    except ImportError:
        pass
    
    # Standalone mode - not available
    result = AnalysisResult(
        request_date=request_date,
        ticker=args.ticker.upper(),
        status="failed",
        data_as_of=None,
        price=None,
        score=None,
        verdict=None,
        score_components=None,
        indicators=None,
        levels=None,
        recommendation=None,
        methodology={
            "source": "Robinhood MCP",
            "source_tools": ["get_equity_quotes", "get_equity_historicals"],
            "bounds": "regular",
            "adjustment_type": "split",
            "chart_timeframes": ["weekly", "monthly"],
            "intraday_used": False,
            "score_is_probability": False,
        },
        warnings=["CLI requires Hermes agent context with MCP tools. Run via Hermes agent."],
    )
    
    print(result.to_json())


if __name__ == "__main__":
    main()