"""
NAV de cierre del dia anterior via IBKR Flex Web Service.

Se usa cuando accountSummary/accountValues no entregan PreviousDayEquityWithLoanValue.
Flujo estandar de Flex (2 pasos):
  1. SendRequest(token, queryId)  -> ReferenceCode
  2. GetStatement(token, ref)     -> XML del reporte (con polling si aun se genera)

Credenciales (el token es sensible, NO se versiona):
  - IBKR_FLEX_TOKEN     (variable de entorno)  o  cfg.FLEX_TOKEN
  - IBKR_FLEX_QUERY_ID  (variable de entorno)  o  cfg.FLEX_QUERY_ID

Nota: el parser (`_parse_nav`) es provisional; se afina con el XML real de tu query.
"""
import os
import sys
import time
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, ".."))
try:
    import config_demo as cfg
except Exception:
    cfg = None

FLEX_BASE = "https://ndcdyn.interactivebrokers.com/AccountManagement/FlexWebService"
SEND_URL = FLEX_BASE + "/SendRequest"
GET_URL = FLEX_BASE + "/GetStatement"


def _get_credentials(token=None, query_id=None):
    token = token or os.getenv("IBKR_FLEX_TOKEN") or getattr(cfg, "FLEX_TOKEN", None)
    query_id = query_id or os.getenv("IBKR_FLEX_QUERY_ID") or getattr(cfg, "FLEX_QUERY_ID", None)
    if not token or not query_id:
        raise RuntimeError(
            "Faltan credenciales Flex. Define IBKR_FLEX_TOKEN e IBKR_FLEX_QUERY_ID "
            "(o FLEX_TOKEN/FLEX_QUERY_ID en config)."
        )
    return str(token), str(query_id)


def _http_get(url, params):
    full = url + "?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(full, timeout=30) as resp:
        return resp.read().decode("utf-8", errors="replace")


def request_report(token, query_id):
    """Paso 1: pide el reporte, devuelve el ReferenceCode."""
    xml = _http_get(SEND_URL, {"t": token, "q": query_id, "v": "3"})
    root = ET.fromstring(xml)
    status = (root.findtext("Status") or "").strip()
    if status != "Success":
        code = root.findtext("ErrorCode")
        msg = root.findtext("ErrorMessage")
        raise RuntimeError(f"Flex SendRequest fallo: status={status} code={code} msg={msg}")
    ref = root.findtext("ReferenceCode")
    if not ref:
        raise RuntimeError("Flex SendRequest sin ReferenceCode.")
    return ref


def fetch_report(token, reference_code, retries=8, delay=3.0):
    """Paso 2: obtiene el XML del reporte (hace polling mientras se genera)."""
    for _ in range(retries):
        xml = _http_get(GET_URL, {"t": token, "q": reference_code, "v": "3"})
        stripped = xml.lstrip()
        # Mientras se genera, IBKR devuelve un <FlexStatementResponse> con status Warn.
        if "Statement generation in progress" in xml or "<Status>Warn</Status>" in xml:
            time.sleep(delay)
            continue
        return xml
    raise RuntimeError("Flex GetStatement: el reporte no estuvo listo tras varios intentos.")


def _parse_nav(xml, account=None):
    """
    Extrae el NAV de cierre del XML del reporte. Provisional: intenta varias
    secciones comunes de Flex. Se ajustara al XML real de la query.
    """
    root = ET.fromstring(xml)

    def _match_acct(el):
        return account is None or el.get("accountId") in (None, account) or el.get("account") in (None, account)

    # 1) EquitySummaryInBase / EquitySummaryByReportDateInBase -> total (por fecha)
    best_date, best_val = None, None
    for tag in ("EquitySummaryInBase", "EquitySummaryByReportDateInBase"):
        for el in root.iter(tag):
            if not _match_acct(el):
                continue
            val = el.get("total") or el.get("cash")
            date = el.get("reportDate") or el.get("date") or ""
            if val:
                if best_date is None or date >= best_date:
                    best_date, best_val = date, float(val)
    if best_val is not None:
        return best_val

    # 2) ChangeInNAV -> endingValue
    for el in root.iter("ChangeInNAV"):
        if _match_acct(el) and el.get("endingValue"):
            return float(el.get("endingValue"))

    # 3) NAV / NetAssetValue con endingValue o total
    for tag in ("NAV", "NetAssetValue"):
        for el in root.iter(tag):
            if _match_acct(el):
                val = el.get("endingValue") or el.get("total")
                if val:
                    return float(val)

    raise RuntimeError("No se encontro el NAV en el XML del Flex Query (revisar secciones).")


def previous_day_nav_flex(token=None, query_id=None, account=None):
    """Devuelve el NAV de cierre del dia anterior via Flex Query. None si falla."""
    try:
        token, query_id = _get_credentials(token, query_id)
        ref = request_report(token, query_id)
        xml = fetch_report(token, ref)
        return _parse_nav(xml, account=account)
    except Exception as e:
        print(f"[flex] error: {e}")
        return None


if __name__ == "__main__":
    # Prueba rapida: python flex_nav.py  (con IBKR_FLEX_TOKEN / IBKR_FLEX_QUERY_ID)
    print("NAV cierre (Flex):", previous_day_nav_flex())
