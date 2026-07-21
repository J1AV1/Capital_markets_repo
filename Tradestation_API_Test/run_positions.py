import os
import json

from tradestation_client import TradeStationClient


def main():
    client = TradeStationClient()
    client.authenticate()

    accounts_data = client.get_accounts()
    accounts = [acct.get("AccountID") for acct in accounts_data.get("Accounts", []) if acct.get("AccountID")]
    if not accounts:
        raise RuntimeError("No se encontraron cuentas válidas para el usuario.")

    configured_account = os.getenv("TRADESTATION_ACCOUNT_ID")
    if configured_account:
        account_ids = configured_account
    else:
        account_ids = ",".join(accounts[:5])

    print(f"Usando cuentas: {account_ids}")
    positions_data = client.get_positions(account_ids)

    print(json.dumps(positions_data, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
