"""Build the small, deterministic test fixture used by tests and CI (no Java needed).

It writes Synthea-format CSVs (exactly the v4.0.0 headers) to tests/fixtures/synthea_mini/.
Every patient is invented here by hand, never copied from generated data. All SSNs start
with 999, a range the US Social Security Administration never issues.

Clinical codes (SNOMED, LOINC, RxNorm, CVX) are real ones taken from the generated Synthea
data, so the fixture exercises the same code paths as the full dataset.

Regenerate after editing:  py -3.12 tests/fixtures/build_fixture.py
"""

import csv
import sys
import uuid
from pathlib import Path

# The headers live in scripts/synthea_columns.py (shared with the loader).
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from synthea_columns import HEADERS  # noqa: E402

OUT_DIR = Path(__file__).resolve().parent / "synthea_mini"

# The simulated timeline ends here, like the full dataset (-r/-e 20250101).
REFERENCE_DATE = "2025-01-01"

# Namespace for deterministic UUIDs: the same label always gives the same ID.
NAMESPACE = uuid.UUID("7f0c3a52-2c1e-4f5e-9b1a-6c1d2e3f4a5b")

def uid(label: str) -> str:
    return str(uuid.uuid5(NAMESPACE, label))


class Fixture:
    """Collects rows per table. Unspecified columns are left empty, like Synthea does."""

    def __init__(self):
        self.rows = {table: [] for table in HEADERS}

    def add(self, table: str, **values) -> None:
        columns = HEADERS[table].split(",")
        unknown = set(values) - set(columns)
        if unknown:
            raise ValueError(f"{table}: unknown columns {unknown}")
        self.rows[table].append({c: values.get(c, "") for c in columns})

    def write(self, out_dir: Path = OUT_DIR) -> None:
        out_dir.mkdir(parents=True, exist_ok=True)
        for table, rows in self.rows.items():
            # newline="" + lineterminator="\n": identical bytes on Windows and Linux.
            columns = HEADERS[table].split(",")
            with open(out_dir / f"{table}.csv", "w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=columns, lineterminator="\n")
                writer.writeheader()
                writer.writerows(rows)


# --- Real codes, looked up in the generated Synthea v4.0.0 data ---
WELLNESS = ("162673000", "General examination of patient (procedure)")
WELL_CHILD = ("410620009", "Well child visit (procedure)")
EMERGENCY = ("50849002", "Emergency room admission (procedure)")
INPATIENT = ("32485007", "Hospital admission (procedure)")
PROBLEM_VISIT = ("185347001", "Encounter for problem (procedure)")
HYPERTENSION = ("59621000", "Essential hypertension (disorder)")
CARIES_ICD10 = ("K02.9", "Dental caries  unspecified")  # double space is how Synthea writes it
HBA1C = ("4548-4", "Hemoglobin A1c/Hemoglobin.total in Blood", "%", "laboratory")
SYSTOLIC = ("8480-6", "Systolic Blood Pressure", "mm[Hg]", "vital-signs")
DIASTOLIC = ("8462-4", "Diastolic Blood Pressure", "mm[Hg]", "vital-signs")
INSULIN = ("106892", "insulin isophane  human 70 UNT/ML / insulin  regular  human 30 UNT/ML "
           "Injectable Suspension [Humulin]")
DEPRESSION_SCREEN = ("171207006", "Depression screening (procedure)")
TOOTH_EXTRACTION_CDT = ("D7140", "extraction  erupted tooth or exposed root "
                        "(elevation and/or forceps removal)")
FLU_VACCINE = ("140", "Influenza  split virus  trivalent  PF")
DIABETES = ("44054006", "Diabetes mellitus type 2 (disorder)")
CHILDHOOD_ASTHMA = ("233678006", "Childhood asthma (disorder)")
HEART_FAILURE = ("88805009", "Chronic congestive heart failure (disorder)")
LISINOPRIL = ("314076", "lisinopril 10 MG Oral Tablet")
FIVE_MEDS = [  # five different RxNorm codes, all found in the generated data
    LISINOPRIL,
    ("866412", "24 HR metoprolol succinate 100 MG Extended Release Oral Tablet"),
    ("312961", "Simvastatin 20 MG Oral Tablet"),
    ("309362", "Clopidogrel 75 MG Oral Tablet"),
    ("310798", "Hydrochlorothiazide 25 MG Oral Tablet"),
]

# Invented names for the cohort patients (none match the 8 hand-written patients).
COHORT_FIRST = ["Avery", "Blake", "Casey", "Devon", "Emerson", "Finley", "Harper", "Jules",
                "Kendall", "Logan", "Morgan", "Parker", "Quinn", "Reese", "Rowan", "Sage",
                "Skyler", "Taylor", "Tatum", "Wren"]
COHORT_LAST = ["Ashford", "Brookline", "Carrow", "Dunmore", "Ellery", "Fairholm", "Garrick",
               "Holloway", "Ivers", "Kestrel", "Lindqvist", "Marlowe"]


def build() -> Fixture:
    fx = Fixture()

    # --- Organizations, providers, payers (made up; payer names as Synthea uses them) ---
    for key, name, city in [("org-hospital", "Example General Hospital", "Springfield"),
                            ("org-clinic", "Example Family Clinic", "Shelbyville")]:
        fx.add("organizations", Id=uid(key), NAME=name, ADDRESS="1 Example Way", CITY=city,
               STATE="MA", ZIP="01000", LAT="42.1", LON="-72.5", PHONE="555-0100",
               REVENUE="0.0", UTILIZATION="0")
    for key, org, name, gender in [("prov-a", "org-hospital", "Pat Example", "F"),
                                   ("prov-b", "org-clinic", "Sam Sample", "M")]:
        fx.add("providers", Id=uid(key), ORGANIZATION=uid(org), NAME=name, GENDER=gender,
               SPECIALITY="GENERAL PRACTICE", ADDRESS="1 Example Way", CITY="Springfield",
               STATE="MA", ZIP="01000", LAT="42.1", LON="-72.5", ENCOUNTERS="0", PROCEDURES="0")
    payer_zeros = {c: "0" for c in HEADERS["payers"].split(",")[8:]}
    for key, name, ownership in [("payer-medicare", "Medicare", "GOVERNMENT"),
                                 ("payer-medicaid", "Medicaid", "GOVERNMENT"),
                                 ("payer-aetna", "Aetna", "PRIVATE"),
                                 ("payer-none", "NO_INSURANCE", "NO_INSURANCE")]:
        fx.add("payers", Id=uid(key), NAME=name, OWNERSHIP=ownership, **payer_zeros)

    # --- Patients: each one covers an edge case (see comments) ---
    def patient(key, birth, first, last, gender, race, ethnicity, n, **extra):
        values = dict(
            Id=uid(key), BIRTHDATE=birth, SSN=f"999-00-{n:04d}", FIRST=first, LAST=last,
            GENDER=gender, RACE=race, ETHNICITY=ethnicity,
            BIRTHPLACE="Springfield  Massachusetts  US", ADDRESS=f"{n} Example Street",
            CITY="Springfield", STATE="Massachusetts", COUNTY="Hampden County", FIPS="25013",
            ZIP="01101", LAT="42.10", LON="-72.59", HEALTHCARE_EXPENSES="1000.00",
            HEALTHCARE_COVERAGE="500.00", INCOME="50000",
        )
        values.update(extra)  # per-patient values override the defaults above
        fx.add("patients", **values)

    ids = {"DRIVERS": "S99999001", "PASSPORT": "X99999001X"}
    # Hyphenated surname, maiden name, all optional fields present.
    patient("p01", "1950-03-15", "Mary", "Smith-Jones", "F", "white", "nonhispanic", 1,
            PREFIX="Mrs.", MIDDLE="Ellen", MAIDEN="Smith", MARITAL="M", **ids)
    # Non-ASCII name; uninsured ED visit; ICD-10 condition.
    patient("p02", "1985-07-22", "José", "García", "M", "white", "hispanic", 2,
            PREFIX="Mr.", MARITAL="S")
    # Age 92 at the reference date, so he falls in the "90+" band. First and last name
    # are also everyday English words (hard case for the name redactor).
    patient("p03", "1932-06-01", "Will", "Young", "M", "black", "nonhispanic", 3,
            PREFIX="Mr.", MARITAL="W")
    # Deceased patient.
    patient("p04", "1940-01-10", "Robert", "Brown", "M", "white", "nonhispanic", 4,
            DEATHDATE="2023-08-20", PREFIX="Mr.", MARITAL="M")
    # Infant, under 1 year old at the reference date.
    patient("p05", "2024-11-02", "Ava", "Chen", "F", "asian", "nonhispanic", 5)
    # Only required fields: no prefix, middle, maiden, marital status, IDs or FIPS.
    patient("p06", "1990-12-31", "Grace", "Lee", "F", "black", "nonhispanic", 6, FIPS="")
    # More everyday-word names.
    patient("p07", "1958-04-04", "Mark", "Grant", "M", "native", "nonhispanic", 7, MARITAL="D")
    patient("p08", "1972-09-09", "Hope", "Rivera", "F", "other", "hispanic", 8, MARITAL="M")

    # --- Encounters and clinical events ---
    def encounter(key, pat, start, stop, cls, code, payer, org="org-clinic", prov="prov-b",
                  cost="100.00", covered="80.00", reason=("", "")):
        fx.add("encounters", Id=uid(key), START=start, STOP=stop, PATIENT=uid(pat),
               ORGANIZATION=uid(org), PROVIDER=uid(prov), PAYER=uid(payer), ENCOUNTERCLASS=cls,
               CODE=code[0], DESCRIPTION=code[1], BASE_ENCOUNTER_COST="85.55",
               TOTAL_CLAIM_COST=cost, PAYER_COVERAGE=covered, REASONCODE=reason[0],
               REASONDESCRIPTION=reason[1])

    def condition(pat, enc, start, code, stop=""):
        fx.add("conditions", START=start, STOP=stop, PATIENT=uid(pat), ENCOUNTER=uid(enc),
               SYSTEM="SNOMED-CT", CODE=code[0], DESCRIPTION=code[1])

    def medication(pat, enc, start, code, payer, stop=""):
        fx.add("medications", START=start, STOP=stop, PATIENT=uid(pat), PAYER=uid(payer),
               ENCOUNTER=uid(enc), CODE=code[0], DESCRIPTION=code[1], BASE_COST="10.00",
               PAYER_COVERAGE="8.00", DISPENSES="1", TOTALCOST="10.00")

    def observation(date, pat, enc, obs, value):
        fx.add("observations", DATE=date, PATIENT=uid(pat), ENCOUNTER=uid(enc) if enc else "",
               CATEGORY=obs[3], CODE=obs[0], DESCRIPTION=obs[1], VALUE=value, UNITS=obs[2],
               TYPE="numeric")

    # p01: wellness visit with labs and vitals, chronic condition, active medication,
    # flu shot, then two inpatient stays 15 days apart (a 30-day readmission).
    encounter("e01a", "p01", "2024-02-10T09:00:00Z", "2024-02-10T09:30:00Z", "wellness",
              WELLNESS, "payer-medicare")
    observation("2024-02-10T09:10:00Z", "p01", "e01a", HBA1C, "6.1")
    observation("2024-02-10T09:05:00Z", "p01", "e01a", SYSTOLIC, "138.0")
    observation("2024-02-10T09:05:00Z", "p01", "e01a", DIASTOLIC, "86.0")
    fx.add("conditions", START="2024-02-10", PATIENT=uid("p01"), ENCOUNTER=uid("e01a"),
           SYSTEM="SNOMED-CT", CODE=HYPERTENSION[0], DESCRIPTION=HYPERTENSION[1])
    fx.add("medications", START="2024-02-10T09:30:00Z", PATIENT=uid("p01"),
           PAYER=uid("payer-medicare"), ENCOUNTER=uid("e01a"), CODE=INSULIN[0],
           DESCRIPTION=INSULIN[1], BASE_COST="40.00", PAYER_COVERAGE="30.00", DISPENSES="10",
           TOTALCOST="400.00")  # no STOP: still active
    encounter("e01b", "p01", "2024-03-01T08:00:00Z", "2024-03-05T12:00:00Z", "inpatient",
              INPATIENT, "payer-medicare", org="org-hospital", prov="prov-a",
              cost="12000.00", covered="10000.00")
    encounter("e01c", "p01", "2024-03-20T14:00:00Z", "2024-03-22T10:00:00Z", "inpatient",
              INPATIENT, "payer-medicare", org="org-hospital", prov="prov-a",
              cost="8000.00", covered="6500.00")
    encounter("e01d", "p01", "2024-10-05T10:00:00Z", "2024-10-05T10:20:00Z", "wellness",
              WELLNESS, "payer-medicare")
    fx.add("immunizations", DATE="2024-10-05T10:10:00Z", PATIENT=uid("p01"),
           ENCOUNTER=uid("e01d"), CODE=FLU_VACCINE[0], DESCRIPTION=FLU_VACCINE[1],
           BASE_COST="136.00")

    # p02: uninsured ED visit (payer pays nothing), then a dental visit with ICD-10 + CDT codes.
    encounter("e02a", "p02", "2024-07-04T22:00:00Z", "2024-07-05T01:00:00Z", "emergency",
              EMERGENCY, "payer-none", org="org-hospital", prov="prov-a",
              cost="1500.00", covered="0.00")
    encounter("e02b", "p02", "2024-08-01T10:00:00Z", "2024-08-01T10:45:00Z", "ambulatory",
              PROBLEM_VISIT, "payer-none", covered="0.00")
    fx.add("conditions", START="2024-08-01", STOP="2024-09-01", PATIENT=uid("p02"),
           ENCOUNTER=uid("e02b"), SYSTEM="ICD10", CODE=CARIES_ICD10[0],
           DESCRIPTION=CARIES_ICD10[1])
    fx.add("procedures", START="2024-08-01T10:10:00Z", STOP="2024-08-01T10:40:00Z",
           PATIENT=uid("p02"), ENCOUNTER=uid("e02b"), SYSTEM="CDT",
           CODE=TOOTH_EXTRACTION_CDT[0], DESCRIPTION=TOOTH_EXTRACTION_CDT[1], BASE_COST="250.00")

    # p03: 90+ wellness visit with a SNOMED procedure.
    encounter("e03a", "p03", "2024-05-01T09:00:00Z", "2024-05-01T09:30:00Z", "wellness",
              WELLNESS, "payer-medicare")
    fx.add("procedures", START="2024-05-01T09:10:00Z", STOP="2024-05-01T09:20:00Z",
           PATIENT=uid("p03"), ENCOUNTER=uid("e03a"), SYSTEM="SNOMED-CT",
           CODE=DEPRESSION_SCREEN[0], DESCRIPTION=DEPRESSION_SCREEN[1], BASE_COST="20.00")

    # p04: visit and diagnosis before death.
    encounter("e04a", "p04", "2023-06-01T09:00:00Z", "2023-06-01T09:30:00Z", "ambulatory",
              PROBLEM_VISIT, "payer-medicare")
    fx.add("conditions", START="2023-06-01", PATIENT=uid("p04"), ENCOUNTER=uid("e04a"),
           SYSTEM="SNOMED-CT", CODE=HYPERTENSION[0], DESCRIPTION=HYPERTENSION[1])

    # p05: infant well-child visit.
    encounter("e05a", "p05", "2024-12-02T09:00:00Z", "2024-12-02T09:30:00Z", "wellness",
              WELL_CHILD, "payer-medicaid")

    # p06: an observation with no encounter (Synthea writes QALY/DALY like this).
    encounter("e06a", "p06", "2024-09-09T09:00:00Z", "2024-09-09T09:30:00Z", "wellness",
              WELLNESS, "payer-aetna")
    fx.add("observations", DATE="2024-12-31T00:00:00Z", PATIENT=uid("p06"), CODE="QALY",
           DESCRIPTION="QALY", VALUE="33.0", UNITS="a", TYPE="numeric")

    # p07, p08: one ambulatory and one ED visit, privately insured.
    encounter("e07a", "p07", "2024-04-04T11:00:00Z", "2024-04-04T11:30:00Z", "ambulatory",
              PROBLEM_VISIT, "payer-aetna")
    encounter("e08a", "p08", "2024-01-15T03:00:00Z", "2024-01-15T06:00:00Z", "emergency",
              EMERGENCY, "payer-aetna", org="org-hospital", prov="prov-a",
              cost="1200.00", covered="900.00")

    # p06: childhood asthma that resolved in 2015, so it is NOT active on the reference date.
    encounter("e06b", "p06", "2010-05-05T09:00:00Z", "2010-05-05T09:30:00Z", "wellness",
              WELLNESS, "payer-aetna")
    condition("p06", "e06b", "2010-05-05", CHILDHOOD_ASTHMA, stop="2015-05-05")

    # ================================================================== cohorts
    # Groups of more than 10 patients, so the analyses have numbers that are NOT suppressed.
    # Each cohort is sized so every analysis has one cell above 10 and one cell of 1-10.
    # The expected results, worked out by hand, are in tests/test_analyses.py.
    # Reference date = 2024-12-02 (latest encounter, p05's visit). "Last 12 months" =
    # after 2023-12-02 up to and including 2024-12-02. All cohort dates avoid the edges.

    def cohort_patient(key, n, i, birth, gender, ethnicity):
        patient(key, birth, COHORT_FIRST[i % 20], COHORT_LAST[(i * 7) % 12], gender, "white",
                ethnicity, n)

    # C1: 20 patients aged 69 (65-74), 12 women and 8 men, Medicare. All have diabetes and
    # hypertension (diagnosed 2018), and a wellness visit on 2024-10-15 with blood pressure.
    #   - HbA1c at that visit for i < 14         -> 6 diabetics with a care gap
    #   - flu shot at that visit for i < 12      -> 12 vaccinated (+ p01 = 13)
    #   - 5 active medications for i < 11        -> 11 with polypharmacy; the rest have 1
    #   - i == 11 also has 4 medications that STOPPED before the reference date (not active)
    #   - i == 12 had a flu shot on 2023-10-01, outside the 12-month window
    for i in range(20):
        p = f"c1-{i}"
        cohort_patient(p, 101 + i, i, "1955-06-15", "F" if i < 12 else "M", "nonhispanic")
        encounter(f"{p}-dx", p, "2018-01-10T09:00:00Z", "2018-01-10T09:30:00Z", "ambulatory",
                  PROBLEM_VISIT, "payer-medicare")
        condition(p, f"{p}-dx", "2018-01-10", DIABETES)
        condition(p, f"{p}-dx", "2018-01-10", HYPERTENSION)
        visit = f"{p}-well"
        encounter(visit, p, "2024-10-15T09:00:00Z", "2024-10-15T09:30:00Z", "wellness",
                  WELLNESS, "payer-medicare")
        observation("2024-10-15T09:05:00Z", p, visit, SYSTOLIC, "128.0")
        observation("2024-10-15T09:05:00Z", p, visit, DIASTOLIC, "82.0")
        if i < 14:
            observation("2024-10-15T09:10:00Z", p, visit, HBA1C, "7.2")
        if i < 12:
            fx.add("immunizations", DATE="2024-10-15T09:20:00Z", PATIENT=uid(p),
                   ENCOUNTER=uid(visit), CODE=FLU_VACCINE[0], DESCRIPTION=FLU_VACCINE[1],
                   BASE_COST="136.00")
        for med in (FIVE_MEDS if i < 11 else [LISINOPRIL]):
            medication(p, visit, "2024-10-15T09:30:00Z", med, "payer-medicare")
        if i == 11:
            for med in FIVE_MEDS[1:]:
                medication(p, f"{p}-dx", "2018-01-10T09:30:00Z", med, "payer-medicare",
                           stop="2024-06-01T00:00:00Z")
        if i == 12:
            encounter(f"{p}-flu2023", p, "2023-10-01T09:00:00Z", "2023-10-01T09:15:00Z",
                      "wellness", WELLNESS, "payer-medicare")
            fx.add("immunizations", DATE="2023-10-01T09:05:00Z", PATIENT=uid(p),
                   ENCOUNTER=uid(f"{p}-flu2023"), CODE=FLU_VACCINE[0],
                   DESCRIPTION=FLU_VACCINE[1], BASE_COST="136.00")

    # C2: 12 men aged 54 (45-64), Aetna. Hypertension since 2018, a wellness visit on
    # 2024-06-01 but NO blood pressure reading -> 12 hypertensive patients with a care gap.
    for i in range(12):
        p = f"c2-{i}"
        cohort_patient(p, 201 + i, i, "1970-02-02", "M", "nonhispanic")
        encounter(f"{p}-dx", p, "2018-01-10T10:00:00Z", "2018-01-10T10:30:00Z", "ambulatory",
                  PROBLEM_VISIT, "payer-aetna")
        condition(p, f"{p}-dx", "2018-01-10", HYPERTENSION)
        encounter(f"{p}-well", p, "2024-06-01T09:00:00Z", "2024-06-01T09:30:00Z", "wellness",
                  WELLNESS, "payer-aetna")

    # C3: 12 women aged 34 (18-44), hispanic, Aetna. A hospital stay for heart failure,
    # discharged 2024-04-04.
    #   - i < 11 come back on 2024-04-20 (16 days later) -> 11 readmissions
    #   - i == 11 is admitted again on 2024-11-20: discharged within 30 days of the reference
    #     date, so that stay is NOT an index stay (no full 30-day follow-up)
    heart_failure_stay = dict(org="org-hospital", prov="prov-a", cost="10000.00",
                              covered="9000.00", reason=HEART_FAILURE)
    for i in range(12):
        p = f"c3-{i}"
        cohort_patient(p, 301 + i, i, "1990-03-03", "F", "hispanic")
        encounter(f"{p}-stay1", p, "2024-04-01T08:00:00Z", "2024-04-04T12:00:00Z", "inpatient",
                  INPATIENT, "payer-aetna", **heart_failure_stay)
        condition(p, f"{p}-stay1", "2024-04-01", HEART_FAILURE)  # diagnosed on the first stay
        if i < 11:
            encounter(f"{p}-stay2", p, "2024-04-20T08:00:00Z", "2024-04-22T12:00:00Z",
                      "inpatient", INPATIENT, "payer-aetna", **heart_failure_stay)
        else:
            encounter(f"{p}-stay3", p, "2024-11-20T08:00:00Z", "2024-11-22T12:00:00Z",
                      "inpatient", INPATIENT, "payer-aetna", **heart_failure_stay)

    # C4: 11 men aged 29 (18-44), Aetna. Four ED visits each in the last 12 months
    # -> 11 frequent ED users, 44 ED visits.
    for i in range(11):
        p = f"c4-{i}"
        cohort_patient(p, 401 + i, i, "1995-05-05", "M", "nonhispanic")
        for month in ["02", "03", "05", "08"]:
            encounter(f"{p}-ed{month}", p, f"2024-{month}-01T20:00:00Z",
                      f"2024-{month}-01T23:00:00Z", "emergency", EMERGENCY, "payer-aetna",
                      org="org-hospital", prov="prov-a", cost="1000.00", covered="800.00")
    return fx


if __name__ == "__main__":
    build().write()
    print(f"Fixture written to {OUT_DIR}")
