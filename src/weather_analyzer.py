"""Weather forecast analyzer - checks NWS forecasts before trading weather markets."""

import logging
import re
import time
from datetime import datetime, timezone, timedelta
from typing import Optional, Tuple

logger = logging.getLogger("kalshi-bot.weather")

# NWS API is free, no key needed
NWS_BASE = "https://api.weather.gov"

# Map Kalshi city codes to NWS station/gridpoint info
# Format: (lat, lon) for NWS point lookup
CITY_COORDS = {
    "DAL": (32.7767, -96.7970),    # Dallas
    "DC":  (38.9072, -77.0369),    # Washington DC
    "DEN": (39.7392, -104.9903),   # Denver
    "PHX": (33.4484, -112.0740),   # Phoenix
    "SEA": (47.6062, -122.3321),   # Seattle
    "NYC": (40.7128, -74.0060),    # New York
    "CHI": (41.8781, -87.6298),    # Chicago
    "MIA": (25.7617, -80.1918),    # Miami
    "LAX": (34.0522, -118.2437),   # Los Angeles (LAX area)
    "HOU": (29.7604, -95.3698),    # Houston
    "ATL": (33.7490, -84.3880),    # Atlanta
    "BOS": (42.3601, -71.0589),    # Boston
    "LV":  (36.1699, -115.1398),   # Las Vegas
    "NOLA":(29.9511, -90.0715),    # New Orleans
    "OKC": (35.4676, -97.5164),    # Oklahoma City
    "PHIL":(39.9526, -75.1652),    # Philadelphia
    "AUS": (30.2672, -97.7431),    # Austin
    "SF":  (37.7749, -122.4194),   # San Francisco
}

# Common ticker aliases
TICKER_CITY_MAP = {
    "DALLAS": "DAL", "DAL": "DAL",
    "DENVER": "DEN", "DEN": "DEN",
    "PHOENIX": "PHX", "PHX": "PHX",
    "SEATTLE": "SEA", "SEA": "SEA",
    "NEWYORK": "NYC", "NYC": "NYC", "NY": "NYC",
    "CHICAGO": "CHI", "CHI": "CHI",
    "MIAMI": "MIA", "MIA": "MIA",
    "LOSANGELES": "LAX", "LAX": "LAX", "LA": "LAX",
    "HOUSTON": "HOU", "HOU": "HOU",
    "ATLANTA": "ATL", "ATL": "ATL",
    "BOSTON": "BOS", "BOS": "BOS",
    "LASVEGAS": "LV", "LV": "LV",
    "NEWORLEANS": "NOLA", "NOLA": "NOLA",
    "OKLAHOMACITY": "OKC", "OKC": "OKC",
    "PHILADELPHIA": "PHIL", "PHIL": "PHIL",
    "AUSTIN": "AUS", "AUS": "AUS",
    "SANFRANCISCO": "SF", "SF": "SF",
    "DC": "DC", "WASHINGTON": "DC",
}


