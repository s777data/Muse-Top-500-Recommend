import sys
import json
from datetime import datetime, date

sys.path.insert(0, '.')

from technical_analysis_recommend.engine import TechnicalAnalysisEngine
from technical_analysis_recommend.models import PriceData, DailyBar, AnalysisResult, Methodology

# Read data from files saved by the agent
with open('/tmp/meta_quote.json', 'r') as f:
    quote_response = json.load(f)

with open('/tmp/meta_historical.json', 'r') as f:
    hist_response = json.load(f)

class MCPClient:
    def __init__(self, quote_response, hist_response):
        self.quote_response = quote_response
        self.hist_response = hist_response
    
    def get_equity_quotes(self, symbols):
        result = self.quote_response
        if 'data' in result and 'results' in result['data']:
            quote = result['data']['results'][0]['quote']
            return PriceData(
                regular_last_trade=float(quote['last_trade_price']),
                regular_last_trade_at=quote['venue_last_trade_time'],
                symbol=quote['symbol'],
                listing_state=quote['state'],
                has_traded=quote['has_traded'],
            )
        return None
    
    def get_equity_historicals(self, symbols, start_time, end_time=None, **kwargs):
        result = self.hist_response
        bars = []
        if 'data' in result and 'results' in result['data']:
            for bar in result['data']['results'][0]['bars']:
                dt = datetime.fromisoformat(bar['begins_at'].replace('Z', '+00:00'))
                bars.append(DailyBar(
                    date=dt.date(),
                    open=float(bar['open_price']),
                    high=float(bar['high_price']),
                    low=float(bar['low_price']),
                    close=float(bar['close_price']),
                    volume=int(bar['volume']),
                    interpolated=False,
                ))
        return bars

engine = TechnicalAnalysisEngine(MCPClient(quote_response, hist_response))
result = engine.run("META")
print(result.to_json())
