# Copilot Instructions for Capital_markets

## Purpose
This repository is a personal capital markets workspace with two main domains:
- `Portfolio_stuff`: portfolio analytics, Dash dashboard, and IBKR CSV data refresh.
- `Trading_stuff`: live momentum trading logic using IBKR and experimental ML/transformer code.

## Key architecture

### Capa de Datos Centralizada (v2.0)
- **BD SQLite centralizada**: `Portfolio_stuff/data/market_data.db`
  - Tabla `price_data`: symbol, date, open, high, low, close, volume, adj_close
  - Módulo de acceso: `Portfolio_stuff/data/db.py`
  - Interfaz: `get_price_data()`, `get_consolidated_data()`, `insert_or_update_prices_batch()`, `get_latest_close()`
- **Migración histárica**: CSVs migrados una sola vez con `migrate_to_db.py`; CSVs aún existen como backup

### Flujos Principales
- `Portfolio_stuff/Portfolio.py`: lee de BD via `get_consolidated_data()` y `get_price_data(symbol="SPY")`
- `Portfolio_stuff/data/update_data.py`: `update_ibkr_prices_to_db()` escribe precios directo en BD (sin CSVs)
- `Trading_stuff/momentum_strat/...`: lee precios de BD via `db.get_price_data()`

### Módulos Clave
- `Portfolio_stuff/data/db.py` (NEW): interfaz SQL centralizada
  - Inicializa BD automáticamente al importar
  - Métodos CRUD y consultas útiles
- `Portfolio_stuff/data/update_data.py` (REFACTORED): escribe en BD, mantiene backward compatibility
  - `update_ibkr_prices_to_db()` es la función nueva
  - `update_ibkr_csvs_and_consolidate()` delega a la nueva función
- `Portfolio_stuff/Portfolio.py` (UPDATED): lee de BD
  - Usa `get_consolidated_data()` para datos históricos
  - Usa `get_price_data(symbol="SPY")` para benchmark

## Data Flow
1. IBKR → `update_data.update_ibkr_prices_to_db()` → **BD SQLite** ← todos los módulos leen
2. Portfolio dashboard lee históricos de BD (sin I/O de CSVs)
3. Live trading lee precios diarios de BD
4. No hay flujo de datos en `Portfolio_stuff` que dependa de archivos CSV locales.

## Important workflows
- Run portfolio dashboard: `python Portfolio_stuff/Portfolio.py` (lee de BD automáticamente)
- Update prices from IBKR to BD: `python Portfolio_stuff/data/update_data.py`
- Add new instruments to BD desde IBKR: `python Portfolio_stuff/data/add_instruments_to_db.py --symbols AAPL TSLA`
- Test BD integration: `python Portfolio_stuff/test_db_integration.py`
- Run live trading: `python Trading_stuff/momentum_strat/QSTrader_Live_or_Paper_(IBKR)_Momentum_Top_N/live_runner_ibkr.py` (to be updated)

## Project conventions
- El repositorio es script-driven sin harness de tests.
- Paths actualmente Windows con rutas absolutas.
- **Datos centralizados en SQLite** (`market_data.db`); `Portfolio_stuff` ya no usa CSVs en el flujo principal.
- Portfolio analytics esperan columnas `Symbol`, `Date`, `Close` de BD o normalizan `Adj Close`.
- Trading_stuff usa pipeline CSV-driven de backtest/live separado (próxima migración a BD).
- No cambiar efectos de importación en `Portfolio.py` sin justificación: anteriormente hacía update automático; ahora leer de BD.

## Integration points
- **IBKR integration**: `Portfolio_stuff/data/update_data.py` escribe en BD; `Trading_stuff/.../broker_ibkr.py` ejecuta órdenes.
- **Portfolio dashboard**: lee de BD (`get_consolidated_data()` desde `db.py`); sin I/O CSV en flujo principal.
- **Live trading**: próximo paso es reemplazar lecturas CSV con `db.get_price_data()` en `live_runner_ibkr.py` y `data_live_csv.py`.

## Datos en BD
- Tabla `price_data` con UNIQUE(symbol, date); índice en (symbol, date) para consultas rápidas.
- Métodos clave en `db.py`:
  - `get_price_data(symbol=None, start_date=None, end_date=None)` → pandas DataFrame
  - `get_consolidated_data()` → (Symbol, Date, Close) para dashboard
  - `insert_or_update_prices_batch(records)` → ingesta bulk desde IBKR
  - `get_latest_close(symbol)` → (date, close) más reciente

## Agent guidance
- Responde de forma concisa y en español.
- Antes de realizar cambios en el repositorio, pregunta siempre al usuario qué desea modificar.
- Enfócate en cambios de archivos concretos y preserva el flujo de datos basado en CSV.
- Haz ediciones mínimas en `Portfolio.py` y `update_data.py` porque son críticos para la carga de datos y el dashboard.
- Antes de tocar la lógica de trading, revisa `live_config.py`; es la fuente única de parámetros y rutas.
- Si agregas funcionalidad, documenta qué CSV se genera y qué CSV se consume, especialmente `all_historical_data.csv` y `logs_live/*.csv`.

> Este archivo guía al agente sobre el comportamiento esperado para este repositorio.
