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
│   ├── config_demo.py                    # único archivo que cambia para live
│   ├── execution/  (broker_ibkr, signals_strat4, run_demo)
│   └── monitoring/ (monitor_demo)
└── live/                     # (futuro) copia de demo/ con config_live.py (puerto 7496)
```

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
`--compound_freq {daily,weekly,monthly}`, `--high_watermark`, `--start/--end`,
`--plot`. En trend: `--speeds`, `--long_short`.

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
```

Todo el comportamiento (puerto, universo, riesgo, dry-run, apalancamiento máximo)
se controla en `demo/config_demo.py`. Al pasar a **live** se copia la carpeta y se
ajusta `config_live.py` (puerto 7496, `DRY_RUN=False`).

### Notas de ejecución (IBKR)
- **Sin margen**: `MAX_LEVERAGE = 1.0` → la exposición bruta nunca supera el NAV.
- **Acciones enteras**: IBKR rechaza órdenes fraccionales por API (error 10243) → `ROUND_POSITIONS = True`.
- **Capital**: `CAPITAL_SOURCE = "nav"` lee el NetLiquidation real de la cuenta (compounding natural).
- El `state/` y `logs/` de ejecución están en `.gitignore` (son runtime, no se versionan).
