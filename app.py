# app.py — JDAS backend (serve index.html + Dataverse API)
from __future__ import annotations
import os, time
from pathlib import Path
from typing import Dict, List, Optional, Any, Sequence
from urllib.parse import urlencode

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

# -------------------------
# App & paths
# -------------------------
BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
TEMPLATES_DIR = BASE_DIR / "templates"

app = FastAPI(title="JDAS Dataverse API", version="0.4.0")

# static
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# -------------------------
# Env & constants
# -------------------------
load_dotenv()

TENANT_ID     = os.getenv("TENANT_ID")      or os.getenv("AZURE_TENANT_ID")
CLIENT_ID     = os.getenv("CLIENT_ID")      or os.getenv("AZURE_CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")  or os.getenv("AZURE_CLIENT_SECRET")

# Accept both keys, prefer DATAVERSE_BASE_URL
DATAVERSE_BASE_URL = (
    os.getenv("DATAVERSE_BASE_URL")
    or os.getenv("DATAVERSE_URL")
    or os.getenv("DATAVERSE_API_BASE")
    or ""
).rstrip("/")

ALLOW_ORIGINS = os.getenv("ALLOW_ORIGINS", "*").split(",")

DATAVERSE_ENABLED = all([TENANT_ID, CLIENT_ID, CLIENT_SECRET, DATAVERSE_BASE_URL])

TOKEN_URL = f"https://login.microsoftonline.com/{TENANT_ID}/oauth2/v2.0/token" if DATAVERSE_ENABLED else None
SCOPE     = f"{DATAVERSE_BASE_URL}/.default" if DATAVERSE_ENABLED else None
API_BASE  = f"{DATAVERSE_BASE_URL}/api/data/v9.2" if DATAVERSE_ENABLED else None

# CORS (Wix/embedded)
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOW_ORIGINS if ALLOW_ORIGINS != ["*"] else ["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -------------------------
# Health & info
# -------------------------
@app.get("/health")
def health_root():
    return {"ok": True, "dataverse": DATAVERSE_ENABLED}

@app.get("/api/health")
def health_api():
    return {"ok": True, "dataverse": DATAVERSE_ENABLED}

@app.get("/info")
def root_info():
    return {
        "service": "JDAS Dataverse API",
        "docs": "/docs",
        "health": "/health",
        "dataverse": DATAVERSE_ENABLED,
        "base_url": DATAVERSE_BASE_URL,
    }

# -------------------------
# Home (serves your dashboard)
# -------------------------
@app.get("/", response_class=HTMLResponse)
def home():
    idx = TEMPLATES_DIR / "index.html"
    if idx.exists():
        return FileResponse(str(idx))
    return HTMLResponse("<h1>JDAS</h1><p>templates/index.html not found.</p>", status_code=200)

# ============================================================
#                Dataverse client (helper layer)
# ============================================================
_token_cache: Dict[str, Any] = {"value": None, "exp": 0.0}
_SKEW = 60  # seconds

def _assert_cfg():
    if not DATAVERSE_ENABLED:
        raise HTTPException(503, "Dataverse env not configured")

def _token_expiring_soon() -> bool:
    return not _token_cache["value"] or (time.time() > float(_token_cache["exp"]) - _SKEW)

def _get_token() -> str:
    _assert_cfg()
    if not _token_expiring_soon():
        return _token_cache["value"]

    data = {
        "grant_type": "client_credentials",
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "scope": f"{DATAVERSE_BASE_URL}/.default",
    }
    with httpx.Client(timeout=30) as c:
        r = c.post(TOKEN_URL, data=data)
    if r.status_code != 200:
        raise HTTPException(r.status_code, f"Token error: {r.text[:300]}")
    j = r.json()
    _token_cache["value"] = j["access_token"]
    _token_cache["exp"] = time.time() + int(j.get("expires_in", 3600))
    return _token_cache["value"]

def _dv_headers() -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {_get_token()}",
        "Accept": "application/json;odata.metadata=none",
        "OData-MaxVersion": "4.0",
        "OData-Version": "4.0",
        "Prefer": "odata.maxpagesize=5000",
    }

