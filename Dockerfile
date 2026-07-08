# Live Kalshi up/down crypto dashboard — a hostable web service.
#
# Build:  docker build -t kalshi-dashboard .
# Run:    docker run -p 8787:8787 kalshi-dashboard          # public real data, no keys
#         docker run -p 8787:8787 \
#           -e KALSHI_KEY_ID=... -e KALSHI_PRIVATE_KEY="$(cat keys/kalshi.pem)" \
#           kalshi-dashboard                                # authenticated (adds balance)
#
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

# Public live data by default; set KALSHI_* env vars to authenticate.
CMD ["python", "scripts/dashboard.py", "--live"]
