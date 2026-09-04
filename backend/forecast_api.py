"""Read-only HTTP surface over ``data/forecast.json`` (FORECAST-SPEC §9).

Every request re-reads the file from disk and re-validates it through
:func:`forecast.contract.load_and_validate_forecast`. That is deliberate: the file is
small, and re-reading it means the offline refresh CLI can swap a new forecast in
underneath a running server without a restart, while the validator stays the single
gate between the page and a fabricated number. A document that fails the contract
becomes a 503 carrying the validator's own message — including the offending JSON path
— never a partial payload and never a silent repair.

The routes live on a module-level :class:`~fastapi.APIRouter` rather than on the app, so
``backend/main.py`` needs exactly one import and one ``include_router`` call, and a later
endpoint can be mounted here without touching ``main.py`` at all. Keep this module free
of import-time side effects for that reason.

Design rules:

* ``FORECAST_PATH`` and ``HISTORY_PATH`` are resolved from ``__file__``, never from the
  CWD — uvicorn may be started from anywhere. They are also the *entire* configuration
  seam: no environment variables, no ``Depends`` overrides, no settings object.
* The path constants are read as module globals at call time, so a test (or a future
  caller) can repoint them and have the change take effect immediately.
* **No bare ``assert``** anywhere. ``python -O`` deletes assertions, and a guard that
  vanishes under an optimisation flag is not a guard.
* The route handlers carry **no return annotation**. A ``-> dict`` would make FastAPI
  build a ``response_model`` and run a pydantic pass over the payload, which can reshape
  or drop keys — defeating the contract validation that just ran. ``/api/results`` in
  ``backend/main.py`` avoids this for the same reason; this module mirrors it.

Deliberately *not* here:

* **No refetch / POST route, not even a stub.** A live-fetch endpoint that nothing ever
  presses is dead code sitting on the demo path. The refresh path is the offline CLI,
  ``uv run --no-sync python -m forecast.refresh``, documented in the README. POST to a
  GET-only route already returns 405 from FastAPI; that needs no code here.
* **No fixture fallback.** If ``data/forecast.json`` is missing or invalid these routes
  503 with the reason. They must never quietly serve a synthetic document instead: a
  page that looks fine and is wrong is the exact failure class SPEC §10 exists to
  prevent. Do not "helpfully" add one.
* **No network client and no remote address.** This module imports no HTTP client of any
  kind and contains no archive location, so a request can never trigger a fetch.
  Fetching happens offline, in the refresh CLI, and only there.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException

from forecast import contract as forecast_contract
from forecast.contract import ContractError, load_and_validate_forecast

# Resolved from this file, never from the CWD -- uvicorn may be started from anywhere.
REPO_ROOT = Path(__file__).resolve().parent.parent
FORECAST_PATH = REPO_ROOT / "data" / "forecast.json"
HISTORY_PATH = REPO_ROOT / "data" / "forecast_history.json"

MISSING_FORECAST_DETAIL = (
    "No forecast cache at data/forecast.json. "
    "Run: uv run --no-sync python -m forecast.refresh"
)

#: Format for a contract failure. ``{exc}`` is interpolated **whole** -- it carries the
#: offending JSON path, which is the entire diagnostic value of the message.
FORECAST_CONTRACT_DETAIL = "data/forecast.json failed the FORECAST-SPEC §9 contract: {exc}"

MISSING_HISTORY_DETAIL = (
    "No history payload at data/forecast_history.json. "
    "It is built offline (FORECAST-SPEC §10) and is not present in this checkout."
)

#: The absent-validator case. It is a 503 and not a pass-through on purpose -- see
#: :func:`get_forecast_history`.
UNVALIDATABLE_HISTORY_DETAIL = (
    "data/forecast_history.json cannot be served: no FORECAST-SPEC §10 validator is "
    "available, and an unvalidated history payload is never served."
)

#: The §10 twin of :data:`FORECAST_CONTRACT_DETAIL`. ``{exc}`` is interpolated **whole**
#: for the same reason: it carries the offending JSON path.
HISTORY_CONTRACT_DETAIL = (
    "data/forecast_history.json failed the FORECAST-SPEC §10 contract: {exc}"
)

router = APIRouter()


def _load_forecast() -> dict:
    """Read and validate the forecast document, or raise the 503 that explains why not.

    ``FORECAST_PATH`` is looked up as a module global on every call, so repointing the
    constant takes effect without rebuilding the router.

    One ``except ContractError`` is sufficient and correct:
    :func:`~forecast.contract.load_and_validate_forecast` already wraps an unreadable
    file (``OSError``) and unparseable bytes (``json.JSONDecodeError``) into
    ``ContractError`` alongside the structural violations. A broader ``except`` on top
    would swallow real bugs in this process and report them as a bad data file.
    """
    if not FORECAST_PATH.exists():
        raise HTTPException(status_code=503, detail=MISSING_FORECAST_DETAIL)
    try:
        return load_and_validate_forecast(FORECAST_PATH)
    except ContractError as exc:
        raise HTTPException(
            status_code=503,
            detail=FORECAST_CONTRACT_DETAIL.format(exc=exc),
        ) from exc


def _history_validator():
    """Resolve the FORECAST-SPEC §10 history validator by name, or ``None`` if absent.

    The lookup goes through the imported **module object** and happens on every call, so
    the day F6 adds ``load_and_validate_history`` to ``forecast/contract.py`` the endpoint
    lights up with **zero** edits to this file. A
    ``from forecast.contract import load_and_validate_history`` would freeze the lookup at
    import time -- and would fail outright today, since the function does not exist yet.
    """
    return getattr(forecast_contract, "load_and_validate_history", None)


@router.get(
    "/api/forecast",
    summary="The current forward forecast for the site, whole",
    description=(
        "Returns the complete FORECAST-SPEC §9 document: `meta` (init time, staleness and "
        "the provenance of the blend weights), `forecast` (one row per lead hour, each "
        "carrying every member model's value alongside the weighted blend), `gaps` (the "
        "lead hours that are deliberately absent, each with a stated reason) and `skill` "
        "(how the blend scored against its members in the backtest that fitted the weights).\n\n"
        "The file is re-read and re-validated on **every** request, so an offline refresh "
        "is picked up without restarting the server. If the cache is missing, unreadable, "
        "unparseable or fails the contract, this returns **503** with a `detail` naming the "
        "reason — and, for a contract failure, the exact JSON path of the offending value. "
        "It never returns a partial document and never falls back to a synthetic one: a "
        "missing forecast is reported as missing, not papered over."
    ),
)
def get_forecast():
    return _load_forecast()


@router.get(
    "/api/forecast/skill",
    summary="Backtest skill of the blend, by lead hour",
    description=(
        "Returns the `skill` block of the forecast document verbatim — `basis`, `window`, "
        "`note` and `by_lead` — with no envelope, no filtering and no re-derivation. It is "
        "the same object served under `skill` by `/api/forecast`, offered separately so a "
        "caller that only wants the honest scorecard need not pull the whole document.\n\n"
        "`by_lead` reports, per lead hour, how the site-tuned blend compared with the "
        "individual models over the backtest window. A negative `improvement_pct` is a "
        "real, publishable result: the blend lost at that lead. Nothing here is smoothed "
        "or suppressed to make the blend look better.\n\n"
        "Backed by the same file and the same validation as `/api/forecast`, so the two "
        "endpoints can never disagree about whether the forecast is servable: if the "
        "document is missing or invalid, this returns **503** with the same `detail`."
    ),
)
def get_forecast_skill():
    return _load_forecast()["skill"]


@router.get(
    "/api/forecast/history",
    summary="Recent forecast-versus-observed history for the site",
    description=(
        "Returns the FORECAST-SPEC §10 history document whole: the recent days on which "
        "the site-tuned blend was scored against what the station actually recorded. It "
        "is the receipt behind `/api/forecast/skill` — the numbers a reader can check the "
        "blend's claimed skill against, rather than taking it on trust.\n\n"
        "The payload is built **offline** and read here; nothing on this path fetches, "
        "recomputes or backfills anything. It is validated on every request by the §10 "
        "contract validator, exactly as `/api/forecast` is validated by the §9 one.\n\n"
        "This returns **503** with a `detail` explaining which of three things is true: "
        "the payload is not present in this checkout; no §10 validator is available, so "
        "the bytes on disk cannot be vouched for; or the document failed the contract, in "
        "which case the `detail` carries the exact JSON path of the offending value. "
        "There is no fourth outcome: an unvalidated history payload is never served."
    ),
)
def get_forecast_history():
    """Serve the validated §10 history document, or the 503 that explains why not.

    ``HISTORY_PATH`` is read as a module global on every call, so repointing the constant
    takes effect immediately.

    The F6 seam is the name **``forecast.contract.load_and_validate_history(path) -> dict``**
    — the exact twin of :func:`~forecast.contract.load_and_validate_forecast`, raising
    ``ContractError`` with a message naming the offending JSON path. F6 adds that one
    function; this module does not change.

    Two details of the order are deliberate:

    * **The missing file is checked first.** With no payload on disk, "there is no history
      payload" is the operator's real problem; blaming the validator would send them to
      fix the wrong thing.
    * **An absent validator is a 503, not a pass-through.** Serving the bytes unvalidated
      "because the validator is not written yet" is precisely the failure this project
      exists to prevent: a page that looks fine and is wrong. Until F6 lands, this
      endpoint's honest answer is that it cannot vouch for the file — so it says so, with
      a status code the page can act on, and it is *impossible* for a 200 to leave here
      without a validator having run.
    """
    if not HISTORY_PATH.exists():
        raise HTTPException(status_code=503, detail=MISSING_HISTORY_DETAIL)

    validate = _history_validator()
    if validate is None:
        raise HTTPException(status_code=503, detail=UNVALIDATABLE_HISTORY_DETAIL)

    try:
        return validate(HISTORY_PATH)
    except ContractError as exc:
        raise HTTPException(
            status_code=503,
            detail=HISTORY_CONTRACT_DETAIL.format(exc=exc),
        ) from exc