def dv_paged_get(path_or_url: str) -> List[dict]:
    _assert_cfg()
    url = path_or_url if path_or_url.startswith("http") else f"{API_BASE}/{path_or_url}"
    rows: List[dict] = []
    pages = 0
    with httpx.Client(timeout=60) as c:
        while url and pages < 50:
            r = c.get(url, headers=_dv_headers())
            if r.status_code != 200:
                raise HTTPException(r.status_code, f"Dataverse GET failed: {r.text[:500]}")
            j = r.json()
            rows.extend(j.get("value", []))
            url = j.get("@odata.nextLink")
            pages += 1
    return rows

def build_select(entity_set: str, columns: Sequence[str], orderby: Optional[str], top: int, extra: Optional[str]) -> str:
    params = {"$top": str(top)}
    if columns:
        params["$select"] = ",".join(columns)
    if orderby:
        params["$orderby"] = orderby
    qs = urlencode(params)
    return f"{entity_set}?{qs}" + (f"&{extra}" if extra else "")

def resolve_entity_set_from_logical(logical_name: str) -> str:
    """Resolve LogicalName -> EntitySetName (once)."""
    _assert_cfg()
    url = f"{API_BASE}/EntityDefinitions(LogicalName='{logical_name}')?$select=EntitySetName"
    with httpx.Client(timeout=30) as c:
        r = c.get(url, headers=_dv_headers())
    if r.status_code != 200:
        raise HTTPException(500, f"Metadata lookup failed for {logical_name}: {r.text[:400]}")
    es = r.json().get("EntitySetName")
    if not es:
        raise HTTPException(500, f"No EntitySetName for {logical_name}")
    return es

