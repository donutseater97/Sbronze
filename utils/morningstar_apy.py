"""
utils/morningstar_api.py — Client per l'API pubblica Morningstar security_details.

Scarica e interpreta i dati analitici per singolo fondo (asset allocation,
settori azionari, style box, esposizione valutaria, partecipazioni) e li
aggrega a livello di portafoglio pesando per il controvalore in euro.

È lo stesso endpoint pubblico (token widget morningstar.it) usato come
fallback NAV in get_historical_data.py: nessuna licenza o autenticazione.
Nota: è una ricostruzione "X-Ray fai da te" — per alcuni fondi le
partecipazioni pubblicate sono solo le prime 10, quindi il look-through
completo può differire da strumenti licenziati (es. Morningstar DWS X-Ray).

Modulo puro (nessuna dipendenza da Streamlit): il caching è gestito
dalla pagina chiamante.
"""

import requests
import pandas as pd
import xml.etree.ElementTree as ET

# -----------------------------------------------------------------------------
# Costanti API e mapping dei codici Morningstar
# -----------------------------------------------------------------------------

_BASE_URL = (
    "https://tools.morningstar.it/api/rest.svc/security_details/jbyiq3rhyf"
    "?id={msid}&idtype=msid&responseViewFormat=json&viewid=snapshot"
    "&currencyId=EUR&languageId=it-IT"
)
_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

# GlobalStockSectorBreakdown → nomi settore (schema Morningstar a 11 settori)
SECTOR_NAMES = {
    "101": "Materiali di base",
    "102": "Consumi Ciclici",
    "103": "Servizi Finanziari",
    "104": "Immobiliari",
    "205": "Consumi Difensivi",
    "206": "Salute",
    "207": "Utilità",
    "308": "Servizi Comunicazioni",
    "309": "Energia",
    "310": "Industria",
    "311": "Tecnologia",
}

# AssetAllocation (Type="1", _SalePosition="N") → macro classi
# Mapping verificato empiricamente: 1=Azioni, 3=Obbligazioni, 6=Convertibili,
# 7=Liquidità, 99=Non classificato; il resto confluisce in "Altro".
ASSET_CLASS_MAP = {
    "1": "Azioni",
    "3": "Obbligazioni",
    "6": "Obbligazioni",   # convertibili raggruppate con i bond
    "7": "Liquidità",
    "99": "Non Classificato",
}
ASSET_CLASS_ORDER = ["Azioni", "Obbligazioni", "Liquidità", "Altro", "Non Classificato"]

# Celle style box: 1..9 = riga per riga (Large→Small × Value→Growth)
STYLEBOX_ROWS = ["Large", "Mid", "Small"]
STYLEBOX_COLS = ["Value", "Blend", "Growth"]
BOND_STYLEBOX_ROWS = ["High", "Med", "Low"]          # qualità creditizia
BOND_STYLEBOX_COLS = ["Ltd", "Mod", "Ext"]           # sensibilità ai tassi


# -----------------------------------------------------------------------------
# Fetch e parsing per singolo fondo
# -----------------------------------------------------------------------------

def fetch_security_details_xml(msid: str, timeout: int = 30) -> str:
    """Scarica l'XML security_details per un Morningstar ID (es. 0P00015OFP)."""
    resp = requests.get(_BASE_URL.format(msid=msid), headers=_HEADERS, timeout=timeout)
    resp.raise_for_status()
    return resp.text


def parse_fund_analytics(xml_text: str) -> dict:
    """Estrae i blocchi analitici di un fondo dall'XML security_details.

    Returns:
        dict con chiavi: asset_allocation, sectors, stylebox, bond_stylebox,
        currency, holdings (DataFrame), n_holdings_disclosed.
        I valori percentuali sono riferiti al singolo fondo (somma ~100).
    """
    root = ET.fromstring(xml_text)
    out: dict = {}

    # --- Asset allocation (posizione netta) ---
    alloc: dict[str, float] = {}
    for aa in root.iter("AssetAllocation"):
        if aa.get("Type") == "1" and aa.get("_SalePosition") == "N":
            for b in aa:
                label = ASSET_CLASS_MAP.get(b.get("Type"), "Altro")
                alloc[label] = alloc.get(label, 0.0) + float(b.text)
            break
    out["asset_allocation"] = alloc

    # --- Settori azionari (posizione netta) ---
    sec = root.find(".//GlobalStockSectorBreakdown[@_SalePosition='N']")
    out["sectors"] = (
        {SECTOR_NAMES.get(b.get("Type"), b.get("Type")): float(b.text) for b in sec}
        if sec is not None else {}
    )

    # --- Style box azionario (9 celle, posizione netta) ---
    sb = root.find(".//StyleBoxBreakdown[@_SalePosition='N']")
    out["stylebox"] = (
        {int(b.get("Type")): float(b.text) for b in sb} if sb is not None else {}
    )

    # --- Style box obbligazionario (cella singola da BondStatistics) ---
    bond_cell = root.find(".//BondStatistics/StyleBox")
    out["bond_stylebox"] = int(bond_cell.text) if bond_cell is not None and bond_cell.text else None

    # --- Esposizione valutaria (posizione netta, Type B = per valuta) ---
    ccy: dict[str, float] = {}
    for ce in root.iter("RiskCurrencyExposure"):
        if ce.get("_SalePosition") == "N" and ce.get("Type") == "B":
            ccy = {v.get("CurrencyId"): float(v.text) for v in ce}
            break
    out["currency"] = ccy

    # --- Partecipazioni pubblicate ---
    rows = []
    for hd in root.findall(".//Holding/HoldingDetail"):
        def _t(tag):
            el = hd.find(tag)
            return el.text if el is not None else None
        w = _t("Weighting")
        if w is None:
            continue
        rows.append({
            "SecurityName": _t("SecurityName"),
            "ISIN": _t("ISIN"),
            "Country": _t("Country"),
            "Currency": _t("LocalCurrencyCode"),
            "Weighting": float(w),
        })
    holdings = pd.DataFrame(rows)
    out["holdings"] = holdings
    out["n_holdings_disclosed"] = len(holdings)

    return out


