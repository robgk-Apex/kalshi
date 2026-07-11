"""Outcome prediction for short-term crypto strike markets.

Turns real technical indicators — trend (moving averages), momentum, distance
to the strike, volatility, and time to settlement — into a transparent call of
the likely CORRECT outcome:

    YES / NO            (predict it finishes at/above — or below — the strike)
    LEAN YES / LEAN NO  (same call, low conviction — still the favored side)
    NO DATA             (only when there isn't enough history to read a chart)

It always commits to a side when it has data — the lean is never withheld, it's
just labelled. The read is built like a trader's: a volatility-scaled
probability that the coin finishes in the money (gap to strike measured in units
of the expected move over the time left), then nudged by RSI (overbought/oversold)
and MACD (trend). It predicts the RESULT, NOT a trade's value — it ignores how
the contract is priced, so a likely YES is called YES even at a rich ask.

HONESTY: short-horizon crypto is noisy and no indicator is a guarantee. The
model gives a calibrated-ish probability and its reasoning, not certainty.
"""

from __future__ import annotations

import math
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

# Confidence (0-100) above which we print a firm YES/NO; below it we still pick
# the favored side but label it LEAN YES / LEAN NO. We never refuse to call.
DECISION_THRESHOLD = 25.0
# Candle spacing of the price series, in minutes (Coinbase feed = 5-min candles).
DEFAULT_INTERVAL_MIN = 5.0


# How much to trust the market's own price vs the chart. The market price is the
# best available forecast of the outcome, so it gets the majority weight; the
# chart tilts it rather than overriding it.
MARKET_WEIGHT = 0.72
CHART_WEIGHT = 1.0 - MARKET_WEIGHT


@dataclass
class Recommendation:
    action: str            # "YES" | "NO" | "LEAN YES" | "LEAN NO" | "NO DATA"
    side: str              # "yes" | "no"
    confidence: int        # 0-100
    score: float           # signed: + favors YES/up, - favors NO/down
    reasons: List[str] = field(default_factory=list)
    probability: float = 0.5   # blended P(finishes at/above strike), 0-1
    ev: float = 0.0            # expected value per $1 staked on the called side

    def as_dict(self) -> dict:
        return {"action": self.action, "side": self.side,
                "confidence": self.confidence, "score": self.score,
                "reasons": self.reasons, "probability": self.probability,
                "ev": self.ev}


# ── chart-reading primitives ────────────────────────────────────────────────
def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _logit(p: float) -> float:
    p = min(0.999, max(0.001, p))
    return math.log(p / (1.0 - p))


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, x))))


