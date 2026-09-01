"""
pages/portfolio_analysis.py — "Portfolio Analysis" page.

Reads pre-computed analytics from data/analytics/ (produced by
scripts/compute_analytics.py in the GitHub Action) and presents them. NO heavy
computation happens here, so navigation stays fast. Sections:

  1. Summary metrics (Sharpe, Sortino, CAGR, vol, max drawdown) per fund + portfolio
  2. Rolling evolution charts (volatility per fund / portfolio, average & pairwise correlation)
  3. Correlation matrix heatmap (daily / monthly)
  4. Risk contribution by fund
  5. Downloads — individual XLSX exports of every series/matrix, via a dropdown

All euro-free (returns, correlations, ratios), so privacy mode does not mask it,
except the weights note which references current market value.
"""

import io
import os

import numpy as np
import pandas as pd
import streamlit as st
import plotly.graph_objects as go

from config import FUND_COLORS
from components.chart_helpers import get_plotly_config
from utils.privacy import render_page_header

_ANALYTICS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "analytics"
)


# -----------------------------------------------------------------------------
# Cached loaders (cheap CSV reads, refreshed every 5 min)
# -----------------------------------------------------------------------------

@st.cache_data(ttl=300, show_spinner=False)
def _load_csv(name: str, index_col=0, parse_dates=False):
    path = os.path.join(_ANALYTICS_DIR, name)
    if not os.path.exists(path):
        return None
    return pd.read_csv(path, index_col=index_col, parse_dates=parse_dates)


def _to_xlsx_bytes(df: pd.DataFrame, sheet_name="Sheet1") -> bytes:
    """Serialize a DataFrame to XLSX bytes for download."""
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name=sheet_name[:31])
    return buf.getvalue()


# Catalogue of downloadable analytics files: label -> (filename, is_dated_index)
_DOWNLOADS = {
    "NAV — daily": ("nav_daily.csv", True),
    "NAV — monthly": ("nav_monthly.csv", True),
    "Returns — daily": ("returns_daily.csv", True),
    "Returns — monthly": ("returns_monthly.csv", True),
    "Covariance — daily (annualized)": ("cov_daily.csv", False),
    "Covariance — monthly (annualized)": ("cov_monthly.csv", False),
    "Correlation — daily": ("corr_daily.csv", False),
    "Correlation — monthly": ("corr_monthly.csv", False),
}


# -----------------------------------------------------------------------------
# Page
# -----------------------------------------------------------------------------

