"""
Genera las posiciones OBJETIVO de HOY para la Estrategia 4 (VolTarget Portfolio).

Reutiliza run_voltarget_portfolio para obtener los pesos ERC y el IDM, y luego
calcula la posicion optima N (sin buffer) y la banda de no-negociacion por
instrumento, usando el precio y la volatilidad mas recientes de la BD.

El buffer NO se aplica aqui: en vivo la banda se compara contra la posicion REAL
del broker (eso lo hace run_demo), no contra una ruta simulada.
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, ".."))
import config_demo as cfg  # noqa: E402  (fija sys.path a backtest/BD)

import Utils_function_backtest as utils  # noqa: E402
from Trading_stuff.backtest.voltarget_portfolio_backtest import run_voltarget_portfolio  # noqa: E402


def compute_targets(capital):
    """
    Calcula los objetivos de hoy para la Estrategia 4 con el capital dado.

    :return: (targets, meta)
        targets: dict {symbol: {date, price, sigma_annual, optimal, lower, upper}}
        meta: dict con weights (ERC) e idm.
    """
    portfolio, per, meta = run_voltarget_portfolio(
        cfg.SYMBOLS,
        capital=capital,
        target_risk=cfg.TARGET_RISK,
        weight_mode=cfg.WEIGHT_MODE,
        round_positions=cfg.ROUND_POSITIONS,
        buffer=True,
        buffer_frac=cfg.BUFFER_FRAC,
        span=cfg.SPAN,
        long_window_years=cfg.LONG_WINDOW_YEARS,
        start_date=cfg.START_DATE,
    )
    weights, idm = meta["weights"], meta["idm"]

    targets = {}
    for sym in cfg.SYMBOLS:
        sub = per[sym]
        if sub.empty:
            continue
        price = float(sub["price"].iloc[-1])
        sigma = float(sub["sigma_annual"].iloc[-1])
        date = sub.index[-1]
        n = utils.position_size(
            capital=capital, target_risk=cfg.TARGET_RISK, price=price,
            sigma_annual=sigma, multiplier=1.0, weight=weights[sym], idm=idm,
        )
        band = cfg.BUFFER_FRAC * abs(n)
        lower, upper = n - band, n + band
        if cfg.ROUND_POSITIONS:
            n, lower, upper = round(n), round(lower), round(upper)
        targets[sym] = {
            "date": str(date.date()) if hasattr(date, "date") else str(date),
            "price": price,
            "sigma_annual": sigma,
            "optimal": float(n),
            "lower": float(lower),
            "upper": float(upper),
        }

    # --- Tope de apalancamiento (cuenta sin margen) ---
    # Exposicion bruta objetivo = suma de |posicion| * precio. Si supera
    # capital * MAX_LEVERAGE, se escalan todas las posiciones (y sus bandas)
    # proporcionalmente para caber en el capital, preservando los pesos relativos.
    gross = sum(abs(t["optimal"]) * t["price"] for t in targets.values())
    max_gross = capital * cfg.MAX_LEVERAGE
    scale = 1.0
    if gross > max_gross and gross > 0:
        scale = max_gross / gross
        for t in targets.values():
            t["optimal"] *= scale
            band = cfg.BUFFER_FRAC * abs(t["optimal"])
            t["lower"] = t["optimal"] - band
            t["upper"] = t["optimal"] + band
            if cfg.ROUND_POSITIONS:
                t["optimal"] = round(t["optimal"])
                t["lower"] = round(t["lower"])
                t["upper"] = round(t["upper"])

    meta = {
        "weights": weights, "idm": idm,
        "gross_before": gross, "gross_after": min(gross, max_gross),
        "leverage_before": gross / capital if capital else 0.0,
        "leverage_after": min(gross, max_gross) / capital if capital else 0.0,
        "leverage_scale": scale,
    }
    return targets, meta
