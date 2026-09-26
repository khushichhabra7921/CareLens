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
