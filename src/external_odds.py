"""External odds fetcher - pulls real Vegas/sportsbook odds to find edge vs Kalshi."""

import logging
import requests
from typing import Dict, Optional, Tuple
from datetime import datetime, timezone

logger = logging.getLogger("kalshi-bot.odds")

# The Odds API - free tier: 500 requests/month
# https://the-odds-api.com/
ODDS_API_BASE = "https://api.the-odds-api.com/v4"

# Sport keys for The Odds API
SPORT_KEYS = {
    "nba": "basketball_nba",
    "nfl": "americanfootball_nfl",
    "mlb": "baseball_mlb",
    "nhl": "icehockey_nhl",
    "ncaab": "basketball_ncaab",
    "ncaaf": "americanfootball_ncaaf",
    "mls": "soccer_usa_mls",
    "epl": "soccer_epl",
    "ufc": "mma_mixed_martial_arts",
}

# Team name mapping: Kalshi abbreviations -> The Odds API team names
TEAM_MAP = {
    # NBA
    "LAL": "Los Angeles Lakers",
    "BKN": "Brooklyn Nets",
    "IND": "Indiana Pacers",
    "BOS": "Boston Celtics",
    "MIL": "Milwaukee Bucks",
    "PHI": "Philadelphia 76ers",
    "NYK": "New York Knicks",
    "MIA": "Miami Heat",
    "CLE": "Cleveland Cavaliers",
    "CHI": "Chicago Bulls",
    "ATL": "Atlanta Hawks",
    "TOR": "Toronto Raptors",
    "CHA": "Charlotte Hornets",
    "WAS": "Washington Wizards",
    "DET": "Detroit Pistons",
    "ORL": "Orlando Magic",
    "DEN": "Denver Nuggets",
    "OKC": "Oklahoma City Thunder",
    "MIN": "Minnesota Timberwolves",
    "DAL": "Dallas Mavericks",
    "PHX": "Phoenix Suns",
    "SAC": "Sacramento Kings",
    "GSW": "Golden State Warriors",
    "LAC": "Los Angeles Clippers",
    "HOU": "Houston Rockets",
    "MEM": "Memphis Grizzlies",
    "NOP": "New Orleans Pelicans",
    "SAS": "San Antonio Spurs",
    "POR": "Portland Trail Blazers",
    "UTA": "Utah Jazz",
    # NFL
    "KC": "Kansas City Chiefs",
    "BUF": "Buffalo Bills",
    "SF": "San Francisco 49ers",
    "BAL": "Baltimore Ravens",
    "DAL": "Dallas Cowboys",
    "GB": "Green Bay Packers",
    "PIT": "Pittsburgh Steelers",
    "NE": "New England Patriots",
    "SEA": "Seattle Seahawks",
    "ARI": "Arizona Cardinals",
    "TB": "Tampa Bay Buccaneers",
    "JAX": "Jacksonville Jaguars",
    "CIN": "Cincinnati Bengals",
    "TEN": "Tennessee Titans",
    "CAR": "Carolina Panthers",
    "LV": "Las Vegas Raiders",
    "NYG": "New York Giants",
    "NYJ": "New York Jets",
    # MLB
    "NYY": "New York Yankees",
    "LAD": "Los Angeles Dodgers",
    "HOU": "Houston Astros",
    # NHL
    "EDM": "Edmonton Oilers",
    "FLA": "Florida Panthers",
    "COL": "Colorado Avalanche",
    "VGK": "Vegas Golden Knights",
}

# Reverse map for lookup
TEAM_REVERSE = {v.lower(): k for k, v in TEAM_MAP.items()}


