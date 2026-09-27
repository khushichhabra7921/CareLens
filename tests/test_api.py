"""API tests against the fixture database (carelens_test), through the real app."""

import re
import uuid

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

import common
from app.analyses import ANALYSES
from app.main import app

API_KEY = "test-admin-key-0123456789"


@pytest.fixture
def client(test_db, monkeypatch):
    db = common.settings()
    monkeypatch.setenv("POSTGRES_DB", test_db)
    monkeypatch.setenv("DB_HOST", db.db_host)
    monkeypatch.setenv("DB_PORT", str(db.db_port))
    monkeypatch.setenv("APP_DB_PASSWORD", db.app_db_password.get_secret_value())
    monkeypatch.setenv("ADMIN_API_KEY", API_KEY)
    monkeypatch.setenv("REPORTS_RATE_LIMIT", "3")
    with TestClient(app) as c:   # runs startup: fresh pool, cache and rate limiter per test
        yield c


def post_report(client, analysis_id="care-gaps", key=API_KEY):
    headers = {"X-API-Key": key} if key is not None else {}
    return client.post("/api/reports", json={"analysis_id": analysis_id}, headers=headers)


# ------------------------------------------------------------------ health and analyses

def test_health_ok(client):
    assert client.get("/health").json() == {"status": "ok", "database": "ok"}


def test_health_is_503_when_the_schema_is_out_of_date(client, monkeypatch):
    # e.g. a new table was added but scripts/db_setup.py wasn't re-run on this database
    monkeypatch.setattr("app.main.REQUIRED_OBJECTS", ["app.table_that_does_not_exist"])
    response = client.get("/health")
    assert response.status_code == 503
    assert response.json()["database"] == "schema out of date"


def test_lists_all_eight_analyses_with_reference_date(client):
    body = client.get("/api/analyses").json()
    assert body["reference_date"] == "2024-12-02"
    assert [a["id"] for a in body["analyses"]] == [a.id for a in ANALYSES]
    assert all(a["title"] and a["question"] for a in body["analyses"])


@pytest.mark.parametrize("analysis", ANALYSES, ids=lambda a: a.id)
def test_each_analysis_returns_its_tables(client, analysis):
    body = client.get(f"/api/analyses/{analysis.id}").json()
    assert [t["name"] for t in body["tables"]] == list(analysis.views)
    assert body["limitations"]
    for table in body["tables"]:
        assert "sort_order" not in table["columns"]
        assert all(set(row) == set(table["columns"]) for row in table["rows"])


def test_analysis_values_match_the_views(client):
    # Spot check that the API passes numbers through unchanged (see test_analyses.py).
    body = client.get("/api/analyses/care-gaps").json()
    htn = next(r for r in body["tables"][0]["rows"] if r["measure"].startswith("Hypertension"))
    assert (htn["eligible_patients"], htn["patients_with_gap"], htn["gap_pct"]) == (33, 12, 36.4)


@pytest.mark.parametrize("bad_id", ["nope", "care_gaps", "x'; DROP TABLE app.reports; --"])
def test_unknown_analysis_is_404(client, bad_id):
    assert client.get(f"/api/analyses/{bad_id}").status_code == 404


# ------------------------------------------------------------------ reports

def test_report_needs_the_api_key(client):
    assert post_report(client, key=None).status_code == 401
    assert post_report(client, key="wrong-key-wrong-key-wrong").status_code == 401


def test_create_and_fetch_a_template_report(client):
    response = post_report(client)
    assert response.status_code == 201
    record = response.json()
    assert record["source"] == "template"
    assert record["disclaimer"] == "Synthetic data. Not clinical advice."
    assert record["grounding"]["status"] == "not_checked"
    assert record["report"]["findings"]
    fetched = client.get(f"/api/reports/{record['report_id']}")
    assert fetched.status_code == 200 and fetched.json() == record


def test_template_report_only_cites_numbers_from_the_data(client):
    analysis = client.get("/api/analyses/polypharmacy").json()
    data_values = {float(v) for t in analysis["tables"] for r in t["rows"] for v in r.values()
                   if isinstance(v, int | float) and not isinstance(v, bool)}
    data_values |= {float(len(t["rows"])) for t in analysis["tables"]}
    data_values |= {float(t["suppressed_rows"]) for t in analysis["tables"]}
    record = post_report(client, "polypharmacy").json()
    for finding in record["report"]["findings"]:
        assert set(finding["values_cited"]) <= data_values, finding


def test_unknown_report_is_404_and_bad_id_is_422(client):
    assert client.get(f"/api/reports/{uuid.uuid4()}").status_code == 404
    assert client.get("/api/reports/not-a-uuid").status_code == 422


def test_report_for_unknown_analysis_is_404(client):
    assert post_report(client, "unknown-analysis").status_code == 404


def test_rate_limit_counts_every_attempt_including_bad_keys(client):
    # Limit is 3 per window in this test. Failed key guesses count too.
    assert post_report(client, key="wrong-key-wrong-key-wrong").status_code == 401
    assert post_report(client).status_code == 201
    assert post_report(client).status_code == 201
    blocked = post_report(client)
    assert blocked.status_code == 429
    assert int(blocked.headers["Retry-After"]) > 0


# ------------------------------------------------------------------ browser security

def test_dashboard_is_served_with_a_strict_content_security_policy(client):
    page = client.get("/")
    assert page.status_code == 200
    assert "Synthetic data. Not clinical advice." in page.text
    csp = page.headers["Content-Security-Policy"]
    assert "script-src 'self'" in csp and "frame-ancestors 'none'" in csp
    assert page.headers["X-Content-Type-Options"] == "nosniff"


# ------------------------------------------------------------------ no row-level data, anywhere

def test_no_endpoint_returns_row_level_patient_data(client, loader_conn):
    """Call EVERY API route and check that no patient identifier or patient-level id from the
    fixture appears in any response. Fails if a new route is added without being covered here."""
    covered = {"/health", "/api/analyses", "/api/analyses/{analysis_id}", "/api/reports",
               "/api/reports/{report_id}", "/"}
    routes = {r.path for r in app.routes if isinstance(r, APIRoute)}
    assert routes == covered, f"update this test for new routes: {routes - covered}"

    # Everything that would identify a patient or a single visit.
    secrets = set()
    for row in loader_conn.execute(
            "SELECT patient_id::text, first_name, last_name, ssn, address, birth_date::text "
            "FROM phi.patient_identifiers"):
        secrets.update(v for v in row if v)
    secrets.update(r[0] for r in loader_conn.execute(
        "SELECT encounter_id::text FROM analytics.encounters"))
    # Short or common strings (e.g. a surname like "Lee") could match by accident in
    # ordinary words; names are checked as whole words below, ids and SSNs as substrings.
    names = {s for s in secrets if s.isalpha()}
    exact = secrets - names

    report = post_report(client).json()
    responses = [client.get("/health"), client.get("/api/analyses"), client.get("/"),
                 client.get(f"/api/reports/{report['report_id']}")]
    responses += [client.get(f"/api/analyses/{a.id}") for a in ANALYSES]
    for response in responses:
        text = response.text
        leaked = [s for s in exact if s in text]
        leaked += [n for n in names if re.search(rf"\b{re.escape(n)}\b", text)]
        assert not leaked, f"{response.url} leaked {leaked[:5]}"
    # A report id is a UUID, but not a patient's: make sure no fixture UUID slipped in.
    assert report["report_id"] not in secrets
