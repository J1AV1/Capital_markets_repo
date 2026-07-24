#Funciones y clases a utilizar para el backtest de estrategias
#Copia de Portfolio_stuff/Analitic_functions/Util_functions.py + funciones de backtest

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

BUSINESS_DAYS_PER_YEAR = 256
ANNUALISATION = np.sqrt(BUSINESS_DAYS_PER_YEAR)  # = 16


def calculate_ewma_std(returns, periods):
    """
    Calculate EWMA standard deviation directly using the recursive variance formula.

    Parameters:
    - returns: A numpy array of returns
    - periods for smoothing

    Returns:
    - std_dev: A numpy array of EWMA standard deviation values
    """
    lambda_param = (2/(1+periods))
    ewma_variance = np.zeros(len(returns))
    ewma_variance[2] = returns[2] ** 2  # Initialize with the square of the first return
    for t in range(2, len(returns)):
        ewma_variance[t] = lambda_param * (returns[t] ** 2) + ((1 - lambda_param) * ewma_variance[t - 1])
    return np.sqrt(ewma_variance)


def calculate_returns(data):

    retornos = pd.DataFrame()

    for symbol, df in data.items():
            retornos[symbol] = df['Close'].pct_change()

    return retornos


def calculate_correlation_returns_individual_csv(data):
    """
    Calcula la matriz de correlación de los retornos diarios de los activos.
    :param data: Diccionario con DataFrames de históricos de cada activo.
    :return: DataFrame con la matriz de correlaciones.
    """
    retornos = pd.DataFrame()

    for symbol, df in data.items():
        retornos[symbol] = df['Close'].pct_change()

    return retornos.corr()


def calculate_correlation_returns_all_instruments_csv(data):
    """
    Calcula la matriz de correlación de los retornos diarios de los activos.
    :param data: DataFrame consolidado con históricos de cada activo.
    :return: DataFrame con la matriz de correlaciones.
    """
    retornos = data.groupby(level=0)['Close'].pct_change().unstack(level=0)
    return retornos.corr()


# ---------------------------------------------------------------------------
# Funciones de backtest (Carver - Advanced Futures Trading Strategies)
# ---------------------------------------------------------------------------

def ewma_daily_vol(returns, span=32):
    """
    Desviación estándar diaria estimada con un EWMA (pandas).
    span=32 equivale a lambda ~ 0.0606, el valor recomendado por Carver
    para pronosticar volatilidad (strategy three).

    :param returns: pd.Series de retornos porcentuales diarios.
    :param span: span del EWMA en días.
    :return: pd.Series de sigma diaria (en las mismas unidades que los retornos).
    """
    return returns.ewm(span=span, min_periods=span).std()


def blended_daily_vol(returns, span=32, long_window_years=10, weight_short=0.7):
    """
    Estimación de volatilidad mezclada de Carver (strategy three):
    sigma = 0.7 * short_run_std  +  0.3 * long_run_std

    - short_run_std: EWMA con span dado (~mes), peso 0.7.
    - long_run_std : media móvil (rolling) de largo plazo de la short_run_std,
                     con ventana de `long_window_years` años, peso 0.3.

    La long_run_std usa una ventana deslizante de N años (min_periods=1):
    el primer día en que la short_run_std existe, ambas son iguales (la media
    de un solo punto). Día a día la media incorpora más puntos (comportamiento
    tipo expanding) hasta llenar la ventana de N años; a partir de ahí la
    ventana se desliza y el dato más antiguo sale cuando entra uno nuevo.

    :param returns: pd.Series de retornos porcentuales diarios.
    :param span: span del EWMA corto.
    :param long_window_years: años de la ventana móvil de la media larga.
    :param weight_short: peso del componente corto (0.7 por defecto).
    :return: pd.Series de sigma diaria mezclada.
    """
    short_run_std = ewma_daily_vol(returns, span=span)

    long_window = int(long_window_years * BUSINESS_DAYS_PER_YEAR)
    long_run_std = short_run_std.rolling(window=long_window, min_periods=1).mean()

    weight_long = 1.0 - weight_short
    return weight_short * short_run_std + weight_long * long_run_std


