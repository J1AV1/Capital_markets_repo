from ib_insync import *
import pandas as pd
import time

# Conexión con TWS/IB Gateway
ib = IB()
ib.connect('127.0.0.1', 7496)  # Asegúrate de que TWS esté ejecutándose

# Lista de símbolos y su tipo de contrato
symbols = ["AXP", "EQR", "GOOG", "IWM", "JPM",
           "KO", "NDAQ", "NVDA", "TQQQ", "UBER",
           "WMT", "SPY"]

data_dict = {}

for symbol in symbols:
    print(f"Descargando datos de {symbol} desde IBKR...")
    
    # Crear contrato de acción en NASDAQ
    contract = Stock(symbol, 'SMART', 'USD')
    
    # Solicitar datos históricos
    bars = ib.reqHistoricalData(
        contract,
        endDateTime='',
        durationStr='10 Y',
        barSizeSetting='1 day',
        whatToShow='TRADES',
        useRTH=True,
        formatDate=1
    )
    
    # Convertir a DataFrame y extraer solo Date y Close
    df = util.df(bars)[["date", "open","high","low","close", "volume"]].rename(columns={"date": "Date", "open":"Open", "high":"High",
                                                                                         "close": "Close", "volume":"Volume"})
    df.set_index("Date", inplace=True)
    
    data_dict[symbol] = df

    # Guardar CSV individual
    df.to_csv(f"{symbol}_historical_data.csv")
    
    time.sleep(1.5)  # Evitar limitaciones de IBKR

# Combinar todos los datos
all_data = pd.concat(data_dict, names=["Symbol"])
all_data = all_data.reset_index()
all_data.to_csv("all_historical_data.csv", index=False)

print("✅ Descarga completa desde IBKR.")
ib.disconnect()
