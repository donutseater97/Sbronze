# Sbronze — Personal Investment Portfolio Tracker

Sbronze ("Sbronze Treasure Hunt") is a Streamlit application that tracks a
self-managed portfolio of investment funds. It ingests your transactions,
fetches historical NAVs automatically, and presents returns, allocation,
evolution, and a reconstructed Morningstar X-Ray. Data is stored as plain CSV
files in the repository and updated hourly by a GitHub Actions workflow.

---

## Table of contents

1. [Quick start](#quick-start)
2. [Configuration & secrets](#configuration--secrets)
3. [User roles & privacy mode](#user-roles--privacy-mode)
4. [Repository structure](#repository-structure)
5. [Data files & schemas](#data-files--schemas)
6. [Pages](#pages)
7. [Utilities & components](#utilities--components)
8. [Data pipeline (NAV updater)](#data-pipeline-nav-updater)
9. [Morningstar analytics & freshness](#morningstar-analytics--freshness)
10. [Calculated fields reference](#calculated-fields-reference)
11. [Caching & performance](#caching--performance)

---

## Quick start

```bash
pip install -r requirements.txt
streamlit run main.py
```

The app reads the CSVs in `data/`, so it works immediately with the committed
data. Editing data (the *Add Transactions & Funds* page) requires the admin
password; see [Configuration & secrets](#configuration--secrets).

---

## Configuration & secrets

Secrets are read by `config.py` via `_get_secret(name, default)`, which checks
`st.secrets` first, then environment variables. On Streamlit Cloud set them in
the app's **Secrets**; locally use environment variables or
`.streamlit/secrets.toml`.

| Secret | Purpose | Required |
|---|---|---|
| `ADMIN_PASSWORD` | Admin role: full access, can edit data and disable privacy mode. | Yes (falls back to `OWNER_PASSWORD`) |
| `VIEWER_PASSWORD` | Viewer role: browse everything except editing data. | Optional |
| `OWNER_PASSWORD` | Legacy admin password; used as admin if `ADMIN_PASSWORD` is unset. | Legacy |
| `GITHUB_TOKEN` | Write CSVs back to the repo from the *Add Transactions* page. | For in-app writes |
| `GITHUB_REPO` | `owner/repo` for writes (default `donutseater97/Sbronze`). | Optional |
| `GITHUB_BRANCH` | Target branch (default `main`). | Optional |

Theme is set in `.streamlit/config.toml`: background `#0d1117`, secondary
`#161b22`, text `#e6edf3`, primary `#58a6ff`. These hex values are reused in
code where a chart must match the page background exactly.

---

## User roles & privacy mode

Two roles are recognised by `config.check_role(password)`:

- **admin** — no restrictions. Can edit the *Add Transactions & Funds* page and
  disable privacy mode.
- **viewer** — can browse every page and use every control **except** editing
  data. The *Add Transactions & Funds* page shows an admin-password prompt.

Sign-in is a popover in the page header (`👤 Sign in`), rendered by
`utils/privacy.render_page_header`. State lives in
`st.session_state["role"]` and `["authenticated"]`, which are non-widget keys
so they persist across page navigation.

**Privacy mode** hides all personal euro amounts and quantities (NAVs stay
visible — they are public prices). It is **on by default** (`main.py` sets
`privacy_mode = True`). Anyone can enable it; only an **admin** can disable it
via the header's `🙈 Privacy` popover. When active:

- Euro figures render as `€ ••••` and quantities as `••••`.
- Combined-value columns (e.g. `Return [€ (%)]`) show only the `%`.
- Chart hovers and metric-card sparklines are indexed (base 100) so hovering
  never reveals absolute euros; when privacy is **off**, sparklines show real
  values. This logic lives in `utils/privacy.normalize_spark`.

---

## Repository structure

```
Sbronze/
├── main.py                       # Entry point: nav, session-state init, page wiring
├── config.py                     # Paths, secrets, data loaders (cached), GitHub API, roles
├── get_historical_data.py        # NAV updater run hourly by GitHub Actions
├── requirements.txt              # streamlit, pandas, plotly
├── .streamlit/config.toml        # Theme + client settings
├── .github/workflows/
│   └── update-historical-data.yml# Hourly NAV refresh + commit
├── data/                         # All persisted data (CSV)
│   ├── funds.csv
│   ├── transaction_history.csv
│   ├── historical_data.csv
│   ├── historical_sources.csv
│   ├── monthly_historical_data.csv
│   └── monthly_returns.csv
├── pages/                        # One module per Streamlit page
│   ├── overview_and_charts.py
│   ├── daily_dashboard.py
│   ├── evolution_of_portfolio.py
│   ├── historical_prices.py
│   ├── transaction_history.py
│   ├── morningstar_api_data.py
│   ├── active_funds.py
│   └── add_transactions_and_funds.py
├── utils/
│   ├── nav_sources.py            # NAV/analytics fetchers (investgo, Morningstar, official)
│   ├── morningstar_api.py        # Parse security_details XML → analytics + aggregation
│   ├── privacy.py                # Roles, privacy mode, page header, spark masking
│   └── formatting.py             # Decimal precision & quantity formatting
├── components/
│   ├── chart_helpers.py          # Plotly config, range-selector buttons, y-range helpers
│   ├── fund_filter.py            # Fund multiselect + colour→emoji mapping
│   └── styling.py                # hex→rgb/rgba, fund-cell styling
└── scripts/
    └── extract_monthly_data_for_matrix.py  # Build monthly matrices from daily data
```

---

## Data files & schemas

All data is CSV in `data/`. The app never overwrites history destructively; the
updater merges new rows over existing ones.

### `funds.csv` — the fund catalogue
| Column | Meaning |
|---|---|
| `Fund` | Short label / key used everywhere (e.g. `US`, `EU HY`). |
| `Ticker` | Morningstar ID (e.g. `0P0001CRXW`); used for investgo and Morningstar. |
| `ISIN` | Fund ISIN; used for JPMorgan/Fidelity/BlackRock/UBS official sources. |
| `Fund Name` | Full legal name. Detection of `"JPMorgan"` here routes the NAV source. |
| `Type` | `Equity` or `Bond`. |
| `Colour` | Hex colour for that fund across all charts/tables. |
| `URL` | Official fund page (rendered as a link in *Active Funds*). |

### `transaction_history.csv` — your purchases
| Column | Meaning |
|---|---|
| `Date` | Transaction date. |
| `Fund` | Fund key (matches `funds.csv`). |
| `Price (€)` | NAV paid per unit. |
| `Quantity` | Units bought. |
| `Fees (€)` | Fees for that transaction. |

### `historical_data.csv` — daily NAV matrix
`Date` plus one column per fund key, each holding that day's NAV. Written by
`get_historical_data.py`. Missing early dates are forward-filled after each
fund's first valid value; dates before a fund existed are blank.

### `historical_sources.csv` — provenance metadata
`Fund, Source, LastDate` — which source (`InvestGo`, `Morningstar`,
`JPMorgan AM`, `Fidelity`, `BlackRock`, `UBS`) actually supplied each fund on
the last run, and the latest date obtained. Written by the updater.

### `monthly_historical_data.csv` / `monthly_returns.csv`
Month-end NAV matrix and month-over-month percentage returns, produced by
`scripts/extract_monthly_data_for_matrix.py` from the daily data. Used for
matrix-style views.

---

## Pages

Navigation order and wiring live in `main.py`. Each page is a function receiving
the global `funds`, `transactions`, `hist_data`, and `last_date_str`.

### Overview & Charts (`overview_and_charts.py`)
The home page. Builds the per-fund **Portfolio Summary** table and the **Totals
based on filters** scorecards, plus allocation pies and the investment-evolution
chart.

- Summary columns, in order: Gross Contributions, Net Invested, Market Value,
  Latest Price, Average NAV, Quantity, Fees, Return `[€ (%)]`, Net Return
  `[€ (%)]`, MoM, YTD, YoY, Weight.
- Scorecards (2×3): Total Return / Total Net Return / Daily P/L, then Total Gross
  Contributions / Total Market Value / YoY performance. Every card carries a
  30-day sparkline.
- Market-value time series is computed **vectorized** and cached (see
  [Caching & performance](#caching--performance)).

### Daily Dashboard (`daily_dashboard.py`)
Per-fund cards for the latest session: current NAV and daily P/L (value + %),
each with a small sparkline. P/L sparklines are masked under privacy.

### Evolution of Portfolio (`evolution_of_portfolio.py`)
Longer-horizon views: absolute/percentage change by fund, NAV evolution,
portfolio market value over time, and composition. Under privacy the euro views
are hidden or axis-masked.

### Historical Data Charts (`historical_prices.py`)
Two modes:
- **Grid** — one panel per fund (native `st.plotly_chart`).
- **Combined** — a stacked multi-panel chart rendered as an HTML component with
  embedded Plotly.js and a **JavaScript crosshair**: a single full-height
  vertical line spanning every panel, with one consolidated tooltip listing all
  funds at the cursor date. Includes a native modebar full-screen button and a
  "Chart height" slider (default 1.5×).

Each panel's y-range is derived from that fund's NAV min/max **within the
selected interval**, ignoring the Average-NAV dashed line (which is still drawn
and reappears when you zoom out). The bottom historical table uses cell
background colours (green up / red down) with transaction days outlined, styled
in a single pass and limited to a time window (default 1M) for speed.

### Transaction History (`transaction_history.py`)
The full transaction ledger with computed columns and totals. Under privacy all
value columns are masked except `Price` (public NAV).

### Morningstar API data (`morningstar_api_data.py`)
A reconstructed portfolio X-Ray from Morningstar's public `security_details`
endpoint, weighted by each fund's current market value. Sections: Asset
Allocation, Currency Exposure, Equity Sector Exposure (donut + legend), Style
Box (equity + bonds), and a filterable, scrollable look-through **Holdings**
accordion. Includes a **Data freshness** panel (see below) and a per-fund
completeness disclaimer.

### Active Funds (`active_funds.py`)
The fund catalogue with a clickable `URL` link column to each official fund
page.

### Add Transactions & Funds (`add_transactions_and_funds.py`)
**Admin-only.** Forms to add transactions and funds; writes back to the CSVs
(and to GitHub if a token is configured). Viewers and anonymous users see an
admin-password prompt.

---

## Utilities & components

### `utils/nav_sources.py`
All NAV/analytics fetchers, shared by the updater and the Morningstar page.
- `fetch_investgo_nav` — investing.com via the `investgo` library.
- `fetch_morningstar_nav` / `fetch_morningstar_details_xml` — Morningstar public
  REST API with **host + token rotation** (`MORNINGSTAR_HOSTS`,
  `MORNINGSTAR_TOKENS`). The live host is `lt.morningstar.com`; the historic
  `tools.morningstar.<cc>` hosts are kept as fallbacks.
- `fetch_jpmorgan_nav`, `fetch_fidelity_nav`, `fetch_blackrock_nav`,
  `fetch_ubs_nav` — official fund sources; `OFFICIAL_FUND_SOURCES` maps ISIN →
  fetcher.

### `utils/morningstar_api.py`
- `parse_fund_analytics(xml)` — parses the ~2 MB XML into asset allocation,
  sectors, style boxes, currency exposure, holdings, and a **freshness** block
  (`portfolio_date`, `prev_portfolio_date`, `nav_date`).
- `aggregate_portfolio(per_fund, weights)` — market-value-weighted aggregation,
  including a per-holding breakdown (which funds hold it, weight in fund, weight
  in portfolio).

### `utils/privacy.py`
Roles and privacy. Key functions: `check_role` (via config), `privacy_on`,
`fmt_eur`, `mask_text`, `normalize_spark`, `render_page_header` (title +
sign-in + privacy popovers), plus `MASK`/`MASK_PLAIN` constants.

### `utils/formatting.py`
`count_decimals` and `format_qty` — per-fund decimal precision for quantities.

### `components/chart_helpers.py`
`get_plotly_config` (modebar, export, drawing tools), `RANGE_SELECTOR_BUTTONS`,
`apply_standard_xaxis`, and y-range helpers.

### `components/fund_filter.py`
`render_fund_filter` — the fund multiselect, plus the colour→emoji mapping used
in labels.

### `components/styling.py`
`hex_to_rgb`, `hex_to_rgba`, and fund-cell styling helpers for coloured tables.

---

## Data pipeline (NAV updater)

`get_historical_data.py` runs **hourly** via
`.github/workflows/update-historical-data.yml` (`cron: '0 * * * *'`). For every
fund it tries sources in a cascade, stopping at the first success:

1. **JPMorgan funds** (name contains `JPMorgan`): JPMorgan AM → Morningstar.
2. **All other funds**: investgo → Morningstar → the fund's official source
   (Fidelity / BlackRock / UBS, by ISIN).

Notes:
- investgo is usually blocked from datacenter IPs (GitHub runners), so most
  funds resolve via Morningstar in practice.
- Fidelity and UBS are behind Akamai and reject datacenter IPs; they only help
  from a residential/self-hosted runner. JPMorgan and BlackRock work from
  datacenters.

The updater **merges** new data over the existing CSV (new values win on
overlapping dates, correcting stale quotes; history is preserved), then writes
`historical_data.csv` and `historical_sources.csv`. The workflow pulls before
committing to avoid divergence.

> Because the workflow commits to `historical_data.csv`, run `git pull` before
> starting local work to avoid non-fast-forward push rejections.

---

## Morningstar analytics & freshness

The Morningstar page reads `security_details` **live** each visit (cached 6h per
fund). Two independent clocks govern freshness, surfaced in the page's
**Data freshness & sourcing** panel:

- **Holdings / sector composition** — disclosed by funds on a **monthly**
  cadence with a few weeks' lag. Exposed as `portfolio_date`; cadence is
  inferred from the gap to `prev_portfolio_date`.
- **Latest NAV** — typically daily. Exposed as `nav_date`.

The panel shows, per fund, the composition date, its age in days, the inferred
cadence, and the latest NAV date, with a status banner keyed off the oldest
composition (green ≤45d, amber ≤75d, red beyond).

Limitations: some funds disclose only their top-10 holdings publicly, so the
aggregate holdings count is inflated versus a licensed full look-through; and
currency exposure uses net-position methodology, not hedged-position.

---

## Calculated fields reference

Let `Q` = summed quantity, `P` = price, `F` = fees, `NAV_t` = latest NAV.
Contributions use a "theoretical" rounding: each transaction's gross is rounded
to the nearest €10 (`round(gross/10)*10`) to match round-number bank transfers.

| Field | Formula | Notes |
|---|---|---|
| Gross Contribution (real) | `Q·P + F` | Per transaction. |
| Gross Contribution (theor) | `round((Q·P + F)/10)·10` | Rounded to €10; summed for the table. |
| Net Invested | `Σ(Q·P)` | Excludes fees. |
| Market Value | `Σ(Q · NAV_t)` | Current value at latest NAV. |
| Average NAV | `(Gross Contributions − Fees) / Q` | Weighted cost basis; **fixed** over all transactions (interval-independent). |
| Total Return (€) | `Market Value − Gross Contributions` | Gross of fees. |
| Total Return (%) | `Total Return / Gross Contributions · 100` | |
| Net Return (€) | `Market Value − Net Invested` | |
| Net Return (%) | `Net Return / Net Invested · 100` | |
| Daily P/L (€) | `Σ(Q · (NAV_today − NAV_prev))` | Latest session. |
| MoM performance (%) | `NAV_today / NAV_(1 month ago) − 1` | **NAV-based** price return (as-of lookup). |
| YTD performance (%) | `NAV_today / NAV_(last of prior year) − 1` | Base = Dec 31 of prior year. |
| YoY performance (%) | `NAV_today / NAV_(12 months ago) − 1` | |
| Portfolio YoY | MV-weighted average of per-fund YoY | Shown in scorecards. |
| Weight (Mkt Value) | `fund Market Value / Σ Market Value · 100` | |

Sparklines (30-day, `SPARK_DAYS = 30`): `spark_mv` = market value series;
`spark_return` = `MV − gross`; `spark_net_return` = `MV − net invested`;
`spark_daily_pnl` = daily P/L bars; `spark_yoy` = trailing-12m portfolio %.
Money sparklines are index-normalized only under privacy mode.

---

## Caching & performance

- `config.load_funds_and_transactions` and `config.load_historical_prices` are
  `@st.cache_data(ttl=300)` so the 7k-row CSV is not re-read on every rerun.
- Morningstar per-fund fetches are `@st.cache_data(ttl=6h)`.
- The Overview market-value time series is computed vectorized (cumulative
  shares reindexed onto price dates, then a matrix multiply) rather than a
  per-date Python loop — ~130× faster on the full history.
- The historical table styles a single time-window (default 1M) in one pass to
  stay responsive; "Max" is available when the full history is needed.