def annualise_vol(daily_vol):
    """Anualiza una sigma diaria multiplicando por sqrt(256)=16."""
    return daily_vol * ANNUALISATION


def _period_key(d, freq):
    """Clave de periodo para la frecuencia de actualizacion del capital."""
    if freq == "daily":
        return (d.year, d.month, d.day)
    if freq == "weekly":
        iso = d.isocalendar()
        return (iso[0], iso[1])
    return (d.year, d.month)  # monthly


def simulate_capital(prices, sigmas, weights, idm, target_risk, capital,
                     buffer_frac=0.1, round_positions=False, multiplier=1.0,
                     capital_mode="full", compound_freq="monthly",
                     high_watermark=None):
    """
    Simulacion forward con capital compuesto (Carver, Tactica 3: cash & compounding).

    El capital de sizing se actualiza al valor de la cuenta (equity = realizado +
    no realizado) con la frecuencia indicada. Las posiciones escalan con ese capital,
    de modo que las apuestas crecen con las ganancias y se reducen con las perdidas.

    capital_mode:
      - "full" : capital de sizing = equity (valor de cuenta mark-to-market).
                 Maximiza el crecimiento geometrico si el riesgo esta en Kelly.
      - "half" : high watermark (performance fee 100%). Actua como capital fijo cuando el
                 capital de sizing alcanza el high watermark (retira/'skimea' el excedente)
                 y como full compounding por debajo (reduce posicion). Sobrevive drawdowns
                 severos igual que full, pero deja retirar ganancias. El high watermark por
                 defecto es el capital inicial; se puede fijar con `high_watermark`.
      - "fixed": capital constante (equivale al backtest no compuesto).

    compound_freq: 'daily' | 'weekly' | 'monthly' - cada cuanto se actualiza el capital.

    :param high_watermark: umbral del modo 'half' (None -> capital inicial). Con un HWM
                           mayor al capital, se compone full hasta alcanzarlo y luego se skimea.

    :param prices: dict {symbol: pd.Series de precios}.
    :param sigmas: dict {symbol: pd.Series de sigma anualizada}.
    :param weights: dict {symbol: peso}.
    :param idm: Instrument Diversification Multiplier.
    :return: (portfolio_df, per_instrument, info)
        portfolio_df: DataFrame con pnl, capital, equity, ret_pct.
        per_instrument: dict {symbol: DataFrame con price, sigma_annual, position, pnl}.
        info: dict con final_equity, final_capital, skimmed.
    """
    syms = list(prices.keys())
    price_df = pd.DataFrame({s: prices[s] for s in syms}).sort_index()
    sigma_df = pd.DataFrame({s: sigmas[s] for s in syms}).reindex(price_df.index)
    dates = price_df.index

    P = price_df.to_numpy(dtype=float)
    S = sigma_df.to_numpy(dtype=float)
    w = np.array([weights[s] for s in syms], dtype=float)
    m = len(syms)

    held = np.zeros(m)
    prev_price = np.full(m, np.nan)
    positions = np.full((len(dates), m), np.nan)
    pnl_arr = np.zeros(len(dates))
    cap_arr = np.zeros(len(dates))
    eq_arr = np.zeros(len(dates))

    hwm = float(high_watermark) if high_watermark is not None else float(capital)
    equity = float(capital)
    notional = float(capital)
    skimmed = 0.0
    prev_key = None

    for t in range(len(dates)):
        # P&L del dia por las posiciones mantenidas desde ayer
        pnl_day = 0.0
        for j in range(m):
            if held[j] != 0.0 and not np.isnan(P[t, j]) and not np.isnan(prev_price[j]):
                pnl_day += held[j] * (P[t, j] - prev_price[j]) * multiplier
        equity += pnl_day

        # Actualizar el capital de sizing al inicio de cada periodo nuevo
        key = _period_key(dates[t], compound_freq)
        if prev_key is None or key != prev_key:
            if capital_mode == "full":
                notional = max(equity, 0.0)
            elif capital_mode == "half":
                avail = equity - skimmed
                if avail > hwm:                     # sobre el high watermark -> skimear
                    skimmed += avail - hwm
                    notional = hwm
                else:                               # por debajo -> full compounding
                    notional = max(avail, 0.0)
            else:                                   # fixed
                notional = float(capital)
        prev_key = key

        # Rebalanceo con banda de no-negociacion
        for j in range(m):
            p = P[t, j]
            sig = S[t, j]
            if np.isnan(p) or np.isnan(sig) or sig <= 0:
                if not np.isnan(p):
                    prev_price[j] = p
                continue
            opt = notional * idm * w[j] * target_risk / (p * multiplier * sig)
            band = buffer_frac * abs(opt)
            lower, upper = opt - band, opt + band
            if round_positions:
                lower, upper = round(lower), round(upper)
            cur = held[j]
            new = lower if cur < lower else (upper if cur > upper else cur)
            held[j] = new
            positions[t, j] = new
            prev_price[j] = p

        pnl_arr[t] = pnl_day
        cap_arr[t] = notional
        eq_arr[t] = equity

    portfolio = pd.DataFrame(
        {"pnl": pnl_arr, "capital": cap_arr, "equity": eq_arr}, index=dates
    )
    # Retorno % sobre el capital vigente cuando se fijo la posicion (periodo previo),
    # no el de hoy (que ya incluye el P&L del dia).
    cap_prev = np.empty(len(dates))
    if len(dates):
        cap_prev[0] = capital
        cap_prev[1:] = cap_arr[:-1]
    portfolio["ret_pct"] = np.where(cap_prev > 0, pnl_arr / cap_prev, 0.0)

    per_instrument = {}
    for j, s in enumerate(syms):
        sub = pd.DataFrame(
            {"price": price_df[s], "sigma_annual": sigma_df[s], "position": positions[:, j]},
            index=dates,
        )
        sub["pnl"] = sub["position"].shift(1) * sub["price"].diff() * multiplier
        per_instrument[s] = sub

    info = {"final_equity": float(equity), "final_capital": float(notional),
            "skimmed": float(skimmed), "capital_mode": capital_mode,
            "compound_freq": compound_freq, "high_watermark": hwm}
    return portfolio, per_instrument, info


