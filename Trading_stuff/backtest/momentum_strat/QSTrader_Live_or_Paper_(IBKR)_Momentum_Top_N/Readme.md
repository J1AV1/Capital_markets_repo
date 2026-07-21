# QSTrader Live (IBKR) — Momentum Top-N 

Este paquete te permite ejecutar en vivo/paper tu estrategia Top-N Momentum con IBKR (ib_insync), leyendo precios desde CSV (EOD) para las señales y dejando rastros (logs) para luego generar un tearsheet similar al del backtest.

## Poryecto

  momentum_taa.py          # AlphaModel Top N Momentum (reutilizado del backtest)
  live_config.py           # Configuración de símbolos, rebalanceo, rutas, IBKR, etc.
  broker_ibkr.py           # Adaptador de bróker (IBKR con ib_insync)
  data_live_csv.py         # Entorno de datos CSV para señales y precios EOD
  utils_live.py            # Utilidades (rebalanceo, sizing -> órdenes)
  live_state.py            # Persistencia de logs (snapshots, órdenes, equity)
  live_runner_ibkr.py      # Runner principal en vivo (orquestación diaria/EOM)
  live_tearsheet.py        # Genera un tearsheet a partir del equity live + benchmark
  logs_live/               # Salida: daily_snapshot.csv, orders_log.csv, equity_curve.csv
  ib_data_full/            # CSVs de precios diarios por símbolo (Close/Adj Close)
  logs/
    trades_log.csv
    daily_pv.csv
    positions_log.csv

# Archivos y función específica
## momentum_taa.py
Qué es: Implementa el TopNMomentumAlphaModel y el wiring de señales (MomentumSignal).

Para qué se usa aquí: Reutilizamos el AlphaModel para calcular pesos objetivo en vivo; no ejecuta backtest en este flujo (la parte de backtest puede ignorarse al correr en live).

## live_config.py
Qué contiene:

Lista de símbolos y sus assets (EQ:TICKER).

Parámetros de la estrategia (MOM_LOOKBACK, MOM_TOP_N), CASH_BUFFER y frecuencia de rebalanceo (REBALANCE = 'end_of_month' | 'weekly' | 'daily').

Rutas de datos (CSV_DIR) y de logs (LOG_DIR).

Conexión a IBKR (host, port, clientId).

Mapeo de símbolos para IBKR (ej. EQ:BRK-B → BRK B).

Benchmark para el tearsheet (por defecto SPY).

Por qué es útil: Centraliza todo lo configurable para no tocar el runner.

## broker_ibkr.py
Qué hace: Adaptador a IBKR usando ib_insync.

get_positions() → dict { 'EQ:NVDA': 100, ... }.

get_cash() → efectivo disponible en USD.

place_orders(orders) -> List[dict] → envía órdenes Market y devuelve órdenes enriquecidas con:

filled_qty (cantidad ejecutada total)

fill_price (VWAP de ejecución)

Detalles:

Resuelve contratos con Stock(symbol, 'SMART', 'USD').

Normaliza símbolos (BRK-B ↔ BRK B).

Incluye un timeout configurable wait_fill_seconds para capturar fills.

## data_csv_live.py
Qué hace:

Monta un BacktestDataHandler con CSVDailyBarDataSource para que MomentumSignal funcione con histórico desde CSV.

Expone get_latest_close() para obtener precios de cierre del día (EOD) desde CSV (para marcar el portafolio y sizing).

Formato esperado:

Un archivo por símbolo en ib_data_full/, p.ej. NVDA.csv.

Columnas: Date, Open, High, Low, Close, Volume (o Adj Close si no hay Close).

## utils_live.py
Qué hace:

is_rebalance_day(now_utc) → Detecta si hoy toca rebalancear según REBALANCE.

weights_to_orders(...) → Convierte pesos objetivo en órdenes (market), respetando cash buffer, redondeo a enteros y generando ventas para activos con peso 0.

Nota: Mantiene symbol en formato interno 'EQ:...' para ser compatible con el broker adapter.

## live_state.py
Qué guarda (en logs_live/):

daily_snapshot.csv → una fila por día con:

datetime, target_weights (JSON), positions (JSON), prices (JSON), cash, portfolio_value.

orders_log.csv → órdenes enriquecidas realmente enviadas (y sus fills):

datetime, orders_json (lista de órdenes con filled_qty, fill_price).

equity_curve.csv → curva de equity live (para tearsheet):

datetime, equity.

Por qué: Permite reconstruir métricas live (turnover, slippage, rendementos) y auditar decisiones.

## live_runner_ibkr.py
Qué hace: Programa principal de ejecución en vivo.

Comprueba si hoy es día de rebalance.

Construye el universo y el data handler con CSVs.

Calcula pesos con el AlphaModel.

Consulta posiciones y cash en IBKR, y precios EOD desde CSV.

Genera órdenes (weights_to_orders), las envía con IBKR y obtiene fills.

Loguea snapshot, órdenes (con VWAP) y equity (post-trade).

Cómo se ejecuta:

Manual: python live_runner_ibkr.py

Programado: via cron/systemd unos minutos después del cierre (p.ej. 16:10 ET), cuando los CSV ya incluyen el cierre del día.

## live_tearsheet.py
Qué hace: Construye un tearsheet similar al del backtest usando:

equity_curve.csv (equity live) y

la serie de benchmark desde CSV (por defecto SPY) como buy&hold normalizado.

Resultado: abre una ventana con el TearsheetStatistics de QSTrader (equity curve, drawdown, Sharpe, etc.).

# Requisitos

pip install ib-insync qstrader pandas pytz

IBKR: TWS o IB Gateway corriendo, credenciales OK. Para paper trading, puerto por defecto 7497.
Datos: CSVs diarios actualizados en ib_data_full/ con los tickers definidos en live_config.py.

# Flujo de ejecución diario

1. Actualiza CSVs de precios EOD (Close/Adj Close).

2. live_runner_ibkr.py:

  * Verifica si es día de rebalance.

  * Calcula pesos con el AlphaModel (momentum).

  * Genera y envía las órdenes a IBKR; captura fills.

  * Guarda snapshot, órdenes y equity.

3. Cuando quieras, corre live_tearsheet.py para ver el tearsheet live.

# Consideraciones y Buenas Prácticas

1. Tipos de orden: el ejemplo usa Market por simplicidad. En producción evalúa MOC/LOC/LMT según tu política.

2. Persistencia: hoy CSVs; es fácil migrar live_state.py a SQLite manteniendo la misma interfaz.

3. Consistencia EOD: corre el runner cuando los CSV ya incluyen el cierre del día que estás rebalanceando.