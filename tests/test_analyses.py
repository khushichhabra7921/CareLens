"""The 8 analyses against the fixture. Every expected number is worked out by hand from the
cohorts in tests/fixtures/build_fixture.py (the comments show the arithmetic).

Reference date = 2024-12-02; "last 12 months" = after 2023-12-02 up to 2024-12-02.
Queries run as app_readonly, exactly like the web app will.
"""

from decimal import Decimal

import pytest
from psycopg import sql
from psycopg.rows import dict_row

import refresh_views

VIEWS = [a.view for a in refresh_views.list_analyses()]


def rows(app_conn, view: str) -> list[dict]:
    query = sql.SQL("SELECT * FROM {} ORDER BY sort_order").format(
        sql.Identifier("reporting", view))
    with app_conn.cursor(row_factory=dict_row) as cur:
        return cur.execute(query).fetchall()


def find(result: list[dict], **match) -> dict:
    hits = [r for r in result if all(r[k] == v for k, v in match.items())]
    assert len(hits) == 1, f"expected one row for {match}, found {len(hits)}"
    return hits[0]


# ------------------------------------------------------------------ rules for every analysis

def test_there_are_ten_views_for_eight_analyses():
    assert len(VIEWS) == 10


@pytest.mark.parametrize("view", VIEWS)
def test_no_count_between_1_and_10_is_ever_shown(app_conn, view):
    # The core small-cell rule, checked on every integer column of every view.
    skip = {"sort_order", "period", "cost_rank"}   # row labels, not counts
    for row in rows(app_conn, view):
        for col, value in row.items():
            if col not in skip and isinstance(value, int) and not isinstance(value, bool):
                assert not 1 <= value <= 10, f"{view}.{col} shows {value}"


@pytest.mark.parametrize("view", VIEWS)
def test_every_row_has_a_suppressed_flag(app_conn, view):
    assert all(isinstance(r["suppressed"], bool) for r in rows(app_conn, view))


def test_reporting_views_have_no_patient_level_columns(loader_conn):
    # No uuid (patient/encounter id) or identifier-like column can appear in an aggregate view.
    cols = loader_conn.execute("""
        SELECT c.relname, a.attname, format_type(a.atttypid, a.atttypmod)
        FROM pg_attribute a JOIN pg_class c ON c.oid = a.attrelid
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'reporting' AND a.attnum > 0 AND NOT a.attisdropped""").fetchall()
    assert cols, "no reporting views found"
    assert not [c for c in cols if c[2] == "uuid" or c[1].endswith("_id")]


# ------------------------------------------------------------------ 1. population overview

def test_population_overview(app_conn):
    r = rows(app_conn, "population_overview")
    # 8 hand-written patients + cohorts C1 20 + C2 12 + C3 12 + C4 11 = 63
    assert find(r, dimension="gender", category="F")["patients"] == 28   # 4 + 12 (C1) + 12 (C3)
    assert find(r, dimension="gender", category="M")["patients"] == 35   # 4 + 8 + 12 + 11
    assert find(r, dimension="age_band", category="65-74")["patients"] == 22  # p01, p07 + C1
    assert find(r, dimension="ethnicity", category="hispanic")["patients"] == 14  # p02, p08 + C3
    assert find(r, dimension="vital_status", category="living")["patients"] == 62
    deceased = find(r, dimension="vital_status", category="deceased")      # only p04 -> 1
    assert deceased == {**deceased, "patients": None, "suppressed": True}
    assert find(r, dimension="age_band", category="90+")["suppressed"] is True  # p03 only


# ------------------------------------------------------------------ 2. chronic disease