def apply_buffer(optimal, buffer_frac=0.1, round_positions=True):
    """
    Banda de no-negociacion de Carver (capitulo 8) para reducir trading/costos.

    Ancho de la banda:  B_t = buffer_frac * N_t   (buffer_frac = 0.1 => 10% de N)
    Zona:               [ round(N_t - B_t) , round(N_t + B_t) ]

    Decision, dada la posicion actual C (heredada del dia previo):
        - si  B^L <= C <= B^U : no operar (mantener C)
        - si  C < B^L         : comprar hasta B^L
        - si  C > B^U         : vender hasta B^U

    Es path-dependent: la posicion de hoy depende de si ayer se opero o no, por
    lo que se calcula iterando dia a dia. Long-only (las estrategias siempre
    estan largas).

    :param optimal: pd.Series de la posicion optima N_t (fraccional, puede tener NaN en warmup).
    :param buffer_frac: fraccion del ancho de banda (0.1 = recomendado por Carver).
    :param round_positions: redondear los bordes de la banda a unidades enteras.
    :return: pd.Series de la posicion realmente mantenida (buffered).
    """
    n = optimal.to_numpy(dtype=float)
    out = np.full(len(n), np.nan)
    current = 0.0
    for t in range(len(n)):
        if np.isnan(n[t]):
            continue
        width = buffer_frac * abs(n[t])
        lower = n[t] - width
        upper = n[t] + width
        if round_positions:
            lower = round(lower)
            upper = round(upper)
        if current < lower:
            current = lower          # comprar hasta el borde inferior
        elif current > upper:
            current = upper          # vender hasta el borde superior
        # else: dentro de la banda -> mantener
        out[t] = current
    return pd.Series(out, index=optimal.index)


