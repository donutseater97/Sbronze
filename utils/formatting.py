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


# ---------------------------------------------------------------------------
# Formatter per tabelle ordinabili
# ---------------------------------------------------------------------------
# Le tabelle tengono i valori NUMERICI e delegano il testo mostrato a
# Styler.format(...). st.dataframe ordina così per valore reale (−140.45 <
# −54.12 < 0.50 < 84.76 < 411.90) pur mostrando "€-140.45", "+35.43%", ecc.
# Una cella già convertita in stringa, invece, viene ordinata alfabeticamente
# ("411.90" prima di "84.76"), che era il bug.
#
# Ogni factory restituisce una funzione valore -> stringa. I valori mancanti
# (NaN) non passano dal formatter: si usa na_rep in Styler.format.

def _sign(v: float, signed: bool) -> str:
    if not signed:
        return "-" if v < 0 else ""
    return "+" if v > 0 else "-" if v < 0 else ""


def f_eur(dp: int = 2, signed: bool = False, thousands: bool = True,
          space: bool = False, sign_after_symbol: bool = False):
    """€: "€1,234.56"; signed -> "+€48.55" / "-€31.18".

    sign_after_symbol=True -> "€+48.55" / "€-31.18" (stile P/L storico).
    space=True -> "€ 1,234.56".
    """
    sym = "€ " if space else "€"
    num_fmt = f"{{:{',' if thousands else ''}.{dp}f}}"

    def fmt(v):
        v = float(v)
        s = _sign(v, signed)
        body = num_fmt.format(abs(v))
        return f"{sym}{s}{body}" if sign_after_symbol else f"{s}{sym}{body}"
    return fmt


def f_pct(dp: int = 2, signed: bool = False, scale: float = 1.0):
    """%: "35.43%" / signed "+35.43%". scale=100 per frazioni (0.1345 -> 13.45%)."""
    def fmt(v):
        v = float(v) * scale
        return f"{_sign(v, signed)}{abs(v):.{dp}f}%"
    return fmt


def f_num(dp: int = 2, signed: bool = False, thousands: bool = False):
    """Numero semplice: "1199.76" / signed "+0.01"."""
    num_fmt = f"{{:{',' if thousands else ''}.{dp}f}}"

    def fmt(v):
        v = float(v)
        return f"{_sign(v, signed)}{num_fmt.format(abs(v))}"
    return fmt


def f_qty(dp: int = 3):
    """Quantità senza zeri finali (come format_qty): "4.588", "23.8", "23"."""
    return lambda v: format_qty(v, dp)


def f_date(pattern: str = "%Y-%m-%d"):
    """Date/Timestamp -> stringa (ordinamento cronologico sul valore)."""
    return lambda v: pd.Timestamp(v).strftime(pattern)


def sign_bg(v, alpha: float = 0.12, zero_neutral: bool = True, eps: float = 0.0) -> str:
    """Sfondo verde/rosso in base al segno (stringa CSS, vuota se neutro/NaN)."""
    if v is None or pd.isna(v):
        return ""
    if zero_neutral and abs(v) <= eps:
        return ""
    return (f"background-color: rgba(46,160,67,{alpha});" if v > 0 or (not zero_neutral and v == 0)
            else f"background-color: rgba(248,81,73,{alpha});")


def style_cols(styler, formats: dict, na_rep: str | None = None):
    """Styler.format limitato alle SOLE colonne del dict.

    Attenzione: styler.format({...}) senza subset riporta al formato di default
    tutte le altre colonne, cancellando i format applicati prima. Usare sempre
    questa funzione per i format a dizionario.
    """
    formats = {c: f for c, f in formats.items() if c in styler.data.columns}
    if not formats:
        return styler
    return styler.format(formats, subset=list(formats), na_rep=na_rep)