def test_chronic_disease_prevalence(app_conn):
    r = rows(app_conn, "chronic_disease_prevalence")
    # 65-74 women: p01 + 12 C1 = 13 living; the 12 C1 women have diabetes -> 12/13 = 92.3%
    cell = find(r, condition="diabetes", age_band="65-74", gender="F")
    assert (cell["patients_with_condition"], cell["living_patients"]) == (12, 13)
    assert cell["prevalence_pct"] == Decimal("92.3")
    # 65-74 men: p07 + 8 C1 = 9 living -> the whole cell is suppressed
    assert find(r, condition="diabetes", age_band="65-74", gender="M")["suppressed"] is True
    # Hypertension in 45-64 men: all 12 of C2 -> 100%
    assert find(r, condition="hypertension", age_band="45-64", gender="M")["prevalence_pct"] == 100
    # Heart failure in 18-44 women: C3 12 of (p06 + 12) = 13 -> 92.3%
    assert find(r, condition="heart_failure", age_band="18-44", gender="F"
                )["prevalence_pct"] == Decimal("92.3")
    # p06's asthma resolved in 2015, so it doesn't count: 0 of 13 (0 is allowed to be shown)
    asthma = find(r, condition="asthma", age_band="18-44", gender="F")
    assert (asthma["patients_with_condition"], asthma["prevalence_pct"]) == (0, 0)


# ------------------------------------------------------------------ 3. readmissions

def test_readmissions(app_conn):
    r = rows(app_conn, "readmissions_30day")
    # Aetna = C3: 12 first stays + 11 second stays = 23 index stays (the 2024-11-22 discharge
    # is within 30 days of the reference date, so excluded). 11 first stays were followed by a
    # readmission 16 days later -> 11/23 = 47.8%.
    aetna = find(r, dimension="payer", category="Aetna")
    assert (aetna["index_stays"], aetna["readmissions"]) == (23, 11)
    assert aetna["readmission_rate_pct"] == Decimal("47.8")
    # Medicare = p01: 2 stays, 1 readmission -> suppressed
    assert find(r, dimension="payer", category="Medicare")["suppressed"] is True
    # Overall would be 25 stays / 12 readmissions, but then Medicare's hidden 2 and 1 could be
    # recovered by subtraction (25 - 23, 12 - 11), so the overall row is suppressed too.
    overall = find(r, dimension="overall")
    assert (overall["index_stays"], overall["readmissions"], overall["suppressed"]) == (
        None, None, True)
    assert find(r, dimension="primary_reason",
                category="Chronic congestive heart failure (disorder)")["index_stays"] == 23


# ------------------------------------------------------------------ 4. ED utilization

def test_ed_visits_per_1000(app_conn):
    r = rows(app_conn, "ed_visits_per_1000")
    latest = find(r, period=1)
    # 44 (C4: 11 x 4) + p02 + p08 = 46 visits; 62 living patients had an encounter this year
    # (all except p04). 46 / 62 x 1000 = 741.9
    assert (latest["ed_visits"], latest["active_patients"]) == (46, 62)
    assert latest["visits_per_1000"] == Decimal("741.9")
    # Year before: only p04 and one C1 patient were seen (2 people) -> suppressed
    assert find(r, period=2)["suppressed"] is True
    # Nobody at all in period 3 -> 0 visits, 0 patients, no rate (0 is not suppressed)
    p3 = find(r, period=3)
    assert (p3["ed_visits"], p3["active_patients"], p3["visits_per_1000"],
            p3["suppressed"]) == (0, 0, None, False)


def test_ed_frequent_users(app_conn):
    (row,) = rows(app_conn, "ed_frequent_users")
    # ED users = C4 (11) + p02 + p08 = 13; frequent (4+) = 11 -> 84.6%
    # Visits: 46 in total, 44 by frequent users -> 95.7%
    assert (row["ed_users"], row["frequent_users"], row["frequent_user_pct"]) == (
        13, 11, Decimal("84.6"))
    assert (row["ed_visits"], row["frequent_user_visits"], row["frequent_user_visit_pct"]) == (
        46, 44, Decimal("95.7"))


# ------------------------------------------------------------------ 5. cost and coverage

