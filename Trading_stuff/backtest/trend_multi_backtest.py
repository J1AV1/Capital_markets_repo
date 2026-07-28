"""
Trend Multi (Estrategia 9, long-only): portafolio de instrumentos operados con un
forecast de tendencia combinado de MULTIPLES filtros EWMAC de distinta velocidad.
Inspirado en Carver (Advanced Futures Trading Strategies), con implementacion propia.

Variante LONG-ONLY: el forecast combinado se pisa en 0, de modo que cuando el
forecast es <= 0 la posicion se cierra (0); solo se toman posiciones largas.

EWMACs MODULARES: eliges los speeds con --speeds (ej. 16 32 64 = EWMAC16/32/64).

Pipeline por instrumento:
  1. Forecast crudo de cada EWMAC(n,4n) = crossover / vol_diaria_en_precio.
  2. Escalado (forecast scalar) y capeado a +/-20.
  3. Promedio ponderado de los filtros + FDM (diversification multiplier) + re-cap.
  4. Long-only: forecast = max(forecast, 0).
  5. Posicion: N = (Capital*IDM*weight*tau*forecast/10) / (price*sigma%), con buffer.

Reutiliza pesos ERC, IDM, buffer, benchmark, desglose P&L y cash management.

Uso:
  python trend_multi_backtest.py --symbols SPY NVDA GOOG --capital 100000
  python trend_multi_backtest.py --speeds 8 16 32 64 --no_round --plot
  python trend_multi_backtest.py --symbols SPY --capital 5000 --no_round --capital_mode full
"""
import os
import sys
import argparse

import numpy as np
import pandas as pd

import Utils_function_backtest as utils
from Trading_stuff.backtest.voltarget_single_backtest import load_prices

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_DB_DIR = os.path.join(_REPO_ROOT, "Portfolio_stuff", "data")
if _DB_DIR not in sys.path:
    sys.path.insert(0, _DB_DIR)

import db  # noqa: E402

# Set de filtros por defecto: los mas lentos/baratos y robustos (Carver desaconseja
# los muy rapidos por costos, sobre todo con el minimo de $1 por orden de IBKR).
DEFAULT_SPEEDS = [16, 32, 64]


def prep_instrument(symbol, speeds, forecast_weights, long_only, span,
                    long_window_years, start_date, end_date):
    """Carga precio, calcula sigma y el forecast de tendencia combinado."""
    price = load_prices(symbol, start_date=start_date, end_date=end_date)
    returns = price.pct_change()
    sigma_daily = utils.blended_daily_vol(returns, span=span, long_window_years=long_window_years)
    sigma_annual = utils.annualise_vol(sigma_daily)
    forecast, fdm, _ = utils.combined_trend_forecast(
        price, sigma_annual, speeds, forecast_weights=forecast_weights,
        long_only=long_only,
    )
    return {"price": price, "sigma_annual": sigma_annual, "forecast": forecast, "fdm": fdm}


def _trend_position(prep, capital, target_risk, weight, idm, multiplier,
                    round_positions, buffer, buffer_frac):
    """Posicion con forecast: N = base * forecast/10, con buffer."""
    base = utils.position_size(
        capital=capital, target_risk=target_risk, price=prep["price"],
        sigma_annual=prep["sigma_annual"], multiplier=multiplier, weight=weight, idm=idm,
    )
    optimal = base * (prep["forecast"] / 10.0)
    if buffer:
        return utils.apply_buffer(optimal, buffer_frac=buffer_frac, round_positions=round_positions)
    return optimal.round() if round_positions else optimal


def _sub_df(prep, position, capital, multiplier):
    df = pd.DataFrame({
        "price": prep["price"], "sigma_annual": prep["sigma_annual"],
        "forecast": prep["forecast"], "position": position,
    })
    df["pnl"] = df["position"].shift(1) * df["price"].diff() * multiplier
    df["ret_pct"] = df["pnl"] / capital
    return df.dropna(subset=["position"])


