"""
Backtest de la Estrategia 3 de Carver (Advanced Futures Trading Strategies):
Buy and hold con sizing de posición escalado por riesgo variable.

Adaptado a acciones individuales (multiplier=1, sin rolling ni back-adjustment).
Lee precios desde la BD SQLite centralizada (Portfolio_stuff/data/market_data.db).

Idea de la estrategia:
  1. Estimar la volatilidad diaria con un EWMA mezclado (corto 70% + largo 30%).
  2. Anualizar (x16) para obtener sigma_%.
  3. Posición óptima diaria: N = (Capital * target_risk) / (price * sigma_%).
  4. Rebalancear cada día al N redondeado; P&L = N_{t-1} * (P_t - P_{t-1}).

Uso:
  python strategy3_backtest.py --symbol SPY --capital 100000 --target_risk 0.10
  python strategy3_backtest.py --symbol NVDA --plot
"""
import os
import sys
import argparse

import numpy as np
import pandas as pd

import Utils_function_backtest as utils

# Acceso a la BD centralizada en Portfolio_stuff/data
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_DB_DIR = os.path.join(_REPO_ROOT, "Portfolio_stuff", "data")
if _DB_DIR not in sys.path:
    sys.path.insert(0, _DB_DIR)

import db  # noqa: E402


def load_prices(symbol, start_date=None, end_date=None):
    """
    Carga precios de cierre de un símbolo desde la BD.

    :return: pd.Series de close indexada por fecha (DatetimeIndex).
    """
    df = db.get_price_data(symbol, start_date=start_date, end_date=end_date)
    if df.empty:
        raise ValueError(f"No hay datos en la BD para el símbolo '{symbol}'.")
    df = df.dropna(subset=["close"]).copy()
    df["date"] = pd.to_datetime(df["date"])
    series = df.set_index("date")["close"].sort_index()
    series.name = symbol
    return series


def run_strategy3(
    symbol,
    capital=100_000.0,
    target_risk=0.10,
    multiplier=1.0,
    span=32,
    long_window_years=10,
    round_positions=True,
    start_date=None,
    end_date=None,
):
    """
    Ejecuta el backtest de la estrategia 3 para un símbolo.

    :param capital: capital nocional fijo (no compuesto, estilo Carver).
    :param target_risk: riesgo objetivo anual (Carver sugiere 0.10 para 1 instrumento).
    :param multiplier: multiplicador del contrato (1 para acciones).
    :param span: span del EWMA de volatilidad (32 = lambda ~0.06).
    :param long_window_years: años de la ventana móvil de la media larga de vol.
    :param round_positions: redondear la posición a entero (True) o dejar fraccional.
    :return: pd.DataFrame con price, returns, sigma, position, pnl, ret_pct, cum_ret.
    """
    price = load_prices(symbol, start_date=start_date, end_date=end_date)
    returns = price.pct_change()

    # Volatilidad mezclada (corto + largo) y anualizada
    sigma_daily = utils.blended_daily_vol(returns, span=span, long_window_years=long_window_years)
    sigma_annual = utils.annualise_vol(sigma_daily)

    # Posición óptima según el precio y la volatilidad de HOY
    optimal = utils.position_size(
        capital=capital,
        target_risk=target_risk,
        price=price,
        sigma_annual=sigma_annual,
        multiplier=multiplier,
    )
    if round_positions:
        optimal = optimal.round()

    df = pd.DataFrame({
        "price": price,
        "returns": returns,
        "sigma_annual": sigma_annual,
        "position": optimal,
    })

    # P&L usa la posición del día anterior sobre el cambio de precio (sin look-ahead)
    df["pnl"] = df["position"].shift(1) * df["price"].diff() * multiplier
    df["ret_pct"] = df["pnl"] / capital
    df = df.dropna(subset=["position"])
    df["cum_ret"] = df["ret_pct"].cumsum()

    return df


def plot_results(df, symbol, target_risk):
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(3, 1, figsize=(11, 9), sharex=True)

    axes[0].plot(df.index, df["cum_ret"] * 100, color="tab:blue")
    axes[0].set_ylabel("Retorno acum. (%)")
    axes[0].set_title(f"Estrategia 3 - {symbol} (target risk {target_risk:.0%})")
    axes[0].grid(alpha=0.3)

    axes[1].plot(df.index, df["sigma_annual"] * 100, color="tab:orange")
    axes[1].axhline(target_risk * 100, color="grey", ls="--", lw=1)
    axes[1].set_ylabel("Sigma anual (%)")
    axes[1].grid(alpha=0.3)

    axes[2].plot(df.index, df["position"], color="tab:green")
    axes[2].set_ylabel("Posición (unidades)")
    axes[2].set_xlabel("Fecha")
    axes[2].grid(alpha=0.3)

    plt.tight_layout()
    plt.show()


def main():
    parser = argparse.ArgumentParser(description="Backtest Estrategia 3 (Carver) sobre acciones.")
    parser.add_argument("--symbol", default="SPY", help="Símbolo a backtestear (debe existir en la BD).")
    parser.add_argument("--capital", type=float, default=100_000.0, help="Capital nocional.")
    parser.add_argument("--target_risk", type=float, default=0.10, help="Riesgo objetivo anual (ej. 0.10).")
    parser.add_argument("--span", type=int, default=32, help="Span del EWMA de volatilidad.")
    parser.add_argument("--long_window_years", type=int, default=10, help="Años de la ventana móvil de la media larga de vol.")
    parser.add_argument("--no_round", action="store_true", help="No redondear posiciones (permite fraccional).")
    parser.add_argument("--start", default=None, help="Fecha inicio YYYY-MM-DD.")
    parser.add_argument("--end", default=None, help="Fecha fin YYYY-MM-DD.")
    parser.add_argument("--plot", action="store_true", help="Mostrar gráficos.")
    args = parser.parse_args()

    df = run_strategy3(
        symbol=args.symbol,
        capital=args.capital,
        target_risk=args.target_risk,
        span=args.span,
        long_window_years=args.long_window_years,
        round_positions=not args.no_round,
        start_date=args.start,
        end_date=args.end,
    )

    stats = utils.performance_stats(df["ret_pct"], capital=args.capital)
    utils.print_stats(stats, title=f"Estrategia 3 - {args.symbol}")

    if args.plot:
        plot_results(df, args.symbol, args.target_risk)


if __name__ == "__main__":
    main()
