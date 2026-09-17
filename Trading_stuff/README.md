# Trading_stuff

Backtesting y ejecución de estrategias sistemáticas sobre acciones/ETFs,
inspiradas en las ideas de Robert Carver (*Advanced Futures Trading Strategies*)
pero con implementación y ajustes propios. Los precios salen de la BD SQLite
centralizada `Portfolio_stuff/data/market_data.db`.

## Estructura

```
Trading_stuff/
├── backtest/                 # investigación / backtesting
│   ├── Utils_function_backtest.py        # toolkit común (vol, sizing, buffer, ERC, IDM, FDM, forecast, compounding, stats)
│   ├── voltarget_single_backtest.py      # 1 instrumento, sizing por volatilidad objetivo
│   ├── voltarget_portfolio_backtest.py   # portafolio: VolTarget + pesos ERC + IDM
│   ├── trend_multi_backtest.py           # trend following multi-EWMAC (long-only por defecto)
│   └── momentum_strat/                   # estrategia de momentum legacy (QSTrader/IBKR)
├── demo/                     # ejecución + monitoreo en cuenta PAPER (IBKR 7497)
│   ├── config_demo.py                    # todo el entorno demo (puerto, universo, riesgo, dry-run)
│   ├── execution/  (broker_ibkr, signals_strat4, run_demo, flex_nav)
│   └── monitoring/ (monitor_demo)
└── live/                     # ejecución + monitoreo en cuenta REAL (IBKR 7496)
    ├── config_live.py                    # espejo de config_demo apuntando a la cuenta real
    ├── execution/  (broker_ibkr, signals_strat4, run_live, flex_nav)
    └── monitoring/ (monitor_live)
```

**Ajustes locales sensibles** (cuenta real, capital) NO se versionan: viven en
`<env>/execution/local_settings.json` (gitignoreado) o en variables de entorno
`IB_ACCOUNT` / `FIXED_CAPITAL`. Ver plantilla `local_settings.example.json`.

## Las estrategias

| Nombre | Archivo | Idea |
|---|---|---|
| **VolTarget Single** | `voltarget_single_backtest.py` | Un instrumento; posición escalada para un riesgo objetivo anual usando vol EWMA. |
| **VolTarget Portfolio** | `voltarget_portfolio_backtest.py` | Cartera siempre larga; cada instrumento a la misma vol, pesos **ERC**, apalancada al target vía **IDM**. |
| **Trend Multi** | `trend_multi_backtest.py` | Trend following combinando varios filtros **EWMAC(n,4n)**; forecast escalado/capeado + **FDM**; long-only por defecto. |

Todas comparten: vol EWMA mezclada (corto 0.7 + media 10y 0.3), banda de
no-negociación (buffer), comisiones IBKR, desglose P&L realizado/no realizado,
benchmark buy & hold con los mismos pesos, y cash management (fixed / full /
half compounding con frecuencia daily/weekly/monthly).

## Cómo correr los backtests

Los módulos mezclan imports planos (`Utils_function_backtest`, `db`) y de paquete
(`Trading_stuff.backtest...`), así que la forma robusta de correrlos es con el
`PYTHONPATH` apuntando a la raíz del repo, la carpeta de backtest y la de la BD:

```bash
export PYTHONPATH="$REPO:$REPO/Trading_stuff/backtest:$REPO/Portfolio_stuff/data"
```
(en Windows/PowerShell: `$env:PYTHONPATH="..."`)

```bash
# Un instrumento
python Trading_stuff/backtest/voltarget_single_backtest.py --symbol SPY --no_round

# Portafolio (todos los símbolos de la BD por defecto)
python Trading_stuff/backtest/voltarget_portfolio_backtest.py --symbols SPY NVDA GLD --capital 5000 --no_round --capital_mode full

# Trend following multi-EWMAC
python Trading_stuff/backtest/trend_multi_backtest.py --speeds 32 64 --no_round
```

Flags comunes: `--capital`, `--target_risk`, `--no_round`, `--no_buffer`,
`--buffer_frac`, `--weight_mode {erc,equal}`, `--capital_mode {fixed,full,half}`,
`--compound_freq {daily,weekly,monthly}`, `--high_watermark`,
`--max_leverage` (1.0 = sin margen), `--start/--end`, `--plot`.
En trend: `--speeds`, `--long_short`.

