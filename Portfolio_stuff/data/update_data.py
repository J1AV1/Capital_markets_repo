def update_ibkr_csvs_and_consolidate(
    csv_dir: str = "Portfolio_stuff/data",
    host: str = "127.0.0.1",
    port: int = 7496,
    client_id: int = 43,
    min_days_fetch: int = 30,
    bar_size: str = "1 day",
    what_to_show: str = "TRADES",
    use_rth: bool = True,
    sleep_between: float = 3.0,
) -> int:
    """
    Actualiza archivos CSV de datos históricos (OHLCV) usando IBKR (ib_insync) y
    consolida todo en all_historical_data.csv (Symbol, Date, Close).

    Requisitos:
        pip install ib-insync pandas

    Retorna:
        0 si éxito, >0 si error.
    """
    import os
    import time
    from typing import List, Tuple
    import pandas as pd

    try:
        from ib_insync import IB, Stock, util, BarData
    except Exception as e:
        print(f"[ERROR] ib_insync no está disponible: {e}")
        return 9

    CSV_COLS = ["Date", "Open", "High", "Low", "Close", "Volume"]
    CONSOLIDATED_BASENAME = "all_historical_data"  # sin .csv

    # ---- Helpers (internos a la función) ----
    def list_csv_tickers(dirpath: str) -> List[str]:
        if not os.path.isdir(dirpath):
            print(f"[ERROR] Carpeta no encontrada: {dirpath}")
            return []
        names = []
        for fn in os.listdir(dirpath):
            if not fn.lower().endswith(".csv"):
                continue
            base = fn[:-4]
            # Evitar consolidado y cualquier archivo “no-ticker”
            if base == CONSOLIDATED_BASENAME:
                continue
            names.append(base)
        return sorted(names)

    def ib_symbol_from_csv_name(csv_name: str) -> str:
        # Ej.: "SPY_historical_data" -> "SPY"
        return csv_name.split("_")[0]

    def build_contract(symbol: str) -> Stock:
        return Stock(symbol, "SMART", "USD")

    def safe_read_csv(path: str) -> pd.DataFrame:
        if not os.path.exists(path):
            return pd.DataFrame(columns=CSV_COLS)
        df = pd.read_csv(path)
        # Normalizar columnas
        df.columns = [c.strip() for c in df.columns]
        if "Close" not in df.columns and "Adj Close" in df.columns:
            df["Close"] = df["Adj Close"]
        for c in CSV_COLS:
            if c not in df.columns:
                df[c] = 0 if c == "Volume" else pd.NA
        return df[CSV_COLS]

    def bars_to_df(bars: List[BarData]) -> pd.DataFrame:
        if not bars:
            return pd.DataFrame(columns=CSV_COLS)
        rows = []
        for b in bars:
            dt = util.parseIBDatetime(b.date) if isinstance(b.date, str) else b.date
            d = pd.Timestamp(dt).tz_localize(None).date()
            rows.append({
                "Date": d.isoformat(),
                "Open": float(b.open),
                "High": float(b.high),
                "Low": float(b.low),
                "Close": float(b.close),
                "Volume": int(b.volume) if b.volume is not None else 0
            })
        df = pd.DataFrame(rows).drop_duplicates(subset=["Date"]).sort_values("Date")
        return df[CSV_COLS]

    def merge_new_rows(existing: pd.DataFrame, incoming: pd.DataFrame) -> Tuple[pd.DataFrame, int]:
        if existing.empty:
            return incoming.copy(), len(incoming)
        ex = existing.copy()
        inc = incoming.copy()
        ex["Date"] = pd.to_datetime(ex["Date"]).dt.date.astype(str)
        inc["Date"] = pd.to_datetime(inc["Date"]).dt.date.astype(str)
        merged = pd.concat([ex, inc], ignore_index=True)
        merged = merged.drop_duplicates(subset=["Date"], keep="last").sort_values("Date")
        added = len(merged) - len(ex.drop_duplicates(subset=["Date"]))
        return merged, max(0, added)

    def fetch_recent_daily_bars(ib: IB, contract: Stock, min_days: int) -> List[BarData]:
        duration_str = f"{max(5, min_days)} D"
        bars = ib.reqHistoricalData(
            contract,
            endDateTime="",
            durationStr=duration_str,
            barSizeSetting=bar_size,
            whatToShow=what_to_show,
            useRTH=use_rth,
            formatDate=1,
            keepUpToDate=False
        )
        if not bars:
            ib.sleep(0.5)
        return bars or []

    def update_one_ticker(ib: IB, dirpath: str, csv_name: str) -> Tuple[str, int]:
        path = os.path.join(dirpath, f"{csv_name}.csv")
        df_old = safe_read_csv(path)
        ib_symbol = ib_symbol_from_csv_name(csv_name)
        contract = build_contract(ib_symbol)
        ib.qualifyContracts(contract)
        bars = fetch_recent_daily_bars(ib, contract, min_days_fetch)
        df_new = bars_to_df(bars)
        if df_new.empty:
            print(f"[WARN] Sin barras para {csv_name} ({ib_symbol}).")
            return csv_name, 0
        merged, added = merge_new_rows(df_old, df_new)
        if added > 0:
            merged.to_csv(path, index=False)
        return csv_name, added

    # ---- Flujo principal ----
    print("== Actualización CSVs desde IBKR hasta T ==")
    tickers = list_csv_tickers(csv_dir)
    if not tickers:
        print(f"[ERROR] No hay CSVs en {csv_dir}")
        return 1

    ib = IB()
    try:
        ib.connect(host, port, clientId=client_id, readonly=True)
    except Exception as e:
        print(f"[ERROR] No se pudo conectar a IBKR: {e}")
        return 2

    total_added = 0
    updated: List[Tuple[str, int]] = []
    for csv_name in tickers:
        try:
            t0 = time.time()
            name, added = update_one_ticker(ib, csv_dir, csv_name)
            dt = time.time() - t0
            total_added += added
            updated.append((name, added))
            print(f"[OK] {name:>24s}: +{added:>3d} filas  ({dt:.2f}s)")
        except Exception as e:
            print(f"[FAIL] {csv_name}: {e}")
        time.sleep(sleep_between)

    ib.disconnect()

    print("\n== Resumen ==")
    for name, added in updated:
        print(f"  {name:>24s}: +{added} filas")
    print(f"Total filas nuevas: {total_added}")

    # ---- Consolidado ----
    print("\n📦 Consolidando todos los CSV en all_historical_data.csv...")
    frames = []
    for base in tickers:
        path = os.path.join(csv_dir, f"{base}.csv")
        if not os.path.exists(path):
            continue
        df = pd.read_csv(path)
        df["Symbol"] = ib_symbol_from_csv_name(base)
        frames.append(df)

    if frames:
        combined = pd.concat(frames, ignore_index=True)
        combined = combined[["Symbol", "Date", "Close"]]  # columnas mínimas
        out_path = os.path.join(csv_dir, f"{CONSOLIDATED_BASENAME}.csv")
        combined.to_csv(out_path, index=False)
        print("✅ Archivo all_historical_data.csv actualizado.")
    else:
        print("[WARN] No se encontraron datos para consolidar.")

    return 0
