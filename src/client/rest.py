"""Kalshi REST API client with rate limiting, pagination, and retries."""

from __future__ import annotations

import logging
import time
from decimal import Decimal
from typing import Optional

import requests

from .auth import KalshiAuth
from ..models.market import Event, Market, Orderbook
from ..models.order import Fill, Order
from ..models.portfolio import Balance, Position

logger = logging.getLogger("kalshi_bot.client.rest")


class TokenBucket:
    """Simple token bucket rate limiter."""

    def __init__(self, rate: float, capacity: float):
        """
        Args:
            rate: Tokens added per second
            capacity: Maximum tokens
        """
        self.rate = rate
        self.capacity = capacity
        self.tokens = capacity
        self.last_refill = time.monotonic()

    def acquire(self, tokens: float = 1.0):
        """Block until the requested tokens are available."""
        while True:
            self._refill()
            if self.tokens >= tokens:
                self.tokens -= tokens
                return
            # Calculate wait time
            deficit = tokens - self.tokens
            wait = deficit / self.rate
            time.sleep(wait)

    def _refill(self):
        now = time.monotonic()
        elapsed = now - self.last_refill
        self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)
        self.last_refill = now


class KalshiRestClient:
    """REST client for the Kalshi trading API.

    Features:
    - RSA-PSS authentication on every request
    - Token bucket rate limiting (separate read/write buckets)
    - Cursor-based pagination
    - Exponential backoff on 429 and 5xx errors
    - Comprehensive logging
    """

    def __init__(self, config: dict):
        """
        Args:
            config: API config dict with keys:
                base_url, key_id, private_key_path, timeout_seconds, max_retries
        """
        self.base_url = config["base_url"].rstrip("/")
        self.timeout = config.get("timeout_seconds", 10)
        self.max_retries = config.get("max_retries", 3)

        self.auth = KalshiAuth(
            key_id=config["key_id"],
            private_key_path=config["private_key_path"],
        )

        self.session = requests.Session()
        self.session.headers.update({
            "Content-Type": "application/json",
            "Accept": "application/json",
        })

        # Rate limiters: Basic tier = 20 reads/sec, 10 writes/sec
        self._read_limiter = TokenBucket(rate=18.0, capacity=18.0)   # slight buffer
        self._write_limiter = TokenBucket(rate=9.0, capacity=9.0)

    # -------------------------------------------------------------------------
    # Core request methods
    # -------------------------------------------------------------------------

    def _request(
        self,
        method: str,
        path: str,
        params: Optional[dict] = None,
        json_body: Optional[dict] = None,
        auth_required: bool = True,
    ) -> dict:
        """Send an authenticated request with rate limiting and retries.

        Args:
            method: HTTP method
            path: API path (relative to base_url, e.g., "/markets")
            params: Query parameters
            json_body: JSON request body
            auth_required: Whether to sign the request

        Returns:
            Parsed JSON response dict
        """
        # Determine rate limit bucket
        is_write = method.upper() in ("POST", "PUT", "PATCH")
        limiter = self._write_limiter if is_write else self._read_limiter
        limiter.acquire()

        url = f"{self.base_url}{path}"

        # Build full path for signing (includes query params path but signs without them)
        full_path = f"/trade-api/v2{path}"

        headers = {}
        if auth_required:
            headers = self.auth.get_headers(method.upper(), full_path)

        last_error = None
        for attempt in range(self.max_retries + 1):
            try:
                logger.debug(
                    f"API {method.upper()} {path} "
                    f"params={params} body_keys={list(json_body.keys()) if json_body else None}"
                )

                response = self.session.request(
                    method=method.upper(),
                    url=url,
                    params=params,
                    json=json_body,
                    headers=headers,
                    timeout=self.timeout,
                )

                # Handle rate limiting
                if response.status_code == 429:
                    wait = min(2 ** attempt, 60)
                    logger.warning(f"Rate limited (429). Waiting {wait}s before retry.")
                    time.sleep(wait)
                    # Refresh auth headers for retry
                    if auth_required:
                        headers = self.auth.get_headers(method.upper(), full_path)
                    continue

                # Handle server errors
                if response.status_code >= 500:
                    wait = min(2 ** attempt, 60)
                    logger.warning(
                        f"Server error {response.status_code}. "
                        f"Waiting {wait}s before retry {attempt + 1}/{self.max_retries}."
                    )
                    time.sleep(wait)
                    if auth_required:
                        headers = self.auth.get_headers(method.upper(), full_path)
                    continue

                # Handle client errors
                if response.status_code >= 400:
                    error_msg = response.text[:500]
                    logger.error(
                        f"API error {response.status_code}: {method.upper()} {path} - {error_msg}"
                    )
                    response.raise_for_status()

                # Success
                if response.status_code == 204:
                    return {}

                data = response.json()
                logger.debug(f"API response: {str(data)[:200]}")
                return data

            except requests.exceptions.Timeout:
                last_error = f"Request timeout after {self.timeout}s"
                logger.warning(f"{last_error} (attempt {attempt + 1})")
            except requests.exceptions.ConnectionError as e:
                last_error = f"Connection error: {e}"
                logger.warning(f"{last_error} (attempt {attempt + 1})")
                time.sleep(min(2 ** attempt, 30))

        raise RuntimeError(f"Request failed after {self.max_retries + 1} attempts: {last_error}")

    def _paginate(self, path: str, params: dict, result_key: str) -> list[dict]:
        """Fetch all pages of a paginated endpoint.

        Args:
            path: API path
            params: Query parameters (cursor will be added automatically)
            result_key: Key in response containing the results list

        Returns:
            Combined list of all results across all pages
        """
        all_results = []
        cursor = None

        while True:
            page_params = {**params}
            if cursor:
                page_params["cursor"] = cursor

            data = self._request("GET", path, params=page_params)
            results = data.get(result_key, [])
            all_results.extend(results)

            cursor = data.get("cursor")
            if not cursor or not results:
                break

            logger.debug(f"Pagination: fetched {len(all_results)} total, next cursor: {cursor[:20]}...")

        return all_results

    # -------------------------------------------------------------------------
    # Market endpoints
    # -------------------------------------------------------------------------

    def get_markets(
        self,
        status: str = "open",
        event_ticker: Optional[str] = None,
        series_ticker: Optional[str] = None,
        limit: int = 200,
    ) -> list[Market]:
        """Fetch markets with optional filters.

        Args:
            status: Filter by status (open, closed, settled)
            event_ticker: Filter by event
            series_ticker: Filter by series
            limit: Results per page (max 1000)

        Returns:
            List of Market objects
        """
        params = {"status": status, "limit": min(limit, 1000)}
        if event_ticker:
            params["event_ticker"] = event_ticker
        if series_ticker:
            params["series_ticker"] = series_ticker

        raw_markets = self._paginate("/markets", params, "markets")
        markets = [Market.from_api_response(m) for m in raw_markets]
        logger.info(f"Fetched {len(markets)} markets (status={status})")
        return markets

    def get_market(self, ticker: str) -> Market:
        """Fetch a single market by ticker."""
        data = self._request("GET", f"/markets/{ticker}")
        return Market.from_api_response(data.get("market", data))

    def get_orderbook(self, ticker: str, depth: int = 10) -> Orderbook:
        """Fetch the orderbook for a market.

        Args:
            ticker: Market ticker
            depth: Number of price levels (default 10)
        """
        data = self._request("GET", f"/markets/{ticker}/orderbook", params={"depth": depth})
        return Orderbook.from_api_response(ticker, data)

    def get_events(
        self,
        series_ticker: Optional[str] = None,
        status: str = "open",
        limit: int = 200,
    ) -> list[Event]:
        """Fetch events."""
        params = {"status": status, "limit": min(limit, 1000)}
        if series_ticker:
            params["series_ticker"] = series_ticker

        raw_events = self._paginate("/events", params, "events")
        return [Event.from_api_response(e) for e in raw_events]

    # -------------------------------------------------------------------------
    # Portfolio endpoints
    # -------------------------------------------------------------------------

    def get_balance(self) -> Balance:
        """Fetch account balance."""
        data = self._request("GET", "/portfolio/balance")
        return Balance.from_api_response(data)

    def get_positions(self) -> list[Position]:
        """Fetch all open positions."""
        params = {"limit": 1000}
        raw = self._paginate("/portfolio/positions", params, "market_positions")
        return [Position.from_api_response(p) for p in raw]

    def get_fills(
        self,
        ticker: Optional[str] = None,
        limit: int = 100,
    ) -> list[Fill]:
        """Fetch fill history."""
        params = {"limit": limit}
        if ticker:
            params["ticker"] = ticker
        raw = self._paginate("/portfolio/fills", params, "fills")
        return [Fill.from_api_response(f) for f in raw]

    # -------------------------------------------------------------------------
    # Order endpoints
    # -------------------------------------------------------------------------

    def place_order(self, order: Order) -> dict:
        """Place a new order.

        Args:
            order: Order object with all details

        Returns:
            API response dict (contains order_id, status, etc.)
        """
        body = order.to_api_body()
        logger.info(
            f"PLACING ORDER: {order.action.value} {order.count}x "
            f"{order.side.value} {order.ticker} @ ${order.price_dollars} "
            f"[{order.strategy_name}] {order.reason}"
        )
        data = self._request("POST", "/portfolio/orders", json_body=body)
        logger.info(f"ORDER RESPONSE: {data.get('order', {}).get('order_id', 'unknown')}")
        return data

    def cancel_order(self, order_id: str) -> dict:
        """Cancel an open order."""
        logger.info(f"CANCELLING ORDER: {order_id}")
        return self._request("DELETE", f"/portfolio/orders/{order_id}")

    def get_order(self, order_id: str) -> dict:
        """Get order details."""
        return self._request("GET", f"/portfolio/orders/{order_id}")

    def get_orders(
        self,
        ticker: Optional[str] = None,
        status: Optional[str] = None,
    ) -> list[dict]:
        """Get all orders with optional filters."""
        params = {"limit": 1000}
        if ticker:
            params["ticker"] = ticker
        if status:
            params["status"] = status
        return self._paginate("/portfolio/orders", params, "orders")