## Ejecución demo (Estrategia VolTarget Portfolio)

Con **TWS paper** abierto en el puerto **7497** y "Read-Only API" desactivado:

```bash
cd Trading_stuff/demo/execution
python run_demo.py               # DRY-RUN: calcula objetivos e imprime órdenes SIN enviar
python run_demo.py --execute     # envía órdenes a la cuenta paper
python run_demo.py --no-update   # no refresca la BD antes de correr
```
```bash
cd ../monitoring
python monitor_demo.py           # snapshot: objetivo vs real, NAV/P&L, vol, salud
python monitor_demo.py --no-flex # usar nav_history.csv local en vez del Flex
```

El monitor muestra retornos **YTD / total / anualizado** en dos formas:
**TWR** (time-weighted, ignora aportes/retiros) y **MWR/TIR** (money-weighted, los
considera). La serie de NAV y los depósitos/retiros salen del Flex
(`flex_report`), con fallback a `nav_history.csv`.

Todo el comportamiento (puerto, universo, riesgo, dry-run, apalancamiento máximo)
se controla en `demo/config_demo.py`.

## Ejecución live (cuenta REAL — dinero real)

Espejo de la demo apuntando a la cuenta real. **Arranca en `DRY_RUN=True`**; el envío
real (`run_live.py --execute`) lo dispara **siempre el usuario**, nunca un agente.

```bash
cd Trading_stuff/live/execution
python run_live.py               # DRY-RUN contra la cuenta real (puerto 7496)
python run_live.py --execute     # ENVÍA órdenes reales (solo el usuario)
cd ../monitoring && python monitor_live.py
```

- Requiere TWS/Gateway en **7496** con la cuenta real, "Read-Only API" desactivado.
- **Cuenta**: `IB_ACCOUNT` en `local_settings.json`. Con **varias cuentas** bajo el
  mismo login la orden lleva `order.account` explícito (si no, IBKR la rechaza por
  ambigüedad).
- **Oro**: live usa **GLDM** (~$75/acción, cabe en cuenta chica); los **backtests**
  usan **GLD** (historia larga). Mismo subyacente, retorno idéntico.

### Notas de ejecución (IBKR)
- **Sin margen**: `MAX_LEVERAGE = 1.0` → si el sizing por riesgo pide más, se escala
  todo para que la exposición bruta no supere el NAV.
- **Acciones enteras**: IBKR rechaza órdenes fraccionales por API (error 10243) → `ROUND_POSITIONS = True`.
- **Tope post-redondeo (cuenta chica)**: con enteras y poco capital, redondear infla
  el bruto por encima del efectivo y IBKR rechaza por caja. `CAP_AFTER_ROUND = True`
  enforca el tope sobre las posiciones **ya redondeadas** + colchón `CASH_BUFFER`
  (ej. 0.97); puede dejar en 0 los instrumentos más caros. Con más capital, ponerlo
  en `False` → sizing usual (tope pre-redondeo). Mismo flag opcional en el backtest
  (`cap_after_round` en `simulate_capital` / `run_voltarget_portfolio`).
- **Capital = balance de AYER al cierre** (`CAPITAL_SOURCE = "nav_prev"`): se obtiene
  vía **IBKR Flex Web Service** (`flex_nav.py`). **Sin fallbacks**: si el Flex no
  devuelve NAV, la corrida **aborta con alerta** (no se opera sin capital confiable).
- El `state/` y `logs/` de ejecución están en `.gitignore` (son runtime, no se versionan).

### Configurar el Flex Web Service (para el NAV de cierre)
1. En IBKR Account Management: genera un **Flex Web Service token** y una **Flex Query**
   que incluya la sección de NAV / *Equity Summary in Base*; anota su **Query ID**.
   Para el monitor (TWR/MWR) conviene añadir a la query la **serie diaria de NAV** y
   las **transacciones de caja** (*Deposits/Withdrawals*).
2. Copia `<env>/execution/flex_credentials.example.json` a `flex_credentials.json`
   (gitignoreado) y pon tu token y query id. Alternativa: variables de entorno
   `IBKR_FLEX_TOKEN` / `IBKR_FLEX_QUERY_ID`. La cuenta a operar (`IB_ACCOUNT`) y el
   capital de respaldo (`FIXED_CAPITAL`) van en `local_settings.json` (gitignoreado).
