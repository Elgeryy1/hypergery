FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY hypergery-ubuntu /app/hypergery-ubuntu

ENV PYTHONPATH=/app/hypergery-ubuntu

RUN mkdir -p /data /hypergery/migrations

EXPOSE 8765

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/health', timeout=3).read()"]

CMD ["python", "-m", "hypergery_ubuntu.cli", "hub", "serve", "--host", "0.0.0.0", "--port", "8765"]
