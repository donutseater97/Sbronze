# 📊 Sbronze Treasure Hunt

A comprehensive portfolio tracking and analysis application built with Streamlit. Track investments, visualize performance, and gain insights into your financial portfolio.

## 🎯 Features

### Portfolio Summary
- **Fund Filters**: Filter portfolio by individual funds or view all
- **Data Masking**: 🔒 Toggle to hide sensitive financial data (shows "***.*€")
- **Key Metrics**:
  - Gross Contributions & Net Invested
  - Market Value with Daily % changes
  - Total & Net Returns with percentage breakdown
  - Month-over-Month performance
  - Portfolio weights by market value

### Charts & Analytics

#### Revenue P&L Chart
- Cumulative daily profit/loss visualization
- Portfolio total line (toggleable) + individual fund lines
- Each fund line starts from its first contribution date
- Interactive controls: range selector, scroll zoom, drawing tools
- Right-side data labels showing latest P&L values

#### Investment Evolution
- Stair-step gross contribution tracking
- Market value overlay
- Side-by-side view with Allocation pies

#### Allocation Pies (Dual View)
- **Left**: Gross Contributions allocation
- **Right**: Market Value allocation
- **Group By Options**:
  - Fund (color by fund)
  - Type (Equity/Bond)
  - Asset Manager (first word of Fund Name, with assigned palette)
- Unified legend below both pies
- Aligned heights (520px) for visual balance

#### Daily Performance Table
- Date (descending order)
- Per-fund daily absolute changes with %
- Daily Portfolio Performance Total
- Green/red background coloring
- Shows "+" prefix for positive values

#### Historical Data Charts
- **Combined View**: All funds on single chart with average NAV lines
- **Grid View**: Individual fund charts (up to 3 per row)
- Transaction markers on charts
- Right-side data labels with latest prices
- Range selector buttons (1M, 3M, 6M, YTD, 1Y, 3Y, All)
- Scroll zoom and drawing tools

#### Historical Data Table
- Most recent dates first
- Per-fund daily price changes with % (descending order)
- Transaction day highlighting (light grey)
- Colored fund headers matching fund colors

### Transaction History
- Complete transaction record
- Contribution count per fund
- Fund and date filtering
- Average NAV tracking

### Additional Sections
- Active Funds management
- Data input interface (password-protected)
- Support for custom funds and transactions

## 🚀 Getting Started

### Prerequisites
- Python 3.11+
- pip

### Installation

1. Clone the repository:
```bash
git clone https://github.com/donutseater97/Sbronze.git
cd Sbronze
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Run the application:
```bash
streamlit run main.py
```

4. Open your browser to `http://localhost:8501`

## 📋 Project Structure

```
Sbronze/
├── main.py                          # Main Streamlit application
├── get_historical_data.py           # Investgo + JPMorgan historical data fetcher
├── get_backup_historical_data.py    # YFinance backup fetcher
├── requirements.txt                 # Python dependencies
├── funds.csv                        # Fund definitions (ticker, ISIN, type, color)
├── transaction_history.csv          # Investment transaction record
├── historical_data.csv              # Cached price history (updated hourly)
├── backup_historical_data.csv       # YFinance backup prices (updated weekly)
├── README.md                        # This file
└── .github/workflows/
    ├── update-historical-data.yml   # Hourly price data update (investgo + JPMorgan)
    ├── update-backup-historical-data.yml  # Weekly backup (YFinance)
    └── monthly-backup.yml           # Monthly data snapshot
```

## 🔧 Configuration

### Fund Data (`funds.csv`)
Define your funds with:
- **Fund**: Short identifier (used in code)
- **Ticker**: Yahoo Finance ticker
- **ISIN**: International Securities Identification Number
- **Fund Name**: Full fund name (first word = Asset Manager)
- **Type**: Equity or Bond
- **Colour**: Hex color code for charts

### Transactions (`transaction_history.csv`)
Record each investment with:
- **Date**: Transaction date (YYYY-MM-DD)
- **Fund**: Fund identifier
- **Price (€)**: Unit price at purchase
- **Quantity**: Number of units
- **Fees (€)**: Transaction fees

## 📊 Data Processing

### Daily Portfolio Performance (DPP)
Calculated as: `Σ [quantity_f(t-1) × (price_f(t) - price_f(t-1))]`
- Only includes holdings (quantity > 0)
- Starts from first transaction date
- Per-fund calculation from first purchase date

### Returns
- **Gross Return**: Market Value - Gross Contributions
- **Net Return**: Market Value - (Gross Contributions + Fees)
- **Total Invested**: Sum of (Quantity × Price + Fees) across all transactions

### Allocation
- **Gross Contributions**: Sum of all investments (actual cash paid)
- **Market Value**: Current portfolio value at latest prices

## 🔐 Security & Privacy

- **Password-Protected Admin**: Default password "123" (change in code)
- **Data Masking Toggle**: Hide all financial values during screen sharing
- **Session State**: All data is local to the user's Streamlit session
- **GitHub Actions**: Secured with ACTIONS_PUSH_TOKEN for auto-updates

## 🔄 Data Updates

- **Historical Prices**: Updated **every hour** from Investgo (primary) + JPMorgan API
- **Backup Prices**: Updated **weekly** from YFinance
- **Manual Updates**: Can run `get_historical_data.py` locally anytime

## 📈 Performance Optimizations

- **Vectorized Calculations**: Pandas operations instead of loops
- **Cached DPP Computation**: Recalculates only on fund filter changes
- **Efficient Merging**: `merge_asof` for time-series lookups
- **Minimal Recomputation**: DPP removed from historical table (moved to dedicated section)

**Result**: ~3x faster historical data table rendering

## 🛠️ Development

### Adding New Funds
1. Add row to `funds.csv` with fund details
2. Ensure ticker works with Investgo/YFinance
3. Workflow auto-fetches price history

### Customizing Charts
- Modify `FUND_COLORS` dictionary for fund colors
- Edit chart layouts in `overview_and_charts()` and `historical_prices()`
- Adjust color palettes in allocation pie sections

## 📝 Notes

- **Currency**: All values in Euros (€)
- **Timezone**: Historical data timestamps in Europe/Rome timezone
- **Data Quality**: Missing prices filled with forward-fill method
- **Rounding**: Gross Contributions rounded to nearest €10 (configurable)

## 🤝 Contributing

Pull requests welcome! Please ensure:
- Code follows existing style
- No sensitive credentials in commits
- Performance improvements documented

## 📄 License

Private project - use as reference for your own portfolio tracking

## 📞 Support

For issues or questions:
1. Check the console output for error messages
2. Verify `funds.csv` and `transaction_history.csv` formats
3. Ensure internet connection for real-time price updates
4. Check workflow logs in GitHub Actions for auto-update status

---

**Last Updated**: January 2026
**App Version**: 1.0
**Status**: Production Ready
