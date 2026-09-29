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
from datetime import datetime, date

from components.chart_helpers import get_plotly_config
from config import FUND_COLORS
from utils.official_data import fetch_official_portfolio, OfficialUnavailable, provider_for
from utils.privacy import fmt_eur, render_page_header, privacy_on, MASK
from utils.formatting import f_pct, style_cols
from utils.morningstar_api import (
    fetch_security_details_xml,
    parse_fund_analytics,
    fetch_global_breakdowns,
    apply_global_overlay,
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


def _days_ago(date_str):
    """Return integer days between date_str (YYYY-MM-DD) and today, or None."""
    if not date_str:
        return None
    try:
        d = datetime.strptime(date_str[:10], "%Y-%m-%d").date()
        return (date.today() - d).days
    except Exception:
        return None


def _months_between(a: str, b: str) -> int:
    """Mesi interi tra due date YYYY-MM-DD (b - a), su base fine mese."""
    ya, ma = int(a[:4]), int(a[5:7])
    yb, mb = int(b[:4]), int(b[5:7])
    return (yb - ya) * 12 + (mb - ma)


def _render_data_freshness(funds: pd.DataFrame, per_fund: dict,
                           official: dict | None = None) -> None:
    """Show how fresh each fund's Morningstar data is, and how it's sourced.

    `official` = {fund: dict da fetch_official_portfolio | {"error": msg}}:
    aggiunge la data della scheda ufficiale e il confronto con Morningstar.
    """
    official = official or {}
    ms_behind = []     # funds where the official factsheet is newer than Morningstar
    rows = []
    stale_vs_ms = []   # funds where Morningstar has something newer than shown
    unverified = []    # funds where the global check failed
    for fund in funds["Fund"]:
        d = per_fund.get(fund)
        if not d:
            continue
        fr = d.get("freshness", {}) or {}
        pdate = fr.get("portfolio_date")
        bdate = fr.get("breakdown_date") or pdate
        ndate = fr.get("nav_date")
        prev = fr.get("prev_portfolio_date")
        latest = fr.get("latest_on_morningstar")
        # Cadenza stimata dalla distanza tra le due date di composizione.
        cadence = "—"
        if pdate and prev:
            try:
                gap = (datetime.strptime(pdate[:10], "%Y-%m-%d")
                       - datetime.strptime(prev[:10], "%Y-%m-%d")).days
                cadence = "Monthly" if 20 <= gap <= 40 else f"~{gap}d"
            except Exception:
                pass
        if fr.get("global_error") or not latest:
            check = "unverified"
            unverified.append(fund)
        elif bdate and latest > bdate[:10]:
            check = f"behind ({latest})"
            stale_vs_ms.append(fund)
        else:
            check = "✓ latest"
        off = official.get(fund) or {}
        off_date = off.get("as_of")
        if off_date and pdate:
            lag = _months_between(pdate[:10], off_date)
            if lag > 0:
                vs_off = f"holdings {lag} month{'s' if lag > 1 else ''} behind"
                ms_behind.append(fund)
            else:
                vs_off = "✓ in sync"
        elif off.get("error"):
            vs_off = "not checkable"
        else:
            vs_off = "—"
        pago = _days_ago(pdate)
        rows.append({
            "Fund": fund,
            "Holdings as of": pdate or "n/a",
            "Age (days)": pago,
            "Sectors & allocation as of": bdate or "n/a",
            "Latest on Morningstar": check,
            "Official factsheet as of": off_date or "n/a",
            "Morningstar vs official": vs_off,
            "Cadence": cadence,
            "Currency exposure": d.get("currency_source", "fund"),
            "Latest NAV": ndate or "n/a",
        })
    if not rows:
        return

    # Sommario: la data di composizione più vecchia guida il "semaforo".
    ages = [r["Age (days)"] for r in rows if r["Age (days)"] is not None]
    worst = max(ages, default=None)
    with st.expander("ℹ️ Data freshness & sourcing", expanded=False):
        if stale_vs_ms:
            st.error("Morningstar has newer data than shown for: "
                     f"{', '.join(stale_vs_ms)}. Try again later (cache: 6h).")
        elif worst is not None and worst <= 45:
            st.success(f"Holdings composition is current "
                       f"(latest data up to {worst} days old).")
        elif worst is not None and unverified:
            st.warning(f"Holdings are up to {worst} days old. Could not check "
                       "Morningstar's global API for: "
                       f"{', '.join(unverified)}, so newer sector / allocation "
                       "data may exist there. Try again later (cache: 6h).")
        elif worst is not None and not ms_behind:
            st.info(f"Holdings are up to {worst} days old. This is the most "
                    "recent composition Morningstar has for these funds, but "
                    "Morningstar can lag the fund houses: the official factsheets "
                    "(document section of each fund page in Active Funds) may "
                    "already show a newer month-end.")
        if ms_behind:
            st.info("Morningstar lags the fund houses' own factsheets for: "
                    f"{', '.join(ms_behind)}. Their newer top holdings and sectors "
                    "are in the **Official factsheets** tab.")
        blocked = [f for f, o in official.items() if (o or {}).get("error")]
        if blocked:
            st.caption("Official factsheet not checkable automatically for: "
                       f"{', '.join(blocked)} (the fund house's site blocks servers). "
                       "Links are in the Official factsheets tab.")
        st.markdown(
            "**How it works.** Holdings, style box and currency exposure come "
            "from Morningstar's public `security_details` endpoint "
            "(`lt.morningstar.com`). Sector and asset-allocation breakdowns are "
            "also checked on Morningstar's global site API, which sometimes "
            "receives them a month earlier; the newer one is used. Everything "
            "is cached for 6 hours. Two clocks matter: the **composition**, "
            "disclosed **monthly** with a lag, and the **latest NAV**, which is "
            "typically daily."
        )
        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
        st.caption("‘Latest on Morningstar’ compares what is shown with the newest "
                   "composition date Morningstar exposes. ‘Morningstar vs official’ "
                   "compares Morningstar's holdings date with the fund house's own "
                   "latest factsheet. ‘Currency exposure’: "
                   "‘fund’ = published by the fund; ‘holdings’ = rebuilt from the "
                   "disclosed holdings; ‘category proxy’ = category average, used "
                   "only when the fund publishes neither.")


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def _load_fund_analytics(msid: str, _cache_version: int = 3) -> dict:
    """Download and parse Morningstar analytics for a single fund (cached).

    1. security_details XML (lt.morningstar.com): every block, incl. holdings,
       style box and currency exposure. Raises if unavailable, so failures
       are not cached and are retried on the next run.
    2. Global site API: newer sector / asset-allocation breakdowns when
       Morningstar has them there first. Best effort: if it fails the XML
       data is used as-is and the freshness check shows "unverified".

    _cache_version bumps invalidate stale cached results after the parser's
    output shape changes.
    """
    data = parse_fund_analytics(fetch_security_details_xml(msid))
    sec_id = data.get("sec_id")
    if sec_id:
        try:
            data = apply_global_overlay(data, fetch_global_breakdowns(sec_id))
        except Exception as e:  # overlay is optional
            data.setdefault("freshness", {})["global_error"] = f"{type(e).__name__}: {e}"
    return data


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
# Official factsheets (fund houses' own data)
# -----------------------------------------------------------------------------

@st.cache_data(ttl=6 * 3600, show_spinner=False)
def _load_official(isin: str, url: str, _cache_version: int = 1) -> dict:
    """Official top-10 / sectors / regions for one fund (cached 6h).

    "Site blocks servers" is a stable condition and is cached as an error
    entry; transient failures raise, so they are retried on the next run.
    """
    try:
        return fetch_official_portfolio(isin, url)
    except OfficialUnavailable as e:
        return {"error": str(e), "provider": provider_for(url), "url": url}


def _load_all_official(funds: pd.DataFrame, only: set) -> dict:
    out = {}
    for _, row in funds.iterrows():
        fund = row["Fund"]
        if fund not in only:
            continue
        url = row.get("URL") if "URL" in funds.columns else None
        if pd.isna(url) or not url:
            continue
        try:
            out[fund] = _load_official(row["ISIN"], url)
        except Exception as e:
            out[fund] = {"error": f"temporarily unavailable ({type(e).__name__})",
                         "provider": provider_for(url), "url": url, "transient": True}
    return out


def _bar_fund_vs_bench(df: pd.DataFrame, color: str, key: str, height: int | None = None):
    """Horizontal grouped bars: fund vs benchmark (benchmark only if present)."""
    df = df.copy()
    df["Fund %"] = pd.to_numeric(df["Fund %"], errors="coerce")
    df = df.sort_values("Fund %", ascending=True)
    fig = go.Figure()
    has_bench = bool(pd.to_numeric(df["Benchmark %"], errors="coerce").notna().any())
    if has_bench:
        fig.add_trace(go.Bar(y=df["Name"], x=df["Benchmark %"], orientation="h",
                             name="Benchmark", marker_color="rgba(200,200,200,0.45)",
                             hovertemplate="%{y}: %{x:.1f}%<extra>Benchmark</extra>"))
    fig.add_trace(go.Bar(y=df["Name"], x=df["Fund %"], orientation="h", name="Fund",
                         marker_color=color, text=[f"{v:.1f}%" for v in df["Fund %"]],
                         textposition="outside", cliponaxis=False,
                         hovertemplate="%{y}: %{x:.1f}%<extra>Fund</extra>"))
    fig.update_layout(barmode="group", height=height or max(260, 26 * len(df) + 80),
                      margin=dict(l=10, r=40, t=10, b=10), xaxis_title="%",
                      legend=dict(orientation="h", yanchor="bottom", y=1.0, x=0),
                      bargap=0.25, showlegend=has_bench)
    st.plotly_chart(fig, width="stretch", config=get_plotly_config(key))


def _render_official(funds: pd.DataFrame, official: dict, weights: dict,
                     per_fund: dict) -> None:
    """Fund-by-fund view of the fund houses' latest official data."""
    st.caption(
        "Latest data published by each fund house (the same source as the PDF "
        "factsheets). Official sources disclose only the **top 10 holdings**, and "
        "each fund house uses its **own sector labels**, so this view is shown "
        "fund by fund and is not combined with the Morningstar X-Ray."
    )

    # Summary
    rows = []
    for fund in funds["Fund"]:
        o = official.get(fund)
        if o is None:
            continue
        ms_date = ((per_fund.get(fund) or {}).get("freshness") or {}).get("portfolio_date")
        rows.append({
            "Fund": fund,
            "Source": o.get("provider") or "—",
            "Official as of": o.get("as_of") or "n/a",
            "Morningstar holdings as of": ms_date or "n/a",
            "Status": "✓ available" if not o.get("error") else o["error"],
            "Official page": o.get("url") or "",
        })
    if not rows:
        st.info("No official page URL configured for the active funds "
                "(column URL in funds.csv).")
        return
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True,
                 column_config={"Official page": st.column_config.LinkColumn(
                     "Official page", display_text="open ↗")})

    available = [r["Fund"] for r in rows if not official[r["Fund"]].get("error")]
    if not available:
        st.info("No official data could be read automatically right now.")
        return

    fund = st.segmented_control("Fund", available, default=available[0],
                                key="official_fund") or available[0]
    o = official[fund]
    color = FUND_COLORS.get(fund, "#4C78A8")
    value = weights.get(fund)

    st.markdown(f"#### {fund} · {o.get('provider')} · as of {o.get('as_of') or 'n/a'}")

    col_h, col_s = st.columns(2, gap="medium")
    with col_h:
        st.markdown("**Top 10 holdings**")
        h = o.get("holdings")
        if h is None or h.empty:
            st.info("No holdings published.")
        else:
            h = h.copy()
            cfg = {"Weight %": st.column_config.NumberColumn("Weight", format="%.2f%%")}
            if value is not None:
                h["Your exposure"] = h["Weight %"].astype(float) / 100.0 * value
                if privacy_on():
                    h["Your exposure"] = MASK
                else:
                    cfg["Your exposure"] = st.column_config.NumberColumn(
                        "Your exposure", format="€%.2f",
                        help="Weight × current value of your position in this fund")
            if h["Sector"].isna().all():
                h = h.drop(columns=["Sector"])
            st.dataframe(h, width="stretch", hide_index=True, column_config=cfg)
            st.caption(f"Top 10 = {h['Weight %'].astype(float).sum():.1f}% of the fund.")
    with col_s:
        st.markdown("**Sectors**" + (" (net = long + short)" if o.get("long_short") else ""))
        sec = o.get("sectors")
        if sec is None or sec.empty:
            st.info("No sector breakdown published.")
        else:
            _bar_fund_vs_bench(sec, color, f"official_sectors_{fund}")

    if o.get("long_short") and o.get("sectors") is not None:
        sec = o["sectors"]
        c1, c2, c3 = st.columns(3)
        c1.metric("Gross long", f"{pd.to_numeric(sec['Long %']).sum():.1f}%")
        c2.metric("Gross short", f"{pd.to_numeric(sec['Short %']).sum():.1f}%")
        c3.metric("Net", f"{pd.to_numeric(sec['Fund %']).sum():.1f}%")
        with st.expander("Long / short detail by sector"):
            st.dataframe(sec[["Name", "Long %", "Short %", "Fund %", "Benchmark %"]]
                         .rename(columns={"Fund %": "Net %"}),
                         width="stretch", hide_index=True,
                         column_config={c: st.column_config.NumberColumn(format="%.1f")
                                        for c in ["Long %", "Short %", "Net %", "Benchmark %"]})

    reg = o.get("regions")
    if reg is not None and not reg.empty:
        st.markdown("**Countries / regions**")
        _bar_fund_vs_bench(reg, color, f"official_regions_{fund}")

    blocked = [r["Fund"] for r in rows if official[r["Fund"]].get("error")]
    if blocked:
        st.caption("Not readable automatically: " + ", ".join(blocked)
                   + ". Use the ‘open ↗’ links above to see their factsheets.")


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

    # --- Official factsheets (fund houses) -------------------------------
    with st.spinner("Checking the fund houses' official factsheets..."):
        official = _load_all_official(funds, set(active_weights))

    # --- Data freshness (both sources) ------------------------------------
    _render_data_freshness(funds, per_fund, official)

    tab_xray, tab_official = st.tabs([
        "🔎 Morningstar X-Ray (full look-through)",
        "🏛️ Official factsheets (latest)",
    ])
    with tab_official:
        _render_official(funds, official, weights, per_fund)

    with tab_xray:
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
                            "Weight in fund": b["fund_weight"],
                            "Weight in portfolio": b["portfolio_weight"],
                        }
                        for b in bd
                    ])
                    detail = style_cols(detail.style, {"Weight in fund": f_pct(),
                                                       "Weight in portfolio": f_pct()})
                    try:
                        st.dataframe(detail, width="stretch", hide_index=True,
                                     row_height=28)
                    except TypeError:
                        # row_height requires streamlit >= 1.43
                        st.dataframe(detail, width="stretch", hide_index=True)