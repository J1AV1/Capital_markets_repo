"""
Agrega nuevos instrumentos a la BD SQLite desde IBKR, trayendo la historia
completa (desde la data más vieja disponible).

Uso:
    python add_instruments_to_db.py --symbols AAPL TSLA
    python add_instruments_to_db.py --symbols AAPL --port 7497   # cuenta paper
"""
import argparse
from update_data import add_instruments_to_db


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Agrega instrumentos a market_data.db desde IBKR (historia completa)."
    )
    parser.add_argument("--symbols", nargs="+", required=True, help="Lista de símbolos a cargar")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=7496, help="7496 live / 7497 paper / 4001 gateway")
    parser.add_argument("--client_id", type=int, default=43)
    parser.add_argument("--sleep", type=float, default=3.0)
    parser.add_argument("--chunk", default="5 Y", help="Duración por request (ej. '5 Y', '10 Y')")
    parser.add_argument("--max_chunks", type=int, default=15, help="Máximo de bloques hacia atrás por símbolo")

    args = parser.parse_args()

    total = add_instruments_to_db(
        symbols=args.symbols,
        host=args.host,
        port=args.port,
        client_id=args.client_id,
        sleep_between=args.sleep,
        chunk=args.chunk,
        max_chunks=args.max_chunks,
    )

    print(f"\n[OK] Proceso completado. Total de filas procesadas: {total}")

