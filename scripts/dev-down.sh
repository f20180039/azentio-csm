#!/usr/bin/env bash
# Stops the services scripts/dev-up.sh started, including child processes (npm → vite).
RUN="$(cd "$(dirname "$0")/.." && pwd)/.run"
descendants() { for c in $(pgrep -P "$1"); do descendants "$c"; echo "$c"; done; }
for f in "$RUN"/*.pid; do
  [ -f "$f" ] || continue
  pid=$(cat "$f"); name=$(basename "$f" .pid)
  kill $(descendants "$pid") "$pid" 2>/dev/null && echo "stopped $name"
  rm -f "$f"
done
