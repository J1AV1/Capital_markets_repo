"""
VolTarget Single: backtest de un instrumento con sizing de posición escalado por
volatilidad objetivo. Inspirado en las ideas de Carver (Advanced Futures Trading
Strategies) pero con implementación y ajustes propios.

Adaptado a acciones individuales (multiplier=1, sin rolling ni back-adjustment).
Lee precios desde la BD SQLite centralizada (Portfolio_stuff/data/market_data.db).

Idea:
  1. Estimar la volatilidad diaria con un EWMA mezclado (corto 70% + largo 30%).
  2. Anualizar (x16) para obtener sigma_%.
  3. Posición óptima diaria: N = (Capital * target_risk) / (price * sigma_%).
  4. Rebalancear al N objetivo (con banda de no-negociación); P&L = N_{t-1} * (P_t - P_{t-1}).

Uso:
  python voltarget_single_backtest.py --symbol SPY --capital 100000 --target_risk 0.10
  python voltarget_single_backtest.py --symbol NVDA --plot
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


def run_voltarget_single(
    symbol,
    capital=100_000.0,
    target_risk=0.10,
    multiplier=1.0,
    span=32,
    long_window_years=10,
    round_positions=True,
    buffer=True,
    buffer_frac=0.1,
    capital_mode="fixed",
    compound_freq="monthly",
    high_watermark=None,
    start_date=None,
    end_date=None,
):
    """
    Ejecuta el backtest VolTarget Single para un símbolo.

    :param capital: capital nocional inicial.
    :param target_risk: riesgo objetivo anual (Carver sugiere 0.10 para 1 instrumento).
    :param multiplier: multiplicador del contrato (1 para acciones).
    :param span: span del EWMA de volatilidad (32 = lambda ~0.06).
    :param long_window_years: años de la ventana móvil de la media larga de vol.
    :param round_positions: redondear la posición a entero (True) o dejar fraccional.
    :param buffer: aplicar banda de no-negociación de Carver (cap. 8) para reducir costos.
    :param buffer_frac: ancho de la banda como fracción de N (0.1 = recomendado).
    :param capital_mode: 'fixed' | 'full' | 'half' (cash management, Tactica 3 de Carver).
    :param compound_freq: 'daily' | 'weekly' | 'monthly' (cada cuánto se compone el capital).
    :return: pd.DataFrame con price, returns, sigma, position, pnl, ret_pct, cum_ret, bench_*.
    """
    price = load_prices(symbol, start_date=start_date, end_date=end_date)
    returns = price.pct_change()

    # Volatilidad mezclada (corto + largo) y anualizada
    sigma_daily = utils.blended_daily_vol(returns, span=span, long_window_years=long_window_years)
    sigma_annual = utils.annualise_vol(sigma_daily)

    if capital_mode != "fixed":
        # --- Capital compuesto: simulacion forward (Tactica 3) ---
        portfolio, per, info = utils.simulate_capital(
            {symbol: price}, {symbol: sigma_annual}, {symbol: 1.0}, idm=1.0,
            target_risk=target_risk, capital=capital, buffer_frac=buffer_frac,
            round_positions=round_positions, multiplier=multiplier,
            capital_mode=capital_mode, compound_freq=compound_freq,
            high_watermark=high_watermark,
        )
        df = pd.DataFrame({
            "price": price,
            "returns": returns,
            "sigma_annual": sigma_annual,
            "position": per[symbol]["position"],
        })
        df["pnl"] = portfolio["pnl"]
        df["ret_pct"] = portfolio["ret_pct"]
        df["capital"] = portfolio["capital"]
        df["equity"] = portfolio["equity"]
        df["bench_ret"] = utils.buy_and_hold_returns(price)
        df = df.dropna(subset=["position"])
        df["cum_ret"] = df["ret_pct"].cumsum()
        df["bench_cum"] = df["bench_ret"].cumsum()
        df.attrs["compound_info"] = info
        return df

    # --- Capital fijo (no compuesto) ---
    optimal = utils.position_size(
        capital=capital,
        target_risk=target_risk,
        price=price,
        sigma_annual=sigma_annual,
        multiplier=multiplier,
    )
    if buffer:
        position = utils.apply_buffer(optimal, buffer_frac=buffer_frac, round_positions=round_positions)
    else:
        position = optimal.round() if round_positions else optimal

    df = pd.DataFrame({
        "price": price,
        "returns": returns,
        "sigma_annual": sigma_annual,
        "optimal": optimal,
        "position": position,
    })

    # P&L usa la posición del día anterior sobre el cambio de precio (sin look-ahead)
    df["pnl"] = df["position"].shift(1) * df["price"].diff() * multiplier
    df["ret_pct"] = df["pnl"] / capital

    # Benchmark: buy & hold 100% invertido en el mismo instrumento (weight = 1)
    df["bench_ret"] = utils.buy_and_hold_returns(price)

    df = df.dropna(subset=["position"])
    df["cum_ret"] = df["ret_pct"].cumsum()
    df["bench_cum"] = df["bench_ret"].cumsum()

    return df


def plot_results(df, symbol, target_risk):
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(3, 1, figsize=(11, 9), sharex=True)

    axes[0].plot(df.index, df["cum_ret"] * 100, color="tab:blue", label="VolTarget Single")
    axes[0].plot(df.index, df["bench_cum"] * 100, color="tab:grey", lw=1, ls="--", label="Buy & Hold")
    axes[0].set_ylabel("Retorno acum. (%)")
    axes[0].set_title(f"VolTarget Single - {symbol} (target risk {target_risk:.0%})")
    axes[0].legend(loc="upper left")
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
    parser = argparse.ArgumentParser(description="VolTarget Single: backtest de un instrumento (sizing por volatilidad objetivo).")
    parser.add_argument("--symbol", default="SPY", help="Símbolo a backtestear (debe existir en la BD).")
    parser.add_argument("--capital", type=float, default=100_000.0, help="Capital nocional.")
    parser.add_argument("--target_risk", type=float, default=0.10, help="Riesgo objetivo anual (ej. 0.10).")
    parser.add_argument("--span", type=int, default=32, help="Span del EWMA de volatilidad.")
    parser.add_argument("--long_window_years", type=int, default=10, help="Años de la ventana móvil de la media larga de vol.")
    parser.add_argument("--no_round", action="store_true", help="No redondear posiciones (permite fraccional).")
    parser.add_argument("--no_buffer", action="store_true", help="Desactivar la banda de no-negociación (rebalanceo diario).")
    parser.add_argument("--buffer_frac", type=float, default=0.1, help="Ancho de la banda como fracción de N (0.1 default).")
    parser.add_argument("--capital_mode", choices=["fixed", "full", "half"], default="fixed",
                        help="Cash management (Carver Tactica 3): fixed / full / half compounding.")
    parser.add_argument("--compound_freq", choices=["daily", "weekly", "monthly"], default="monthly",
                        help="Frecuencia de actualización del capital compuesto.")
    parser.add_argument("--high_watermark", type=float, default=None,
                        help="High watermark del modo 'half' (default = capital inicial).")
    parser.add_argument("--start", default=None, help="Fecha inicio YYYY-MM-DD.")
    parser.add_argument("--end", default=None, help="Fecha fin YYYY-MM-DD.")
    parser.add_argument("--plot", action="store_true", help="Mostrar gráficos.")
    args = parser.parse_args()

    df = run_voltarget_single(
        symbol=args.symbol,
        capital=args.capital,
        target_risk=args.target_risk,
        span=args.span,
        long_window_years=args.long_window_years,
        round_positions=not args.no_round,
        buffer=not args.no_buffer,
        buffer_frac=args.buffer_frac,
        capital_mode=args.capital_mode,
        compound_freq=args.compound_freq,
        high_watermark=args.high_watermark,
        start_date=args.start,
        end_date=args.end,
    )

    stats = utils.performance_stats(df["ret_pct"], capital=args.capital)
    bench_stats = utils.performance_stats(df["bench_ret"], capital=args.capital)
    utils.print_stats_comparison(
        stats, bench_stats,
        title=f"VolTarget Single vs Buy & Hold - {args.symbol}",
        label_strat="VolTarget Single", label_bench="Buy & Hold",
    )

    split = utils.realized_unrealized_pnl(df["price"], df["position"])
    utils.print_pnl_split(split, label="VolTarget Single")

    if "compound_info" in df.attrs:
        utils.print_compound_summary(df.attrs["compound_info"], args.capital)

    if args.plot:
        plot_results(df, args.symbol, args.target_risk)


if __name__ == "__main__":
    main()
