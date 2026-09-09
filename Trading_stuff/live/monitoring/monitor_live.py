"""
Monitoreo de la ejecucion LIVE - Estrategia 4 (cuenta REAL, solo lectura).

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
sys.path.insert(0, os.path.join(_HERE, ".."))            # config_live
sys.path.insert(0, os.path.join(_HERE, "..", "execution"))  # broker_ibkr, flex_nav
sys.path.insert(0, os.path.join(_HERE, "..", "..", "backtest"))  # Utils_function_backtest
import config_live as cfg  # noqa: E402

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import db  # noqa: E402
import Utils_function_backtest as utils  # noqa: E402


def _load_last_run():
    if not os.path.exists(cfg.LAST_RUN_JSON):
        return None
    with open(cfg.LAST_RUN_JSON, "r", encoding="utf-8") as f:
        return json.load(f)


def _stats_from_series(nav, flows=None):
    """
    Calcula el bloque de retornos desde una serie de NAV (indexada por fecha) y,
    opcionalmente, una lista de flujos [(fecha, monto)] (deposito>0, retiro<0).

    Todo se calcula TIME-WEIGHTED (neteando el flujo de cada dia, eod), asi que las
    metricas no se contaminan por aportes/retiros. El MWR (TIR/xirr) se calcula
    ademas si hay flujos, para comparar contra el TWR.
    """
    nav = pd.Series(nav).sort_index()
    nav = nav[~nav.index.duplicated(keep="last")]
    if len(nav) < 2:
        return {"nav": float(nav.iloc[-1]), "points": len(nav)} if len(nav) else None

    # Flujos alineados a las fechas de NAV (para el ajuste diario del TWR).
    flows = list(flows) if flows else []
    if flows:
        f_raw = pd.Series({pd.Timestamp(d): float(a) for d, a in flows})
        f_raw = f_raw.groupby(level=0).sum()
        f = f_raw.reindex(nav.index).fillna(0.0)
    else:
        f = pd.Series(0.0, index=nav.index)
    has_flows = bool((f != 0).any())

    # Retorno diario time-weighted: r_t = (NAV_t - flujo_t) / NAV_{t-1} - 1  (eod)
    prev = nav.shift(1)
    r = ((nav - f) / prev - 1.0).replace([np.inf, -np.inf], np.nan).dropna()
    if len(r) == 0:
        return {"nav": float(nav.iloc[-1]), "points": len(nav)}

    equity = (1.0 + r).cumprod()
    total = float(equity.iloc[-1] - 1.0)
    dd = equity / equity.cummax() - 1.0
    max_dd = float(dd.min())
    vol_ann = float(r.std() * np.sqrt(256)) if len(r) > 1 else float("nan")

    # YTD time-weighted: producto de los retornos del ano en curso.
    year = nav.index[-1].year
    r_ytd = r[r.index >= pd.Timestamp(year, 1, 1)]
    ytd = float((1.0 + r_ytd).prod() - 1.0) if len(r_ytd) else float("nan")

    # Anualizado TWR (CAGR por dias calendario del periodo).
    days = (nav.index[-1] - nav.index[0]).days
    years = days / 365.25 if days > 0 else float("nan")
    ann_twr = float((1.0 + total) ** (1.0 / years) - 1.0) if years and years > 0 and total > -1 else float("nan")

    # MWR (money-weighted / TIR) solo si hubo aportes/retiros.
    mwr = float("nan")
    if has_flows:
        cfs = [(nav.index[0], -float(nav.iloc[0]))]              # inversion inicial = salida
        for d, amt in f_raw[f_raw != 0].items():
            cfs.append((d, -float(amt)))                          # deposito>0 -> salida negativa
        cfs.append((nav.index[-1], float(nav.iloc[-1])))         # NAV final = entrada
        mwr = utils.xirr(cfs)

    return {
        "nav": float(nav.iloc[-1]), "start_nav": float(nav.iloc[0]),
        "total_ret": total, "ytd": ytd, "ann_twr": ann_twr, "mwr": mwr,
        "max_dd": max_dd, "vol_ann": vol_ann, "points": len(nav),
        "has_flows": has_flows, "n_flows": int((f != 0).sum()),
    }


def _nav_stats():
    """Fallback local: retornos desde nav_history.csv (sin flujos)."""
    if not os.path.exists(cfg.NAV_HISTORY_CSV):
        return None
    # keep="last": si hubo varias corridas el mismo dia, usar el NAV mas reciente.
    nav = (pd.read_csv(cfg.NAV_HISTORY_CSV, parse_dates=["date"])
           .drop_duplicates("date", keep="last").set_index("date")["nav"])
    return _stats_from_series(nav, flows=None)


def _flex_stats():
    """Retornos desde el Flex (serie NAV diaria + depositos/retiros). None si falla."""
    if not (getattr(cfg, "FLEX_TOKEN", None) and getattr(cfg, "FLEX_QUERY_ID", None)):
        return None
    from flex_nav import flex_report
    rep = flex_report(account=getattr(cfg, "IB_ACCOUNT", None))
    series = rep.get("nav_series") or []
    if len(series) < 2:
        return None
    nav = pd.Series({pd.Timestamp(d): v for d, v in series})
    return _stats_from_series(nav, flows=rep.get("flows"))


def main():
    parser = argparse.ArgumentParser(description="Monitoreo LIVE Estrategia 4 (cuenta REAL).")
    parser.add_argument("--no-broker", action="store_true", help="No conectar al broker.")
    parser.add_argument("--no-flex", action="store_true",
                        help="No consultar el Flex; usar nav_history.csv local (sin flujos).")
    args = parser.parse_args()

    print(f"=== MONITOR LIVE Estrategia 4 | {dt.datetime.now():%Y-%m-%d %H:%M:%S} ===\n")

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

    # --- Broker: NAV en vivo + posiciones (una sola conexion) ---
    current = None      # None = no conectado ; {} = conectado, cuenta vacia
    live_nav = None
    if not args.no_broker:
        try:
            from broker_ibkr import DemoBroker
            with DemoBroker(readonly=True) as broker:
                live_nav = broker.net_liquidation()
                current = broker.positions()
        except Exception as e:
            print(f"[broker] no se pudo conectar: {e}")

    # --- NAV / retornos ---
    # Fuente preferida: Flex (serie NAV diaria + depositos/retiros -> TWR y MWR).
    # Fallback: nav_history.csv local (sin flujos: TWR = MWR).
    ns, ret_src = None, None
    if not args.no_flex:
        try:
            ns = _flex_stats()
            if ns:
                ret_src = "flex"
        except Exception as e:
            print(f"[flex]   no se pudo obtener la serie NAV/flujos: {e}")
    if ns is None:
        ns = _nav_stats()
        ret_src = "hist"

    display_nav = live_nav if live_nav is not None else (ns["nav"] if ns else None)
    src = "live" if live_nav is not None else (ret_src or "-")
    if display_nav is None:
        print("[nav]    sin NAV disponible")
    elif ns and "total_ret" in ns:
        print(f"[nav]    NAV={display_nav:,.2f} ({src})  "
              f"maxDD={ns['max_dd']:+.2%}  vol_ann~{ns['vol_ann']:.1%} (target {cfg.TARGET_RISK:.0%})  "
              f"({ns['points']} dias, ret:{ret_src})")
        print(f"[ret]    YTD={ns['ytd']:+.2%}  |  total={ns['total_ret']:+.2%}  (time-weighted)")
        if ns.get("has_flows"):
            print(f"[ann]    anualizado -> TWR {ns['ann_twr']:+.2%}  |  MWR/TIR {ns['mwr']:+.2%}  "
                  f"({ns['n_flows']} flujos)")
            print("         (TWR: asume que no hubo aportes/retiros ; "
                  "MWR: considera aportes y retiros)")
        else:
            print(f"[ann]    anualizado {ns['ann_twr']:+.2%}  "
                  "(sin aportes/retiros: time = money weighted)")
    else:
        print(f"[nav]    NAV={display_nav:,.2f} ({src})")

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
