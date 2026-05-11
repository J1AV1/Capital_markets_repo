"""
Agrega nuevos instrumentos a la BD SQLite desde IBKR.

Uso:
    python add_instruments_to_db.py --symbols AAPL TSLA
"""
import argparse
from update_data import add_instruments_to_db


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Agrega instrumentos a market_data.db desde IBKR."
    )
    parser.add_argument("--symbols", nargs="+", required=True, help="Lista de símbolos a cargar")
    parser.add_argument("--min_days", type=int, default=3650, help="Días mínimos a descargar para nuevos símbolos")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=7496)
    parser.add_argument("--client_id", type=int, default=43)
    parser.add_argument("--sleep", type=float, default=3.0)

    args = parser.parse_args()

    total = add_instruments_to_db(
        symbols=args.symbols,
        host=args.host,
        port=args.port,
        client_id=args.client_id,
        min_days_fetch=args.min_days,
        sleep_between=args.sleep,
    )

    print(f"\n✅ Proceso completado. Total de filas procesadas: {total}")

