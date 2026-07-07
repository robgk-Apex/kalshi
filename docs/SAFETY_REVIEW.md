# Safety review — live-trading logic

Scope: the active bot reachable from `python -m src` (`src/__main__.py`,
`scanner.py`, `risk_manager.py`, `executor.py`, `api_client.py`,
`paper_trader.py`, and the trade-gate modules). The orphaned second
implementation (`src/main.py` + `client/execution/portfolio/risk/strategies/models`)
was deleted before this review.

Headline: in **LIVE** mode, as originally written, **neither the stop-loss nor
the daily-loss limit reliably protected real money.** One of the two is now
fixed; the other and several related issues are documented below and left for a
decision because the correct fix depends on the live Kalshi API and/or on
trading-strategy intent.

Severity: CRITICAL = can lose real money / defeats a stated safety feature.

---

## FIXED

### C1 — Live stop-loss was anchored to a config placeholder, not the real balance ✅ fixed
`risk_manager.py`, `__main__.py`

`RiskManager.__init__` set `starting_bankroll = config["risk"]["bankroll"]`
(default **100**), and `update_bankroll()` only moved `self.bankroll`, never the
anchor. The stop-loss test `bankroll < starting_bankroll * (1 - stop_loss_pct)`
therefore reduced to a fixed `< $80` line unrelated to the account.

- Fund with **$1,000** (config left at `bankroll: 100`) → "20% stop-loss" would
  not halt until below **$80**, i.e. after a **~92% loss**.
- Fund with **$50** → halted before placing a single trade (`50 < 80`).

**Fix applied:** `update_bankroll()` now anchors `starting_bankroll` to the real
balance on the first sync (guarded by `_starting_bankroll_synced` so later syncs
don't move it). Covered by `tests/test_bot.py::TestRiskManager`
(`test_update_bankroll_anchors_starting_bankroll`,
`test_stop_loss_scales_with_real_balance`, `test_starting_bankroll_only_anchors_once`).

### L1 — A single malformed market could crash an entire scan ✅ fixed
`scanner.py`

`scan()` is called unguarded from the main loop, and the per-market
`_evaluate_market()` calls were not wrapped, so one bad market (or a future
change in a gate module) could propagate out and take the bot down. Both
call sites now `try/except` and skip the offending market.

---

## OPEN — need your decision

### C2 — Daily-loss limit is a complete no-op in LIVE mode
`risk_manager.py` (`check_halt` reads `daily_pnl`; `record_trade` sets it)

`daily_pnl` is only ever changed by `record_trade()`, and **`record_trade` is
never called anywhere in the active code.** In live mode there is no fill or
settlement accounting at all (`paper.check_settlements` runs only in dry-run).
So `daily_pnl` is stuck at `0.0` and the daily-loss halt **never triggers**, no
matter how much is lost in a day.

Correct fix requires wiring realized P&L into `risk.record_trade(...)` each
scan by polling `client.get_fills()` / settled `client.get_positions()`. Left
open because it depends on Kalshi's live response schema (field names for
realized P&L), which cannot be verified here without API access.

### C3 — The "arbitrage" branch places a single-leg naked bet and skips every safety gate
`scanner.py` (`_evaluate_market`, the `yes_ask + no_ask < 0.99` branch)

When `yes_ask + no_ask < 0.99` the code builds an `Opportunity` for **only the
cheaper leg** and `return`s immediately. That is not arbitrage (real arb buys
*both* legs so one always pays $1) — it's a directional bet on the
market-implied *less likely* side. Additionally:

- It sets `edge = 1 - (yes_ask + no_ask)` and `size_position` then computes
  `win_prob = price + edge`. Example `yes_ask = no_ask = 0.30` → `edge = 0.40`,
  `win_prob = 0.70`, tier **MAX** (up to 6% / ~60 contracts): a large,
  aggressively sized bet derived from a fabricated probability.
- The early `return` happens **before** the crypto / weather / probability
  gates, so these signals bypass all trade-blocking safety layers.

This branch fires exactly when a book is crossed/stale — when you least want to
auto-buy one leg at size. Options: (a) execute both legs atomically for true
arb, (b) remove the branch, or (c) at minimum route it through the gates and
stop deriving Kelly `win_prob` from `1 - (yes + no)`. This is a
**strategy decision**, so it is left to you.

### C4 — Live position count and duplicate-guard are not synced to the account — ⚠️ partially fixed
`__main__.py`, `executor.py`, `risk_manager.py`

`max_positions` is enforced via `risk.open_positions`. In live mode, originally:
- `open_positions` started at **0** every process start and was **only
  incremented** (`record_open`); `record_close` is never called. It also
  increments on *resting/unfilled* limit orders.
- `held_tickers` (the re-buy guard) started **empty** in live mode (only
  pre-seeded from paper positions) and is never persisted.

So after any restart (crash, deploy, STOP), the bot forgot its real positions:
`max_positions` was defeated and it could re-buy tickers it already held →
over-exposure beyond the configured cap.

**Fix applied:** at live startup the bot now seeds `held_tickers` and
`open_positions` from `client.get_positions()` (`fetch_live_positions`, which
fails safe — returns `None` on error so state isn't wiped on a transient API
hiccup). This resolves the restart-over-exposure failure. Covered by
`tests/test_bot.py::TestLivePositionSync`.

**Residual (needs the C2 fill-accounting work to fully close):** within a single
long-running session, `open_positions` is still only incremented and not
decremented on settlement, and resting-but-unfilled orders aren't reconciled
against `get_orders()`. The drift is *conservative* (it can stop trading early,
not over-trade). A periodic in-loop resync from `get_positions()` would remove
the drift but shares the live-API-schema uncertainty noted in C2.

### M1 — Stop-loss measures deployed cash, not equity
`risk_manager.py`, `__main__.py`

In live mode `bankroll` is refreshed to account **cash** each scan. Buying
contracts lowers cash immediately, so the halt conflates capital deployment
with loss. Usually errs safe (halts early), but it does not measure real P&L.
Proper fix ties into C2: track equity = cash + mark-to-market position value.

---

## Verified correct (no action)

- Dollars→cents order conversion `int(price * 100)` (`api_client.py`).
- Side routing: YES→`yes_price`, NO→`no_price`; NO priced at `no_ask`
  (`executor.py`).
- Per-trade dollar caps: `min(kelly*bankroll, max_pct*bankroll)` then
  `min(..., 200.0)`; contract count derived from the capped dollars and only
  reduced by the tier cap. No wrong-side / buy-vs-sell bug outside C3.
- Non-arb `win_prob = price + edge` correctly reduces to fair value for the
  edge / market-making strategies.

## Minor notes (low impact)

- `risk_manager.py`: `contracts = max(1, ...)` forces a minimum of 1 contract
  even when the computed size rounds to 0.
- `scanner.py`: price reads fall back from `*_dollars` to raw `*` fields; if the
  API ever returns only cents-denominated fields they'd be read as dollars and
  every market silently filtered (a no-op failure, not a bad order).
- `executor.py`: `get_summary` counts the cost of resting/unfilled orders as
  "deployed" (cosmetic reporting only).
