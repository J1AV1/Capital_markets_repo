# ib_full_history_downloader.py

from ib_insync import *
import pandas as pd
import os
import time

ib = IB()
ib.connect("127.0.0.1", 7496, clientId=1)

# === Configura tus símbolos aquí ===
symbols = ['SPY','NVDA','MSFT','AAPL','AMZN','META','AVGO','GOOG','BRK B','TSLA','JPM']  # Cambia a los que necesites
output_dir = "ib_data_full"
os.makedirs(output_dir, exist_ok=True)

def download_full_history(symbol):
    print(f"\n📥 Descargando {symbol}")
    contract = Stock(symbol, 'SMART', 'USD')

    end_date = ''
    duration = '1 Y'
    df_full = pd.DataFrame()
    attempts = 0

    while True:
        try:
            bars = ib.reqHistoricalData(
                contract,
                endDateTime=end_date,
                durationStr=duration,
                barSizeSetting='1 day',
                whatToShow='TRADES',
                useRTH=True,
                formatDate=1
            )

            if not bars:
                print("✅ Reached beginning of data.")
                break

            df = util.df(bars)
            df_full = pd.concat([df, df_full])
            end_date = df['date'].min().strftime('%Y%m%d %H:%M:%S')

            print(f"📆 Obtenido hasta: {end_date} ({len(df)} filas)")

            time.sleep(11)  # Para evitar pacing violation

        except Exception as e:
            print(f"❌ Error: {e}")
            attempts += 1
            if attempts > 3:
                break
            time.sleep(15)

    if not df_full.empty:
        df_full.drop_duplicates(subset='date', inplace=True)
        df_full.sort_values('date', inplace=True)
        df_full.rename(columns={
            'date': 'Date',
            'open': 'Open',
            'high': 'High',
            'low': 'Low',
            'close': 'Close',
            'volume': 'Volume'
        }, inplace=True)
        df_full.to_csv(f"{output_dir}/{symbol}.csv", index=False)
        print(f"💾 Guardado: {output_dir}/{symbol}.csv ({len(df_full)} filas)")
    else:
        print(f"⚠️ No se obtuvo data para {symbol}")

# Ejecuta por cada símbolo
for sym in symbols:
    download_full_history(sym)

ib.disconnect()