class ExternalOddsProvider:
    """Fetches real odds from sportsbooks via The Odds API."""

    def __init__(self, api_key: str):
        self.api_key = api_key
        self._cache: Dict[str, dict] = {}  # sport -> {team_pair -> probability}
        self._cache_time: Dict[str, datetime] = {}
        self._requests_used = 0
        self._requests_remaining = None

    def get_fair_probability(self, kalshi_ticker: str, kalshi_market: dict) -> Optional[float]:
        """
        Given a Kalshi market, return the fair probability (0-1) based on
        external sportsbook odds. Returns None if no external data available.
        """
        # Parse the Kalshi ticker to identify sport, teams, and date
        sport, team_abbr, opponent_abbr, game_date = self._parse_kalshi_ticker(kalshi_ticker)
        if not sport or not team_abbr:
            return None

        # Get odds for this sport
        odds_data = self._fetch_sport_odds(sport)
        if not odds_data:
            return None

        # Find the matching game - must match BOTH teams to avoid cross-matching
        team_name = TEAM_MAP.get(team_abbr, "").lower()
        opp_name = TEAM_MAP.get(opponent_abbr, "").lower() if opponent_abbr else None
        if not team_name:
            return None

        for game in odds_data:
            home = game.get("home_team", "").lower()
            away = game.get("away_team", "").lower()

            team_match = team_name in home or team_name in away
            if not team_match:
                continue

            # If we know the opponent, verify it matches too
            if opp_name:
                opp_match = opp_name in home or opp_name in away
                if not opp_match:
                    continue

            # Optional: verify date matches (within 1 day)
            if game_date:
                game_start = game.get("commence_time", "")
                if game_start and not self._dates_match(game_date, game_start):
                    continue

            # Found the correct game
            prob = self._calculate_consensus_probability(game, team_name)
            if prob is not None:
                logger.info(
                    f"[ODDS] {kalshi_ticker}: Vegas fair prob for "
                    f"{team_abbr} = {prob:.4f} "
                    f"(from {len(game.get('bookmakers', []))} books) "
                    f"| {away} @ {home}"
                )
            return prob

        return None

    def _dates_match(self, kalshi_date: str, api_time: str) -> bool:
        """Check if a Kalshi date string (e.g. '26MAR28') matches an API commence_time."""
        try:
            if api_time.endswith("Z"):
                api_time = api_time[:-1] + "+00:00"
            api_dt = datetime.fromisoformat(api_time)
            # Parse Kalshi date: format like 26MAR28 = 2026-03-28
            months = {"JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
                       "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12}
            year = 2000 + int(kalshi_date[:2])
            month_str = kalshi_date[2:5].upper()
            day = int(kalshi_date[5:])
            month = months.get(month_str, 0)
            if not month:
                return True  # Can't parse, allow match
            # Allow 1 day tolerance (games near midnight)
            from datetime import timedelta
            kalshi_dt = datetime(year, month, day, tzinfo=timezone.utc)
            diff = abs((api_dt.date() - kalshi_dt.date()).days)
            return diff <= 1
        except Exception:
            return True  # If parsing fails, don't block the match

    def _parse_kalshi_ticker(self, ticker: str) -> Tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
        """Parse Kalshi ticker to extract sport, team, opponent, and date.

        Examples:
            KXNBAGAME-26MAR25LALIND-LAL -> ('nba', 'LAL', 'IND', '26MAR25')
            KXNFLGAME-26SEP07KCBUF-KC -> ('nfl', 'KC', 'BUF', '26SEP07')
        Returns: (sport, team_abbr, opponent_abbr, date_str)
        """
        ticker_upper = ticker.upper()

        # Detect sport
        sport = None
        if "NBAGAME" in ticker_upper:
            sport = "nba"
        elif "NFLGAME" in ticker_upper:
            sport = "nfl"
        elif "MLBGAME" in ticker_upper:
            sport = "mlb"
        elif "NHLGAME" in ticker_upper:
            sport = "nhl"
        elif "NCAAB" in ticker_upper:
            sport = "ncaab"

        if not sport:
            return None, None, None, None

        parts = ticker.split("-")
        if len(parts) < 3:
            return sport, None, None, None

        # Last part is the team we're betting on
        team_abbr = parts[-1].upper()
        if team_abbr not in TEAM_MAP:
            return sport, None, None, None

        # Middle part contains date + both team abbrs
        # e.g. "26MAR25LALIND" -> date=26MAR25, teams=LAL+IND
        middle = parts[1]
        # Date is first 7 chars: YYMMMDD (e.g. 26MAR25)
        date_str = middle[:7] if len(middle) >= 7 else None
        teams_str = middle[7:] if len(middle) > 7 else ""

        # Extract opponent: teams_str contains both abbrs concatenated
        # e.g. "LALIND" -> remove our team to get opponent
        opponent_abbr = None
        if teams_str:
            # Try removing our team from start or end
            ts = teams_str.upper()
            if ts.startswith(team_abbr):
                opp = ts[len(team_abbr):]
                if opp in TEAM_MAP:
                    opponent_abbr = opp
            elif ts.endswith(team_abbr):
                opp = ts[:-len(team_abbr)]
                if opp in TEAM_MAP:
                    opponent_abbr = opp
            else:
                # Try all known abbreviations
                for abbr in TEAM_MAP:
                    if abbr != team_abbr and abbr in ts:
                        opponent_abbr = abbr
                        break

        return sport, team_abbr, opponent_abbr, date_str

    def _fetch_sport_odds(self, sport: str) -> Optional[list]:
        """Fetch odds for a sport, with 5-minute caching."""
        sport_key = SPORT_KEYS.get(sport)
        if not sport_key:
            return None

        # Check cache (5 min TTL)
        now = datetime.now(timezone.utc)
        if sport in self._cache_time:
            age = (now - self._cache_time[sport]).total_seconds()
            if age < 300:  # 5 minutes
                return self._cache.get(sport)

        try:
            url = f"{ODDS_API_BASE}/sports/{sport_key}/odds/"
            params = {
                "apiKey": self.api_key,
                "regions": "us",
                "markets": "h2h",
                "oddsFormat": "decimal",
            }
            resp = requests.get(url, params=params, timeout=10)

            # Track usage
            self._requests_remaining = resp.headers.get("x-requests-remaining")
            self._requests_used = resp.headers.get("x-requests-used")

            if resp.status_code == 401:
                logger.error("[ODDS] Invalid API key for The Odds API")
                return None
            elif resp.status_code == 429:
                logger.warning("[ODDS] Rate limited - out of credits this month")
                return None

            resp.raise_for_status()
            data = resp.json()

            # Cache it
            self._cache[sport] = data
            self._cache_time[sport] = now

            logger.info(
                f"[ODDS] Fetched {len(data)} games for {sport} "
                f"(credits remaining: {self._requests_remaining})"
            )
            return data

        except Exception as e:
            logger.error(f"[ODDS] Failed to fetch {sport} odds: {e}")
            return None

    def _calculate_consensus_probability(self, game: dict, team_name: str) -> Optional[float]:
        """
        Calculate consensus probability from multiple bookmakers.

        Takes the average implied probability across all bookmakers,
        then removes the vig (overround) to get a fair probability.
        """
        bookmakers = game.get("bookmakers", [])
        if not bookmakers:
            return None

        team_probs = []
        other_probs = []

        for book in bookmakers:
            for market in book.get("markets", []):
                if market.get("key") != "h2h":
                    continue

                outcomes = market.get("outcomes", [])
                team_odds = None
                other_odds = None

                for outcome in outcomes:
                    name = outcome.get("name", "").lower()
                    price = outcome.get("price", 0)
                    if price <= 1:
                        continue

                    if team_name in name:
                        team_odds = price
                    elif name != "draw":
                        other_odds = price

                if team_odds and other_odds:
                    # Implied probability (with vig)
                    team_implied = 1.0 / team_odds
                    other_implied = 1.0 / other_odds
                    total = team_implied + other_implied

                    # Remove vig (normalize to sum to 1.0)
                    fair_prob = team_implied / total
                    team_probs.append(fair_prob)

        if not team_probs:
            return None

        # Consensus = average across bookmakers
        avg_prob = sum(team_probs) / len(team_probs)
        return round(avg_prob, 4)

    def get_usage(self) -> dict:
        return {
            "requests_used": self._requests_used,
            "requests_remaining": self._requests_remaining,
        }
