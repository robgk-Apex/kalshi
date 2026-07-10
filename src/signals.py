"""Educated buy/sell suggestion for short-term up/down crypto markets.

Turns real technical indicators — trend (moving averages), momentum, distance
to the strike, volatility, and time to settlement — plus the book's own edge
into a transparent recommendation:

    BUY YES  (bet the coin finishes above the strike / up)
    BUY NO   (bet it finishes below / down)
    HOLD     (no clear, priced-in edge — sit out)

Every recommendation carries a 0-100 confidence and a short list of the reasons
behind it, so it's an explainable read of price action rather than a black box.

HONESTY: hourly up/down crypto is close to a coin flip and any single indicator
is weak. The value here is combining several and being explicit about the
reasoning and confidence — it is NOT a guarantee. Treat low-confidence calls as
noise.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional


def strike_from_market(market: dict) -> float:
    """Extract a market's strike price across Kalshi's formats.

    Hourly markets encode it as a `-T<price>` ticker suffix; the 15-minute
    markets put it in the `floor_strike` field and the title ("Target Price:
    $77.39"). Tries, in order: structured strike fields, the ticker suffix,
    then a dollar amount in the title/subtitle. Returns 0.0 if none found.
    """
    for key in ("floor_strike", "cap_strike", "strike", "strike_price"):
        v = market.get(key)
        if isinstance(v, (int, float)) and v > 0:
            return float(v)
        if isinstance(v, str):
            try:
                f = float(v.replace(",", "").replace("$", ""))
                if f > 0:
                    return f
            except ValueError:
                pass
    for part in str(market.get("ticker", "")).split("-"):
        if part[:1] in ("T", "B"):
            try:
                return float(part[1:])
            except ValueError:
                pass
    for key in ("subtitle", "yes_sub_title", "title", "no_sub_title"):
        m = re.search(r"\$?\s*([\d,]+\.?\d*)", str(market.get(key, "")))
        if m:
            try:
                f = float(m.group(1).replace(",", ""))
                if f > 0:
                    return f
            except ValueError:
                pass
    return 0.0

# Score needed before we'll suggest a trade at all (below this -> HOLD).
DECISION_THRESHOLD = 25.0
# Don't recommend buying a contract richer than this (little payout left).
MAX_ENTRY = 0.85


@dataclass
class Recommendation:
    action: str            # "BUY YES" | "BUY NO" | "HOLD"
    side: str              # "yes" | "no" | ""
    confidence: int        # 0-100
    score: float           # signed: + favors YES/up, - favors NO/down
    reasons: List[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"action": self.action, "side": self.side,
                "confidence": self.confidence, "score": self.score,
                "reasons": self.reasons}


def indicators_from_series(prices: List[float], strike: float) -> Optional[dict]:
    """Compute technical indicators from a list of recent close prices
    (oldest -> newest) relative to a strike. Returns None if there isn't
    enough data."""
    if not prices or len(prices) < 6 or strike <= 0:
        return None
    prices = [float(p) for p in prices if p]
    if len(prices) < 6:
        return None
    price = prices[-1]
    n = len(prices)
    ma_short = sum(prices[-6:]) / len(prices[-6:])
    ma_long = sum(prices[-24:]) / len(prices[-24:]) if n >= 24 else sum(prices) / n
    window = prices[-12:] if n >= 12 else prices
    return {
        "price": price,
        "strike": strike,
        "trend_short": (price - ma_short) / ma_short * 100 if ma_short else 0.0,
        "trend_long": (price - ma_long) / ma_long * 100 if ma_long else 0.0,
        "momentum": (price - prices[-6]) / prices[-6] * 100 if prices[-6] else 0.0,
        "volatility": (max(window) - min(window)) / price * 100 if price else 0.0,
        "distance": (price - strike) / price * 100 if price else 0.0,  # + above
    }


def recommend(ind: Optional[dict], yes_ask: float, no_ask: float,
              hours_to_settle: float, edge: float = 0.0) -> Recommendation:
    """Combine indicators + book edge into a BUY YES / BUY NO / HOLD call.

    A positive score favors YES (price up / above strike); negative favors NO.
    """
    if not ind:
        return Recommendation("HOLD", "", 0, 0.0, ["No price data available"])

    score = 0.0
    reasons: List[str] = []

    # 1) Where is price relative to the strike right now (cushion vs gap)?
    d = ind["distance"]
    if d >= 0:
        score += min(35.0, 8.0 + d * 10.0)
        reasons.append(f"{d:.1f}% above strike (YES in the money)")
    else:
        score -= min(35.0, 8.0 + (-d) * 10.0)
        reasons.append(f"{-d:.1f}% below strike (NO in the money)")

    # 2) Trend (price vs short moving average).
    t = ind["trend_short"]
    if t > 0.3:
        score += 18.0
        reasons.append(f"Uptrend +{t:.1f}% vs short MA")
    elif t < -0.3:
        score -= 18.0
        reasons.append(f"Downtrend {t:.1f}% vs short MA")
    else:
        reasons.append(f"Flat trend ({t:+.1f}%)")

    # 3) Momentum (recent rate of change).
    mo = ind["momentum"]
    if mo > 0.3:
        score += 14.0
        reasons.append(f"Momentum rising +{mo:.1f}%")
    elif mo < -0.3:
        score -= 14.0
        reasons.append(f"Momentum falling {mo:.1f}%")

    # 4) Can it realistically get where it needs to go? (volatility vs gap)
    vol = ind["volatility"]
    need = abs(d)
    if d < 0 and need > vol * 1.5:
        score -= 12.0
        reasons.append(f"Needs +{need:.1f}% but only ~{vol:.1f}% recent range — unlikely")
    elif d > 0 and need > vol * 1.5:
        score += 10.0
        reasons.append(f"{need:.1f}% cushion vs ~{vol:.1f}% range — safe")

    # 5) Time: little time locks in the current standing; lots adds uncertainty.
    if hours_to_settle < 0.5:
        score *= 1.15
        reasons.append(f"{hours_to_settle * 60:.0f}m left — current standing likely holds")
    elif hours_to_settle > 4:
        score *= 0.8
        reasons.append(f"{hours_to_settle:.1f}h out — more can change")

    # 6) Book edge (fair value vs ask) reinforces a mispriced side.
    if edge and edge > 0:
        reasons.append(f"Book edge {edge * 100:.1f}%")

    side = "yes" if score > 0 else "no"
    ask = yes_ask if side == "yes" else no_ask
    confidence = int(min(95.0, abs(score)))

    if abs(score) >= DECISION_THRESHOLD and 0 < ask <= MAX_ENTRY:
        action = "BUY YES" if side == "yes" else "BUY NO"
        if edge and edge > 0:
            confidence = min(97, confidence + 8)
        return Recommendation(action, side, confidence, round(score, 1), reasons[:4])

    # Otherwise HOLD — lead with why we're sitting out.
    if ask and ask > MAX_ENTRY:
        why = f"Ask ${ask:.2f} too rich for the payout"
    else:
        why = "Signals are mixed — no clear edge"
    return Recommendation("HOLD", "", confidence, round(score, 1), [why] + reasons[:3])