def position_size(capital, target_risk, price, sigma_annual,
                  multiplier=1.0, weight=1.0, idm=1.0, fx=1.0):
    """
    Numero optimo de contratos/acciones segun el sizing por riesgo de Carver.

        N = (Capital * IDM * weight * target_risk)
            / (multiplier * price * fx * sigma_annual_%)

    Para acciones individuales: multiplier=1, fx=1, weight=1, idm=1.

    :param capital: capital nocional asignado (float).
    :param target_risk: riesgo objetivo anual (ej. 0.20 = 20%).
    :param price: precio del instrumento (Series o float).
    :param sigma_annual: desviación estándar anualizada de retornos (Series o float).
    :param multiplier: multiplicador del futuro (1 para acciones).
    :param weight: peso del instrumento en el portafolio.
    :param idm: instrument diversification multiplier.
    :param fx: tipo de cambio a la moneda de la cuenta.
    :return: numero de unidades (sin redondear).
    """
    notional_exposure = multiplier * price * fx
    risk_per_contract = notional_exposure * sigma_annual
    return (capital * idm * weight * target_risk) / risk_per_contract


# ---------------------------------------------------------------------------
# Portafolio (strategy four): IDM, pesos
# ---------------------------------------------------------------------------

# Tabla 16 de Carver: IDM aproximado segun numero de instrumentos.
_IDM_TABLE = [
    (1, 1.00), (2, 1.20), (3, 1.48), (4, 1.56), (5, 1.70),
    (6, 1.90), (7, 2.10), (14, 2.20), (24, 2.30), (29, 2.40),
]
_IDM_MAX = 2.50


def idm_from_table(n_instruments):
    """
    IDM aproximado de la tabla 16 de Carver dado el numero de instrumentos.
    Asume un set relativamente diversificado (no valido si todos son del
    mismo tipo, p.ej. 30 acciones de equity).
    """
    if n_instruments <= 0:
        return 1.0
    for threshold, idm in _IDM_TABLE:
        if n_instruments <= threshold:
            return idm
    return _IDM_MAX


def compute_idm(sub_returns, weights):
    """
    Instrument Diversification Multiplier calculado con la matriz de
    correlaciones de los retornos de las sub-estrategias (Appendix B de Carver):

        IDM = 1 / sqrt( w . rho . w^T )

    Con instrumentos no correlacionados e iguales pesos, IDM -> sqrt(N).
    Con instrumentos muy correlacionados (p.ej. puras acciones), IDM -> ~1.

    :param sub_returns: pd.DataFrame de retornos diarios por sub-estrategia
                        (una columna por instrumento).
    :param weights: dict {symbol: peso} (deben sumar 1).
    :return: float IDM.
    """
    corr = sub_returns.corr()
    symbols = list(corr.columns)
    w = np.array([weights[s] for s in symbols], dtype=float)
    corr_values = np.nan_to_num(corr.values, nan=0.0)
    np.fill_diagonal(corr_values, 1.0)
    variance = float(w @ corr_values @ w)
    if variance <= 0:
        return 1.0
    return 1.0 / np.sqrt(variance)


def equal_weights(symbols):
    """Pesos iguales para una lista de simbolos: dict {symbol: 1/N}."""
    n = len(symbols)
    return {s: 1.0 / n for s in symbols} if n else {}


