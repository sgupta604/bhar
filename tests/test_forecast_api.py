"""Endpoint behaviour for `backend.forecast_api`: the three read-only forecast routes.

Covers /api/forecast, /api/forecast/skill and /api/forecast/history. The history route
is exercised across all four of its branches, including the one that matters most: with
bytes on disk but no FORECAST-SPEC §10 validator available it must still 503, because an
unvalidated history payload is never served.

Written test-first (F4 Stream 1). Until Stream 2 lands `backend/forecast_api.py` this
module fails at *import*, which is the point — a TDD scaffold that collects green is a
scaffold that is testing nothing.

Every negative case asserts on the **message text**, not merely on the status code,
following `tests/test_results_contract.py`: a 503 raised for the wrong reason is worse
than no 503, because it still renders as "the API is down" while hiding the real fault.

Two hazards this file is built to avoid:

1. `data/forecast.json` **exists in this worktree** (gitignored, absent on a fresh clone).
   A test that forgets to repoint `backend.forecast_api.FORECAST_PATH` would pass here and
   fail on a fresh clone. The autouse `isolated_paths` fixture points **both** path
   constants at a directory that does not exist, so binding the real file takes a
   deliberate act, not an oversight.
2. Wall-clock instants. `PINNED` is a fixed aware-UTC datetime and `init_time` is derived
   from it via `forecast.make_fixture.default_init_time` — the builder computes staleness
   from the *pair*, so a hand-rolled `init_time` silently builds a document nobody meant.
   No wall-clock call appears anywhere in this file.

FORECAST-SPEC §9's worked example is defective: its `blend_f` contradicts its own rule 6
(F3 SUMMARY §1). No number from that example is used here as an expected value.

Hermetic: no network, no server process, no writes outside `tmp_path`.
"""

from __future__ import annotations

import copy
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import backend.main
from backend import forecast_api
from forecast import contract as forecast_contract
from forecast.contract import ContractError, write_atomic
from forecast.make_fixture import build_fixture_document, default_init_time

#: A fixed aware-UTC instant. Never a wall clock — see the module docstring.
PINNED = datetime(2026, 9, 4, 4, 20, 0, tzinfo=timezone.utc)

FORECAST_URL = "/api/forecast"
SKILL_URL = "/api/forecast/skill"
HISTORY_URL = "/api/forecast/history"

#: The row index used for the two contract-violation mutations. The fixture's `forecast`
#: list omits the two gap leads (21 h, 48 h), so index 7 is a real, mid-document row and
#: its JSON path is what the 503 detail must name.
VIOLATION_ROW = 7


# --------------------------------------------------------------------------- fixtures


@pytest.fixture(scope="module")
def client() -> TestClient:
    """A client over the **real shipped app object**, not a rebuilt one.

    Every assertion here is therefore about the thing `run.sh` serves.
    """
    return TestClient(backend.main.app)


@pytest.fixture(scope="module")
def forecast_doc() -> dict:
    """A complete, valid FORECAST-SPEC §9 document from pinned instants.

    Deliberately hostile: two declared gaps, extrapolated rows, and a real skill *loss*
    at 24 h. Treat as read-only; take a `copy.deepcopy` before mutating.
    """
    return build_fixture_document(
        generated_at=PINNED,
        init_time=default_init_time(PINNED),
    )


@pytest.fixture()
def doc(forecast_doc: dict) -> dict:
    """A throwaway deep copy of the valid document, safe to mutate."""
    return copy.deepcopy(forecast_doc)