def portfolio_analysis(funds: pd.DataFrame, transactions: pd.DataFrame,
                       hist_data: pd.DataFrame, last_date_str: str):
    """Render the Portfolio Analysis page from pre-computed analytics."""
    render_page_header("📊 Portfolio Analysis")

    meta = _load_csv("analytics_meta.csv", index_col=None)
    if meta is None:
        st.warning(
            "Analytics have not been generated yet. They are produced by "
            "`scripts/compute_analytics.py` in the GitHub Action after each data "
            "update. Run it once locally (`python scripts/compute_analytics.py`) "
            "or wait for the next scheduled run."
        )
        return

    m = meta.iloc[0]
    st.caption(
        f"Risk & correlation analytics computed from the daily NAV history, from "
        f"the first common date **{m['common_start']}** to **{m['last_date']}**. "
        f"Pre-computed offline (generated {m['generated_at']}); this page only "
        f"reads the results. Returns are simple; annualization uses "
        f"√{int(m['trading_days'])} (daily) and √12 (monthly); missing dates are "
        f"forward-filled."
    )

    # ==================================================================
    # 1. Summary metrics
    # ==================================================================
    st.subheader("Key metrics")
    metrics = _load_csv("metrics_summary.csv", index_col=None)
    if metrics is not None:
        port = metrics[metrics["Name"] == "Portfolio"]
        if not port.empty:
            p = port.iloc[0]
            c1, c2, c3, c4, c5 = st.columns(5)
            c1.metric("Portfolio CAGR", _pct(p["CAGR"]))
            c2.metric("Ann. Volatility", _pct(p["AnnVol"]))
            c3.metric("Sharpe", _num(p["Sharpe"]))
            c4.metric("Sortino", _num(p["Sortino"]))
            c5.metric("Max Drawdown", _pct(p["MaxDrawdown"]))

        show = metrics.copy()
        for col in ["CAGR", "AnnVol", "MaxDrawdown"]:
            show[col] = show[col].apply(_pct)
        for col in ["Sharpe", "Sortino"]:
            show[col] = show[col].apply(_num)
        show = show.rename(columns={
            "Name": "Fund", "AnnVol": "Ann. Vol", "MaxDrawdown": "Max DD",
            "MeanDailyRet": "Mean daily",
        }).drop(columns=["Mean daily"])
        st.dataframe(show, width="stretch", hide_index=True)
        st.caption("Sharpe/Sortino use the risk-free rate below; risk-free "
                   "changes rescale only these two ratios (done live).")

        # Live risk-free control — cheap, so recompute Sharpe/Sortino on the fly.
        rf = st.slider("Risk-free rate (annual %) for Sharpe/Sortino", 0.0, 6.0,
                       float(m.get("risk_free_default", 0.0)) * 100, 0.25) / 100
        if rf != float(m.get("risk_free_default", 0.0)):
            _render_live_ratios(rf)

    st.divider()

    # ==================================================================
    # 2. Rolling evolution charts
    # ==================================================================
    st.subheader(f"Rolling evolution ({int(m['rolling_window_days'])}-day window)")

    vol_fund = _load_csv("rolling_vol_fund.csv", parse_dates=True)
    vol_port = _load_csv("rolling_vol_portfolio.csv", parse_dates=True)
    if vol_fund is not None:
        fig = go.Figure()
        for f in vol_fund.columns:
            fig.add_trace(go.Scatter(
                x=vol_fund.index, y=vol_fund[f] * 100, mode="lines", name=f,
                line=dict(color=FUND_COLORS.get(f, "#999999"), width=1.4),
            ))
        if vol_port is not None:
            fig.add_trace(go.Scatter(
                x=vol_port.index, y=vol_port["Portfolio"] * 100, mode="lines",
                name="Portfolio", line=dict(color="#e6edf3", width=2.6, dash="dot"),
            ))
        _dark(fig, "Annualized volatility (%)", height=380)
        st.plotly_chart(fig, width="stretch",
                        config=get_plotly_config("rolling_vol"))
        st.caption("Rolling annualized volatility per fund; the dotted white "
                   "line is the portfolio (current market-value weights).")

    corr_avg = _load_csv("rolling_corr_avg.csv", parse_dates=True)
    corr_pairs = _load_csv("rolling_corr_pairs.csv", parse_dates=True)
    if corr_avg is not None:
        pair_opts = list(corr_pairs.columns) if corr_pairs is not None else []
        sel = st.multiselect(
            "Show pairwise correlations (optional)", pair_opts, default=[],
            help="Add specific fund pairs on top of the portfolio average.",
        )
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=corr_avg.index, y=corr_avg["AvgPairwiseCorr"], mode="lines",
            name="Avg pairwise", line=dict(color="#e6edf3", width=2.6),
        ))
        for pair in sel:
            fig.add_trace(go.Scatter(
                x=corr_pairs.index, y=corr_pairs[pair], mode="lines", name=pair,
                line=dict(width=1.2),
            ))
        _dark(fig, "Correlation", height=380, yrange=[-0.2, 1.0])
        st.plotly_chart(fig, width="stretch",
                        config=get_plotly_config("rolling_corr"))
        st.caption("Average pairwise correlation across the portfolio. Rising "
                   "correlation means less diversification benefit.")

    st.divider()

    # ==================================================================
    # 3. Correlation matrix heatmap
    # ==================================================================
    st.subheader("Correlation matrix")
    freq = st.radio("Frequency", ["Daily", "Monthly"], horizontal=True,
                    key="corr_freq")
    corr = _load_csv("corr_daily.csv" if freq == "Daily" else "corr_monthly.csv")
    if corr is not None:
        _render_heatmap(corr)
        st.caption("Correlation of simple returns over the full common history.")

    st.divider()

    # ==================================================================
    # 4. Risk contribution
    # ==================================================================
    st.subheader("Risk contribution by fund")
    rc = _load_csv("risk_contribution.csv", index_col=None)
    if rc is not None:
        col_chart, col_tbl = st.columns([3, 2])
        with col_chart:
            fig = go.Figure(go.Bar(
                x=rc["Fund"], y=rc["RiskContributionPct"] * 100,
                marker_color=[FUND_COLORS.get(f, "#999999") for f in rc["Fund"]],
                text=[f"{v*100:.1f}%" for v in rc["RiskContributionPct"]],
                textposition="outside",
            ))
            _dark(fig, "Share of portfolio risk (%)", height=340)
            st.plotly_chart(fig, width="stretch",
                            config=get_plotly_config("risk_contrib"))
        with col_tbl:
            disp = rc.copy()
            disp["RiskContributionPct"] = (disp["RiskContributionPct"] * 100).map("{:.1f}%".format)
            disp = disp.rename(columns={"RiskContributionPct": "Risk %",
                                        "RiskContribution": "Risk (abs)"})
            st.dataframe(disp[["Fund", "Risk %"]], width="stretch", hide_index=True)
        st.caption("How much each fund contributes to total portfolio risk "
                   "(marginal contribution × weight). Sums to 100%.")

    st.divider()

    # ==================================================================
    # 5. Downloads
    # ==================================================================
    st.subheader("Download analytics (XLSX)")
    st.caption("Each file exports one series or matrix. Pick one or more, then "
               "download individually.")
    picks = st.multiselect("Files", list(_DOWNLOADS.keys()),
                           default=["Correlation — daily"])
    if picks:
        cols = st.columns(min(len(picks), 3))
        for i, label in enumerate(picks):
            fname, dated = _DOWNLOADS[label]
            df = _load_csv(fname, index_col=0, parse_dates=dated)
            if df is None:
                continue
            xlsx = _to_xlsx_bytes(df, sheet_name=label.split(" — ")[0])
            out_name = fname.replace(".csv", ".xlsx")
            with cols[i % len(cols)]:
                st.download_button(
                    f"⬇️ {label}", data=xlsx, file_name=out_name,
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    width="stretch", key=f"dl_{fname}",
                )


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------

