# live_runner_ibkr.py
import os
import pytz
from datetime import datetime
import pandas as pd

from live_config import (
    ASSETS, CSV_DIR, CASH_BUFFER, MOM_LOOKBACK, MOM_TOP_N,
    IBKR_HOST, IBKR_PORT, IBKR_CLIENT_ID, LOG_DIR
)
from broker_ibkr import IBKRBroker
from data_live_csv import CSVLiveDataEnv
from live_state import LiveState
from utils_live import is_rebalance_day, weights_to_orders

from qstrader.asset.universe.dynamic import DynamicUniverse
from qstrader.signals.momentum import MomentumSignal
from qstrader.signals.signals_collection import SignalsCollection
from momentum_taa import TopNMomentumAlphaModel  # tu AlphaModel

def build_alpha(universe, data_handler, mom_lookback, mom_top_n):
    # start_dt puede ser antiguo; el DataHandler limitará por CSVs
    momentum = MomentumSignal(pd.Timestamp('2000-01-01', tz=pytz.UTC), universe, lookbacks=[mom_lookback])
    signals = SignalsCollection({'momentum': momentum}, data_handler)
    alpha = TopNMomentumAlphaModel(signals, mom_lookback, mom_top_n, universe, data_handler)
    return signals, alpha

def main():
    now = datetime.now(pytz.UTC)
    # 1) ¿Hoy hay rebalance?
    if not is_rebalance_day(now):
        print("No es día de rebalance. Saliendo.")
        return

    # 2) Entorno de datos (CSV) y universo
    data_env = CSVLiveDataEnv(CSV_DIR, ASSETS)
    asset_dates = {a: pd.Timestamp('2000-01-01', tz=pytz.UTC) for a in ASSETS}
    universe = DynamicUniverse(asset_dates)
    data_handler = data_env.build_data_handler(universe)

    # 3) Alpha
    signals, alpha = build_alpha(universe, data_handler, MOM_LOOKBACK, MOM_TOP_N)

    # 4) Broker (IBKR)
    broker = IBKRBroker(IBKR_HOST, IBKR_PORT, IBKR_CLIENT_ID, paper=True)

    # 5) Estado actual
    positions = broker.get_positions()                    # {'EQ:NVDA': 10, ...}
    prices = data_env.get_latest_close()                  # {'EQ:NVDA': 129.3, ...}
    cash = broker.get_cash()
    pv = cash + sum(positions.get(a,0)*prices.get(a,0) for a in ASSETS)

    # 6) Pesos objetivo (hoy)
    dt = pd.Timestamp(now)
    target_w = alpha(dt)  # dict {'EQ:XXX': weight, ...}

    # 7) Órdenes
    orders = weights_to_orders(target_w, prices, positions, cash, pv, CASH_BUFFER)

    # 8) Logs + ejecución
    state = LiveState(LOG_DIR)
    state.log_snapshot(now, target_w, positions, prices, cash, pv)

    if orders:
        # Enviar y obtener fills enriquecidos
        executed_orders = broker.place_orders(orders)

        # Log gear: guarda exactamente lo ejecutado (con VWAP y filled_qty)
        state.log_orders(now, executed_orders)
        print("Órdenes ejecutadas:", executed_orders)

        # Refresca estado tras fills para equity
        positions_after = broker.get_positions()
        prices_after = prices  # si quieres, vuelve a leer; EOD no cambia
        cash_after = broker.get_cash()
        pv_after = cash_after + sum(positions_after.get(a,0)*prices_after.get(a,0) for a in ASSETS)

        # 9) Log de equity post-trade
        state.log_equity(now, pv_after)
    else:
        print("No hay órdenes que enviar.")
        # Aun así registra equity del día
        state.log_equity(now, pv)

if __name__ == "__main__":
    main()