def buy_and_hold_returns(prices, weights=None):
    """
    Retornos diarios del benchmark BUY & HOLD, 100% invertido, usando los
    MISMOS pesos que el backtest que se esta comparando.

        r_bench_t = sum_i ( weight_i * r_i,t )

    Es un portafolio de pesos constantes (rebalanceo implicito). Para un solo
    instrumento equivale a estar 100% invertido en el (weight = 1).

    Cuando un instrumento aun no tiene datos (historias distintas), no aporta a
    ese dia (min_count=1), igual que la estrategia solo opera los instrumentos
    disponibles.

    :param prices: pd.Series de precios (un instrumento) o dict {symbol: Series}.
    :param weights: dict {symbol: peso}. None -> pesos iguales (solo dict).
    :return: pd.Series de retornos diarios del benchmark.
    """
    if isinstance(prices, pd.Series):
        return prices.pct_change()

    symbols = list(prices.keys())
    if weights is None:
        weights = equal_weights(symbols)
    rets = pd.DataFrame({s: prices[s].pct_change() for s in symbols})
    w = pd.Series({s: weights[s] for s in symbols})
    weighted = rets.mul(w, axis=1)
    return weighted.sum(axis=1, min_count=1)


def performance_stats(returns, capital=None):
    """
    Estadisticos de desempeño al estilo Carver a partir de retornos porcentuales
    diarios (no compuestos).

    :param returns: pd.Series de retornos diarios porcentuales (decimal, 1% = 0.01).
    :param capital: opcional, capital nocional para reportar P&L en dinero.
    :return: dict con los estadisticos.
    """
    r = returns.dropna()
    if len(r) == 0:
        return {}

    mean_daily = r.mean()
    std_daily = r.std()

    mean_annual = mean_daily * BUSINESS_DAYS_PER_YEAR
    std_annual = std_daily * ANNUALISATION
    sharpe = mean_annual / std_annual if std_annual != 0 else np.nan

    # Skew mensual (Carver prefiere skew mensual)
    monthly = r.resample('ME').sum() if isinstance(r.index, pd.DatetimeIndex) else r
    skew_monthly = monthly.skew()

    # Drawdown sobre la curva acumulada (suma de retornos, no compuesta)
    cum = r.cumsum()
    drawdown = cum - cum.cummax()
    avg_drawdown = drawdown.mean()
    max_drawdown = drawdown.min()

    # Tails (percentile ratios) relativos a la Gaussiana (4.43)
    demeaned = r - mean_daily
    p1, p30, p70, p99 = demeaned.quantile([0.01, 0.30, 0.70, 0.99])
    gaussian_ratio = 4.43
    lower_tail = (p1 / p30) / gaussian_ratio if p30 != 0 else np.nan
    upper_tail = (p99 / p70) / gaussian_ratio if p70 != 0 else np.nan

    stats = {
        "years_of_data": len(r) / BUSINESS_DAYS_PER_YEAR,
        "mean_annual_return": mean_annual,
        "annualised_std": std_annual,
        "sharpe_ratio": sharpe,
        "skew_monthly": skew_monthly,
        "avg_drawdown": avg_drawdown,
        "max_drawdown": max_drawdown,
        "lower_tail": lower_tail,
        "upper_tail": upper_tail,
    }
    if capital is not None:
        stats["total_pnl"] = r.sum() * capital
    return stats


# Comisiones IBKR - plan Fixed para acciones/ETFs de EE.UU.
#   0.005 USD por accion, minimo 1.00 USD por orden, maximo 1% del valor.
IBKR_PER_SHARE = 0.005
IBKR_MIN_PER_ORDER = 1.00
IBKR_MAX_PCT = 0.01


def ibkr_commission(shares_traded, price,
                    per_share=IBKR_PER_SHARE,
                    min_per_order=IBKR_MIN_PER_ORDER,
                    max_pct=IBKR_MAX_PCT):
    """
    Comision IBKR (plan Fixed, acciones/ETFs US) para una orden.

        comision = min( max(per_share * |acciones|, min_por_orden),
                        max_pct * valor_operacion )

    El tope maximo (1% del valor) gana sobre el minimo en ordenes muy pequenas.

    :param shares_traded: unidades compradas (+) o vendidas (-); se usa el valor absoluto.
    :param price: precio de ejecucion.
    :return: comision en USD (0 si no hay trade).
    """
    shares = abs(float(shares_traded))
    if shares == 0:
        return 0.0
    raw = shares * per_share
    trade_value = shares * float(price)
    return min(max(raw, min_per_order), max_pct * trade_value)


