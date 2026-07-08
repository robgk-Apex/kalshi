"""Kalshi API client with RSA-PSS authentication."""

import base64
import time
import requests
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding


class KalshiClient:
    """Handles all communication with the Kalshi API."""

    def __init__(self, base_url: str, key_id: str = None,
                 private_key_path: str = None):
        """If key_id/private_key_path are given, requests are signed
        (needed for balances/positions/orders). If BOTH are omitted, the client
        runs unauthenticated — fine for public market data (GET /markets,
        /events), which is all the read-only dashboard needs."""
        self.base_url = base_url.rstrip("/")
        self.key_id = key_id
        if key_id or private_key_path:
            # Auth explicitly requested — load the key (raises if the file is missing).
            self.private_key = self._load_key(private_key_path)
        else:
            self.private_key = None
        self.authed = self.private_key is not None
        self.session = requests.Session()

    def _load_key(self, path: str):
        with open(path, "rb") as f:
            return serialization.load_pem_private_key(f.read(), password=None)

    def _sign(self, timestamp_ms: str, method: str, path: str) -> str:
        message = f"{timestamp_ms}{method}{path}".encode()
        signature = self.private_key.sign(
            message,
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.DIGEST_LENGTH,
            ),
            hashes.SHA256(),
        )
        return base64.b64encode(signature).decode()

    def _headers(self, method: str, path: str) -> dict:
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.authed:
            ts = str(int(time.time() * 1000))
            headers["KALSHI-ACCESS-KEY"] = self.key_id
            headers["KALSHI-ACCESS-TIMESTAMP"] = ts
            headers["KALSHI-ACCESS-SIGNATURE"] = self._sign(ts, method, path)
        return headers

    def _request(self, method: str, path: str, params=None, json_body=None):
        url = f"{self.base_url}{path}"
        # Signature must include the full path from the URL (after the host)
        # e.g. /trade-api/v2/portfolio/balance
        from urllib.parse import urlparse
        full_path = urlparse(url).path
        headers = self._headers(method, full_path)
        resp = self.session.request(
            method, url, headers=headers, params=params, json=json_body, timeout=15
        )
        resp.raise_for_status()
        return resp.json()

    # ── Account ──────────────────────────────────────────
    def get_balance(self) -> dict:
        return self._request("GET", "/portfolio/balance")

    def get_positions(self, **kwargs) -> dict:
        return self._request("GET", "/portfolio/positions", params=kwargs)

    # ── Markets ──────────────────────────────────────────
    def get_markets(self, **kwargs) -> dict:
        return self._request("GET", "/markets", params=kwargs)

    def get_market(self, ticker: str) -> dict:
        return self._request("GET", f"/markets/{ticker}")

    def get_orderbook(self, ticker: str, depth: int = 10) -> dict:
        return self._request("GET", f"/markets/{ticker}/orderbook", params={"depth": depth})

    def get_events(self, **kwargs) -> dict:
        return self._request("GET", "/events", params=kwargs)

    def get_trades(self, **kwargs) -> dict:
        return self._request("GET", "/markets/trades", params=kwargs)

    # ── Orders ───────────────────────────────────────────
    def place_order(
        self,
        ticker: str,
        side: str,
        action: str,
        count: int,
        yes_price: float = None,
        no_price: float = None,
        time_in_force: str = "good_till_canceled",
        client_order_id: str = None,
    ) -> dict:
        body = {
            "ticker": ticker,
            "side": side,
            "action": action,
            "count": count,
            "type": "limit",
            "time_in_force": time_in_force,
        }
        if yes_price is not None:
            body["yes_price"] = int(yes_price * 100)  # convert dollars to cents
        if no_price is not None:
            body["no_price"] = int(no_price * 100)
        if client_order_id:
            body["client_order_id"] = client_order_id
        return self._request("POST", "/portfolio/orders", json_body=body)

    def get_orders(self, **kwargs) -> dict:
        return self._request("GET", "/portfolio/orders", params=kwargs)

    def cancel_order(self, order_id: str) -> dict:
        return self._request("DELETE", f"/portfolio/orders/{order_id}")

    def get_fills(self, **kwargs) -> dict:
        return self._request("GET", "/portfolio/fills", params=kwargs)
