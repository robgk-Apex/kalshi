"""Place researched trades - run manually by user."""
import yaml
from src.api_client import KalshiClient

config = yaml.safe_load(open("config/config.yaml"))
api = config["api"]
client = KalshiClient(api["base_url"], api["key_id"], api["private_key_path"])

bal = client.get_balance()
balance = bal.get("balance", 0) / 100
print(f"Balance: ${balance:,.2f}\n")

trades = [
    # TIER 1: FREE MONEY / NEAR-CERTAIN
    ("KXNCAAMBCBC-26-CREI", "no", 100, "Creighton wins championship NO (they're eliminated)"),
    ("KXTRUMPSAY-26APR06-WIND", "yes", 50, "Trump says Windmill YES (already said it Mar 24)"),
    ("KXNASCARRACE-NORCEL2PBB26-JELO", "no", 50, "NASCAR Jesse Love wins NO (+50000 longshot)"),
    ("KXSNLMENTION-26APR04-TRUM", "yes", 50, "SNL Jack Black says Trump YES (97% certain)"),
    
    # TIER 2: STRONG EDGE  
    ("KXRT-DRA-80", "no", 50, "The Drama RT stays 80+ (currently 84% on 55 reviews)"),
    ("KXAAAGASW-26APR06-4.080", "yes", 50, "Gas above $4.08 YES (at $4.02 and rising)"),
    ("KXAAAGASW-26APR06-4.120", "yes", 50, "Gas above $4.12 YES (Iran war driving prices)"),
    ("KXTESLA-26-Q1-340000", "yes", 50, "Tesla >340k deliveries YES (consensus 365k)"),
]

print("PLACING TRADES:")
print("=" * 60)
total = 0
for ticker, side, qty, desc in trades:
    try:
        market = client.get_market(ticker).get("market", {})
        if side == "yes":
            price = int(float(market.get("yes_ask_dollars", 0) or 0) * 100)
        else:
            price = int(float(market.get("no_ask_dollars", 0) or 0) * 100)
        
        if price <= 0 or price >= 100:
            print(f"  SKIP: {desc} - bad price ${price/100:.2f}")
            continue
            
        cost = qty * price / 100
        total += cost
        
        resp = client.create_order(
            ticker=ticker,
            side=side,
            count=qty,
            price=price,
            order_type="limit",
        )
        order_id = resp.get("order", {}).get("order_id", "???")
        status = resp.get("order", {}).get("status", "???")
        print(f"  PLACED: {desc}")
        print(f"          {qty}x {side} @ ${price/100:.2f} = ${cost:.2f} | {status} | {order_id}")
    except Exception as e:
        print(f"  ERROR: {desc} - {e}")

print(f"\nTotal deployed: ~${total:.2f}")
print(f"Remaining balance: ~${balance - total:.2f}")
