# app.py — JDAS backend (serve index.html + Dataverse API)
import os
import time
from pathlib import Path
from typing import Dict, List, Optional, Any
from urllib.parse import urlencode

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

# -------------------------
# App & absolute paths
# -------------------------
BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
TEMPLATES_DIR = BASE_DIR / "templates"

app = FastAPI(title="JDAS Dataverse API", version="0.3.0")

# Serve /static/* from ./static (absolute)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# Serve the SPA/HTML (with a fallback if index is missing)
@app.get("/", response_class=HTMLResponse)
def home():
    index_path = TEMPLATES_DIR / "index.html"
    if index_path.exists():
        return FileResponse(str(index_path))
    return HTMLResponse("<h1>JDAS</h1><p>templates/index.html not found.</p>", status_code=200)

# -------------------------
# Env & constants (normalized)
# -------------------------
load_dotenv()

# Accept either your names or the AZURE_*/DATAVERSE_API_BASE variants
TENANT_ID     = os.getenv("TENANT_ID")      or os.getenv("AZURE_TENANT_ID")
CLIENT_ID     = os.getenv("CLIENT_ID")      or os.getenv("AZURE_CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")  or os.getenv("AZURE_CLIENT_SECRET")

DATAVERSE_URL = os.getenv("DATAVERSE_URL")  or os.getenv("DATAVERSE_API_BASE")
if DATAVERSE_URL:
    DATAVERSE_URL = DATAVERSE_URL.rstrip("/")
ALLOW_ORIGINS = os.getenv("ALLOW_ORIGINS", "*").split(",")

DATAVERSE_ENABLED = all([TENANT_ID, CLIENT_ID, CLIENT_SECRET, DATAVERSE_URL])

TOKEN_URL = f"https://login.microsoftonline.com/{TENANT_ID}/oauth2/v2.0/token" if DATAVERSE_ENABLED else None
SCOPE     = f"{DATAVERSE_URL}/.default" if DATAVERSE_ENABLED else None
API_BASE  = f"{DATAVERSE_URL}/api/data/v9.2" if DATAVERSE_ENABLED else None

# CORS for Wix / embedded dashboards
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
@app.get("/health", summary="Simple health check")
def health_root():
    return {"ok": True, "dataverse": DATAVERSE_ENABLED}

@app.get("/api/health", summary="Health under /api")
def health_api():
    return {"ok": True, "dataverse": DATAVERSE_ENABLED}

@app.get("/info", summary="Service info")
def root_info():
    return {
        "service": "JDAS Dataverse API",
        "docs": "/docs",
        "health": "/health",
        "dataverse": DATAVERSE_ENABLED,
    }
# --- add near your other imports ---
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

app = FastAPI()

# Static + templates (adjust paths if yours differ)
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# ----- health (support both) -----
@app.get("/health")
@app.get("/api/health")
def health():
    return {"ok": True}

# ----- home -----
@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

# ===== TRADE =====
@app.get("/api/trade-deficit-annual")
def trade_deficit_annual():
    return []  # TODO: fill with Dataverse rows

@app.get("/api/tariff-by-country")
def tariff_by_country():
    return []

@app.get("/api/tariff-by-item")
def tariff_by_item():
    return []

@app.get("/api/trade-deals")
def trade_deals():
    return []

@app.get("/api/tariff-revenue")
def tariff_revenue():
    return []

# ===== KPI =====
@app.get("/api/unemployment-rate")
def unemployment_rate():
    return []

@app.get("/api/inflation-rate")
def inflation_rate():
    return []

@app.get("/api/economic-indicator")
def economic_indicator_a():
    return []

@app.get("/api/manufacturing-pmi-report")
def manufacturing_pmi():
    return []

@app.get("/api/weekly-claims-report")
def weekly_claims():
    return []

@app.get("/api/consumer-confidence-index")
def consumer_confidence():
    return []

@app.get("/api/treasury-yields-record")
def treasury_yields():
    return []

@app.get("/api/economic-growth-report")
def economic_growth():
    return []

@app.get("/api/economic-indicator-1")
def economic_indicator_b():
    return []

# ===== GLOBAL =====
@app.get("/api/corporate-spinoff")
def corporate_spinoff():
    return []

@app.get("/api/conflict-record")
def conflict_record():
    return []

@app.get("/api/global-natural-disasters")
def global_disasters():
    return []

# ===== LABOR & SOCIETY =====
@app.get("/api/publicly-annouced-revenue-loss")  # note: 'annouced' matches your front-end spelling
def public_revenue_loss():
    return []

@app.get("/api/layoff-announcement")
def layoff_announcement():
    return []

@app.get("/api/acquisition-deal")
def acquisition_deal():
    return []

@app.get("/api/bankruptcies")
def bankruptcies():
    return []

@app.get("/api/layoffs")
def layoffs():
    return []

# ===== ENVIRONMENTAL & ENERGY =====
@app.get("/api/environmental-regulation")
def env_regulation():
    return []

