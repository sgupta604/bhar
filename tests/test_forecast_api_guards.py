"""F4 Stream 4 — demo-path regression guards, a source scan, and the two-line diff gate.

Three unrelated machineries live here, deliberately kept out of `tests/test_forecast_api.py`
(which is about endpoint *behaviour*): a `TestClient` over the real shipped app, an
`ast`/`tokenize` scan of `backend/forecast_api.py`, and a `subprocess`/`git` diff gate.

**`backend/main.py` had ZERO test coverage before F4.** Nothing anywhere in the suite
asserted the app title, `/health`, or `/api/results` — the three things the demo path
actually depends on. These tests *create* that guard; they do not re-assert an existing one.
That matters when reading a failure here: there is no prior green run to compare against, and
a failure means the demo path moved, not that a known-good assertion regressed.

Two rules this file is built around:

* **Never verify server identity via `/health`.** A VS Code helper squats port 8000 and
  answers `/health` with a byte-identical `{"status": "ok"}`; it now also serves a
  "Boreas API" OpenAPI document. `/openapi.json` → `info.title` is the only discriminator,
  and `demo.sh` uses exactly that. TEST-7 locks the literal it compares against.
* **A guard that cannot fail is not a guard** (the demo team's inherited retrospective).
  Every pattern in the TEST-9 scan is fed a deliberately bad sample and proven to fire, as
  well as being run against the real module. A pattern that matches nothing is worthless,
  and so is a scan over zero files.

`tests/test_live_guards.py` is deliberately **not** imported from and **not** edited. Its T29
scan globs `forecast/*.py` only; F2 and F3 both left it untouched and that precedent holds, so
F4 carries its own copy of the ~20-line normalizer rather than widening someone else's guard.
"""

from __future__ import annotations

import ast
import io
import json
import re
import shutil
import subprocess
import tokenize
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import backend.contract
import backend.main
import backend.make_fixture

REPO = Path(__file__).resolve().parent.parent

#: The module TEST-9 scans, discovered by path and read from disk at test time. A parallel
#: stream is adding a third handler to it; nothing here may depend on its current contents,
#: its handler count or its length.
FORECAST_API_SOURCE = REPO / "backend" / "forecast_api.py"

#: The identity discriminator. Exact literal, on purpose: a substring check would pass
#: against a squatter titled "Boreas API (Bhar - Site-Tuned Model Blend compatible)".
EXPECTED_APP_TITLE = "Bhar - Site-Tuned Model Blend"

#: Pinned so the fixture document is byte-stable across runs. `build_document` takes a
#: **string stamp**, not a datetime, and defaults to `datetime.now` when omitted — never omit it.
PINNED_GENERATED_AT = "2026-09-04T12:00:00Z"


# ------------------------------------------------------------------------------------------
# TEST-7 / TEST-8 — first-ever coverage of backend/main.py
# ------------------------------------------------------------------------------------------


@pytest.fixture()
def client() -> TestClient:
    """A client over `backend.main.app` — the real shipped app object, not a rebuilt one."""
    return TestClient(backend.main.app)


def write_results_document(directory: Path) -> Path:
    """Write a contract-valid `results.json` into `directory` and return its path.

    `backend.contract` exposes no writer, so the document is validated explicitly through
    `validate_results` before `json.dumps` puts it on disk — same order `make_fixture.write_fixture`
    uses, so a document that could never be served is never written and then asserted against.
    """
    doc = backend.make_fixture.build_document(generated_at=PINNED_GENERATED_AT)
    backend.contract.validate_results(doc)
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / "results.json"
    target.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    return target


def test_test7_openapi_title_is_the_exact_squatter_discriminator(client: TestClient) -> None:
    """`/openapi.json` → `info.title` is how `demo.sh` proves it reached *this* service.

    The port-8000 squatter answers `/health` byte-identically and serves a "Boreas API"
    OpenAPI document, so this literal is the whole identity check. Renaming the app silently
    breaks the demo launcher's verification step, not the app.
    """
    response = client.get("/openapi.json")

    assert response.status_code == 200, response.text
    assert response.json()["info"]["title"] == EXPECTED_APP_TITLE


def test_test8_health_returns_exactly_the_status_ok_body(client: TestClient) -> None:
    """Whole-body equality, not a substring: `/health` carries nothing else, ever."""
    response = client.get("/health")

    assert response.status_code == 200, response.text
    assert response.json() == {"status": "ok"}