class WeatherAnalyzer:
    """Checks NWS forecasts before approving weather trades."""

    def __init__(self):
        self._grid_cache = {}  # city -> (office, gridX, gridY)
        self._forecast_cache = {}  # (city, date) -> {high, low}
        self._cache_time = {}
        import urllib.request
        self._urlopen = urllib.request.urlopen
        self._Request = urllib.request.Request

    def should_trade(self, ticker: str, side: str, ask_price: float) -> Tuple[bool, str]:
        """
        Analyze a weather market and decide if we should trade.

        Returns (approved, reason)
        """
        # Parse the ticker to get city, type (high/low), date, strike
        parsed = self._parse_ticker(ticker)
        if not parsed:
            return False, f"Could not parse weather ticker: {ticker}"

        city, wx_type, date_str, strike, direction = parsed

        # Get the NWS forecast
        forecast = self._get_forecast(city, date_str)
        if not forecast:
            return False, f"Could not get forecast for {city} on {date_str}"

        forecasted_temp = forecast.get("high") if wx_type == "HIGH" else forecast.get("low")
        if forecasted_temp is None:
            return False, f"No {wx_type.lower()} temp forecast for {city}"

        # Determine if the bet makes sense
        # direction: "B" = above (>=), "T" = below (<) based on Kalshi convention
        # But we need to check what side we're betting

        # Calculate the cushion (how far the forecast is from the strike)
        if direction == "B":
            # Market: "Will temp be >= strike?" (above)
            if side == "yes":
                # We're betting temp WILL be >= strike
                cushion = forecasted_temp - strike
                win_prob = self._estimate_probability(cushion, wx_type)
                reason_detail = f"{city} forecast={forecasted_temp}°F, strike={strike}°F, cushion={cushion:+.1f}°F"
            else:
                # We're betting temp will NOT be >= strike (will be below)
                cushion = strike - forecasted_temp
                win_prob = self._estimate_probability(cushion, wx_type)
                reason_detail = f"{city} forecast={forecasted_temp}°F, strike={strike}°F, cushion={cushion:+.1f}°F (betting below)"
        else:
            # direction == "T": Market: "Will temp be < strike?" (below)
            if side == "yes":
                # We're betting temp WILL be < strike
                cushion = strike - forecasted_temp
                win_prob = self._estimate_probability(cushion, wx_type)
                reason_detail = f"{city} forecast={forecasted_temp}°F, strike={strike}°F, cushion={cushion:+.1f}°F"
            else:
                # We're betting temp will NOT be < strike (will be above)
                cushion = forecasted_temp - strike
                win_prob = self._estimate_probability(cushion, wx_type)
                reason_detail = f"{city} forecast={forecasted_temp}°F, strike={strike}°F, cushion={cushion:+.1f}°F (betting above)"

        # Decision criteria
        # 1. Must have positive cushion (forecast in our favor)
        if cushion < 0:
            return False, f"REJECTED: {reason_detail} - forecast AGAINST us"

        # 2. Win probability must be >= 55%
        if win_prob < 0.55:
            return False, f"REJECTED: {reason_detail} - win prob {win_prob:.0%} too low"

        # 3. Expected value must be positive
        # EV = (win_prob * (1.0 - ask)) - ((1 - win_prob) * ask)
        ev = (win_prob * (1.0 - ask_price)) - ((1 - win_prob) * ask_price)
        if ev < 0.02:
            return False, f"REJECTED: {reason_detail} - EV={ev:.4f} too low"

        # 4. Higher confidence for higher priced contracts
        if ask_price > 0.15 and win_prob < 0.70:
            return False, f"REJECTED: {reason_detail} - price ${ask_price:.2f} needs 70%+ prob, got {win_prob:.0%}"

        score_parts = []
        if cushion >= 10:
            score_parts.append(f"HUGE cushion ({cushion:+.1f}°F)")
        elif cushion >= 5:
            score_parts.append(f"GOOD cushion ({cushion:+.1f}°F)")
        else:
            score_parts.append(f"TIGHT cushion ({cushion:+.1f}°F)")

        score_parts.append(f"prob={win_prob:.0%}")
        score_parts.append(f"EV={ev:.4f}")
        score_parts.append(f"forecast={forecasted_temp}°F vs strike={strike}°F")

        reason = f"APPROVED: {reason_detail} | {' | '.join(score_parts)}"
        logger.info(f"[WEATHER] {reason}")
        return True, reason

    def _estimate_probability(self, cushion: float, wx_type: str) -> float:
        """
        Estimate win probability based on forecast cushion.

        NWS forecasts have typical errors:
        - High temp: ~3-5°F standard deviation
        - Low temp: ~3-5°F standard deviation
        - Bigger errors in spring/fall, smaller in summer

        We model this as a normal distribution with std=4°F
        """
        import math

        std_dev = 4.0  # Typical NWS forecast error in °F

        if cushion <= 0:
            # Forecast is against us
            # Still some chance of winning due to forecast error
            z = cushion / std_dev
            # Approximate normal CDF
            prob = 0.5 * (1 + math.erf(z / math.sqrt(2)))
            return prob
        else:
            # Forecast is in our favor
            z = cushion / std_dev
            prob = 0.5 * (1 + math.erf(z / math.sqrt(2)))
            return prob

    def _parse_ticker(self, ticker: str) -> Optional[tuple]:
        """
        Parse a weather ticker like:
        KXHIGHTDAL-26MAR28-B53.5  -> (DAL, HIGH, 26MAR28, 53.5, B)
        KXLOWTDEN-26MAR28-T36.5   -> (DEN, LOW, 26MAR28, 36.5, T)
        """
        ticker = ticker.upper()

        # Match pattern: KX(HIGHT|LOWT)(CITY)-(DATE)-(B|T)(STRIKE)
        m = re.match(
            r'KX(HIGHT|LOWT)(\w+)-(\d{2}\w{3}\d{2})-(B|T)([\d.]+)',
            ticker
        )
        if not m:
            return None

        wx_type = "HIGH" if m.group(1) == "HIGHT" else "LOW"
        city_raw = m.group(2)
        date_str = m.group(3)
        direction = m.group(4)  # B = above/below threshold, T = above/below threshold
        strike = float(m.group(5))

        # Map city
        city = TICKER_CITY_MAP.get(city_raw)
        if not city:
            # Try partial match
            for key, val in TICKER_CITY_MAP.items():
                if key in city_raw or city_raw in key:
                    city = val
                    break

        if not city:
            logger.debug(f"Unknown city: {city_raw}")
            return None

        return (city, wx_type, date_str, strike, direction)

    def _get_forecast(self, city: str, date_str: str) -> Optional[dict]:
        """Get NWS forecast for a city and date."""
        cache_key = (city, date_str)

        # Check cache (valid for 30 minutes)
        if cache_key in self._forecast_cache:
            if time.time() - self._cache_time.get(cache_key, 0) < 1800:
                return self._forecast_cache[cache_key]

        coords = CITY_COORDS.get(city)
        if not coords:
            return None

        try:
            # Step 1: Get grid info
            grid = self._get_grid(city, coords)
            if not grid:
                return None

            office, gridX, gridY = grid

            # Step 2: Get forecast
            url = f"{NWS_BASE}/gridpoints/{office}/{gridX},{gridY}/forecast"
            req = self._Request(url, headers={"User-Agent": "kalshi-bot/1.0"})

            import json
            response = self._urlopen(req, timeout=10)
            data = json.loads(response.read().decode())

            # Parse the target date
            target_date = self._parse_date(date_str)
            if not target_date:
                return None

            # Find the matching forecast period
            periods = data.get("properties", {}).get("periods", [])

            high_temp = None
            low_temp = None

            for period in periods:
                start = period.get("startTime", "")
                try:
                    if start.endswith("Z"):
                        start = start[:-1] + "+00:00"
                    period_date = datetime.fromisoformat(start).date()
                except:
                    continue

                if period_date == target_date:
                    temp = period.get("temperature")
                    is_day = period.get("isDaytime", True)

                    if is_day and temp is not None:
                        high_temp = temp
                    elif not is_day and temp is not None:
                        low_temp = temp

            result = {}
            if high_temp is not None:
                result["high"] = high_temp
            if low_temp is not None:
                result["low"] = low_temp

            if result:
                self._forecast_cache[cache_key] = result
                self._cache_time[cache_key] = time.time()
                logger.info(f"[WEATHER] Forecast for {city} on {date_str}: {result}")
                return result

        except Exception as e:
            logger.warning(f"[WEATHER] NWS API error for {city}: {e}")

        return None

    def _get_grid(self, city: str, coords: tuple) -> Optional[tuple]:
        """Get NWS grid info for coordinates."""
        if city in self._grid_cache:
            return self._grid_cache[city]

        try:
            lat, lon = coords
            url = f"{NWS_BASE}/points/{lat},{lon}"
            req = self._Request(url, headers={"User-Agent": "kalshi-bot/1.0"})

            import json
            response = self._urlopen(req, timeout=10)
            data = json.loads(response.read().decode())

            props = data.get("properties", {})
            office = props.get("gridId")
            gridX = props.get("gridX")
            gridY = props.get("gridY")

            if office and gridX is not None and gridY is not None:
                result = (office, gridX, gridY)
                self._grid_cache[city] = result
                return result

        except Exception as e:
            logger.warning(f"[WEATHER] Grid lookup error for {city}: {e}")

        return None

    def _parse_date(self, date_str: str) -> Optional[object]:
        """Parse date like '26MAR28' -> date(2026, 3, 28)"""
        months = {
            "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
            "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12
        }

        m = re.match(r'(\d{2})([A-Z]{3})(\d{2})', date_str.upper())
        if not m:
            return None

        year = 2000 + int(m.group(1))
        month = months.get(m.group(2))
        day = int(m.group(3))

        if not month:
            return None

        from datetime import date
        try:
            return date(year, month, day)
        except:
            return None
