from ib_insync import *
import pandas as pd
import os
import datetime
import time

def data_update_csv_ibkr(folder_path, symbols):
    """
    Actualiza archivos *_historical_data.csv existentes con datos desde IBKR.
    :param folder_path: Ruta donde están los CSV existentes.
    :param symbols: Lista de símbolos a actualizar.
    """
    ib = IB()
    try:
        ib.connect('127.0.0.1', 7497, clientId=2)
    except Exception:
        print("❌ Conexión a terminal fallida.")
        return

    for symbol in symbols:
        file_path = os.path.join(folder_path, f"{symbol}_historical_data.csv")
        if not os.path.exists(file_path):
            print(f"❌ {symbol}: CSV no encontrado, saltando...")
            continue

        # Leer CSV existente
        df_existing = pd.read_csv(file_path, parse_dates=["Date"])
        df_existing.set_index("Date", inplace=True)
        last_date = df_existing.index.max()
        next_date = last_date + pd.Timedelta(days=1)

        if next_date.date() >= pd.Timestamp.today().date():
            print(f"✅ {symbol}: Datos ya están actualizados.")
            continue

        print(f"🔄 {symbol}: Actualizando desde {next_date.date()}...")

        # Crear contrato
        contract = Stock(symbol, 'SMART', 'USD')

        # Calcular duración (máx. 365 días)
        delta_days = (pd.Timestamp.today().date() - next_date.date()).days
        duration_str = f"{min(delta_days, 365)} D"

        # Solicitar datos nuevos desde la última fecha
        bars = ib.reqHistoricalData(
            contract,
            endDateTime='',
            durationStr=duration_str,
            barSizeSetting='1 day',
            whatToShow='TRADES',
            useRTH=True,
            formatDate=1
        )

        # Convertir y filtrar
        df_new = util.df(bars)[["date", "close"]].rename(columns={"date": "Date", "close": "Close"})
        df_new["Date"] = pd.to_datetime(df_new["Date"])
        df_new = df_new[df_new["Date"] > last_date]
        df_new.set_index("Date", inplace=True)

        if df_new.empty:
            print(f"⚠️ {symbol}: No hay nuevos datos disponibles.")
            continue

        # Concatenar y guardar
        df_updated = pd.concat([df_existing, df_new])
        df_updated = df_updated[~df_updated.index.duplicated(keep='last')]  # evitar duplicados
        df_updated.sort_index(inplace=True)
        df_updated.to_csv(file_path)

        print(f"✅ {symbol}: {len(df_new)} nuevas filas agregadas.")
        time.sleep(1.5)  # evitar throttling

    ib.disconnect()
    print("🟢 Actualización completa.")
     
    # ======= Actualizar archivo consolidado ======= #
    print("📦 Consolidando todos los CSV en all_historical_data.csv...")

    all_data = []
    for symbol in symbols:
        file_path = os.path.join(folder_path, f"{symbol}_historical_data.csv")
        if os.path.exists(file_path):
            df = pd.read_csv(file_path)
            df["Symbol"] = symbol
            all_data.append(df)

    if all_data:
        combined_df = pd.concat(all_data)
        combined_df = combined_df[["Symbol", "Date", "Close"]]  # solo columnas necesarias
        combined_df.to_csv(os.path.join(folder_path, "all_historical_data.csv"), index=False)
        print("✅ Archivo all_historical_data.csv actualizado.")


# Ejemplo de uso:
data_update_csv_ibkr(r"C:\Users\jalpi\git_repos\Capital_markets\Portfolio_stuff\data", ["AXP", "EQR", "GOOG", "IWM", "JPM",
           "KO", "NDAQ", "NVDA", "TQQQ", "UBER",
           "WMT", "SPY"])

