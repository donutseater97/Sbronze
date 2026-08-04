"""
utils/nav_sources.py — Sorgenti dati per NAV storici e analytics dei fondi.

Espone funzioni di fetch riutilizzabili sia da get_historical_data.py
(aggiornamento CSV via GitHub Actions) sia dalla pagina Streamlit
Morningstar API data. Ogni funzione è indipendente e solleva eccezione
in caso di errore, così il chiamante può gestire la cascata di fallback.

Sorgenti, in ordine di preferenza per i NAV:
  1. investgo          (scraping investing.com — spesso bloccato da IP datacenter)
  2. Morningstar       (endpoint pubblico lt.morningstar.com, multi-token)
  3. API ufficiali     (JPMorgan / Fidelity / BlackRock / UBS a seconda del fondo)

NOTA STORICA sull'host Morningstar: fino a metà 2026 l'host regionale
tools.morningstar.<paese> serviva l'API REST. Ora quegli host fanno
redirect 301/202 verso il nuovo sito global.morningstar.com e non
rispondono più. L'host live che serve ancora l'API REST classica è
lt.morningstar.com ("Library Tools"), usato dai widget morningstar.
"""

import re
import time
from io import BytesIO
from datetime import datetime
from urllib.parse import urljoin

import requests
import pandas as pd


_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
_HEADERS = {"User-Agent": _UA, "Accept-Language": "it-IT,it;q=0.9,en;q=0.8"}


# =============================================================================
# MORNINGSTAR — host + token pubblici
# =============================================================================
#
# Host che attualmente serve l'API REST classica (timeseries_price /
# security_details). Gli host regionali storici sono elencati come
# fallback nel caso Morningstar ne riattivi qualcuno.
MORNINGSTAR_HOSTS = [
    "lt.morningstar.com",       # live, confermato funzionante (ago 2026)
    "tools.morningstar.it",     # storici — ora 301/202, tenuti per resilienza
    "tools.morningstar.dk",
    "tools.morningstar.co.uk",
]

# Token "universal client" citati pubblicamente (Portfolio Performance,
# MoneyManagerEx, forum vari). Non sono chiavi segrete: sono ID del client
# widget che Morningstar espone nelle pagine pubbliche. Non c'è garanzia di
# permanenza, quindi il codice li prova a rotazione finché uno risponde.
MORNINGSTAR_TOKENS = [
    "jbyiq3rhyf",   # widget morningstar.it — confermato attivo
    "nen6ere626",   # tools.morningstar.dk (Portfolio Performance) — confermato attivo
    "wj5w9v50wg",
    "e6e626525a",
    "5t3md0hkzy",
]


def _morningstar_get(path_and_query: str, timeout: int = 25) -> requests.Response:
    """GET su Morningstar provando host×token finché uno risponde 200 con corpo.

    Args:
        path_and_query: parte dopo il token, es.
            "/timeseries_price/{TOKEN}?id=...": passare "{TOKEN}" come
            segnaposto letterale, verrà sostituito con ciascun token.
    Returns:
        requests.Response valida (status 200, corpo non vuoto).
    Raises:
        RuntimeError se nessuna combinazione host/token funziona.
    """
    last_err = None
    for host in MORNINGSTAR_HOSTS:
        for token in MORNINGSTAR_TOKENS:
            url = f"https://{host}" + path_and_query.replace("{TOKEN}", token)
            try:
                r = requests.get(url, headers=_HEADERS, timeout=timeout, allow_redirects=False)
            except Exception as e:  # rete/timeout: prova la combinazione successiva
                last_err = f"{host}/{token}: {type(e).__name__}"
                continue
            # Redirect (301/302) o "accepted" vuoto (202) => host non più valido
            if r.status_code in (301, 302, 202) or not r.content:
                last_err = f"{host}/{token}: status {r.status_code}, {len(r.content)} bytes"
                continue
            if r.status_code == 200 and ("WebServiceException" in r.text[:200]):
                # token rifiutato per questo id — prova il prossimo token
                last_err = f"{host}/{token}: WebServiceException"
                continue
            if r.status_code == 200:
                return r
            last_err = f"{host}/{token}: status {r.status_code}"
    raise RuntimeError(f"Nessun host/token Morningstar valido ({last_err})")


