"""Market, Orderbook, and Event data models for Kalshi API."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Optional


@dataclass
class OrderbookLevel:
    """A single price level in the orderbook."""
    price_dollars: Decimal
    count_fp: Decimal

    @classmethod
    def from_api(cls, price: str | float, quantity: str | float) -> OrderbookLevel:
        return cls(
            price_dollars=Decimal(str(price)),
            count_fp=Decimal(str(quantity)),
        )


@dataclass
class Orderbook:
    """Full orderbook for a market."""
    ticker: str
    yes_bids: list[OrderbookLevel] = field(default_factory=list)
    no_bids: list[OrderbookLevel] = field(default_factory=list)
    timestamp: Optional[datetime] = None

    @property
    def best_yes_bid(self) -> Optional[Decimal]:
        """Best (highest) yes bid price."""
        if not self.yes_bids:
            return None
        return max(lvl.price_dollars for lvl in self.yes_bids)

    @property
    def best_no_bid(self) -> Optional[Decimal]:
        """Best (highest) no bid price."""
        if not self.no_bids:
            return None
        return max(lvl.price_dollars for lvl in self.no_bids)

    @property
    def best_yes_ask(self) -> Optional[Decimal]:
        """Best yes ask = 1 - best no bid (buying YES from a NO seller)."""
        if self.best_no_bid is None:
            return None
        return Decimal("1.00") - self.best_no_bid

    @property
    def best_no_ask(self) -> Optional[Decimal]:
        """Best no ask = 1 - best yes bid (buying NO from a YES seller)."""
        if self.best_yes_bid is None:
            return None
        return Decimal("1.00") - self.best_yes_bid

    @property
    def spread(self) -> Optional[Decimal]:
        """Yes bid-ask spread."""
        if self.best_yes_bid is None or self.best_yes_ask is None:
            return None
        return self.best_yes_ask - self.best_yes_bid

    @property
    def midpoint(self) -> Optional[Decimal]:
        """Midpoint of the yes bid-ask spread."""
        if self.best_yes_bid is None or self.best_yes_ask is None:
            return None
        return (self.best_yes_bid + self.best_yes_ask) / 2

    @classmethod
    def from_api_response(cls, ticker: str, data: dict) -> Orderbook:
        """Parse Kalshi orderbook API response.

        Kalshi returns:
        {
            "orderbook": {
                "yes": [[price, quantity], ...],
                "no": [[price, quantity], ...]
            }
        }
        """
        ob_data = data.get("orderbook", data)

        yes_bids = []
        for level in ob_data.get("yes", []):
            if isinstance(level, list) and len(level) >= 2:
                yes_bids.append(OrderbookLevel.from_api(level[0], level[1]))

        no_bids = []
        for level in ob_data.get("no", []):
            if isinstance(level, list) and len(level) >= 2:
                no_bids.append(OrderbookLevel.from_api(level[0], level[1]))

        return cls(
            ticker=ticker,
            yes_bids=yes_bids,
            no_bids=no_bids,
            timestamp=datetime.utcnow(),
        )


@dataclass
class Market:
    """A single Kalshi prediction market."""
    ticker: str
    event_ticker: str
    series_ticker: str
    title: str
    status: str  # unopened, open, closed, settled
    yes_bid: Optional[Decimal] = None
    yes_ask: Optional[Decimal] = None
    no_bid: Optional[Decimal] = None
    no_ask: Optional[Decimal] = None
    last_price: Optional[Decimal] = None
    previous_price: Optional[Decimal] = None
    volume_24h: int = 0
    open_interest: int = 0
    close_time: Optional[datetime] = None
    result: Optional[str] = None
    rules_primary: Optional[str] = None

    @property
    def implied_yes_prob(self) -> Optional[Decimal]:
        """Midpoint implied probability for YES."""
        if self.yes_bid is not None and self.yes_ask is not None:
            return (self.yes_bid + self.yes_ask) / 2
        return self.last_price

    @property
    def spread_pct(self) -> Optional[Decimal]:
        """Bid-ask spread as a fraction."""
        if self.yes_bid is not None and self.yes_ask is not None and self.yes_ask > 0:
            return (self.yes_ask - self.yes_bid) / self.yes_ask
        return None

    @classmethod
    def from_api_response(cls, data: dict) -> Market:
        """Parse a market object from Kalshi API response."""

        def to_decimal(val) -> Optional[Decimal]:
            if val is None:
                return None
            try:
                return Decimal(str(val))
            except Exception:
                return None

        def to_datetime(val) -> Optional[datetime]:
            if val is None:
                return None
            try:
                if isinstance(val, str):
                    # Handle ISO format with Z suffix
                    val = val.replace("Z", "+00:00")
                    return datetime.fromisoformat(val)
                return val
            except Exception:
                return None

        return cls(
            ticker=data.get("ticker", ""),
            event_ticker=data.get("event_ticker", ""),
            series_ticker=data.get("series_ticker", ""),
            title=data.get("title", data.get("subtitle", "")),
            status=data.get("status", ""),
            yes_bid=to_decimal(data.get("yes_bid")),
            yes_ask=to_decimal(data.get("yes_ask")),
            no_bid=to_decimal(data.get("no_bid")),
            no_ask=to_decimal(data.get("no_ask")),
            last_price=to_decimal(data.get("last_price")),
            previous_price=to_decimal(data.get("previous_price")),
            volume_24h=int(data.get("volume_24h", 0) or 0),
            open_interest=int(data.get("open_interest", 0) or 0),
            close_time=to_datetime(data.get("close_time")),
            result=data.get("result"),
            rules_primary=data.get("rules_primary"),
        )


@dataclass
class Event:
    """A Kalshi event containing one or more markets."""
    event_ticker: str
    series_ticker: str
    title: str
    markets: list[str] = field(default_factory=list)
    status: str = ""

    @classmethod
    def from_api_response(cls, data: dict) -> Event:
        market_tickers = []
        for m in data.get("markets", []):
            if isinstance(m, dict):
                market_tickers.append(m.get("ticker", ""))
            elif isinstance(m, str):
                market_tickers.append(m)

        return cls(
            event_ticker=data.get("event_ticker", ""),
            series_ticker=data.get("series_ticker", ""),
            title=data.get("title", ""),
            markets=market_tickers,
            status=data.get("status", ""),
        )
