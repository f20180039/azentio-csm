FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    SIMULATOR_DB_PATH=/app/data/runtime/simulator.db
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ app/
COPY data/seed/ data/seed/

RUN useradd --system --create-home --user-group simulator \
    && mkdir -p /app/data/runtime && chown -R simulator:simulator /app/data/runtime
USER simulator
VOLUME /app/data/runtime

EXPOSE 8090
HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=6 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8090/health')"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8090"]
