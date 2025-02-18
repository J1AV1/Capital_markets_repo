#Funciones y clases a utilizar para el analisis del portafolio

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt






# def calculate_std_36_dialy(Returns):

#     lambd = (2/(1+36)) 

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

