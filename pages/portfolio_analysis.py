"""
pages/portfolio_analysis.py — "Portfolio Analysis" page.

Reads pre-computed analytics from data/analytics/ (produced by
scripts/compute_analytics.py in the GitHub Action). A few controls recompute
cheaply in-page from the pre-computed daily returns: the risk-free rate (updates
the key-metrics table in place), the rolling window, and the weighting scheme.

Sections (top to bottom):
  0. Downloads — a one-line accordion (fieldset of per-file links + checkboxes,
     plus a "Download selected" ZIP button)
  1. Key metrics — CAGR, vol, Sharpe, Sortino, max drawdown; parametrizable
  2. Portfolio composition — uses the chosen weights (current portfolio insight)
  3. Rolling evolution — volatility (parametrizable window) + correlation
  4. Correlation matrix heatmap
  5. Risk contribution — parametrizable by weighting scheme

Every metric/section has an info help icon with its definition/context.
Euro-free (returns, ratios, correlations), so privacy mode does not mask it.
"""

import io
import os
import zipfile

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

TRADING_DAYS = 252

_PAGE_BG = "#0d1117"
_PAGE_TEXT = "#e6edf3"
_GRID = "rgba(230,237,243,0.08)"
_PORT_LINE = "#e6edf3"


@st.cache_data(ttl=300, show_spinner=False)
def _load_csv(name, index_col=0, parse_dates=False):
    path = os.path.join(_ANALYTICS_DIR, name)
    if not os.path.exists(path):
        return None
    return pd.read_csv(path, index_col=index_col, parse_dates=parse_dates)


def _to_xlsx_bytes(df, sheet_name="Sheet1"):
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name=sheet_name[:31])
    return buf.getvalue()


_DOWNLOADS = {
    "NAV — daily": ("nav_daily.csv", True),
    "NAV — monthly": ("nav_monthly.csv", True),
    "Returns — daily": ("returns_daily.csv", True),
    "Returns — monthly": ("returns_monthly.csv", True),
    "Covariance — daily (annualized)": ("cov_daily.csv", False),
    "Covariance — monthly (annualized)": ("cov_monthly.csv", False),
    "Correlation — daily": ("corr_daily.csv", False),
    "Correlation — monthly": ("corr_monthly.csv", False),
    "Weights": ("weights.csv", False)
}


def portfolio_analysis(funds, transactions, hist_data, last_date_str):
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

    returns_daily = _load_csv("returns_daily.csv", parse_dates=True)
    weights_df = _load_csv("weights.csv")
    fund_cols = list(returns_daily.columns) if returns_daily is not None else []

    st.caption(
        f"Risk & correlation analytics from the first common date "
        f"**{m['common_start']}** to **{m['last_date']}**. Base series are "
        f"pre-computed offline (generated {m['generated_at']}); the controls "
        f"below recompute cheaply in-page. Returns are simple; annualization "
        f"uses √{int(m['trading_days'])} (daily) / √12 (monthly); missing dates "
        f"are forward-filled."
    )

    # 0. DOWNLOADS
    _render_downloads()
    st.divider()

    # 1. KEY METRICS
    _hdr("Key metrics",
         "Risk/return summary per fund and for the portfolio. CAGR is the "
         "annualized growth rate; Ann. Vol is the annualized standard deviation "
         "of daily returns; Sharpe and Sortino divide excess return by total and "
         "downside volatility; Max DD is the worst peak-to-trough drop. "
         "Sharpe/Sortino use the risk-free rate you set below.")
    cparam1, cparam2 = st.columns(2)
    with cparam1:
        rf = st.slider("Risk-free rate (annual %)", 0.0, 6.0,
                       float(m.get("risk_free_default", 0.0)) * 100, 0.25,
                       help="Annual risk-free return subtracted from fund returns "
                            "in the Sharpe/Sortino ratios.") / 100
    with cparam2:
        weight_scheme = st.selectbox(
            "Portfolio weighting", ["Market value", "Invested capital", "Equal"],
            index=0, help="Weights used to build the portfolio return series and "
                          "its metrics. 'Market value' = quantity × latest NAV.")
    weights = _weights_for(weights_df, weight_scheme, fund_cols)

    if returns_daily is not None:
        metrics = _compute_metrics(returns_daily, fund_cols, weights, rf)
        _render_metrics_scorecards(metrics)
        _render_metrics_table(metrics)
    st.divider()

    # 2. COMPOSITION
    _hdr("Portfolio composition & diversification",
         "The weights currently driving the portfolio metrics, plus the "
         "diversification ratio = (weighted average of single-fund volatilities) "
         "÷ (portfolio volatility). Well above 1 means diversification is "
         "reducing risk; near 1 means little benefit.")
    if returns_daily is not None:
        _render_composition(returns_daily, fund_cols, weights)
    st.divider()

    # 3. ROLLING
    _hdr("Rolling evolution",
         "Volatility and correlation over a moving window of the chosen length, "
         "one point per day. Rising correlation or volatility signals fading "
         "diversification / higher risk.")
    window = st.segmented_control(
        "Rolling window", [30, 60, 90, 120, 180, 252],
        default=int(m.get("rolling_window_days", 90)),
        format_func=lambda d: f"{d}d", key="roll_window",
    ) or int(m.get("rolling_window_days", 90))
    if returns_daily is not None:
        _render_rolling_vol(returns_daily, fund_cols, weights, window)
        _render_rolling_corr(returns_daily, fund_cols, window)
    st.divider()

    # 4. CORRELATION MATRIX
    _hdr("Correlation matrix",
         "Pearson correlation of the funds' simple returns over the full common "
         "history. +1 = move together, 0 = unrelated, −1 = opposite. Lower "
         "correlations improve diversification.")
    freq = st.radio("Frequency", ["Daily", "Monthly"], horizontal=True,
                    key="corr_freq")
    corr = _load_csv("corr_daily.csv" if freq == "Daily" else "corr_monthly.csv")
    if corr is not None:
        _render_heatmap(corr)
    st.divider()

    # 5. RISK CONTRIBUTION
    _hdr("Risk contribution by fund",
         "Each fund's share of total portfolio risk = weight × marginal "
         "contribution to volatility, ÷ portfolio variance. Sums to 100%. A fund "
         "can carry more risk than its weight if it is volatile or highly "
         "correlated with the rest.")
    cov_d = _load_csv("cov_daily.csv")
    if cov_d is not None:
        _render_risk_contribution(cov_d, fund_cols, weights)


