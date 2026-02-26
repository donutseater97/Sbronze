"""
main.py — Entry point dell'applicazione Streamlit "Sbronze Treasure Hunt".

Questo file è il punto di ingresso letto da Streamlit Cloud.
Non contiene logica di business: si limita a:
1. Configurare la pagina e l'autenticazione
2. Caricare i dati globali (fondi, transazioni, prezzi storici)
3. Popolare FUND_COLORS dai dati dei fondi
4. Definire la navigazione tra le pagine
5. Iniettare il CSS globale
6. Avviare pg.run()

Ogni pagina è definita in un file separato dentro pages/.
"""

# =============================================================================
# IMPORTS
# =============================================================================
import streamlit as st
import pandas as pd

# Configurazione globale e caricamento dati
from config import (
    APP_TITLE,
    FUND_COLORS,
    load_funds_and_transactions,
    load_historical_prices,
)

# Pagine dell'applicazione
from pages.overview_and_charts import overview_and_charts
from pages.daily_dashboard import daily_dashboard
from pages.evolution_of_portfolio import evolution_of_portfolio
from pages.transaction_history import transaction_history
from pages.active_funds import active_funds
from pages.historical_prices import historical_prices
from pages.add_transactions_and_funds import add_transactions_and_funds


# =============================================================================
# CONFIGURAZIONE PAGINA — deve essere la prima chiamata Streamlit
# =============================================================================
st.set_page_config(page_title=APP_TITLE, layout="wide")
st.title(f"📊 {APP_TITLE}")


# =============================================================================
# AUTENTICAZIONE — Stato sessione per l'area admin
# =============================================================================
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False


# =============================================================================
# CARICAMENTO DATI GLOBALI
# =============================================================================

# Carica fondi e transazioni dai CSV
funds, transactions = load_funds_and_transactions()

# Popola la mappa colori globale {fund_name: '#RRGGBB'}
for _, row in funds.iterrows():
    FUND_COLORS[row["Fund"]] = row["Colour"]

# Costruisci lista ticker Yahoo Finance (ticker + ".F" per borsa di Francoforte)
yahoo_tickers = [f"{t}.F" for t in funds["Ticker"].dropna().unique()]

# Inizializza il filtro fondi nello stato sessione
if "fund_filter" not in st.session_state:
    st.session_state.fund_filter = funds["Fund"].tolist() if len(funds) > 0 else []

# Carica prezzi storici dal CSV generato da GitHub Actions
hist_data_global = load_historical_prices(funds)

# Calcola la data più recente dei dati storici (usata nell'header)
if len(hist_data_global) > 0 and "date" in hist_data_global.columns:
    _latest_hist_date = pd.to_datetime(hist_data_global["date"]).max()
    last_date_str = _latest_hist_date.strftime("%Y-%m-%d") if pd.notna(_latest_hist_date) else "-"
else:
    last_date_str = "-"


# =============================================================================
# TEMA — Stato sessione per dark/light mode
# =============================================================================
if "theme_dark" not in st.session_state:
    st.session_state.theme_dark = True


# =============================================================================
# NAVIGAZIONE — Menu laterale con le 6 pagine
# =============================================================================
pg = st.navigation({
    "Sbronze Menu": [
        # Ogni st.Page wrappa la funzione pagina passando i parametri globali.
        # url_path esplicito perché tutte usano lambda (altrimenti Streamlit
        # deduce "<lambda>" per tutte e lancia un errore di duplicati).
        st.Page(
            lambda: overview_and_charts(funds, transactions, hist_data_global, last_date_str),
            title="📊 Overview & Charts",
            url_path="overview",
        ),
        st.Page(
            lambda: daily_dashboard(funds, transactions, hist_data_global, last_date_str),
            title="📋 Daily Dashboard",
            url_path="dashboard",
        ),
        st.Page(
            lambda: evolution_of_portfolio(funds, transactions, hist_data_global),
            title="📊 Evolution of Portfolio",
            url_path="evolution",
        ),
        st.Page(
            lambda: historical_prices(funds, transactions, hist_data_global, yahoo_tickers),
            title="📈 Historical Data Charts",
            url_path="historical",
        ),
        st.Page(
            lambda: transaction_history(funds, transactions, hist_data_global, last_date_str),
            title="📜 Transaction History",
            url_path="transactions",
        ),
        st.Page(
            lambda: active_funds(funds),
            title="📋 Active Funds",
            url_path="funds",
        ),
        st.Page(
            lambda: add_transactions_and_funds(funds, transactions),
            title="➕ Add Transactions & Funds",
            url_path="admin",
        ),
    ]
})


# =============================================================================
# CSS GLOBALE — Stile navigazione e bottoni
# =============================================================================
st.markdown("""
<style>
    /* Stile voci navigazione sidebar */
    div[data-testid="stSidebarNav"] ul { padding: 0; }
    div[data-testid="stSidebarNav"] li { margin: 0.3rem 0; }

    div[data-testid="stSidebarNav"] a {
        padding: 0.85rem 1rem !important;
        border-radius: 0.5rem !important;
        color: rgba(150, 150, 150, 0.75) !important;
        font-size: 0.95rem !important;
        font-weight: 400 !important;
        text-decoration: none !important;
    }

    div[data-testid="stSidebarNav"] a:hover {
        background-color: rgba(255, 255, 255, 0.05) !important;
        color: rgba(180, 180, 180, 0.9) !important;
    }

    /* Pagina attiva nel menu */
    div[data-testid="stSidebarNav"] a[aria-current="page"] {
        background-color: rgba(255, 255, 255, 0.12) !important;
        color: rgba(255, 255, 255, 1) !important;
        font-size: 1.05rem !important;
        font-weight: 700 !important;
    }
</style>
""", unsafe_allow_html=True)


# =============================================================================
# AVVIO APPLICAZIONE
# =============================================================================
pg.run()