def test_test8_api_results_serves_a_valid_document(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`/api/results` still serves a contract-valid document whole, from the monkeypatched path.

    `RESULTS_PATH` is read as a module global inside the handler, so repointing it at `tmp_path`
    is enough — and it means this test never touches the committed `data/results.json`.
    """
    results_path = write_results_document(tmp_path / "data")
    monkeypatch.setattr(backend.main, "RESULTS_PATH", results_path)

    response = client.get("/api/results")

    assert response.status_code == 200, response.text
    assert response.json() == json.loads(results_path.read_text(encoding="utf-8"))


def test_test8_api_results_503s_with_the_missing_results_detail(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A missing file is reported as missing — 503 with the existing reason, never an empty payload."""
    monkeypatch.setattr(backend.main, "RESULTS_PATH", tmp_path / "absent" / "results.json")

    response = client.get("/api/results")

    assert response.status_code == 503, response.text
    assert response.json() == {"detail": backend.main.MISSING_RESULTS_DETAIL}


# ------------------------------------------------------------------------------------------
# TEST-9 — source scan over backend/forecast_api.py
# ------------------------------------------------------------------------------------------


def normalized_code(text: str) -> str:
    """Return `text` as executable code only: comments and docstrings dropped, spacing collapsed.

    Tokenizing (rather than splitting on `#`) means a `#` inside a string literal cannot
    truncate a line, and dropping only *statement-initial* string tokens removes docstrings and
    the endpoints' long `description=` prose is kept only where it is a real expression — every
    string literal that code actually evaluates survives, which is what the URL scan needs to see.

    Reimplemented here rather than imported from `tests/test_live_guards.py`: that file's T29 is
    scoped to `forecast/*.py` and F4 does not widen it.
    """
    pieces: list[str] = []
    at_statement_start = True

    for token in tokenize.generate_tokens(io.StringIO(text).readline):
        if token.type in (tokenize.COMMENT, tokenize.NL, tokenize.ENCODING, tokenize.ENDMARKER):
            continue
        if token.type in (tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT):
            at_statement_start = True
            continue
        if token.type == tokenize.STRING and at_statement_start:
            at_statement_start = False  # a docstring / bare string statement
            continue
        pieces.append(token.string)
        at_statement_start = False

    return " ".join(pieces)


def shown(hit: re.Match | None) -> str:
    """The matched text of `hit`, for a failure message. `""` when there is no hit."""
    return repr(hit.group(0)) if hit else ""



#: Any HTTP client import. A request handler that can reach the network can fetch on the
#: request path; the refresh CLI is the only place fetching is allowed to happen.
HTTP_CLIENT_IMPORT = re.compile(
    r"\b(?:import|from)\s+(?:requests|httpx|aiohttp|urllib|http\s*\.\s*client)\b"
)

#: An archive location baked into the module. Covers every archive this repo actually reads:
#: the S3 GRIB buckets (`https://{bucket}.s3.amazonaws.com/{key}`) and IEM's ASOS endpoint.
#: A URL literal here would be the other half of a request-path fetch. The gap between the
#: scheme and the host tolerates whitespace on purpose: Python 3.12 tokenizes an f-string into
#: FSTRING_START/MIDDLE parts, so the normalizer renders one as `f" https:// { bucket } .s3...`
#: and a `[^\s]`-style gap would let an f-string URL walk straight through this guard.
ARCHIVE_URL_LITERAL = re.compile(
    r"https?://[^\"']{0,200}?(?:amazonaws\.com|s3[.-]|nomads|noaa|mesonet|agron\.iastate\.edu)"
    r"|\bnoaa-[a-z0-9-]+-bdp-pds\b",
    re.IGNORECASE,
)

#: A write-method route, in either spelling: a `@router.post(...)`-style decorator, or an
#: explicit `methods=[...]` list carrying a write verb (`add_api_route`, `api_route`).
WRITE_ROUTE_DECORATOR = re.compile(r"@\s*[A-Za-z_]\w*\s*\.\s*(?:post|put|delete|patch)\s*\(", re.I)
WRITE_METHODS_KWARG = re.compile(
    r"methods\s*=\s*[\[\(][^\]\)]*['\"](?:POST|PUT|DELETE|PATCH)['\"]", re.I
)


def bare_assert_lines(text: str, filename: str = "<sample>") -> list[int]:
    """Line numbers of every bare `assert` statement in `text`."""
    tree = ast.parse(text, filename=filename)
    return sorted(node.lineno for node in ast.walk(tree) if isinstance(node, ast.Assert))


#: The verbs a router decorator can spell. `@router.get(...)` and friends only — an attribute
#: decorator like `@functools.lru_cache` is not a route and must not be scanned as one.
ROUTE_DECORATOR_VERBS = frozenset(
    {"get", "post", "put", "delete", "patch", "head", "options", "trace"}
)


def route_handler_decorators(
    text: str, filename: str = "<forecast_api>"
) -> list[tuple[ast.FunctionDef | ast.AsyncFunctionDef, str]]:
    """Every `(function node, verb)` pair for an `@<name>.<verb>(...)` route decorator.

    The single decorator walk the TEST-9 route scans share: `def` and `async def` alike, both
    the bare (`@router.get`) and called (`@router.get("/path")`) decorator spellings. Callers
    filter on the verb; nothing here decides what counts as forbidden.
    """
    tree = ast.parse(text, filename=filename)
    found: list[tuple[ast.FunctionDef | ast.AsyncFunctionDef, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        for decorator in node.decorator_list:
            func = decorator.func if isinstance(decorator, ast.Call) else decorator
            if isinstance(func, ast.Attribute):
                found.append((node, func.attr.lower()))
    return found


def route_decorator_methods(text: str) -> list[str]:
    """The HTTP verbs of every `@<name>.<verb>(...)` route decorator, in source order."""
    return [verb for _node, verb in route_handler_decorators(text)]


def annotated_route_handlers(text: str, filename: str = "<forecast_api>") -> list[tuple[str, int]]:
    """`(name, line)` for every route handler that carries a return annotation."""
    return sorted(
        {
            (node.name, node.lineno)
            for node, verb in route_handler_decorators(text, filename=filename)
            if verb in ROUTE_DECORATOR_VERBS and node.returns is not None
        }
    )


def route_handler_names(text: str, filename: str = "<forecast_api>") -> list[str]:
    """The names of every route handler the decorator walk found, deduplicated."""
    return sorted(
        {
            node.name
            for node, verb in route_handler_decorators(text, filename=filename)
            if verb in ROUTE_DECORATOR_VERBS
        }
    )


@pytest.fixture(scope="module")
def forecast_api_text() -> str:
    """The module's source, read from disk at test time — never a pinned copy of its contents."""
    return FORECAST_API_SOURCE.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def forecast_api_code(forecast_api_text: str) -> str:
    return normalized_code(forecast_api_text)


def test_test9_the_scan_actually_sees_source(forecast_api_text: str, forecast_api_code: str) -> None:
    """A scan over zero files passes vacuously. Prove there is something to scan.

    Deliberately shaped as a floor, not an equality: a parallel stream is adding a third
    handler, so this asserts the module is present, non-trivial and routing — not how much of it
    there is.
    """
    assert FORECAST_API_SOURCE.is_file(), f"{FORECAST_API_SOURCE} is missing — every TEST-9 scan below was vacuous"
    assert forecast_api_text.strip(), f"{FORECAST_API_SOURCE.name} is empty"
    assert len(forecast_api_code) > 500, (
        f"{FORECAST_API_SOURCE.name} normalizes to {len(forecast_api_code)} chars of code — "
        f"too little to be the router module the scans below assume"
    )
    assert "APIRouter" in forecast_api_code, "the scanned module defines no APIRouter"

    verbs = route_decorator_methods(forecast_api_text)
    assert verbs.count("get") >= 2, f"expected at least two GET routes, found decorators {verbs}"


def test_test9_normalizer_keeps_code_strings_and_drops_docstrings() -> None:
    """The normalizer itself must not be the hole. Comments and docstrings out, literals in."""
    sample = '''"""A docstring mentioning import requests and https://noaa.example/key."""
# A comment mentioning import httpx and https://x.s3.amazonaws.com/k.
LABEL = "keep # this"
import requests
'''
    code = normalized_code(sample)

    assert "A docstring mentioning" not in code, "docstrings must be dropped"
    assert "A comment mentioning" not in code, "comments must be dropped"
    assert '"keep # this"' in code, "a `#` inside a string literal must not truncate the line"
    assert HTTP_CLIENT_IMPORT.search(code), (
        "the HTTP-client pattern must fire on the real import it exists to catch, not only on "
        "the prose in the docstring the normalizer just removed"
    )
    assert not ARCHIVE_URL_LITERAL.search(code), (
        "a URL mentioned only in a docstring or comment must not count as a request-path fetch"
    )


def test_test9_no_bare_assert_in_forecast_api(forecast_api_text: str) -> None:
    """`python -O` strips `assert`, so a guard written as one vanishes in production."""
    lines = bare_assert_lines(forecast_api_text, filename=str(FORECAST_API_SOURCE))

    assert not lines, (
        f"{FORECAST_API_SOURCE.name} uses bare `assert` at line(s) {lines}; `python -O` deletes "
        f"those, so the guard silently disappears in production — raise instead"
    )


def test_test9_bare_assert_guard_fires_on_a_bad_sample() -> None:
    """A guard that cannot fail is not a guard."""
    bad = "def handler(doc):\n    assert doc, 'empty'\n    return doc\n"

    assert bare_assert_lines(bad) == [2]


@pytest.mark.parametrize(
    "bad",
    [
        "import requests",
        "import httpx",
        "from httpx import AsyncClient",
        "import urllib.request",
        "from urllib.request import urlopen",
        "import http.client",
    ],
)
def test_test9_http_client_guard_fires_on_a_bad_sample(bad: str) -> None:
    assert HTTP_CLIENT_IMPORT.search(normalized_code(bad + "\n")), f"guard missed {bad!r}"


def test_test9_no_http_client_import_in_forecast_api(forecast_api_code: str) -> None:
    """No HTTP client of any kind: a request handler that cannot reach the network cannot fetch."""
    hit = HTTP_CLIENT_IMPORT.search(forecast_api_code)

    assert hit is None, (
        f"{FORECAST_API_SOURCE.name} imports an HTTP client ({shown(hit)}); "
        f"fetching happens offline in the refresh CLI and only there — a request path that can "
        f"fetch is a demo that hangs on a slow archive"
    )


@pytest.mark.parametrize(
    "bad",
    [
        'GRIB_URL = f"https://{bucket}.s3.amazonaws.com/{key}"',
        'IEM_URL = "https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py"',
        'BASE = "https://nomads.ncep.noaa.gov/pub/data"',
        'BUCKET = "noaa-hrrr-bdp-pds"',
    ],
)
def test_test9_archive_url_guard_fires_on_a_bad_sample(bad: str) -> None:
    assert ARCHIVE_URL_LITERAL.search(normalized_code(bad + "\n")), f"guard missed {bad!r}"


def test_test9_no_archive_url_literal_in_forecast_api(forecast_api_code: str) -> None:
    """No archive location in executable code — the other half of the no-fetch proof."""
    hit = ARCHIVE_URL_LITERAL.search(forecast_api_code)

    assert hit is None, (
        f"{FORECAST_API_SOURCE.name} names an archive location in executable code: "
        f"{shown(hit)}; the request path reads a local file and nothing else"
    )


@pytest.mark.parametrize(
    "bad",
    [
        '@router.post("/api/forecast/refresh")\ndef refetch():\n    return {}\n',
        '@router.put("/api/forecast")\ndef replace():\n    return {}\n',
        '@app.delete("/api/forecast")\ndef drop():\n    return {}\n',
        '@router.patch("/api/forecast")\ndef tweak():\n    return {}\n',
        'router.add_api_route("/api/forecast/refresh", refetch, methods=["POST"])\n',
    ],
)
def test_test9_write_route_guard_fires_on_a_bad_sample(bad: str) -> None:
    code = normalized_code(bad)

    assert WRITE_ROUTE_DECORATOR.search(code) or WRITE_METHODS_KWARG.search(code), (
        f"guard missed {bad!r}"
    )


def test_test9_no_write_method_route_in_forecast_api(
    forecast_api_text: str, forecast_api_code: str
) -> None:
    """Read-only surface. A refetch route that nothing presses is dead code on the demo path.

    Checked three ways so a rename cannot slip past: the decorator spelling, the explicit
    `methods=[...]` spelling, and the verbs `ast` actually sees on the decorators.
    """
    decorator_hit = WRITE_ROUTE_DECORATOR.search(forecast_api_code)
    assert decorator_hit is None, (
        f"{FORECAST_API_SOURCE.name} declares a write route: {shown(decorator_hit)}"
    )

    kwarg_hit = WRITE_METHODS_KWARG.search(forecast_api_code)
    assert kwarg_hit is None, (
        f"{FORECAST_API_SOURCE.name} registers a write method: {shown(kwarg_hit)}"
    )

    verbs = route_decorator_methods(forecast_api_text)
    forbidden = sorted({verb for verb in verbs if verb in {"post", "put", "delete", "patch"}})
    assert not forbidden, f"{FORECAST_API_SOURCE.name} decorates handler(s) with {forbidden}"


def test_test9_no_return_annotation_on_a_forecast_api_route_handler(forecast_api_text: str) -> None:
    """No route handler may declare a return type. FastAPI reads one as a `response_model`.

    A `-> dict` (or `-> SomeModel`) on a handler makes FastAPI run a pydantic serialization pass
    over the returned payload, which can silently reshape or drop keys — after
    `forecast/contract.py` has already certified the document. That would make the contract
    validator prove something about a payload the client never receives.
    `backend/main.py`'s `/api/results` avoids an annotation for exactly the same reason.

    Scoped to *route handlers*: module-level helpers such as `_load_forecast() -> dict` are
    annotated on purpose and are not served, so they must not trip this.
    """
    handlers = route_handler_names(forecast_api_text, filename=str(FORECAST_API_SOURCE))
    assert len(handlers) >= 2, (
        f"the return-annotation scan found only {handlers} in {FORECAST_API_SOURCE.name} — "
        f"with fewer than two handlers to inspect it would pass vacuously"
    )

    annotated = annotated_route_handlers(forecast_api_text, filename=str(FORECAST_API_SOURCE))

    assert annotated == [], (
        f"{FORECAST_API_SOURCE.name} annotates the return type of route handler(s) "
        f"{[f'{name} (line {line})' for name, line in annotated]}; FastAPI turns a handler's "
        f"return annotation into a pydantic `response_model` and re-serializes the payload "
        f"through it, which can reshape or drop keys the contract validator just certified — "
        f"drop the annotation, as `/api/results` in backend/main.py does"
    )


@pytest.mark.parametrize(
    ("bad", "expected"),
    [
        ('@router.get("/api/forecast")\ndef get_forecast() -> dict:\n    return {}\n', [("get_forecast", 2)]),
        (
            '@router.get("/api/forecast")\nasync def get_forecast() -> dict:\n    return {}\n',
            [("get_forecast", 2)],
        ),
        (
            '@router.get(\n    "/api/forecast/skill",\n)\ndef get_skill() -> JSONResponse:\n    return {}\n',
            [("get_skill", 4)],
        ),
        ('@app.get("/api/forecast")\ndef served() -> ForecastDocument:\n    return {}\n', [("served", 2)]),
    ],
)
def test_test9_return_annotation_guard_fires_on_a_bad_sample(
    bad: str, expected: list[tuple[str, int]]
) -> None:
    """A guard that cannot fail is not a guard — parse a sample, never mutate the real module."""
    assert annotated_route_handlers(bad) == expected, f"guard missed {bad!r}"


@pytest.mark.parametrize(
    "clean",
    [
        '@router.get("/api/forecast")\ndef get_forecast():\n    return {}\n',
        '@router.get("/api/forecast")\nasync def get_forecast():\n    return {}\n',
        'def _load_forecast() -> dict:\n    return {}\n',
        '@functools.lru_cache\ndef _history_validator() -> object:\n    return None\n',
    ],
)
def test_test9_return_annotation_guard_stays_silent_on_clean_source(clean: str) -> None:
    """...and a guard that fires on everything is noise: an undecorated or non-route
    function may be annotated, and an unannotated handler is the shape being enforced."""
    assert annotated_route_handlers(clean) == []


# ------------------------------------------------------------------------------------------
# TEST-10 — the two-line diff gate
# ------------------------------------------------------------------------------------------

#: F4's branch point. **Deliberately not `git merge-base HEAD develop`**, which resolves to
#: `54088fd`: between `54088fd` and F4's branch point sit F2's and F3's already-shipped
#: commits, and those legitimately touch `forecast/`, `.gitignore` and
#: `tests/test_live_guards.py` — three names on F4's off-limits list. Rooting the off-limits
#: scan at the `develop` merge-base would fail this ticket for other tickets' correct work.
#: `backend/main.py` is byte-identical at `54088fd` and at `740dfb0`, so the `2 0` numstat
#: assertion is unaffected by the choice; only the off-limits scan is base-sensitive.
F4_BRANCH_POINT = "740dfb0"

#: `backend/main.py` may gain exactly one import and one `include_router` call. Nothing else
#: in it may move — not the title (the demo's identity gate), not CORS, not a blank line.
EXPECTED_MAIN_NUMSTAT = (2, 0)

#: Paths F4 may not touch. Trailing `/` means "anything under here"; the rest are exact.
OFF_LIMITS = (
    "fetch/",
    "score/",
    "frontend/",
    "docs/",
    "run.sh",
    "demo.sh",
    ".gitignore",
    "tests/test_live_guards.py",
    "backend/contract.py",
    "data/results.json",
)


def git(*args: str) -> subprocess.CompletedProcess:
    """Run a read-only `git` command in this repository."""
    return subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True, check=False)


@pytest.fixture()
def git_repo() -> None:
    """Skip rather than fail when `git` is unavailable or this is not a checkout."""
    if shutil.which("git") is None:
        pytest.skip("git is not available on PATH")
    if git("rev-parse", "--is-inside-work-tree").returncode != 0:
        pytest.skip(f"{REPO} is not a git working tree")


def branch_point() -> str:
    """F4's recorded branch point, resolved to a full sha — or a clean skip if absent."""
    resolved = git("rev-parse", "--verify", f"{F4_BRANCH_POINT}^{{commit}}")
    if resolved.returncode != 0 or not resolved.stdout.strip():
        pytest.skip(f"branch point {F4_BRANCH_POINT} is not present in this checkout")
    return resolved.stdout.strip()


def parse_numstat(output: str) -> dict[str, tuple[int, int]]:
    """`git diff --numstat` output as `{path: (added, deleted)}`. Binary files (`-`) are skipped."""
    parsed: dict[str, tuple[int, int]] = {}
    for line in output.splitlines():
        fields = line.split("\t")
        if len(fields) != 3 or "-" in (fields[0], fields[1]):
            continue
        parsed[fields[2]] = (int(fields[0]), int(fields[1]))
    return parsed


def off_limits_hits(paths: list[str]) -> list[str]:
    """The subset of `paths` that F4 is forbidden to touch."""
    return sorted(
        path
        for path in paths
        for rule in OFF_LIMITS
        if (path.startswith(rule) if rule.endswith("/") else path == rule)
    )


def test_test10_off_limits_matcher_fires_on_a_bad_sample() -> None:
    """A guard that cannot fail is not a guard — prove the matcher catches both rule shapes."""
    assert off_limits_hits(["fetch/grib.py", "backend/main.py", ".gitignore"]) == [
        ".gitignore",
        "fetch/grib.py",
    ]
    assert off_limits_hits(["backend/main.py", "backend/forecast_api.py"]) == []
    assert off_limits_hits(["tests/test_live_guards.py"]) == ["tests/test_live_guards.py"]
    assert off_limits_hits(["docs/SPEC.md", "run.sh", "demo.sh", "data/results.json"]) == [
        "data/results.json",
        "demo.sh",
        "docs/SPEC.md",
        "run.sh",
    ]


@pytest.mark.usefixtures("git_repo")
def test_test10_main_py_gained_exactly_two_lines() -> None:
    """`backend/main.py`: exactly 2 added, 0 deleted — committed, staged and working tree alike.

    `<base>` with no `..HEAD` so the comparison reaches the working tree; an editor auto-format
    or a stray blank line would otherwise break the demo path's identity gate silently.
    Asserted on parsed integers, never on a formatted string.
    """
    base = branch_point()

    result = git("diff", "--numstat", base, "--", "backend/main.py")
    assert result.returncode == 0, result.stderr

    numstat = parse_numstat(result.stdout)
    assert numstat.get("backend/main.py") == EXPECTED_MAIN_NUMSTAT, (
        f"backend/main.py must gain exactly {EXPECTED_MAIN_NUMSTAT[0]} line(s) and lose "
        f"{EXPECTED_MAIN_NUMSTAT[1]} since {base[:7]} — one import and one include_router call. "
        f"Got {numstat.get('backend/main.py')} from:\n{result.stdout}"
    )


@pytest.mark.usefixtures("git_repo")
def test_test10_diff_names_no_off_limits_path() -> None:
    """Nothing on F4's off-limits list appears in the diff since the branch point.

    Tracked changes only, on purpose: `.venv` and `data/raw` are untracked **symlinks** in this
    worktree and `.claude/features/forecast-api/` is untracked, so a `git status --porcelain`
    scan would trip on all three. `git diff` sees none of them, which is correct.
    """
    base = branch_point()

    result = git("diff", "--name-only", base)
    assert result.returncode == 0, result.stderr

    changed = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    hits = off_limits_hits(changed)

    assert hits == [], (
        f"F4 must not touch {hits} — the diff since {base[:7]} names them.\n"
        f"Full change set:\n" + "\n".join(changed)
    )
