"""
utils/official_data.py — Dati di portafoglio dalle fonti UFFICIALI dei gestori.

Perché
------
Morningstar può essere indietro di un mese rispetto alle schede ufficiali
(es. a fine settembre: Morningstar al 31 luglio, schede JPM al 31 agosto).
Questo modulo legge i dati che alimentano le schede prodotto dei gestori:

    J.P. Morgan AM  -> API product-data (stessa fonte delle schede PDF)
    BlackRock       -> pagina prodotto (tabelle embedded nell'HTML)
    Fidelity, UBS   -> NON disponibili: i siti rifiutano gli IP server
                       (HTTP 403, Akamai). Si mostra solo il link ufficiale.

Cosa danno (e cosa no)
----------------------
Solo le PRIME 10 partecipazioni e i breakdown (settori, aree) con la
tassonomia del gestore, che non coincide con gli 11 settori Morningstar
(es. JPM US: "Semiconduttori e hardware", "Media"). Per questo i dati
ufficiali NON vengono aggregati a livello di portafoglio né mescolati alla
X-Ray Morningstar: si mostrano fondo per fondo.

Output uniforme per fondo (dict):
    provider, as_of (YYYY-MM-DD | None), url,
    holdings:  DataFrame [Name, Sector, Weight %]      (top 10)
    sectors:   DataFrame [Name, Fund %, Benchmark %, (Long %, Short %)]
    regions:   DataFrame [Name, Fund %, Benchmark %] | None
    long_short: bool   (True se il fondo ha posizioni corte, es. JPM US)
"""

from __future__ import annotations

import html as _html
import json
import re
from urllib.parse import urlparse

import pandas as pd
import requests

_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"),
    "Accept-Language": "it-IT,it;q=0.9,en;q=0.8",
}


class OfficialUnavailable(RuntimeError):
    """La fonte ufficiale non è leggibile da server (es. 403 Akamai)."""


def provider_for(url: str | None) -> str | None:
    host = urlparse(url or "").netloc.lower()
    if "jpmorgan.com" in host:
        return "J.P. Morgan AM"
    if "blackrock.com" in host:
        return "BlackRock"
    if "fidelity" in host:
        return "Fidelity"
    if "ubs.com" in host:
        return "UBS"
    return None


def fetch_official_portfolio(isin: str, url: str | None, timeout: int = 30) -> dict:
    """Dispatch per gestore. Raises OfficialUnavailable / RuntimeError."""
    prov = provider_for(url)
    if prov == "J.P. Morgan AM":
        out = _fetch_jpm(isin, timeout)
    elif prov == "BlackRock":
        out = _fetch_blackrock(url, timeout)
    elif prov in ("Fidelity", "UBS"):
        raise OfficialUnavailable(
            f"{prov}'s website blocks automated access from servers (HTTP 403)")
    else:
        raise OfficialUnavailable("No supported official source for this fund")
    out["provider"] = prov
    out["url"] = url
    return out


# -----------------------------------------------------------------------------
# J.P. Morgan AM
# -----------------------------------------------------------------------------

_JPM_URL = "https://am.jpmorgan.com/FundsMarketingHandler/product-data"


def _jpm_block_rows(block: dict | None, exposure: bool) -> pd.DataFrame | None:
    """Righe di un blocco breakdown JPM in DataFrame uniforme.

    Blocchi "*Exposure" (fondi long/short, flag BENCHMARK):
        value=Long, secondary=Short, tertiary=Net, quarternary=Benchmark
    Blocchi "*Breakdown":
        value=Fondo, secondary=Benchmark, tertiary=differenza
    """
    if not block or not block.get("data"):
        return None
    rows = []
    for d in sorted(block["data"], key=lambda x: x.get("sortNumber") or 0):
        if exposure:
            rows.append({"Name": d.get("name"), "Fund %": d.get("tertiaryValue"),
                         "Benchmark %": d.get("quarternaryValue"),
                         "Long %": d.get("value"), "Short %": d.get("secondaryValue")})
        else:
            rows.append({"Name": d.get("name"), "Fund %": d.get("value"),
                         "Benchmark %": d.get("secondaryValue")})
    return _clean(pd.DataFrame(rows))


_TOTAL_NAMES = {"totale", "total", "totale complessivo"}


def _clean(df: pd.DataFrame | None) -> pd.DataFrame | None:
    """Rimuove righe di totale e righe vuote (fondo e benchmark entrambi 0/None)."""
    if df is None or df.empty:
        return None
    df = df[~df["Name"].fillna("").str.strip().str.lower().isin(_TOTAL_NAMES)]
    num = df[["Fund %", "Benchmark %"]].apply(pd.to_numeric, errors="coerce").fillna(0)
    df = df[(num.abs() > 0).any(axis=1)]
    return df.reset_index(drop=True) if not df.empty else None