def run_trend_multi(
    symbols,
    capital=100_000.0,
    target_risk=0.20,
    speeds=None,
    forecast_weights=None,
    long_only=True,
    weights=None,
    weight_mode="erc",
    idm=None,
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
    Ejecuta el backtest Trend Multi (Estrategia 9, long-only) sobre una lista de simbolos.

    :param speeds: lista de spans rapidos de EWMAC (default [16, 32, 64]).
    :param long_only: si True, forecast<=0 -> posicion 0 (solo largos).
    :param weight_mode: 'erc' (default) | 'equal' para los pesos de instrumento.
    :param capital_mode: 'fixed' | 'full' | 'half'.
    :return: (portfolio_df, per_instrument, meta)
    """
    symbols = [s for s in symbols if s and s != "ALL"]
    if not symbols:
        raise ValueError("No se especificaron simbolos.")
    if speeds is None:
        speeds = list(DEFAULT_SPEEDS)

    # Preparar cada instrumento (precio, sigma, forecast combinado)
    prep = {s: prep_instrument(s, speeds, forecast_weights, long_only, span,
                               long_window_years, start_date, end_date) for s in symbols}

    base_weights = utils.equal_weights(symbols)

    # --- Pasada base (pesos iguales, IDM=1, sin buffer) para correlaciones ---
    base = {}
    for s in symbols:
        pos = _trend_position(prep[s], capital, target_risk, base_weights[s], 1.0,
                              multiplier, round_positions=False, buffer=False, buffer_frac=buffer_frac)
        base[s] = _sub_df(prep[s], pos, capital, multiplier)

    sub_returns = pd.DataFrame({s: base[s]["ret_pct"] for s in symbols})
    if weights is None:
        weights = utils.erc_weights(sub_returns) if weight_mode == "erc" else base_weights
    if idm is None:
        idm = utils.compute_idm(sub_returns, weights)

    compound_info = None
    if capital_mode != "fixed":
        # --- Capital compuesto: simulacion forward con forecasts ---
        prices = {s: prep[s]["price"] for s in symbols}
        sigmas = {s: prep[s]["sigma_annual"] for s in symbols}
        forecasts = {s: prep[s]["forecast"] for s in symbols}
        portfolio, per_instrument, compound_info = utils.simulate_capital(
            prices, sigmas, weights, idm, target_risk, capital,
            buffer_frac=buffer_frac, round_positions=round_positions, multiplier=multiplier,
            capital_mode=capital_mode, compound_freq=compound_freq,
            high_watermark=high_watermark, forecasts=forecasts,
        )
        prices_bh = {s: per_instrument[s]["price"] for s in symbols}
        portfolio["bench_ret"] = utils.buy_and_hold_returns(prices_bh, weights)
        portfolio = portfolio.dropna(subset=["ret_pct"])
        portfolio["cum_ret"] = portfolio["ret_pct"].cumsum()
        portfolio["bench_cum"] = portfolio["bench_ret"].cumsum()
    else:
        # --- Capital fijo: pasada final con pesos + IDM + buffer ---
        per_instrument = {}
        for s in symbols:
            pos = _trend_position(prep[s], capital, target_risk, weights[s], idm,
                                  multiplier, round_positions, buffer, buffer_frac)
            per_instrument[s] = _sub_df(prep[s], pos, capital, multiplier)

        pnl = pd.DataFrame({s: per_instrument[s]["pnl"] for s in symbols})
        portfolio = pd.DataFrame({"pnl": pnl.sum(axis=1, min_count=1)})
        portfolio["ret_pct"] = portfolio["pnl"] / capital
        prices_bh = {s: per_instrument[s]["price"] for s in symbols}
        portfolio["bench_ret"] = utils.buy_and_hold_returns(prices_bh, weights)
        portfolio = portfolio.dropna(subset=["ret_pct"])
        portfolio["cum_ret"] = portfolio["ret_pct"].cumsum()
        portfolio["bench_cum"] = portfolio["bench_ret"].cumsum()

    meta = {"weights": weights, "idm": idm, "n": len(symbols), "speeds": speeds,
            "long_only": long_only, "fdm": {s: prep[s]["fdm"] for s in symbols},
            "compound_info": compound_info}
    return portfolio, per_instrument, meta


def plot_results(portfolio, per_instrument, target_risk, idm, speeds):
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(2, 1, figsize=(12, 8), sharex=True)
    for sym, sub in per_instrument.items():
        axes[0].plot(sub.index, sub["ret_pct"].cumsum() * 100, lw=0.7, alpha=0.35)
    axes[0].plot(portfolio.index, portfolio["cum_ret"] * 100, color="black", lw=2, label="Trend Multi")
    axes[0].plot(portfolio.index, portfolio["bench_cum"] * 100, color="tab:red", lw=1.5, ls="--",
                 label="Buy & Hold (mismos pesos)")
    axes[0].set_ylabel("Retorno acum. (%)")
    axes[0].set_title(f"Trend Multi long-only - EWMAC{speeds} (target {target_risk:.0%}, IDM {idm:.2f})")
    axes[0].legend(loc="upper left")
    axes[0].grid(alpha=0.3)

    roll_vol = portfolio["ret_pct"].rolling(42).std() * utils.ANNUALISATION * 100
    axes[1].plot(portfolio.index, roll_vol, color="tab:orange")
    axes[1].axhline(target_risk * 100, color="grey", ls="--", lw=1)
    axes[1].set_ylabel("Vol realizada rolling (%)")
    axes[1].set_xlabel("Fecha")
    axes[1].grid(alpha=0.3)

    plt.tight_layout()
    plt.show()


def main():
    parser = argparse.ArgumentParser(description="Trend Multi (Estrategia 9, long-only): trend following con EWMACs modulares.")
    parser.add_argument("--symbols", nargs="+", default=None, help="Simbolos. Default: todos los de la BD.")
    parser.add_argument("--speeds", nargs="+", type=int, default=None,
                        help="Spans rapidos de EWMAC, ej. 16 32 64 (default). EWMAC(n,4n).")
    parser.add_argument("--capital", type=float, default=100_000.0, help="Capital nocional total.")
    parser.add_argument("--target_risk", type=float, default=0.20, help="Riesgo objetivo anual.")
    parser.add_argument("--long_short", action="store_true", help="Permitir cortos (desactiva long-only).")
    parser.add_argument("--weight_mode", choices=["erc", "equal"], default="erc",
                        help="Pesos de instrumento: 'erc' (default) o 'equal'.")
    parser.add_argument("--idm", type=float, default=None, help="IDM fijo (None = calcular).")
    parser.add_argument("--span", type=int, default=32, help="Span del EWMA de volatilidad.")
    parser.add_argument("--long_window_years", type=int, default=10, help="Anos de la vol larga.")
    parser.add_argument("--no_round", action="store_true", help="No redondear posiciones (fraccional).")
    parser.add_argument("--no_buffer", action="store_true", help="Desactivar la banda de no-negociacion.")
    parser.add_argument("--buffer_frac", type=float, default=0.1, help="Ancho de la banda (fraccion de N).")
    parser.add_argument("--capital_mode", choices=["fixed", "full", "half"], default="fixed",
                        help="Cash management: fixed / full / half compounding.")
    parser.add_argument("--compound_freq", choices=["daily", "weekly", "monthly"], default="monthly")
    parser.add_argument("--high_watermark", type=float, default=None, help="HWM del modo 'half'.")
    parser.add_argument("--start", default=None, help="Fecha inicio YYYY-MM-DD.")
    parser.add_argument("--end", default=None, help="Fecha fin YYYY-MM-DD.")
    parser.add_argument("--plot", action="store_true", help="Mostrar graficos.")
    args = parser.parse_args()

    symbols = args.symbols
    if symbols is None:
        symbols = [s for s in db.get_all_symbols() if s != "ALL"]
    speeds = args.speeds if args.speeds is not None else list(DEFAULT_SPEEDS)

    portfolio, per_instrument, meta = run_trend_multi(
        symbols=symbols,
        capital=args.capital,
        target_risk=args.target_risk,
        speeds=speeds,
        long_only=not args.long_short,
        weight_mode=args.weight_mode,
        idm=args.idm,
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

    stats = utils.performance_stats(portfolio["ret_pct"], capital=args.capital)
    bench_stats = utils.performance_stats(portfolio["bench_ret"], capital=args.capital)
    print(f"\nInstrumentos ({meta['n']}): {', '.join(symbols)}")
    print(f"Filtros EWMAC        : {', '.join(f'EWMAC{n}' for n in meta['speeds'])}")
    print(f"Direccion            : {'long-only' if meta['long_only'] else 'long/short'}")
    print(f"Modo de pesos        : {args.weight_mode}")
    if args.weight_mode == "erc":
        print("Pesos por instrumento (ERC):")
        for sym in sorted(meta["weights"], key=lambda s: -meta["weights"][s]):
            print(f"    {sym:6s}: {meta['weights'][sym]:6.2%}")
    print(f"IDM                  : {meta['idm']:.3f}")
    utils.print_stats_comparison(
        stats, bench_stats,
        title=f"Trend Multi vs Buy & Hold - Portafolio ({meta['n']} instrumentos)",
        label_strat="Trend Multi", label_bench="Buy & Hold",
    )

    agg = {"realized": 0.0, "unrealized": 0.0, "commissions": 0.0,
           "net_total": 0.0, "gross_total": 0.0, "n_trades": 0}
    for sym in symbols:
        split = utils.realized_unrealized_pnl(per_instrument[sym]["price"], per_instrument[sym]["position"])
        for k in agg:
            agg[k] += split[k]
    utils.print_pnl_split(agg, label="Trend Multi")

    if meta.get("compound_info"):
        utils.print_compound_summary(meta["compound_info"], args.capital)

    if args.plot:
        plot_results(portfolio, per_instrument, args.target_risk, meta["idm"], meta["speeds"])


if __name__ == "__main__":
    main()
