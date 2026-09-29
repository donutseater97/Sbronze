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

# Il fetch dell'XML security_details è delegato a utils.nav_sources, che
# gestisce l'host Morningstar live (lt.morningstar.com) e la rotazione dei
# token pubblici. Vedi la nota storica in nav_sources.py sul motivo per cui
# tools.morningstar.<paese> non funziona più.

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
    """Scarica l'XML security_details per un Morningstar ID.

    Delega a utils.nav_sources.fetch_morningstar_details_xml, che prova host
    e token pubblici in cascata sull'endpoint Morningstar live.
    """
    from utils.nav_sources import fetch_morningstar_details_xml
    return fetch_morningstar_details_xml(msid, timeout=timeout)


def _own_portfolio(root: ET.Element) -> ET.Element:
    """Nodo Portfolio DEL FONDO (PortfolioList/Portfolio).

    L'XML contiene anche Category/Portfolio e Index/Portfolio (medie di
    categoria e benchmark), con gli stessi tag. Cercare con ".//Tag" su
    tutto il documento prende il primo match, che per i blocchi assenti nel
    fondo è quello della CATEGORIA: es. l'esposizione valutaria di EM ed EU
    arrivava dalla media di categoria. Tutto il parsing va quindi limitato
    al portafoglio del fondo.
    """
    own = root.find("PortfolioList/Portfolio")
    return own if own is not None else root


# Copertura minima (somma pesi delle partecipazioni pubblicate) per stimare
# l'esposizione valutaria dalle partecipazioni quando il fondo non la pubblica.
_CCY_FROM_HOLDINGS_MIN_COVERAGE = 80.0


def parse_fund_analytics(xml_text: str) -> dict:
    """Estrae i blocchi analitici di un fondo dall'XML security_details.

    Returns:
        dict con chiavi: asset_allocation, sectors, stylebox, bond_stylebox,
        currency, currency_source, holdings (DataFrame), n_holdings_disclosed,
        sec_id, freshness.
        I valori percentuali sono riferiti al singolo fondo (somma ~100).
    """
    root = ET.fromstring(xml_text)
    own = _own_portfolio(root)
    out: dict = {"sec_id": root.get("_Id")}

    # --- Asset allocation (posizione netta) ---
    alloc: dict[str, float] = {}
    for aa in own.iter("AssetAllocation"):
        if aa.get("Type") == "1" and aa.get("_SalePosition") == "N":
            for b in aa:
                label = ASSET_CLASS_MAP.get(b.get("Type"), "Altro")
                alloc[label] = alloc.get(label, 0.0) + float(b.text)
            break
    out["asset_allocation"] = alloc

    # --- Settori azionari (posizione netta) ---
    sec = own.find(".//GlobalStockSectorBreakdown[@_SalePosition='N']")
    out["sectors"] = (
        {SECTOR_NAMES.get(b.get("Type"), b.get("Type")): float(b.text) for b in sec}
        if sec is not None else {}
    )

    # --- Style box azionario (9 celle, posizione netta) ---
    sb = own.find(".//StyleBoxBreakdown[@_SalePosition='N']")
    out["stylebox"] = (
        {int(b.get("Type")): float(b.text) for b in sb} if sb is not None else {}
    )

    # --- Style box obbligazionario (cella singola da BondStatistics) ---
    bond_cell = own.find(".//BondStatistics/StyleBox")
    out["bond_stylebox"] = int(bond_cell.text) if bond_cell is not None and bond_cell.text else None

    # --- Partecipazioni pubblicate ---
    rows = []
    for hd in own.findall(".//Holding/HoldingDetail"):
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

    # --- Esposizione valutaria (posizione netta, Type B = per valuta) ---
    # 1) dal fondo; 2) se assente, dalle partecipazioni pubblicate quando
    #    coprono quasi tutto il fondo; 3) altrimenti media di categoria,
    #    dichiarata come proxy.
    def _ccy_block(node):
        for ce in node.iter("RiskCurrencyExposure"):
            if ce.get("_SalePosition") == "N" and ce.get("Type") == "B":
                return {v.get("CurrencyId"): float(v.text) for v in ce}
        return {}

    ccy = _ccy_block(own)
    ccy_source = "fund"
    if not ccy:
        coverage = float(holdings["Weighting"].sum()) if not holdings.empty else 0.0
        if coverage >= _CCY_FROM_HOLDINGS_MIN_COVERAGE:
            by_ccy = holdings.dropna(subset=["Currency"]).groupby("Currency")["Weighting"].sum()
            tot = float(by_ccy.sum())
            ccy = {c: 100.0 * v / tot for c, v in by_ccy.items()} if tot > 0 else {}
            ccy_source = f"holdings ({coverage:.0f}% covered)"
        else:
            cat = root.find("Category/Portfolio")
            ccy = _ccy_block(cat) if cat is not None else {}
            ccy_source = "category proxy" if ccy else "n/a"
    out["currency"] = ccy
    out["currency_source"] = ccy_source

    # --- Freschezza dei dati (date "as of" pubblicate da Morningstar) ---
    # portfolio_date: data di composizione del portafoglio (holdings/settori),
    #                 tipicamente aggiornata a cadenza MENSILE con ritardo.
    # nav_date:       data dell'ultimo NAV disponibile (di solito giornaliero).
    # prev_portfolio_date: composizione precedente (per stimare la cadenza).
    def _text(node, path):
        el = node.find(path)
        return el.text if el is not None and el.text else None

    portfolio_date = _text(own, "PortfolioSummary/Date") or _text(own, ".//Date")
    nav_el = root.find("FundShareClass//NetAssetValue")
    if nav_el is None:
        nav_el = root.find(".//NetAssetValue")
    nav_date = nav_el.get("Date") if nav_el is not None else None
    out["freshness"] = {
        "portfolio_date": portfolio_date,                        # holdings
        "breakdown_date": portfolio_date,                        # settori / asset alloc.
        "breakdown_source": "lt.morningstar.com",
        "prev_portfolio_date": _text(own, ".//PreviousPortfolioDate"),
        "nav_date": nav_date,                                    # ultimo NAV
        "latest_on_morningstar": None,                           # verificato via API globale
    }

    return out