def _mean(xs: List[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def _stdev(xs: List[float]) -> float:
    if len(xs) < 2:
        return 0.0
    m = _mean(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))


def _log_returns(prices: List[float]) -> List[float]:
    out = []
    for i in range(1, len(prices)):
        if prices[i - 1] > 0 and prices[i] > 0:
            out.append(math.log(prices[i] / prices[i - 1]))
    return out


def _ema_series(vals: List[float], period: int) -> List[float]:
    if not vals:
        return []
    k = 2.0 / (period + 1)
    e = vals[0]
    out = [e]
    for v in vals[1:]:
        e = v * k + e * (1 - k)
        out.append(e)
    return out


def _rsi(prices: List[float], period: int = 14) -> Optional[float]:
    """Wilder-style Relative Strength Index over the last `period` changes."""
    if len(prices) < period + 1:
        return None
    gains = losses = 0.0
    for i in range(len(prices) - period, len(prices)):
        ch = prices[i] - prices[i - 1]
        if ch >= 0:
            gains += ch
        else:
            losses -= ch
    avg_gain, avg_loss = gains / period, losses / period
    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0
    rs = avg_gain / avg_loss
    return 100.0 - 100.0 / (1.0 + rs)


def _macd_hist(prices: List[float]) -> Optional[float]:
    """MACD histogram (macd line − signal), the classic 12/26/9 setup."""
    if len(prices) < 26:
        return None
    e12 = _ema_series(prices, 12)
    e26 = _ema_series(prices, 26)
    macd = [a - b for a, b in zip(e12, e26)]
    signal = _ema_series(macd, 9)
    return macd[-1] - signal[-1]


def indicators_from_series(prices: List[float], strike: float) -> Optional[dict]:
    """Read the chart: trend, momentum, RSI, MACD, and — most importantly for a
    'will it hit the strike' question — the per-candle volatility used to size
    the expected move. Oldest -> newest closes. None if too little data."""
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
    rets = _log_returns(prices)
    return {
        "price": price,
        "strike": strike,
        "trend_short": (price - ma_short) / ma_short * 100 if ma_short else 0.0,
        "trend_long": (price - ma_long) / ma_long * 100 if ma_long else 0.0,
        "momentum": (price - prices[-6]) / prices[-6] * 100 if prices[-6] else 0.0,
        "volatility": (max(window) - min(window)) / price * 100 if price else 0.0,
        "distance": (price - strike) / price * 100 if price else 0.0,  # + above
        "sigma_step": _stdev(rets),       # per-candle log-return volatility
        "mu_step": _mean(rets),           # per-candle drift
        "rsi": _rsi(prices),
        "macd_hist": _macd_hist(prices),
    }


def recommend(ind: Optional[dict], yes_ask: float = 0.0, no_ask: float = 0.0,
              hours_to_settle: float = 1.0,
              interval_minutes: float = DEFAULT_INTERVAL_MIN) -> Recommendation:
    """Predict whether the coin finishes AT/ABOVE the strike.

    Two forecasts are blended in log-odds:
      • the MARKET's own implied probability (from the YES/NO prices) — the best
        available forecast of the outcome, so it carries the majority weight; and
      • a CHART model — a volatility-scaled probability-to-strike (how options
        desks read 'probability in the money': gap to strike in units of the
        expected move over the time left), nudged by RSI and MACD.
    The chart tilts the market's odds rather than overriding them, which stops
    the predictor from confidently betting against a fairly-priced market.

    Using the price as a probability estimate is NOT arbitrage — it's using the
    best forecast to predict the outcome. `ev` reports the expected value of
    entering the called side at its ask, so a bad-value click is visible. Always
    commits to a side when there's data; NO DATA only when history is missing.
    """
    # The ONLY non-directional outcome: we don't have enough history to read.
    if not ind:
        return Recommendation("NO DATA", "", 0, 0.0,
                              ["Not enough price history yet"], 0.5)

    price, strike = ind["price"], ind["strike"]
    reasons: List[str] = []

    # 1) Volatility-scaled probability the coin finishes at/above the strike.
    sigma_step = ind.get("sigma_step") or 0.0
    steps = max(1.0, hours_to_settle * 60.0 / max(1e-6, interval_minutes))
    # Recent realized vol UNDERstates the move to come (quiet != quiet ahead), so
    # buffer it and floor it — this is what stops false 99% calls on coin flips.
    sigma_h = sigma_step * math.sqrt(steps) * 1.3
    sigma_h = max(sigma_h, 0.006)
    drift_h = ind.get("mu_step", 0.0) * steps
    drift_h = max(-0.5 * sigma_h, min(0.5 * sigma_h, drift_h))  # damp noisy drift
    log_gap = math.log(price / strike) if price > 0 and strike > 0 else 0.0
    z = (log_gap + drift_h) / sigma_h
    p = _norm_cdf(z)

    dist_sigma = log_gap / sigma_h
    if dist_sigma >= 0:
        reasons.append(f"{dist_sigma:.2f}σ cushion above strike over the time left")
    else:
        reasons.append(f"{-dist_sigma:.2f}σ gap below strike to make up")

    # 2) RSI — overbought/oversold mean-reversion risk (nudge in σ-space).
    rsi = ind.get("rsi")
    if rsi is not None:
        if rsi >= 70:
            z -= 0.12
            reasons.append(f"RSI {rsi:.0f} — overbought, pullback risk")
        elif rsi <= 30:
            z += 0.12
            reasons.append(f"RSI {rsi:.0f} — oversold, bounce risk")
        else:
            reasons.append(f"RSI {rsi:.0f} — neutral")

    # 3) MACD — trend/momentum confirmation.
    mh = ind.get("macd_hist")
    if mh is not None:
        if mh > 0:
            z += 0.10
            reasons.append("MACD bullish (histogram > 0)")
        elif mh < 0:
            z -= 0.10
            reasons.append("MACD bearish (histogram < 0)")

    # 4) Short-term trend vs moving average, as confirmation colour.
    t = ind["trend_short"]
    if t > 0.3:
        reasons.append(f"Uptrend +{t:.1f}% vs short MA")
    elif t < -0.3:
        reasons.append(f"Downtrend {t:.1f}% vs short MA")

    # Chart model's probability (bounded — it's noisier than the market).
    p_chart = max(0.05, min(0.95, _norm_cdf(z)))

    # Market's own implied P(YES). Buying NO at no_ask ≈ selling YES at 1-no_ask,
    # so yes_mid ≈ (yes_ask + (1 - no_ask)) / 2 — the crowd's forecast.
    p_market = None
    if yes_ask > 0 and no_ask > 0:
        p_market = max(0.02, min(0.98, (yes_ask + (1.0 - no_ask)) / 2.0))
    elif yes_ask > 0:
        p_market = max(0.02, min(0.98, yes_ask))
    elif no_ask > 0:
        p_market = max(0.02, min(0.98, 1.0 - no_ask))

    if p_market is not None:
        p = _sigmoid(MARKET_WEIGHT * _logit(p_market) + CHART_WEIGHT * _logit(p_chart))
        reasons.insert(0, f"Market odds ~{p_market * 100:.0f}% · chart read ~{p_chart * 100:.0f}%")
    else:
        p = p_chart
    p = max(0.02, min(0.98, p))

    score = (p - 0.5) * 200.0             # -100 (NO) .. +100 (YES)
    side = "yes" if p >= 0.5 else "no"
    confidence = int(min(97.0, abs(score)))
    p_side = p if side == "yes" else 1.0 - p

    # Expected value of entering the called side at its ask ($1 payout if right).
    entry = yes_ask if side == "yes" else no_ask
    ev = (p_side / entry - 1.0) if entry and entry > 0 else 0.0
    lead = (f"Best estimate: ~{p_side * 100:.0f}% "
            f"{'YES — finishes at/above strike' if side == 'yes' else 'NO — finishes below strike'}")
    reasons = [lead] + reasons[:3]
    if entry and entry > 0:
        tag = "good value" if ev > 0 else "overpriced — likely -EV"
        reasons.append(f"Entry ${entry:.2f} → EV {ev * 100:+.0f}% ({tag})")

    firm = confidence >= DECISION_THRESHOLD
    if side == "yes":
        action = "YES" if firm else "LEAN YES"
    else:
        action = "NO" if firm else "LEAN NO"
    return Recommendation(action, side, confidence, round(score, 1),
                          reasons, round(p, 3), round(ev, 3))
