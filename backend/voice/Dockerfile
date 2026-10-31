FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
# Three levels deep: app/main.py looks for .env at parents[3] and parents[2] of itself.
WORKDIR /opt/csm/voice

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ app/

RUN (getent group voice || groupadd -r voice) && \
    (getent passwd voice || useradd --system --create-home -g voice voice) && \
    mkdir -p data/recordings && chown -R voice:voice data
USER voice

EXPOSE 7861
HEALTHCHECK --interval=10s --timeout=3s --start-period=20s --retries=6 \
    CMD python -c "import urllib.request, os; urllib.request.urlopen(f'http://localhost:{os.environ.get(\"PORT\", 7861)}/health')"
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port \"${PORT:-7861}\""]
