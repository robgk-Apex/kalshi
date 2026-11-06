FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir "fastapi>=0.110" "uvicorn>=0.29" "httpx>=0.27"
COPY app ./app
COPY static ./static
COPY data/snapshot.db ./data/snapshot.db
ENV AUTO_REFRESH_HOURS=24
CMD ["sh", "-c", "uvicorn app.server:app --host 0.0.0.0 --port ${PORT:-8000}"]
