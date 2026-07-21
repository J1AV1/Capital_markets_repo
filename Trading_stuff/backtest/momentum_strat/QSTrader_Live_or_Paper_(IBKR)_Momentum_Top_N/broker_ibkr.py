# broker_ibkr.py
from typing import Dict, List
from ib_insync import IB, Stock, MarketOrder, util
from live_config import BROKER_SYMBOL_MAP

class IBKRBroker:
    def __init__(self, host: str, port: int, client_id: int, paper: bool = True):
        self.ib = IB()
        self.ib.connect(host, port, clientId=client_id, readonly=False)
        self.paper = paper
        self.wait_fill_seconds = 10.0  # configurable

    def _ib_symbol_from_asset(self, asset: str) -> str:
        # 'EQ:BRK-B' -> 'BRK B', 'EQ:NVDA'->'NVDA'
        return BROKER_SYMBOL_MAP.get(asset, asset.replace('EQ:', ''))

    def _stock_contract(self, asset: str) -> Stock:
        """
        Recibe 'EQ:TICKER' y construye el contrato IBKR (Stock SMART USD).
        """
        ib_symbol = self._ib_symbol_from_asset(asset)
        contract = Stock(ib_symbol, 'SMART', 'USD')
        self.ib.qualifyContracts(contract)
        return contract

    def get_positions(self) -> Dict[str, float]:
        pos = {}
        for p in self.ib.positions():
            sym = p.contract.symbol
            # Normaliza simetría con tus assets internos
            if sym == 'BRK B':
                asset = 'EQ:BRK-B'
            else:
                asset = f"EQ:{sym}"
            pos[asset] = pos.get(asset, 0.0) + float(p.position)
        return pos

    def get_cash(self) -> float:
        for v in self.ib.accountValues():
            if v.tag == 'AvailableFunds' and v.currency == 'USD':
                try:
                    return float(v.value)
                except Exception:
                    pass
        return 0.0

    def place_orders(self, orders: List[dict]) -> List[dict]:
        """
        Envía órdenes y devuelve una lista de órdenes enriquecidas con:
        - 'filled_qty': cantidad ejecutada (suma de fills)
        - 'fill_price': VWAP de ejecución
        Mantiene 'symbol' en el formato interno 'EQ:...'
        """
        executed: List[dict] = []
        for o in orders:
            # Asegura formato interno
            asset = o['symbol'] if str(o['symbol']).startswith('EQ:') else f"EQ:{o['symbol']}"
            contract = self._stock_contract(asset)

            qty = int(o['qty'])
            side = str(o['side']).lower()
            if qty <= 0 or side not in ('buy', 'sell'):
                continue

            action = 'BUY' if side == 'buy' else 'SELL'
            order = MarketOrder(action, qty)
            trade = self.ib.placeOrder(contract, order)

            # Espera breve y luego polling hasta done o timeout
            self.ib.sleep(0.25)
            deadline = util.time.time() + getattr(self, 'wait_fill_seconds', 10.0)
            while util.time.time() < deadline and not trade.isDone():
                self.ib.waitOnUpdate(timeout=1.0)

            filled_qty = 0
            fill_price = None
            if trade.fills:
                v_qty = 0
                v_sum = 0.0
                for f in trade.fills:
                    shares = abs(int(f.execution.shares))
                    price = float(f.execution.price)
                    v_qty += shares
                    v_sum += shares * price
                if v_qty > 0:
                    filled_qty = v_qty
                    fill_price = v_sum / v_qty

            enriched = dict(o)  # conserva tus campos originales
            enriched['symbol'] = asset  # normalizado
            enriched['filled_qty'] = filled_qty if filled_qty else qty  # fallback
            if fill_price is not None:
                enriched['fill_price'] = fill_price

            executed.append(enriched)

        return executed
