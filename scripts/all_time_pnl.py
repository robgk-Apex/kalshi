"""Calculate all-time P&L across every run since day 1."""
import json
import sys
sys.path.insert(0, ".")

from src.api_client import KalshiClient
import yaml

config = yaml.safe_load(open("config/config.yaml"))
api = config["api"]
client = KalshiClient(api["base_url"], api["key_id"], api["private_key_path"])

all_trades = [
    # Run 1: Original trades (Mar 25)
    {"ticker": "KXUSDBRLMAX-26DEC31-T6.7499", "side": "no", "contracts": 20, "entry": 0.09, "run": "Run1-RTX"},
    {"ticker": "KXRTX5090MON-26MAR31-0.605", "side": "no", "contracts": 20, "entry": 0.10, "run": "Run1-RTX"},
    {"ticker": "KXRTX5090MON-26MAR31-0.545", "side": "no", "contracts": 20, "entry": 0.10, "run": "Run1-RTX"},
    {"ticker": "KXRTX5090MON-26MAR31-0.555", "side": "no", "contracts": 20, "entry": 0.10, "run": "Run1-RTX"},
    {"ticker": "KXRTX5090MON-26MAR31-0.635", "side": "no", "contracts": 20, "entry": 0.11, "run": "Run1-RTX"},
    {"ticker": "KXRTX5090MON-26MAR31-0.615", "side": "no", "contracts": 20, "entry": 0.12, "run": "Run1-RTX"},
    {"ticker": "KXRTX5090MON-26MAR31-0.625", "side": "no", "contracts": 20, "entry": 0.12, "run": "Run1-RTX"},
    {"ticker": "KXRTX5090MON-26MAR31-0.645", "side": "no", "contracts": 20, "entry": 0.12, "run": "Run1-RTX"},
    {"ticker": "KXRTX5090MON-26MAR31-0.375", "side": "yes", "contracts": 20, "entry": 0.10, "run": "Run1-RTX"},
    {"ticker": "KXRTX5090MON-26MAR31-0.575", "side": "no", "contracts": 20, "entry": 0.10, "run": "Run1-RTX"},

    # Weather trades
    {"ticker": "KXHIGHTDAL-26MAR28-T58", "side": "yes", "contracts": 40, "entry": 0.13, "run": "Weather"},
    {"ticker": "KXHIGHTPHX-26MAR28-B89.5", "side": "yes", "contracts": 40, "entry": 0.17, "run": "Weather"},
    {"ticker": "KXHIGHTSEA-26MAR28-B51.5", "side": "yes", "contracts": 40, "entry": 0.10, "run": "Weather"},
    {"ticker": "KXHIGHTDC-26MAR28-B53.5", "side": "yes", "contracts": 40, "entry": 0.06, "run": "Weather"},
    {"ticker": "KXLOWTDEN-26MAR28-B38.5", "side": "yes", "contracts": 40, "entry": 0.04, "run": "Weather"},
    {"ticker": "KXLOWTAUS-26MAR28-B53.5", "side": "yes", "contracts": 36, "entry": 0.13, "run": "Weather"},
    {"ticker": "KXLOWTMIA-26MAR28-B64.5", "side": "yes", "contracts": 80, "entry": 0.13, "run": "Weather"},
    {"ticker": "KXLOWTLAX-26MAR28-B60.5", "side": "yes", "contracts": 40, "entry": 0.10, "run": "Weather"},
    {"ticker": "KXLOWTDEN-26MAR28-B36.5", "side": "yes", "contracts": 40, "entry": 0.10, "run": "Weather"},

    # Crypto hourly (all losses)
    {"ticker": "KXSOLD-26MAR2715-T81.9999", "side": "no", "contracts": 40, "entry": 0.13, "run": "Crypto"},
    {"ticker": "KXDOGE-26MAR2715-B0.087", "side": "no", "contracts": 58, "entry": 0.24, "run": "Crypto"},
    {"ticker": "KXBTCD-26MAR2715-T69499.99", "side": "yes", "contracts": 40, "entry": 0.10, "run": "Crypto"},
    {"ticker": "KXBTC-26MAR2715-B65350", "side": "yes", "contracts": 40, "entry": 0.05, "run": "Crypto"},
    {"ticker": "KXBTCD-26MAR2715-T69399.99", "side": "yes", "contracts": 80, "entry": 0.10, "run": "Crypto"},
    {"ticker": "KXBTCD-26MAR2715-T65899.99", "side": "yes", "contracts": 40, "entry": 0.22, "run": "Crypto"},
    {"ticker": "KXBTCD-26MAR2715-T69699.99", "side": "yes", "contracts": 120, "entry": 0.04, "run": "Crypto"},
    {"ticker": "KXBTCD-26MAR2715-T69899.99", "side": "yes", "contracts": 120, "entry": 0.06, "run": "Crypto"},
    {"ticker": "KXBTCD-26MAR2715-T69799.99", "side": "yes", "contracts": 120, "entry": 0.06, "run": "Crypto"},
    {"ticker": "KXBTCD-26MAR2715-T70399.99", "side": "yes", "contracts": 80, "entry": 0.06, "run": "Crypto"},
    {"ticker": "KXBTCD-26MAR2715-T70499.99", "side": "yes", "contracts": 80, "entry": 0.06, "run": "Crypto"},
    {"ticker": "KXBTCD-26MAR2715-T70699.99", "side": "yes", "contracts": 40, "entry": 0.04, "run": "Crypto"},
    {"ticker": "KXBTC-26MAR2715-B65550", "side": "yes", "contracts": 40, "entry": 0.11, "run": "Crypto"},
]

