# data_csv_live.py
import os
import pandas as pd
from typing import List, Dict
from qstrader.asset.equity import Equity
from qstrader.asset.universe.dynamic import DynamicUniverse
from qstrader.data.backtest_data_handler import BacktestDataHandler
from qstrader.data.daily_bar_csv import CSVDailyBarDataSource

class CSVLiveDataEnv:
    """
    Entorno que:
      - monta un DataHandler con CSVs para que MomentumSignal funcione,
      - entrega últimos cierres para marcar el portafolio.
    """
    def __init__(self, csv_dir: str, assets: List[str]):
        self.csv_dir = csv_dir
        self.assets = assets
        self.symbols = [a.replace('EQ:', '') for a in assets]

    def build_data_handler(self, universe: DynamicUniverse):
        data_source = CSVDailyBarDataSource(
            self.csv_dir, Equity, csv_symbols=self.symbols, adjust_prices=False
        )
        return BacktestDataHandler(universe, data_sources=[data_source])

    def get_latest_close(self) -> Dict[str, float]:
        px = {}
        for sym in self.symbols:
            path = os.path.join(self.csv_dir, f"{sym}.csv")
            if not os.path.exists(path):
                continue
            df = pd.read_csv(path)
            # Asume columna 'Close' o 'Adj Close'; ajusta si es necesario
            if 'Close' in df.columns:
                last = float(df['Close'].iloc[-1])
            elif 'Adj Close' in df.columns:
                last = float(df['Adj Close'].iloc[-1])
            else:
                continue
            px[f"EQ:{sym}"] = last
        return px
