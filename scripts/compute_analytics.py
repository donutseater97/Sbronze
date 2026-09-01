#!/usr/bin/env python3
"""
compute_analytics.py — Pre-calcola le analisi di portafoglio per la pagina
"Portfolio Analysis", così Streamlit legge solo file già pronti e non rallenta.

Viene eseguito dalla GitHub Action DOPO get_historical_data.py, ogni volta che
historical_data.csv (o transaction_history.csv) cambia. Produce, in data/analytics/:

  Serie ordinate (crescenti per data, dalla prima data comune a tutti i fondi):
    nav_daily.csv        NAV giornalieri
    nav_monthly.csv      NAV mensili (ultimo valore del mese)
    returns_daily.csv    rendimenti semplici giornalieri
    returns_monthly.csv  rendimenti semplici mensili

  Matrici (annualizzate):
    cov_daily.csv        covarianza annualizzata dai rendimenti giornalieri (×252)
    cov_monthly.csv      covarianza annualizzata dai rendimenti mensili (×12)
    corr_daily.csv       correlazione dai rendimenti giornalieri
    corr_monthly.csv     correlazione dai rendimenti mensili

  Serie temporali rolling (finestra 90g default, per i grafici evolutivi):
    rolling_vol_fund.csv       volatilità annualizzata per fondo
    rolling_vol_portfolio.csv  volatilità annualizzata del portafoglio (pesi correnti)
    rolling_corr_avg.csv       correlazione media di coppia del portafoglio
    rolling_corr_pairs.csv     correlazione per ogni coppia di fondi

  Metriche riassuntive:
    metrics_summary.csv  Sharpe, Sortino, max drawdown, CAGR, vol, ecc. per fondo
                         e per il portafoglio, con i parametri usati.

Convenzioni: rendimenti SEMPLICI (pct_change); annualizzazione √252 / √12 per la
volatilità, ×252 / ×12 per le covarianze; forward-fill sulle date mancanti dentro
il range comune. Nessun calcolo avviene a runtime in Streamlit.
"""

import os
import sys
import numpy as np
import pandas as pd

_ROOT = os.path.dirname(os.path.abspath(__file__))
if os.path.basename(_ROOT) == "scripts":
    _ROOT = os.path.dirname(_ROOT)

DATA_DIR = os.path.join(_ROOT, "data")
OUT_DIR = os.path.join(DATA_DIR, "analytics")

TRADING_DAYS = 252
MONTHS = 12
ROLLING_WINDOW_DAYS = 90       # finestra rolling per volatilità/correlazione
DEFAULT_RISK_FREE = 0.0        # tasso risk-free annuo di default (per Sharpe/Sortino)


# -----------------------------------------------------------------------------
# Serie di base: NAV e rendimenti, daily e monthly, dal primo giorno comune
# -----------------------------------------------------------------------------

def _load_prices():
    """Carica historical_data.csv, ordina crescente, ritaglia dal primo giorno
    comune a TUTTI i fondi e forward-filla i buchi interni."""
    df = pd.read_csv(os.path.join(DATA_DIR, "historical_data.csv"),
                     parse_dates=["Date"])
    df = df.sort_values("Date").reset_index(drop=True)
    funds = [c for c in df.columns if c != "Date"]

    df = df.set_index("Date")[funds]
    # Prima data in cui OGNI fondo ha un valore = max delle prime date valide.
    first_valid = max(df[c].first_valid_index() for c in funds)
    df = df.loc[first_valid:]
    # Forward-fill dei buchi interni (festività disallineate ecc.).
    df = df.ffill()
    # Elimina eventuali colonne ancora interamente NaN.
    df = df.dropna(axis=1, how="all")
    return df, [c for c in df.columns]


def _monthly_prices(daily: pd.DataFrame) -> pd.DataFrame:
    """Ultimo NAV disponibile di ogni mese."""
    return daily.resample("ME").last()


def _returns(prices: pd.DataFrame) -> pd.DataFrame:
    """Rendimenti semplici, prima riga (NaN) rimossa."""
    return prices.pct_change().dropna(how="all")


# -----------------------------------------------------------------------------
# Matrici covarianza / correlazione annualizzate
# -----------------------------------------------------------------------------

def _cov_corr(returns: pd.DataFrame, ann_factor: int):
    cov = returns.cov() * ann_factor          # covarianza annualizzata
    corr = returns.corr()                     # correlazione (adimensionale)
    return cov, corr


# -----------------------------------------------------------------------------
# Serie rolling: volatilità (per fondo e portafoglio), correlazione
# -----------------------------------------------------------------------------

