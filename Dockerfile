FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Só o que o app precisa em produção (pandas/openpyxl ficam de fora:
# são usados apenas pelo scripts/sincronizar_base.py, que roda no seu PC).
COPY requirements-cloudrun.txt .
RUN pip install --no-cache-dir -r requirements-cloudrun.txt

COPY app ./app
COPY criterios_rede.json ./criterios_rede.json

# Cloud Run injeta a porta em $PORT.
CMD exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080} --proxy-headers --forwarded-allow-ips='*'
