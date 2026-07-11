# Live Kalshi up/down crypto dashboard — a hostable web service.
#
# Build:  docker build -t kalshi-dashboard .
# Run:    docker run -p 8787:8787 kalshi-dashboard          # view-only shared board
#         docker run -p 8787:8787 \
#           -e KALSHI_KEY_ID=... -e KALSHI_PRIVATE_KEY="$(cat keys/kalshi.pem)" \
#           kalshi-dashboard                                # authenticated (adds balance)
#
# Each visitor gets their OWN P&L in their browser (localStorage), so a hosted
# instance is safe to share while still letting everyone paper-trade their own
# book. Add --public to the CMD for a pure view-only display (no trading UI).
# The container must be able to reach api.elections.kalshi.com.
FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# HOST/PORT are read from the environment by scripts/dashboard.py.
ENV HOST=0.0.0.0 \
    PORT=8787
EXPOSE 8787

# Live board, per-viewer P&L; set KALSHI_* env vars to add your balance tile.
CMD ["python", "scripts/dashboard.py", "--live"]
