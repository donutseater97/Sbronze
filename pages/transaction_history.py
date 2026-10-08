"""
pages/transaction_history.py — Pagina "Transaction History".

Mostra la cronologia completa delle transazioni con:
- Filtro fondi e filtro per data
- Tabella dettagliata con contributi, quantità, delta, ecc.
- Metriche totali (gross contribution, net invested, fees, P/L)

Switch (US (old) → US (a), ecc.): compaiono come due righe con colonna
"Operation" (⇄ Switch Out / ⇄ Switch In). Non sono versamenti: per loro il
"Gross Contribution" è il controvalore trasferito (negativo in uscita,
positivo in entrata), i campi teorici (Δ vs Exp, Quantity theor) sono vuoti
e i totali "Contributions" contano solo i Buy.
"""

import streamlit as st
from utils.privacy import privacy_on, fmt_eur, MASK, MASK_PLAIN, render_page_header
import pandas as pd

from config import FUND_COLORS
from components.fund_filter import render_fund_filter
from components.styling import style_fund_cell
from utils.formatting import (
    get_fund_qty_decimals,
    f_eur, f_pct, f_num, f_qty, f_date, sign_bg, style_cols,
)
from utils.transactions import (
    OP_SWITCH_OUT,
    is_buy,
    exit_price_by_fund,
    operation_label,
)


