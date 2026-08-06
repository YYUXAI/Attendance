FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    ATTENDANCE_RUN_MODE=webhook \
    WEBHOOK_PORT=8001 \
    KMP_DUPLICATE_LIB_OK=TRUE \
    TZ=UTC

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libpq5 \
        libglib2.0-0 \
        libgl1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8001

CMD ["uvicorn", "webhook_app:app", "--host", "0.0.0.0", "--port", "8001"]