def realized_unrealized_pnl(price, position, multiplier=1.0, commissions=True,
                            per_share=IBKR_PER_SHARE,
                            min_per_order=IBKR_MIN_PER_ORDER,
                            max_pct=IBKR_MAX_PCT):
    """
    Descompone el P&L de una sub-estrategia en realizado / no realizado, con
    comisiones IBKR incorporadas al COSTO PROMEDIO.

      - realizado   : P&L materializado al VENDER acciones en los rebalanceos,
                      NETO de la comision de venta (lo que queda "en caja").
      - no realizado: P&L latente de la posicion abierta; el costo promedio
                      incluye la comision de compra pagada.
      - comisiones  : total de comisiones IBKR pagadas en el periodo.

    Contabilidad por costo promedio, long-only (valido: las estrategias siempre
    estan largas). Los trades se ejecutan al cierre P_t.

    Identidades:
        realizado + no_realizado            == P&L neto
        P&L neto + comisiones               == P&L bruto (mark-to-market)

    :param commissions: si False, comision = 0 (P&L bruto = neto).
    :return: dict con realized, unrealized, commissions, net_total, gross_total,
             n_trades y las series acumuladas realized_series / unrealized_series.
    """
    df = pd.DataFrame({"price": price, "position": position}).dropna(subset=["price", "position"])
    p = df["price"].to_numpy(dtype=float)
    n = df["position"].to_numpy(dtype=float)

    shares = 0.0
    avg_cost = 0.0          # costo promedio, con comision de compra cargada
    realized = 0.0
    total_comm = 0.0
    n_trades = 0
    tol = 1e-12

    realized_arr = np.empty(len(p))
    unreal_arr = np.empty(len(p))

    for t in range(len(p)):
        target = n[t]
        delta = target - shares
        if delta > tol:                                  # compra
            comm = ibkr_commission(delta, p[t], per_share, min_per_order, max_pct) if commissions else 0.0
            total_comm += comm
            n_trades += 1
            total = shares + delta
            # costo base = costo previo + efectivo pagado (precio + comision)
            avg_cost = (shares * avg_cost + delta * p[t] * multiplier + comm) / total
            shares = target
        elif delta < -tol:                               # venta: realiza
            sold = -delta
            comm = ibkr_commission(sold, p[t], per_share, min_per_order, max_pct) if commissions else 0.0
            total_comm += comm
            n_trades += 1
            realized += sold * (p[t] * multiplier - avg_cost) - comm
            shares = target
            if abs(shares) < tol:
                shares = 0.0
        realized_arr[t] = realized
        unreal_arr[t] = shares * (p[t] * multiplier - avg_cost)

    realized_series = pd.Series(realized_arr, index=df.index)
    unreal_series = pd.Series(unreal_arr, index=df.index)
    net_total = realized_series.iloc[-1] + unreal_series.iloc[-1] if len(p) else 0.0

    return {
        "realized": float(realized_series.iloc[-1]) if len(p) else 0.0,
        "unrealized": float(unreal_series.iloc[-1]) if len(p) else 0.0,
        "commissions": float(total_comm),
        "net_total": float(net_total),
        "gross_total": float(net_total + total_comm),
        "n_trades": n_trades,
        "realized_series": realized_series,
        "unrealized_series": unreal_series,
    }


