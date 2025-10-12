# app.py — JDAS backend (serve index.html + Dataverse API)
import os, time
from pathlib import Path
from typing import Dict, List, Optional, Any
from urllib.parse import urlencode

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

# =========================
# App & absolute paths
# =========================
BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
TEMPLATES_DIR = BASE_DIR / "templates"

app = FastAPI(title="JDAS Dataverse API", version="0.4.0")

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# Serve SPA/HTML with graceful fallback
@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    index_path = TEMPLATES_DIR / "index.html"
    if index_path.exists():
        return templates.TemplateResponse("index.html", {"request": request})
    return HTMLResponse("<h1>JDAS</h1><p>templates/index.html not found.</p>", status_code=200)

# =========================
# Env & constants
# =========================
load_dotenv()

TENANT_ID     = os.getenv("TENANT_ID")      or os.getenv("AZURE_TENANT_ID")
CLIENT_ID     = os.getenv("CLIENT_ID")      or os.getenv("AZURE_CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")  or os.getenv("AZURE_CLIENT_SECRET")
DATAVERSE_URL = (os.getenv("DATAVERSE_URL") or os.getenv("DATAVERSE_API_BASE") or "").rstrip("/")

ALLOW_ORIGINS = [o.strip() for o in os.getenv("ALLOW_ORIGINS", "*").split(",")]

DATAVERSE_ENABLED = all([TENANT_ID, CLIENT_ID, CLIENT_SECRET, DATAVERSE_URL])

TOKEN_URL = f"https://login.microsoftonline.com/{TENANT_ID}/oauth2/v2.0/token" if DATAVERSE_ENABLED else ""
SCOPE     = f"{DATAVERSE_URL}/.default" if DATAVERSE_ENABLED else ""
API_BASE  = f"{DATAVERSE_URL}/api/data/v9.2" if DATAVERSE_ENABLED else ""

# CORS (Wix + local preview)
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOW_ORIGINS if ALLOW_ORIGINS != ["*"] else ["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =========================
# Health & info
# =========================
@app.get("/health")
@app.get("/api/health")
def health():
    return {"ok": True, "dataverse": DATAVERSE_ENABLED, "api_base": API_BASE or None}

@app.get("/info")
def info():
    return {"service": "JDAS Dataverse API", "docs": "/docs", "health": "/health", "dataverse": DATAVERSE_ENABLED}

# =========================
# Dataverse helpers
# =========================
_token_cache: Dict[str, str] = {}
_token_expiry_ts: float = 0.0
_SKEW = 60  # seconds
_entityset_cache: Dict[str, str] = {}  # logical -> EntitySetName

def _assert_cfg():
    if not DATAVERSE_ENABLED:
        raise HTTPException(503, "Dataverse env not configured")

async def fetch_access_token() -> str:
    _assert_cfg()
    data = {"client_id": CLIENT_ID, "client_secret": CLIENT_SECRET, "grant_type": "client_credentials", "scope": SCOPE}
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post(TOKEN_URL, data=data)
    if r.status_code != 200:
        raise HTTPException(502, f"Token error: {r.text[:500]}")
    j = r.json()
    tok = j["access_token"]
    expires_in = int(j.get("expires_in", 3600))
    global _token_expiry_ts
    _token_expiry_ts = time.time() + max(60, expires_in - _SKEW)
    _token_cache["token"] = tok
    return tok

async def get_access_token() -> str:
    tok = _token_cache.get("token")
    if not tok or time.time() >= _token_expiry_ts:
        return await fetch_access_token()
    return tok

def build_headers(token: str) -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "OData-MaxVersion": "4.0",
        "OData-Version": "4.0",
        "Prefer": "odata.maxpagesize=5000",
    }

async def resolve_entity_set_from_logical(logical_name: str) -> str:
    """Resolve Dataverse EntitySetName for a logical table name (cached)."""
    key = logical_name.strip()
    if key in _entityset_cache:
        return _entityset_cache[key]
    token = await get_access_token()
    headers = build_headers(token)
    url = f"{API_BASE}/EntityDefinitions(LogicalName='{key}')?$select=EntitySetName"
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.get(url, headers=headers)
    if r.status_code != 200:
        raise HTTPException(500, f"Metadata lookup failed for {key}: {r.text[:500]}")
    entity_set = r.json().get("EntitySetName")
    if not entity_set:
        raise HTTPException(500, f"No EntitySetName for {key}")
    _entityset_cache[key] = entity_set
    return entity_set

async def dv_paged_get(path_or_url: str) -> List[dict]:
    """GET with paging; accepts path like 'cred8_bankruptcylogs?$top=200' or a full URL."""
    next_url = path_or_url if path_or_url.startswith("http") else f"{API_BASE}/{path_or_url}"
    token = await get_access_token()
    headers = build_headers(token)

    async with httpx.AsyncClient(timeout=60) as c:
        out: List[dict] = []
        while True:
            r = await c.get(next_url, headers=headers)
            if r.status_code == 401:  # refresh token once
                token = await fetch_access_token()
                headers = build_headers(token)
                r = await c.get(next_url, headers=headers)
            if r.status_code != 200:
                raise HTTPException(r.status_code, r.text)
            data = r.json()
            out.extend(data.get("value", []))
            next_link = data.get("@odata.nextLink")
            if not next_link:
                break
            next_url = next_link
    return out