# ============================================================
# ============================================================
# TABLE CONFIG (corrected logical names from your screenshots)
# ============================================================
TABLES: List[Dict[str, Any]] = [
    # U.S. Trade
    {"name": "Trade Deficit Annual",     "logical": "cred8_tradedeficitannual",   "path": "/api/trade-deficit-annual",   "columns": [], "map_to": [], "orderby": "cred8_year desc"},
    {"name": "Tariff % by Country",      "logical": "cred8_tariffbycountry",      "path": "/api/tariff-by-country",      "columns": [], "map_to": [], "orderby": "cred8_country asc"},
    {"name": "Tariff By Item",           "logical": "jdas_tariffbyitem",          "path": "/api/tariff-by-item",         "columns": [], "map_to": [], "orderby": ""},
    {"name": "Trade Deals",              "logical": "cred8_tradedeal",            "path": "/api/trade-deals",            "columns": [], "map_to": [], "orderby": ""},
    {"name": "Tariff Revenue",           "logical": "Cred8_tariffrevenue",        "path": "/api/tariff-revenue",         "columns": [], "map_to": [], "orderby": "cred8_month desc"},

    # KPI / Key Stats
    {"name": "Unemployment Rate",        "logical": "Cred8_unemploymentrate",     "path": "/api/unemployment-rate",      "columns": [], "map_to": [], "orderby": "cred8_month desc"},
    {"name": "Inflation Rate",           "logical": "cred8_inflationrate",        "path": "/api/inflation-rate",         "columns": [], "map_to": [], "orderby": "cred8_month desc"},
    {"name": "Economic Indicator (A)",   "logical": "jdas_economicindicator",     "path": "/api/economic-indicator",     "columns": [], "map_to": [], "orderby": ""},
    {"name": "Manufacturing PMI Report", "logical": "jdas_manufacturingpmireport","path": "/api/manufacturing-pmi-report","columns": [], "map_to": [], "orderby": "jdas_month desc"},
    # You showed this as **Claim Report** (weekly claims) => logical: jdas_claimreport
    {"name": "Weekly Claims Report",     "logical": "jdas_claimreport",           "path": "/api/weekly-claims-report",   "columns": [], "map_to": [], "orderby": "jdas_weekending desc"},
    {"name": "Consumer Confidence Index","logical": "jdas_consumerconfidenceindex","path": "/api/consumer-confidence-index","columns": [], "map_to": [], "orderby": "jdas_month desc"},
    {"name": "Treasury Yields Record",   "logical": "jdas_treasuryyieldrecord",   "path": "/api/treasury-yields-record", "columns": [], "map_to": [], "orderby": "jdas_month desc"},
    {"name": "Economic Growth Report",   "logical": "jdas_economicgrowthreport",  "path": "/api/economic-growth-report", "columns": [], "map_to": [], "orderby": "jdas_quarter desc"},
    {"name": "Economic Indicator (B)",   "logical": "jdas_economicindictator1",   "path": "/api/economic-indicator-1",   "columns": [], "map_to": [], "orderby": ""},

    # Labor & Society
    {"name": "Publicly Annouced Revenue Loss", "logical": "Cred8_publiclyannoucedrevenueloss", "path": "/api/publicly-annouced-revenue-loss", "columns": [], "map_to": [], "orderby": "cred8_amountloss desc"},
    # Typo fixed: layoffannoucement → layoffannouncement
    {"name": "Layoff Announcement",      "logical": "jdas_layoffannouncement",    "path": "/api/layoff-announcement",    "columns": [], "map_to": [], "orderby": "jdas_announcementdate desc"},
    {"name": "Acquisition Deal",         "logical": "jdas_acquisitiondeal",       "path": "/api/acquisition-deal",       "columns": [], "map_to": [], "orderby": "jdas_announcedate desc"},
    {"name": "Bankruptcy Log",           "logical": "Cred8_bankruptcylog",        "path": "/api/bankruptcies",           "columns": [], "map_to": [], "orderby": "cred8_datelogged desc"},
    {"name": "Layoffs (Tracking)",       "logical": "jdas_layoffs",               "path": "/api/layoffs",                "columns": [], "map_to": [], "orderby": "jdas_date desc"},

    # Environmental & Energy
    {"name": "Environmental Regulation", "logical": "jdas_environmentalregulation","path": "/api/environmental-regulation", "columns": [], "map_to": [], "orderby": ""},
    {"name": "Environmental Policy",     "logical": "jdas_environmentalpolicy",   "path": "/api/environmental-policy",    "columns": [], "map_to": [], "orderby": ""},
    # You confirmed the real logical name here:
    {"name": "Infrastructure Investment","logical": "jdas_infrastructureinvestment","path": "/api/infrastructure-investment","columns": [], "map_to": [], "orderby": ""},

    # Global Events
    {"name": "Corporate SpinOff",        "logical": "jdas_corporatespinoff",      "path": "/api/corporate-spinoff",      "columns": [], "map_to": [], "orderby": ""},
    # Underscore fixed: jdas_conflictrecord
    {"name": "Conflict Record",          "logical": "jdas_conflictrecord",        "path": "/api/conflict-record",        "columns": [], "map_to": [], "orderby": ""},
    {"name": "Global Natural Disasters", "logical": "jdas_globalnaturaldisasters","path": "/api/global-natural-disasters","columns": [], "map_to": [], "orderby": ""},
]

# Cache resolved EntitySetNames so we don’t keep hitting metadata
_entityset_cache: Dict[str, str] = {}

def _ensure_entity_set(logical: str) -> str:
    """Resolve & cache the EntitySetName for a given logical name."""
    if logical in _entityset_cache:
        return _entityset_cache[logical]
    es = resolve_entity_set_from_logical(logical)
    _entityset_cache[logical] = es
    return es

def _shape_rows(rows: List[dict], columns: Sequence[str], keys: Sequence[str]) -> List[dict]:
    """If columns are provided, project/rename; otherwise return raw rows (discovery mode)."""
    if not columns:
        return rows
    out: List[dict] = []
    for r in rows:
        shaped = {}
        for c, k in zip(columns, keys or columns):
            shaped[k or c] = r.get(c)
        out.append(shaped)
    return out