# Current run
with open("logs/paper_trades.json") as f:
    d = json.load(f)
for ticker, pos in d["positions"].items():
    all_trades.append({
        "ticker": ticker, "side": pos["side"], "contracts": pos["contracts"],
        "entry": pos["entry_price"], "run": "Current"
    })

total_cost = 0
total_pnl = 0
wins = 0
losses = 0
open_count = 0
by_run = {}

for trade in all_trades:
    ticker = trade["ticker"]
    side = trade["side"]
    contracts = trade["contracts"]
    entry = trade["entry"]
    cost = contracts * entry
    total_cost += cost
    run = trade["run"]

    if run not in by_run:
        by_run[run] = {"cost": 0, "pnl": 0, "wins": 0, "losses": 0, "open": 0}
    by_run[run]["cost"] += cost

    try:
        resp = client.get_market(ticker)
        m = resp.get("market", {})
        status = m.get("status", "")
        result = m.get("result", "")

        if status in ("settled", "finalized") and result:
            won = (result == side)
            if won:
                pnl = (contracts * 1.0) - cost
                wins += 1
                by_run[run]["wins"] += 1
            else:
                pnl = -cost
                losses += 1
                by_run[run]["losses"] += 1
        else:
            cur = float(m.get("yes_bid_dollars", 0) or 0) if side == "yes" else float(m.get("no_bid_dollars", 0) or 0)
            pnl = (contracts * cur) - cost
            open_count += 1
            by_run[run]["open"] += 1

        total_pnl += pnl
        by_run[run]["pnl"] += pnl
    except Exception as e:
        pass

print("ALL-TIME P&L SINCE DAY 1")
print("=" * 70)
for run, data in by_run.items():
    settled = data["wins"] + data["losses"]
    wr = f'{data["wins"]}/{settled}' if settled > 0 else "0/0"
    ret = f'{data["pnl"]/data["cost"]*100:+.0f}%' if data["cost"] > 0 else "N/A"
    print(f'  {run:<12} Cost: ${data["cost"]:<8.2f} PnL: ${data["pnl"]:+8.2f}  W/L: {wr:<6} Open: {data["open"]:<3} Return: {ret}')

print("=" * 70)
print(f"TOTAL INVESTED:  ${total_cost:.2f}")
print(f"TOTAL P&L:       ${total_pnl:+.2f}")
print(f"RETURN:          {total_pnl/total_cost*100:+.1f}%")
settled_total = wins + losses
print(f"SETTLED:         {wins}W / {losses}L", end="")
if settled_total > 0:
    print(f" ({wins/settled_total*100:.0f}% win rate)")
else:
    print()
print(f"STILL OPEN:      {open_count}")
