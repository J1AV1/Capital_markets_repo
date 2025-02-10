import numpy as np
import itertools
from collections import defaultdict

def markov_chain_n_order(returns, last_returns, order=2):
    """
    Construye una Cadena de Markov de orden N con los retornos dados
    y predice el retorno más probable basado en los últimos N retornos.

    :param returns: Lista o array de retornos porcentuales.
    :param last_returns: Lista con los últimos N retornos para predecir el siguiente.
    :param order: Orden de la cadena (cuántos retornos pasados considerar).
    :return: Retorno más probable siguiente o None si no hay datos suficientes.
    """
    if len(last_returns) != order:
        raise ValueError(f"Debe proporcionar exactamente {order} retornos pasados.")

    # Redondeamos para reducir valores únicos
    returns = np.round(returns, 2)

    # Construcción de la matriz de transición de orden N
    transition_counts = defaultdict(lambda: defaultdict(int))

    for i in range(len(returns) - order):
        prev_states = tuple(returns[i : i + order])  # Tomamos los últimos N retornos como estado
        next_state = returns[i + order]  # Siguiente retorno
        transition_counts[prev_states][next_state] += 1

    # Convertir a matriz de probabilidades
    transition_matrix = {}
    for state, next_states in transition_counts.items():
        total_transitions = sum(next_states.values())
        transition_matrix[state] = {k: v / total_transitions for k, v in next_states.items()}

    # Predicción del siguiente retorno
    last_state = tuple(last_returns)
    if last_state in transition_matrix:
        predicted_return = max(transition_matrix[last_state], key=transition_matrix[last_state].get)
        return predicted_return
    else:
        return None  # No hay datos suficientes para predecir

# ---- EJEMPLO DE USO ----
np.random.seed(1250)
simulated_returns = np.random.normal(0,1.57,10000)  # Simulación de retornos

# Definimos los últimos N retornos observados
last_returns = [0.25, 0.10]  # Por ejemplo, queremos predecir basándonos en los últimos 2 retornos

# Usamos la cadena de Markov de orden 2
predicted_next = markov_chain_n_order(simulated_returns, last_returns, order=2)

print(f"Retornos imputados: {last_returns}")
if predicted_next is not None:
    print(f"Retorno más probable siguiente: {predicted_next}%")
else:
    print("No hay datos suficientes para hacer una predicción.")