# -----------------------------------------------------------------------------
# Overlay dall'API globale (breakdown più recenti)
# -----------------------------------------------------------------------------

_GLOBAL_SECTOR_KEYS = {
    "basicMaterials": "101", "consumerCyclical": "102", "financialServices": "103",
    "realEstate": "104", "consumerDefensive": "205", "healthcare": "206",
    "utilities": "207", "communicationServices": "308", "energy": "309",
    "industrials": "310", "technology": "311",
}


def _global_asset_label(key: str) -> str:
    k = key.replace("AssetAlloc", "")
    if k.endswith("Equity"):
        return "Azioni"
    if k in ("Bond", "Convertible"):
        return "Obbligazioni"
    if k == "Cash":
        return "Liquidità"
    if k == "NotClassified":
        return "Non Classificato"
    return "Altro"


def fetch_global_breakdowns(sec_id: str) -> dict:
    """Asset allocation e settori dall'API globale Morningstar.

    Returns:
        {"portfolio_date": "YYYY-MM-DD" | None, "asset_allocation": {...},
         "sectors": {...}} con le stesse etichette di parse_fund_analytics.
    """
    from utils.nav_sources import fetch_morningstar_global

    asset = fetch_morningstar_global("process/asset/v2", sec_id)
    pdate = (asset.get("portfolioDate") or "")[:10] or None
    alloc: dict[str, float] = {}
    for key, v in (asset.get("allocationMap") or {}).items():
        try:
            val = float(v.get("netAllocation"))
        except (TypeError, ValueError, AttributeError):
            continue
        label = _global_asset_label(key)
        alloc[label] = alloc.get(label, 0.0) + val

    sectors: dict[str, float] = {}
    try:
        sec = fetch_morningstar_global("portfolio/v2/sector", sec_id)
        eq = (sec.get("EQUITY") or {}).get("fundPortfolio") or {}
        if (eq.get("portfolioDate") or "")[:10] == pdate:
            for key, code in _GLOBAL_SECTOR_KEYS.items():
                val = eq.get(key)
                if val:
                    sectors[SECTOR_NAMES[code]] = float(val)
    except Exception:
        sectors = {}

    return {"portfolio_date": pdate, "asset_allocation": alloc, "sectors": sectors}


def apply_global_overlay(data: dict, overlay: dict) -> dict:
    """Sostituisce settori / asset allocation se l'API globale è più recente.

    Holdings, style box ed esposizione valutaria restano quelli dell'XML
    (l'API globale non li espone o li ha alla stessa data).
    """
    fr = data.setdefault("freshness", {})
    gdate = overlay.get("portfolio_date")
    fr["latest_on_morningstar"] = max(filter(None, [gdate, fr.get("breakdown_date")]), default=None)
    base = fr.get("breakdown_date") or ""
    # Overlay solo se completo: asset allocation + settori (questi ultimi solo
    # per i fondi che li hanno, cioè non per i bond). Così i due blocchi
    # restano sempre della stessa data.
    needs_sectors = bool(data.get("sectors"))
    complete = bool(overlay.get("asset_allocation")) and (
        bool(overlay.get("sectors")) or not needs_sectors)
    if gdate and gdate > base and complete:
        data["asset_allocation"] = overlay["asset_allocation"]
        if needs_sectors:
            data["sectors"] = overlay["sectors"]
        fr["breakdown_date"] = gdate
        fr["breakdown_source"] = "global.morningstar.com"
    return data


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
        # Weighting = peso % del titolo DENTRO il fondo (0..100)
        # PortfolioWeight = peso % del titolo sul portafoglio totale
        h["PortfolioWeight"] = (weights.get(fund, 0.0) / total) * h["Weighting"]
        frames.append(h)
    if frames:
        allh = pd.concat(frames, ignore_index=True)
        # Unisce lo stesso titolo detenuto da più fondi (chiave: ISIN, poi nome)
        allh["_key"] = allh["ISIN"].fillna(allh["SecurityName"])

        # Dettaglio per-fondo: lista di (fund, fund_weight%, portfolio_weight%)
        # per ciascun titolo, usato dall'accordion nella pagina.
        def _breakdown(group):
            return [
                {
                    "fund": r["Fund"],
                    "fund_weight": round(float(r["Weighting"]), 4),
                    "portfolio_weight": round(float(r["PortfolioWeight"]), 4),
                }
                for _, r in group.sort_values("PortfolioWeight", ascending=False).iterrows()
            ]

        breakdowns = allh.groupby("_key").apply(_breakdown, include_groups=False)

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
        )
        merged["Breakdown"] = merged["_key"].map(breakdowns)
        merged = (
            merged.sort_values("PortfolioWeight", ascending=False)
            .reset_index(drop=True)
        )
        agg["holdings"] = merged
    else:
        agg["holdings"] = pd.DataFrame()

    return agg