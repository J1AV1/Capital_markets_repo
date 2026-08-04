"""
Adaptador IBKR para la ejecucion demo (via ib_insync).

Responsabilidades:
  - Conectar a TWS/Gateway (paper por defecto).
  - Leer NAV (NetLiquidation) y posiciones actuales.
  - Colocar ordenes de mercado (fraccionales) con soporte de dry-run.

No contiene logica de estrategia: solo habla con el broker.
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, ".."))  # para importar config_demo
import config_demo as cfg  # noqa: E402

try:
    from ib_insync import IB, Stock, MarketOrder
except Exception as e:  # pragma: no cover
    raise ImportError(f"ib_insync no disponible: {e}")


class DemoBroker:
    def __init__(self, host=None, port=None, client_id=None, account=None, readonly=False):
        self.host = host or cfg.IB_HOST
        self.port = port or cfg.IB_PORT
        self.client_id = client_id or cfg.IB_CLIENT_ID
        self.account = account if account is not None else cfg.IB_ACCOUNT
        self.readonly = readonly
        self.ib = IB()

    def connect(self):
        self.ib.connect(self.host, self.port, clientId=self.client_id, readonly=self.readonly)
        if self.account is None:
            accts = self.ib.managedAccounts()
            self.account = accts[0] if accts else None
        return self

    def disconnect(self):
        if self.ib.isConnected():
            self.ib.disconnect()

    def __enter__(self):
        return self.connect()

    def __exit__(self, exc_type, exc, tb):
        self.disconnect()

    # ---- Lectura ----
    def net_liquidation(self):
        """NAV (NetLiquidation) de la cuenta en USD."""
        vals = self.ib.accountValues(self.account) if self.account else self.ib.accountValues()
        for v in vals:
            if v.tag == "NetLiquidation" and v.currency in ("USD", "BASE"):
                return float(v.value)
        # fallback: cualquier NetLiquidation
        for v in vals:
            if v.tag == "NetLiquidation":
                return float(v.value)
        raise RuntimeError("No se pudo leer NetLiquidation de la cuenta.")

    def previous_day_nav(self):
        """
        Balance (equity) al cierre del dia anterior: PreviousDayEquityWithLoanValue
        de IBKR (valorado a las 16:00 ET del dia previo). None si no esta disponible.
        Para una cuenta de solo acciones sin prestamo equivale al NAV de ayer al cierre.

        Este tag NO viene en accountValues(); se obtiene de accountSummary(), que
        pide explicitamente ese set de tags. Se deja accountValues como fallback.
        """
        tag = "PreviousDayEquityWithLoanValue"

        # 1) accountSummary (fuente correcta para este tag)
        try:
            summ = self.ib.accountSummary(self.account) if self.account else self.ib.accountSummary()
            for v in summ:
                if v.tag == tag:
                    val = float(v.value)
                    if val > 0:
                        return val
        except Exception:
            pass

        # 2) fallback: accountValues
        vals = self.ib.accountValues(self.account) if self.account else self.ib.accountValues()
        for v in vals:
            if v.tag == tag:
                val = float(v.value)
                if val > 0:
                    return val
        return None

    def positions(self):
        """dict {symbol: cantidad} de las posiciones actuales (acciones)."""
        out = {}
        for p in self.ib.positions(self.account) if self.account else self.ib.positions():
            c = p.contract
            if c.secType == "STK":
                out[c.symbol] = out.get(c.symbol, 0.0) + float(p.position)
        return out

    def last_price(self, symbol):
        """Ultimo precio disponible (delayed OK en paper)."""
        contract = Stock(symbol, "SMART", "USD")
        self.ib.qualifyContracts(contract)
        self.ib.reqMarketDataType(3)  # delayed si no hay suscripcion en vivo
        tkr = self.ib.reqMktData(contract, "", False, False)
        self.ib.sleep(1.0)
        px = tkr.last or tkr.close or tkr.marketPrice()
        self.ib.cancelMktData(contract)
        return float(px) if px and px == px else None

    # ---- Ejecucion ----
    def place_order(self, symbol, qty, dry_run=True, ref_price=None):
        """
        Coloca una orden de mercado fraccional. qty>0 compra, qty<0 vende.
        Devuelve un dict con el resultado (o la intencion si dry_run).
        """
        action = "BUY" if qty > 0 else "SELL"
        quantity = round(abs(float(qty)), 4)
        if quantity == int(quantity):        # entero -> enviar como int (IBKR rechaza fraccional por API)
            quantity = int(quantity)
        info = {"symbol": symbol, "action": action, "qty": quantity,
                "ref_price": ref_price, "dry_run": dry_run, "status": None}
        if quantity <= 0:
            info["status"] = "skipped_zero"
            return info
        if dry_run:
            info["status"] = "dry_run"
            return info
        contract = Stock(symbol, "SMART", "USD")
        self.ib.qualifyContracts(contract)
        order = MarketOrder(action, quantity)
        trade = self.ib.placeOrder(contract, order)
        self.ib.sleep(1.0)
        info["status"] = trade.orderStatus.status
        info["filled"] = float(trade.orderStatus.filled)
        info["avg_fill_price"] = float(trade.orderStatus.avgFillPrice or 0.0)
        return info