def test_cost_by_class_and_payer(app_conn):
    r = rows(app_conn, "cost_by_class_payer")
    # Emergency x Aetna: C4 44 visits at $1,000 (payer $800) + p08 at $1,200 ($900)
    ed = find(r, encounter_class="emergency", payer="Aetna")
    assert ed["encounters"] == 45
    assert ed["total_claim_cost"] == Decimal("45200.00")      # 44,000 + 1,200
    assert ed["payer_coverage"] == Decimal("36100.00")        # 35,200 + 900
    assert ed["patient_out_of_pocket"] == Decimal("9100.00")  # 45,200 - 36,100
    assert ed["coverage_pct"] == Decimal("79.9")              # 36,100 / 45,200
    # Wellness x Medicare: p01 x2, p03, 20 C1 visits = 23 at $100 ($80 covered)
    well = find(r, encounter_class="wellness", payer="Medicare")
    assert (well["encounters"], well["total_claim_cost"]) == (23, Decimal("2300.00"))
    # Emergency x NO_INSURANCE: only p02's visit -> the money is hidden too
    uninsured = find(r, encounter_class="emergency", payer="NO_INSURANCE")
    assert uninsured["total_claim_cost"] is None and uninsured["suppressed"] is True


def test_top_conditions_by_cost(app_conn):
    (row,) = rows(app_conn, "top_conditions_by_cost")
    # Only heart failure has a diagnosis-coded reason with 11+ patients: C3's 24 stays
    # (12 + 11 + 1, all in the last 12 months) x $10,000
    assert (row["condition"], row["encounters"], row["patients"]) == (
        "Chronic congestive heart failure (disorder)", 24, 12)
    assert row["total_claim_cost"] == Decimal("240000.00")


# ------------------------------------------------------------------ 6. care gaps

def test_care_gaps(app_conn):
    r = rows(app_conn, "care_gaps")
    # Diabetes: the 20 C1 patients; 14 had an HbA1c -> 6 gaps -> gap count suppressed
    dm = find(r, measure="Diabetes without HbA1c test")
    assert (dm["eligible_patients"], dm["patients_with_gap"], dm["suppressed"]) == (
        20, None, True)
    # Hypertension: p01 + 20 C1 + 12 C2 = 33 (p04 is deceased); only C2 lacks a BP reading
    # -> 12/33 = 36.4%
    htn = find(r, measure="Hypertension without blood pressure reading")
    assert (htn["eligible_patients"], htn["patients_with_gap"]) == (33, 12)
    assert htn["gap_pct"] == Decimal("36.4")


# ------------------------------------------------------------------ 7. polypharmacy

def test_polypharmacy(app_conn):
    r = rows(app_conn, "polypharmacy")
    # 65-74: p01, p07 + 20 C1 = 22 living. 11 C1 patients take 5 active medications.
    # (C1 #11's four medications stopped before the reference date, so they don't count.)
    band = find(r, age_band="65-74")
    assert (band["eligible_patients"], band["patients_with_polypharmacy"]) == (22, 11)
    assert band["polypharmacy_pct"] == Decimal("50.0")
    # 90+: just p03 (1 patient) -> suppressed. So the 65+ total of 23 would reveal it
    # (23 - 22 = 1): the total's eligible count is hidden, its 11 (nothing hidden) is shown.
    assert find(r, age_band="90+")["suppressed"] is True
    total = find(r, age_band="65+ (all)")
    assert (total["eligible_patients"], total["patients_with_polypharmacy"],
            total["polypharmacy_pct"]) == (None, 11, None)


# ------------------------------------------------------------------ 8. flu vaccination

def test_flu_vaccination(app_conn):
    r = rows(app_conn, "flu_vaccination")
    # 65-74: 22 eligible; vaccinated in the window: p01 (2024-10-05) + 12 C1 = 13 -> 59.1%.
    # C1 #12's shot on 2023-10-01 is outside the window and does not count.
    band = find(r, age_band="65-74")
    assert (band["eligible_patients"], band["vaccinated_patients"]) == (22, 13)
    assert band["vaccination_pct"] == Decimal("59.1")
    assert find(r, age_band="65+ (all)")["eligible_patients"] is None   # 90+ has 1 patient