def build_select(entity_set: str, columns: List[str], orderby: Optional[str] = None, top: int = 5000, extra: Optional[str] = None) -> str:
    params = {"$top": str(top)}
    if columns:
        params["$select"] = ",".join(columns)
    if orderby:
        params["$orderby"] = orderby
    qs = urlencode(params)
    return f"{entity_set}?{qs}" + (f"&{extra}" if extra else "")

# =========================
# TABLE CONFIG (focus: 10 tables you flagged)
# =========================
TABLES: List[Dict[str, Any]] = [
    # ----- Trade -----
    {"name": "Tariff By Item", "logical": "jdas_tariffbyitem", "path": "/api/tariff-by-item", "columns": [], "map_to": [], "orderby": ""},
    {"name": "Tariff Revenue", "logical": "cred8_tariffrevenue", "entity_set": "cred8_tariffrevenues", "path": "/api/tariff-revenue", "columns": [], "map_to": [], "orderby": ""},

    # ----- KPI / Indicators -----
    {"name": "Unemployment Rate", "logical": "cred8_unemploymentrate", "entity_set": "cred8_unemploymentrates", "path": "/api/unemployment-rate", "columns": [], "map_to": [], "orderby": ""},
    {"name": "What is Economic Indicator (A)", "logical": "jdas_economicindicator", "path": "/api/economic-indicator", "columns": [], "map_to": [], "orderby": ""},
    {"name": "Weekly Claims report", "logical": "jdas_weeklyclaimsreport", "path": "/api/weekly-claims-report", "columns": [], "map_to": [], "orderby": ""},
    {"name": "Economic Indicator (B)", "logical": "jdas_economicindictator1", "path": "/api/economic-indicator-1", "columns": [], "map_to": [], "orderby": ""},

    # ----- Labor & Society -----
    {"name": "Publicly Announced Revenue Loss", "logical": "cred8_publiclyannoucedrevenueloss", "path": "/api/publicly-annouced-revenue-loss", "columns": [], "map_to": [], "orderby": ""},
    {"name": "Acquisition Deal", "logical": "jdas_acquisitiondeal", "path": "/api/acquisition-deal", "columns": [], "map_to": [], "orderby": ""},
    {"name": "Bankruptcy Log", "logical": "cred8_bankruptcylog", "entity_set": "cred8_bankruptcylogs", "path": "/api/bankruptcies", "columns": [], "map_to": [], "orderby": ""},
    {"name": "Layoff Tracking", "logical": "cred8_layoffannouncement", "entity_set": "cred8_layoffannouncements", "path": "/api/layoff-announcement", "columns": [], "map_to": [], "orderby": ""},
]

# =========================
# Route factory (entity_set OR logical) — always returns {"data":[...]}
# =========================
def make_handler(entity_set: Optional[str], logical: Optional[str], cols: List[str], keys: List[str], default_order: Optional[str]):
    _resolved_entity_set: Optional[str] = None

    async def handler(
        top: int = Query(5000, ge=1, le=50000, description="$top limit"),
        orderby: Optional[str] = Query(None, description="Override $orderby"),
        extra: Optional[str] = Query(None, description="Extra OData query string to append (advanced)"),
        select: Optional[str] = Query(None, description="Comma-separated column list to override server-side columns"),
    ):
        _assert_cfg()
        nonlocal _resolved_entity_set

        if entity_set:
            es = entity_set
        else:
            if not logical:
                raise HTTPException(500, "No entity_set or logical provided for this endpoint")
            if _resolved_entity_set is None:
                _resolved_entity_set = await resolve_entity_set_from_logical(logical)
            es = _resolved_entity_set

        # Build query
        final_cols = [c.strip() for c in select.split(",")] if select else cols
        query = build_select(es, final_cols, orderby or (default_order or ""), top=top, extra=extra)

        # Fetch rows; if $orderby is bad, retry once without it so UI isn't blank
        try:
            rows = await dv_paged_get(query)
        except HTTPException as e:
            if e.status_code == 400 and "$orderby" in query:
                safe_query = build_select(es, final_cols, orderby=None, top=top, extra=extra)
                rows = await dv_paged_get(safe_query)
            else:
                raise

        # Shape: if columns defined, map to keys; else return raw rows
        if final_cols and keys:
            shaped = [{k: r.get(c) for c, k in zip(final_cols, keys)} for r in rows]
            return JSONResponse(content={"data": shaped})
        return JSONResponse(content={"data": rows})

    return handler

# Register routes from TABLES
for cfg in TABLES:
    app.get(cfg["path"], name=cfg["name"])(make_handler(
        cfg.get("entity_set"),
        cfg.get("logical"),
        cfg.get("columns", []),
        cfg.get("map_to", []),
        cfg.get("orderby"),
    ))

# =========================
# Metadata utilities
# =========================
@app.get("/api/metadata", summary="List available resources")
async def list_resources():
    return [
        {
            "name": t["name"],
            "path": t["path"],
            "entity_set": t.get("entity_set", ""),
            "logical": t.get("logical", ""),
            "columns": t.get("columns", []),
            "orderby": t.get("orderby", ""),
        }
        for t in TABLES
    ]

@app.get("/api/describe", summary="Resolve entity set & return one sample row")
async def describe(logical: str):
    es = await resolve_entity_set_from_logical(logical)
    rows = await dv_paged_get(f"{es}?$top=1")
    return {"logical": logical, "entity_set": es, "sample": rows[:1]}

