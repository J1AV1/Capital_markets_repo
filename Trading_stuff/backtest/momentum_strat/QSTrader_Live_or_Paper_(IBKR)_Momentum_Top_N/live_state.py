# live_state.py
import os
import json
import pandas as pd
from datetime import datetime
from typing import Dict, List, Any

class LiveState:
    def __init__(self, log_dir: str):
        self.log_dir = log_dir
        os.makedirs(self.log_dir, exist_ok=True)
        self.snap_path = os.path.join(self.log_dir, 'daily_snapshot.csv')
        self.orders_path = os.path.join(self.log_dir, 'orders_log.csv')
        self.equity_path = os.path.join(self.log_dir, 'equity_curve.csv')

        # Crea archivos si no existen
        if not os.path.exists(self.snap_path):
            pd.DataFrame(columns=[
                'datetime','target_weights','positions','prices','cash','portfolio_value'
            ]).to_csv(self.snap_path, index=False)
        if not os.path.exists(self.orders_path):
            pd.DataFrame(columns=[
                'datetime','orders_json'
            ]).to_csv(self.orders_path, index=False)
        if not os.path.exists(self.equity_path):
            pd.DataFrame(columns=[
                'datetime','equity'
            ]).to_csv(self.equity_path, index=False)

    def log_snapshot(self, when: datetime, target_w: Dict[str,float],
                     positions: Dict[str,float], prices: Dict[str,float],
                     cash: float, pv: float):
        row = {
            'datetime': when.isoformat(),
            'target_weights': json.dumps(target_w),
            'positions': json.dumps(positions),
            'prices': json.dumps(prices),
            'cash': cash,
            'portfolio_value': pv
        }
        df = pd.DataFrame([row])
        df.to_csv(self.snap_path, mode='a', header=False, index=False)

    def log_orders(self, when: datetime, orders: List[dict]):
        row = {'datetime': when.isoformat(), 'orders_json': json.dumps(orders)}
        pd.DataFrame([row]).to_csv(self.orders_path, mode='a', header=False, index=False)

    def log_equity(self, when: datetime, equity: float):
        row = {'datetime': when.isoformat(), 'equity': equity}
        pd.DataFrame([row]).to_csv(self.equity_path, mode='a', header=False, index=False)