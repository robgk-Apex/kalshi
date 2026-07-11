"""
Crypto Price Analyzer - Analyzes like a stock trader before trading.

Before buying ANY crypto contract on Kalshi, this module checks:
1. Current price vs strike price (is it even close?)
2. Price trend (moving average - is price going toward or away from strike?)
3. Momentum (rate of change - how fast is it moving?)
4. Volatility (how wild are the swings? can it reach the strike in time?)
5. Support/resistance (is there a price floor/ceiling nearby?)

Only trades when multiple signals agree. No more blind spread trades.
"""

import logging
import time
from datetime import datetime, timezone
from typing import Optional, Dict, Tuple

logger = logging.getLogger("kalshi-bot.crypto")

# Coinbase public API — no key required.
COINBASE_SPOT = "https://api.coinbase.com/v2/prices"
COINBASE_CANDLES = "https://api.exchange.coinbase.com/products"
# Kalshi coin id -> Coinbase product.
COINBASE_PRODUCT = {
    "BTC": "BTC-USD", "ETH": "ETH-USD", "SOL": "SOL-USD",
    "XRP": "XRP-USD", "DOGE": "DOGE-USD", "BNB": "BNB-USD", "HYPE": "HYPE-USD",
}

# Map Kalshi ticker prefixes to CryptoCompare symbols
COIN_MAP = {
    "KXBTC": ("BTC", "BTC"),
    "KXBTCD": ("BTC", "BTC"),
    "KXETH": ("ETH", "ETH"),
    "KXETHD": ("ETH", "ETH"),
    "KXSOL": ("SOL", "SOL"),
    "KXSOLD": ("SOL", "SOL"),
    "KXXRP": ("XRP", "XRP"),
    "KXXRPD": ("XRP", "XRP"),
    "KXDOGE": ("DOGE", "DOGE"),
    "KXDOGED": ("DOGE", "DOGE"),
    "KXBNB": ("BNB", "BNB"),
    "KXBNBD": ("BNB", "BNB"),
    "KXHYPE": ("HYPE", "HYPE"),
    "KXHYPED": ("HYPE", "HYPE"),
}


