import pandas as pd
import numpy as np
from sklearn.preprocessing import MinMaxScaler
import tensorflow as tf
from keras import layers
from keras.callbacks import EarlyStopping, ReduceLROnPlateau
import matplotlib.pyplot as plt

# Paso 1: Cargar los datos del archivo Excel
file_path = r"C:\Users\jalpi\git_repos\Trading_stuff\Ideas_new_start\data\data_prueba.xlsx"
df = pd.read_excel(file_path, sheet_name="MES")

# Paso 2: Normalizar las columnas Price y Price_vol
scaler = MinMaxScaler()
df[['Price', 'Price_vol']] = scaler.fit_transform(df[['Price', 'Price_vol']])

# Paso 3: Convertir la columna Date a formato datetime (para uso posterior)
df['Date'] = pd.to_datetime(df['Date'])

# Paso 4: Crear secuencias para el modelo (X = características, y = predicción)
# Usamos una ventana de 60 días como ejemplo
def create_sequences(df, window_size):
    X, y = [], []
    for i in range(len(df) - window_size):
        X.append(df[['Price', 'Price_vol']].iloc[i:i+window_size].values)
        y.append(df['Price'].iloc[i + window_size])  # Predecimos el siguiente precio
    return np.array(X), np.array(y)

window_size = 60  # Usamos 60 días para predecir el siguiente día
X, y = create_sequences(df, window_size)

# Paso 5: Dividir en conjunto de entrenamiento y validación (80% - 20%)
train_size = int(len(X) * 0.8)
X_train, X_val = X[:train_size], X[train_size:]
y_train, y_val = y[:train_size], y[train_size:]

# Paso 6: Definir el modelo Transformer básico
def build_transformer_model(input_shape):
    inputs = layers.Input(shape=input_shape)
    x = layers.MultiHeadAttention(num_heads=8, key_dim=64)(inputs, inputs)
    x = layers.Dropout(0.1)(x)
    x = layers.LayerNormalization()(x)
    x = layers.GlobalAveragePooling1D()(x)
    x = layers.Dense(30, activation='relu')(x)
    outputs = layers.Dense(1)(x)  # Predicción de precio continuo
    model = tf.keras.Model(inputs, outputs)
    model.compile(optimizer='adam', loss='mean_squared_error')
    return model

# Paso 7: Construir y entrenar el modelo
input_shape = X_train.shape[1:]  # Forma (n_días, 2) para Price y Price_vol
model = build_transformer_model(input_shape)

# Callbacks
early_stopping = EarlyStopping(monitor='val_loss', patience=5, restore_best_weights=True)
reduce_lr = ReduceLROnPlateau(monitor='val_loss', factor=0.5, patience=3, min_lr=1e-6)

# Entrenar el modelo
history = model.fit(X_train, y_train, validation_data=(X_val, y_val),
                    epochs=20, batch_size=32, callbacks=[early_stopping, reduce_lr])

# Paso 8: Evaluar el modelo
loss = model.evaluate(X_val, y_val)
print(f'Pérdida en conjunto de validación: {loss}')

# Paso 9: Hacer predicciones
predictions = model.predict(X_val)

# Visualizar las predicciones vs valores reales
plt.figure(figsize=(10, 6))
plt.plot(y_val, label='Valor Real')
plt.plot(predictions, label='Predicción')
plt.legend()
plt.show()
