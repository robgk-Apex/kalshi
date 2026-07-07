"""Layer 3: Probability & reality checker.

Every trade must pass this gate before real money is spent.
Blocks trades that are cheap-for-a-reason (long shots with no real edge).

Categories:
- Weather: checked by WeatherAnalyzer (NWS forecast)
- Crypto: checked by CryptoAnalyzer (price/trend/momentum)
- Sports: requires external odds disagreement OR skip
- Culture/mentions: blocked unless high-volume + clear pattern
- Economics: checked against consensus forecasts
- Commodities: checked against current price + trend
"""

import logging
import re
from typing import Tuple, Optional

logger = logging.getLogger("kalshi-bot.probability")

# Categories that are BLOCKED without external verification
BLOCK_WITHOUT_DATA = [
    "MENTION",      # "Will announcer say X" - pure coin flips
    "SURVIVOR",     # "Will Jeff Probst say X" - unpredictable
    "TRUMPSAY",     # "Will Trump say X" - unpredictable
    "BERNIE",       # "Will Bernie say X" - unpredictable
    "NETFLIX",      # Streaming rankings - hard to predict
    "RANKLISTSONG", # Spotify rankings - hard to predict
    "ALBUMSALES",   # Album sales - need actual sales data
]

# Categories that need external odds (Vegas) to trade
SPORTS_REQUIRE_ODDS = [
    "NBAGAME", "NHLGAME", "NHLSPREAD", "MLBGAME", "MLBRFI",
    "NFLGAME", "NFLSPREAD",
    "LOLGAME", "CS2GAME", "VALORANT",
    "FIFAGAME", "FIFASPREAD",
    "LALIGAGAME", "LALIGA2GAME", "LALIGASPREAD",
    "LIGUE1", "BUNDESLIGA", "SERIEA",
    "DIMAYORGAME", "BRASILEIROGAME",
    "NCAAGAME", "WMARMADROUND",
    "UCLWGAME", "UELGAME",
    "NASCARRACE", "INDYCARRACE",
    "F1FASTLAP", "F1TOP10", "F1RACE",
    "LPGATOUR", "PGATOUR", "PGAH2H",
    "KFTOUR",
    "MLSGAME", "MLSSPREAD",
]

# Categories that are OK to trade with spread analysis alone
SAFE_CATEGORIES = [
    "HIGHT", "LOWT",            # Weather (has its own checker)
    "BTC", "ETH", "SOL",        # Crypto (has its own checker)
    "XRP", "DOGE", "BNB", "HYPE",
    "RAIN",                      # Rain markets (verifiable forecast)
    "JOBLESSCLAIMS",            # Economic data (has consensus)
    "ISMPMI",                   # Economic data
    "CREDITC",                  # Credit card rates (slow-moving, predictable)
    "BRENTD", "BRENTW",        # Oil (has price data)
    "WTID", "WTI",             # Oil
    "GOLDD", "GOLDW",          # Gold
    "SILVERD", "SILVERW",      # Silver
    "COPPERD", "COPPERW", "COPPERMON",  # Copper
    "APRPOTUS",                 # Presidential approval (polling data exists)
    "PARDONSTRUMP",             # Factual - either happened or didn't
    "BILLSCOUNT",               # Factual - public record
    "AUCTIONPRICE",             # Has comparable data
    "AAAGASW",                  # Gas prices (verifiable)
    "VANCEPAKISTAN",            # Factual event - either happens or not
    "TRUMPMEET",                # Factual event
]


class ProbabilityChecker:
    """Gate that blocks trades without real-world probability backing."""

    def __init__(self, external_odds=None):
        self.external_odds = external_odds
        self._sports_odds_cache = {}

    def should_trade(self, ticker: str, side: str, entry_price: float,
                     edge: float, market_data: dict = None) -> Tuple[bool, str]:
        """
        Check if a trade should be allowed.

        Returns (approved, reason)
        """
        ticker_upper = ticker.upper()

        # Step 1: Check if this is a blocked category (mentions, rankings, etc.)
        for blocked in BLOCK_WITHOUT_DATA:
            if blocked in ticker_upper:
                return False, f"BLOCKED: {blocked} markets are unpredictable coin flips"

        # Step 2: Check if this is a sports market requiring external odds
        for sport in SPORTS_REQUIRE_ODDS:
            if sport in ticker_upper:
                return self._check_sports(ticker, side, entry_price, edge, market_data)

        # Step 3: Check if this is a safe category
        for safe in SAFE_CATEGORIES:
            if safe in ticker_upper:
                # Additional sanity check: reject if entry price is suspiciously low
                # and the market is about a future event (not a current fact)
                if entry_price <= 0.03:
                    return False, f"BLOCKED: Entry ${entry_price:.2f} too cheap - likely a long shot"
                return True, f"APPROVED: {safe} category with {edge:.1%} edge"

        # Step 4: Unknown category - apply strict filter
        if entry_price <= 0.05:
            return False, f"BLOCKED: Unknown market at ${entry_price:.2f} - too risky without data"

        if edge < 0.03:
            return False, f"BLOCKED: Unknown market with only {edge:.1%} edge - need 3%+ for unknowns"

        return True, f"APPROVED: Unknown category, edge={edge:.1%}, price=${entry_price:.2f}"

    def _check_sports(self, ticker: str, side: str, entry_price: float,
                      edge: float, market_data: dict = None) -> Tuple[bool, str]:
        """Check sports trades against external odds if available."""

        if self.external_odds:
            # Try to get external probability
            ext_prob = None
            if market_data:
                ext_prob = self.external_odds.get_fair_probability(ticker, market_data)

            if ext_prob is not None:
                # We have external odds - check if Kalshi price disagrees significantly
                if side == "yes":
                    our_prob = ext_prob
                    kalshi_prob = entry_price
                else:
                    our_prob = 1.0 - ext_prob
                    kalshi_prob = entry_price

                disagreement = our_prob - kalshi_prob

                if disagreement < 0.05:
                    return False, (f"BLOCKED: Sports - external odds ({our_prob:.0%}) don't disagree "
                                   f"enough with Kalshi (${entry_price:.2f}). Need 5%+ edge.")

                if our_prob < 0.40:
                    return False, (f"BLOCKED: Sports - external probability only {our_prob:.0%}. "
                                   f"Need 40%+ chance to bet.")

                return True, (f"APPROVED: Sports - external says {our_prob:.0%}, "
                              f"Kalshi at ${entry_price:.2f}, disagreement={disagreement:.0%}")

        # No external odds available - block sports
        return False, "BLOCKED: Sports market without external odds data. Too risky."
