# Design decisions

Short log of why things are the way they are. Newest milestone at the bottom.

## Milestone 1: Repo and local environment

- **Repo lives outside OneDrive** (`C:\Users\hp\dev\CareLens`). OneDrive would sync the generated
  patient data (names, SSNs, addresses) and `.env` secrets to a personal cloud drive. We treat
  the synthetic data as real PHI, so that would be a leak.
- **Python 3.12 from python.org + a plain `venv`**, not Conda. It's the standard setup and one less
  tool to explain. `py -3.12` picks the right version even though Miniconda 3.13 is also installed.
- **Pinned dependency versions** in `requirements.txt`, so local, Docker and CI installs are identical.
  Dev tools are in a separate `requirements-dev.txt` so they aren't shipped in the Docker image.
- **The app refuses to start** if `APP_DB_PASSWORD` or `ADMIN_API_KEY` is missing, empty, or still
  the `change-me` placeholder. Settings load in FastAPI's startup (lifespan) hook, so the failure
  happens at boot, not on the first request. Secrets use Pydantic's `SecretStr`, so they
  print as `**********` in logs. `GROQ_API_KEY` is optional because the app has a template fallback.
- **Ports bound to `127.0.0.1`** in Docker Compose, so Postgres and the app are reachable only from
  this machine, not from other devices on the same Wi-Fi.
- **The container runs as a non-root user.** If the app were compromised, the attacker wouldn't be root
  inside the container.
- **`.gitattributes` forces LF line endings** in git. Windows editors write CRLF, which breaks
  shell scripts and `.sql` heredocs run inside Linux containers and CI.
- **Docker Postgres uses host port 5433.** A separate Postgres installed on this machine already
  listens on 5432. Inside Docker the app still connects to `db:5432`, and only scripts running on
  the host use 5433 (`DB_PORT` in `.env`).
- **`httpx2` instead of `httpx`** for FastAPI's `TestClient`. Starlette 1.7 deprecates `httpx`,
  and switching removes the warning. It's a dev-only dependency.
- **`scripts/check_encoding.py`** fails if any tracked text file isn't UTF-8 or starts with a
  BOM. It guards against the UTF-16 `.gitignore` problem that broke an earlier repo, and it will run in CI.

## Milestone 2: Synthetic patients with Synthea

- **Pinned Synthea v4.0.0** (not `master-branch-latest`) with a SHA-256 check. The "latest" jar changes
  over time, so the same seed would stop producing the same patients. If the checksum doesn't
  match, the script deletes the jar and stops, so we never run code we can't verify. (Oddly, the
  jar reports itself internally as `v3.4.0-18-ga07a65555`, but it is the asset published under the v4.0.0 tag.)
- **`-e 20250101` added on top of `-r 20250101`.** Found by checking the data: with only `-r`, the latest
  encounter was 2026-10-14 and the run metadata said `endTime: 20260926` (the day of the run).
  `-r` only sets the date used to calculate ages; the simulation still ran until the real current date.
  With `-e`, the latest encounter starts on 2024-12-31.
- **Reproducibility, checked:** two runs with identical settings gave the same rows in 16 of 18 CSVs
  (row order differs because Synthea uses 12 threads, which a database doesn't care about).
  Only `claims_transactions` (not loaded) and the payer **summary totals** (`AMOUNT_COVERED`,
  `REVENUE`, …, about 0.02% apart) differ. So we load only `Id`, `NAME` and `OWNERSHIP` from payers
  and calculate all costs from the encounter rows.
- **Result of the default run:** 1,155 patients (1,000 alive + 155 deceased; `-p` counts living
  patients only). The main tables are encounters (70,597 rows), observations (870,136), conditions (40,330)
  and medications (51,302), 693 MB of CSV in total.
- **FHIR fully off.** `exporter.fhir.export=false` alone still writes hospital and practitioner FHIR files,
  so those two are switched off as well.
- **Real-looking names** (`generate.append_numbers_to_person_names=false`). The default adds digits
  (`Jose871`), which would make the name redactor's job unrealistically easy. The data contains 2,077 distinct
  name tokens, 50 name fields with non-ASCII letters, and tokens that are everyday words
  (`Will`, `Mark`, `Grant`, `Long`, `Young`, `White`), a known false-positive risk for M6.
- **The wiki data dictionary is out of date for v4.0.0.** Differences found in the real files:
  immunizations use `BASE_COST` (not `COST`); 26,844 observations (QALY/DALY-style) have **no
  encounter**; conditions include **897 ICD-10** codes as well as SNOMED-CT (a new `SYSTEM` column);
  payer ownership includes `NO_INSURANCE`; the patient county column is `FIPS`. The schema follows the
  real files, and a test compares the fixture headers with the generated headers.
- **Clinical codes found in the data** (not guessed): HbA1c LOINC `4548-4`, systolic/diastolic BP
  `8480-6`/`8462-4`, essential hypertension SNOMED `59621000`, flu vaccine CVX `140` (the only
  influenza code in this run), ED encounter class `emergency`, inpatient class `inpatient`.
- **Test fixture = a small Python builder** (`tests/fixtures/build_fixture.py`), not hand-typed CSVs.
  It writes Synthea-format CSVs with the exact v4.0.0 headers. Patients are invented by hand (SSNs start
  with `999`, which is never issued), while the clinical codes are real. Deterministic UUIDs (`uuid5`) mean the
  same patient always gets the same ID. A test fails if the committed CSVs don't match the builder.
  It currently covers structural edge cases (90+, deceased, infant, non-ASCII name, everyday-word
  names, missing optional fields, an observation without an encounter, ICD-10, CDT, uninsured). **In M4
  we'll add cohorts larger than 10**, because small-cell suppression would otherwise turn every count into NULL
  and there would be nothing to check by hand.