#!/usr/bin/env bash
# Starts the four services natively (no Docker): Spring API :8080, bank simulator :8090, voice :7861, web :5173.
# Needs a local Postgres. Logs and PIDs go to .run/. Stop everything with scripts/dev-down.sh.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RUN="$ROOT/.run"
mkdir -p "$RUN"
DB_NAME="${DB_NAME:-caseintel}"
DB_URL="${DB_URL:-jdbc:postgresql://localhost:5432/$DB_NAME}"
DB_USER="${DB_USER:-$(whoami)}"
DB_PASSWORD="${DB_PASSWORD:-}"
API_PORT="${API_PORT:-8080}"; SIM_PORT="${SIM_PORT:-8090}"; VOICE_PORT="${VOICE_PORT:-7861}"; WEB_PORT="${WEB_PORT:-5173}"
WEB="http://localhost:$WEB_PORT"
for p in $API_PORT $SIM_PORT $VOICE_PORT $WEB_PORT; do
  lsof -nP -iTCP:$p -sTCP:LISTEN >/dev/null 2>&1 && { echo "port $p is taken by: $(lsof -nP -iTCP:$p -sTCP:LISTEN | awk 'NR==2{print $1" pid "$2}')"; echo "stop it, or pick other ports, e.g. API_PORT=8081 SIM_PORT=8091 VOICE_PORT=7862 WEB_PORT=5174 $0"; exit 1; }
done

pg_isready -q || { echo "Postgres is not running on localhost:5432"; exit 1; }
psql -Atqc "select 1 from pg_database where datname='$DB_NAME'" postgres | grep -q 1 || createdb "$DB_NAME"

start() {  # name, dir, command...
  local name=$1 dir=$2; shift 2
  if [ -f "$RUN/$name.pid" ] && kill -0 "$(cat "$RUN/$name.pid")" 2>/dev/null; then echo "$name already running"; return; fi
  (cd "$dir" && nohup "$@" > "$RUN/$name.log" 2>&1 & echo $! > "$RUN/$name.pid")
  echo "started $name (log: .run/$name.log)"
}

start api "$ROOT/backend/api" env DB_URL="$DB_URL" DB_USER="$DB_USER" DB_PASSWORD="$DB_PASSWORD" SERVER_PORT="$API_PORT" \
  CORS_ORIGINS="$WEB" ENFORCE_CALLING_HOURS=false ./mvnw -q spring-boot:run
start simulator "$ROOT/backend/simulator" env CORS_ORIGINS="[\"$WEB\"]" .venv/bin/python -m uvicorn app.main:app --port "$SIM_PORT"
start voice "$ROOT/backend/voice" env SIMULATOR_BASE="http://localhost:$SIM_PORT/v1" RENEWALS_API_BASE="http://localhost:$API_PORT/api/v1" \
  CORS_ORIGINS="$WEB" .venv/bin/python -m uvicorn app.main:app --port "$VOICE_PORT"
start web "$ROOT/frontend" env VITE_API_BASE="http://localhost:$API_PORT/api/v1" VITE_VOICE_BASE="http://localhost:$VOICE_PORT" \
  VITE_SIMULATOR_BASE="http://localhost:$SIM_PORT/v1" npm run dev -- --port "$WEB_PORT" --strictPort

echo "waiting for health checks..."
for i in $(seq 1 60); do
  ok=0
  curl -fsS -u analyst:analyst "http://localhost:$API_PORT/api/v1/renewals/queue" >/dev/null 2>&1 && ok=$((ok+1))
  curl -fsS "http://localhost:$SIM_PORT/health" >/dev/null 2>&1 && ok=$((ok+1))
  curl -fsS "http://localhost:$VOICE_PORT/health" >/dev/null 2>&1 && ok=$((ok+1))
  curl -fsS "$WEB" >/dev/null 2>&1 && ok=$((ok+1))
  [ $ok -eq 4 ] && { echo "all four services are up: open $WEB/support (analyst/analyst)"; exit 0; }
  sleep 2
done
echo "not all services came up; check .run/*.log"; exit 1