def _current_weights(funds):
    """Pesi da controvalore attuale (quote × ultimo NAV), coerenti con Overview.
    Fallback a equal-weight se mancano transazioni/prezzi."""
    try:
        tx = pd.read_csv(os.path.join(DATA_DIR, "transaction_history.csv"),
                         parse_dates=["Date"])
        prices = pd.read_csv(os.path.join(DATA_DIR, "historical_data.csv"),
                             parse_dates=["Date"]).sort_values("Date")
        latest = prices.iloc[-1]
        qty = tx.groupby("Fund")["Quantity"].sum()
        w = {}
        for f in funds:
            q = float(qty.get(f, 0.0))
            nav = latest.get(f)
            if q > 0 and pd.notna(nav):
                w[f] = q * float(nav)
        tot = sum(w.values())
        if tot > 0:
            return {f: w.get(f, 0.0) / tot for f in funds}
    except Exception:
        pass
    return {f: 1.0 / len(funds) for f in funds}


def _rolling_analytics(returns_daily: pd.DataFrame, funds, weights,
                       window=ROLLING_WINDOW_DAYS):
    """Volatilità rolling annualizzata per fondo e portafoglio, e correlazione
    rolling (media di coppia + per coppia)."""
    ann = np.sqrt(TRADING_DAYS)

    # Volatilità per fondo
    vol_fund = returns_daily.rolling(window).std() * ann
    vol_fund = vol_fund.dropna(how="all")

    # Rendimento di portafoglio (pesi correnti) e sua volatilità rolling
    w = pd.Series({f: weights.get(f, 0.0) for f in funds})
    port_ret = (returns_daily[funds] * w).sum(axis=1)
    vol_port = port_ret.rolling(window).std() * ann
    vol_port = vol_port.dropna().to_frame("Portfolio")

    # Correlazione rolling per ogni coppia + media
    pairs = [(a, b) for i, a in enumerate(funds) for b in funds[i + 1:]]
    corr_pairs = pd.DataFrame(index=returns_daily.index)
    for a, b in pairs:
        corr_pairs[f"{a}~{b}"] = returns_daily[a].rolling(window).corr(returns_daily[b])
    corr_pairs = corr_pairs.dropna(how="all")
    corr_avg = corr_pairs.mean(axis=1).to_frame("AvgPairwiseCorr")

    return vol_fund, vol_port, corr_avg, corr_pairs


# -----------------------------------------------------------------------------
# Metriche riassuntive per fondo e portafoglio
# -----------------------------------------------------------------------------

def _max_drawdown(prices: pd.Series) -> float:
    """Max drawdown (frazione negativa, es. -0.35) su una serie di prezzi."""
    roll_max = prices.cummax()
    dd = prices / roll_max - 1.0
    return float(dd.min())


def _metrics(daily_prices, returns_daily, funds, weights,
             risk_free=DEFAULT_RISK_FREE):
    """Metriche annualizzate per ogni fondo + portafoglio."""
    ann = np.sqrt(TRADING_DAYS)
    rf_daily = risk_free / TRADING_DAYS
    rows = []

    # Serie di portafoglio
    w = pd.Series({f: weights.get(f, 0.0) for f in funds})
    port_ret = (returns_daily[funds] * w).sum(axis=1)
    port_prices = (1 + port_ret).cumprod()

    def _one(name, ret, prices):
        mean_d = ret.mean()
        std_d = ret.std()
        downside = ret[ret < 0].std()
        cagr = (prices.iloc[-1] / prices.iloc[0]) ** (TRADING_DAYS / len(prices)) - 1 \
            if len(prices) > 1 and prices.iloc[0] > 0 else np.nan
        vol = std_d * ann
        sharpe = ((mean_d - rf_daily) / std_d * ann) if std_d > 0 else np.nan
        sortino = ((mean_d - rf_daily) / downside * ann) if downside and downside > 0 else np.nan
        mdd = _max_drawdown(prices)
        return {
            "Name": name,
            "CAGR": round(cagr, 4) if pd.notna(cagr) else "",
            "AnnVol": round(vol, 4),
            "Sharpe": round(sharpe, 3) if pd.notna(sharpe) else "",
            "Sortino": round(sortino, 3) if pd.notna(sortino) else "",
            "MaxDrawdown": round(mdd, 4),
            "MeanDailyRet": round(mean_d, 6),
        }

    for f in funds:
        rows.append(_one(f, returns_daily[f].dropna(),
                         daily_prices[f].dropna()))
    rows.append(_one("Portfolio", port_ret.dropna(), port_prices.dropna()))

    df = pd.DataFrame(rows)
    df.attrs["risk_free"] = risk_free
    return df


# -----------------------------------------------------------------------------
# Contributo al rischio per fondo (risk contribution)
# -----------------------------------------------------------------------------

def _risk_contribution(cov_daily, funds, weights):
    """Contributo marginale/totale al rischio di portafoglio per ogni fondo."""
    w = np.array([weights.get(f, 0.0) for f in funds])
    Sigma = cov_daily.loc[funds, funds].values
    port_var = float(w @ Sigma @ w)
    if port_var <= 0:
        return pd.DataFrame({"Fund": funds, "RiskContribution": [0.0] * len(funds),
                             "RiskContributionPct": [0.0] * len(funds)})
    mrc = Sigma @ w                      # marginal risk contribution
    rc = w * mrc                         # total risk contribution
    rc_pct = rc / port_var
    return pd.DataFrame({
        "Fund": funds,
        "RiskContribution": np.round(rc, 6),
        "RiskContributionPct": np.round(rc_pct, 4),
    })


# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------

def main():
    os.makedirs(OUT_DIR, exist_ok=True)

    daily_prices, funds = _load_prices()
    if len(funds) < 2:
        print("Meno di 2 fondi con storico comune: analisi saltata.")
        return

    monthly_prices = _monthly_prices(daily_prices)
    returns_daily = _returns(daily_prices)
    returns_monthly = _returns(monthly_prices)

    print(f"Funds: {funds}")
    print(f"Common start: {daily_prices.index[0].date()} | "
          f"daily rows: {len(daily_prices)} | monthly rows: {len(monthly_prices)}")

    # --- Serie di base (ordinate crescenti per data) ---
    daily_prices.to_csv(os.path.join(OUT_DIR, "nav_daily.csv"))
    monthly_prices.to_csv(os.path.join(OUT_DIR, "nav_monthly.csv"))
    returns_daily.to_csv(os.path.join(OUT_DIR, "returns_daily.csv"))
    returns_monthly.to_csv(os.path.join(OUT_DIR, "returns_monthly.csv"))

    # --- Matrici annualizzate ---
    cov_d, corr_d = _cov_corr(returns_daily, TRADING_DAYS)
    cov_m, corr_m = _cov_corr(returns_monthly, MONTHS)
    cov_d.to_csv(os.path.join(OUT_DIR, "cov_daily.csv"))
    cov_m.to_csv(os.path.join(OUT_DIR, "cov_monthly.csv"))
    corr_d.to_csv(os.path.join(OUT_DIR, "corr_daily.csv"))
    corr_m.to_csv(os.path.join(OUT_DIR, "corr_monthly.csv"))

    # --- Pesi correnti + serie rolling ---
    weights = _current_weights(funds)
    # Salva i tre schemi di pesi, così la pagina può farli scegliere all'utente
    # senza ricalcolarli: market value (default), capitale investito, equal.
    try:
        tx = pd.read_csv(os.path.join(DATA_DIR, "transaction_history.csv"))
        invested = tx.assign(inv=tx["Quantity"] * tx["Price (€)"]).groupby("Fund")["inv"].sum()
        w_inv = {f: float(invested.get(f, 0.0)) for f in funds}
        tot_inv = sum(w_inv.values())
        w_inv = {f: (v / tot_inv if tot_inv > 0 else 0.0) for f, v in w_inv.items()}
    except Exception:
        w_inv = {f: 1.0 / len(funds) for f in funds}
    w_eq = {f: 1.0 / len(funds) for f in funds}
    pd.DataFrame({
        "MarketValue": pd.Series(weights),
        "Invested": pd.Series(w_inv),
        "Equal": pd.Series(w_eq),
    }).to_csv(os.path.join(OUT_DIR, "weights.csv"))
    pd.Series(weights, name="Weight").to_csv(os.path.join(OUT_DIR, "weights_current.csv"))

    vol_fund, vol_port, corr_avg, corr_pairs = _rolling_analytics(
        returns_daily, funds, weights)
    vol_fund.to_csv(os.path.join(OUT_DIR, "rolling_vol_fund.csv"))
    vol_port.to_csv(os.path.join(OUT_DIR, "rolling_vol_portfolio.csv"))
    corr_avg.to_csv(os.path.join(OUT_DIR, "rolling_corr_avg.csv"))
    corr_pairs.to_csv(os.path.join(OUT_DIR, "rolling_corr_pairs.csv"))

    # --- Metriche riassuntive + contributo al rischio ---
    metrics = _metrics(daily_prices, returns_daily, funds, weights)
    metrics.to_csv(os.path.join(OUT_DIR, "metrics_summary.csv"), index=False)
    rc = _risk_contribution(cov_d, funds, weights)
    rc.to_csv(os.path.join(OUT_DIR, "risk_contribution.csv"), index=False)

    # --- Metadati (per mostrare freschezza in pagina) ---
    meta = pd.DataFrame([{
        "generated_at": pd.Timestamp.now("UTC").strftime("%Y-%m-%d %H:%M:%S UTC"),
        "common_start": daily_prices.index[0].strftime("%Y-%m-%d"),
        "last_date": daily_prices.index[-1].strftime("%Y-%m-%d"),
        "rolling_window_days": ROLLING_WINDOW_DAYS,
        "trading_days": TRADING_DAYS,
        "risk_free_default": DEFAULT_RISK_FREE,
        "funds": ",".join(funds),
    }])
    meta.to_csv(os.path.join(OUT_DIR, "analytics_meta.csv"), index=False)

    print(f"✓ Analytics written to {OUT_DIR}")


if __name__ == "__main__":
    main()