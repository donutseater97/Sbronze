"""
components/styling.py — Utilità di stile e conversione colori.

Funzioni condivise per convertire colori esadecimali, applicare sfondi
colorati alle righe delle tabelle e determinare il colore verde/rosso
in base al segno di un valore.
"""


# ---------------------------------------------------------------------------
# Conversione colori esadecimali
# ---------------------------------------------------------------------------

def hex_to_rgba(hex_color: str, alpha: float = 0.15) -> str:
    """Converte un colore esadecimale '#RRGGBB' in stringa 'rgba(r,g,b,a)'.

    Args:
        hex_color: Colore in formato '#RRGGBB' o 'RRGGBB'.
        alpha:     Opacità (0.0 – 1.0).

    Returns:
        Stringa CSS rgba.
    """
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r}, {g}, {b}, {alpha})"


def hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    """Converte un colore esadecimale '#RRGGBB' in tupla (r, g, b).

    Args:
        hex_color: Colore in formato '#RRGGBB' o 'RRGGBB'.

    Returns:
        Tupla (red, green, blue) con valori 0-255.
    """
    h = hex_color.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


# ---------------------------------------------------------------------------
# Stile condizionale per valori positivi / negativi
# ---------------------------------------------------------------------------

# Colori standard per valori positivi (verde) e negativi (rosso)
GREEN_BG = "background-color: rgba(46, 160, 67, 0.15);"
RED_BG   = "background-color: rgba(248, 81, 73, 0.15);"

# Colori per testo nelle tabelle di evoluzione
GREEN_CELL = "background-color: rgba(107, 203, 119, 0.15); color: #2d6a3f;"
RED_CELL   = "background-color: rgba(226, 106, 106, 0.15); color: #8b2e2e;"


def return_color_bg(value: float) -> str:
    """Restituisce lo stile CSS di sfondo verde/rosso in base al segno.

    Args:
        value: Valore numerico da valutare.

    Returns:
        Stringa CSS con background-color, oppure stringa vuota se zero.
    """
    if value > 0:
        return GREEN_BG
    elif value < 0:
        return RED_BG
    return ""


def return_color_cell(value: float) -> str:
    """Come return_color_bg, ma include anche il colore del testo.

    Usato nelle tabelle di evoluzione (Portfolio P/L Evolution, ecc.).
    """
    if value > 0:
        return GREEN_CELL
    elif value < 0:
        return RED_CELL
    return ""


# ---------------------------------------------------------------------------
# Stile riga per tabelle con colonna Fund
# ---------------------------------------------------------------------------

def style_fund_cell(fund_name: str, fund_colors: dict) -> str:
    """Restituisce lo stile CSS per una cella della colonna Fund.

    Lo sfondo usa il colore del fondo con alpha leggero (0.15).

    Args:
        fund_name:   Nome del fondo.
        fund_colors: Dizionario {fund_name: '#RRGGBB'}.

    Returns:
        Stringa CSS 'background-color: rgba(...)'.
    """
    hex_color = fund_colors.get(fund_name, "#000000")
    rgba = hex_to_rgba(hex_color, alpha=0.15)
    return f"background-color: {rgba}"


# ---------------------------------------------------------------------------
# Tabelle "giornaliere" (Historical Data, Market Value Evolution)
# ---------------------------------------------------------------------------
# Palette condivisa: stessa resa visiva in tutte le tabelle con una riga per
# giorno. Sfondo cella tenue (alpha 0.12) per la variazione giornaliera,
# molto più forte (0.35) + bordo interno nei giorni di transazione.

DAILY_ALPHA = 0.12
DAILY_TX_ALPHA = 0.35
DAILY_TX_NEUTRAL = "background-color: rgba(230,237,243,0.14);"
DAILY_TX_BORDER = "box-shadow: inset 0 0 0 2px rgba(230,237,243,0.55);"


def daily_change_style(direction: int, is_tx: bool = False) -> str:
    """Stile CSS di una cella in una tabella giornaliera.

    Args:
        direction: +1 salita, -1 discesa, 0 nessuna variazione / dato mancante.
        is_tx:     True se nel giorno c'è una transazione sul fondo.

    Returns:
        Stringa CSS (può essere vuota).
    """
    alpha = DAILY_TX_ALPHA if is_tx else DAILY_ALPHA
    if direction > 0:
        base = f"background-color: rgba(46,160,67,{alpha});"
    elif direction < 0:
        base = f"background-color: rgba(248,81,73,{alpha});"
    elif is_tx:
        base = DAILY_TX_NEUTRAL
    else:
        base = ""
    if is_tx:
        base += DAILY_TX_BORDER
    return base


def fund_header_css(funds: list[str], fund_colors: dict) -> str:
    """CSS per header colorati (prima colonna neutra, poi un colore per fondo)."""
    css = "<style>\ntable th { font-weight: 600 !important; }\n"
    css += "table th:first-child { background-color: rgba(100, 100, 100, 0.3) !important; }\n"
    for idx, fund in enumerate(funds, start=1):
        r, g, b = hex_to_rgb(fund_colors.get(fund, "#999999"))
        css += f"table th:nth-child({idx+1}) {{ background-color: rgba({r}, {g}, {b}, 0.3) !important; }}\n"
    css += "</style>\n"
    return css


DAILY_WINDOW_OPTIONS = ["1M", "3M", "6M", "1Y", "Max"]
DAILY_WINDOW_DAYS = {"1M": 30, "3M": 91, "6M": 182, "1Y": 365, "Max": None}
