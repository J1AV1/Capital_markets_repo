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
        opt_cont = n                      # optimo continuo (pre-redondeo), para el fix post-round
        band = cfg.BUFFER_FRAC * abs(n)
        lower, upper = n - band, n + band
        if cfg.ROUND_POSITIONS:
            n, lower, upper = round(n), round(lower), round(upper)
        targets[sym] = {
            "date": str(date.date()) if hasattr(date, "date") else str(date),
            "price": price,
            "sigma_annual": sigma,
            "optimal": float(n),
            "opt_cont": float(opt_cont),
            "lower": float(lower),
            "upper": float(upper),
        }

    # --- Tope de exposicion (cuenta sin margen) ---
    # Exposicion bruta objetivo = suma de |posicion| * precio.
    max_gross = capital * cfg.MAX_LEVERAGE
    gross_before = sum(abs(t["optimal"]) * t["price"] for t in targets.values())

    # Opcion CAP_AFTER_ROUND (cuenta chica): al redondear a enteros el bruto se
    # infla y puede superar el efectivo -> IBKR rechaza. Se enforca el tope sobre
    # las posiciones YA REDONDEADAS, con un colchon de caja (CASH_BUFFER) para el
    # drift de precio. Con enteras esto puede dejar en 0 los instrumentos mas caros.
    # Con mas capital, poner CAP_AFTER_ROUND=False -> sizing usual (pre-redondeo).
    cap_after_round = getattr(cfg, "CAP_AFTER_ROUND", False) and cfg.ROUND_POSITIONS
    cash_buffer = getattr(cfg, "CASH_BUFFER", 1.0) if cap_after_round else 1.0

    if cap_after_round:
        eff_cap = max_gross * cash_buffer
        scale = 1.0
        for _ in range(30):
            gross_r = sum(round(abs(t["opt_cont"]) * scale) * t["price"] for t in targets.values())
            if gross_r <= eff_cap or gross_r == 0:
                break
            scale *= (eff_cap / gross_r) * 0.99
        for t in targets.values():
            o = round(t["opt_cont"] * scale)
            band = cfg.BUFFER_FRAC * abs(o)
            t["optimal"] = float(o)
            t["lower"] = float(round(o - band))
            t["upper"] = float(round(o + band))
    else:
        # Sizing usual: escalar el optimo para caber en el tope y (si aplica) redondear.
        # El overshoot de redondeo es despreciable en cuentas grandes.
        if gross_before > max_gross and gross_before > 0:
            sc = max_gross / gross_before
            for t in targets.values():
                t["optimal"] *= sc
                band = cfg.BUFFER_FRAC * abs(t["optimal"])
                t["lower"] = t["optimal"] - band
                t["upper"] = t["optimal"] + band
                if cfg.ROUND_POSITIONS:
                    t["optimal"] = round(t["optimal"])
                    t["lower"] = round(t["lower"])
                    t["upper"] = round(t["upper"])

    gross_after = sum(abs(t["optimal"]) * t["price"] for t in targets.values())
    meta = {
        "weights": weights, "idm": idm,
        "gross_before": gross_before, "gross_after": gross_after,
        "leverage_before": gross_before / capital if capital else 0.0,
        "leverage_after": gross_after / capital if capital else 0.0,
        "leverage_scale": (gross_after / gross_before) if gross_before else 1.0,
        "cap_after_round": cap_after_round, "cash_buffer": cash_buffer,
    }
    return targets, meta
