"""
Actualiza datos de precios desde IBKR directamente a la BD SQLite.
No escribe CSVs, todo va a la BD centralizada.
"""


def update_ibkr_prices_to_db(
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
    Actualiza precios desde IBKR y los guarda directamente en la BD SQLite.
    No toca los CSVs, todo centralizado en BD.

    Requisitos:
        pip install ib-insync pandas

    Retorna:
        0 si éxito, >0 si error.
    """
    import time
    from typing import List, Tuple
    import pandas as pd

    try:
        from ib_insync import IB, Stock, util, BarData
    except Exception as e:
        print(f"[ERROR] ib_insync no está disponible: {e}")
        return 9

    try:
        try:
            from .db import insert_or_update_prices_batch, get_all_symbols, get_latest_close
        except ImportError:
            from db import insert_or_update_prices_batch, get_all_symbols, get_latest_close
    except Exception as e:
        print(f"[ERROR] No se pudo importar db local: {e}")
        return 10

    # ---- Helpers ----
    def build_contract(symbol: str) -> Stock:
        return Stock(symbol, "SMART", "USD")

    def bars_to_records(symbol: str, bars: List[BarData]) -> List[dict]:
        """Convierte barras de IBKR a registros para BD."""
        if not bars:
            return []
        rows = []
        for b in bars:
            dt = util.parseIBDatetime(b.date) if isinstance(b.date, str) else b.date
            d = pd.Timestamp(dt).tz_localize(None).date()
            rows.append({
                "symbol": symbol,
                "date": d.isoformat(),
                "open": float(b.open) if b.open else None,
                "high": float(b.high) if b.high else None,
                "low": float(b.low) if b.low else None,
                "close": float(b.close),
                "volume": int(b.volume) if b.volume else None,
                "adj_close": None,
            })
        # Eliminar duplicados y ordenar
        df = pd.DataFrame(rows).drop_duplicates(subset=["date"]).sort_values("date")
        return df.to_dict("records")

    today = pd.Timestamp.now().normalize()

    def update_one_ticker(ib: IB, symbol: str) -> Tuple[str, int]:
        """
        Actualización incremental: mira la última fecha en la BD y trae solo lo
        faltante hasta t-1 (excluye la barra incompleta del día en curso).
        No mira hacia atrás más allá del hueco existente.
        """
        try:
            latest = get_latest_close(symbol)
            if latest is None:
                print(f"  [SKIP] {symbol}: sin datos previos (usa add_instruments_to_db.py)")
                return symbol, 0

            latest_date = pd.Timestamp(latest[0]).normalize()
            gap_days = (today - latest_date).days
            if gap_days <= 1:
                # La BD ya está en t-1 (o más nueva): nada que traer.
                return symbol, 0

            # Duración justa para cubrir el hueco, con margen para fines de semana/feriados.
            duration_str = f"{gap_days + 4} D"

            contract = build_contract(symbol)
            ib.qualifyContracts(contract)
            bars = ib.reqHistoricalData(
                contract,
                endDateTime="",
                durationStr=duration_str,
                barSizeSetting=bar_size,
                whatToShow=what_to_show,
                useRTH=use_rth,
                formatDate=1,
                keepUpToDate=False,
            )
            records = bars_to_records(symbol, bars)

            # Solo lo faltante: fechas nuevas y excluyendo el día en curso (t).
            records = [
                r for r in records
                if latest_date < pd.Timestamp(r["date"]) < today
            ]
            if not records:
                return symbol, 0

            insert_or_update_prices_batch(records)
            return symbol, len(records)
        except Exception as e:
            print(f"  [ERROR] {symbol}: {e}")
            return symbol, 0

    # ---- Flujo principal ----
    print("== Actualización de precios desde IBKR a BD ==")
    
    symbols = get_all_symbols()
    if not symbols:
        print("[WARN] No hay símbolos en BD. Agrega instrumentos con add_instruments_to_db.py")
        return 1
    
    # Limpiar símbolos irrelevantes
    symbols = [s for s in symbols if s != "ALL"]
    
    print(f"Actualizando {len(symbols)} símbolos...\n")

    ib = IB()
    try:
        ib.connect(host, port, clientId=client_id, readonly=True)
    except Exception as e:
        print(f"[ERROR] No se pudo conectar a IBKR: {e}")
        return 2

    total_added = 0
    updated: List[Tuple[str, int]] = []
    
    for symbol in symbols:
        try:
            t0 = time.time()
            name, added = update_one_ticker(ib, symbol)
            dt = time.time() - t0
            total_added += added
            updated.append((name, added))
            print(f"[OK] {name:>10s}: +{added:>4d} filas  ({dt:.2f}s)")
        except Exception as e:
            print(f"[FAIL] {symbol}: {e}")
        time.sleep(sleep_between)

    ib.disconnect()

    print("\n== Resumen ==")
    for name, added in updated:
        print(f"  {name:>10s}: +{added} filas")
    print(f"Total filas nuevas en BD: {total_added}")
    print("[OK] Precios actualizados en BD (market_data.db)")

    return 0


def add_instruments_to_db(
    symbols,
    host: str = "127.0.0.1",
    port: int = 7496,
    client_id: int = 43,
    min_days_fetch: int = 3650,  # deprecado: se ignora, ahora se trae historia completa
    bar_size: str = "1 day",
    what_to_show: str = "TRADES",
    use_rth: bool = True,
    sleep_between: float = 3.0,
    chunk: str = "5 Y",
    max_chunks: int = 15,
) -> int:
    """
    Descarga datos para nuevos símbolos desde IBKR y los inserta en la BD,
    trayendo la HISTORIA COMPLETA (desde la data más vieja disponible).

    IBKR limita cuánta historia entrega por request, así que se pide en bloques
    hacia atrás (endDateTime retrocediendo) hasta que deja de devolver barras
    nuevas = se llegó al inicio del activo. Los registros se ordenan por fecha
    ascendente y se insertan de una vez para mantener el orden cronológico.

    :param chunk: duración por request (ej. '5 Y', '10 Y').
    :param max_chunks: máximo de bloques hacia atrás por símbolo.
    """
    import time
    from typing import List, Tuple
    import pandas as pd

    try:
        from ib_insync import IB, Stock, util, BarData
    except Exception as e:
        print(f"[ERROR] ib_insync no está disponible: {e}")
        return 9

    try:
        try:
            from .db import insert_or_update_prices_batch
        except ImportError:
            from db import insert_or_update_prices_batch
    except Exception as e:
        print(f"[ERROR] No se pudo importar db local: {e}")
        return 10

    def build_contract(symbol: str) -> Stock:
        return Stock(symbol, "SMART", "USD")

    def bars_to_records(symbol: str, bars: List[BarData]) -> List[dict]:
        if not bars:
            return []
        rows = []
        for b in bars:
            dt = util.parseIBDatetime(b.date) if isinstance(b.date, str) else b.date
            d = pd.Timestamp(dt).tz_localize(None).date()
            rows.append({
                "symbol": symbol,
                "date": d.isoformat(),
                "open": float(b.open) if b.open else None,
                "high": float(b.high) if b.high else None,
                "low": float(b.low) if b.low else None,
                "close": float(b.close),
                "volume": int(b.volume) if b.volume else None,
                "adj_close": None,
            })
        df = pd.DataFrame(rows).drop_duplicates(subset=["date"]).sort_values("date")
        return df.to_dict("records")

    def fetch_full_history(ib: IB, contract: Stock, symbol: str) -> List[dict]:
        """Pide historia hacia atrás en bloques hasta agotar la data disponible."""
        all_records = {}
        cursor = pd.Timestamp.now().normalize()
        prev_earliest = cursor
        for i in range(max_chunks):
            end_str = cursor.strftime("%Y%m%d %H:%M:%S")
            try:
                bars = ib.reqHistoricalData(
                    contract,
                    endDateTime=end_str,
                    durationStr=chunk,
                    barSizeSetting=bar_size,
                    whatToShow=what_to_show,
                    useRTH=use_rth,
                    formatDate=1,
                    keepUpToDate=False,
                )
            except Exception as e:
                print(f"  [WARN] {symbol} bloque {i+1}: {e}")
                break
            if not bars:
                break
            recs = bars_to_records(symbol, bars)
            if not recs:
                break
            for r in recs:
                all_records[r["date"]] = r
            chunk_earliest = pd.to_datetime(recs[0]["date"])
            # Si no retrocedimos, ya no hay más historia disponible.
            if chunk_earliest >= prev_earliest:
                break
            prev_earliest = chunk_earliest
            cursor = chunk_earliest  # el próximo request termina aquí (solape 1 día -> upsert)
            ib.sleep(2.0)
        # Ordenar por fecha ascendente para mantener el orden cronológico en la tabla.
        return [all_records[d] for d in sorted(all_records)]

    def download_symbol(ib: IB, symbol: str) -> Tuple[str, int]:
        try:
            contract = build_contract(symbol)
            ib.qualifyContracts(contract)
            records = fetch_full_history(ib, contract, symbol)
            if not records:
                return symbol, 0
            insert_or_update_prices_batch(records)
            return symbol, len(records)
        except Exception as e:
            print(f"  [ERROR] {symbol}: {e}")
            return symbol, 0

    symbols = sorted({s.upper() for s in symbols if s})
    if not symbols:
        print("[ERROR] No se especificaron símbolos.")
        return 1

    print(f"== Agregando {len(symbols)} nuevos símbolos a la BD ==")
    ib = IB()
    try:
        ib.connect(host, port, clientId=client_id, readonly=True)
    except Exception as e:
        print(f"[ERROR] No se pudo conectar a IBKR: {e}")
        return 2

    total_added = 0
    added_log = []
    for symbol in symbols:
        t0 = time.time()
        name, added = download_symbol(ib, symbol)
        dt = time.time() - t0
        total_added += added
        added_log.append((name, added, dt))
        print(f"[OK] {name:>10s}: +{added:>4d} filas  ({dt:.2f}s)")
        time.sleep(sleep_between)

    ib.disconnect()
    print("\n== Resumen ==")
    for name, added, _ in added_log:
        print(f"  {name:>10s}: +{added} filas")
    print(f"Total filas nuevas en BD: {total_added}")
    return total_added


# Backward compatibility: mantener nombre antiguo
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
    """Función legacy que delega a update_ibkr_prices_to_db()."""
    return update_ibkr_prices_to_db(
        host=host,
        port=port,
        client_id=client_id,
        min_days_fetch=min_days_fetch,
        bar_size=bar_size,
        what_to_show=what_to_show,
        use_rth=use_rth,
        sleep_between=sleep_between,
    )


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Actualiza o agrega símbolos en la BD desde IBKR.")
    parser.add_argument("--add", nargs="+", help="Agregar nuevos símbolos a la BD desde IBKR")
    parser.add_argument("--min_days", type=int, default=3650, help="Días mínimos a descargar para nuevos símbolos")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=7496)
    parser.add_argument("--client_id", type=int, default=43)
    parser.add_argument("--sleep", type=float, default=3.0)

    args = parser.parse_args()
    if args.add:
        result = add_instruments_to_db(
            symbols=args.add,
            host=args.host,
            port=args.port,
            client_id=args.client_id,
            min_days_fetch=args.min_days,
            sleep_between=args.sleep,
        )
    else:
        result = update_ibkr_prices_to_db(
            host=args.host,
            port=args.port,
            client_id=args.client_id,
            min_days_fetch=args.min_days,
            sleep_between=args.sleep,
        )
    import sys
    sys.exit(0 if result >= 0 else 1)


if __name__ == "__main__":
    import sys
    sys.exit(update_ibkr_prices_to_db())
