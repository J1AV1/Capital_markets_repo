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


def print_stats(stats, title=""):
    """Imprime los estadisticos de performance en formato legible."""
    if title:
        print(f"\n== {title} ==")
    fmt = {
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
    for key, (label, f) in fmt.items():
        if key in stats:
            print(f"  {label:<28s}: {f.format(stats[key])}")
