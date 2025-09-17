# live_config.py
import pytz

# Símbolos (como en tu backtest)
SYMBOLS = ['NVDA','MSFT','AAPL','AMZN','META','AVGO','GOOG','BRK B','TSLA','JPM']
ASSETS  = [f"EQ:{s}" for s in SYMBOLS]

CSV_DIR = 'ib_data_full'      # carpeta con tus CSVs diarios
CASH_BUFFER = 0.01            # igual que backtest
MOM_LOOKBACK = 126
MOM_TOP_N = 3
REBALANCE = 'end_of_month'    # 'daily' / 'weekly' / 'end_of_month'
TZ_MARKET = 'America/New_York'

# Mapeo a símbolos de IBKR (importante BRK-B)
BROKER_SYMBOL_MAP = {
    'EQ:BRK-B': 'BRK B',  # IBKR contract para Berkshire B
    # otros suelen coincidir
}

# Conexión IBKR Paper
IBKR_HOST = '127.0.0.1'
IBKR_PORT = 7497
IBKR_CLIENT_ID = 17

# Carpeta de logs persistentes
LOG_DIR = 'logs_live'  # se crearán CSVs aquí

# Benchmark para tearsheet
BENCHMARK = 'SPY'