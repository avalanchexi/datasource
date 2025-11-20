
# External Data Sources for Asset Management

## Overview

This document outlines external data sources for integrating daily asset information into the AssetManagement system, specifically for generating portfolio holdings data similar to `持仓股20250718.xls`.

## Primary Data Sources

### 1. AKShare

**Description**: Python-based open-source financial data interface
**Motto**: "致力于为人类提供简单优雅的数据获取方式" (Dedicated to providing simple and elegant data acquisition methods for humanity)

**Supported Data Types**:

- Stock data (Chinese, Hong Kong, US markets)
- Historical price information (OHLCV)
- Market trading volumes
- Real-time market data

**Key Features**:

- Open source and free to use
- Python native integration
- Multi-market support
- Active community maintenance

**Installation**: `pip install akshare`

### 2. TuShare

**Description**: Comprehensive financial data API platform
**Note**: "可以说是国内最好的免费金融数据接口" (Arguably the best free financial data interface in China)

**Supported Data Types**:

- Daily stock historical prices
- Trading volumes and market metrics
- Basic financial indicators
- Market capitalization data
- Fundamental analysis data

**Key Features**:

- Extensive data coverage
- Multiple international stock exchanges
- Professional-grade data quality
- Token-based authentication system

**Requirements**:

- API token registration required
- Usage rate limits apply
- `pip install tushare`

## Integration Strategy

### For Portfolio Holdings Generation

Both data sources can provide essential information for `持仓股20250718.xls`:

1. **Current Prices**: Latest closing prices for position valuation
2. **Trading Volumes**: Market liquidity indicators
3. **Price Changes**: Daily/periodic price movements
4. **Market Cap**: Company size and weight calculations
5. **Basic Ratios**: P/E, P/B ratios for analysis

### Implementation Approach

```python
# Example integration pattern
import akshare as ak
import tushare as ts

class ExternalDataCollector:
    def __init__(self):
        # Initialize API connections
        self.ts_pro = ts.pro_api('your_token_here')
  
    def get_stock_basic_info(self, symbol):
        # Fetch current price, volume, market cap
        # Return standardized data format
        pass
  
    def update_portfolio_holdings(self, holdings_file):
        # Read existing holdings
        # Fetch current market data
        # Update with latest prices and metrics
        pass
```

## Technical Considerations

### Rate Limits

- TuShare: Token-based rate limiting
- AKShare: General usage guidelines
- Implement proper request throttling

### Data Quality

- Both sources provide reliable market data
- Cross-validation between sources recommended
- Implement data freshness checks

### Market Coverage

- **Chinese Markets**: Comprehensive coverage (A-shares, Hong Kong)
- **US Markets**: Available through both platforms
- **Other Markets**: Limited availability, check documentation

## Configuration Requirements

### Environment Variables

```bash
# Add to .env file
TUSHARE_TOKEN=your_tushare_token_here
AKSHARE_ENABLE=true

# Optional fallback sources
ALPHA_VANTAGE_API_KEY=backup_source
```

### Dependencies

```bash
pip install akshare tushare pandas requests
```

## Data Mapping for Portfolio Holdings

| Portfolio Field | AKShare Source                   | TuShare Source    |
| --------------- | -------------------------------- | ----------------- |
| 股票代码        | `stock_info_a_code_name_sse()` | `stock_basic()` |
| 当前价格        | `stock_zh_a_spot_em()`         | `daily()`       |
| 涨跌幅          | `stock_zh_a_spot_em()`         | `daily()`       |
| 成交量          | `stock_zh_a_spot_em()`         | `daily()`       |
| 市值            | Calculated from price × shares  | `daily_basic()` |

## Future Enhancements

1. **Real-time Updates**: WebSocket connections for live data
2. **Multi-source Aggregation**: Combine multiple data providers
3. **Data Caching**: Local storage for frequently accessed data
4. **Error Handling**: Robust fallback mechanisms
5. **Data Validation**: Cross-source verification

## Usage Notes

- Both libraries are primarily focused on stock market data
- Registration required for TuShare (free tier available)
- AKShare is completely open source and free
- Consider implementing both for redundancy and data validation
- Respect rate limits to maintain API access

This integration will enable automated daily updates to portfolio holdings data, ensuring accurate asset valuations and market information for the AssetManagement system.
