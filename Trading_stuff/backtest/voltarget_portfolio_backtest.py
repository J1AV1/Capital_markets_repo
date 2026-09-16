"""
VolTarget Portfolio: backtest de un PORTAFOLIO de instrumentos, cada uno con sizing
escalado por volatilidad objetivo (VolTarget Single) + pesos de instrumento + IDM.
Inspirado en las ideas de Carver (Advanced Futures Trading Strategies), con
implementación y ajustes propios (pesos ERC por defecto, cash management, buffer).

Adaptado a acciones individuales (multiplier=1). Lee precios desde la BD SQLite
centralizada (Portfolio_stuff/data/market_data.db).

Idea:
  1. Cada instrumento se opera como una sub-estrategia = VolTarget Single.
  2. Se le asigna un peso (weight_i). Por defecto ERC (equal risk contribution).
  3. La posicion se escala por el peso y por el IDM (Instrument Diversification
     Multiplier), que recupera el riesgo "perdido" por diversificacion:
         N_i = (Capital * IDM * weight_i * target_risk) / (price_i * sigma_i%)
  4. El IDM se calcula con la matriz de correlaciones de las sub-estrategias:
         IDM = 1 / sqrt(w . rho . w^T)
  5. P&L del portafolio = suma de P&L de cada sub-estrategia.

Uso:
  python voltarget_portfolio_backtest.py                       # todos los simbolos de la BD
  python voltarget_portfolio_backtest.py --symbols SPY NVDA GOOG --capital 100000
  python voltarget_portfolio_backtest.py --target_risk 0.20 --no_round --plot
"""
import os
import sys
import argparse

import numpy as np
import pandas as pd

import Utils_function_backtest as utils
from Trading_stuff.backtest.voltarget_single_backtest import load_prices

# Acceso a la BD centralizada en Portfolio_stuff/data
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_DB_DIR = os.path.join(_REPO_ROOT, "Portfolio_stuff", "data")
if _DB_DIR not in sys.path:
    sys.path.insert(0, _DB_DIR)

import db  # noqa: E402


def _sub_strategy(symbol, capital, target_risk, weight, idm, multiplier,
                  span, long_window_years, round_positions, start_date, end_date,
                  buffer=True, buffer_frac=0.1):
    """
    Calcula la sub-estrategia (VolTarget Single con peso + IDM) para un simbolo.

    :return: DataFrame con price, sigma_annual, position, pnl, ret_pct.
    """
    price = load_prices(symbol, start_date=start_date, end_date=end_date)
    returns = price.pct_change()

    sigma_daily = utils.blended_daily_vol(returns, span=span, long_window_years=long_window_years)
    sigma_annual = utils.annualise_vol(sigma_daily)

    optimal = utils.position_size(
        capital=capital,
        target_risk=target_risk,
        price=price,
        sigma_annual=sigma_annual,
        multiplier=multiplier,
        weight=weight,
        idm=idm,
    )
    if buffer:
        position = utils.apply_buffer(optimal, buffer_frac=buffer_frac, round_positions=round_positions)
    else:
        position = optimal.round() if round_positions else optimal

    df = pd.DataFrame({"price": price, "sigma_annual": sigma_annual, "position": position})
    df["pnl"] = df["position"].shift(1) * df["price"].diff() * multiplier
    df["ret_pct"] = df["pnl"] / capital
    return df.dropna(subset=["position"])


