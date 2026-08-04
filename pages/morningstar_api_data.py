"""
pages/morningstar_api_data.py — "Morningstar API data" page.

Reconstructs a portfolio X-Ray (asset allocation, currency exposure, equity
sector breakdown, style box, look-through holdings) from Morningstar's public
security_details endpoint, weighting each fund's data by its current EUR value.

All styling is done with inline HTML/CSS so the page has NO matplotlib
dependency (Streamlit Cloud does not ship matplotlib, and pandas Styler's
background_gradient requires it).
"""

import streamlit as st
import pandas as pd
import plotly.graph_objects as go

from components.chart_helpers import get_plotly_config
from utils.privacy import fmt_eur, render_page_header
from utils.morningstar_api import (
    fetch_security_details_xml,
    parse_fund_analytics,
    aggregate_portfolio,
    ASSET_CLASS_ORDER,
    STYLEBOX_ROWS, STYLEBOX_COLS,
    BOND_STYLEBOX_ROWS, BOND_STYLEBOX_COLS,
)

# Qualitative palette for the sector pie (distinct, colour-blind friendly-ish).
_SECTOR_PALETTE = [
    "#4C78A8", "#F58518", "#54A24B", "#E45756", "#72B7B2",
    "#EECA3B", "#B279A2", "#FF9DA6", "#9D755D", "#BAB0AC", "#5C7BD9",
]


# -----------------------------------------------------------------------------
# Caching — one download per fund, reused for 6 hours
# -----------------------------------------------------------------------------

@st.cache_data(ttl=6 * 3600, show_spinner=False)
def _load_fund_analytics(msid: str) -> dict:
    """Download and parse Morningstar analytics for a single fund (cached)."""
    return parse_fund_analytics(fetch_security_details_xml(msid))


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------

def _current_values(funds: pd.DataFrame, transactions: pd.DataFrame,
                    hist_data: pd.DataFrame) -> dict:
    """Return {fund: current EUR value} from transactions and latest NAV."""
    values = {}
    if len(transactions) == 0 or len(hist_data) == 0:
        return values
    qty = transactions.groupby("Fund")["Quantity"].sum()
    latest = hist_data.sort_values("date").iloc[-1]
    for fund in funds["Fund"]:
        q = float(qty.get(fund, 0.0))
        nav = latest.get(fund)
        if q > 0 and pd.notna(nav):
            values[fund] = q * float(nav)
    return values


def _stylebox_cells(cells: dict, rows: list, cols: list):
    """Yield (row_label, col_label, value) for the 3x3 style box."""
    for r in range(3):
        for c in range(3):
            yield rows[r], cols[c], cells.get(r * 3 + c + 1, 0.0)


def _render_stylebox(cells: dict, rows: list, cols: list, accent: str):
    """Render a 3x3 style box as inline HTML (no matplotlib)."""
    if not cells:
        st.info("N/A for this portfolio")
        return
    vmax = max(cells.values()) if cells.values() else 0.0
    html = ['<table style="border-collapse:collapse;width:100%;text-align:center;font-size:13px;">']
    # header
    html.append("<tr><td></td>" + "".join(
        f'<td style="padding:4px;color:#888;font-weight:600;">{c}</td>' for c in cols) + "</tr>")
    grid = {(rl, cl): v for rl, cl, v in _stylebox_cells(cells, rows, cols)}
    for r in rows:
        html.append(f'<tr><td style="padding:4px;color:#888;font-weight:600;">{r}</td>')
        for c in cols:
            v = grid[(r, c)]
            intensity = (v / vmax) if vmax > 0 else 0.0
            # blend accent over transparent based on intensity
            alpha = 0.12 + 0.75 * intensity
            html.append(
                f'<td style="padding:10px;border:1px solid rgba(255,255,255,0.06);'
                f'background:{accent}{int(alpha*255):02x};border-radius:4px;">'
                f'{v:.1f}</td>'
            )
        html.append("</tr>")
    html.append("</table>")
    st.markdown("".join(html), unsafe_allow_html=True)


# -----------------------------------------------------------------------------
# Page
# -----------------------------------------------------------------------------

