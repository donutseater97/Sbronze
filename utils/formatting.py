"""
utils/formatting.py — Funzioni di formattazione numeri e valute.

Funzioni pure senza dipendenze da Streamlit, pensate per essere riusate
in tutte le pagine dell'app e facilmente testabili in isolamento.
"""

import pandas as pd


# ---------------------------------------------------------------------------
# Precisione decimale
# ---------------------------------------------------------------------------

def count_decimals(num, max_dp: int = 6) -> int:
    """Conta le cifre decimali significative di un numero.

    Args:
        num:    Valore numerico (o NaN).
        max_dp: Numero massimo di cifre decimali da considerare.

    Returns:
        Numero di cifre decimali effettive (0 se NaN o intero).
    """
    if pd.isna(num):
        return 0
    s = f"{float(num):.{max_dp}f}".rstrip("0").rstrip(".")
    if "." in s:
        return min(len(s.split(".")[-1]), max_dp)
    return 0


def get_fund_qty_decimals(transactions_df: pd.DataFrame, max_dp: int = 3) -> dict[str, int]:
    """Calcola la precisione decimale per le quantità di ciascun fondo.

    Analizza tutte le transazioni raggruppate per fondo e restituisce il
    numero massimo di decimali significativi usati nelle quantità.

    Args:
        transactions_df: DataFrame con colonne "Fund" e "Quantity".
        max_dp:          Numero massimo di decimali (default 3).

    Returns:
        Dizionario {fund_name: n_decimali}.
    """
    try:
        result = (
            transactions_df
            .groupby("Fund")["Quantity"]
            .apply(lambda s: max((count_decimals(v) for v in s if pd.notna(v)), default=0))
            .to_dict()
        )
    except Exception:
        result = {}
    return {f: min(int(d or 0), max_dp) for f, d in result.items()}


# ---------------------------------------------------------------------------
# Formattazione quantità
# ---------------------------------------------------------------------------

def format_qty(val, dp: int = 3) -> str:
    """Formatta una quantità rimuovendo gli zeri finali.

    Args:
        val: Valore numerico della quantità.
        dp:  Decimali massimi (default 3).

    Returns:
        Stringa formattata (es. "4.588", "23", "0.69").
    """
    if pd.isna(val):
        return ""
    rounded = round(float(val), dp)
    if rounded == int(rounded):
        return str(int(rounded))
    return f"{rounded:.{dp}f}".rstrip("0").rstrip(".")


# ---------------------------------------------------------------------------
# Formattazione valute
# ---------------------------------------------------------------------------

def fmt_currency(value: float, symbol: str = "€") -> str:
    """Formatta un valore come valuta (es. '€ 1,234.56').

    Args:
        value:  Valore numerico.
        symbol: Simbolo valuta (default '€').

    Returns:
        Stringa formattata con separatore delle migliaia e 2 decimali.
    """
    if pd.isna(value):
        return f"{symbol} 0.00"
    return f"{symbol} {value:,.2f}"


# ---------------------------------------------------------------------------
# Formattazione delta (variazioni)
# ---------------------------------------------------------------------------

def format_delta_net_inv(val) -> float | None:
    """Arrotonda un delta di investimento netto a 2 decimali.

    Restituisce 0.0 se il valore arrotondato è trascurabile (< 0.005 €).
    """
    if pd.isna(val):
        return None
    rounded = round(val, 2)
    return 0.0 if abs(rounded) < 0.005 else rounded


def format_delta_qty(delta_qty, fund: str, fund_qty_decimals: dict) -> float | None:
    """Arrotonda un delta di quantità secondo la precisione del fondo.

    Args:
        delta_qty:         Valore delta grezzo.
        fund:              Nome del fondo (per lookup precisione).
        fund_qty_decimals: Dizionario {fund: n_decimali}.

    Returns:
        Valore arrotondato o None se NaN.
    """
    if pd.isna(delta_qty):
        return None
    dp = fund_qty_decimals.get(fund, 3)
    rounded = round(delta_qty, dp)
    return 0.0 if abs(rounded) < 10 ** (-dp) else rounded
