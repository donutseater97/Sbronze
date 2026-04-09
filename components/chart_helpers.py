"""
components/chart_helpers.py — Funzioni helper per configurazione grafici Plotly.

Contiene configurazioni comuni per layout, assi, range selector e config
di esportazione, evitando duplicazione tra le varie pagine.
"""

import pandas as pd
import plotly.graph_objects as go


DATE_AXIS_RIGHT_PADDING_RATIO = 0.02
DATE_AXIS_RIGHT_PADDING_MIN = pd.Timedelta(days=2)


# ---------------------------------------------------------------------------
# Range selector standard (bottoni 1M, 3M, 6M, YTD, 1Y, 3Y, All)
# ---------------------------------------------------------------------------

RANGE_SELECTOR_BUTTONS = [
    dict(count=1, label="1M", step="month", stepmode="backward"),
    dict(count=3, label="3M", step="month", stepmode="backward"),
    dict(count=6, label="6M", step="month", stepmode="backward"),
    dict(count=1, label="YTD", step="year", stepmode="todate"),
    dict(count=1, label="1Y", step="year", stepmode="backward"),
    dict(count=3, label="3Y", step="year", stepmode="backward"),
    dict(step="all", label="All"),
]

# Range selector ridotto (senza 3Y)
RANGE_SELECTOR_BUTTONS_SHORT = [
    dict(count=1, label="1M", step="month", stepmode="backward"),
    dict(count=3, label="3M", step="month", stepmode="backward"),
    dict(count=6, label="6M", step="month", stepmode="backward"),
    dict(count=1, label="YTD", step="year", stepmode="todate"),
    dict(count=1, label="1Y", step="year", stepmode="backward"),
    dict(step="all", label="All"),
]


# ---------------------------------------------------------------------------
# Configurazione standard export immagine
# ---------------------------------------------------------------------------

def get_plotly_config(filename: str = "chart") -> dict:
    """Restituisce la configurazione standard per st.plotly_chart().

    Include scroll zoom, strumenti di disegno e opzioni di esportazione PNG.

    Args:
        filename: Nome del file per l'export PNG.

    Returns:
        Dizionario config compatibile con plotly_chart().
    """
    return dict(
        scrollZoom=True,
        displaylogo=False,
        doubleClick="reset",
        editable=True,
        edits=dict(
            annotationPosition=True,
            annotationTail=False,
            axisTitleText=False,
            colorbarPosition=False,
            colorbarTitleText=False,
            legendPosition=False,
            legendText=False,
            shapePosition=False,
            titleText=False,
        ),
        modeBarButtonsToAdd=[
            "drawline",
            "eraseshape",
            "zoom2d",
            "pan2d",
            "select2d",
            "lasso2d",
        ],
        toImageButtonOptions=dict(
            format="png",
            filename=filename,
            height=600,
            width=1200,
            scale=2,
        ),
    )


# ---------------------------------------------------------------------------
# Configurazione assi X con range slider e range selector
# ---------------------------------------------------------------------------

def apply_standard_xaxis(fig: go.Figure, buttons: list | None = None) -> None:
    """Applica configurazione standard all'asse X di un grafico.

    Include range slider, range selector buttons e spike lines.
    Quando l'asse X contiene date, applica un piccolo padding a destra
    per evitare che l'ultimo punto/label resti schiacciato sul bordo.

    Args:
        fig:     Figura Plotly da configurare.
        buttons: Lista di bottoni per il range selector (default: RANGE_SELECTOR_BUTTONS).
    """
    if buttons is None:
        buttons = RANGE_SELECTOR_BUTTONS

    xaxis_cfg = dict(
        rangeslider=dict(visible=True, thickness=0.07),
        rangeselector=dict(buttons=buttons),
        showspikes=True,
        spikemode="across",
        spikesnap="cursor",
        spikethickness=1,
        spikecolor="#888888",
    )

    # Calcola range esplicito per assi data, con leggero padding destro
    # per mostrare l'ultimo punto vicino al bordo senza tagliare annotazioni.
    x_values = []
    for trace in fig.data:
        x_data = getattr(trace, "x", None)
        if x_data is None:
            continue
        x_values.extend([x for x in x_data if x is not None])

    if x_values:
        x_dt = pd.to_datetime(pd.Series(x_values), errors="coerce").dropna()
        if len(x_dt) > 0:
            x_min = x_dt.min()
            x_max = x_dt.max()
            if x_max > x_min:
                right_padding = max(
                    (x_max - x_min) * DATE_AXIS_RIGHT_PADDING_RATIO,
                    DATE_AXIS_RIGHT_PADDING_MIN,
                )
            else:
                right_padding = DATE_AXIS_RIGHT_PADDING_MIN

            xaxis_cfg["autorange"] = False
            xaxis_cfg["range"] = [x_min, x_max + right_padding]
            xaxis_cfg["rangeslider"]["range"] = [x_min, x_max]

    fig.update_xaxes(**xaxis_cfg)


def apply_standard_yaxis(fig: go.Figure, title: str = "", fixed: bool = False) -> None:
    """Applica configurazione standard all'asse Y di un grafico.

    Args:
        fig:   Figura Plotly da configurare.
        title: Titolo dell'asse Y.
        fixed: Se True, l'asse Y non è zoomabile.
    """
    fig.update_yaxes(
        title_text=title,
        rangemode="normal",
        fixedrange=fixed,
        showspikes=True,
        spikemode="across",
        automargin=True,
    )


# ---------------------------------------------------------------------------
# Calcolo range Y con padding
# ---------------------------------------------------------------------------

def calculate_y_range_with_padding(
    traces,
    padding_pct: float = 0.01,
) -> tuple[float | None, float | None]:
    """Calcola il range dell'asse Y con un margine percentuale.

    Analizza tutti i trace di una figura e restituisce (y_min, y_max)
    con un padding proporzionale al range dei dati.

    Args:
        traces:      Lista di trace Plotly (fig.data).
        padding_pct: Percentuale di padding (default 1%).

    Returns:
        Tupla (y_min_con_padding, y_max_con_padding), o (None, None) se vuoto.
    """
    all_y = []
    for trace in traces:
        if hasattr(trace, "y") and trace.y is not None:
            all_y.extend([y for y in trace.y if y is not None])

    if not all_y:
        return None, None

    y_min, y_max = min(all_y), max(all_y)
    y_range = y_max - y_min

    # Gestisci caso con tutti valori identici
    if y_range == 0:
        padding = abs(y_min) * padding_pct if y_min != 0 else 1.0
    else:
        padding = y_range * padding_pct

    return y_min - padding, y_max + padding


# ---------------------------------------------------------------------------
# Annotazione prezzo laterale (data label)
# ---------------------------------------------------------------------------

def add_price_annotation(
    fig: go.Figure,
    x,
    y: float,
    text: str,
    color: str = "#999999",
    font_size: int = 13,
) -> None:
    """Aggiunge un'annotazione di prezzo a destra dell'ultimo punto di un trace.

    Args:
        fig:       Figura Plotly.
        x:         Coordinata X (data).
        y:         Coordinata Y (prezzo).
        text:      Testo da mostrare (es. '€123.45').
        color:     Colore del bordo e del testo.
        font_size: Dimensione font.
    """
    fig.add_annotation(
        x=x,
        y=y,
        text=text,
        showarrow=False,
        xanchor="right",
        xshift=-4,
        font=dict(size=font_size, color=color),
        bordercolor=color,
        borderwidth=1.5,
        borderpad=4,
        bgcolor="rgba(255,255,255,0)",
    )
