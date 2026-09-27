"""FastAPI entry point. Run locally with:  uvicorn app.main:app --reload

Endpoints:
  GET  /health                 app and database status
  GET  /api/analyses           list of the 8 analyses
  GET  /api/analyses/{id}      aggregate results (cached; small cells already suppressed)
  POST /api/reports            generate an insight report (admin API key + per-IP rate limit)
  GET  /api/reports/{id}       fetch a stored report
  GET  /                       the dashboard (static HTML + JS)
"""

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import UUID

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app import analyses, reports
from app.config import get_settings
from app.db import create_pool
from app.report_schema import ReportRecord
from app.security import DASHBOARD_CSP, SECURITY_HEADERS, RateLimiter, check_api_key, client_ip

STATIC_DIR = Path(__file__).parent / "static"
log = logging.getLogger("carelens")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Load settings at startup so a missing secret stops the app immediately,
    # instead of failing later on the first request.
    settings = get_settings()
    app.state.settings = settings
    app.state.pool = create_pool(settings)
    app.state.pool.open(wait=False)
    app.state.cache = analyses.TTLCache(settings.cache_ttl_seconds)
    app.state.limiter = RateLimiter(settings.reports_rate_limit,
                                    settings.reports_rate_window_seconds)
    yield
    app.state.pool.close()


app = FastAPI(title="CareLens", lifespan=lifespan)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.update(SECURITY_HEADERS)
    if request.url.path == "/" or request.url.path.startswith("/static/"):
        response.headers["Content-Security-Policy"] = DASHBOARD_CSP
    return response


# ------------------------------------------------------------------ health

# Objects the app needs. If one is missing, the database schema is out of date
# (run scripts/db_setup.py) and the app would fail on the first real request.
REQUIRED_OBJECTS = ["reporting.dataset_info", "reporting.population_overview", "app.reports"]


@app.get("/health")
def health(request: Request):
    try:
        with request.app.state.pool.connection(timeout=3) as conn:
            missing = [name for name in REQUIRED_OBJECTS
                       if conn.execute("SELECT to_regclass(%s)", [name]).fetchone()[0] is None]
    except Exception:  # any failure means "not ready"; details go to the log, not the client
        log.exception("health check: database unavailable")
        return JSONResponse(status_code=503, content={"status": "degraded",
                                                      "database": "unavailable"})
    if missing:
        log.error("health check: schema out of date, missing %s", missing)
        return JSONResponse(status_code=503, content={"status": "degraded",
                                                      "database": "schema out of date"})
    return {"status": "ok", "database": "ok"}


# ------------------------------------------------------------------ analyses

@app.get("/api/analyses")
def list_analyses(request: Request):
    pool = request.app.state.pool

    def compute():
        meta = analyses.view_metadata(pool)
        return {
            "reference_date": analyses.reference_date(pool),
            "analyses": [
                {"id": a.id,
                 "title": meta.get(a.views[0], {}).get("Title", a.id),
                 "question": meta.get(a.views[0], {}).get("Question", ""),
                 "tables": list(a.views)}
                for a in analyses.ANALYSES
            ],
        }
    return request.app.state.cache.get_or_set("__list__", compute)


def _analysis_or_404(analysis_id: str) -> analyses.AnalysisDef:
    analysis = analyses.BY_ID.get(analysis_id)
    if analysis is None:
        raise HTTPException(status_code=404, detail="Unknown analysis.")
    return analysis


def _load(request: Request, analysis: analyses.AnalysisDef) -> dict:
    pool = request.app.state.pool
    return request.app.state.cache.get_or_set(
        analysis.id, lambda: analyses.load_analysis(pool, analysis))


@app.get("/api/analyses/{analysis_id}")
def get_analysis(analysis_id: str, request: Request):
    return _load(request, _analysis_or_404(analysis_id))


# ------------------------------------------------------------------ reports

class ReportRequest(BaseModel):
    analysis_id: str = Field(pattern=r"^[a-z-]{1,40}$")


@app.post("/api/reports", status_code=201, response_model=ReportRecord)
def create_report(body: ReportRequest, request: Request):
    # Rate limit first, so failed key guesses also count against the limit.
    request.app.state.limiter.check(client_ip(request))
    check_api_key(request)
    analysis = _analysis_or_404(body.analysis_id)
    return reports.create_report(request.app.state.pool, _load(request, analysis))


@app.get("/api/reports/{report_id}", response_model=ReportRecord)
def get_report(report_id: UUID, request: Request):
    record = reports.get_report(request.app.state.pool, report_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Report not found.")
    return record


# ------------------------------------------------------------------ dashboard

@app.get("/", include_in_schema=False)
def dashboard():
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
