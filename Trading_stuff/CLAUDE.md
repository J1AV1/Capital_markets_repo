# CLAUDE.md — Trading_stuff

Guía para agentes que trabajen en este directorio. Complementa el `README.md`.

## Qué es esto
Estrategias sistemáticas (backtest + ejecución) sobre acciones/ETFs, inspiradas
en Carver (*Advanced Futures Trading Strategies*) pero con implementación propia.
**No las llames "Estrategia 3/4/9 de Carver" en código ni en salidas** — usan
nombres propios: **VolTarget Single**, **VolTarget Portfolio**, **Trend Multi**.
La inspiración de Carver se reconoce en docstrings, nada más.

## Arquitectura y flujo de datos
- **Fuente de precios**: `Portfolio_stuff/data/market_data.db` (SQLite), vía
  `Portfolio_stuff/data/db.py`. Precios diarios ajustados por splits (no dividendos).
- **`backtest/Utils_function_backtest.py`** es el toolkit central; casi toda la
  lógica vive ahí. Los archivos de estrategia son orquestadores delgados.
- Cada estrategia produce: stats vs benchmark buy&hold, desglose P&L
  realizado/no realizado (comisiones IBKR), y opcionalmente gráficos.

### Funciones clave en `Utils_function_backtest.py`
- `blended_daily_vol` → vol diaria (EWMA corto 0.7 span 32 + media móvil 10y 0.3).
  `annualise_vol` la pasa a anual (×16). **`position_size` recibe la ANUALIZADA.**
- `position_size(capital, target_risk, price, sigma_annual, weight, idm)` → N.
- `apply_buffer` → banda de no-negociación (Carver cap. 8), path-dependent.
- `erc_weights` (equal risk contribution) y `compute_idm` (1/√(wᵀρw)).
- Forecast trend: `ewmac_raw_forecast`, `estimate_forecast_scalar` (backward-looking,
  **calculado por nosotros**, no tabla fija), `capped_forecast`, `compute_fdm`,
  `combined_trend_forecast`.
- `simulate_capital` → simulación forward con compounding (fixed/full/half + freq +
  high watermark); acepta `forecasts` para la estrategia de trend.
- `realized_unrealized_pnl` (costo promedio + comisiones IBKR), `ibkr_commission`.

## Convenciones importantes
- **Sizing usa `sigma_annual`** (no la diaria). El trend usa vol diaria en puntos de
  precio (`price·sigma_annual/16`) SOLO para el crossover EWMAC.
- **Pesos ERC son el default** en el portafolio (`weight_mode="erc"`); `equal` es opt-in.
- **Buffer**: en backtest se aplica sobre la ruta simulada; en vivo se compara la banda
  contra la posición REAL del broker (así no hay drift backtest↔ejecución).
- **% returns son invariantes al compounding**; el compounding solo escala dólares.
  No esperes que el Sharpe cambie entre fixed/full/half.
- El benchmark buy&hold usa **los mismos pesos** que la estrategia.
- **`max_leverage`** (1.0 = sin margen) capea la exposición bruta. Se aplica al OPTIMO
  **antes** del buffer (dentro de `simulate_capital`, dos pasadas) — nunca después,
  o el reescalado diario rompe la banda y dispara miles de trades. Con `max_leverage`
  activo, el backtest se enruta por `simulate_capital` aunque el capital sea fijo.

## Cómo correr (quirk de imports)
Los módulos mezclan imports planos (`import Utils_function_backtest`, `import db`)
y de paquete (`from Trading_stuff.backtest.voltarget_single_backtest import ...`).
Para que todo resuelva, corre con `PYTHONPATH` = raíz del repo + `Trading_stuff/backtest`
+ `Portfolio_stuff/data`. Los scripts añaden la carpeta de la BD a `sys.path` solos.
En consola de Windows los acentos salen como `A�os`; es cosmético (el UTF-8 en archivo está bien).
Silenciar `Error 162` de IBKR al hacer grep: son la señal de "no hay más historia".

## Ejecución demo/live (`demo/`, futuro `live/`)
- Config-driven: **todo el entorno vive en `config_demo.py`**; pasar a live = copiar
  la carpeta y ajustar `config_live.py` (puerto 7496, `DRY_RUN=False`).
- Broker: IBKR paper 7497 vía `ib_insync` (`broker_ibkr.py`). Requiere "Read-Only API"
  **desactivado** en TWS para enviar; timeouts de conexión suelen ser `clientId` colgado.
- `signals_strat4.py` reutiliza `run_voltarget_portfolio` para los targets de hoy y
  aplica el **tope de apalancamiento** (`MAX_LEVERAGE=1.0`, sin margen).
- IBKR **rechaza órdenes fraccionales por API** → `ROUND_POSITIONS=True` (enteras).
- **Capital = balance de ayer al cierre** (`CAPITAL_SOURCE="nav_prev"`) vía **Flex Web
  Service** (`flex_nav.py`, flujo SendRequest→GetStatement con polling). El campo
  `PreviousDayEquityWithLoanValue` NO viene por `accountValues`/`accountSummary` fiable
  → por eso Flex. **Sin fallbacks**: si Flex no da NAV, la corrida **aborta con alerta**.
- **Credenciales Flex** (token sensible): env `IBKR_FLEX_TOKEN`/`IBKR_FLEX_QUERY_ID` o
  `execution/flex_credentials.json` (**gitignoreado**). Nunca hardcodear en `config_demo.py`.
- El **parser del Flex** (`_parse_nav` en `flex_nav.py`) es provisional: ajustar a las
  secciones reales del XML de la query del usuario cuando esté disponible.

### ⚠️ Regla de seguridad (crítica)
**Un agente NO debe ejecutar el envío de órdenes** (`run_demo.py --execute`), ni
siquiera en paper — colocar compra/venta de valores lo hace el usuario. El agente
puede: correr backtests, correr `run_demo.py` en **dry-run**, y correr
`monitor_demo.py` (solo lectura). El disparo de órdenes reales es del usuario.

## Git
- No versionar `**/execution/state/` ni `**/execution/logs/` (ya en `.gitignore`).
- `market_data.db` (~15 MB binario) se recommitea entero en cada update; commitéalo
  aparte del código cuando cambie, no en cada commit de lógica.
- Termina los mensajes de commit con la línea `Co-Authored-By` correspondiente.
