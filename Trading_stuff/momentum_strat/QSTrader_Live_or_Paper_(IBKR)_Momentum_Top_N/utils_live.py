# utils_live.py
import pandas as pd
from datetime import datetime
from typing import Dict, List
from live_config import REBALANCE, TZ_MARKET, BROKER_SYMBOL_MAP

def is_rebalance_day(now_utc: datetime) -> bool:
    if REBALANCE == 'daily':
        return True
    if REBALANCE == 'weekly':
        # viernes
        return pd.Timestamp(now_utc).tz_convert(TZ_MARKET).weekday() == 4
    if REBALANCE == 'end_of_month':
        ts = pd.Timestamp(now_utc).tz_convert(TZ_MARKET)
        next_bus = ts + pd.tseries.offsets.BusinessDay(1)
        return ts.month != next_bus.month
    return False

def weights_to_orders(target_w, prices, positions, cash, portfolio_value, cash_buffer):
    investable = portfolio_value * (1.0 - cash_buffer)
    orders = []
    # target > 0
    for asset, w in target_w.items():
        px = prices.get(asset)
        if px is None or px <= 0:
            continue
        target_value = investable * w
        tgt_qty = int(target_value // px)
        cur_qty = int(positions.get(asset, 0))
        diff = tgt_qty - cur_qty
        if diff == 0:
            continue
        orders.append({
            'symbol': asset,              # *** 'EQ:...' ***
            'qty': abs(diff),
            'side': 'buy' if diff > 0 else 'sell',
            'type': 'market',
            'time_in_force': 'day'
        })
    # liquidaciones (w=0 con pos > 0)
    for asset, cur_qty in positions.items():
        if target_w.get(asset, 0.0) == 0.0 and cur_qty != 0:
            orders.append({
                'symbol': asset,          # *** 'EQ:...' ***
                'qty': abs(int(cur_qty)),
                'side': 'sell',
                'type': 'market',
                'time_in_force': 'day'
            })
    return orders