@pytest.fixture(autouse=True)
def isolated_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point **both** path constants at a directory that does not exist.

    Autouse, so this is the default for every test in the file: the only way to reach a
    real file on disk is to repoint a constant explicitly. Nothing is created here — the
    missing directory is the whole point.
    """
    nowhere = tmp_path / "no-such-data-dir"
    monkeypatch.setattr(forecast_api, "FORECAST_PATH", nowhere / "forecast.json")
    monkeypatch.setattr(forecast_api, "HISTORY_PATH", nowhere / "forecast_history.json")
    return nowhere


@pytest.fixture()
def forecast_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, isolated_paths: Path) -> Path:
    """A writable `data/forecast.json` under `tmp_path`, bound to `FORECAST_PATH`.

    The file itself is *not* written — cases that need invalid bytes on disk write them
    themselves. Depends on `isolated_paths` so the override order is explicit rather than
    a matter of autouse-fixture luck.
    """
    path = tmp_path / "data" / "forecast.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(forecast_api, "FORECAST_PATH", path)
    return path


@pytest.fixture()
def written_forecast(forecast_path: Path, forecast_doc: dict) -> Path:
    """The valid document on disk at `FORECAST_PATH`, written through `write_atomic`.

    `write_atomic` validates before it writes, so this fixture existing at all is itself
    proof the document is contract-clean.
    """
    write_atomic(forecast_doc, forecast_path)
    return forecast_path


# --------------------------------------------------------------------------- helpers


def write_unvalidated(path: Path, document: dict) -> None:
    """Write a document *without* validating it.

    `write_atomic` refuses to write an invalid document — correctly — so the contract
    violation cases have to go around it to get bad bytes onto disk.
    """
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")


def detail_of(response) -> str:
    """The `detail` string from a FastAPI error body, asserting the body has that shape."""
    body = response.json()
    assert isinstance(body, dict), f"error body must be an object, got {type(body).__name__}"
    assert "detail" in body, f"error body must carry a `detail` reason, got keys {sorted(body)}"
    return body["detail"]


def violate_blend_rule(document: dict) -> None:
    """Break FORECAST-SPEC §9 rule 6: `blend_f` no longer equals sum(weight * member)."""
    document["forecast"][VIOLATION_ROW]["blend_f"] += 1.0


def inject_banned_key(document: dict) -> None:
    """Inject a FORECAST-SPEC §6.2 banned field name onto a forecast row."""
    document["forecast"][VIOLATION_ROW]["confidence_pct"] = 90


#: The two contract violations, as (id, mutator, expected JSON path fragment).
CONTRACT_VIOLATIONS = [
    pytest.param(
        violate_blend_rule,
        f"forecast[{VIOLATION_ROW}].blend_f",
        id="blend_f-breaks-rule-6",
    ),
    pytest.param(
        inject_banned_key,
        f"forecast[{VIOLATION_ROW}].confidence_pct",
        id="banned-confidence_pct-key",
    ),
]


# --------------------------------------------------------------------------- fixture guard


def test_the_default_paths_never_bind_the_repository_data_directory(isolated_paths: Path) -> None:
    """The autouse guard must actually redirect both constants away from the real files.

    `data/forecast.json` exists in this worktree. Without this guard a test that forgot to
    monkeypatch would pass here and fail on a fresh clone, where the file is absent.
    """
    repo_data = Path(backend.main.__file__).resolve().parent.parent / "data"

    for name in ("FORECAST_PATH", "HISTORY_PATH"):
        bound = Path(getattr(forecast_api, name))
        assert not bound.exists(), f"{name} must point at a path that does not exist"
        assert repo_data not in bound.parents, f"{name} must not live under the repo's data/"
        assert bound.parent == isolated_paths


# --------------------------------------------------------------------------- TEST-1


def test_forecast_serves_the_document_on_disk_whole(
    client: TestClient, written_forecast: Path
) -> None:
    """TEST-1: a valid document on disk is returned byte-for-byte in meaning."""
    response = client.get(FORECAST_URL)

    assert response.status_code == 200
    payload = response.json()

    on_disk = json.loads(written_forecast.read_text(encoding="utf-8"))
    assert payload == on_disk, "the endpoint must serve the file, not a reshaped view of it"

    assert set(payload) == {"meta", "forecast", "gaps", "skill"}
    assert payload["forecast"], "no rows is the empty-but-well-formed failure mode"
    assert payload["gaps"], "the fixture declares two gaps; a response that drops them is wrong"

    # A real JSON boolean, not the string "True" and not 1 -- the page branches on it.
    assert payload["meta"]["is_synthetic"] is True
    assert '"is_synthetic":true' in response.text.replace(" ", "")


# --------------------------------------------------------------------------- TEST-2..4


@pytest.mark.parametrize("url", [FORECAST_URL, SKILL_URL])
def test_missing_forecast_file_is_a_503_naming_the_file_and_the_refresh_command(
    client: TestClient, url: str
) -> None:
    """TEST-2 / TEST-5: no file is a loud 503, never an empty-but-well-formed payload."""
    response = client.get(url)

    assert response.status_code == 503
    detail = detail_of(response)
    assert "data/forecast.json" in detail, "the reason must name the file the operator has to fix"
    assert "forecast.refresh" in detail, "the reason must name the command that rebuilds it"

    assert "meta" not in response.json()
    assert "forecast" not in response.json()


@pytest.mark.parametrize("url", [FORECAST_URL, SKILL_URL])
def test_malformed_json_is_a_503_that_says_it_is_not_valid_json(
    client: TestClient, forecast_path: Path, url: str
) -> None:
    """TEST-3 / TEST-5: truncated bytes on disk surface as a parse failure, not a crash."""
    forecast_path.write_text("{not json", encoding="utf-8")

    response = client.get(url)

    assert response.status_code == 503
    detail = detail_of(response)
    assert "data/forecast.json" in detail
    assert "not valid JSON" in detail, f"the reason must say the bytes do not parse, got: {detail}"


@pytest.mark.parametrize(("mutate", "json_path"), CONTRACT_VIOLATIONS)
@pytest.mark.parametrize("url", [FORECAST_URL, SKILL_URL])
def test_a_contract_violation_is_a_503_naming_the_offending_json_path(
    client: TestClient, forecast_path: Path, doc: dict, url: str, mutate, json_path: str
) -> None:
    """TEST-4 / TEST-5: the 503 has to be actionable, so it carries the JSON path.

    `{exc}` must reach the response untruncated — the path is the whole diagnostic value.
    """
    mutate(doc)
    write_unvalidated(forecast_path, doc)

    response = client.get(url)

    assert response.status_code == 503
    detail = detail_of(response)
    assert "data/forecast.json" in detail
    assert json_path in detail, f"the reason must name the offending row, got: {detail}"


def test_the_blend_violation_reason_cites_rule_6(
    client: TestClient, forecast_path: Path, doc: dict
) -> None:
    """The rule-6 message must survive to the client, not be flattened to "invalid"."""
    violate_blend_rule(doc)
    write_unvalidated(forecast_path, doc)

    detail = detail_of(client.get(FORECAST_URL))
    assert "rule 6" in detail


def test_the_banned_key_reason_cites_the_ban_and_not_a_typo(
    client: TestClient, forecast_path: Path, doc: dict
) -> None:
    """A §6.2 name must be rejected *as banned*, not as an "unexpected key" typo."""
    inject_banned_key(doc)
    write_unvalidated(forecast_path, doc)

    detail = detail_of(client.get(FORECAST_URL))
    assert "6.2" in detail


# --------------------------------------------------------------------------- TEST-5


def test_skill_returns_the_skill_block_verbatim(
    client: TestClient, written_forecast: Path, forecast_doc: dict
) -> None:
    """TEST-5: /api/forecast/skill is `doc["skill"]` and nothing else."""
    response = client.get(SKILL_URL)

    assert response.status_code == 200
    payload = response.json()

    assert payload == forecast_doc["skill"]
    assert set(payload) == {"basis", "window", "note", "by_lead"}

    assert [entry["lead_h"] for entry in payload["by_lead"]] == [6, 12, 24]

    # The whole document must not leak through this endpoint.
    for leaked in ("meta", "forecast", "gaps"):
        assert leaked not in payload, f"/api/forecast/skill must not carry `{leaked}`"


# --------------------------------------------------------------------------- TEST-6

# History-specific machinery lives with its tests: nothing above this line needs it, and
# keeping it here makes the four branches readable as one block.
#
# `data/forecast_history.json` is F6's deliverable and must not exist in this checkout.
# Every history byte written by this suite lives under `tmp_path` and dies with the test;
# nothing here fabricates, stubs or commits a real history payload.

#: A stand-in FORECAST-SPEC §10 history document. F6 owns the real shape. F4 only has to
#: prove the endpoint hands back whatever the validator returned, whole and unreshaped,
#: so this is deliberately minimal and obviously not the finished thing.
HISTORY_STANDIN = {
    "meta": {"generated_at": "2026-09-04T04:20:00Z", "window_days": 2},
    "days": [
        {"date": "2026-09-02", "observed_f": 71.2, "blend_f": 70.8},
        {"date": "2026-09-03", "observed_f": 68.9, "blend_f": 69.6},
    ],
}

#: What sits on disk in the branches that get past the file check. It is deliberately
#: *not* what any test expects back: the handler must serve the validator's return value,
#: never a second, unvalidated read of the bytes.
HISTORY_BYTES_ON_DISK = {"unvalidated": True}


class RecordingValidator:
    """A stand-in for F6's `forecast.contract.load_and_validate_history(path) -> dict`.

    Records the path it was handed, so a test can prove the validator actually ran — and,
    in the missing-file case, prove that it did *not*.
    """

    def __init__(self, *, returns: dict | None = None, raises: ContractError | None = None) -> None:
        self.calls: list[Path] = []
        self._returns = returns
        self._raises = raises

    def __call__(self, path) -> dict:
        self.calls.append(Path(path))
        if self._raises is not None:
            raise self._raises
        return self._returns if self._returns is not None else {}


@pytest.fixture()
def history_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, isolated_paths: Path) -> Path:
    """A writable `data/forecast_history.json` under `tmp_path`, bound to `HISTORY_PATH`.

    The file itself is not written — the missing-file branch needs it absent. Depends on
    `isolated_paths` so the override order is explicit rather than autouse-fixture luck.
    """
    path = tmp_path / "data" / "forecast_history.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(forecast_api, "HISTORY_PATH", path)
    return path


@pytest.fixture()
def written_history(history_path: Path) -> Path:
    """Bytes on disk at `HISTORY_PATH`, putting the missing-file branch behind us."""
    write_unvalidated(history_path, HISTORY_BYTES_ON_DISK)
    return history_path


def test_history_without_a_payload_is_a_503_naming_the_file(client: TestClient) -> None:
    """TEST-6(a): the payload is absent from this checkout, and the 503 says so."""
    response = client.get(HISTORY_URL)

    assert response.status_code == 503
    detail = detail_of(response)
    assert "data/forecast_history.json" in detail, "the reason must name the missing file"

    assert "days" not in response.json(), "a 503 must not also carry an empty history body"


def test_history_reports_the_missing_file_before_it_reaches_the_validator(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """TEST-6(a), ordering: a working validator must not mask the real problem.

    With the §10 validator available but no file on disk, the 503 has to name the file —
    not blame the validator, and not hand it a path that is not there.
    """
    validator = RecordingValidator(returns=copy.deepcopy(HISTORY_STANDIN))
    monkeypatch.setattr(
        forecast_contract, "load_and_validate_history", validator, raising=False
    )

    response = client.get(HISTORY_URL)

    assert response.status_code == 503
    assert "data/forecast_history.json" in detail_of(response)
    assert validator.calls == [], "a missing file must be reported, not passed to the validator"

    assert "days" not in response.json()


def test_history_without_a_section_10_validator_is_a_503_and_is_never_served(
    client: TestClient, written_history: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """TEST-6(b): bytes on disk are not enough — unvalidated history is never served.

    The absence of `load_and_validate_history` is asserted *by deletion* rather than
    assumed. F6 has not landed, so the attribute genuinely does not exist yet; deleting it
    anyway makes this branch honest and order-independent, instead of one leaked patch
    from an earlier test away from passing for the wrong reason.
    """
    monkeypatch.delattr(forecast_contract, "load_and_validate_history", raising=False)

    assert written_history.exists(), "this branch is only meaningful with the file present"

    response = client.get(HISTORY_URL)

    assert response.status_code == 503
    detail = detail_of(response)
    assert "data/forecast_history.json" in detail
    assert "no FORECAST-SPEC §10 validator is available" in detail, (
        f"the reason must name what is missing, got: {detail}"
    )
    assert "never served" in detail, (
        f"the reason must say an unvalidated payload is never served, got: {detail}"
    )

    assert "days" not in response.json(), "no validator ran, so no history may be served"
    assert "unvalidated" not in response.json(), "the on-disk bytes must not leak through"


def test_history_contract_violation_is_a_503_naming_the_offending_json_path(
    client: TestClient, written_history: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """TEST-6(c): the validator's own message, JSON path and all, reaches the client whole.

    The path is the entire diagnostic value of the message, so `{exc}` must not be
    truncated, summarised or replaced with a generic "invalid document".
    """
    json_path = "days[3].observed_f"
    validator = RecordingValidator(
        raises=ContractError(f"{json_path}: expected a number, got str")
    )
    monkeypatch.setattr(
        forecast_contract, "load_and_validate_history", validator, raising=False
    )

    response = client.get(HISTORY_URL)

    assert response.status_code == 503
    detail = detail_of(response)
    assert "data/forecast_history.json" in detail
    assert json_path in detail, f"the reason must name the offending value, got: {detail}"
    assert "expected a number, got str" in detail, f"`{{exc}}` must arrive whole, got: {detail}"

    assert validator.calls == [written_history], "the validator must have been handed HISTORY_PATH"
    assert "days" not in response.json(), "a rejected document must not be served in part"


def test_history_with_a_validator_serves_the_validated_document_whole(
    client: TestClient, written_history: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """TEST-6(d): once F6 lands its validator, the endpoint serves what that validator returns.

    Asserted against the validator's return value rather than the file's bytes — the two
    are deliberately different here, so a handler that re-read the file, or served it
    without validating, would fail instead of quietly agreeing.
    """
    validator = RecordingValidator(returns=copy.deepcopy(HISTORY_STANDIN))
    monkeypatch.setattr(
        forecast_contract, "load_and_validate_history", validator, raising=False
    )

    response = client.get(HISTORY_URL)

    assert response.status_code == 200
    payload = response.json()

    assert payload == HISTORY_STANDIN, "the document must be served whole, not reshaped"
    assert payload["days"] == HISTORY_STANDIN["days"]
    assert "unvalidated" not in payload, "the response must be the validator's output, not the file"

    assert validator.calls == [written_history], "a 200 is only legitimate if the validator ran"


# --------------------------------------------------------------------------- TEST-11


#: A demo-plausible frontend origin, distinct from the API's own. The API is served on
#: :8000 and the page on a static server, so **every** browser request to these routes is
#: cross-origin. `backend/main.py` allows `http://(localhost|127.0.0.1):<port>`.
DEMO_ORIGIN = "http://localhost:5184"


def test_cors_header_is_present_on_a_served_forecast(
    client: TestClient, written_forecast: Path
) -> None:
    """TEST-11: the 200 path must carry `access-control-allow-origin`.

    The page is served from a different origin than the API, so without this header the
    browser discards a perfectly good body: full chrome, zero data, and a console error as
    the only symptom. CORS is configured in `backend/main.py` and F4 changes none of it —
    this test exists to make a later "harmless" middleware reshuffle fail loudly here.
    """
    response = client.get(FORECAST_URL, headers={"Origin": DEMO_ORIGIN})

    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == DEMO_ORIGIN, (
        "a cross-origin 200 the browser will not hand to the page is a blank page"
    )


@pytest.mark.parametrize("url", [FORECAST_URL, SKILL_URL, HISTORY_URL])
def test_cors_header_is_present_on_a_503_too(client: TestClient, url: str) -> None:
    """TEST-11: the **error** path needs the header just as much as the success path.

    A 503 whose `detail` names the missing file is the whole diagnostic. If CORS stops
    stamping error responses — the failure mode when a router is mounted before the
    middleware rather than after — the page loses the reason and shows a generic network
    error instead, sending the operator to debug the wrong thing.
    """
    response = client.get(url, headers={"Origin": DEMO_ORIGIN})

    assert response.status_code == 503
    assert response.headers.get("access-control-allow-origin") == DEMO_ORIGIN, (
        "a 503 the browser withholds hides the one message that explains the failure"
    )
    assert detail_of(response), "the reason must survive to the client alongside the header"


# --------------------------------------------------------------------------- TEST-12


@pytest.mark.parametrize("url", [FORECAST_URL, SKILL_URL, HISTORY_URL])
def test_post_to_a_forecast_route_is_405(client: TestClient, url: str) -> None:
    """TEST-12: these routes are read-only, and nothing here may accept a write.

    FastAPI returns 405 for a GET-only route with no code at all, so this asserts a
    property rather than an implementation — the day someone adds a "harmless" refetch
    POST to trigger a live fetch from the page, this fails. Fetching is offline, in
    `forecast.refresh`, and only there.
    """
    response = client.post(url, json={"forecast": []})

    assert response.status_code == 405, (
        f"{url} must not accept a write; a request path that fetches is the failure "
        "FORECAST-SPEC §6 forbids"
    )


def test_openapi_advertises_only_get_for_the_three_forecast_routes(client: TestClient) -> None:
    """TEST-12: the published schema must not advertise a write either.

    The 405 above proves the server refuses one; this proves nothing *offers* one. Both
    matter: `/openapi.json` is what a reader (and the demo's identity check) consults to
    learn what this API does.
    """
    schema = client.get("/openapi.json").json()
    paths = schema["paths"]

    for url in (FORECAST_URL, SKILL_URL, HISTORY_URL):
        assert url in paths, f"{url} must be published in the schema"
        assert set(paths[url]) == {"get"}, (
            f"{url} must advertise only `get`, got {sorted(paths[url])}"
        )


# --------------------------------------------------------------------------- TEST-13


def test_a_replaced_file_is_revalidated_on_the_very_next_request(
    client: TestClient, forecast_path: Path, doc: dict
) -> None:
    """TEST-13: "picked up without a restart" means re-read *and* re-validated per request.

    One client, one path, no restart and no second fixture: the only thing that changes
    between the two requests is the bytes on disk. The first request proves the document
    was servable; the second proves the handler read it again rather than serving a cached
    parse from the first.

    The 503 has to name the offending JSON path. A bare status-code assertion would pass
    just as well if the route had broken for an unrelated reason — naming the path is what
    proves the *validator* ran on the *new* bytes.
    """
    write_atomic(doc, forecast_path)
    assert client.get(FORECAST_URL).status_code == 200, "the fixture must start out servable"

    # Same path, mutated in place. `write_atomic` would refuse these bytes, correctly.
    violate_blend_rule(doc)
    write_unvalidated(forecast_path, doc)

    second = client.get(FORECAST_URL)

    assert second.status_code == 503, (
        "a cached parse would still return 200 here; the file must be re-read every request"
    )
    detail = detail_of(second)
    assert f"forecast[{VIOLATION_ROW}].blend_f" in detail, (
        f"the reason must name the newly-broken row, got: {detail}"
    )
    assert "rule 6" in detail
    assert "forecast" not in second.json(), "a stale-but-valid body must not be served instead"


# --------------------------------------------------------------------------- TEST-14


def test_a_fixture_file_beside_a_missing_forecast_is_not_served(
    client: TestClient, forecast_path: Path, forecast_doc: dict
) -> None:
    """TEST-14: FR5 — there is no fallback to a synthetic document, ever.

    A complete, contract-valid `data/forecast.fixture.json` sits in the same directory as
    the absent `data/forecast.json`, which is exactly the shape a well-meaning "serve the
    fixture so the demo doesn't break" fallback would key off. The endpoint must still
    503: a page that looks fine and is wrong is the failure class SPEC §10 exists to
    prevent, and a demo showing a fabricated forecast is worse than a demo showing an
    error.
    """
    fallback = forecast_path.parent / "forecast.fixture.json"
    write_atomic(forecast_doc, fallback)

    assert fallback.exists(), "the tempting fallback must actually be on disk"
    assert not forecast_path.exists(), "the real cache must be absent for this to mean anything"

    response = client.get(FORECAST_URL)

    assert response.status_code == 503, "a valid fixture next door is not a licence to serve it"

    body = response.json()
    assert "meta" not in body, "no synthetic document may reach the page"
    assert "forecast" not in body

    detail = detail_of(response)
    assert "data/forecast.json" in detail, "the 503 must be the missing-file reason"
    assert "forecast.refresh" in detail, "and must name the command that builds the real one"


# --------------------------------------------------------------------------- no-real-file proof


@pytest.mark.parametrize("url", [FORECAST_URL, SKILL_URL, HISTORY_URL])
def test_every_endpoint_503s_when_both_paths_point_at_nothing(
    client: TestClient, isolated_paths: Path, url: str
) -> None:
    """The mechanical proof that no test in this file leans on the repository's real data.

    `data/forecast.json` **exists in this worktree** — gitignored, built by F3's refresh —
    and is **absent on a fresh clone**. A test that forgot to repoint `FORECAST_PATH`
    would pass here and fail in CI, and the symptom would be a red build nobody can
    reproduce locally. With the autouse guard's nonexistent directory bound to both
    constants, every endpoint must 503; if any returns 200, something is reading a file
    this suite never wrote.
    """
    assert not isolated_paths.exists(), "the autouse guard must bind a directory that is not there"

    response = client.get(url)

    assert response.status_code == 503, (
        f"{url} returned {response.status_code} with no file on disk — it is reading "
        "something outside tmp_path"
    )
    assert detail_of(response), "each 503 must still explain itself"
