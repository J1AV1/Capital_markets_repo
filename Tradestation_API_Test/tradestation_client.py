import json
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

import requests

AUTH_BASE = "https://signin.tradestation.com"
API_BASE = "https://api.tradestation.com"
AUTH_URL = f"{AUTH_BASE}/authorize"
TOKEN_URL = f"{AUTH_BASE}/oauth/token"
TOKEN_STORE = "token_store.json"

DEFAULT_REDIRECT_URI = os.getenv("TRADESTATION_REDIRECT_URI", "http://localhost:8080/callback")
DEFAULT_SCOPES = "openid offline_access profile MarketData ReadAccount Trade"


class AuthCodeHandler(BaseHTTPRequestHandler):
    server_version = "TradeStationAuth/1.0"

    def do_GET(self):
        query = urlparse(self.path).query
        params = parse_qs(query)
        code = params.get("code", [None])[0]
        state = params.get("state", [None])[0]
        if code:
            self.server.auth_code = code
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"<html><body><h1>Authorization complete.</h1><p>You may close this window.</p></body></html>")
        else:
            self.send_response(400)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"<html><body><h1>Authorization failed.</h1><p>No code received.</p></body></html>")

    def log_message(self, format, *args):
        return


class TradeStationClient:
    def __init__(self):
        self.client_id = os.getenv("TRADESTATION_CLIENT_ID")
        self.client_secret = os.getenv("TRADESTATION_CLIENT_SECRET")
        self.redirect_uri = DEFAULT_REDIRECT_URI
        self.scopes = os.getenv("TRADESTATION_SCOPES", DEFAULT_SCOPES)
        self.access_token = None
        self.refresh_token = None
        self.token_data = {}
        self._load_saved_tokens()

        if not self.client_id or not self.client_secret:
            raise EnvironmentError(
                "Define TRADESTATION_CLIENT_ID y TRADESTATION_CLIENT_SECRET en el entorno."
            )

    def _load_saved_tokens(self):
        if os.path.exists(TOKEN_STORE):
            try:
                with open(TOKEN_STORE, "r", encoding="utf-8") as f:
                    self.token_data = json.load(f)
                    self.access_token = self.token_data.get("access_token")
                    self.refresh_token = self.token_data.get("refresh_token")
            except Exception:
                self.token_data = {}

    def _save_tokens(self):
        if not self.token_data:
            return
        with open(TOKEN_STORE, "w", encoding="utf-8") as f:
            json.dump(self.token_data, f, indent=2)

    def _build_auth_url(self, state: str = "ts_state") -> str:
        params = {
            "response_type": "code",
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "audience": "https://api.tradestation.com",
            "scope": self.scopes,
            "state": state,
        }
        return requests.Request("GET", AUTH_URL, params=params).prepare().url

    def _exchange_code(self, code: str) -> dict:
        data = {
            "grant_type": "authorization_code",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "code": code,
            "redirect_uri": self.redirect_uri,
        }
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        resp = requests.post(TOKEN_URL, data=data, headers=headers, timeout=30)
        resp.raise_for_status()
        return resp.json()

    def _refresh_token(self, refresh_token: str) -> dict:
        data = {
            "grant_type": "refresh_token",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "refresh_token": refresh_token,
        }
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        resp = requests.post(TOKEN_URL, data=data, headers=headers, timeout=30)
        resp.raise_for_status()
        return resp.json()

    def authenticate(self):
        if self.refresh_token:
            try:
                print("Usando refresh token guardado para renovar acceso...")
                token_data = self._refresh_token(self.refresh_token)
                self._set_token_data(token_data)
                print("Token renovado correctamente.")
                return
            except Exception as exc:
                print("No se pudo usar refresh token guardado:", exc)

        print("Iniciando flow de autorización en el navegador...")
        url = self._build_auth_url()
        print("Abriendo navegador para autorizar:", url)
        import webbrowser
        webbrowser.open(url)

        parsed = urlparse(self.redirect_uri)
        host = parsed.hostname or "localhost"
        port = parsed.port or 8080
        server = HTTPServer((host, port), AuthCodeHandler)
        server.auth_code = None

        def serve():
            server.handle_request()

        thread = threading.Thread(target=serve, daemon=True)
        thread.start()
        thread.join(timeout=180)

        if not server.auth_code:
            raise RuntimeError("No se recibió el código de autorización en el redirect_uri.")

        token_data = self._exchange_code(server.auth_code)
        self._set_token_data(token_data)
        print("Autenticación completada.")

    def _set_token_data(self, token_data: dict):
        self.token_data = token_data
        self.access_token = token_data.get("access_token")
        self.refresh_token = token_data.get("refresh_token")
        self._save_tokens()

    def _get_headers(self):
        if not self.access_token:
            raise RuntimeError("No hay access token válido. Ejecuta authenticate() primero.")
        return {"Authorization": f"Bearer {self.access_token}", "Content-Type": "application/json"}

    def get_accounts(self) -> dict:
        url = f"{API_BASE}/v3/brokerage/accounts"
        resp = requests.get(url, headers=self._get_headers(), timeout=30)
        resp.raise_for_status()
        return resp.json()

    def get_positions(self, account_ids: str) -> dict:
        url = f"{API_BASE}/v3/brokerage/accounts/{account_ids}/positions"
        resp = requests.get(url, headers=self._get_headers(), timeout=30)
        resp.raise_for_status()
        return resp.json()
