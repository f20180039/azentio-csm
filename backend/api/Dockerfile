FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    API_DB_PATH=/app/data/runtime/api.db
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ app/

RUN useradd --system --create-home --user-group api \
    && mkdir -p /app/data/runtime && chown -R api:api /app/data
USER api
VOLUME /app/data/runtime

EXPOSE 8080
HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=6 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/health')"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
