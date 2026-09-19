#!/usr/bin/env bash
set -euo pipefail

HEADROOM_VENV="${HEADROOM_VENV:-$HOME/Repositories/headroom/.venv}"
PROXY_HOST="${HEADROOM_PROXY_HOST:-127.0.0.1}"
PROXY_PORT="${HEADROOM_PROXY_PORT:-8788}"
PROXY_MODE="${HEADROOM_PROXY_MODE:-token}"
PROXY_TARGET_RATIO="${HEADROOM_PROXY_TARGET_RATIO:-0.5}"
PROXY_CCR_FLAG=()
if [[ "${HEADROOM_PROXY_CCR:-0}" != "1" ]]; then
  PROXY_CCR_FLAG=(--no-ccr)
fi
BACKEND="${HEADROOM_PROXY_BACKEND:-openrouter}"
RUNTIME_DIR="$HOME/.headroom"
LOG_FILE="$RUNTIME_DIR/proxy.log"
PID_FILE="$RUNTIME_DIR/proxy.pid"
ACTION="${1:-status}"

mkdir -p "$RUNTIME_DIR"

proxy_pid() {
  [[ -f "$PID_FILE" ]] || return 1
  cat "$PID_FILE" 2>/dev/null
}

proxy_running() {
  local pid
  pid="$(proxy_pid)" || return 1
  [[ -n "$pid" ]] || return 1
  kill -0 "$pid" 2>/dev/null
}

health() {
  curl -fsS "http://$PROXY_HOST:$PROXY_PORT/health" >/dev/null 2>&1
}

case "$ACTION" in
  start)
    if proxy_running && health; then
      echo "already_running pid=$(proxy_pid) url=http://$PROXY_HOST:$PROXY_PORT"
      exit 0
    fi
    if [[ ! -x "$HEADROOM_VENV/bin/headroom" ]]; then
      echo "ERROR: headroom binary not found in $HEADROOM_VENV" >&2
      exit 1
    fi
    OPENROUTER_API_KEY="$(grep -m1 '^OPENROUTER_API_KEY=' "$HOME/.hermes/.env" | cut -d'=' -f2- || true)"
    if [[ -z "${OPENROUTER_API_KEY:-}" ]]; then
      echo "ERROR: OPENROUTER_API_KEY missing in ~/.hermes/.env" >&2
      exit 1
    fi
    export OPENROUTER_API_KEY
    export HEADROOM_BEACON=off
    export HEADROOM_TARGET_RATIO="$PROXY_TARGET_RATIO"
    nohup "$HEADROOM_VENV/bin/headroom" proxy \
      --backend "$BACKEND" \
      --mode "$PROXY_MODE" \
      --host "$PROXY_HOST" \
      --port "$PROXY_PORT" \
      "${PROXY_CCR_FLAG[@]}" \
      >>"$LOG_FILE" 2>&1 &
    echo $! > "$PID_FILE"
    for _ in $(seq 1 60); do
      if health; then
        echo "started pid=$(cat "$PID_FILE") url=http://$PROXY_HOST:$PROXY_PORT mode=$PROXY_MODE target_ratio=$PROXY_TARGET_RATIO ccr=${HEADROOM_PROXY_CCR:-0}"
        exit 0
      fi
      sleep 1
    done
    echo "ERROR: proxy not healthy after 60s; tail of $LOG_FILE:" >&2
    tail -n 40 "$LOG_FILE" >&2 || true
    exit 1
    ;;
  stop)
    if proxy_running; then
      kill "$(proxy_pid)" >/dev/null 2>&1 || true
      rm -f "$PID_FILE"
      echo "stopped"
    else
      rm -f "$PID_FILE"
      echo "not_running"
    fi
    ;;
  status)
    if proxy_running && health; then
      echo "running pid=$(proxy_pid) url=http://$PROXY_HOST:$PROXY_PORT"
    else
      echo "not_running"
      exit 1
    fi
    ;;
  *)
    echo "usage: $0 {start|stop|status}" >&2
    exit 2
    ;;
esac
