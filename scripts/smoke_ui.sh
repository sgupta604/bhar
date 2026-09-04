#!/usr/bin/env bash
# SPEC 13 UI smoke check for T3 demo-shell. Lives OUTSIDE pytest: it needs running
# servers, and pytest must stay hermetic (TR7).
#
# Drives the page with agent-browser 0.36.0. Sliders are set via `eval` rather than
# `fill` -- probed 2026-09-04 03:14, `fill` on an <input type=range> reports success
# without moving the thumb.
#
# The assertion that matters (SPEC 8 / D5) is step 5: the number under the sliders must
# AGREE with the blend in the API payload, not merely change. A check that only proves
# "the number changed" would pass against a page that fabricates values.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."
REPO_ROOT="$PWD"

BACKEND_PORT="${BHAR_BACKEND_PORT:-8000}"
FRONTEND_PORT="${BHAR_FRONTEND_PORT:-5173}"
API_BASE="http://localhost:${BACKEND_PORT}"
PAGE_URL="http://localhost:${FRONTEND_PORT}/?api=${API_BASE}"
SHOT_DIR="${REPO_ROOT}/.claude/active-work/site-tuned-blend/screenshots"
SHOT_PATH="${SHOT_DIR}/demo-shell.png"
PAYLOAD="$(mktemp -t bhar-smoke-payload)"

STARTED_STACK=0
BACKEND_PID=""
FRONTEND_PID=""

fail() { echo "SMOKE FAIL: $*" >&2; exit 1; }
ok()   { echo "  ok  $*"; }

cleanup() {
    trap - EXIT INT TERM
    agent-browser close >/dev/null 2>&1 || true
    if [ "$STARTED_STACK" = "1" ]; then
        for pid in "$BACKEND_PID" "$FRONTEND_PID"; do
            [ -n "$pid" ] || continue
            pkill -P "$pid" 2>/dev/null || true   # uv run spawns a child; killing only the
            kill "$pid" 2>/dev/null || true       # wrapper orphans python on the port
        done
        wait 2>/dev/null || true
    fi
    rm -f "$PAYLOAD"
}
trap cleanup EXIT INT TERM

# --- bring the stack up if it is not already ------------------------------------------
if ! curl -fsS --max-time 2 "${API_BASE}/openapi.json" >/dev/null 2>&1; then
    echo "Starting backend on ${BACKEND_PORT} and frontend on ${FRONTEND_PORT}..."
    STARTED_STACK=1
    uv run uvicorn backend.main:app --port "$BACKEND_PORT" >/dev/null 2>&1 &
    BACKEND_PID=$!
    uv run python -m http.server "$FRONTEND_PORT" --directory frontend >/dev/null 2>&1 &
    FRONTEND_PID=$!
    for _ in $(seq 1 40); do
        curl -fsS --max-time 2 "${API_BASE}/openapi.json" >/dev/null 2>&1 && break
        sleep 0.5
    done
fi

# --- 1. identity ----------------------------------------------------------------------
# NEVER /health: a VS Code helper squats port 8000 and answers {"status":"ok"}
# byte-identically, which would fake a green check.
echo "[1] backend identity via /openapi.json"
TITLE="$(curl -fsS --max-time 5 "${API_BASE}/openapi.json" \
    | python3 -c 'import json,sys; print(json.load(sys.stdin)["info"]["title"])')" \
    || fail "could not read ${API_BASE}/openapi.json"
[ "$TITLE" = "Bhar - Site-Tuned Model Blend" ] \
    || fail "wrong service on ${BACKEND_PORT}: openapi title is '${TITLE}' (port squatter?)"
ok "title = ${TITLE}"

curl -fsS --max-time 5 "${API_BASE}/api/results" -o "$PAYLOAD" || fail "/api/results did not return 200"
python3 -c '
import json, sys
d = json.load(open(sys.argv[1]))
n = len(d["results"]["6"]["blends"])
if n != 286:
    sys.exit(f"blends at 6h is {n}, expected the complete 286-point grid")
' "$PAYLOAD" || fail "payload is not the complete weight grid"
ok "/api/results 200, 286 blends at 6h"

# --- 2. page loads, synthetic signals present -----------------------------------------
echo "[2] page + synthetic signals"
agent-browser open "$PAGE_URL" >/dev/null 2>&1 || fail "agent-browser could not open ${PAGE_URL}"
agent-browser eval 'new Promise(r => setTimeout(() => r(1), 1200))' >/dev/null 2>&1 || true