def morningstar_api_data(funds: pd.DataFrame, transactions: pd.DataFrame,
                         hist_data: pd.DataFrame, last_date_str: str):
    """Render the Morningstar API data page."""
    render_page_header("🔎 Morningstar API data")

    if len(funds) == 0:
        st.info("No funds added yet")
        return

    # --- Current weights per fund -----------------------------------------
    weights = _current_values(funds, transactions, hist_data)
    if not weights:
        st.warning("Cannot compute current fund values (missing transactions "
                   "or price history).")
        return

    # --- Download Morningstar analytics per fund (cached) -----------------
    per_fund = {}
    failed = []
    with st.spinner("Fetching Morningstar data for each fund..."):
        for _, row in funds.iterrows():
            fund, msid = row["Fund"], row["Ticker"]
            if fund not in weights or pd.isna(msid):
                continue
            try:
                per_fund[fund] = _load_fund_analytics(msid)
            except Exception as e:
                failed.append(f"{fund} ({e})")
    if not per_fund:
        st.error("No Morningstar data available for any fund.")
        if failed:
            st.caption("Failures: " + "; ".join(failed))
        return

    active_weights = {f: w for f, w in weights.items() if f in per_fund}
    agg = aggregate_portfolio(per_fund, active_weights)

    # --- Data-completeness disclaimer -------------------------------------
    # Classify each fund: full data, equity-only-partial (few holdings),
    # bond fund (no equity sectors/stylebox), or failed.
    complete, partial_holdings, bond_funds = [], [], []
    for fund in funds["Fund"]:
        if fund not in per_fund:
            continue
        d = per_fund[fund]
        n_hold = d.get("n_holdings_disclosed", 0)
        has_sectors = bool(d.get("sectors"))
        # A disclosed-holdings count of exactly 10 (or fewer) signals Morningstar
        # only publishes the top-10 for that fund => partial look-through.
        if not has_sectors and d.get("bond_stylebox"):
            bond_funds.append(fund)
        elif n_hold <= 10:
            partial_holdings.append(fund)
        else:
            complete.append(fund)

    st.caption(
        "Portfolio X-Ray reconstructed from Morningstar's public "
        "security_details endpoint, with each fund's data weighted by its "
        "current market value."
    )
    parts = []
    if complete:
        parts.append(f"**Full data:** {', '.join(complete)}")
    if bond_funds:
        parts.append(f"**Bond fund (no equity sectors / style box, by nature):** "
                     f"{', '.join(bond_funds)}")
    if partial_holdings:
        parts.append(f"**Partial look-through (Morningstar discloses only the "
                     f"top 10 holdings):** {', '.join(partial_holdings)}")
    if failed:
        parts.append(f"**Unavailable:** {', '.join(failed)}")
    st.info("  \n".join(parts))

    # --- Overview ----------------------------------------------------------
    total_value = sum(active_weights.values())
    holdings = agg["holdings"]
    n_holdings = len(holdings) if not holdings.empty else 0
    c1, c2, c3 = st.columns(3)
    c1.metric("Portfolio Value", fmt_eur(total_value, "{:,.2f} €"))
    c2.metric("Instruments", f"{len(per_fund)}")
    c3.metric("Aggregate Holdings", f"{n_holdings}")

    st.divider()

    # --- Asset Allocation + Currency Exposure ------------------------------
    col_aa, col_ccy = st.columns(2)

    with col_aa:
        st.subheader("Asset Allocation")
        alloc = agg["asset_allocation"]
        labels = [l for l in ASSET_CLASS_ORDER if l in alloc]
        vals = [alloc[l] for l in labels]
        fig = go.Figure(go.Bar(
            x=vals, y=labels, orientation="h",
            marker_color=["#3B6FD4", "#E8772E", "#6AA84F", "#E8C22E", "#BBBBBB"][:len(labels)],
            text=[f"{v:.1f}%" for v in vals], textposition="outside",
        ))
        fig.update_layout(height=320, margin=dict(l=10, r=30, t=10, b=10),
                          xaxis_title="Percentage %",
                          yaxis=dict(autorange="reversed"))
        st.plotly_chart(fig, width="stretch", config=get_plotly_config("asset_allocation"))

    with col_ccy:
        st.subheader("Currency Exposure")
        ccy = {k: v for k, v in sorted(agg["currency"].items(),
                                       key=lambda x: -x[1]) if v > 0.01}
        fig = go.Figure(go.Pie(
            labels=list(ccy.keys()), values=list(ccy.values()),
            hole=0.55, sort=False, textinfo="none",
            hovertemplate="%{label}: %{value:.2f}%<extra></extra>",
        ))
        fig.update_layout(height=320, margin=dict(l=10, r=10, t=10, b=10),
                          legend=dict(orientation="v", font=dict(size=11)))
        st.plotly_chart(fig, width="stretch", config=get_plotly_config("currency_exposure"))
        st.caption("Based on the market value of holdings in each currency "
                   "(net position per fund).")

    st.divider()

    # --- Equity Sector Exposure: pie + legend list -------------------------
    st.subheader("Equity Sector Exposure")
    sectors = dict(sorted(agg["sectors"].items(), key=lambda x: -x[1]))
    if sectors:
        col_pie, col_list = st.columns([3, 2])
        colors = _SECTOR_PALETTE[:len(sectors)]
        with col_pie:
            fig = go.Figure(go.Pie(
                labels=list(sectors.keys()), values=list(sectors.values()),
                hole=0.45, sort=False, textinfo="none",
                marker=dict(colors=colors),
                hovertemplate="%{label}: %{value:.2f}%<extra></extra>",
            ))
            fig.update_layout(height=360, margin=dict(l=10, r=10, t=10, b=10),
                              showlegend=False)
            st.plotly_chart(fig, width="stretch",
                            config=get_plotly_config("sector_exposure"))
        with col_list:
            rows = ['<div style="font-size:14px;line-height:2.0;">']
            for (name, val), col in zip(sectors.items(), colors):
                rows.append(
                    f'<div style="display:flex;justify-content:space-between;">'
                    f'<span><span style="display:inline-block;width:11px;height:11px;'
                    f'background:{col};border-radius:2px;margin-right:8px;"></span>{name}</span>'
                    f'<span style="font-weight:600;">{val:.2f}%</span></div>'
                )
            rows.append("</div>")
            st.markdown("".join(rows), unsafe_allow_html=True)
        st.caption("Percentages are of the equity component of the portfolio.")
    else:
        st.info("No sector data available.")

    st.divider()

    # --- Style Box ---------------------------------------------------------
    st.subheader("Style Box")
    col_eq, col_bd = st.columns(2)
    with col_eq:
        st.markdown("**Equity** — Size × Value/Blend/Growth")
        _render_stylebox(agg["stylebox"], STYLEBOX_ROWS, STYLEBOX_COLS, "#4C78A8")
    with col_bd:
        st.markdown("**Bonds** — Rate sensitivity × Credit quality")
        _render_stylebox(agg["bond_stylebox"], BOND_STYLEBOX_ROWS, BOND_STYLEBOX_COLS, "#F58518")
    st.caption("Equity weighted on the equity sleeve; Bonds on the bond sleeve.")

    st.divider()

    # --- Look-through holdings (filterable, scrollable accordion) ----------
    st.subheader(f"Holdings: {n_holdings}")
    if holdings.empty:
        st.info("No holdings available.")
        return

    st.caption("Ordered by weight on the total portfolio. Expand a holding to "
               "see which of your funds hold it and its weight within each fund.")

    # Compact styling: tighter expander headers and inner tables flush to the row.
    st.markdown("""
        <style>
        div[data-testid="stExpander"] details {
            border: none;
            border-bottom: 1px solid rgba(255,255,255,0.08);
            border-radius: 0;
        }
        div[data-testid="stExpander"] summary {
            padding: 2px 6px;
            font-size: 13px;
            min-height: 0;
        }
        div[data-testid="stExpander"] summary p { font-size: 13px; margin: 0; }
        div[data-testid="stExpander"] details > div[data-testid="stExpanderDetails"] {
            padding: 2px 6px 6px 22px;
        }
        div[data-testid="stExpander"] div[data-testid="stExpanderDetails"] table {
            font-size: 12px;
        }
        </style>
    """, unsafe_allow_html=True)

    fcol, ncol = st.columns([3, 2])
    with fcol:
        query = st.text_input("Filter by holding name", "",
                              placeholder="e.g. NVIDIA, ASML, Apple...").strip()
    with ncol:
        show_all = st.toggle("Show all", value=False,
                             help="Render every matching holding (may be slower "
                                  "with hundreds of rows).")

    view = holdings
    if query:
        view = view[view["SecurityName"].str.contains(query, case=False, na=False)]

    n_match = len(view)
    if n_match == 0:
        st.info(f"No holdings match '{query}'.")
        return

    if show_all or n_match <= 10:
        top_n = n_match
    else:
        default = min(50, n_match)
        top_n = st.slider("Positions to show", 10, n_match, default, step=10)

    st.caption(f"Showing {top_n} of {n_match}"
               + (f" matching '{query}'" if query else "") + ".")

    # Scrollable container with one compact expander per holding.
    with st.container(height=520):
        for _, row in view.head(top_n).iterrows():
            name = row["SecurityName"] or "—"
            pw = row["PortfolioWeight"]
            label = f"{name}  ·  {pw:.2f}%"
            with st.expander(label):
                bd = row.get("Breakdown") or []
                if not bd:
                    st.write("No per-fund detail available.")
                    continue
                detail = pd.DataFrame([
                    {
                        "Fund": b["fund"],
                        "Weight in fund": f"{b['fund_weight']:.2f}%",
                        "Weight in portfolio": f"{b['portfolio_weight']:.2f}%",
                    }
                    for b in bd
                ])
                try:
                    st.dataframe(detail, width="stretch", hide_index=True,
                                 row_height=28)
                except TypeError:
                    # row_height requires streamlit >= 1.43
                    st.dataframe(detail, width="stretch", hide_index=True)