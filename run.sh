#!/usr/bin/env bash
# SPEC 14.3 - the one command that starts the demo: FastAPI backend + static frontend.
# Ports default to 8000/5173 but are overridable: dev machines commonly squat on 8000
# (a squatter that answers /health would otherwise fake a passing smoke check).
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"

BACKEND_PORT="${BHAR_BACKEND_PORT:-8000}"
FRONTEND_PORT="${BHAR_FRONTEND_PORT:-5173}"

require_free_port() {
    local port="$1" label="$2" holder
    if holder=$(lsof -nP -iTCP:"$port" -sTCP:LISTEN -t 2>/dev/null) && [ -n "$holder" ]; then
        echo "ERROR: $label port $port is already in use by PID(s): $(echo "$holder" | tr '\n' ' ')" >&2
        # shellcheck disable=SC2086
        ps -p $(echo "$holder" | tr '\n' ',') -o pid=,command= 2>/dev/null | cut -c1-120 >&2 || true
        echo "Free that port, or override:" >&2
        echo "  BHAR_BACKEND_PORT=8001 BHAR_FRONTEND_PORT=5174 ./run.sh" >&2
        exit 1
    fi
}

require_free_port "$BACKEND_PORT" backend
require_free_port "$FRONTEND_PORT" frontend

cleanup() {
    trap - EXIT INT TERM
    for pid in "${BACKEND_PID:-}" "${FRONTEND_PID:-}"; do
        [ -n "$pid" ] || continue
        pkill -P "$pid" 2>/dev/null || true   # uv run spawns a child; kill it too or it orphans
        kill "$pid" 2>/dev/null || true
    done
    # Belt and braces. On Ctrl-C the signal reaches the whole process group, so the
    # `uv run` wrapper can exit BEFORE the trap runs -- its python child is reparented to
    # init, `pkill -P` then matches nothing, and the child keeps the port. Observed:
    # the http.server on the frontend port survived every time. A held port is not a
    # cosmetic problem, because the preflight above refuses to start on a busy port, so
    # one Ctrl-C would otherwise make the next `./run.sh` fail.
    # Only sweep ports we actually bound: this runs after the preflight proved them free,
    # so anything listening there now is ours. Never reached on a preflight failure
    # (the trap is installed after it), which is what keeps this from killing a squatter.
    if [ -n "${BACKEND_PID:-}${FRONTEND_PID:-}" ]; then
        for port in "$BACKEND_PORT" "$FRONTEND_PORT"; do
            for stray in $(lsof -nP -iTCP:"$port" -sTCP:LISTEN -t 2>/dev/null); do
                kill "$stray" 2>/dev/null || true
                sleep 0.2
                kill -9 "$stray" 2>/dev/null || true
            done
        done
    fi

    # Reap last. This has to come AFTER the port sweep: if a child survived the signal,
    # `wait` blocks on it forever and nothing below it would ever run.
    wait 2>/dev/null || true
}
trap cleanup EXIT INT TERM

uv run uvicorn backend.main:app --port "$BACKEND_PORT" &
BACKEND_PID=$!
uv run python -m http.server "$FRONTEND_PORT" --directory frontend &
FRONTEND_PID=$!

echo "Backend:  http://localhost:${BACKEND_PORT}  (identity: http://localhost:${BACKEND_PORT}/openapi.json)"
if [ "$BACKEND_PORT" != "8000" ]; then
    # The page defaults its API base to :8000; on an override it needs ?api= or it renders
    # chrome with no data. Print the assembled URL so nobody hand-builds it at demo time.
    # ?api= is carried across both pages by the links themselves (theme.js linkify()).
    echo "Start here: http://localhost:${FRONTEND_PORT}/overview.html?api=http://localhost:${BACKEND_PORT}"
    echo "Frontend: http://localhost:${FRONTEND_PORT}/?api=http://localhost:${BACKEND_PORT}"
else
    echo "Start here: http://localhost:${FRONTEND_PORT}/overview.html"
    echo "Frontend: http://localhost:${FRONTEND_PORT}"
fi
echo "Ctrl-C stops both."

wait