class CryptoAnalyzer:
    """Analyzes crypto price action before allowing trades."""

    def __init__(self):
        self._price_cache: Dict[str, Tuple[float, float]] = {}  # coin_id -> (price, timestamp)
        self._history_cache: Dict[str, Tuple[list, float]] = {}  # coin_id -> (prices, timestamp)
        self._cache_ttl = 15   # seconds - keep spot fresh so distance-to-strike is current
        self._history_ttl = 60  # seconds - candles change slowly
        self._last_request = 0
        self._min_request_gap = 0.3  # Coinbase public API is generous

    def should_trade(self, ticker: str, side: str, strike: float,
                     hours_to_settle: float, ask_price: float) -> Tuple[bool, str]:
        """
        Analyze whether a crypto trade makes sense.

        Returns (should_trade: bool, reason: str)
        """
        # Find which coin this is
        coin_id, symbol = self._get_coin(ticker)
        if not coin_id:
            return False, f"Unknown crypto ticker: {ticker}"

        # Get current price
        current_price = self._get_price(coin_id)
        if current_price is None:
            return False, f"Could not fetch {symbol} price"

        # Get price history (last 24h)
        history = self._get_history(coin_id)
        if not history or len(history) < 10:
            return False, f"Insufficient {symbol} price history"

        # Parse strike from ticker
        strike = self._parse_strike(ticker)
        if strike is None:
            return False, f"Could not parse strike from {ticker}"

        # Determine if this is an above/below market
        is_above = self._is_above_market(ticker)

        # ══════════════════════════════════════════════
        # ANALYSIS - Think like a trader
        # ══════════════════════════════════════════════

        signals = []
        score = 0  # -5 to +5, need >= 3 to trade

        # ── 1. DISTANCE CHECK ──
        # How far is current price from strike?
        distance_pct = abs(current_price - strike) / current_price * 100

        if side == "yes" and is_above:
            # We're betting price will be ABOVE strike
            if current_price > strike:
                # Already above - how much cushion?
                cushion_pct = (current_price - strike) / current_price * 100
                if cushion_pct > 3:
                    signals.append(f"STRONG: {symbol} ${current_price:.2f} is {cushion_pct:.1f}% above strike ${strike:.2f}")
                    score += 2
                elif cushion_pct > 1:
                    signals.append(f"OK: {symbol} ${current_price:.2f} is {cushion_pct:.1f}% above strike ${strike:.2f}")
                    score += 1
                else:
                    signals.append(f"TIGHT: {symbol} ${current_price:.2f} barely above strike ${strike:.2f}")
                    score += 0
            else:
                # Below strike - needs to go UP
                gap_pct = (strike - current_price) / current_price * 100
                signals.append(f"BELOW: {symbol} ${current_price:.2f} needs +{gap_pct:.1f}% to hit ${strike:.2f}")
                score -= 1
                if gap_pct > 3:
                    score -= 1  # extra penalty for big gap

        elif side == "no" and is_above:
            # We're betting price will be BELOW strike
            if current_price < strike:
                cushion_pct = (strike - current_price) / current_price * 100
                if cushion_pct > 3:
                    signals.append(f"STRONG: {symbol} ${current_price:.2f} is {cushion_pct:.1f}% below strike ${strike:.2f}")
                    score += 2
                elif cushion_pct > 1:
                    signals.append(f"OK: {symbol} ${current_price:.2f} is {cushion_pct:.1f}% below strike ${strike:.2f}")
                    score += 1
                else:
                    signals.append(f"TIGHT: {symbol} ${current_price:.2f} barely below strike ${strike:.2f}")
            else:
                gap_pct = (current_price - strike) / current_price * 100
                signals.append(f"ABOVE: {symbol} ${current_price:.2f} needs -{gap_pct:.1f}% to go below ${strike:.2f}")
                score -= 1
                if gap_pct > 3:
                    score -= 1

        elif side == "yes" and not is_above:
            # Below market - YES means price IS below
            if current_price < strike:
                cushion_pct = (strike - current_price) / current_price * 100
                if cushion_pct > 3:
                    signals.append(f"STRONG: {symbol} ${current_price:.2f} well below strike ${strike:.2f}")
                    score += 2
                else:
                    signals.append(f"OK: {symbol} ${current_price:.2f} below strike ${strike:.2f}")
                    score += 1
            else:
                signals.append(f"ABOVE: {symbol} ${current_price:.2f} above strike, needs to drop")
                score -= 1

        elif side == "no" and not is_above:
            # Below market - NO means price is NOT below (i.e., above)
            if current_price > strike:
                cushion_pct = (current_price - strike) / current_price * 100
                if cushion_pct > 3:
                    signals.append(f"STRONG: {symbol} ${current_price:.2f} well above strike ${strike:.2f}")
                    score += 2
                else:
                    signals.append(f"OK: {symbol} ${current_price:.2f} above strike ${strike:.2f}")
                    score += 1
            else:
                signals.append(f"BELOW: {symbol} ${current_price:.2f} below strike, needs to rise")
                score -= 1

        # ── 2. TREND CHECK (Moving Average) ──
        # Compare current price to 1h and 4h moving averages
        prices = [p[1] for p in history]  # extract price values

        ma_1h = sum(prices[-12:]) / min(12, len(prices[-12:]))  # ~1h (5min candles)
        ma_4h = sum(prices[-48:]) / min(48, len(prices[-48:])) if len(prices) >= 48 else ma_1h

        trend_1h = (current_price - ma_1h) / ma_1h * 100
        trend_4h = (current_price - ma_4h) / ma_4h * 100

        # Is the trend helping our trade?
        want_up = (side == "yes" and is_above) or (side == "no" and not is_above)
        want_down = (side == "no" and is_above) or (side == "yes" and not is_above)

        if want_up:
            if trend_1h > 0.5:
                signals.append(f"TREND UP: {symbol} +{trend_1h:.2f}% vs 1h MA")
                score += 1
            elif trend_1h < -0.5:
                signals.append(f"TREND DOWN: {symbol} {trend_1h:.2f}% vs 1h MA (against us)")
                score -= 1
            else:
                signals.append(f"TREND FLAT: {symbol} {trend_1h:+.2f}% vs 1h MA")
        else:  # want_down
            if trend_1h < -0.5:
                signals.append(f"TREND DOWN: {symbol} {trend_1h:.2f}% vs 1h MA (in our favor)")
                score += 1
            elif trend_1h > 0.5:
                signals.append(f"TREND UP: {symbol} +{trend_1h:.2f}% vs 1h MA (against us)")
                score -= 1
            else:
                signals.append(f"TREND FLAT: {symbol} {trend_1h:+.2f}% vs 1h MA")

        # ── 3. MOMENTUM CHECK ──
        # Rate of change over last 30 min
        if len(prices) >= 6:
            price_30m_ago = prices[-6]
            momentum = (current_price - price_30m_ago) / price_30m_ago * 100

            if want_up and momentum > 0.3:
                signals.append(f"MOMENTUM+: {symbol} +{momentum:.2f}% last 30min")
                score += 1
            elif want_down and momentum < -0.3:
                signals.append(f"MOMENTUM+: {symbol} {momentum:.2f}% last 30min (dropping)")
                score += 1
            elif (want_up and momentum < -0.5) or (want_down and momentum > 0.5):
                signals.append(f"MOMENTUM-: {symbol} {momentum:+.2f}% last 30min (against us)")
                score -= 1
            else:
                signals.append(f"MOMENTUM NEUTRAL: {symbol} {momentum:+.2f}% last 30min")

        # ── 4. VOLATILITY CHECK ──
        # Can price realistically reach the strike in time?
        if len(prices) >= 12:
            recent = prices[-12:]
            high = max(recent)
            low = min(recent)
            volatility_pct = (high - low) / current_price * 100

            # If we need price to move X% and volatility is only Y%, it's unlikely
            if distance_pct > volatility_pct * 2 and score < 2:
                signals.append(f"VOL LOW: {symbol} moved {volatility_pct:.2f}% in 1h, need {distance_pct:.1f}%")
                score -= 1
            elif volatility_pct > 2:
                signals.append(f"VOL HIGH: {symbol} {volatility_pct:.2f}% range in 1h - risky")
                # High vol is risky for both sides
                if score > 0:
                    score -= 1

        # ── 5. TIME CHECK ──
        # More time = more uncertainty
        if hours_to_settle < 0.5:
            # 15-30 min markets - need to be very confident
            if score < 2:
                signals.append(f"TIME PRESSURE: only {hours_to_settle*60:.0f}min left, not confident enough")
                score -= 1
        elif hours_to_settle > 6:
            # Long time - more can go wrong
            if distance_pct < 1:
                signals.append(f"LONG SETTLE: {hours_to_settle:.1f}h, too close to strike for comfort")
                score -= 1

        # ── 6. PRICE CHECK ──
        # Don't pay too much for the contract
        if ask_price > 0.20:
            signals.append(f"EXPENSIVE: ${ask_price:.2f} per contract, limited upside")
            score -= 1
        elif ask_price < 0.05:
            signals.append(f"CHEAP: ${ask_price:.2f} per contract, high payout if right")
            score += 1

        # ══════════════════════════════════════════════
        # DECISION
        # ══════════════════════════════════════════════

        min_score = 3  # Need at least 3 positive signals

        reason = f"Score: {score}/{min_score} | " + " | ".join(signals)

        if score >= min_score:
            logger.info(f"[CRYPTO] APPROVED: {ticker} {side} @ ${ask_price:.2f} | {reason}")
            return True, reason
        else:
            logger.debug(f"[CRYPTO] REJECTED: {ticker} {side} @ ${ask_price:.2f} | {reason}")
            return False, reason

    def _get_coin(self, ticker: str) -> Tuple[Optional[str], Optional[str]]:
        """Map Kalshi ticker to CoinGecko coin ID."""
        for prefix, (coin_id, symbol) in COIN_MAP.items():
            if ticker.startswith(prefix):
                return coin_id, symbol
        return None, None

    def _parse_strike(self, ticker: str) -> Optional[float]:
        """Extract strike price from Kalshi ticker."""
        # Tickers like: KXBTCD-26MAR2715-T69499.99 or KXBTC-26MAR2715-B65550
        parts = ticker.split("-")
        for part in parts:
            if part.startswith("T") or part.startswith("B"):
                try:
                    return float(part[1:])
                except ValueError:
                    pass
        return None

    def _is_above_market(self, ticker: str) -> bool:
        """Is this a 'price above X' market (T=threshold above) or below (B=below)?"""
        parts = ticker.split("-")
        for part in parts:
            if part.startswith("T"):
                return True
            if part.startswith("B"):
                # B can mean "between" or "below" depending on context
                # For KXBTC range markets, B means the upper bound of range
                # For KXBTCD directional, T means "above threshold"
                return True  # Treat both as "above" since the logic handles it
        return True  # Default

    def _get_price(self, coin_id: str) -> Optional[float]:
        """Current spot price from Coinbase (public, no key), with caching."""
        now = time.time()
        if coin_id in self._price_cache:
            price, cached_at = self._price_cache[coin_id]
            if now - cached_at < self._cache_ttl:
                return price

        product = COINBASE_PRODUCT.get(coin_id)
        if not product:
            return None
        if now - self._last_request < self._min_request_gap:
            time.sleep(self._min_request_gap - (now - self._last_request))

        try:
            import urllib.request
            import json

            url = f"{COINBASE_SPOT}/{product}/spot"
            self._last_request = time.time()
            req = urllib.request.Request(url, headers={"Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())
                price = float(data["data"]["amount"])
                self._price_cache[coin_id] = (price, time.time())
                return price
        except Exception as e:
            logger.warning(f"[CRYPTO] Price fetch failed for {coin_id}: {e}")
        return None

    def _get_history(self, coin_id: str) -> Optional[list]:
        """Recent price history from Coinbase 5-min candles (public, no key).

        Returns [[ts_ms, close], ...] oldest-first, matching the old format."""
        now = time.time()
        if coin_id in self._history_cache:
            history, cached_at = self._history_cache[coin_id]
            if now - cached_at < self._history_ttl:
                return history

        product = COINBASE_PRODUCT.get(coin_id)
        if not product:
            return None
        if now - self._last_request < self._min_request_gap:
            time.sleep(self._min_request_gap - (now - self._last_request))

        try:
            import urllib.request
            import json

            # Coinbase candles: [ time, low, high, open, close, volume ], newest-first.
            url = f"{COINBASE_CANDLES}/{product}/candles?granularity=300"
            self._last_request = time.time()
            req = urllib.request.Request(url, headers={
                "Accept": "application/json", "User-Agent": "kalshi-dashboard"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                candles = json.loads(resp.read().decode())
                prices = [[int(c[0]) * 1000, float(c[4])]
                          for c in reversed(candles) if len(c) >= 5]
                if prices:
                    self._history_cache[coin_id] = (prices, time.time())
                    return prices
        except Exception as e:
            logger.warning(f"[CRYPTO] History fetch failed for {coin_id}: {e}")
        return None
