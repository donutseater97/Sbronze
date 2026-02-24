# 📊 Sbronze Treasure Hunt

Applicazione di portfolio tracking e analisi costruita con **Streamlit**.
Traccia investimenti, visualizza performance e ottieni insight sul tuo portafoglio finanziario.

## 🎯 Funzionalità

### 📊 Overview & Charts
- **Filtro fondi**: seleziona singoli fondi o visualizza tutto il portafoglio
- **Mascheramento dati**: 🔒 nascondi valori sensibili ("***.*€") durante condivisione schermo
- **Metriche chiave**: Gross Contributions, Net Invested, Market Value, Total & Net Returns, Month-over-Month, pesi di portafoglio
- **Revenue P&L Chart**: profitto/perdita cumulativo giornaliero per fondo + totale portafoglio
- **Investment Evolution**: contributi lordi a scalini + overlay Market Value
- **Allocation Pies**: doppio grafico (Gross vs Market Value) raggruppabile per Fund, Type o Asset Manager

### 📊 Evolution of Portfolio
- **Daily NAV Table**: variazioni giornaliere assolute e percentuali per fondo
- **NAV Chart**: andamento NAV del portafoglio
- **Market Value Table**: evoluzione del controvalore
- **Holdings Area Chart**: composizione del portafoglio nel tempo

### 📈 Historical Data Charts
- **Combined View**: tutti i fondi su un unico grafico con linee media NAV
- **Grid View**: grafici individuali (fino a 3 per riga) con marker transazioni
- **Tabella prezzi storici**: variazioni giornaliere colorate, evidenziazione giorni transazione

### 📜 Transaction History
- Storico completo delle transazioni con filtri per fondo e data
- Conteggio contributi, NAV media, delta rispetto alla transazione precedente

### 📋 Active Funds
- Lista fondi attivi con colori identificativi

### ➕ Add Transactions & Funds (protetto da password)
- Interfaccia per aggiungere transazioni e fondi
- Push automatico su GitHub via REST API

## 🚀 Getting Started

### Prerequisiti
- Python 3.11+
- pip

### Installazione

```bash
git clone https://github.com/donutseater97/Sbronze.git
cd Sbronze
pip install -r requirements.txt
```

### Avvio

```bash
streamlit run main.py
```

Apri il browser su `http://localhost:8501`

## 📋 Struttura del Progetto

```
Sbronze/
├── main.py                         # Entry point Streamlit Cloud (navigazione + CSS)
├── config.py                       # Configurazione globale, caricamento dati, helper GitHub API
├── requirements.txt                # Dipendenze Python
├── get_historical_data.py          # Fetcher prezzi storici (Investgo + JPMorgan API)
├── README.md
│
├── data/                           # Dati CSV del portafoglio
│   ├── funds.csv                   # Definizioni fondi (ticker, ISIN, tipo, colore)
│   ├── transaction_history.csv     # Registro transazioni
│   ├── historical_data.csv         # Prezzi storici (aggiornati ogni ora da GitHub Actions)
│   ├── monthly_historical_data.csv # Dati mensili per matrice di correlazione
│   └── monthly_returns.csv         # Rendimenti mensili
│
├── pages/                          # Pagine dell'applicazione (una per sezione)
│   ├── overview_and_charts.py      # Riepilogo portafoglio, P&L, allocation pies
│   ├── evolution_of_portfolio.py   # Daily NAV, Market Value, Holdings
│   ├── historical_prices.py        # Grafici prezzi, tabella dati storici
│   ├── transaction_history.py      # Storico transazioni con filtri
│   ├── active_funds.py             # Lista fondi attivi
│   └── add_transactions_and_funds.py # Admin: aggiungi transazioni e fondi
│
├── components/                     # Componenti UI riutilizzabili
│   ├── styling.py                  # Conversioni colore, stili condizionali (verde/rosso)
│   ├── fund_filter.py              # Widget filtro fondi con bottoni colorati
│   └── chart_helpers.py            # Configurazione Plotly condivisa (assi, range selector)
│
├── utils/                          # Funzioni utility pure (nessuna dipendenza Streamlit)
│   └── formatting.py               # Formattazione numeri, valute, quantità
│
├── scripts/                        # Script standalone
│   └── extract_monthly_data_for_matrix.py  # Estrae dati mensili per matrice correlazione
│
└── .github/workflows/
    └── update-historical-data.yml  # Aggiornamento prezzi ogni ora (Investgo + JPMorgan)
```

## 🔧 Configurazione

### Fund Data (`data/funds.csv`)
| Colonna     | Descrizione                                          |
|-------------|------------------------------------------------------|
| `Fund`      | Identificativo breve (usato nel codice e nei filtri) |
| `Ticker`    | Ticker Yahoo Finance                                 |
| `ISIN`      | Codice ISIN                                          |
| `Fund Name` | Nome completo (prima parola = Asset Manager)         |
| `Type`      | Equity o Bond                                        |
| `Colour`    | Codice colore esadecimale per i grafici              |

### Transactions (`data/transaction_history.csv`)
| Colonna      | Descrizione               |
|--------------|---------------------------|
| `Date`       | Data transazione (YYYY-MM-DD) |
| `Fund`       | Identificativo fondo      |
| `Price (€)`  | Prezzo unitario           |
| `Quantity`   | Numero di quote           |
| `Fees (€)`   | Commissioni               |

## 📊 Data Processing

### Daily Portfolio Performance (DPP)
$DPP(t) = \sum_{f} \left[ qty_f(t-1) \times \left( price_f(t) - price_f(t-1) \right) \right]$

- Solo posizioni con quantità > 0
- Parte dalla data della prima transazione
- Calcolo per fondo dalla data del primo acquisto

### Returns
- **Gross Return** = Market Value − Gross Contributions
- **Net Return** = Market Value − (Gross Contributions + Fees)
- **Total Invested** = $\sum (Quantity \times Price + Fees)$

## 🔐 Security & Privacy

- **Admin protetto da password** (default "123" — modificabile in `config.py`)
- **Toggle mascheramento dati** per condivisione schermo
- **Session State** locale per ogni sessione Streamlit
- **GitHub Actions** protetto con `ACTIONS_PUSH_TOKEN`

## 🔄 Aggiornamento Dati

- **Prezzi storici**: aggiornati **ogni ora** da Investgo (primario) + JPMorgan API
- **Aggiornamento manuale**: `python get_historical_data.py`

## 🛠️ Development

### Aggiungere un nuovo fondo
1. Aggiungi riga in `data/funds.csv`
2. Verifica che il ticker funzioni con Investgo
3. Il workflow GitHub Actions scarica automaticamente i prezzi

### Personalizzare i grafici
- Modifica `FUND_COLORS` in `config.py` per i colori
- Modifica layout in `pages/overview_and_charts.py` e `pages/historical_prices.py`
- Configurazione assi/range in `components/chart_helpers.py`

### Script utility
```bash
# Estrai dati mensili per matrice di correlazione
python3 scripts/extract_monthly_data_for_matrix.py data/historical_data.csv
```

## 📝 Note

- **Valuta**: tutti i valori in Euro (€)
- **Timezone**: dati storici in Europe/Rome
- **Dati mancanti**: forward-fill dei prezzi
- **Arrotondamento**: Gross Contributions arrotondati alla decina più vicina

## 📄 License

Progetto privato — usare come riferimento per il proprio portfolio tracker.

---

**Ultimo aggiornamento**: Gennaio 2026
**Versione**: 2.0 (ristrutturazione modulare)
**Status**: Production Ready