def fetch_morningstar_nav(msid: str, fund_name: str, start: str = "1990-01-01") -> pd.DataFrame:
    """Serie storica NAV giornaliera da Morningstar per un Morningstar ID.

    Args:
        msid: Morningstar ID (es. "0P00015OFP"), dalla colonna Ticker di funds.csv.
    Returns:
        DataFrame ["Date", fund_name], tz-naive, arrotondato a 2 decimali.
    """
    path = (
        "/api/rest.svc/timeseries_price/{TOKEN}"
        f"?id={msid}]2]0]FOITA$$ALL&currencyId=EUR&idtype=Morningstar"
        f"&frequency=daily&startDate={start}&outputType=JSON"
    )
    r = _morningstar_get(path)
    detail = r.json()["TimeSeries"]["Security"][0]["HistoryDetail"]
    hist = pd.DataFrame(detail)[["EndDate", "Value"]]
    hist.columns = ["Date", fund_name]
    hist["Date"] = pd.to_datetime(hist["Date"])
    hist[fund_name] = pd.to_numeric(hist[fund_name], errors="coerce").round(2)
    return hist.dropna()


def fetch_morningstar_details_xml(msid: str, timeout: int = 30) -> str:
    """XML security_details (analytics X-Ray) per un Morningstar ID."""
    path = (
        "/api/rest.svc/security_details/{TOKEN}"
        f"?id={msid}&idtype=msid&responseViewFormat=json&viewid=snapshot"
        "&currencyId=EUR&languageId=it-IT"
    )
    return _morningstar_get(path, timeout=timeout).text


# =============================================================================
# INVESTGO (investing.com)
# =============================================================================

def fetch_investgo_nav(ticker: str, fund_name: str,
                       start_ddmmyyyy: str = "01011990",
                       end_ddmmyyyy: str | None = None) -> pd.DataFrame:
    """Serie NAV via la libreria investgo (scraping investing.com)."""
    from investgo import get_pair_id, get_historical_prices  # import locale

    if end_ddmmyyyy is None:
        end_ddmmyyyy = datetime.now().strftime("%d%m%Y")
    pair_id = get_pair_id([ticker])[0]
    hist_raw = get_historical_prices(pair_id, start_ddmmyyyy, end_ddmmyyyy)
    hist = hist_raw.reset_index().rename(columns={"date": "Date", "price": fund_name})
    hist = hist[["Date", fund_name]]
    dt = pd.to_datetime(hist["Date"], errors="coerce")
    hist["Date"] = dt.dt.tz_localize("Europe/Rome").dt.tz_localize(None)
    hist[fund_name] = pd.to_numeric(hist[fund_name], errors="coerce").round(2)
    return hist.dropna()


# =============================================================================
# API UFFICIALI DEI FONDI (ultima risorsa)
# =============================================================================

def fetch_jpmorgan_nav(isin: str, fund_name: str) -> pd.DataFrame:
    """NAV storico dall'handler JPMorgan AM (funziona da IP datacenter)."""
    params = {
        "type": "historicalNav", "cusip": isin, "country": "it", "role": "adv",
        "locale": "it-IT", "fromDate": "1990-01-01",
        "toDate": datetime.now().strftime("%Y-%m-%d"),
    }
    headers = {**_HEADERS,
               "Accept": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}
    r = requests.get("https://am.jpmorgan.com/FundsMarketingHandler/excel",
                     params=params, headers=headers, timeout=30)
    r.raise_for_status()
    df_raw = pd.read_excel(BytesIO(r.content))
    df = df_raw.iloc[4:].copy()
    df.columns = ["Date", fund_name]
    df = df.dropna()
    df["Date"] = pd.to_datetime(df["Date"], format="%d.%m.%Y")
    df[fund_name] = pd.to_numeric(df[fund_name], errors="coerce").round(2)
    df["Date"] = df["Date"].dt.tz_localize("Europe/Rome").dt.tz_localize(None)
    return df


def fetch_fidelity_nav(isin: str, fund_name: str) -> pd.DataFrame:
    """NAV storico dall'xls Fidelity Italia (HistoricalNav.xlsx).

    NB: Fidelity è dietro Akamai e rifiuta gli IP datacenter (403). Utile
    solo da IP residenziale / self-hosted runner.
    """
    url = (
        "https://www.fidelity-italia.it/api/ce/fdh/HistoricalNav.xlsx"
        f"?id={isin}&countries=it&country=it&languages=it%2Cen&language=it"
        "&channels=ce.private-investor%2Cce.professional-investor"
        "&channel=ce.professional-investor"
    )
    r = requests.get(url, headers=_HEADERS, timeout=30)
    r.raise_for_status()
    df = pd.read_excel(BytesIO(r.content))
    df = df.iloc[4:].copy()
    df.columns = ["Date", fund_name]
    df = df.dropna()
    df["Date"] = pd.to_datetime(df["Date"], format="%d.%m.%Y", errors="coerce")
    df[fund_name] = pd.to_numeric(df[fund_name], errors="coerce").round(2)
    return df.dropna()


