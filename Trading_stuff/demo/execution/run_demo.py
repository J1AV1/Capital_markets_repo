"""
Orquestador diario de la ejecucion DEMO - Estrategia 4 (VolTarget Portfolio).

Flujo:
  1. (opcional) actualizar precios de la BD a t-1 desde IBKR.
  2. verificar frescura de la data.
  3. conectar al broker demo y leer NAV (o usar capital fijo).
  4. calcular posiciones objetivo de hoy (signals_strat4).
  5. leer posiciones actuales del broker.
  6. reconciliar con la banda de no-negociacion -> ordenes.
  7. chequeos de seguridad + colocar ordenes (dry-run por defecto).
  8. persistir estado y log.

Uso:
  python run_demo.py                # dry-run (imprime, no envia)
  python run_demo.py --execute      # envia ordenes a la cuenta demo
  python run_demo.py --no-update    # no refresca la BD
"""
import os
import sys
import json
import argparse
import datetime as dt

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, ".."))
import config_demo as cfg  # noqa: E402

import pandas as pd  # noqa: E402
import db  # noqa: E402
import signals_strat4 as signals  # noqa: E402
from broker_ibkr import DemoBroker  # noqa: E402


def _log(msg, lines):
    print(msg)
    lines.append(msg)


def _ensure_dirs():
    os.makedirs(cfg.STATE_DIR, exist_ok=True)
    os.makedirs(cfg.LOG_DIR, exist_ok=True)


def _check_data_freshness(lines):
    latest = db.get_latest_data_date(ignore_symbols=["ALL"])
    if latest is None:
        raise RuntimeError("La BD no tiene datos.")
    latest_ts = pd.to_datetime(latest).normalize()
    today = pd.Timestamp.now().normalize()
    bdays = len(pd.bdate_range(latest_ts, today)) - 1
    _log(f"Ultima barra en BD: {latest}  ({bdays} dias habiles atras)", lines)
    if bdays > cfg.MAX_DATA_STALE_DAYS:
        raise RuntimeError(f"Data desactualizada ({bdays} dias > {cfg.MAX_DATA_STALE_DAYS}). Aborto.")
    return latest


def main():
    parser = argparse.ArgumentParser(description="Ejecucion demo Estrategia 4 (VolTarget Portfolio).")
    parser.add_argument("--execute", action="store_true", help="Enviar ordenes (desactiva dry-run).")
    parser.add_argument("--no-update", action="store_true", help="No refrescar la BD antes de correr.")
    args = parser.parse_args()

    dry_run = cfg.DRY_RUN and not args.execute
    lines = []
    _ensure_dirs()
    _log(f"=== RUN DEMO Estrategia 4 | {dt.datetime.now():%Y-%m-%d %H:%M:%S} | dry_run={dry_run} ===", lines)

    # 1. Actualizar data a t-1
    if not args.no_update:
        try:
            import update_data
            _log("Actualizando precios a t-1...", lines)
            update_data.update_ibkr_prices_to_db(
                host=cfg.IB_HOST, port=cfg.IB_PORT, client_id=cfg.IB_CLIENT_ID + 1
            )
        except Exception as e:
            _log(f"[WARN] no se pudo actualizar la data: {e}", lines)

    # 2. Frescura
    _check_data_freshness(lines)

    # 3. Broker + NAV
    broker = DemoBroker(readonly=False).connect()
    try:
        if cfg.CAPITAL_SOURCE == "nav":
            capital = broker.net_liquidation()
            _log(f"NAV cuenta demo ({broker.account}): {capital:,.2f}", lines)
        else:
            capital = cfg.FIXED_CAPITAL
            _log(f"Capital fijo (config): {capital:,.2f}", lines)
        if capital <= 0:
            raise RuntimeError("Capital <= 0, aborto.")

        # 4. Objetivos
        targets, meta = signals.compute_targets(capital)
        _log(f"IDM={meta['idm']:.3f} | objetivos para {len(targets)} instrumentos", lines)
        lev_b, lev_a = meta["leverage_before"], meta["leverage_after"]
        if meta["leverage_scale"] < 1.0:
            _log(f"Apalancamiento: {lev_b:.2f}x pedido -> escalado a {lev_a:.2f}x "
                 f"(tope {cfg.MAX_LEVERAGE:.2f}x, factor {meta['leverage_scale']:.3f}) | "
                 f"exposicion bruta ${meta['gross_after']:,.0f} de ${capital:,.0f}", lines)
        else:
            _log(f"Apalancamiento: {lev_a:.2f}x | exposicion bruta ${meta['gross_after']:,.0f} "
                 f"de ${capital:,.0f}", lines)

        # 5. Posiciones actuales
        current = broker.positions()

        max_order_value = cfg.MAX_ORDER_PCT_NAV * capital

        # 6-7. Reconciliar + ordenes
        _log(f"\n{'sym':6s} {'actual':>10s} {'banda':>20s} {'objetivo':>10s} {'orden':>10s}", lines)
        orders = []
        for sym, t in targets.items():
            cur = float(current.get(sym, 0.0))
            lo, up, price = t["lower"], t["upper"], t["price"]
            if cur < lo:
                new = lo
            elif cur > up:
                new = up
            else:
                new = cur
            qty = new - cur
            band = f"[{lo:.2f},{up:.2f}]"
            _log(f"{sym:6s} {cur:>10.3f} {band:>20s} {new:>10.3f} {qty:>+10.3f}", lines)

            value = abs(qty) * price
            if value < cfg.MIN_ORDER_VALUE:
                continue
            if value > max_order_value:
                _log(f"  [BLOCK] {sym}: orden de ${value:,.0f} supera el tope ${max_order_value:,.0f} "
                     f"({cfg.MAX_ORDER_PCT_NAV:.0%} del NAV)", lines)
                continue
            res = broker.place_order(sym, qty, dry_run=dry_run, ref_price=price)
            orders.append(res)
            _log(f"  -> {res['action']} {res['qty']} {sym} @~{price:.2f}  [{res['status']}]", lines)

        # 8. Persistir estado
        state = {
            "timestamp": dt.datetime.now().isoformat(timespec="seconds"),
            "dry_run": dry_run, "capital": capital, "idm": meta["idm"],
            "weights": meta["weights"], "targets": targets,
            "current_positions": current, "orders": orders,
        }
        with open(cfg.LAST_RUN_JSON, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, default=str)

        nav_row = pd.DataFrame([{"date": dt.date.today().isoformat(), "nav": capital}])
        if os.path.exists(cfg.NAV_HISTORY_CSV):
            nav_row.to_csv(cfg.NAV_HISTORY_CSV, mode="a", header=False, index=False)
        else:
            nav_row.to_csv(cfg.NAV_HISTORY_CSV, index=False)

        _log(f"\nOrdenes generadas: {len(orders)} | estado -> {cfg.LAST_RUN_JSON}", lines)
    finally:
        broker.disconnect()

    logfile = os.path.join(cfg.LOG_DIR, f"run_{dt.date.today():%Y%m%d}.log")
    with open(logfile, "a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
