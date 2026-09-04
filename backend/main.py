"""Bhar backend. Three endpoints, deliberately (SPEC 6, D8).

`data/results.json` on disk is the entire system boundary between the scoring pipeline
and the page. T3 writes a synthetic fixture there; T5 overwrites the same file with real
results and touches no frontend code.

Two things here are load-bearing and easy to break:

1. The FastAPI title is the *identity discriminator*. A VS Code helper squats port 8000
   and answers /health with a byte-identical {"status":"ok"}, so every verification step
   must read /openapi.json's title instead. Do not rename this app.
2. CORSMiddleware is not optional. The page is served from :5173 and the API from :8000 --
   different origins. Without CORS the page renders full chrome and zero data, and the
   only symptom is a console error nobody looks at during a demo.

There is no refetch endpoint, not even a 501 stub: a live-fetch route that is never
pressed is dead code on the demo path. The refresh path is the offline CLI, documented
in the README.
"""

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from backend.contract import ContractError, load_and_validate

# Resolved from this file, never from the CWD -- uvicorn may be started from anywhere.
REPO_ROOT = Path(__file__).resolve().parent.parent
RESULTS_PATH = REPO_ROOT / "data" / "results.json"

MISSING_RESULTS_DETAIL = (
    "No results file at data/results.json. "
    "Run: uv run python -m backend.make_fixture (fixture) or uv run python -m score.run (real)."
)

app = FastAPI(title="Bhar - Site-Tuned Model Blend")

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1):\d+",
    allow_methods=["GET"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    # Kept for liveness only. NEVER use this to confirm you reached *this* service --
    # see the module docstring. /openapi.json's title is the identity check.
    return {"status": "ok"}


@app.get("/api/results")
def get_results():
    """Serve data/results.json whole, contract-validated on every request.

    Re-read and re-validated per request (the file is a few hundred KB) so that T5 can
    swap the file in without restarting the server.

    A missing or invalid file returns 503 with a reason. It must NEVER return an
    empty-but-well-formed payload, and must NEVER silently fall back to
    data/results.synthetic.json -- either would render a page that looks fine and is
    wrong, which is the exact failure class SPEC 10 exists to prevent.
    """
    if not RESULTS_PATH.exists():
        raise HTTPException(status_code=503, detail=MISSING_RESULTS_DETAIL)
    try:
        return load_and_validate(RESULTS_PATH)
    except ContractError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"data/results.json failed the SPEC 7 contract: {exc}",
        ) from exc
    except (OSError, ValueError) as exc:
        raise HTTPException(
            status_code=503,
            detail=f"data/results.json could not be read as JSON: {exc}",
        ) from exc