def fetch_blackrock_nav(product_url: str, fund_name: str) -> pd.DataFrame:
    """NAV storico dal grafico BlackRock (array navData nella pagina ajax).

    product_url: URL prodotto BlackRock, es.
      https://www.blackrock.com/it/consulenti/products/280749/bsf-...-e2-eur
    """
    # L'ajax del grafico è <product_url>/<id>.ajax?tab=chart&timePeriod=all;
    # BlackRock accetta anche direttamente ?tab=chart sul path prodotto.
    sep = "&" if "?" in product_url else "?"
    ajax = f"{product_url}{sep}tab=chart&timePeriod=all"
    r = requests.get(ajax, headers=_HEADERS, timeout=30)
    r.raise_for_status()
    m = re.search(r"var\s+navData\s*=\s*\[(.*?)\];", r.text, re.S)
    if not m:
        raise RuntimeError(f"navData non trovato nella pagina BlackRock per {fund_name}")
    pts = re.findall(r"\{x:Date\.UTC\((\d+),(\d+),(\d+)\),y:Number\(\(([\d.]+)\)", m.group(1))
    if not pts:
        raise RuntimeError(f"Nessun punto navData per {fund_name}")
    df = pd.DataFrame(pts, columns=["y", "mo", "d", "v"]).astype(
        {"y": int, "mo": int, "d": int, "v": float})
    df["Date"] = pd.to_datetime(dict(year=df.y, month=df.mo + 1, day=df.d))
    df[fund_name] = df["v"].round(2)
    return df[["Date", fund_name]]


def fetch_ubs_nav(isin: str, fund_name: str) -> pd.DataFrame:
    """NAV storico dall'export UBS Fondi (price-services downloadtoexcel).

    NB: come Fidelity, UBS è dietro Akamai e rifiuta gli IP datacenter (403).
    Mantenuto per completezza / uso da IP residenziale.
    """
    today = datetime.now().strftime("%d.%m.%Y")
    url = (
        "https://www.ubs.com/app/HA4/api/api/price-services/358/downloadtoexcel"
        f"?currency=EUR&period=Tutto&ssp=0&toDate={today}&fromDate=01.01.1998"
        "&locale=it_IT_RETL&sgmtKey=ubsf.emwh&profile_variant=&fileName=UBSFunds_Prices_"
    )
    r = requests.get(url, headers=_HEADERS, timeout=30)
    r.raise_for_status()
    df = pd.read_excel(BytesIO(r.content))
    # Individua le colonne data/prezzo in modo robusto
    date_col = next((c for c in df.columns if "data" in str(c).lower() or "date" in str(c).lower()), df.columns[0])
    price_col = next((c for c in df.columns if c != date_col and pd.to_numeric(df[c], errors="coerce").notna().any()), df.columns[-1])
    out = df[[date_col, price_col]].copy()
    out.columns = ["Date", fund_name]
    out["Date"] = pd.to_datetime(out["Date"], dayfirst=True, errors="coerce")
    out[fund_name] = pd.to_numeric(out[fund_name], errors="coerce").round(2)
    return out.dropna()


# Mappa ISIN -> funzione ufficiale + URL/parametro specifico del fondo.
# Usata come ultima risorsa quando investgo e Morningstar falliscono entrambi.
OFFICIAL_FUND_SOURCES = {
    # JPMorgan (già primario per questi due, ma elencato per completezza)
    "LU0281484963": ("JPMorgan AM", lambda name: fetch_jpmorgan_nav("LU0281484963", name)),
    "LU2539333562": ("JPMorgan AM", lambda name: fetch_jpmorgan_nav("LU2539333562", name)),
    # Fidelity
    "LU0261952682": ("Fidelity", lambda name: fetch_fidelity_nav("LU0261952682", name)),
    "LU1213836080": ("Fidelity", lambda name: fetch_fidelity_nav("LU1213836080", name)),
    # BlackRock (EM)
    "LU1321847805": ("BlackRock", lambda name: fetch_blackrock_nav(
        "https://www.blackrock.com/it/consulenti/products/280749/"
        "bsf-blackrock-emerging-markets-equity-strategies-e2-eur", name)),
    # UBS (EU HY)
    "LU0086177085": ("UBS", lambda name: fetch_ubs_nav("LU0086177085", name)),
}