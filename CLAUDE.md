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
- Schemas: `phi` holds identifiers only; `analytics` holds de-identified + clinical data; `app` holds reports, the audit log and name-token hashes.
- The web app connects as `app_readonly`, which has **no access to `phi`**.
- Analyses return aggregates only. Counts 1–10 are suppressed (NULL + `suppressed` flag).
- Reference date = the latest encounter date in the data, never `CURRENT_DATE`.
- Never guess clinical codes. Look them up in the data or in official sources.
- Secrets live only in env vars / `.env` (gitignored). `.env.example` is committed. The app refuses to start if a secret is missing.

## Files
- All text files are UTF-8 without a BOM. Check with `py -3.12 scripts/check_encoding.py`.
- `data/`, `tools/`, `.env` and `.venv/` are gitignored. Check with `git check-ignore -v <path>`.

## Common commands (PowerShell)
```
py -3.12 -m venv .venv; .\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
pytest; ruff check .
docker compose up --build
```
