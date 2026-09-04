#!/usr/bin/env bash
#
# f5_payload_swap.sh -- trap-restoring harness for swapping data/forecast.json
# in and out for UI/API probes, without ever risking the one live copy of
# NOAA cycle 2026090412 that this checkout holds.
#
# Usage: scripts/f5_payload_swap.sh <fixture|truncated|missing|corrupt|restore|status>
#
# Safety model (see .claude/active-work/forecast-page/ task notes for the full spec):
#   1. The backup lives OUTSIDE the repo, at ${F5_BACKUP:-$TMPDIR/f5-live-forecast.json},
#      with its SHA-256 recorded in a ".sha256" sidecar next to it. It is created once,
#      on first use, from whatever is currently at data/forecast.json.
#   2. Before any swap, the script refuses to run if a backup already exists whose
#      recorded SHA disagrees with the current live file AND the current file is not
#      one of the known swap payloads (fixture / truncated-src / corrupt). That
#      combination means a previous swap did not restore -- overwriting the backup
#      now would destroy the only copy of the live payload.
#   3. A trap restores the live payload on ABNORMAL exit only (non-zero status, or
#      SIGINT/SIGTERM). A successful swap subcommand (fixture/truncated/missing/corrupt)
#      deliberately leaves the swapped file in place on a clean exit -- that's the
#      whole point of the harness, so a browser/probe can be driven against it.
#   4. `restore` re-verifies the restored file's SHA-256 against the recorded backup
#      SHA and exits non-zero, loudly, on any mismatch.
#   5. The repo root is resolved from this script's own location, never from $PWD, and
#      is asserted to be exactly /Users/sanjaygupta/Projects/Bhar-forecast. This is the
#      guard that stops the script from ever touching the sibling Bhar checkout.
#   6. The live file is only ever replaced via cp+mv-into-place. `rm` is used ONLY in
#      `missing` mode, and only after the backup is confirmed present and SHA-verified.

set -euo pipefail

# ---------------------------------------------------------------- repo root guard

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
EXPECTED_ROOT="/Users/sanjaygupta/Projects/Bhar-forecast"

if [[ "${REPO_ROOT}" != "${EXPECTED_ROOT}" ]]; then
  echo "f5_payload_swap: REFUSING TO RUN -- resolved repo root '${REPO_ROOT}' is not '${EXPECTED_ROOT}'." >&2
  echo "f5_payload_swap: this script must never operate against any other checkout." >&2
  exit 1
fi

# ---------------------------------------------------------------- paths

LIVE="${REPO_ROOT}/data/forecast.json"
FIXTURE="${REPO_ROOT}/data/forecast.fixture.json"

BACKUP="${F5_BACKUP:-${TMPDIR:-/tmp}/f5-live-forecast.json}"
BACKUP_SHA_FILE="${BACKUP}.sha256"

CORRUPT_FILE="${TMPDIR:-/tmp}/f5-corrupt-forecast.json"

# ---------------------------------------------------------------- helpers

sha256_of() {
  shasum -a 256 "$1" | awk '{print $1}'
}

# Deterministic, structurally-valid-JSON corruption: drop the required top-level
# "skill" key from the fixture. forecast/contract.py's validate_forecast() calls
# _exact_keys(doc, "$", _TOP_KEYS) first thing, so this fails with
#   ContractError("$: missing required key(s) ['skill']")
# which backend/forecast_api.py wraps into the 503 detail, and it names a JSON path
# ("$") the way a raw JSON-parse error would not.
build_corrupt_payload() {
  if [[ ! -f "${FIXTURE}" ]]; then
    return 1
  fi
  python3 - "${FIXTURE}" "${CORRUPT_FILE}" <<'PYEOF'
import json
import sys

src, dst = sys.argv[1], sys.argv[2]
with open(src) as f:
    doc = json.load(f)
doc.pop("skill", None)
with open(dst, "w") as f:
    json.dump(doc, f, indent=2)
    f.write("\n")
PYEOF
}

# True if $1's contents match a payload this harness itself would put in place
# (fixture, the caller-supplied truncated source, or the deterministic corrupt
# payload). Used only to decide whether an existing SHA mismatch against the
# backup is "a swap in progress" (fine) or "an unrestored prior swap" (refuse).
is_known_swap_payload() {
  local file="$1"
  local file_sha
  file_sha="$(sha256_of "${file}")"

  if [[ -f "${FIXTURE}" ]] && [[ "${file_sha}" == "$(sha256_of "${FIXTURE}")" ]]; then
    return 0
  fi

  if [[ -n "${F5_TRUNCATED_SRC:-}" ]] && [[ -f "${F5_TRUNCATED_SRC}" ]]; then
    if [[ "${file_sha}" == "$(sha256_of "${F5_TRUNCATED_SRC}")" ]]; then
      return 0
    fi
  fi

  build_corrupt_payload 2>/dev/null || true
  if [[ -f "${CORRUPT_FILE}" ]] && [[ "${file_sha}" == "$(sha256_of "${CORRUPT_FILE}")" ]]; then
    return 0
  fi

  return 1
}

