# Kalshi Trading Bot

A bot that scans Kalshi markets and places limit orders on detected mispricings.
It now focuses on **short-term "up/down" crypto** markets (BTC/ETH/SOL/… hourly
directional contracts).

New here? Start with [`SETUP.txt`](SETUP.txt).

## Run modes

```bash
python -m src --dry-run        # paper trade against REAL Kalshi data (needs API keys)
python -m src --live-confirm   # LIVE — real money
```

`--dry-run` scans real markets and logs the trades it *would* make without
placing any orders. It needs a working Kalshi connection (API key + network),
so run it from your own machine — see `SETUP.txt`.

## Paper-trade simulation (no keys, no network)

To see the whole pipeline (scan → size → execute → settle → P&L) without a
Kalshi connection, run the offline simulator. It drives the *actual* bot
components over synthetic-but-realistic up/down crypto markets:

```bash
python scripts/paper_sim.py --scenario mixed --cycles 300
python scripts/paper_sim.py --scenario informed   # a real price signal -> profits
python scripts/paper_sim.py --scenario noise       # a meaningless signal -> loses
python scripts/paper_sim.py --scenario efficient   # no signal -> bot sits out
```

**What it teaches:** for crypto this bot has no external fair-value model — it
trades when the *last* trade price diverges from the current bid/ask. So it only
makes money if that divergence is informative. The `noise` scenario (divergence
unrelated to the outcome) *loses ~20%*, which is the honest risk of the
heuristic. Synthetic markets are a controlled model, **not** a prediction of
live Kalshi behavior — always `--dry-run` against real data before going live.

## Live dashboard

A zero-dependency visual dashboard of the up/down crypto markets, auto-refreshing
in your browser with YES/NO books, live settlement countdowns, and the bot's
detected signals:

```bash
python scripts/dashboard.py --config config/config.yaml   # LIVE Kalshi data
python scripts/dashboard.py --demo                         # synthetic, no keys
```

Then open <http://localhost:8787>. Live mode needs your API keys and a network
that can reach Kalshi; use `--demo` anywhere else to preview the screen.

**Educated buy/sell suggestions.** Each market shows a **BUY YES / BUY NO /
HOLD** recommendation with a confidence score and its reasons (hover it). It's
built by `src/signals.py` from real technical indicators — trend (moving
averages), momentum, distance to the strike, volatility, and time to settle —
plus the book's own edge. In LIVE mode the indicators come from real crypto
prices (via `crypto_analyzer.py`). It's a transparent, explainable read of price
action, **not** a guarantee — hourly up/down crypto is close to a coin flip.

**Track your trades.** Click **Take** on any market to log a trade you made. The
dashboard keeps a ledger (`logs/dashboard_ledger.json`) and shows an **active
P&L** that updates as your positions settle — a win pays $1/contract, a loss
pays $0. Realized P&L counts only settled trades; open positions are marked to
the current price as unrealized. (Settlement outcomes come from Kalshi, so
realized P&L advances in LIVE mode; in `--demo` trades stay open.)

## Focus mode

`config/config.yaml` selects what gets scanned:

```yaml
strategy:
  mode: crypto_short        # only short-term up/down crypto (default)
  # mode: all               # crypto + every other market (original behavior)
  max_hours_to_expiry: 2    # ignore anything settling further out
```

## Safety

Read [`docs/SAFETY_REVIEW.md`](docs/SAFETY_REVIEW.md) before trading real money.
It documents the money-safety review, the fixes already applied (stop-loss
anchoring, restart position sync, scan robustness), and the open issues that
still need decisions (the live daily-loss limit and the single-leg "arbitrage"
branch).

## Tests

```bash
pip install -r requirements.txt pytest
python -m pytest -q
```
