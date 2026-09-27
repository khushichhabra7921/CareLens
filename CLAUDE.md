# CareLens: conventions for Claude sessions

Population health analytics on Synthea synthetic data, with privacy-safe LLM reports.
The full brief is in the owner's Downloads/PROJECT_BRIEF.md. Decisions are logged in `docs/DECISIONS.md`.

## Working rules
- Work one milestone at a time. At the end of each: run the tests, make small, specific commits, write a plain-English summary, append to `docs/DECISIONS.md`, then stop and wait.
- The owner must be able to explain every line. Keep code simple and readable, and explain the "why".
- Ask before: installing system software, creating any AWS resource, deleting data, rewriting git history, force-pushing.
- **AWS: the owner cannot pay anything.** Show every resource and its cost, and get confirmation first.
- Machine: Windows + PowerShell. Use `py -3.12`, and write Python scripts rather than bash.
- No invented numbers. Every figure in docs comes from a real run, and is script-generated where possible.

## Tech
- Python 3.12, FastAPI, Pydantic v2, psycopg 3, PostgreSQL 16, Groq (model from `LLM_MODEL`).
- Analyses are plain `.sql` files in `sql/analyses/` (no ORM). Frontend: one static HTML page, vanilla JS, Chart.js.
- pytest, ruff (`ruff check .`), Docker Compose, GitHub Actions. No Kubernetes, microservices or queues.

## Data & privacy (treat synthetic data as real PHI)
- Schemas: `phi` identifiers; `analytics` pseudonymized row-level clinical data; `reporting` aggregate materialized views; `app` reports/audit/name hashes; `loader` rejected rows.
- The web app connects as `app_readonly`, which can read **only `reporting`** (no `phi`, `analytics` or `loader`).
- Analyses return aggregates only. Counts 1–10 are suppressed (NULL + `suppressed` flag).
- Reference date = the latest encounter date in the data, never `CURRENT_DATE`.
- Never guess clinical codes. Look them up in the data or in official sources.
- Secrets live only in env vars / `.env` (gitignored). `.env.example` is committed. The app refuses to start if a secret is missing.

## Data generation
- `scripts/generate_data.py`: Synthea v4.0.0 pinned + SHA-256; seeds 42; `-r` **and** `-e` 20250101 (without `-e` the output changes daily).
- Follow the real CSV headers, not the wiki (see DECISIONS M2). Don't load payer summary totals; they aren't reproducible.
- Test fixture: edit `tests/fixtures/build_fixture.py`, then run it; never hand-edit `synthea_mini/*.csv`.
- Local Docker Postgres is on host port **5433** (5432 is taken by another install).

## Database
- Setup: `py -3.12 scripts/db_setup.py` (`--recreate` after schema changes). Load: `py -3.12 scripts/load_data.py`.
- Schema DDL in `sql/schema/NNN_*.sql` (applied in order, as `carelens_loader`); roles in `sql/roles.sql` (as admin).
- Loader transform is `sql/load/transform.sql`: guard casts with ordered `CASE WHEN` branches, never `A OR B`.
- DB is UTC. Use `127.0.0.1` not `localhost` (IPv6 delay on Windows). Tests use DB `carelens_test`.

## Analyses
- One file per result table in `sql/analyses/NN[a]_name.sql` becomes `reporting.name`. Header fields Title/Question/Method/Assumptions/Limitations are required (parsed by `refresh_views.py`).
- Use `analytics.suppress()`, `safe_pct()`, `is_small()`, `total_reveals_small()`; every view has `sort_order` and `suppressed`.
- Code sets live in `analytics.condition_groups` / `vaccine_groups` (006_reference.sql), never inline guesses.
- After editing an analysis: `refresh_views.py --rebuild`, update `tests/test_analyses.py`, run `export_findings.py`.

## Files
- All text files are UTF-8 without a BOM. Check with `py -3.12 scripts/check_encoding.py`.
- `data/`, `tools/`, `.env` and `.venv/` are gitignored. Check with `git check-ignore -v <path>`.

## Common commands (PowerShell)
```
py -3.12 -m venv .venv; .\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
docker compose up -d db
py -3.12 scripts/db_setup.py; py -3.12 scripts/load_data.py
pytest; ruff check .
docker compose up --build
```
