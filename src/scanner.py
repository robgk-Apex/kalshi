"""Market scanner - finds mispricings and calculates edge."""

import logging
from datetime import datetime, timezone, timedelta
from typing import List, Optional

logger = logging.getLogger("kalshi-bot.scanner")

# Will be set by __main__ if external odds are enabled
_external_odds_provider = None


class Opportunity:
    """Represents a detected trading opportunity."""

    def __init__(self, ticker: str, event_ticker: str, title: str,
                 side: str, market_price: float, fair_price: float,
                 edge: float, volume: float, yes_bid: float, yes_ask: float,
                 no_bid: float, no_ask: float):
        self.ticker = ticker
        self.event_ticker = event_ticker
        self.title = title
        self.side = side              # "yes" or "no"
        self.market_price = market_price
        self.fair_price = fair_price
        self.edge = edge              # positive = profitable
        self.volume = volume
        self.yes_bid = yes_bid
        self.yes_ask = yes_ask
        self.no_bid = no_bid
        self.no_ask = no_ask

    def __repr__(self):
        return (f"Opportunity({self.ticker} {self.side.upper()} "
                f"market={self.market_price:.2f} fair={self.fair_price:.2f} "
                f"edge={self.edge:+.4f})")


class MarketScanner:
    """Scans Kalshi markets for mispricings."""

    # Intraday market ticker prefixes - these settle within hours
    INTRADAY_PREFIXES = (
        "KXBTC", "KXETH",          # Crypto hourly/daily
        "KXSPX", "KXSPY", "KXSPD",  # S&P 500
        "KXNDX", "KXQQQ", "KXNAS",  # Nasdaq
        "KXDJIA", "KXDOW",          # Dow Jones
        "KXIWM", "KXRUT", "KXRTX",  # Russell 2000
        "KXGLD", "KXGOLD", "KXXAU", # Gold
        "KXOIL", "KXWTI", "KXCL",   # Oil
        "KXEUR", "KXUSD", "KXGBP",  # Forex
        "KXTEMP", "KXHIGH", "KXLOW",# Weather
        "KXTSLA", "KXAAPL", "KXNVDA",# Single stocks
        "KXAMZN", "KXGOOG", "KXMETA",
        "KXMAG7",                     # Mag 7
        "KXVIX",                      # Volatility
        "KXSILV", "KXXAG",           # Silver
        "KXINX",                      # Indexes general
    )

    def __init__(self, client, config: dict, external_odds=None):
        self.client = client
        self.min_edge = config["strategy"]["min_edge"]
        self.min_volume = config["strategy"]["min_volume"]
        self.max_hours = config["strategy"].get("max_hours_to_expiry", 4)
        self.max_entry_price = config["strategy"].get("max_entry_price", 1.0)
        self.external_odds = external_odds

        # Focus mode. "crypto_short" scans ONLY short-term up/down crypto
        # (the directional *D series) and skips every other market. "all"
        # keeps the original behavior (crypto + all other events).
        self.mode = config["strategy"].get("mode", "all")
        # Which crypto series to scan (override the defaults from config if set).
        self.crypto_series = (
            config["strategy"].get("crypto_series")
            or (self.DIRECTIONAL_CRYPTO_SERIES
                if self.mode == "crypto_short" else self.CRYPTO_SERIES)
        )

        # Crypto analyzer - real price/trend/momentum analysis
        try:
            from .crypto_analyzer import CryptoAnalyzer
            self.crypto_analyzer = CryptoAnalyzer()
            logger.info("[CRYPTO] Analyzer enabled - trades require technical approval")
        except Exception as e:
            self.crypto_analyzer = None
            logger.warning(f"[CRYPTO] Analyzer disabled: {e}")

        # Weather analyzer - checks NWS forecasts before trading
        try:
            from .weather_analyzer import WeatherAnalyzer
            self.weather_analyzer = WeatherAnalyzer()
            logger.info("[WEATHER] Analyzer enabled - trades require forecast approval")
        except Exception as e:
            self.weather_analyzer = None
            logger.warning(f"[WEATHER] Analyzer disabled: {e}")

        # Layer 3: Probability checker - blocks trades without real-world backing
        try:
            from .probability_checker import ProbabilityChecker
            self.probability_checker = ProbabilityChecker(external_odds=external_odds)
            logger.info("[LAYER3] Probability checker enabled - blocks coin-flip trades")
        except Exception as e:
            self.probability_checker = None
            logger.warning(f"[LAYER3] Probability checker disabled: {e}")
        # Backwards compat
        if "max_days_to_expiry" in config["strategy"]:
            self.max_hours = config["strategy"]["max_days_to_expiry"] * 24

    # Crypto series - RE-ENABLED with CryptoAnalyzer gating
    CRYPTO_SERIES = [
        "KXBTC", "KXBTCD",       # Bitcoin range + directional
        "KXETH", "KXETHD",       # Ethereum
        "KXSOL", "KXSOLD",       # Solana
        "KXXRP", "KXXRPD",       # XRP
        "KXDOGE", "KXDOGED",     # Dogecoin
        "KXBNB", "KXBNBD",       # BNB
        "KXHYPE", "KXHYPED",     # Hype
    ]

    # Short-term "up/down" crypto: the 15-minute (*15M) and hourly (*D) series.
    # (Confirmed via Kalshi's /series: KXBTC15M etc. are frequency=fifteen_min;
    # KXBTCD etc. are the hourly directional markets.) `mode: crypto_short`
    # scans these; the dashboard groups them into 15m / hourly / daily / weekly.
    DIRECTIONAL_CRYPTO_SERIES = [
        "KXBTC15M", "KXETH15M", "KXSOL15M", "KXXRP15M", "KXDOGE15M",  # 15-min up/down
        "KXBTCD", "KXETHD", "KXSOLD", "KXXRPD", "KXDOGED",            # hourly up/down
    ]

    # Crypto tickers that need CryptoAnalyzer approval before trading
    CRYPTO_TICKERS = (
        "KXBTC", "KXBTCD", "KXETH", "KXETHD", "KXSOL", "KXSOLD",
        "KXXRP", "KXXRPD", "KXDOGE", "KXDOGED", "KXBNB", "KXBNBD",
        "KXHYPE", "KXHYPED",
    )

    def scan(self) -> List[Opportunity]:
        """Scan markets by fetching events then their markets."""
        opportunities = []
        total_scanned = 0
        seen_tickers = set()
        self._market_cache = []

        # ── Phase 1: Scan crypto hourly/15-min series directly ──
        for series in self.crypto_series:
            try:
                cursor_s = None
                for _ in range(5):  # up to 5 pages per series
                    params = {"series_ticker": series, "limit": 200, "with_nested_markets": True}
                    if cursor_s:
                        params["cursor"] = cursor_s
                    resp = self.client.get_events(**params)
                    events = resp.get("events", [])
                    cursor_s = resp.get("cursor", "")

                    for event in events:
                        for market in event.get("markets", []):
                            ticker = market.get("ticker", "")
                            if ticker and ticker not in seen_tickers:
                                seen_tickers.add(ticker)
                                total_scanned += 1
                                try:
                                    opp = self._evaluate_market(market)
                                except Exception as e:
                                    logger.debug(f"Evaluate failed for {ticker}: {e}")
                                    continue
                                if opp:
                                    self._market_cache.append(market)
                                    opportunities.append(opp)

                    if not cursor_s or not events:
                        break
            except Exception as e:
                logger.debug(f"Crypto series {series}: {e}")

        logger.info(f"  ...crypto scan: {total_scanned} markets, {len(opportunities)} opportunities")

        # In crypto-only mode, stop here — do not scan any other markets.
        if self.mode == "crypto_short":
            self._sort_by_soonest_then_edge(opportunities)
            logger.info(
                f"Scan complete (crypto_short): {len(opportunities)} up/down crypto "
                f"opportunities"
            )
            return opportunities

        # ── Phase 2: Scan all other events (sports, weather, politics, etc.) ──
        cursor = None
        event_count = 0
        max_event_pages = 20

        for page in range(max_event_pages):
            params = {"limit": 200, "with_nested_markets": True}
            if cursor:
                params["cursor"] = cursor

            try:
                resp = self.client.get_events(**params)
            except Exception as e:
                logger.error(f"Events API error: {e}")
                break

            events = resp.get("events", [])
            cursor = resp.get("cursor", "")

            for event in events:
                event_count += 1
                # Events with nested markets include them inline
                markets = event.get("markets", [])

                if not markets:
                    # Fetch markets for this event
                    event_ticker = event.get("event_ticker", "")
                    if event_ticker:
                        try:
                            mresp = self.client.get_markets(event_ticker=event_ticker, limit=200)
                            markets = mresp.get("markets", [])
                        except Exception:
                            continue

                for market in markets:
                    ticker = market.get("ticker", "")
                    if ticker and ticker not in seen_tickers:
                        seen_tickers.add(ticker)
                        total_scanned += 1
                        try:
                            opp = self._evaluate_market(market)
                        except Exception as e:
                            logger.debug(f"Evaluate failed for {ticker}: {e}")
                            continue
                        if opp:
                            self._market_cache.append(market)
                            opportunities.append(opp)

            if page % 5 == 0 and page > 0:
                logger.info(f"  ...scanned {event_count} events, {total_scanned} markets, {len(opportunities)} opportunities")

            if not cursor or not events:
                break

        self._sort_by_soonest_then_edge(opportunities)
        logger.info(f"Scan complete: {len(opportunities)} opportunities found")
        return opportunities

    def _sort_by_soonest_then_edge(self, opportunities):
        """Sort in place: soonest settlement first, then by largest edge.

        This maximizes turnover speed for faster compounding.
        """
        for opp in opportunities:
            # Attach hours to expiry for sorting
            for market_data in self._market_cache:
                if market_data.get("ticker") == opp.ticker:
                    ct = (market_data.get("expected_expiration_time")
                          or market_data.get("close_time")
                          or market_data.get("expiration_time", ""))
                    opp._hours_left = self._hours_until(ct) if ct else 9999
                    break
            else:
                opp._hours_left = 9999

        opportunities.sort(key=lambda o: (o._hours_left, -abs(o.edge)))

    def _evaluate_market(self, market: dict) -> Optional[Opportunity]:
        """Check a single market for mispricing."""
        ticker = market.get("ticker", "")
        title = market.get("title", ticker)
        event_ticker = market.get("event_ticker", "")

        # Flag crypto tickers - they need CryptoAnalyzer approval later
        is_crypto = any(ticker.startswith(prefix) for prefix in self.CRYPTO_TICKERS)

        # Filter: must be active
        status = market.get("status", "")
        if status not in ("active", "open"):
            return None

        # Filter: must have enough volume (API uses volume_fp)
        volume = self._to_float(market.get("volume_fp", 0) or market.get("volume", 0))
        if volume < self.min_volume:
            return None

        # Filter: must settle within our hour window
        # Use expected_expiration_time first (actual settlement), fall back to close_time
        # Sports markets have close_time weeks out but expected_expiration is game night
        settle_time = (market.get("expected_expiration_time")
                       or market.get("close_time")
                       or market.get("expiration_time"))
        if settle_time:
            hours_left = self._hours_until(settle_time)
            if hours_left > self.max_hours or hours_left < 0.01:
                return None  # Too far out or already expired
        else:
            return None  # No time = skip

        # Get prices - API v2 uses *_dollars fields (already in dollars, not cents)
        yes_bid = self._to_float(market.get("yes_bid_dollars", 0) or market.get("yes_bid", 0))
        yes_ask = self._to_float(market.get("yes_ask_dollars", 0) or market.get("yes_ask", 0))
        no_bid = self._to_float(market.get("no_bid_dollars", 0) or market.get("no_bid", 0))
        no_ask = self._to_float(market.get("no_ask_dollars", 0) or market.get("no_ask", 0))

        if yes_ask <= 0 and no_ask <= 0:
            return None

        # ── Strategy 1: Arbitrage (YES + NO < 1.00) ──
        # If you can buy YES at yes_ask and NO at no_ask for less than $1 total,
        # you profit guaranteed (one side always pays $1)
        if yes_ask > 0 and no_ask > 0:
            total = yes_ask + no_ask
            if total < 0.99:  # less than $0.99 for a guaranteed $1 payout
                arb_edge = 1.0 - total
                side = "yes" if yes_ask <= no_ask else "no"
                price = yes_ask if side == "yes" else no_ask
                return Opportunity(
                    ticker=ticker, event_ticker=event_ticker, title=title,
                    side=side, market_price=price, fair_price=price,
                    edge=arb_edge, volume=volume,
                    yes_bid=yes_bid, yes_ask=yes_ask,
                    no_bid=no_bid, no_ask=no_ask,
                )

        last_price = self._to_float(
            market.get("last_price_dollars", 0) or market.get("last_price", 0)
        )

        # Estimate fair value
        fair_yes = self._estimate_fair_value(market)
        if fair_yes is None:
            return None
        fair_no = 1.0 - fair_yes

        best_opp = None
        best_edge = 0

        # ── Strategy 2: Limit order at fair value ──
        # Place limit buy slightly below fair value. The "edge" is
        # the difference between fair value and where we'd place our order.
        # We place orders at: fair - 1 cent (to get filled when price dips)
        # The profit comes from buying below fair and selling at fair or above.

        # YES side: buy YES if fair > ask (underpriced) or if spread is wide
        if yes_ask > 0.02 and yes_ask < self.max_entry_price:
            # Direct edge: fair value above the ask price
            yes_edge = fair_yes - yes_ask
            if yes_edge >= self.min_edge and yes_edge > best_edge:
                best_edge = yes_edge
                best_opp = Opportunity(
                    ticker=ticker, event_ticker=event_ticker, title=title,
                    side="yes", market_price=yes_ask, fair_price=fair_yes,
                    edge=yes_edge, volume=volume,
                    yes_bid=yes_bid, yes_ask=yes_ask,
                    no_bid=no_bid, no_ask=no_ask,
                )

        # NO side: buy NO if fair_no > no_ask (underpriced)
        if no_ask > 0.02 and no_ask < self.max_entry_price:
            no_edge = fair_no - no_ask
            if no_edge >= self.min_edge and no_edge > best_edge:
                best_edge = no_edge
                best_opp = Opportunity(
                    ticker=ticker, event_ticker=event_ticker, title=title,
                    side="no", market_price=no_ask, fair_price=fair_no,
                    edge=no_edge, volume=volume,
                    yes_bid=yes_bid, yes_ask=yes_ask,
                    no_bid=no_bid, no_ask=no_ask,
                )

        # ── Strategy 3: Wide spread market making ──
        # If spread is > 5 cents, place limit at midpoint to capture spread
        if yes_bid > 0.02 and yes_ask > 0.02 and yes_ask < self.max_entry_price:
            spread = yes_ask - yes_bid
            if spread >= 0.05:
                mid = (yes_bid + yes_ask) / 2
                # Our limit price: just above the bid (bid + 1 cent)
                limit_price = yes_bid + 0.01
                # Edge: fair value minus our entry
                mm_edge = fair_yes - limit_price
                if mm_edge >= self.min_edge and mm_edge > best_edge:
                    best_edge = mm_edge
                    best_opp = Opportunity(
                        ticker=ticker, event_ticker=event_ticker, title=title,
                        side="yes", market_price=limit_price, fair_price=fair_yes,
                        edge=mm_edge, volume=volume,
                        yes_bid=yes_bid, yes_ask=yes_ask,
                        no_bid=no_bid, no_ask=no_ask,
                    )

        # Same for NO side spread
        if no_bid > 0.02 and no_ask > 0.02 and no_ask < self.max_entry_price:
            spread = no_ask - no_bid
            if spread >= 0.05:
                limit_price = no_bid + 0.01
                mm_edge = fair_no - limit_price
                if mm_edge >= self.min_edge and mm_edge > best_edge:
                    best_edge = mm_edge
                    best_opp = Opportunity(
                        ticker=ticker, event_ticker=event_ticker, title=title,
                        side="no", market_price=limit_price, fair_price=fair_no,
                        edge=mm_edge, volume=volume,
                        yes_bid=yes_bid, yes_ask=yes_ask,
                        no_bid=no_bid, no_ask=no_ask,
                    )

        # ── Crypto gate: must pass CryptoAnalyzer ──
        if is_crypto and best_opp and self.crypto_analyzer:
            settle_time = (market.get("expected_expiration_time")
                           or market.get("close_time")
                           or market.get("expiration_time", ""))
            hours_left = self._hours_until(settle_time) if settle_time else 999

            approved, reason = self.crypto_analyzer.should_trade(
                ticker=best_opp.ticker,
                side=best_opp.side,
                strike=0,  # parsed inside analyzer
                hours_to_settle=hours_left,
                ask_price=best_opp.market_price,
            )
            if not approved:
                return None  # Analyst says no

        # ── Weather gate: must pass WeatherAnalyzer (NWS forecast check) ──
        is_weather = ticker.startswith("KXHIGHT") or ticker.startswith("KXLOWT")
        if is_weather and best_opp and self.weather_analyzer:
            approved, reason = self.weather_analyzer.should_trade(
                ticker=best_opp.ticker,
                side=best_opp.side,
                ask_price=best_opp.market_price,
            )
            if not approved:
                logger.debug(f"[WEATHER] {reason}")
                return None  # Forecast says no

        # ── Layer 3: Probability checker - blocks coin-flip trades ──
        if best_opp and self.probability_checker:
            approved, reason = self.probability_checker.should_trade(
                ticker=best_opp.ticker,
                side=best_opp.side,
                entry_price=best_opp.market_price,
                edge=best_opp.edge,
                market_data=market,
            )
            if not approved:
                logger.debug(f"[LAYER3] {reason}")
                return None  # Reality check says no

        return best_opp

    def _estimate_fair_value(self, market: dict) -> Optional[float]:
        """
        Estimate fair probability for YES side.

        Priority:
        0. External odds (Vegas/sportsbook consensus) - HIGHEST confidence
        1. Wide spread midpoint
        2. Last trade divergence
        3. Cross-market implied from NO side
        """
        ticker = market.get("ticker", "")
        yes_bid = self._to_float(market.get("yes_bid_dollars", 0) or market.get("yes_bid", 0))
        yes_ask = self._to_float(market.get("yes_ask_dollars", 0) or market.get("yes_ask", 0))
        no_bid = self._to_float(market.get("no_bid_dollars", 0) or market.get("no_bid", 0))
        no_ask = self._to_float(market.get("no_ask_dollars", 0) or market.get("no_ask", 0))
        last_price = self._to_float(market.get("last_price_dollars", 0) or market.get("last_price", 0))

        estimates = []
        weights = []

        # Strategy 0: External odds (Vegas consensus) - highest weight
        if self.external_odds:
            ext_prob = self.external_odds.get_fair_probability(ticker, market)
            if ext_prob is not None:
                estimates.append(ext_prob)
                weights.append(5.0)  # Very high confidence - real money lines

        # Strategy 1: Wide spread midpoint
        if yes_bid > 0 and yes_ask > 0:
            spread = yes_ask - yes_bid
            mid = (yes_bid + yes_ask) / 2
            if spread > 0.03:
                estimates.append(mid)
                weights.append(2.0)
            else:
                estimates.append(mid)
                weights.append(1.0)

        # Strategy 2: Last trade price
        if 0 < last_price < 1:
            estimates.append(last_price)
            if yes_ask > 0:
                divergence = abs(last_price - yes_ask)
                weights.append(2.0 if divergence > 0.03 else 1.0)
            else:
                weights.append(1.0)

        # Strategy 3: Cross-implied from NO side
        if no_bid > 0 and no_ask > 0:
            no_mid = (no_bid + no_ask) / 2
            implied_yes = 1.0 - no_mid
            if 0 < implied_yes < 1:
                estimates.append(implied_yes)
                weights.append(1.5)

        if not estimates:
            return None

        # Weighted average
        total_weight = sum(weights)
        fair = sum(e * w for e, w in zip(estimates, weights)) / total_weight
        return max(0.01, min(0.99, fair))

    def _estimate_fair_no(self, market: dict) -> Optional[float]:
        """Estimate fair probability for NO side."""
        fair_yes = self._estimate_fair_value(market)
        if fair_yes is None:
            return None
        return 1.0 - fair_yes

    def _hours_until(self, time_str: str) -> float:
        try:
            if time_str.endswith("Z"):
                time_str = time_str[:-1] + "+00:00"
            dt = datetime.fromisoformat(time_str)
            now = datetime.now(timezone.utc)
            return max(0, (dt - now).total_seconds() / 3600)
        except Exception:
            return 9999

    def _days_until(self, time_str: str) -> float:
        return self._hours_until(time_str) / 24

    def _to_float(self, val) -> float:
        try:
            return float(val)
        except (TypeError, ValueError):
            return 0.0
