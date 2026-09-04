#!/usr/bin/env bash
# demo.sh - the zero-thought demo launcher. Reclaims OUR stale servers, picks free
# ports, starts backend + frontend, proves the backend is really ours, reports whether
# the data is real or the synthetic fixture, and opens the browser at the right URL.
#
# Written for a human who is 30 seconds from presenting. It must never make them think
# about ports, and it must never kill something that is not ours.
#
# Why this exists alongside run.sh: run.sh correctly REFUSES to start on a busy port,
# which leaves the presenter to pick new ports by hand. Three different kinds of process
# can hold a port on this machine:
#   1. A VS Code helper on :8000 that answers /health with a byte-identical
#      {"status":"ok"} -- NOT ours, NEVER killed, and never selected as a port.
#   2. Our own stale uvicorn/http.server from an earlier run -- safe to reclaim.
#   3. Unrelated third-party processes -- never touched.
# Hence: we never kill by port. We kill only processes whose command line is ours AND
# that belong to this checkout.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"
REPO_ROOT="$(pwd -P)"

BACKEND_PORT_START="${BHAR_BACKEND_PORT:-8011}"
FRONTEND_PORT_START="${BHAR_FRONTEND_PORT:-5184}"
FORBIDDEN_PORT=8000                       # the squatter's port; never ours (see above)
EXPECTED_TITLE="Bhar - Site-Tuned Model Blend"   # plain ASCII hyphen, from backend/main.py
READY_TIMEOUT_SECS=30

if [ -t 1 ]; then
    B=$'\033[1m'; DIM=$'\033[2m'; GRN=$'\033[32m'; YEL=$'\033[33m'; RED=$'\033[31m'; RST=$'\033[0m'
else
    B=''; DIM=''; GRN=''; YEL=''; RED=''; RST=''
fi

say()  { printf '%s\n' "$*"; }
step() { printf '%s==>%s %s\n' "$B" "$RST" "$*"; }
warn() { printf '%s!!%s %s\n' "$YEL" "$RST" "$*"; }
die()  { printf '%sERROR:%s %s\n' "$RED" "$RST" "$*" >&2; exit 1; }

port_holders() { lsof -nP -iTCP:"$1" -sTCP:LISTEN -t 2>/dev/null || true; }
port_is_free() { [ -z "$(port_holders "$1")" ]; }

# --- 1. Reclaim only our own stale servers -----------------------------------------
# A candidate must match one of OUR command shapes AND be tied to THIS checkout (repo
# path in argv -- true of the python children -- or cwd == repo root, which covers the
# `uv run` wrappers whose argv carries no path). Anything else is left alone.
find_our_pids() {
    local line pid cmd shape_ok proc_cwd
    ps -axo pid=,command= 2>/dev/null | sed 's/^[[:space:]]*//' | while IFS= read -r line; do
        pid="${line%% *}"
        cmd="${line#* }"
        [ "$pid" = "$$" ] && continue
        shape_ok=0
        case "$cmd" in
            *"uvicorn backend.main"*)                    shape_ok=1 ;;
            *"http.server"*"--directory frontend"*)      shape_ok=1 ;;
        esac
        [ "$shape_ok" = 1 ] || continue
        case "$cmd" in
            *"$REPO_ROOT"*) printf '%s\t%s\n' "$pid" "$cmd"; continue ;;
        esac
        proc_cwd="$(lsof -a -p "$pid" -d cwd -Fn 2>/dev/null | sed -n 's/^n//p' | tail -1)"
        if [ "$proc_cwd" = "$REPO_ROOT" ]; then printf '%s\t%s\n' "$pid" "$cmd"; fi
    done
}

reclaim_stale() {
    local found pid cmd
    found="$(find_our_pids || true)"
    if [ -z "$found" ]; then
        say "   nothing stale to reclaim."
        return 0
    fi
    while IFS=$'\t' read -r pid cmd; do
        [ -n "$pid" ] || continue
        printf '   reclaiming PID %-7s %s%s%s\n' "$pid" "$DIM" "$(printf '%.100s' "$cmd")" "$RST"
        pkill -P "$pid" 2>/dev/null || true   # `uv run` wrappers orphan their python child
        kill "$pid" 2>/dev/null || true
    done <<< "$found"
    for _ in 1 2 3 4 5 6 7 8 9 10; do
        if [ -z "$(find_our_pids || true)" ]; then break; fi
        sleep 0.3
    done
    while IFS=$'\t' read -r pid cmd; do
        [ -n "$pid" ] || continue
        kill -9 "$pid" 2>/dev/null || true
    done <<< "$(find_our_pids || true)"
    sleep 0.3
    if [ -n "$(find_our_pids || true)" ]; then
        warn "some of our processes would not die; continuing on fresh ports anyway."
    fi
}