# -----------------------------------------------------------------------------
# Aggregazione a livello di portafoglio
# -----------------------------------------------------------------------------

def _weighted_merge(per_fund: dict[str, dict], weights: dict[str, float], key: str) -> dict:
    """Somma pesata di dizionari {label: pct} tra i fondi (pesi normalizzati)."""
    total = sum(weights.values())
    agg: dict[str, float] = {}
    if total <= 0:
        return agg
    for fund, data in per_fund.items():
        w = weights.get(fund, 0.0) / total
        for label, pct in data.get(key, {}).items():
            agg[label] = agg.get(label, 0.0) + w * pct
    return agg


def aggregate_portfolio(per_fund: dict[str, dict], weights: dict[str, float]) -> dict:
    """Aggrega gli analytics dei singoli fondi pesando per controvalore in euro.

    Args:
        per_fund: {fund_name: output di parse_fund_analytics}
        weights:  {fund_name: valore corrente in EUR}

    Returns:
        dict con asset_allocation, sectors, currency, stylebox (equity),
        bond_stylebox, holdings (DataFrame ordinato per peso in portafoglio).
    """
    total = sum(weights.values())
    agg: dict = {
        "asset_allocation": _weighted_merge(per_fund, weights, "asset_allocation"),
        "currency": _weighted_merge(per_fund, weights, "currency"),
    }

    # Settori: pesati solo sui fondi con dati settoriali (componente azionaria)
    # e rinormalizzati, coerentemente con la convenzione X-Ray di Morningstar.
    sector_weights = {f: w for f, w in weights.items() if per_fund.get(f, {}).get("sectors")}
    agg["sectors"] = _weighted_merge(per_fund, sector_weights, "sectors")

    # Style box azionario: pesato solo sulla componente azionaria di ciascun fondo
    eq_cells = {i: 0.0 for i in range(1, 10)}
    eq_weight_total = 0.0
    bond_cells = {i: 0.0 for i in range(1, 10)}
    bond_weight_total = 0.0
    for fund, data in per_fund.items():
        w = weights.get(fund, 0.0)
        if w <= 0 or total <= 0:
            continue
        sb = data.get("stylebox") or {}
        if sb:
            for cell, pct in sb.items():
                eq_cells[cell] += (w / total) * pct
            eq_weight_total += w / total
        bcell = data.get("bond_stylebox")
        if bcell:
            bond_cells[bcell] += w / total
            bond_weight_total += w / total
    # Rinormalizza a 100 sulla parte coperta
    agg["stylebox"] = (
        {c: v / eq_weight_total for c, v in eq_cells.items()} if eq_weight_total > 0 else {}
    )
    agg["bond_stylebox"] = (
        {c: 100.0 * v / bond_weight_total for c, v in bond_cells.items()}
        if bond_weight_total > 0 else {}
    )

    # Partecipazioni: peso in portafoglio = peso fondo × peso titolo nel fondo
    frames = []
    for fund, data in per_fund.items():
        h = data.get("holdings")
        if h is None or h.empty or total <= 0:
            continue
        h = h.copy()
        h["Fund"] = fund
        h["PortfolioWeight"] = (weights.get(fund, 0.0) / total) * h["Weighting"]
        frames.append(h)
    if frames:
        allh = pd.concat(frames, ignore_index=True)
        # Unisce lo stesso titolo detenuto da più fondi (chiave: ISIN, poi nome)
        allh["_key"] = allh["ISIN"].fillna(allh["SecurityName"])
        merged = (
            allh.groupby("_key", as_index=False)
            .agg(
                SecurityName=("SecurityName", "first"),
                ISIN=("ISIN", "first"),
                Country=("Country", "first"),
                Currency=("Currency", "first"),
                PortfolioWeight=("PortfolioWeight", "sum"),
                Funds=("Fund", lambda s: ", ".join(sorted(set(s)))),
            )
            .sort_values("PortfolioWeight", ascending=False)
            .reset_index(drop=True)
        )
        agg["holdings"] = merged
    else:
        agg["holdings"] = pd.DataFrame()

    return agg
