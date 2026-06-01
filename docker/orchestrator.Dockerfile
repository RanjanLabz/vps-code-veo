FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY orchestrator /app/orchestrator
COPY config /orchestrator/config

RUN mkdir -p /orchestrator/logs /orchestrator/config

EXPOSE 10000

CMD ["sh", "-c", "uvicorn orchestrator.api.main:app --host 0.0.0.0 --port ${PORT:-8090} --workers 1"]