def _render_downloads():
    with st.expander("⬇️  Download analytics (XLSX)", expanded=False):
        st.markdown(
            "<fieldset style='border:1px solid rgba(230,237,243,0.15);"
            "border-radius:6px;padding:8px 14px;'>"
            "<legend style='padding:0 6px;color:#8b949e;font-size:13px;'>"
            "Analytics files</legend>",
            unsafe_allow_html=True,
        )
        selected = []
        for label, (fname, dated) in _DOWNLOADS.items():
            row = st.columns([0.5, 5, 2])
            with row[0]:
                if st.checkbox("select", key=f"chk_{fname}",
                               label_visibility="collapsed"):
                    selected.append((label, fname, dated))
            with row[1]:
                st.markdown(f"<div style='padding-top:4px;'>{label}</div>",
                            unsafe_allow_html=True)
            with row[2]:
                df = _load_csv(fname, index_col=0, parse_dates=dated)
                if df is not None:
                    st.download_button(
                        "Download", data=_to_xlsx_bytes(df, label.split(" — ")[0]),
                        file_name=fname.replace(".csv", ".xlsx"),
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        key=f"dl_{fname}", width="stretch")
        st.markdown("</fieldset>", unsafe_allow_html=True)

        if selected:
            zbuf = io.BytesIO()
            with zipfile.ZipFile(zbuf, "w", zipfile.ZIP_DEFLATED) as zf:
                for label, fname, dated in selected:
                    df = _load_csv(fname, index_col=0, parse_dates=dated)
                    if df is not None:
                        zf.writestr(fname.replace(".csv", ".xlsx"),
                                    _to_xlsx_bytes(df, label.split(" — ")[0]))
            st.download_button(
                f"⬇️ Download selected ({len(selected)})", data=zbuf.getvalue(),
                file_name="portfolio_analytics.zip", mime="application/zip",
                key="dl_selected", type="primary")
        else:
            st.caption("Tick one or more files to enable 'Download selected'.")


def _weights_for(weights_df, scheme, funds):
    col = {"Market value": "MarketValue", "Invested capital": "Invested",
           "Equal": "Equal"}.get(scheme, "MarketValue")
    if weights_df is not None and col in weights_df.columns:
        w = {f: float(weights_df.loc[f, col]) for f in funds if f in weights_df.index}
        tot = sum(w.values())
        if tot > 0:
            return {f: w.get(f, 0.0) / tot for f in funds}
    return {f: 1.0 / len(funds) for f in funds}


