# TradeStation API Test

Carpeta de prueba para validar la autenticación y la carga de posiciones desde TradeStation.

## Objetivo
- Autenticar usando el flujo Authorization Code de TradeStation.
- Traer cuentas de brokerage.
- Traer posiciones para una o varias cuentas.

## Requisitos
- Python 3.10+ (o similar)
- `requests`

## Instalación
```bash
python -m pip install requests
```

## Variables de entorno
Configura estas variables antes de ejecutar la prueba:

- `TRADESTATION_CLIENT_ID`
- `TRADESTATION_CLIENT_SECRET`
- `TRADESTATION_REDIRECT_URI` (por defecto `http://localhost:8080/callback`)
- `TRADESTATION_ACCOUNT_ID` (opcional; si no se proporciona, usa la primera cuenta retornada)

## Ejecución
```bash
python run_positions.py
```

## Notas
- El script abre una ventana del navegador para iniciar sesión en TradeStation.
- Si ya tienes un `refresh_token`, se guarda en `token_store.json` y se puede reutilizar.
- No agregues tus claves a este repositorio.