def print_compound_summary(info, capital):
    """Imprime el resumen del modo de capital compuesto (Tactica 3 de Carver)."""
    mode = info.get("capital_mode", "fixed")
    if mode == "fixed":
        return
    equity = info["final_equity"]        # riqueza total = cuenta + retirado
    skimmed = info["skimmed"]
    print(f"\n  Cash management (modo '{mode}', freq {info.get('compound_freq')}):")
    print(f"    Capital inicial           : {capital:>14,.0f}")
    print(f"    Capital de sizing final   : {info['final_capital']:>14,.0f}")
    if mode == "half":
        print(f"    High watermark            : {info.get('high_watermark', capital):>14,.0f}")
        print(f"    Valor total (cuenta+skim) : {equity:>14,.0f}")
        print(f"      En cuenta               : {equity - skimmed:>14,.0f}")
        print(f"      Retirado (skim/bolsillo): {skimmed:>14,.0f}")
    else:  # full
        print(f"    Valor de cuenta final     : {equity:>14,.0f}")
    factor = equity / capital if capital else 0.0
    print(f"    Crecimiento del capital   : {factor:>13.2f}x  (vs capital fijo)")


def print_pnl_split(split, label="Estrategia"):
    """Imprime el desglose bruto / comisiones / neto (realizado + no realizado)."""
    net = split["net_total"]
    if net == 0:
        return
    realized, unrealized = split["realized"], split["unrealized"]
    print(f"\n  Desglose P&L ({label}):")
    print(f"    P&L bruto (mark-to-market): {split['gross_total']:>14,.0f}")
    print(f"    Comisiones IBKR           : {-split['commissions']:>14,.0f}  ({split['n_trades']:,} trades)")
    print(f"    P&L neto                  : {net:>14,.0f}")
    print(f"      Realizado (en caja)     : {realized:>14,.0f}  ({realized / net:>6.1%} del neto)")
    print(f"      No realizado (abierto)  : {unrealized:>14,.0f}  ({unrealized / net:>6.1%} del neto)")
    print(f"    Buy & Hold: 100% no realizado (solo paga la comision de compra inicial)")


_STATS_FMT = {
    "years_of_data": ("Años de datos", "{:.1f}"),
    "mean_annual_return": ("Retorno anual medio", "{:.2%}"),
    "annualised_std": ("Desv. estándar anualizada", "{:.2%}"),
    "sharpe_ratio": ("Sharpe ratio", "{:.2f}"),
    "skew_monthly": ("Skew (mensual)", "{:.2f}"),
    "avg_drawdown": ("Drawdown medio", "{:.2%}"),
    "max_drawdown": ("Drawdown máximo", "{:.2%}"),
    "lower_tail": ("Lower tail", "{:.2f}"),
    "upper_tail": ("Upper tail", "{:.2f}"),
    "total_pnl": ("P&L total ($)", "{:,.0f}"),
}


def print_stats(stats, title=""):
    """Imprime los estadisticos de performance en formato legible."""
    if title:
        print(f"\n== {title} ==")
    for key, (label, f) in _STATS_FMT.items():
        if key in stats:
            print(f"  {label:<28s}: {f.format(stats[key])}")


def print_stats_comparison(stats_strat, stats_bench, title="",
                           label_strat="Estrategia", label_bench="Buy & Hold"):
    """
    Imprime dos conjuntos de estadisticos lado a lado (estrategia vs benchmark),
    con la diferencia de Sharpe al final.
    """
    if title:
        print(f"\n== {title} ==")
    print(f"  {'':<28s}  {label_strat:>14s}  {label_bench:>14s}")
    print(f"  {'-' * 28}  {'-' * 14}  {'-' * 14}")
    for key, (label, f) in _STATS_FMT.items():
        if key in stats_strat or key in stats_bench:
            a = f.format(stats_strat[key]) if key in stats_strat else "-"
            b = f.format(stats_bench[key]) if key in stats_bench else "-"
            print(f"  {label:<28s}  {a:>14s}  {b:>14s}")
    if "sharpe_ratio" in stats_strat and "sharpe_ratio" in stats_bench:
        delta = stats_strat["sharpe_ratio"] - stats_bench["sharpe_ratio"]
        ganador = label_strat if delta >= 0 else label_bench
        print(f"  {'-' * 28}  {'-' * 14}  {'-' * 14}")
        print(f"  {'Sharpe (estrat - bench)':<28s}  {delta:>+14.2f}  -> {ganador}")