def _compute_metrics(returns_daily, funds, weights, rf):
    ann = np.sqrt(TRADING_DAYS)
    rf_daily = rf / TRADING_DAYS
    w = pd.Series({f: weights.get(f, 0.0) for f in funds})
    port_ret = (returns_daily[funds] * w).sum(axis=1)
    port_prices = (1 + port_ret).cumprod()

    def _one(name, ret, prices):
        ret = ret.dropna()
        mean_d, std_d = ret.mean(), ret.std()
        dn = ret[ret < 0].std()
        cagr = (prices.iloc[-1] / prices.iloc[0]) ** (TRADING_DAYS / len(prices)) - 1 \
            if len(prices) > 1 and prices.iloc[0] > 0 else np.nan
        mdd = float((prices / prices.cummax() - 1).min())
        return {"Fund": name, "CAGR": cagr, "AnnVol": std_d * ann,
                "Sharpe": (mean_d - rf_daily) / std_d * ann if std_d > 0 else np.nan,
                "Sortino": (mean_d - rf_daily) / dn * ann if dn and dn > 0 else np.nan,
                "MaxDD": mdd}

    rows = [_one(f, returns_daily[f], (1 + returns_daily[f].fillna(0)).cumprod())
            for f in funds]
    rows.append(_one("Portfolio", port_ret, port_prices))
    return pd.DataFrame(rows)


def _render_metrics_scorecards(metrics):
    port = metrics[metrics["Fund"] == "Portfolio"]
    if port.empty:
        return
    p = port.iloc[0]
    c = st.columns(5)
    c[0].metric("Portfolio CAGR", _pct(p["CAGR"]))
    c[1].metric("Ann. Volatility", _pct(p["AnnVol"]))
    c[2].metric("Sharpe", _num(p["Sharpe"]))
    c[3].metric("Sortino", _num(p["Sortino"]))
    c[4].metric("Max Drawdown", _pct(p["MaxDD"]))


def _render_metrics_table(metrics):
    show = metrics.copy()
    for col in ["CAGR", "AnnVol", "MaxDD"]:
        show[col] = show[col].apply(_pct)
    for col in ["Sharpe", "Sortino"]:
        show[col] = show[col].apply(_num)
    show = show.rename(columns={"AnnVol": "Ann. Vol", "MaxDD": "Max DD"})
    st.dataframe(show, width="stretch", hide_index=True)


def _render_composition(returns_daily, funds, weights):
    ann = np.sqrt(TRADING_DAYS)
    vols = {f: returns_daily[f].dropna().std() * ann for f in funds}
    w = pd.Series({f: weights.get(f, 0.0) for f in funds})
    port_vol = ((returns_daily[funds] * w).sum(axis=1)).std() * ann
    wavg_vol = float(sum(w[f] * vols[f] for f in funds))
    div_ratio = (wavg_vol / port_vol) if port_vol > 0 else np.nan

    col_pie, col_stat = st.columns([3, 2])
    with col_pie:
        fig = go.Figure(go.Pie(
            labels=funds, values=[w[f] * 100 for f in funds], hole=0.5,
            marker=dict(colors=[FUND_COLORS.get(f, "#999999") for f in funds]),
            textinfo="label+percent", sort=False,
            hovertemplate="%{label}: %{value:.1f}%<extra></extra>"))
        fig.update_layout(height=320, template="plotly_dark", paper_bgcolor=_PAGE_BG,
                          plot_bgcolor=_PAGE_BG, font=dict(color=_PAGE_TEXT, size=12),
                          margin=dict(l=10, r=10, t=10, b=10), showlegend=False)
        st.plotly_chart(fig, width="stretch", config=get_plotly_config("comp_pie"))
    with col_stat:
        st.metric("Diversification ratio", _num(div_ratio))
        st.metric("Weighted avg fund vol", _pct(wavg_vol))
        st.metric("Portfolio vol", _pct(port_vol))
        st.caption(f"Diversification cuts volatility from a weighted "
                   f"{_pct(wavg_vol)} down to {_pct(port_vol)}.")


def _render_rolling_vol(returns_daily, funds, weights, window):
    ann = np.sqrt(TRADING_DAYS)
    vol_fund = (returns_daily[funds].rolling(window).std() * ann).dropna(how="all")
    w = pd.Series({f: weights.get(f, 0.0) for f in funds})
    port_ret = (returns_daily[funds] * w).sum(axis=1)
    vol_port = (port_ret.rolling(window).std() * ann).dropna()

    fig = go.Figure()
    for f in funds:
        fig.add_trace(go.Scatter(x=vol_fund.index, y=vol_fund[f] * 100,
                                 mode="lines", name=f,
                                 line=dict(color=FUND_COLORS.get(f, "#999999"), width=1.4)))
    fig.add_trace(go.Scatter(x=vol_port.index, y=vol_port * 100, mode="lines",
                             name="Portfolio",
                             line=dict(color=_PORT_LINE, width=2.6, dash="dot")))
    _dark(fig, "Annualized volatility (%)", 380)
    st.plotly_chart(fig, width="stretch", config=get_plotly_config("rolling_vol"))
    st.caption(f"{window}-day rolling annualized volatility per fund; the dotted "
               f"white line is the portfolio.")