def run_voltarget_portfolio(
    symbols,
    capital=100_000.0,
    target_risk=0.20,
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
    max_leverage=None,
    cap_after_round=False,
    start_date=None,
    end_date=None,
):
    """
    Ejecuta el backtest VolTarget Portfolio sobre una lista de simbolos.

    max_leverage: tope de exposicion bruta como multiplo del capital. None = sin
                  tope (usa el apalancamiento natural del IDM). 1.0 = sin margen.

    weight_mode: 'erc' (equal risk contribution, default) | 'equal' (1/N).
    capital_mode: 'fixed' | 'full' | 'half' (cash management / compounding).
    compound_freq: 'daily' | 'weekly' | 'monthly'.

    :param symbols: lista de simbolos (deben existir en la BD).
    :param capital: capital nocional total del portafolio.
    :param target_risk: riesgo objetivo anual del portafolio (0.20 con >=1
                        instrumento por clase de activo; menos si es concentrado).
    :param weights: dict {symbol: peso}. None = derivar segun weight_mode.
    :param idm: IDM a usar. None = calcularlo desde las correlaciones.
    :param round_positions: redondear posiciones (True) o permitir fraccional.
    :return: (portfolio_df, per_instrument, meta)
        portfolio_df: DataFrame con pnl, ret_pct, cum_ret del portafolio agregado.
        per_instrument: dict {symbol: sub_df}.
        meta: dict con weights, idm y stats por instrumento.
    """
    symbols = [s for s in symbols if s and s != "ALL"]
    if not symbols:
        raise ValueError("No se especificaron simbolos.")

    # Pesos base (iguales) para la pasada de correlaciones; la correlacion es
    # invariante al peso (escalar por columna), asi que sirven para derivar ERC.
    base_weights = utils.equal_weights(symbols)

    # --- Paso 1: sub-estrategias base (posiciones ideales sin buffer) para correlaciones ---
    base = {}
    for sym in symbols:
        base[sym] = _sub_strategy(
            sym, capital, target_risk, base_weights[sym], idm=1.0, multiplier=multiplier,
            span=span, long_window_years=long_window_years,
            round_positions=False, start_date=start_date, end_date=end_date,
            buffer=False,
        )

    # --- Paso 2: pesos de instrumento ---
    sub_returns = pd.DataFrame({sym: base[sym]["ret_pct"] for sym in symbols})
    if weights is None:
        if weight_mode == "erc":
            weights = utils.erc_weights(sub_returns)   # Equal Risk Contribution
        else:
            weights = base_weights                     # iguales

    # --- IDM desde la correlacion de las sub-estrategias (con los pesos finales) ---
    if idm is None:
        idm = utils.compute_idm(sub_returns, weights)

    compound_info = None
    # El tope de apalancamiento se aplica correctamente (antes del buffer) dentro
    # de simulate_capital, asi que si esta activo se usa esa ruta aunque el capital
    # sea fijo (capital_mode="fixed" mantiene el notional constante = capital).
    if capital_mode != "fixed" or max_leverage is not None:
        # --- Capital compuesto: simulacion forward del portafolio (Tactica 3) ---
        prices = {sym: base[sym]["price"] for sym in symbols}
        sigmas = {sym: base[sym]["sigma_annual"] for sym in symbols}
        portfolio, per_instrument, compound_info = utils.simulate_capital(
            prices, sigmas, weights, idm, target_risk, capital,
            buffer_frac=buffer_frac, round_positions=round_positions, multiplier=multiplier,
            capital_mode=capital_mode, compound_freq=compound_freq,
            high_watermark=high_watermark, max_leverage=max_leverage,
            cap_after_round=cap_after_round,
        )
        prices_bh = {sym: per_instrument[sym]["price"] for sym in symbols}
        portfolio["bench_ret"] = utils.buy_and_hold_returns(prices_bh, weights)
        portfolio = portfolio.dropna(subset=["ret_pct"])
        portfolio["cum_ret"] = portfolio["ret_pct"].cumsum()
        portfolio["bench_cum"] = portfolio["bench_ret"].cumsum()
    else:
        # --- Paso 3: recalcular sub-estrategias con el IDM final (aplicando buffer) ---
        per_instrument = {}
        for sym in symbols:
            per_instrument[sym] = _sub_strategy(
                sym, capital, target_risk, weights[sym], idm=idm, multiplier=multiplier,
                span=span, long_window_years=long_window_years,
                round_positions=round_positions, start_date=start_date, end_date=end_date,
                buffer=buffer, buffer_frac=buffer_frac,
            )

        # --- Paso 4: agregar P&L del portafolio ---
        pnl = pd.DataFrame({sym: per_instrument[sym]["pnl"] for sym in symbols})
        portfolio_pnl = pnl.sum(axis=1, min_count=1)
        portfolio = pd.DataFrame({"pnl": portfolio_pnl})
        portfolio["ret_pct"] = portfolio["pnl"] / capital

        # --- Benchmark: buy & hold 100% invertido con los MISMOS pesos ---
        prices = {sym: per_instrument[sym]["price"] for sym in symbols}
        portfolio["bench_ret"] = utils.buy_and_hold_returns(prices, weights)

        portfolio = portfolio.dropna(subset=["ret_pct"])
        portfolio["cum_ret"] = portfolio["ret_pct"].cumsum()
        portfolio["bench_cum"] = portfolio["bench_ret"].cumsum()

    # Stats por instrumento (sobre su contribucion al portafolio total)
    per_stats = {}
    for sym in symbols:
        sub = per_instrument[sym]
        if "ret_pct" in sub.columns:
            per_stats[sym] = utils.performance_stats(sub["ret_pct"], capital=capital)

    meta = {"weights": weights, "idm": idm, "per_stats": per_stats, "n": len(symbols),
            "compound_info": compound_info}
    return portfolio, per_instrument, meta


def plot_results(portfolio, per_instrument, target_risk, idm):
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(2, 1, figsize=(11, 8), sharex=True)

    # Curvas individuales (tenues) + portafolio agregado
    for sym, sub in per_instrument.items():
        axes[0].plot(sub.index, sub["ret_pct"].cumsum() * 100, lw=0.8, alpha=0.4)
    axes[0].plot(portfolio.index, portfolio["cum_ret"] * 100, color="black", lw=2, label="VolTarget Portfolio")
    axes[0].plot(portfolio.index, portfolio["bench_cum"] * 100, color="tab:red", lw=1.5, ls="--", label="Buy & Hold (mismos pesos)")
    axes[0].set_ylabel("Retorno acum. (%)")
    axes[0].set_title(f"VolTarget Portfolio (target {target_risk:.0%}, IDM {idm:.2f})")
    axes[0].legend(loc="upper left")
    axes[0].grid(alpha=0.3)

    # Volatilidad realizada rolling del portafolio (2 meses)
    roll_vol = portfolio["ret_pct"].rolling(42).std() * utils.ANNUALISATION * 100
    axes[1].plot(portfolio.index, roll_vol, color="tab:orange")
    axes[1].axhline(target_risk * 100, color="grey", ls="--", lw=1)
    axes[1].set_ylabel("Vol realizada rolling (%)")
    axes[1].set_xlabel("Fecha")
    axes[1].grid(alpha=0.3)

    plt.tight_layout()
    plt.show()