IS_SYN="$(python3 -c 'import json,sys; print(str(json.load(open(sys.argv[1]))["meta"]["is_synthetic"]).lower())' "$PAYLOAD")"
SYN_ATTR="$(agent-browser eval 'document.documentElement.getAttribute("data-synthetic")' | tr -d '"')"
BANNER="$(agent-browser eval 'document.querySelector("#synthetic-banner") ? "yes" : "no"' | tr -d '"')"
DOC_TITLE="$(agent-browser eval 'document.title' | tr -d '"')"

if [ "$IS_SYN" = "true" ]; then
    [ "$SYN_ATTR" = "true" ] || fail "meta.is_synthetic is true but <html data-synthetic> is '${SYN_ATTR}'"
    [ "$BANNER" = "yes" ]    || fail "synthetic payload rendered without the #synthetic-banner"
    case "$DOC_TITLE" in "[SYNTHETIC] "*) ;; *) fail "document.title lacks the [SYNTHETIC] prefix: ${DOC_TITLE}";; esac
    ok "banner + data-synthetic=true + [SYNTHETIC] title prefix"
else
    [ "$SYN_ATTR" = "null" ] || fail "meta.is_synthetic is false but data-synthetic is '${SYN_ATTR}'"
    [ "$BANNER" = "no" ]     || fail "real payload still rendered the synthetic banner"
    ok "real payload: no banner, no data-synthetic (correct)"
fi

# --- 3. leaderboard rows (also the CORS canary) ---------------------------------------
# A CORS block renders full chrome with zero rows, so this is where TR5 regressions surface.
echo "[3] leaderboard rows"
# Row set = top 5 non-pure blends + every pure model + the winner (appended if its
# out-of-sample rank is poor, which at 24h it is). Deduped, OOS order. Never hardcoded.
EXPECTED_ROWS="$(python3 -c '
import json, sys
d = json.load(open(sys.argv[1]))
r = d["results"]["6"]
b = r["blends"]
labels = [x["label"] for x in b if not x["is_pure"]][:5]
labels += [x["label"] for x in b if x["is_pure"]]
labels.append(r["winner"]["label"])
print(len(dict.fromkeys(labels)))
' "$PAYLOAD")"
ROWS="$(agent-browser eval 'document.querySelectorAll("[data-row=\"blend\"]").length')"
[ "$ROWS" -ge 9 ] || fail "leaderboard rendered ${ROWS} rows, expected >= 9 (CORS blocked? check the console)"
[ "$ROWS" -eq "$EXPECTED_ROWS" ] || fail "leaderboard rendered ${ROWS} rows, data implies ${EXPECTED_ROWS}"
ok "${ROWS} rows (data-derived, not hardcoded)"

WINNER_ROWS="$(agent-browser eval 'document.querySelectorAll("[data-row=\"blend\"][data-winner=\"true\"]").length')"
[ "$WINNER_ROWS" = "1" ] || fail "expected exactly 1 highlighted winner row, found ${WINNER_ROWS}"
ok "exactly one winner row highlighted"

# --- 4/5. slider AGREEMENT and change -------------------------------------------------
echo "[4] move a weight slider"
read_readout() {
    agent-browser eval '(() => {
        const el = document.querySelector("#weight-readout");
        return JSON.stringify({w: el.getAttribute("data-weights"), mae: el.getAttribute("data-mae-oos")});
    })()'
}
set_slider() {
    agent-browser eval "(() => {
        const s = document.querySelector('input[type=range][data-model=\"$1\"]');
        s.value = '$2';
        s.dispatchEvent(new Event('input', {bubbles: true}));
        return s.value;
    })()" >/dev/null
}

set_slider HRRR 100
sleep 0.3
R1="$(read_readout)"
set_slider HRRR 60
sleep 0.3
R2="$(read_readout)"
ok "read data-weights + data-mae-oos at two slider positions"

echo "[5] AGREEMENT with the API payload, and change between positions"
python3 - "$PAYLOAD" "$R1" "$R2" <<'PY' || fail "slider readout does not agree with /api/results"
import json, sys

payload = json.load(open(sys.argv[1]))
blends = payload["results"]["6"]["blends"]