def transaction_history(
    funds: pd.DataFrame,
    transactions: pd.DataFrame,
    hist_data_global: pd.DataFrame,
    last_date_str: str,
):
    """Renderizza la pagina Transaction History.

    Args:
        funds:            DataFrame dei fondi.
        transactions:     DataFrame delle transazioni.
        hist_data_global: DataFrame prezzi storici.
        last_date_str:    Data più recente dei dati storici.
    """
    render_page_header("📜 Transaction History")

    # ===== FILTRO FONDI =====
    fund_list = funds["Fund"].tolist() if len(funds) > 0 else []
    filter_funds = render_fund_filter(fund_list, FUND_COLORS)

    # ===== FILTRO DATE =====
    col1, col2 = st.columns(2)
    with col1:
        if len(transactions) > 0:
            first_trans_date = pd.to_datetime(transactions["Date"]).min().date()
            if "trans_start_date" not in st.session_state or st.session_state.trans_start_date < first_trans_date:
                st.session_state.trans_start_date = first_trans_date
            start_date = st.date_input("Start Date:", value=st.session_state.trans_start_date, key="trans_start_date_input")
        else:
            start_date = None
    with col2:
        if len(transactions) > 0:
            max_date = pd.to_datetime(transactions["Date"]).max().date()
            end_date = st.date_input("End Date:", value=max_date, key="trans_end_date")
        else:
            end_date = None

    if len(transactions) > 0:
        start_date = st.session_state.trans_start_date_input

    # ===== NESSUNA TRANSAZIONE =====
    if len(transactions) == 0:
        st.info("No transactions yet")
        return

    # ----- Filtra transazioni -----
    trans_df = transactions.copy()
    trans_df["Date"] = pd.to_datetime(trans_df["Date"], errors="coerce")

    if filter_funds:
        trans_df = trans_df[trans_df["Fund"].isin(filter_funds)]
    if start_date:
        trans_df = trans_df[trans_df["Date"] >= pd.to_datetime(start_date)]
    if end_date:
        trans_df = trans_df[trans_df["Date"] <= pd.to_datetime(end_date)]

    trans_df = trans_df.sort_values("Date", ascending=False)

    # ----- Calcola campi derivati -----
    # Buy: versamento teorico arrotondato ai 10 € e relativi Δ.
    # Switch: controvalore trasferito esatto (segno della quantità), Δ vuoti.
    _buy = is_buy(trans_df)
    trans_df["Reference Period"] = trans_df["Date"].dt.strftime("%Y %b")
    trans_df["Gross Contribution (real)"] = trans_df["Quantity"] * trans_df["Price (€)"] + trans_df["Fees (€)"]
    trans_df["Gross Contribution (theor)"] = (
        ((trans_df["Gross Contribution (real)"] / 10).round() * 10)
        .where(_buy, trans_df["Gross Contribution (real)"])
    )
    trans_df["Net Invested"] = trans_df["Quantity"] * trans_df["Price (€)"]
    trans_df["Δ Net Inv vs Exp"] = (
        trans_df["Net Invested"] - trans_df["Gross Contribution (theor)"] + trans_df["Fees (€)"]
    ).where(_buy)
    trans_df["Quantity (theor)"] = (
        (trans_df["Gross Contribution (theor)"] - trans_df["Fees (€)"]) / trans_df["Price (€)"]
    ).where(_buy)
    trans_df["Δ Quantity"] = trans_df["Quantity"] - trans_df["Quantity (theor)"]
    trans_df["Date_str"] = trans_df["Date"].dt.strftime("%Y-%m-%d")

    # ----- P/L per transazione (rispetto al NAV più recente del fondo) -----
    # Le fee sono già scontate nella quantità acquistata, quindi il P/L confronta
    # semplicemente il valore attuale della tranche col prezzo pagato.
    # Fondo uscito via switch (quantità 0): il riferimento è il NAV di uscita,
    # cioè il P/L realizzato della tranche. La riga Switch Out non ha P/L
    # (sarebbe un doppio conteggio delle tranche che chiude).
    _latest_nav = {}
    if hist_data_global is not None and len(hist_data_global) > 0 and "date" in hist_data_global.columns:
        _hd = hist_data_global.sort_values("date")
        _last = _hd.iloc[-1]
        for _f in transactions["Fund"].unique():
            if _f in _hd.columns and pd.notna(_last.get(_f)):
                _latest_nav[_f] = float(_last[_f])
    _latest_nav.update(exit_price_by_fund(transactions))
    _is_out = trans_df["Operation"] == OP_SWITCH_OUT
    trans_df["_pl_eur"] = trans_df.apply(
        lambda r: r["Quantity"] * (_latest_nav[r["Fund"]] - r["Price (€)"])
        if r["Fund"] in _latest_nav else float("nan"), axis=1).where(~_is_out)
    trans_df["_pl_pct"] = trans_df.apply(
        lambda r: (_latest_nav[r["Fund"]] / r["Price (€)"] - 1.0) * 100.0
        if r["Fund"] in _latest_nav and r["Price (€)"] else float("nan"), axis=1).where(~_is_out)

    # Precisione decimale per fondo
    fund_qty_decimals = get_fund_qty_decimals(transactions)

    # ----- DataFrame di display: SOLO valori numerici / date -----
    # Il testo mostrato viene da Styler.format, così l'ordinamento per colonna
    # di st.dataframe usa il valore reale (prima le colonne erano stringhe e si
    # ordinavano alfabeticamente). Le colonne combinate "valore (Δ)" sono state
    # separate in due colonne, entrambe ordinabili.
    pv = privacy_on()
    display_df = pd.DataFrame({
        "Reference Period": trans_df["Date"].dt.to_period("M").dt.to_timestamp(),
        "Date": trans_df["Date"].dt.normalize(),
        "Fund": trans_df["Fund"],
        "Operation": [operation_label(o, l) for o, l in
                      zip(trans_df["Operation"], trans_df["Linked Fund"])],
        "Price (€)": trans_df["Price (€)"],
        "Quantity": trans_df["Quantity"],
        "Fees (€)": trans_df["Fees (€)"],
        "Gross Contribution": trans_df["Gross Contribution (theor)"],
        "Net Invested": trans_df["Net Invested"],
        "Δ vs Exp": trans_df["Δ Net Inv vs Exp"],
        "Quantity (theor)": trans_df["Quantity (theor)"],
        "Δ vs Q real": trans_df["Δ Quantity"],
        "P/L (€)": trans_df["_pl_eur"],
        "P/L (%)": trans_df["_pl_pct"],
    }).reset_index(drop=True)

    # Privacy: oscura tutte le colonne valore tranne Price (NAV pubblico) e P/L %.
    eur_masked = ["Fees (€)", "Gross Contribution", "Net Invested", "Δ vs Exp", "P/L (€)"]
    qty_masked = ["Quantity", "Quantity (theor)", "Δ vs Q real"]
    # Colori dei Δ calcolati prima di mascherare (il segno resta visibile,
    # come prima: in privacy mode è nascosto solo l'importo)
    _dni_sign = display_df["Δ vs Exp"].round(2)
    if pv:
        # Valore costante (non NaN: st.dataframe mostra "None" per le celle vuote,
        # ignorando il formatter). Colonna costante => l'ordinamento non rivela nulla.
        display_df[eur_masked + qty_masked] = 0.0

    # Δ quantità arrotondato ai decimali del fondo (per il colore)
    def _dq_rounded(i):
        dq = trans_df["Δ Quantity"].iloc[i]
        if pd.isna(dq):
            return float("nan")
        dp = fund_qty_decimals.get(display_df.at[i, "Fund"], 3)
        r = round(dq, dp)
        return 0.0 if abs(r) < 10 ** (-dp) else r
    _dq_col = pd.Series([_dq_rounded(i) for i in range(len(display_df))], index=display_df.index)
    _pl_pct = display_df["P/L (%)"]

    # ----- Stile tabella -----
    def style_rows(row):
        i = row.name
        styles = []
        for col in row.index:
            if col == "Fund":
                styles.append(style_fund_cell(row["Fund"], FUND_COLORS))
            elif col == "Operation":
                styles.append("" if row["Operation"] == "Buy"
                              else "color: #e0a030; font-style: italic;")
            elif col == "Δ vs Exp":
                styles.append(sign_bg(_dni_sign.at[i]))
            elif col == "Δ vs Q real":
                styles.append(sign_bg(_dq_col.at[i]))
            elif col in ("P/L (€)", "P/L (%)"):
                v = _pl_pct.at[i]
                styles.append("" if pd.isna(v) else sign_bg(v, zero_neutral=False))
            else:
                styles.append("")
        return styles

    styled_df = display_df.style.apply(style_rows, axis=1)
    styled_df = style_cols(styled_df, {
        "Reference Period": f_date("%Y %b"),
        "Date": f_date("%Y-%m-%d"),
        "Price (€)": f_eur(thousands=False),
    })
    if pv:
        styled_df = styled_df.format(lambda v: MASK, subset=eur_masked, na_rep=MASK)
        styled_df = styled_df.format(lambda v: MASK_PLAIN, subset=qty_masked, na_rep=MASK_PLAIN)
    else:
        styled_df = style_cols(styled_df, {
            "Quantity": f_qty(),
            "Fees (€)": f_eur(thousands=False),
            "Gross Contribution": f_eur(thousands=False),
            "Net Invested": f_num(2),
            "Δ vs Exp": f_num(2, signed=True),
            "P/L (€)": f_eur(signed=True, sign_after_symbol=True),
        }, na_rep="—")
        # Quantità teorica e Δ: decimali del singolo fondo (un blocco per fondo)
        for fund, dp in fund_qty_decimals.items():
            rows = display_df.index[display_df["Fund"] == fund]
            if len(rows):
                styled_df = styled_df.format(f_num(dp), subset=pd.IndexSlice[rows, ["Quantity (theor)"]], na_rep="—")
                styled_df = styled_df.format(f_num(dp, signed=True), subset=pd.IndexSlice[rows, ["Δ vs Q real"]], na_rep="—")
    styled_df = style_cols(styled_df, {"P/L (%)": f_pct(signed=True)}, na_rep="—")

    st.dataframe(styled_df, width="stretch", hide_index=True)

    # CSS per testo piccolo nelle metriche
    st.markdown("""
    <style>
    [data-testid="stMetric"] small { font-size: 0.5em !important; opacity: 0.7; }
    </style>
    """, unsafe_allow_html=True)

    # ===== TOTALS =====
    st.markdown("")
    st.markdown("**Totals (based on filters):**")

    # Contributi e P/L approx. contano solo i Buy (versamenti reali): gli
    # switch spostano denaro già investito tra due fondi. Le fee contano tutte.
    buys_df = trans_df[is_buy(trans_df)]
    n_switch_rows = int((~is_buy(trans_df)).sum())
    total_gross_theor = buys_df["Gross Contribution (theor)"].sum()
    total_net_invested = buys_df["Net Invested"].sum()
    total_fees = trans_df["Fees (€)"].sum()
    fees_pct = (total_fees / total_gross_theor * 100) if total_gross_theor > 0 else 0.0
    pl_price_approx = buys_df["Δ Net Inv vs Exp"].sum()

    # P/L Quantity
    hist_data = hist_data_global
    pl_qty_approx = 0.0
    pl_qty_approx_now = 0.0
    if len(hist_data) > 0 and "date" in hist_data.columns:
        latest_date = pd.to_datetime(hist_data["date"]).max()
        for _, row in buys_df.iterrows():
            fund = row["Fund"]
            dq_raw = row["Δ Quantity"]
            dp = fund_qty_decimals.get(fund, 3)
            dq = round(dq_raw, dp) if pd.notna(dq_raw) else None
            if dq is not None and abs(dq) < 10 ** (-dp):
                dq = 0.0
            if pd.notna(dq):
                pl_qty_approx += dq * row["Price (€)"]
                if fund in hist_data.columns:
                    lp = hist_data[hist_data["date"] == latest_date][fund].values
                    if len(lp) > 0 and pd.notna(lp[0]):
                        pl_qty_approx_now += dq * lp[0]

    num_contributions = len(buys_df)

    # Display totals
    r1c1, r1c2, r1c3 = st.columns(3)
    with r1c1:
        st.metric("Total Gross Contribution", fmt_eur(total_gross_theor))
    with r1c2:
        st.metric("Total Net Invested", fmt_eur(total_net_invested))
    with r1c3:
        st.metric("Fees", fmt_eur(total_fees), delta=None if privacy_on() else f"↓{fees_pct:.2f}%", delta_color="off")

    r2c1, r2c2, r2c3 = st.columns(3)
    with r2c1:
        pl_price_pct = (pl_price_approx / total_gross_theor * 100) if total_gross_theor > 0 else 0
        st.metric(
            "P/L Price approx.", fmt_eur(pl_price_approx, "€ {:+,.2f}"),
            delta=None if privacy_on() else f"{pl_price_pct:+.2f}%",
            delta_color="normal" if pl_price_approx >= 0 else "off",
        )
    with r2c2:
        if privacy_on():
            pl_qty_display = MASK
        else:
            pl_qty_display = (
                f"€ {pl_qty_approx:+,.2f} (Now: € {pl_qty_approx_now:+,.2f})"
                if last_date_str != "-" else f"€ {pl_qty_approx:+,.2f}"
            )
        st.metric(f"P/L Quantity approx. (as of {last_date_str})", pl_qty_display)
    with r2c3:
        st.metric("Number of Contributions", f"{num_contributions}")

    if n_switch_rows:
        st.caption(f"⇄ {n_switch_rows} switch row(s) in view: excluded from "
                   "contributions, net invested, P/L approx. and the contribution "
                   "count (they move money already invested between funds); "
                   "their fees are included in Fees.")