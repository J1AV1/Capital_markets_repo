"""
Monitoreo de la ejecucion DEMO - Estrategia 4.

Muestra un snapshot del estado del sistema:
  - Posiciones objetivo (ultimo run) vs posiciones reales del broker + desvio.
  - NAV y P&L (desde el inicio del historial de NAV) y drawdown.
  - Volatilidad realizada rolling vs el target.
  - Health checks: frescura de la data, ultima corrida, conexion.

Uso:
  python monitor_demo.py            # snapshot en consola
  python monitor_demo.py --no-broker  # sin conectar al broker (usa el ultimo estado)
"""
import os
import sys
import json
import argparse
import datetime as dt

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, ".."))            # config_demo
sys.path.insert(0, os.path.join(_HERE, "..", "execution"))  # broker_ibkr
import config_demo as cfg  # noqa: E402

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import db  # noqa: E402


def _load_last_run():
    if not os.path.exists(cfg.LAST_RUN_JSON):
        return None
    with open(cfg.LAST_RUN_JSON, "r", encoding="utf-8") as f:
        return json.load(f)


def _nav_stats():
    if not os.path.exists(cfg.NAV_HISTORY_CSV):
        return None
    nav = pd.read_csv(cfg.NAV_HISTORY_CSV, parse_dates=["date"]).drop_duplicates("date").set_index("date")["nav"]
    if len(nav) < 2:
        return {"nav": float(nav.iloc[-1]), "points": len(nav)}
    ret = nav.pct_change().dropna()
    cum = nav / nav.iloc[0] - 1
    dd = nav / nav.cummax() - 1
    vol_ann = ret.std() * np.sqrt(256) if len(ret) > 1 else float("nan")
    return {
        "nav": float(nav.iloc[-1]), "start_nav": float(nav.iloc[0]),
        "total_ret": float(cum.iloc[-1]), "max_dd": float(dd.min()),
        "vol_ann": float(vol_ann), "points": len(nav),
    }


def main():
    parser = argparse.ArgumentParser(description="Monitoreo demo Estrategia 4.")
    parser.add_argument("--no-broker", action="store_true", help="No conectar al broker.")
    args = parser.parse_args()

    print(f"=== MONITOR DEMO Estrategia 4 | {dt.datetime.now():%Y-%m-%d %H:%M:%S} ===\n")

    # --- Health: data ---
    latest = db.get_latest_data_date(ignore_symbols=["ALL"])
    if latest:
        bdays = len(pd.bdate_range(pd.to_datetime(latest), pd.Timestamp.now().normalize())) - 1
        flag = "OK" if bdays <= cfg.MAX_DATA_STALE_DAYS else "STALE"
        print(f"[data]   ultima barra BD: {latest} ({bdays} dias habiles)  [{flag}]")
    else:
        print("[data]   BD sin datos")

    # --- Ultimo run ---
    last = _load_last_run()
    if last:
        print(f"[run]    ultima corrida: {last['timestamp']}  dry_run={last['dry_run']}  "
              f"ordenes={len(last.get('orders', []))}")
    else:
        print("[run]    sin corridas registradas todavia")

    # --- NAV / P&L ---
    ns = _nav_stats()
    if ns and "total_ret" in ns:
        print(f"[nav]    NAV={ns['nav']:,.2f}  ret_total={ns['total_ret']:+.2%}  "
              f"maxDD={ns['max_dd']:+.2%}  vol_ann~{ns['vol_ann']:.1%} (target {cfg.TARGET_RISK:.0%})  "
              f"({ns['points']} dias)")
    elif ns:
        print(f"[nav]    NAV={ns['nav']:,.2f}  ({ns['points']} dia de historial)")

    # --- Objetivo vs real ---
    current = None  # None = no conectado ; {} = conectado, cuenta vacia
    if not args.no_broker:
        try:
            from broker_ibkr import DemoBroker
            with DemoBroker(readonly=True) as broker:
                current = broker.positions()
        except Exception as e:
            print(f"[broker] no se pudo conectar: {e}")

    if last and last.get("targets"):
        print(f"\n{'sym':6s} {'objetivo':>10s} {'real':>10s} {'desvio':>10s} {'en banda':>9s}")
        for sym, t in last["targets"].items():
            tgt = t["optimal"]
            if current is None:
                print(f"{sym:6s} {tgt:>10.3f} {'-':>10s} {'-':>10s} {'':>9s}")
                continue
            cur = float(current.get(sym, 0.0))
            dev = cur - tgt
            in_band = "si" if t["lower"] <= cur <= t["upper"] else "NO"
            print(f"{sym:6s} {tgt:>10.3f} {cur:>10.3f} {dev:>+10.3f} {in_band:>9s}")

    print()


if __name__ == "__main__":
    main()