@app.get("/api/environmental-policy")
def env_policy():
    return []

@app.get("/api/infrastructure-investment")
def infrastructure_investment():
    return []

# -------------------------
# Dataverse helpers (guarded) — async httpx + caching + OData headers
# -------------------------
_token_cache: Dict[str, str] = {}
_token_expiry_ts: float = 0.0
_SKEW = 60  # seconds
_entityset_cache: Dict[str, str] = {}  # logical -> EntitySetName

def _assert_cfg():
    if not DATAVERSE_ENABLED:
        raise HTTPException(503, "Dataverse env not configured")

async def fetch_access_token() -> str:
    _assert_cfg()
    data = {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "grant_type": "client_credentials",
        "scope": SCOPE,
    }
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post(TOKEN_URL, data=data)
        if r.status_code != 200:
            raise HTTPException(500, f"Token error: {r.text[:500]}")
        j = r.json()
        tok = j["access_token"]
        expires_in = int(j.get("expires_in", 3600))
        global _token_expiry_ts
        _token_expiry_ts = time.time() + max(60, expires_in - _SKEW)
        _token_cache["token"] = tok
        return tok

async def get_access_token() -> str:
    _assert_cfg()
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
    """
    Optional dynamic resolution: pass logical name to get EntitySetName.
    Caches results.
    """
    _assert_cfg()
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
    _assert_cfg()
    async def _run(url: str, headers: Dict[str, str]) -> httpx.Response:
        async with httpx.AsyncClient(timeout=60) as c:
            return await c.get(url, headers=headers)

    next_url = path_or_url if path_or_url.startswith("http") else f"{API_BASE}/{path_or_url}"
    token = await get_access_token()
    headers = build_headers(token)
    out: List[dict] = []

    while True:
        r = await _run(next_url, headers)
        if r.status_code == 401:  # token refresh path
            token = await fetch_access_token()
            headers = build_headers(token)
            r = await _run(next_url, headers)
        if r.status_code != 200:
            raise HTTPException(r.status_code, r.text)

        data = r.json()
        out.extend(data.get("value", []))
        next_link = data.get("@odata.nextLink")
        if not next_link:
            break
        next_url = next_link

    return out

# $select is optional — when columns are [], we skip $select and return raw rows
def build_select(
    entity_set: str,
    columns: List[str],
    orderby: Optional[str] = None,
    top: int = 5000,
    extra: Optional[str] = None,
) -> str:
    params = {"$top": str(top)}
    if columns:
        params["$select"] = ",".join(columns)
    if orderby:
        params["$orderby"] = orderby
    qs = urlencode(params)
    return f"{entity_set}?{qs}" + (f"&{extra}" if extra else "")