# A previous demo.sh, once its servers are gone, runs its own EXIT trap and sweeps the
# ports it bound. If we grabbed those same ports first it would sweep OURS out from under
# us. So we wait for it to finish dying -- we never kill it; it exits on its own.
stale_launcher_pids() {
    local mypgid="$1" pid pgid cmd proc_cwd
    ps -axo pid=,pgid=,command= 2>/dev/null | sed 's/^[[:space:]]*//' | while read -r pid pgid cmd; do
        [ "$pgid" = "$mypgid" ] && continue          # our own shell and its subshells
        case "$cmd" in *demo.sh*) ;; *) continue ;; esac
        case "$cmd" in *"$REPO_ROOT"*) echo "$pid"; continue ;; esac
        proc_cwd="$(lsof -a -p "$pid" -d cwd -Fn 2>/dev/null | sed -n 's/^n//p' | tail -1)"
        if [ "$proc_cwd" = "$REPO_ROOT" ]; then echo "$pid"; fi
    done
}

await_stale_launchers() {
    local mypgid i
    mypgid="$(ps -o pgid= -p $$ 2>/dev/null | tr -d ' ')"
    [ -n "$mypgid" ] || return 0
    for i in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20; do
        if [ -z "$(stale_launcher_pids "$mypgid" || true)" ]; then return 0; fi
        [ "$i" = 1 ] && say "   waiting for the previous demo.sh to finish shutting down..."
        sleep 0.25
    done
    return 0
}

# --- 2. Auto-select free ports ------------------------------------------------------
pick_port() {
    local port="$1" tries=0
    while [ "$tries" -lt 60 ]; do
        if [ "$port" != "$FORBIDDEN_PORT" ] && port_is_free "$port"; then
            printf '%s' "$port"; return 0
        fi
        port=$((port + 1)); tries=$((tries + 1))
    done
    return 1
}

# --- 7. Cleanup ---------------------------------------------------------------------
cleanup() {
    trap - EXIT INT TERM
    printf '\n'
    step "Shutting down."
    local pid stray port
    for pid in "${BACKEND_PID:-}" "${FRONTEND_PID:-}"; do
        [ -n "$pid" ] || continue
        pkill -P "$pid" 2>/dev/null || true
        kill "$pid" 2>/dev/null || true
    done
    # Ctrl-C reaches the whole process group, so a `uv run` wrapper can exit before this
    # trap runs; its python child is reparented and `pkill -P` then matches nothing while
    # the child keeps the port. Sweep the two ports we bound ourselves -- we proved them
    # free before binding, so anything on them now is ours. (Never reached before the
    # ports are chosen, which is what keeps this away from the :8000 squatter.)
    if [ -n "${BACKEND_PID:-}${FRONTEND_PID:-}" ]; then
        for port in "${BACKEND_PORT:-}" "${FRONTEND_PORT:-}"; do
            [ -n "$port" ] || continue
            for stray in $(port_holders "$port"); do
                kill "$stray" 2>/dev/null || true
                sleep 0.2
                kill -9 "$stray" 2>/dev/null || true
            done
        done
    fi
    wait 2>/dev/null || true    # must come AFTER the sweep or it blocks on a survivor
    local leftover=""
    for port in "${BACKEND_PORT:-}" "${FRONTEND_PORT:-}"; do
        [ -n "$port" ] || continue
        if [ -n "$(port_holders "$port")" ]; then leftover="$leftover $port"; fi
    done
    if [ -n "$leftover" ]; then
        warn "port(s) still held after shutdown:$leftover"
    else
        say "   both ports released, no orphans. ${GRN}Clean.${RST}"
    fi
}

# ------------------------------------------------------------------------------------
say ""
say "${B}Bhar demo launcher${RST}"
say ""

step "Reclaiming any stale Bhar servers (ours only -- never by port)."
reclaim_stale
await_stale_launchers
sleep 0.4

step "Choosing free ports (never :$FORBIDDEN_PORT)."
BACKEND_PORT="$(pick_port "$BACKEND_PORT_START")" || die "no free backend port near $BACKEND_PORT_START."
FRONTEND_PORT="$(pick_port "$FRONTEND_PORT_START")" || die "no free frontend port near $FRONTEND_PORT_START."
say "   backend :$BACKEND_PORT   frontend :$FRONTEND_PORT"

trap cleanup EXIT INT TERM

step "Starting servers."
uv run uvicorn backend.main:app --port "$BACKEND_PORT" --log-level warning &
BACKEND_PID=$!
uv run python -m http.server "$FRONTEND_PORT" --directory frontend >/dev/null 2>&1 &
FRONTEND_PID=$!

