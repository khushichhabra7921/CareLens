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
## Milestone 3: Postgres schema and loading

- **Four schemas by sensitivity:** `phi` (direct identifiers), `analytics` (clinical, pseudonymized),
  `app` (reports/audit, filled in M6), `loader` (rejected rows, which can contain PHI). The web app's role
  can read `analytics` only.
- **Honest labelling: `analytics` is pseudonymized, not Safe Harbor de-identified.** HHS's Safe Harbor
  guidance lists county and every date element except the year (admission and discharge dates included) as
  identifiers. `analytics` keeps service dates and county because the analyses need them. Safe Harbor-level
  output is enforced at the boundary instead: the API returns only aggregates, small cells are suppressed
  (M4), and the LLM payload reduces dates to year or month (M6). Name, SSN, driver's licence, passport,
  street address, city, 5-digit ZIP, lat/lon, birth date and birthplace exist only in `phi`.
- **Age bands** `0-17, 18-44, 45-64, 65-74, 75-89, 90+`: age at the reference date, or at death for
  deceased patients. 90+ is one band (Safe Harbor). 65-74, 75-89 and 90+ together give the 65+ group
  the polypharmacy and flu analyses need.
- **ZIP3:** `00000` (Synthea's "unknown", 309 patients, all with an empty FIPS too) becomes NULL. The 17
  low-population 3-digit ZIP areas on the HHS list (2000 Census) become `000`. None are in
  Massachusetts. Limitation: HHS says to prefer newer Census data when available.
- **Data minimization:** marital status, income, lifetime expenses, provider names/addresses and payer
  summary totals are not loaded anywhere, because no analysis needs them.
- **Every CHECK constraint was tested against the full data first.** Two were dropped because real
  Synthea rows break them: 57 medications stop a few days before they start (no `stop >= start`
  check on medications), and 226 observations are exact duplicates (kept, with a generated key).
- **Roles:** `carelens_loader` owns everything and loads data; `app_readonly` gets SELECT on
  `analytics` (plus default privileges, so future materialized views are covered) and nothing on `phi` or
  `loader`. `REVOKE ALL ON DATABASE ... FROM PUBLIC` means no other role can even connect. The app role
  also can't create temp tables and has a 15s statement timeout. Passwords come from `.env` and are set
  with `ALTER ROLE ... PASSWORD` using `psycopg.sql.Literal` (safe quoting); they are never in a SQL file.
- **Database pinned to UTC** (`ALTER DATABASE ... SET timezone = 'UTC'`). `max(start_ts)::date`
  depends on the session time zone, so without this the reference date could change from machine to machine.
- **Loader design:** one transaction: COPY each CSV into an all-text temp table, compare the staged count
  with the csv-module count, TRUNCATE the targets, then `sql/load/transform.sql` validates each row.
  Valid rows go to the typed tables; invalid ones go to `loader.rejected_rows` with a reason. Finally
  loaded + rejected must equal the CSV rows for every table, and the reference date must equal the latest
  loaded encounter, or the whole load rolls back. Result on the full data: 1,196,468 rows, 0 rejected,
  72.6 s. The reject path is tested with deliberately broken fixture rows.
- **Evaluation order bug avoided:** SQL doesn't guarantee that `A OR B` evaluates A first, so
  `NOT pg_input_is_valid(x,'uuid') OR NOT EXISTS (... x::uuid)` could crash on a bad ID. Every guard
  is its own ordered `CASE WHEN` branch, and empty optional values use `NULLIF(x,'')` before casting.
- **COPY + FORCE_NOT_NULL:** CSV-mode COPY turns empty fields into NULL. Forcing `''` keeps "empty"
  handled one way throughout the transform SQL.
- **Idempotent:** TRUNCATE ... RESTART IDENTITY + reload, so re-running gives identical tables and IDs.
  Changing the schema itself needs `db_setup.py --recreate` (the data can always be rebuilt from CSV).
  No migration tool; it's not needed for a rebuildable dataset.
- **Indexes:** on every foreign key, plus composites for the analysis filters. Measured on the full
  data: the care-gap benchmark drops from 297.6 ms (parallel seq scan) to 3.0 ms (index-only scan),
  98x. The "before" run drops the indexes inside a transaction that is rolled back.
- **Tests use a separate `carelens_test` database**, recreated each session, so tests never touch the
  full dataset. They skip if Postgres is down, unless `REQUIRE_DB=1` (CI sets it).
- **`127.0.0.1` instead of `localhost`:** on Windows `localhost` resolves to IPv6 `::1` first. Docker
  only listens on IPv4, and each refused attempt cost 2.1 s. The test suite went from 287 s to 6.5 s.