# -------------------------
# TABLE CONFIG
# Supports either:
#   - entity_set: "cred8_bankruptcylogs"
#   - logical:    "cred8_bankruptcylog"  (auto-resolves EntitySetName)
# Columns can be [] while you verify actual field names.
# -------------------------
TABLES: List[Dict[str, Any]] = [
    # ── U.S. Trade ────────────────────────────────────────────────────────────
    {
        "name": "Trade Deficit Annual",
        "logical": "cred8_tradedeficitannual",
        "path": "/api/trade-deficit-annual",
        "columns": [], "map_to": [], "orderby": "cred8_year desc"
    },
    {
        "name": "Tariff % by Country",
        "logical": "cred8_tariffbycountry",
        "path": "/api/tariff-by-country",
        "columns": [], "map_to": [], "orderby": "cred8_country asc"
    },
    {
        "name": "Tariff By Item",
        "logical": "jdas_tariffbyitem",
        "path": "/api/tariff-by-item",
        "columns": [], "map_to": [], "orderby": ""
    },
    {
        "name": "Trade Deals",
        "logical": "cred8_tradedeal",
        "path": "/api/trade-deals",
        "columns": [], "map_to": [], "orderby": ""
    },
    {
    "name": "Tariff Revenue",
    "logical": "cred8_tariffrevenue",
    "entity_set": "cred8_tariffrevenues",      # ← verified set
    "path": "/api/tariff-revenue",
    "columns": [], "map_to": [], "orderby": ""
 },

    # ── KPI / Key Stats ───────────────────────────────────────────────────────
    {
   "name": "Unemployment Rate",
    "logical": "cred8_unemploymentrate",
    "entity_set": "cred8_unemploymentrates",   # ← verified set
    "path": "/api/unemployment-rate",
    "columns": [], "map_to": [], "orderby": ""
    },
    {
    "name": "Inflation Rate",
    "logical": "cred8_inflationrate",
    "entity_set": "cred8_inflationrates",      # ← verified set
    "path": "/api/inflation-rate",
    "columns": [], "map_to": [], "orderby": ""
    },
    {
        "name": "Economic Indicator (A)",
        "logical": "jdas_economicindicator",     # TODO verify exact logical name if needed
        "path": "/api/economic-indicator",
        "columns": [], "map_to": [], "orderby": ""
    },
    {
        "name": "Manufacturing PMI Report",
        "logical": "jdas_manufacturingpmireport",  # TODO verify
        "path": "/api/manufacturing-pmi-report",
        "columns": [], "map_to": [], "orderby": "jdas_month desc"
    },
    {
        "name": "Weekly Claims Report",
        "logical": "jdas_weeklyclaimsreport",    # TODO verify
        "path": "/api/weekly-claims-report",
        "columns": [], "map_to": [], "orderby": "jdas_weekending desc"
    },
    {
        "name": "Consumer Confidence Index",
        "logical": "jdas_consumerconfidenceindex",  # TODO verify
        "path": "/api/consumer-confidence-index",
        "columns": [], "map_to": [], "orderby": "jdas_month desc"
    },
    {
        "name": "Treasury Yields Record",
        "logical": "jdas_treasuryyieldrecord",   # TODO verify
        "path": "/api/treasury-yields-record",
        "columns": [], "map_to": [], "orderby": "jdas_month desc"
    },
    {
        "name": "Economic Growth Report",
        "logical": "jdas_economicgrowthreport",  # TODO verify
        "path": "/api/economic-growth-report",
        "columns": [], "map_to": [], "orderby": "jdas_quarter desc"
    },
    {
        "name": "Economic Indicator (B)",
        "logical": "jdas_economicindictator1",   # NOTE: 'indictator' spelling from source
        "path": "/api/economic-indicator-1",
        "columns": [], "map_to": [], "orderby": ""
    },

    # ── Labor & Society ───────────────────────────────────────────────────────
    {
        "name": "Publicly Annouced Revenue Loss",
        "logical": "cred8_publiclyannoucedrevenueloss",  # NOTE: spelling/caps kept
        "path": "/api/publicly-annouced-revenue-loss",
        "columns": [], "map_to": [], "orderby": "cred8_amountloss desc"
    },
    {
    "name": "Layoff Tracking",
    "logical": "cred8_layoffannouncement",     # ← verified logical
    "entity_set": "cred8_layoffannouncements", # ← verified set
    "path": "/api/layoff-announcement",
    "columns": [], "map_to": [], "orderby": ""
    },
    {
        "name": "Acquisition Deal",
        "logical": "jdas_acquisitiondeal",
        "path": "/api/acquisition-deal",
        "columns": [], "map_to": [], "orderby": "jdas_announcedate desc"
    },
    {
    "name": "Bankruptcy Log",
    "logical": "cred8_bankruptcylog",
    "entity_set": "cred8_bankruptcylogs",      # ← verified set
    "path": "/api/bankruptcies",
    "columns": [], "map_to": [], "orderby": ""
    },

    # ── Environmental & Energy ────────────────────────────────────────────────
    {
        "name": "Environmental Regulation",
        "logical": "jdas_environmentalregulation",
        "path": "/api/environmental-regulation",
        "columns": [], "map_to": [], "orderby": ""
    },
    {
        "name": "Environmental Policy",
        "logical": "Jdas_environmentalpolicy",  # NOTE: capital J as provided
        "path": "/api/environmental-policy",
        "columns": [], "map_to": [], "orderby": ""
    },
    {
        "name": "Infrastructure Investment",
        "logical": "infrastructure_investment",  # NOTE: schema had no prefix; inferred
        "path": "/api/infrastructure-investment",
        "columns": [], "map_to": [], "orderby": ""
    },

    # ── Global Events ─────────────────────────────────────────────────────────
    {
        "name": "Corporate SpinOff",
        "logical": "jdas_corporatespinoff",
        "path": "/api/corporate-spinoff",
        "columns": [], "map_to": [], "orderby": ""
    },
    {
        "name": "Conflict Record",
        "logical": "jdasconflictrecord",  # NOTE: no underscore per source
        "path": "/api/conflict-record",
        "columns": [], "map_to": [], "orderby": ""
    },
    {
        "name": "Global Natural Disasters",
        "logical": "jdas_globalnaturaldisasters",  # source used camel; logicals typically lowercase
        "path": "/api/global-natural-disasters",
        "columns": [], "map_to": [], "orderby": ""
    },
]

# -------------------------
# Route factory (supports entity_set OR logical; returns raw rows if no columns)
# -------------------------
def make_handler(entity_set: Optional[str], logical: Optional[str],
                 cols: List[str], keys: List[str], default_order: Optional[str]):
    _resolved_entity_set: Optional[str] = None

    async def handler(
        top: int = Query(5000, ge=1, le=50000, description="$top limit"),
        orderby: Optional[str] = Query(None, description="Override $orderby"),
        extra: Optional[str] = Query(None, description="Extra OData query string to append (advanced)"),
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

        query = build_select(es, cols, orderby or default_order, top=top, extra=extra)
        rows = await dv_paged_get(query)

        # If columns aren't specified yet, return raw rows to aid discovery
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
# Metadata & describe utilities
# -------------------------
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