def main():
    parser = argparse.ArgumentParser(description="VolTarget Portfolio: backtest de portafolio (sizing por volatilidad, pesos ERC, IDM).")
    parser.add_argument("--symbols", nargs="+", default=None,
                        help="Simbolos del portafolio. Por defecto: todos los de la BD.")
    parser.add_argument("--capital", type=float, default=100_000.0, help="Capital nocional total.")
    parser.add_argument("--target_risk", type=float, default=0.20, help="Riesgo objetivo anual del portafolio.")
    parser.add_argument("--weight_mode", choices=["erc", "equal"], default="erc",
                        help="Pesos de instrumento: 'erc' (equal risk contribution, default) o 'equal' (1/N).")
    parser.add_argument("--idm", type=float, default=None, help="IDM fijo (None = calcular por correlacion).")
    parser.add_argument("--span", type=int, default=32, help="Span del EWMA de volatilidad.")
    parser.add_argument("--long_window_years", type=int, default=10, help="Anos de la ventana movil de la vol larga.")
    parser.add_argument("--no_round", action="store_true", help="No redondear posiciones (permite fraccional).")
    parser.add_argument("--no_buffer", action="store_true", help="Desactivar la banda de no-negociación (rebalanceo diario).")
    parser.add_argument("--buffer_frac", type=float, default=0.1, help="Ancho de la banda como fracción de N (0.1 default).")
    parser.add_argument("--capital_mode", choices=["fixed", "full", "half"], default="fixed",
                        help="Cash management (Carver Tactica 3): fixed / full / half compounding.")
    parser.add_argument("--compound_freq", choices=["daily", "weekly", "monthly"], default="monthly",
                        help="Frecuencia de actualización del capital compuesto.")
    parser.add_argument("--high_watermark", type=float, default=None,
                        help="High watermark del modo 'half' (default = capital inicial).")
    parser.add_argument("--max_leverage", type=float, default=None,
                        help="Tope de exposicion bruta como multiplo del capital (1.0 = sin margen). None = sin tope.")
    parser.add_argument("--start", default=None, help="Fecha inicio YYYY-MM-DD.")
    parser.add_argument("--end", default=None, help="Fecha fin YYYY-MM-DD.")
    parser.add_argument("--plot", action="store_true", help="Mostrar graficos.")
    args = parser.parse_args()

    symbols = args.symbols
    if symbols is None:
        symbols = [s for s in db.get_all_symbols() if s != "ALL"]

    portfolio, per_instrument, meta = run_voltarget_portfolio(
        symbols=symbols,
        capital=args.capital,
        target_risk=args.target_risk,
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
        max_leverage=args.max_leverage,
        start_date=args.start,
        end_date=args.end,
    )

    stats = utils.performance_stats(portfolio["ret_pct"], capital=args.capital)
    bench_stats = utils.performance_stats(portfolio["bench_ret"], capital=args.capital)
    print(f"\nInstrumentos ({meta['n']}): {', '.join(symbols)}")
    print(f"Modo de pesos        : {args.weight_mode}")
    if args.weight_mode == "erc":
        print("Pesos por instrumento (ERC):")
        for sym in sorted(meta["weights"], key=lambda s: -meta["weights"][s]):
            print(f"    {sym:6s}: {meta['weights'][sym]:6.2%}")
    else:
        print(f"Peso por instrumento : {1.0 / meta['n']:.2%} (iguales)")
    print(f"IDM                  : {meta['idm']:.3f}")
    utils.print_stats_comparison(
        stats, bench_stats,
        title=f"VolTarget Portfolio vs Buy & Hold - Portafolio ({meta['n']} instrumentos)",
        label_strat="VolTarget Portfolio", label_bench="Buy & Hold",
    )

    # Desglose realizado / no realizado agregando todos los instrumentos
    agg = {"realized": 0.0, "unrealized": 0.0, "commissions": 0.0,
           "net_total": 0.0, "gross_total": 0.0, "n_trades": 0}
    for sym in symbols:
        sub = per_instrument[sym]
        split = utils.realized_unrealized_pnl(sub["price"], sub["position"])
        for k in agg:
            agg[k] += split[k]
    utils.print_pnl_split(agg, label="VolTarget Portfolio")

    if meta.get("compound_info"):
        utils.print_compound_summary(meta["compound_info"], args.capital)

    if args.plot:
        plot_results(portfolio, per_instrument, args.target_risk, meta["idm"])


if __name__ == "__main__":
    main()