# Create the off-repo backup on first use, or validate it's still trustworthy to
# swap against on subsequent uses. Safety requirement #2 lives here.
ensure_backup() {
  if [[ ! -f "${BACKUP}" ]]; then
    if [[ ! -f "${LIVE}" ]]; then
      echo "f5_payload_swap: no backup exists at ${BACKUP} and no live file at ${LIVE} to back up from." >&2
      echo "f5_payload_swap: cannot proceed without a known-good live payload to protect." >&2
      exit 1
    fi
    cp "${LIVE}" "${BACKUP}"
    sha256_of "${LIVE}" > "${BACKUP_SHA_FILE}"
    echo "f5_payload_swap: created off-repo backup at ${BACKUP} (sha256 $(cat "${BACKUP_SHA_FILE}"))" >&2
    return 0
  fi

  if [[ ! -f "${BACKUP_SHA_FILE}" ]]; then
    echo "f5_payload_swap: REFUSING TO RUN -- backup exists at ${BACKUP} but its .sha256 sidecar is missing." >&2
    echo "f5_payload_swap: cannot verify the backup is trustworthy. Investigate manually before proceeding." >&2
    exit 1
  fi

  local recorded_sha
  recorded_sha="$(cat "${BACKUP_SHA_FILE}")"

  if [[ -f "${LIVE}" ]]; then
    local live_sha
    live_sha="$(sha256_of "${LIVE}")"
    if [[ "${live_sha}" != "${recorded_sha}" ]] && ! is_known_swap_payload "${LIVE}"; then
      echo "f5_payload_swap: REFUSING TO RUN." >&2
      echo "f5_payload_swap:   data/forecast.json (sha ${live_sha}) does not match the recorded" >&2
      echo "f5_payload_swap:   backup sha (${recorded_sha}), and it is not a recognised swap payload" >&2
      echo "f5_payload_swap:   (fixture / F5_TRUNCATED_SRC / corrupt)." >&2
      echo "f5_payload_swap:   This means a previous swap did not restore cleanly. Overwriting the" >&2
      echo "f5_payload_swap:   existing backup now could destroy the only copy of the live payload." >&2
      echo "f5_payload_swap:   Run '$0 restore' first, then re-run." >&2
      exit 1
    fi
  else
    echo "f5_payload_swap: NOTE -- data/forecast.json is currently absent (a prior 'missing' swap may" >&2
    echo "f5_payload_swap:   not have been restored). The off-repo backup is untouched and safe; proceeding." >&2
  fi
}

# Copy the backup back into place and verify its SHA-256 against the recorded value.
# Used by both the explicit `restore` subcommand and the abnormal-exit trap. Never
# calls exit itself -- callers decide how loudly to fail.
restore_live_quiet() {
  if [[ ! -f "${BACKUP}" ]]; then
    echo "f5_payload_swap: no backup at ${BACKUP} -- cannot restore." >&2
    return 1
  fi
  if [[ ! -f "${BACKUP_SHA_FILE}" ]]; then
    echo "f5_payload_swap: no .sha256 sidecar at ${BACKUP_SHA_FILE} -- cannot verify a restore." >&2
    return 1
  fi

  local tmp
  tmp="${LIVE}.restoring.$$"
  cp "${BACKUP}" "${tmp}"
  mv "${tmp}" "${LIVE}"

  local live_sha recorded_sha
  live_sha="$(sha256_of "${LIVE}")"
  recorded_sha="$(cat "${BACKUP_SHA_FILE}")"
  if [[ "${live_sha}" != "${recorded_sha}" ]]; then
    echo "f5_payload_swap: RESTORE VERIFICATION FAILED -- live sha ${live_sha} != backup sha ${recorded_sha}" >&2
    return 1
  fi

  echo "f5_payload_swap: restored live payload to data/forecast.json (sha ${live_sha}, verified)." >&2
  return 0
}

# ---------------------------------------------------------------- trap wiring
#
# _SWAP_PERSISTS=1 marks "a swap subcommand completed its intentional work; leave
# the file exactly as swapped, do not restore on this clean exit." It is set only
# at the very end of cmd_fixture / cmd_truncated / cmd_missing / cmd_corrupt, right
# before they return 0. `restore` and `status` never set it -- for them, exit 0
# means nothing more needs to happen, and exit != 0 means restore_live_quiet already
# ran (for `restore`) or nothing was ever touched (for `status`).
#
# _RESTORED_THIS_RUN guards against restoring twice (once from a signal handler,
# again from the EXIT trap that fires right after it).

_SWAP_PERSISTS=0
_RESTORED_THIS_RUN=0

_f5_restore_once() {
  if [[ "${_RESTORED_THIS_RUN}" -eq 1 ]]; then
    return 0
  fi
  _RESTORED_THIS_RUN=1
  restore_live_quiet || echo "f5_payload_swap: restore-on-exit did not verify cleanly -- check data/forecast.json by hand." >&2
}

_f5_on_signal() {
  local sig="$1"
  echo "f5_payload_swap: caught SIG${sig} -- restoring live payload before exiting." >&2
  _f5_restore_once
  trap - EXIT INT TERM
  exit 130
}