# --- 4. Wait for real readiness, and prove identity via /openapi.json ----------------
# NEVER /health: the :8000 squatter forges exactly that response. The FastAPI title is
# the discriminator.
step "Waiting for the backend to answer (identity via /openapi.json, not /health)."
deadline=$(( $(date +%s) + READY_TIMEOUT_SECS ))
title=""
while [ "$(date +%s)" -lt "$deadline" ]; do
    if body="$(curl -fsS --max-time 2 "http://localhost:${BACKEND_PORT}/openapi.json" 2>/dev/null)"; then
        title="$(printf '%s' "$body" | uv run --no-sync python -c \
            'import json,sys; print(json.load(sys.stdin).get("info",{}).get("title",""))' 2>/dev/null || true)"
        [ -n "$title" ] && break
    fi
    sleep 0.4
done
[ -n "$title" ] || die "backend never answered on :$BACKEND_PORT within ${READY_TIMEOUT_SECS}s."
if [ "$title" != "$EXPECTED_TITLE" ]; then
    die "wrong service on :$BACKEND_PORT -- title is '$title', expected '$EXPECTED_TITLE'."
fi
say "   ${GRN}identity confirmed${RST}: \"$title\""

step "Waiting for the frontend."
deadline=$(( $(date +%s) + READY_TIMEOUT_SECS ))
frontend_ok=0
while [ "$(date +%s)" -lt "$deadline" ]; do
    if curl -fsS --max-time 2 -o /dev/null "http://localhost:${FRONTEND_PORT}/" 2>/dev/null; then
        frontend_ok=1; break
    fi
    sleep 0.4
done
[ "$frontend_ok" = 1 ] || die "frontend never answered on :$FRONTEND_PORT within ${READY_TIMEOUT_SECS}s."
say "   ${GRN}serving${RST} frontend/ on :$FRONTEND_PORT"

# --- 5. Report what data is actually being served -----------------------------------
step "Checking the served data."
meta="$(curl -fsS --max-time 10 "http://localhost:${BACKEND_PORT}/api/results" 2>/dev/null \
    | uv run --no-sync python -c 'import json,sys
m = json.load(sys.stdin).get("meta", {})
print("%s\t%s\t%s" % (m.get("is_synthetic"), m.get("source"), m.get("generated_at")))' 2>/dev/null || true)"
if [ -z "$meta" ]; then
    warn "could not read /api/results -- the page may render chrome with no data."
    IS_SYNTHETIC="unknown"; SOURCE="unknown"; GENERATED="unknown"
else
    IFS=$'\t' read -r IS_SYNTHETIC SOURCE GENERATED <<< "$meta"
fi
say "   meta.is_synthetic = ${IS_SYNTHETIC}"
say "   meta.source       = ${SOURCE}"
say "   generated_at      = ${GENERATED}"

if [ "$IS_SYNTHETIC" = "True" ] || [ "$IS_SYNTHETIC" = "true" ]; then
    say ""
    say "${RED}${B}###################################################################${RST}"
    say "${RED}${B}##                                                               ##${RST}"
    say "${RED}${B}##   WARNING: THIS PAGE IS SHOWING THE SYNTHETIC FIXTURE.        ##${RST}"
    say "${RED}${B}##   The numbers on screen are FABRICATED, not a real backtest.  ##${RST}"
    say "${RED}${B}##   Do NOT present them as results.                             ##${RST}"
    say "${RED}${B}##   To get real data:  uv run python -m score.run               ##${RST}"
    say "${RED}${B}##                                                               ##${RST}"
    say "${RED}${B}###################################################################${RST}"
    say ""
    say "Launching anyway -- the fixture is a legitimate fallback, but you have been told."
    say ""
elif [ "$IS_SYNTHETIC" = "False" ] || [ "$IS_SYNTHETIC" = "false" ]; then
    say "   ${GRN}Real backtest data.${RST} Safe to present."
fi

# --- 6. Open the browser ------------------------------------------------------------
# The page defaults its API base to :8000. On any other backend port it MUST get ?api=
# or it renders full chrome with zero data, which looks like an app bug and is not.
# Overview first: the presenter walks the room through the explainer, then clicks
# through to the live page. The ?api= is carried across by the link itself.
DEMO_URL="http://localhost:${FRONTEND_PORT}/overview.html?api=http://localhost:${BACKEND_PORT}"
PRODUCT_URL="http://localhost:${FRONTEND_PORT}/?api=http://localhost:${BACKEND_PORT}"
say ""
say "${B}Demo URL:${RST} ${DEMO_URL}   ${DIM}(start here)${RST}"
say "${B}Live page:${RST} ${PRODUCT_URL}"
say "${DIM}Backend identity: http://localhost:${BACKEND_PORT}/openapi.json${RST}"
say ""
if command -v open >/dev/null 2>&1; then
    open "$DEMO_URL" >/dev/null 2>&1 && say "   Opened in your browser." \
        || warn "could not open a browser -- copy the URL above."
else
    say "   No 'open' command here; copy the URL above."
fi

say ""
say "${B}Ready.${RST} Press Ctrl-C to stop both servers cleanly."
wait