def parse_jpm(payload: dict) -> dict:
    fd = payload.get("fundData") or {}
    hold_block = fd.get("emeaFundHoldings") or {}
    holdings = pd.DataFrame([
        {"Name": h.get("securityDescription"), "Sector": h.get("sector"),
         "Weight %": h.get("marketValuePercent")}
        for h in sorted(hold_block.get("data") or [], key=lambda x: x.get("sortNumber") or 0)
    ])

    long_short = bool((fd.get("emeaSectorExposure") or {}).get("data"))
    if long_short:
        sec_block, sectors = fd["emeaSectorExposure"], _jpm_block_rows(fd["emeaSectorExposure"], True)
    else:
        sec_block = fd.get("emeaSectorBreakdown") or {}
        sectors = _jpm_block_rows(sec_block, False)

    if (fd.get("emeaRegionalExposure") or {}).get("data"):
        regions = _jpm_block_rows(fd["emeaRegionalExposure"], True)
    else:
        regions = _jpm_block_rows(fd.get("emeaRegionalBreakdown"), False)

    dates = [b.get("effectiveDate") for b in (hold_block, sec_block) if b and b.get("effectiveDate")]
    return {"as_of": max(dates)[:10] if dates else None, "holdings": holdings,
            "sectors": sectors, "regions": regions, "long_short": long_short}


def _fetch_jpm(isin: str, timeout: int) -> dict:
    params = {"cusip": isin, "country": "it", "role": "adv", "language": "it",
              "userLoggedIn": "false", "version": "8.34.0_1"}
    last = None
    for _ in range(2):
        try:
            r = requests.get(_JPM_URL, params=params, headers=_HEADERS, timeout=timeout)
            if r.status_code == 200:
                return parse_jpm(r.json())
            last = f"HTTP {r.status_code}"
        except (requests.RequestException, ValueError) as e:
            last = f"{type(e).__name__}"
    raise RuntimeError(f"J.P. Morgan product-data: {last}")


# -----------------------------------------------------------------------------
# BlackRock
# -----------------------------------------------------------------------------

def _it_float(s) -> float | None:
    try:
        return float(str(s).strip().replace(".", "").replace(",", "."))
    except (TypeError, ValueError):
        return None


def _date_after(text: str, pos: int, span: int = 4000) -> str | None:
    m = re.search(r"al\s+(\d{2})/(\d{2})/(\d{4})", text[pos:pos + span])
    return f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else None


def _br_table(text: str, var: str) -> tuple[pd.DataFrame | None, str | None]:
    m = re.search(var + r"\s*=\s*(\[.*?\]);", text, re.S)
    if not m:
        return None, None
    data = json.loads(m.group(1))
    df = pd.DataFrame([{"Name": d.get("name"), "Fund %": _it_float(d.get("value")),
                        "Benchmark %": _it_float(d.get("benchmark"))} for d in data])
    return _clean(df), _date_after(text, m.end())


def parse_blackrock(text: str) -> dict:
    # Prime 10 posizioni: due tabelle affiancate (odd/even) nel tab "ten-largest"
    i = text.find('id="tenLargestTab"')
    seg = text[i:i + 20000] if i >= 0 else ""
    names = re.findall(r'holdings\.ten-largest\.name">\s*(.*?)\s*</td>', seg, re.S)
    weights = re.findall(r'holdings\.ten-largest\.fundPercentage">\s*(.*?)\s*</td>', seg, re.S)
    holdings = pd.DataFrame([
        {"Name": _html.unescape(n).strip(), "Sector": None, "Weight %": _it_float(w)}
        for n, w in zip(names, weights)
    ])
    if not holdings.empty:
        holdings = holdings.sort_values("Weight %", ascending=False).reset_index(drop=True)
    hold_date = _date_after(seg, 0, 600) if seg else None

    sectors, sec_date = _br_table(text, "tabsSectorDataTable")
    regions, _ = _br_table(text, "subTabsCountriesDataTable")
    dates = [d for d in (hold_date, sec_date) if d]
    if holdings.empty and sectors is None:
        raise RuntimeError("BlackRock page layout not recognised (no holdings / sectors found)")
    return {"as_of": max(dates) if dates else None, "holdings": holdings,
            "sectors": sectors, "regions": regions, "long_short": False}


def _fetch_blackrock(url: str, timeout: int) -> dict:
    r = requests.get(url, headers=_HEADERS, timeout=timeout)
    if r.status_code == 403:
        raise OfficialUnavailable("BlackRock's website blocked the request (HTTP 403)")
    r.raise_for_status()
    return parse_blackrock(r.text)
