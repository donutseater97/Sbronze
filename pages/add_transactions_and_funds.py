"""
pages/add_transactions_and_funds.py — Pagina admin "Add Transactions & Funds".

Pagina protetta da password che consente di:
- Aggiungere nuove transazioni (acquisti)
- Aggiungere nuovi fondi al portafoglio
- Committare automaticamente le modifiche su GitHub via API
"""

import time
import streamlit as st
import pandas as pd
from datetime import date

from config import (
    FUND_COLORS,
    FUNDS_FILE,
    FUNDS_REPO_PATH,
    TRANSACTIONS_FILE,
    TRANSACTIONS_REPO_PATH,
    OWNER_PASSWORD,
    GITHUB_TOKEN,
    GITHUB_REPO,
    github_put_file,
)


def add_transactions_and_funds(
    funds: pd.DataFrame,
    transactions: pd.DataFrame,
):
    """Renderizza la pagina Add Transactions & Funds.

    ⚠️ Modifica in-place i DataFrame globali `funds` e `transactions`
    e li salva su disco + GitHub.

    Args:
        funds:        DataFrame dei fondi (verrà modificato se si aggiunge un fondo).
        transactions: DataFrame delle transazioni (verrà modificato se si aggiunge una transazione).

    Returns:
        Tupla (funds_aggiornato, transactions_aggiornato).
    """

    # ===== AUTENTICAZIONE =====
    st.subheader("🔐 Authentication")
    if not st.session_state.authenticated:
        pwd = st.text_input("Enter password to edit data:", type="password")
        if pwd == OWNER_PASSWORD:
            st.session_state.authenticated = True
            st.rerun()
        elif pwd:
            st.error("Incorrect password")
        st.info("Enter password to add transactions and funds")
        return funds, transactions

    IS_OWNER = st.session_state.authenticated

    # ===== AGGIUNGI TRANSAZIONE =====
    st.header("💰 Add Transaction")
    if len(funds) == 0:
        st.info("Add a fund first")
    elif IS_OWNER:
        with st.form("add_Transaction"):
            fund_choice = st.selectbox("Fund", funds["Fund"].tolist())
            contrib_date = st.date_input("Date", date.today())
            price = st.number_input("Price (€)", min_value=0.0)
            quantity = st.number_input("Quantity", min_value=0.0, step=0.001, format="%f")
            fees = st.number_input("Fees (€)", min_value=0.0)
            submitted_c = st.form_submit_button("Add Transaction")

            if submitted_c:
                if quantity <= 0 or price <= 0:
                    st.error("Quantity and Price must be greater than 0")
                else:
                    # Crea nuova riga transazione
                    new_row = pd.DataFrame([{
                        "Date": pd.Timestamp(contrib_date),
                        "Fund": fund_choice,
                        "Price (€)": price,
                        "Quantity": quantity,
                        "Fees (€)": fees,
                    }])
                    transactions = pd.concat([transactions, new_row], ignore_index=True)

                    # Salva localmente
                    trans_to_save = transactions.copy()
                    trans_to_save["Date"] = pd.to_datetime(trans_to_save["Date"], errors="coerce")
                    trans_to_save["Date"] = trans_to_save["Date"].dt.strftime("%Y-%m-%d %H:%M:%S")
                    trans_to_save.to_csv(TRANSACTIONS_FILE, index=False)

                    # Push su GitHub (usa percorso repo-relativo per l'API)
                    transactions = _push_to_github(
                        trans_to_save, TRANSACTIONS_REPO_PATH,
                        f"Add transaction for {fund_choice} on {contrib_date.strftime('%Y-%m-%d')} via Streamlit",
                        transactions,
                    )

    st.divider()

    # ===== AGGIUNGI FONDO =====
    st.header("➕ Add Fund")
    if IS_OWNER:
        with st.form("add_fund"):
            fund_cat = st.text_input("Fund", placeholder="e.g., US, EU, EM, Tech")

            col1, col2 = st.columns(2)
            with col1:
                isin = st.text_input("ISIN", placeholder="e.g., LU0281484963")
                name = st.text_input("Fund Name", placeholder="e.g., JPMorgan Funds - US Select Equity Plus Fund D (acc) - EUR")
                fund_type = st.selectbox("Type", ["Equity", "Bond"])
            with col2:
                ticker = st.text_input("Ticker", placeholder="e.g., 0P0001CRXW")
                colour = st.color_picker("Colour", value="#C00000")
                fund_url = st.text_input("Official page URL (optional)",
                                         placeholder="https://...")
            submitted = st.form_submit_button("Add Fund")
            if submitted:
                # Validazione
                if not fund_cat.strip() or not isin.strip() or not ticker.strip() or not name.strip():
                    st.error("All fields are required")
                elif fund_cat in funds["Fund"].values:
                    st.error(f"Fund '{fund_cat}' already exists")
                elif isin in funds["ISIN"].values:
                    st.error(f"ISIN '{isin}' already exists")
                elif ticker in funds["Ticker"].values:
                    st.error(f"Ticker '{ticker}' already exists")
                else:
                    new_fund = pd.DataFrame([{
                        "Fund": fund_cat, "Ticker": ticker, "ISIN": isin,
                        "Fund Name": name, "Type": fund_type, "Colour": colour,
                        "URL": fund_url or "",
                    }])
                    funds = pd.concat([funds, new_fund], ignore_index=True)
                    funds.to_csv(FUNDS_FILE, index=False)

                    # Push su GitHub
                    try:
                        csv_str = funds.to_csv(index=False)
                        if GITHUB_TOKEN and GITHUB_REPO:
                            ok = github_put_file(FUNDS_REPO_PATH, csv_str, f"Add/Update fund '{fund_cat}' via Streamlit")
                            if ok:
                                st.success("Fund added and pushed to GitHub. GitHub Actions will refresh prices shortly.")
                            else:
                                st.warning("Fund saved locally but push to GitHub failed.")
                        else:
                            st.warning("Fund saved locally. To sync, configure GITHUB_TOKEN in Streamlit secrets.")
                    except Exception as e:
                        st.warning(f"Fund saved locally, but push failed: {e}")

                    st.rerun()

    return funds, transactions


def _push_to_github(df_to_save, file_path, message, original_df):
    """Tenta il push su GitHub con retry.

    Args:
        df_to_save:  DataFrame formattato per il salvataggio.
        file_path:   Percorso del file nel repo.
        message:     Messaggio di commit.
        original_df: DataFrame originale da restituire.

    Returns:
        Il DataFrame originale (invariato).
    """
    try:
        csv_str = df_to_save.to_csv(index=False)
        if GITHUB_TOKEN and GITHUB_REPO:
            ok = github_put_file(file_path, csv_str, message)
            if ok:
                st.success("✅ Transaction added and pushed to GitHub.")
                time.sleep(1)
                st.rerun()
            else:
                st.warning("⚠️ Transaction saved locally but GitHub push failed. Retrying...")
                try:
                    ok_retry = github_put_file(file_path, csv_str, message + " (retry)")
                    if ok_retry:
                        st.success("✅ Push successful (retry).")
                        time.sleep(1)
                        st.rerun()
                except Exception:
                    pass
        else:
            st.warning("⚠️ Transaction saved locally. Configure GITHUB_TOKEN to sync.")
            st.rerun()
    except Exception as e:
        st.error(f"❌ Error pushing to GitHub: {e}")
        st.info("Transaction saved locally. Check network and Streamlit secrets.")

    return original_df