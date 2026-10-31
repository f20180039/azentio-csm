FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
# Three levels deep: app/main.py looks for .env at parents[3] and parents[2] of itself.
WORKDIR /opt/csm/voice

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ app/

RUN useradd --system --create-home --user-group voice
USER voice

EXPOSE 7861
HEALTHCHECK --interval=10s --timeout=3s --start-period=20s --retries=6 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:7861/health')"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "7861"]
