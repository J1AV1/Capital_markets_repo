"""
Configuracion de la ejecucion LIVE de la Estrategia 4 (VolTarget Portfolio).

Espejo de config_demo.py apuntando a la cuenta REAL (puerto 7496). La logica de
estrategia/ejecucion es la misma (importada desde este paquete live/); aqui solo
cambian entorno, cuenta, credenciales y parametros.

⚠️ DINERO REAL. Arranca en DRY_RUN=True a proposito. El envio de ordenes reales
   (run_live.py --execute) lo dispara SIEMPRE el usuario, nunca un agente.

Incluye el bootstrap de rutas para poder reutilizar el codigo de backtest.
"""
import os
import sys

# --- Bootstrap de rutas (reutilizar backtest + BD sin duplicar codigo) ---
_HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
_BACKTEST_DIR = os.path.join(REPO_ROOT, "Trading_stuff", "backtest")
_DB_DIR = os.path.join(REPO_ROOT, "Portfolio_stuff", "data")
for _p in (REPO_ROOT, _BACKTEST_DIR, _DB_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)


# --- Ajustes locales sensibles (cuenta, capital) ---
# Nunca se versionan: viven en execution/local_settings.json (gitignoreado) o en
# variables de entorno. Asi la cuenta real y el capital no tocan git.
def _load_local_settings():
    import json
    path = os.path.join(_HERE, "execution", "local_settings.json")
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


_LOCAL = _load_local_settings()

# --- Entorno / broker ---
ENV = "live"                 # "demo" | "live"
IB_HOST = "127.0.0.1"
IB_PORT = 7496               # TWS paper = 7497 ; TWS live = 7496 ; Gateway = 4002/4001
IB_CLIENT_ID = 61            # distinto del demo (51) para poder correr ambos sin colision de clientId
# Cuenta REAL: desde env o local_settings.json (gitignoreado). None = primera que devuelva IBKR.
IB_ACCOUNT = os.getenv("IB_ACCOUNT") or _LOCAL.get("IB_ACCOUNT") or None

# --- Seguridad ---
DRY_RUN = True               # True = imprime las ordenes, NO las envia. En LIVE cambiarlo a False lo hace el usuario.
MAX_ORDER_PCT_NAV = 0.30     # tope de valor por orden como fraccion del NAV. Ordenes mayores se bloquean.
MAX_DATA_STALE_DAYS = 5      # si la ultima barra de la BD es mas vieja que esto (dias habiles), abortar.
MIN_ORDER_VALUE = 5.0        # ignorar ordenes cuyo valor sea menor a esto (ruido).

# --- Universo y parametros de la Estrategia 4 ---
SYMBOLS = [
    "AXP", "GOOG", "WMT", "XLB", "XLI", "XLU", "XLV", "XLY",
    "XLC", "XLRE", "GLD", "SLV", "USO", "DBA",
]
TARGET_RISK = 0.20           # riesgo objetivo anual
# Tope de apalancamiento: exposicion bruta maxima como multiplo del NAV.
# 1.0 = SIN MARGEN (la exposicion nunca supera el capital). Si el sizing por
# riesgo pide mas, se escalan todas las posiciones para caber en el capital.
MAX_LEVERAGE = 1.0
WEIGHT_MODE = "erc"          # "erc" | "equal"
BUFFER_FRAC = 0.10           # ancho de la banda de no-negociacion (fraccion de N)
ROUND_POSITIONS = True       # IBKR NO acepta ordenes fraccionales por API (error 10243) -> enteras
SPAN = 32                    # span del EWMA de volatilidad
LONG_WINDOW_YEARS = 10
# Historia minima para calentar la volatilidad; None = todo lo disponible en la BD.
START_DATE = "2015-01-01"

# --- Capital ---
# "nav_prev" = balance al CIERRE DE AYER (PreviousDayEquityWithLoanValue de IBKR).
#              Recomendado para una estrategia EOD: capital estable, sin ruido intradia.
# "nav"      = NetLiquidation en vivo (intradia).
# "fixed"    = usar FIXED_CAPITAL.
CAPITAL_SOURCE = "nav_prev"
# Capital de respaldo (solo si CAPITAL_SOURCE="fixed"): desde env/local_settings.json.
FIXED_CAPITAL = float(os.getenv("FIXED_CAPITAL") or _LOCAL.get("FIXED_CAPITAL") or 1_000.0)

# Flex Web Service para el NAV de cierre (PreviousDayEquity no siempre viene por API).
# El token es SENSIBLE. Se lee de variable de entorno o del archivo gitignoreado
# execution/flex_credentials.json (copia de flex_credentials.example.json).
def _load_flex_creds():
    import json
    token = os.getenv("IBKR_FLEX_TOKEN")
    query = os.getenv("IBKR_FLEX_QUERY_ID")
    path = os.path.join(_HERE, "execution", "flex_credentials.json")
    if (not token or not query) and os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                d = json.load(f)
            token = token or d.get("IBKR_FLEX_TOKEN")
            query = query or d.get("IBKR_FLEX_QUERY_ID")
        except Exception:
            pass
    # Ignorar valores vacios (archivo sin llenar).
    return (token or None), (query or None)


FLEX_TOKEN, FLEX_QUERY_ID = _load_flex_creds()

# --- Rutas de estado / logs ---
STATE_DIR = os.path.join(_HERE, "execution", "state")
LOG_DIR = os.path.join(_HERE, "execution", "logs")
NAV_HISTORY_CSV = os.path.join(STATE_DIR, "nav_history.csv")
LAST_RUN_JSON = os.path.join(STATE_DIR, "last_run.json")
