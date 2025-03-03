import yfinance as yf
import pandas as pd
import os
from datetime import datetime

def data_update_yf(symbols, file_path):
    # Obtener la fecha de hoy
    today = datetime.today().strftime('%Y-%m-%d')

    # Actualizar datos para cada símbolo
    for symbol in symbols:
        csv_file = os.path.join(file_path, f"{symbol}_historical_data.csv")
        
        if os.path.exists(csv_file):
            # Cargar los datos existentes
            df_existing = pd.read_csv(csv_file, index_col="Date", parse_dates=True)
            
            # Obtener la última fecha de datos
            last_date = df_existing.index[-1]
            
            # Descargar los datos desde la última fecha hasta el cierre más reciente
            print(f"Actualizando datos para {symbol} desde {last_date} hasta {today}...")
            stock = yf.Ticker(symbol)
            new_data = stock.history(start=last_date, end=today)  # Fecha final como el día actual
            
            if not new_data.empty:
                # Concatenar los nuevos datos con los existentes
                df_updated = pd.concat([df_existing, new_data])
                
                # Guardar los datos actualizados en el mismo archivo CSV
                df_updated.to_csv(csv_file)
                print(f"Datos de {symbol} actualizados correctamente.")
            else:
                print(f"No hay nuevos datos para {symbol}.")
        else:
            print(f"El archivo para {symbol} no existe.")
    
    # Actualizar all_historical_data.csv
    all_data = pd.concat([pd.read_csv(os.path.join(file_path, f"{symbol}_historical_data.csv"), 
                                      index_col="Date", parse_dates=True) 
                          for symbol in symbols], names=["Symbol", "Date"])
    
    all_data.to_csv(os.path.join(file_path, "all_historical_data.csv"))
    print("Archivo all_historical_data.csv actualizado.")
    print("Actualización completa.")

#Ejemplo de uso
symbols = ["AXP", "EQR", "GOOG", "IWM", "JPM", "KO", "NDAQ", "NVDA", "TQQQ", "UBER", "WMT", "SPY"]
file_path = r"C:\Users\jalpi\git_repos\Capital_markets\Portfolio_stuff\data"

# # Llamar a la función para actualizar los datos
data_update_yf(symbols, file_path)