def unwrap(raw):
    # agent-browser eval returns the JS value JSON-encoded; the readout itself is a
    # JSON string, so it arrives double-encoded.
    v = json.loads(raw)
    if isinstance(v, str):
        v = json.loads(v)
    return v


readouts = []
for arg in sys.argv[2:]:
    r = unwrap(arg)
    if r["w"] is None or r["mae"] is None:
        sys.exit("readout is missing data-weights / data-mae-oos")
    readouts.append((json.loads(r["w"]), r["mae"]))

for weights, shown in readouts:
    if shown.strip() in {"-", "—", ""}:
        sys.exit(f"slider showed a lookup miss for {weights} -- the 286-grid should always hit")
    match = [
        b for b in blends
        if all(abs(b["weights"][m] - float(weights[m])) < 1e-9 for m in b["weights"])
        and set(b["weights"]) == set(weights)
    ]
    if len(match) != 1:
        sys.exit(f"weights {weights} matched {len(match)} blends in the payload, expected 1")
    api_mae = match[0]["mae_out_of_sample"]
    if abs(float(shown) - api_mae) > 1e-9:
        sys.exit(f"DISAGREEMENT: page shows {shown} for {weights}, API says {api_mae}")
    print(f"  ok  {weights} -> {shown} == API {api_mae}")

if readouts[0][1] == readouts[1][1]:
    sys.exit(f"data-mae-oos did not change between slider positions (static label?): {readouts[0][1]}")
print(f"  ok  value changed across positions: {readouts[0][1]} -> {readouts[1][1]}")
PY

# --- 6. 24h lead renders the negative improvement honestly ----------------------------
echo "[6] 24h lead: signed / danger-toned improvement (D4)"
agent-browser eval '(() => {
    const b = document.querySelector("[data-lead=\"24\"]");
    b.click();
    return b.getAttribute("data-lead");
})()' >/dev/null
sleep 0.4
IMP_STATE="$(agent-browser eval 'document.querySelector("#improvement-line").getAttribute("data-improvement-state")' | tr -d '"')"
IMP_TEXT="$(agent-browser eval 'document.querySelector("#improvement-line").textContent')"
API_IMP="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["results"]["24"]["winner"]["improvement_pct_vs_best_single"])' "$PAYLOAD")"

python3 - "$API_IMP" "$IMP_STATE" "$IMP_TEXT" <<'PY' || fail "24h improvement rendered dishonestly"
import json, sys
imp = float(sys.argv[1])
state = sys.argv[2]
text = json.loads(sys.argv[3])
expected = "positive" if imp > 0.05 else ("negative" if imp < -0.05 else "tie")
if state != expected:
    sys.exit(f"improvement {imp} should render state '{expected}', page says '{state}'")
if imp < -0.05 and "−" not in text and "-" not in text:
    sys.exit(f"negative improvement rendered without a minus sign: {text!r}")
print(f"  ok  improvement {imp} rendered as '{state}' with a sign")
PY

# --- 7. no console errors -------------------------------------------------------------
echo "[7] console"
PAGE_ERRORS="$(agent-browser errors 2>/dev/null || true)"
CONSOLE="$(agent-browser console 2>/dev/null || true)"
if echo "$PAGE_ERRORS" | grep -qiE '\S' && ! echo "$PAGE_ERRORS" | grep -qiE 'no (page )?errors|^\s*$'; then
    echo "$PAGE_ERRORS" >&2
    fail "page errors were reported"
fi
if echo "$CONSOLE" | grep -qiE '^\s*(error|\[error\])'; then
    echo "$CONSOLE" >&2
    fail "console errors were reported"
fi
ok "no page or console errors"

# --- 8. screenshot --------------------------------------------------------------------
echo "[8] screenshot"
agent-browser eval '(() => { document.querySelector("[data-lead=\"6\"]").click(); return 1; })()' >/dev/null
sleep 0.4
mkdir -p "$SHOT_DIR"
agent-browser set viewport 1440 900 >/dev/null 2>&1 || true
agent-browser screenshot "$SHOT_PATH" >/dev/null || fail "screenshot failed"
[ -s "$SHOT_PATH" ] || fail "screenshot file is empty: ${SHOT_PATH}"
ok "$SHOT_PATH"

echo
echo "SMOKE PASS"
