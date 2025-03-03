#Funciones y clases a utilizar para el analisis del portafolio

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

def calculate_ewma_std(returns,periods ):
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
    ewma_variance[1] = returns[1] ** 2  # Initialize with the square of the first return
    for t in range(2, len(returns)):
        ewma_variance[t] = lambda_param * (returns[t] ** 2) + ((1 - lambda_param) * ewma_variance[t - 1])
    return np.sqrt(ewma_variance)

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