_f5_on_exit() {
  local code=$?
  if [[ "${_SWAP_PERSISTS}" -eq 1 ]]; then
    # Successful, intentional swap -- the operator wants this file left in place.
    return 0
  fi
  if [[ "${code}" -ne 0 ]]; then
    echo "f5_payload_swap: abnormal exit (code ${code}) -- restoring live payload before exiting." >&2
    _f5_restore_once
  fi
}

trap '_f5_on_signal INT' INT
trap '_f5_on_signal TERM' TERM
trap '_f5_on_exit' EXIT

# ---------------------------------------------------------------- subcommands

cmd_fixture() {
  ensure_backup
  if [[ ! -f "${FIXTURE}" ]]; then
    echo "f5_payload_swap: fixture not found at ${FIXTURE}" >&2
    exit 1
  fi
  local tmp
  tmp="${LIVE}.swap.$$"
  cp "${FIXTURE}" "${tmp}"
  mv "${tmp}" "${LIVE}"
  echo "f5_payload_swap: swapped in fixture payload (sha $(sha256_of "${LIVE}"))." >&2
  _SWAP_PERSISTS=1
}

cmd_truncated() {
  if [[ -z "${F5_TRUNCATED_SRC:-}" ]]; then
    echo "f5_payload_swap: F5_TRUNCATED_SRC is not set. Point it at the truncated-horizon" >&2
    echo "f5_payload_swap: document produced by the parallel probe task -- this harness will" >&2
    echo "f5_payload_swap: not synthesize one itself." >&2
    exit 1
  fi
  if [[ ! -f "${F5_TRUNCATED_SRC}" ]]; then
    echo "f5_payload_swap: F5_TRUNCATED_SRC='${F5_TRUNCATED_SRC}' does not exist." >&2
    exit 1
  fi
  ensure_backup
  local tmp
  tmp="${LIVE}.swap.$$"
  cp "${F5_TRUNCATED_SRC}" "${tmp}"
  mv "${tmp}" "${LIVE}"
  echo "f5_payload_swap: swapped in truncated payload from ${F5_TRUNCATED_SRC} (sha $(sha256_of "${LIVE}"))." >&2
  _SWAP_PERSISTS=1
}

cmd_missing() {
  ensure_backup
  # Requirement #6: rm only here, and only once the backup is confirmed present
  # and its SHA verified against the sidecar.
  if [[ ! -f "${BACKUP}" ]] || [[ ! -f "${BACKUP_SHA_FILE}" ]]; then
    echo "f5_payload_swap: refusing to remove data/forecast.json -- backup not confirmed present." >&2
    exit 1
  fi
  local backup_sha recorded_sha
  backup_sha="$(sha256_of "${BACKUP}")"
  recorded_sha="$(cat "${BACKUP_SHA_FILE}")"
  if [[ "${backup_sha}" != "${recorded_sha}" ]]; then
    echo "f5_payload_swap: refusing to remove data/forecast.json -- backup sha ${backup_sha} != recorded ${recorded_sha}." >&2
    exit 1
  fi
  rm -f "${LIVE}"
  echo "f5_payload_swap: removed data/forecast.json (backup verified present at ${BACKUP})." >&2
  _SWAP_PERSISTS=1
}

cmd_corrupt() {
  ensure_backup
  if ! build_corrupt_payload; then
    echo "f5_payload_swap: could not build the corrupt payload (fixture missing?)." >&2
    exit 1
  fi
  local tmp
  tmp="${LIVE}.swap.$$"
  cp "${CORRUPT_FILE}" "${tmp}"
  mv "${tmp}" "${LIVE}"
  echo "f5_payload_swap: swapped in corrupt payload (sha $(sha256_of "${LIVE}"))." >&2
  _SWAP_PERSISTS=1
}

cmd_restore() {
  if restore_live_quiet; then
    echo "f5_payload_swap: restore OK."
  else
    echo "f5_payload_swap: restore FAILED -- see above." >&2
    exit 1
  fi
}

cmd_status() {
  local live_sha="(absent)"
  if [[ -f "${LIVE}" ]]; then
    live_sha="$(sha256_of "${LIVE}")"
  fi
  local backup_sha="(no backup yet)"
  if [[ -f "${BACKUP_SHA_FILE}" ]]; then
    backup_sha="$(cat "${BACKUP_SHA_FILE}")"
  fi
  echo "live sha:   ${live_sha}"
  echo "backup sha: ${backup_sha}"
  if [[ "${live_sha}" == "${backup_sha}" ]]; then
    echo "match:      yes"
  else
    echo "match:      no"
  fi
}

usage() {
  echo "usage: $0 <fixture|truncated|missing|corrupt|restore|status>" >&2
}

main() {
  if [[ $# -ne 1 ]]; then
    usage
    exit 1
  fi
  case "$1" in
    fixture)   cmd_fixture ;;
    truncated) cmd_truncated ;;
    missing)   cmd_missing ;;
    corrupt)   cmd_corrupt ;;
    restore)   cmd_restore ;;
    status)    cmd_status ;;
    *)
      usage
      exit 1
      ;;
  esac
}

main "$@"
