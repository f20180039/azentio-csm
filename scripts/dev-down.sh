#!/usr/bin/env bash
# Stops the services scripts/dev-up.sh started.
RUN="$(cd "$(dirname "$0")/.." && pwd)/.run"
for f in "$RUN"/*.pid; do
  [ -f "$f" ] || continue
  pid=$(cat "$f"); name=$(basename "$f" .pid)
  pkill -P "$pid" 2>/dev/null; kill "$pid" 2>/dev/null && echo "stopped $name"
  rm -f "$f"
done
