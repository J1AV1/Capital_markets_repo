# live_tearsheet.py
import os
import pandas as pd
import pytz
from live_config import LOG_DIR, CSV_DIR, BENCHMARK
from qstrader.statistics.tearsheet import TearsheetStatistics

def load_equity_curve():
    path = os.path.join(LOG_DIR, 'equity_curve.csv')
    df = pd.read_csv(path, parse_dates=['datetime'])
    df = df.sort_values('datetime')
    df = df.set_index('datetime')
    # Espera columna 'equity'
    return df['equity']

def load_benchmark_equity(bench_symbol='SPY', start=None, end=None):
    # Construye una curva de equity de buy&hold con 1.0 como base
    path = os.path.join(CSV_DIR, f"{bench_symbol}.csv")
    bdf = pd.read_csv(path, parse_dates=['Date'])
    bdf = bdf.set_index('Date')
    px = bdf['Close'] if 'Close' in bdf.columns else bdf['Adj Close']
    px = px.sort_index()
    if start is not None:
        px = px[px.index >= start]
    if end is not None:
        px = px[px.index <= end]
    eq = px / px.iloc[0]
    eq.name = 'benchmark'
    return eq

if __name__ == "__main__":
    strat_eq = load_equity_curve()
    bench_eq = load_benchmark_equity(BENCHMARK, start=strat_eq.index.min(), end=strat_eq.index.max())

    # Alinea índices
    df = pd.concat([strat_eq, bench_eq], axis=1).dropna()
    strategy_equity = df['equity']
    benchmark_equity = df['benchmark']

    tearsheet = TearsheetStatistics(
        strategy_equity=strategy_equity,
        benchmark_equity=benchmark_equity,
        title='Live Momentum — Top N'
    )
    tearsheet.plot_results()
