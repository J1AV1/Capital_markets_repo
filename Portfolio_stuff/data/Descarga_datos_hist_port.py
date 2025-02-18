import yfinance as yf
import pandas as pd

# Lista de símbolos extraídos de la imagen más SPY
symbols = ["AXP", "EQR", "GOOG", "IWM", "JPM",
            "KO", "NDAQ", "NVDA", "TQQQ", "UBER",
              "WMT", "SPY"]

# Definir el período máximo disponible
data = {}
for symbol in symbols:
    print(f"Descargando datos para {symbol}...")
    stock = yf.Ticker(symbol)
    hist = stock.history(period="max")  # Obtiene la mayor cantidad de datos posibles
    data[symbol] = hist

    # Guardar cada símbolo en un CSV individual
    hist.to_csv(f"{symbol}_historical_data.csv")

# También guardamos todo en un solo archivo consolidado
all_data = pd.concat(data, names=["Symbol", "Date"])
all_data.to_csv("all_historical_data.csv")

print("Descarga completa. Datos guardados en archivos CSV.")
