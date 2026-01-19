# Sbronze
Sbronze Treasure Hunt - Portfolio and fund tracking with GitHub-backed historical data caching.

## Architecture Overview

### Data Flow
1. **Streamlit App** (`main.py`): Multi-page portfolio dashboard
   - Reads `funds.csv` for fund definitions
   - Reads `transaction_history.csv` for portfolio transactions
   - Reads `historical_data.csv` for cached fund prices (no direct Yahoo Finance calls in Streamlit)
   - Provides UI forms to add funds and transactions

2. **GitHub Actions Workflow** (`.github/workflows/update-historical-data.yml`):
   - Triggers daily at **05:00 UTC** and on `funds.csv` changes (manual trigger also available)
   - Runs `get_historical_data.py` to fetch historical prices
   - Auto-commits updated `historical_data.csv` to repository

3. **Helper Script** (`get_historical_data.py`):
   - Fetches up to **100 years** of daily Open prices for all funds in `funds.csv`
   - Merges data across funds, forward-fills missing values
   - Renames columns to fund names (e.g., "US" instead of "VTSAX")
   - Outputs to `historical_data.csv`

### Why This Approach?
- **Avoids rate limits**: Streamlit Cloud can't make direct Yahoo Finance calls; prices are cached in CSV
- **Reliable updates**: GitHub Actions handles fetching on a schedule, independent of app usage
- **Persistent history**: All data versioned in Git, survives app redeployment
- **No API keys**: Only needs GitHub token (already required for app to read/write files)

## Features

### Pages
- **📊 Overview**: Portfolio composition pie chart and current holdings
- **📈 Historical Prices**: Interactive Altair charts of fund prices and portfolio value over time
- **💳 Transactions**: View transaction history
- **💰 Active Funds**: List of funds currently in portfolio with ticker symbols
- **➕ Add Fund**: Form to add new funds (saves to `funds.csv`)
- **➕ Add Transaction**: Form to record portfolio changes (saves to `transaction_history.csv`)

### Data Files
- `funds.csv`: Fund definitions (name, ticker, type)
- `transaction_history.csv`: Portfolio transactions (date, fund, shares, price)
- `historical_data.csv`: Cached daily prices (auto-updated by workflow)

## Deployment on Streamlit Cloud

### Setup
1. Deploy repo to Streamlit Cloud
2. Set these secrets in app settings:
   - `GITHUB_TOKEN`: Personal access token with **Contents: Read and write** permission
   - `GITHUB_REPO`: `owner/Sbronze`
   - `GITHUB_BRANCH` (optional): `main`

### Optional: Faster GitHub Actions Updates
If you want guaranteed fast historical data updates (not waiting for daily schedule):
1. Create a fine-grained Personal Access Token with **Contents: Read and write** on this repo
2. Add it as `ACTIONS_PUSH_TOKEN` secret in GitHub repo settings
3. Workflow will use this token if available (fallback to `GITHUB_TOKEN`)

### Workflow Triggers
- **Daily**: 05:00 UTC (GitHub Actions schedule)
- **On funds.csv push**: Automatic regeneration when fund list changes
- **Manual**: Via GitHub Actions "Run workflow" button

## Local Development

### Install dependencies
```bash
pip install -r requirements.txt
```

### Run app locally
```bash
streamlit run main.py
```

### Fetch historical data manually
```bash
python get_historical_data.py
```
(This updates `historical_data.csv` with 100 years of daily prices)
