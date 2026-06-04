FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY hypergery-ubuntu /app/hypergery-ubuntu

ENV PYTHONPATH=/app/hypergery-ubuntu

RUN mkdir -p /data /hypergery/migrations

EXPOSE 8765

CMD ["python", "-m", "hypergery_ubuntu.cli", "hub", "serve", "--host", "0.0.0.0", "--port", "8765"]