def _make_handler(entity_set: Optional[str], logical: Optional[str],
                  columns: Sequence[str], keys: Sequence[str],
                  default_order: Optional[str]):
    """Factory that returns a FastAPI view for one table."""
    def handler(
        top: int = Query(5000, ge=1, le=50000, description="$top limit"),
        orderby: Optional[str] = Query(None, description="Override $orderby"),
        extra: Optional[str] = Query(None, description="Append extra OData (advanced)"),
    ):
        _assert_cfg()
        es = entity_set or _ensure_entity_set(logical or "")
        query = build_select(es, columns, orderby or default_order, top=top, extra=extra)
        rows = dv_paged_get(query)
        return JSONResponse(content=_shape_rows(rows, columns, keys))
    return handler

# Wire up one GET endpoint per table
for cfg in TABLES:
    app.get(cfg["path"], name=cfg["name"])(
        _make_handler(
            cfg.get("entity_set"),
            cfg.get("logical"),
            cfg.get("columns", []),
            cfg.get("map_to", []),
            cfg.get("orderby")
        )
    )

# ------------------------------------------------------------
# Utility endpoints (handy for debugging + discovery)
# ------------------------------------------------------------
@app.get("/api/metadata", summary="List available API resources")
def list_resources():
    return [
        {
            "name": t["name"],
            "path": t["path"],
            "logical": t.get("logical", ""),
            "entity_set": _entityset_cache.get(t.get("logical", ""), ""),
            "orderby": t.get("orderby", ""),
            "columns": t.get("columns", []),
        }
        for t in TABLES
    ]

@app.get("/api/describe", summary="Resolve entity set & return one sample row")
def describe(logical: str):
    es = _ensure_entity_set(logical)
    rows = dv_paged_get(f"{es}?$top=1")
    return {"logical": logical, "entity_set": es, "sample": rows[:1]}

@app.get("/api/search-entities", summary="Search Dataverse entities by text")
def search_entities(q: str):
    """Quick helper: search metadata for logical/schema matches."""
    _assert_cfg()
    # Search EntityDefinitions by contains(LogicalName,'q') OR contains(SchemaName,'q')
    # and return a few useful fields.
    url = (
        f"{API_BASE}/EntityDefinitions"
        f"?$select=LogicalName,SchemaName,EntitySetName"
        f"&$filter=contains(LogicalName,'{q}') or contains(SchemaName,'{q}')"
        f"&$top=50"
    )
    with httpx.Client(timeout=30) as c:
        r = c.get(url, headers=_dv_headers())
    if r.status_code != 200:
        raise HTTPException(r.status_code, r.text[:500])
    return r.json().get("value", [])



# -------------------------
# Route factory
# -------------------------
def make_handler(entity_set: Optional[str], logical: Optional[str],
                 cols: List[str], keys: List[str], default_order: Optional[str]):
    resolved: Optional[str] = entity_set  # may be None; we’ll resolve first call

    def handler(
        top: int = Query(5000, ge=1, le=50000, description="$top limit"),
        orderby: Optional[str] = Query(None, description="Override $orderby"),
        extra: Optional[str] = Query(None, description="Append extra OData (advanced)"),
    ):
        _assert_cfg()
        nonlocal resolved
        if not resolved:
            if not logical:
                raise HTTPException(500, "No entity_set or logical provided for this endpoint")
            resolved = resolve_entity_set_from_logical(logical)

        query = build_select(resolved, cols, orderby or default_order, top=top, extra=extra)
        rows = dv_paged_get(query)

        # If columns not specified yet, return raw rows for discovery
        if not cols:
            return JSONResponse(content=rows)

        shaped = [{k: r.get(c) for c, k in zip(cols, keys)} for r in rows]
        return JSONResponse(content=shaped)

    return handler

for cfg in TABLES:
    app.get(cfg["path"], name=cfg["name"])(
        make_handler(
            cfg.get("entity_set"),
            cfg.get("logical"),
            cfg.get("columns", []),
            cfg.get("map_to", []),
            cfg.get("orderby"),
        )
    )

# -------------------------