def _pct(v):
    try:
        return f"{float(v)*100:.2f}%"
    except (ValueError, TypeError):
        return "—"


def _num(v):
    try:
        return f"{float(v):.2f}"
    except (ValueError, TypeError):
        return "—"


def _dark(fig, ytitle, height=360, yrange=None):
    fig.update_layout(
        height=height, template="plotly_dark",
        paper_bgcolor="#0d1117", plot_bgcolor="#0d1117",
        font=dict(family="sans-serif", color="#e6edf3", size=12),
        margin=dict(l=50, r=20, t=20, b=30),
        yaxis_title=ytitle, hovermode="x unified",
        legend=dict(orientation="h", y=-0.18),
    )
    fig.update_xaxes(gridcolor="rgba(230,237,243,0.08)")
    fig.update_yaxes(gridcolor="rgba(230,237,243,0.08)")
    if yrange:
        fig.update_yaxes(range=yrange)


def _render_heatmap(corr: pd.DataFrame):
    z = corr.values
    fig = go.Figure(go.Heatmap(
        z=z, x=list(corr.columns), y=list(corr.index),
        colorscale="RdBu_r", zmin=-1, zmax=1, zmid=0,
        text=[[f"{v:.2f}" for v in row] for row in z],
        texttemplate="%{text}", textfont=dict(size=12),
        colorbar=dict(title="ρ"),
    ))
    fig.update_layout(
        height=420, template="plotly_dark",
        paper_bgcolor="#0d1117", plot_bgcolor="#0d1117",
        font=dict(family="sans-serif", color="#e6edf3", size=12),
        margin=dict(l=60, r=20, t=20, b=40), yaxis_autorange="reversed",
    )
    st.plotly_chart(fig, width="stretch", config=get_plotly_config("corr_matrix"))


def _render_live_ratios(rf: float):
    """Recompute Sharpe/Sortino at a user-chosen risk-free from daily returns.
    Cheap: one read of returns_daily.csv (cached)."""
    rd = _load_csv("returns_daily.csv", parse_dates=True)
    if rd is None:
        return
    ann = np.sqrt(252)
    rf_daily = rf / 252
    rows = []
    for f in rd.columns:
        r = rd[f].dropna()
        std = r.std()
        dn = r[r < 0].std()
        rows.append({
            "Fund": f,
            "Sharpe": round((r.mean() - rf_daily) / std * ann, 3) if std > 0 else None,
            "Sortino": round((r.mean() - rf_daily) / dn * ann, 3) if dn and dn > 0 else None,
        })
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)