def _render_rolling_corr(returns_daily, funds, window):
    pairs = [(a, b) for i, a in enumerate(funds) for b in funds[i + 1:]]
    corr_pairs = pd.DataFrame(index=returns_daily.index)
    for a, b in pairs:
        corr_pairs[f"{a}~{b}"] = returns_daily[a].rolling(window).corr(returns_daily[b])
    corr_pairs = corr_pairs.dropna(how="all")
    corr_avg = corr_pairs.mean(axis=1)

    sel = st.multiselect("Show pairwise correlations (optional)",
                         list(corr_pairs.columns), default=[],
                         help="Overlay specific fund pairs on the portfolio average.")
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=corr_avg.index, y=corr_avg, mode="lines",
                             name="Avg pairwise", line=dict(color=_PORT_LINE, width=2.6)))
    for pair in sel:
        fig.add_trace(go.Scatter(x=corr_pairs.index, y=corr_pairs[pair], mode="lines",
                                 name=pair, line=dict(width=1.2)))
    _dark(fig, "Correlation", 380, yrange=[-0.2, 1.0])
    st.plotly_chart(fig, width="stretch", config=get_plotly_config("rolling_corr"))
    st.caption(f"{window}-day rolling average pairwise correlation. Rising = less "
               f"diversification benefit.")


def _render_heatmap(corr):
    z = corr.values
    fig = go.Figure(go.Heatmap(
        z=z, x=list(corr.columns), y=list(corr.index),
        colorscale="RdBu_r", zmin=-1, zmax=1, zmid=0,
        text=[[f"{v:.2f}" for v in row] for row in z],
        texttemplate="%{text}", textfont=dict(size=12), colorbar=dict(title="ρ")))
    fig.update_layout(height=420, template="plotly_dark", paper_bgcolor=_PAGE_BG,
                      plot_bgcolor=_PAGE_BG, font=dict(color=_PAGE_TEXT, size=12),
                      margin=dict(l=60, r=20, t=20, b=40), yaxis_autorange="reversed")
    st.plotly_chart(fig, width="stretch", config=get_plotly_config("corr_matrix"))


def _render_risk_contribution(cov_d, funds, weights):
    w = np.array([weights.get(f, 0.0) for f in funds])
    Sigma = cov_d.loc[funds, funds].values
    port_var = float(w @ Sigma @ w)
    if port_var <= 0:
        st.info("Risk contribution unavailable (zero portfolio variance).")
        return
    rc = w * (Sigma @ w)
    rc_pct = rc / port_var

    col_chart, col_tbl = st.columns([3, 2])
    with col_chart:
        fig = go.Figure(go.Bar(
            x=list(funds), y=rc_pct * 100,
            marker_color=[FUND_COLORS.get(f, "#999999") for f in funds],
            text=[f"{v*100:.1f}%" for v in rc_pct], textposition="outside"))
        _dark(fig, "Share of portfolio risk (%)", 340)
        st.plotly_chart(fig, width="stretch", config=get_plotly_config("risk_contrib"))
    with col_tbl:
        disp = pd.DataFrame({
            "Fund": funds,
            "Weight": [f"{weights.get(f,0)*100:.1f}%" for f in funds],
            "Risk %": [f"{v*100:.1f}%" for v in rc_pct]})
        st.dataframe(disp, width="stretch", hide_index=True)
    st.caption("Compare 'Risk %' to 'Weight': funds where risk exceeds weight are "
               "the volatile / highly-correlated drivers of portfolio risk.")


def _hdr(title, help_text):
    st.subheader(title, help=help_text)


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
    fig.update_layout(height=height, template="plotly_dark", paper_bgcolor=_PAGE_BG,
                      plot_bgcolor=_PAGE_BG,
                      font=dict(family="sans-serif", color=_PAGE_TEXT, size=12),
                      margin=dict(l=50, r=20, t=20, b=30), yaxis_title=ytitle,
                      hovermode="x unified", legend=dict(orientation="h", y=-0.18))
    fig.update_xaxes(gridcolor=_GRID)
    fig.update_yaxes(gridcolor=_GRID)
    if yrange:
        fig.update_yaxes(range=yrange)