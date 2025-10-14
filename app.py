# app.py — JDAS backend (stable merge)
import os, time, json, asyncio
from datetime import datetime
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

app = FastAPI(title="JDAS Dataverse API", version="0.5.0")

# Serve /static/* from ./static (absolute)
if STATIC_DIR.exists():
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

TENANT_ID     = os.getenv("TENANT_ID")      or os.getenv("AZURE_TENANT_ID")
CLIENT_ID     = os.getenv("CLIENT_ID")      or os.getenv("AZURE_CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")  or os.getenv("AZURE_CLIENT_SECRET")

DATAVERSE_URL = (os.getenv("DATAVERSE_URL") or os.getenv("DATAVERSE_API_BASE") or "").rstrip("/")

ALLOW_ORIGINS = [o.strip() for o in os.getenv("ALLOW_ORIGINS", "*").split(",")]
CACHE_TTL_S   = int(os.getenv("CACHE_TTL_S", "120"))
UPSTREAM_MAX_CONCURRENCY = int(os.getenv("UPSTREAM_MAX_CONCURRENCY", "4"))
HTTP_TIMEOUT_S = float(os.getenv("HTTP_TIMEOUT_S", "15.0"))
MAX_PAGE_TIMEOUT_S = float(os.getenv("MAX_PAGE_TIMEOUT_S", "60.0"))

DATAVERSE_ENABLED = all([TENANT_ID, CLIENT_ID, CLIENT_SECRET, DATAVERSE_URL])
TOKEN_URL = f"https://login.microsoftonline.com/{TENANT_ID}/oauth2/v2.0/token" if DATAVERSE_ENABLED else None
SCOPE     = f"{DATAVERSE_URL}/.default" if DATAVERSE_ENABLED else None
API_BASE  = f"{DATAVERSE_URL}/api/data/v9.2" if DATAVERSE_ENABLED else None

# CORS for Wix / embedded dashboards
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOW_ORIGINS if ALLOW_ORIGINS != ["*"] else ["*"],
    allow_credentials=False,
    allow_methods=["GET", "OPTIONS"],
    allow_headers=["*"],
)

# -------------------------
# Health & info
# -------------------------
@app.get("/health", summary="Simple health check")
def health_root():
    return {"ok": True, "dataverse": DATAVERSE_ENABLED, "version": app.version}

@app.get("/api/health", summary="Health under /api")
def health_api():
    return {"ok": True, "dataverse": DATAVERSE_ENABLED, "version": app.version}

@app.get("/info", summary="Service info")
def root_info():
    return {
        "service": "JDAS Dataverse API",
        "docs": "/docs",
        "health": "/health",
        "dataverse": DATAVERSE_ENABLED,
        "version": app.version,
    }

# -------------------------
# Dataverse helpers — token cache, http client, retries, paging
# -------------------------
_token_cache: Dict[str, str] = {}
_token_expiry_ts: float = 0.0
_SKEW = 60  # seconds
_entityset_cache: Dict[str, str] = {}  # logical -> EntitySetName

client: Optional[httpx.AsyncClient] = None
gate = asyncio.Semaphore(UPSTREAM_MAX_CONCURRENCY)
table_cache: Dict[str, Dict[str, Any]] = {}  # path -> {"ts": float, "data": Any}

def now_s() -> float:
    return time.time()

def cache_fresh(ts: float, ttl: int) -> bool:
    return (now_s() - ts) < ttl

async def get_client() -> httpx.AsyncClient:
    global client
    if client is None:
        client = httpx.AsyncClient(timeout=HTTP_TIMEOUT_S)
    return client

def _assert_cfg():
    if not DATAVERSE_ENABLED:
        raise HTTPException(503, "Dataverse env not configured")

async def fetch_access_token() -> str:
    _assert_cfg()
    data = {"client_id": CLIENT_ID, "client_secret": CLIENT_SECRET, "grant_type": "client_credentials", "scope": SCOPE}
    c = await get_client()
    r = await c.post(TOKEN_URL, data=data)
    if r.status_code != 200:
        raise HTTPException(502, f"Token error ({r.status_code})")
    j = r.json()
    tok = j["access_token"]
    expires_in = int(j.get("expires_in", 3600))
    global _token_expiry_ts
    _token_expiry_ts = now_s() + max(60, expires_in - _SKEW)
    _token_cache["token"] = tok
    return tok

async def get_access_token() -> str:
    _assert_cfg()
    tok = _token_cache.get("token")
    if not tok or now_s() >= _token_expiry_ts:
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
    """Resolve EntitySetName from a logical table name (cached)."""
    _assert_cfg()
    key = logical_name.strip()
    if key in _entityset_cache:
        return _entityset_cache[key]
    token = await get_access_token()
    headers = build_headers(token)
    url = f"{API_BASE}/EntityDefinitions(LogicalName='{key}')?$select=EntitySetName"
    c = await get_client()
    r = await c.get(url, headers=headers)
    if r.status_code != 200:
        raise HTTPException(502, f"Metadata lookup failed for {key} ({r.status_code})")
    entity_set = r.json().get("EntitySetName")
    if not entity_set:
        raise HTTPException(500, f"No EntitySetName for {key}")
    _entityset_cache[key] = entity_set
    return entity_set

async def dv_paged_get(path_or_url: str) -> List[dict]:
    """
    GET with paging & retries; accepts 'entityset?$top=..' or a full URL.
    Retries 429/5xx and common transport errors with exponential backoff.
    """
    _assert_cfg()
    next_url = path_or_url if path_or_url.startswith("http") else f"{API_BASE}/{path_or_url}"
    delays = [0.2, 0.5, 1.0, 2.0]
    out: List[dict] = []
    last_exc = None

    async with gate:
        c = await get_client()
        token = await get_access_token()
        headers = build_headers(token)

        while True:
            for delay in delays:
                try:
                    r = await c.get(next_url, headers=headers, timeout=MAX_PAGE_TIMEOUT_S)
                    if r.status_code == 401:
                        # refresh token once then retry immediately
                        token = await fetch_access_token()
                        headers = build_headers(token)
                        r = await c.get(next_url, headers=headers, timeout=MAX_PAGE_TIMEOUT_S)

                    if r.status_code == 200:
                        data = r.json()
                        out.extend(data.get("value", []))
                        next_link = data.get("@odata.nextLink")
                        if not next_link:
                            return out
                        next_url = next_link
                        break  # break retry loop, continue outer while for next page

                    if r.status_code in (429, 500, 502, 503, 504):
                        await asyncio.sleep(delay)
                        continue

                    # non-retryable
                    raise HTTPException(r.status_code, f"Upstream error {r.status_code}")
                except (httpx.ReadTimeout, httpx.ConnectTimeout, httpx.RemoteProtocolError) as e:
                    last_exc = e
                    await asyncio.sleep(delay)
                    continue
            else:
                # exhausted retries for this page
                if last_exc:
                    raise HTTPException(504, f"Upstream timeout: {last_exc}")
                raise HTTPException(503, "Upstream unavailable after retries")

def build_select(entity_set: str, columns: List[str], orderby: Optional[str] = None, top: int = 5000, extra: Optional[str] = None) -> str:
    params = {"$top": str(top)}
    if columns:
        params["$select"] = ",".join(columns)
    if orderby:
        params["$orderby"] = orderby
    qs = urlencode(params)
    return f"{entity_set}?{qs}" + (f"&{extra}" if extra else "")



# -------------------------
# TABLE CONFIG
# -------------------------
from typing import Dict, Any, List  # (safe even if already imported)

TABLES: List[Dict[str, Any]] = [
    # ── U.S. Trade ────────────────────────────────────────────────────────────
    {
        "name": "Trade Deficit Annual",
        "logical": "cred8_tradedeficitannual",
        "path": "/api/trade-deficit-annual",
        # Fill these with the exact logical column names you want to expose:
        "columns": ["jdas_month", "cred8_chatgpt"],   # ← Month, Total Deficit
        "map_to":  ["Month", "Total Deficit"],
        "orderby": "jdas_sortoder asc"

    },
    {
        "name": "Tariff % by Country",
        "logical": "cred8_tariffbycountry",
        "entity_set": "cred8_tariffbycountries",
        "path": "/api/tariff-by-country",
        "columns": ["cred8_country", "cred8_tariffrateasofaug1"],
        "map_to": ["Country", "Tariff Rates as of Aug 1"],
        "orderby": "cred8_country asc"
    },
{
    "name": "Tariff By Item",
    "logical": "jdas_tariffschedule",
    "entity_set": "jdas_tariffschedules",
    "path": "/api/tariff-by-item",
    "columns": [
        "jdas_productcategory",
        "jdas_totaltariffpercentage",
        "jdas_additionaltariffpercentage",
        "jdas_tariffreasonorprogram",
        "jdas_tariffeffectivedate",
        "jdas_additionalnotes"
    ],
    "map_to": [
        "Product Category",
        "Total Tariff Percentage",
        "Additional Tariff Percentage",
        "Tariff Reason or Program",
        "Tariff Effective Date",
        "Additional Notes"
    ],
    "orderby": ""
},
{
    "name": "Trade Deals",
    "logical": "cred8_tradedeal",
    "entity_set": "cred8_tradedeals",
    "path": "/api/trade-deals",
    "columns": [
        "cred8_countries",
        "cred8_impact",
        "cred8_notes"
    ],
    "map_to": [
        "Countries",
        "Impact",
        "Notes"
    ],
    "orderby": "cred8_countries asc"
},

 {
    "name": "Tariff Revenue",
    "logical": "cred8_tariffrevenue",
    "entity_set": "cred8_tariffrevenues",   # keep if you already have it
    "path": "/api/tariff-revenue",
    "columns": ["cred8_month", "cred8_revenueamountbillionusd"],
    "map_to":  ["Month",      "RevenueAmountBillionUSD"],
    "orderby": "jdas_sortorder asc"
},

    # ── KPI / Key Stats ───────────────────────────────────────────────────────
    {
        "name": "Unemployment Rate",
        "logical": "cred8_unemploymentrate",
        "entity_set": "cred8_unemploymentrates",
        "path": "/api/unemployment-rate",
        "columns": ["cred8_month", "cred8_unemploymentrate"],
        "map_to": ["Month",       "UnemploymentRate"],
        "orderby": "jdas_sortorder asc, cred8_month asc"
    },
    {
    {
        "name": "Inflation Rate",
        "logical": "cred8_inflationrate",
        "entity_set": "cred8_inflationrates",
        "path": "/api/inflation-rate",
        "columns": ["cred8_month", "cred8_cpi"],
        "map_to": ["Month","CPI %"],
        "orderby": "cred8_sortorder asc"
    },
    },
    {
        "name": "Economic Indicator (A)",
        "logical": "jdas_economicindicator",
        "path": "/api/economic-indicator",
        "columns": [],
        "map_to": [],
        "orderby": ""
    },
    {
        "name": "Manufacturing PMI Report",
        "logical": "jdas_manufacturingpmireport",
        "path": "/api/manufacturing-pmi-report",
        "columns": [],
        "map_to": [],
        "orderby": ""
    },
    {
        "name": "Weekly Claims Report",
        "logical": "jdas_weeklyclaimsreport",
        "path": "/api/weekly-claims-report",
        "columns": [],
        "map_to": [],
        "orderby": ""
    },
    {
        "name": "Consumer Confidence Index",
        "logical": "jdas_consumerconfidenceindex",
        "path": "/api/consumer-confidence-index",
        "columns": [],
        "map_to": [],
        "orderby": ""
    },
    {
        "name": "Treasury Yields Record",
        "logical": "jdas_treasuryyieldrecord",
        "path": "/api/treasury-yields-record",
        "columns": [],
        "map_to": [],
        "orderby": ""
    },
    {
        "name": "Economic Growth Report",
        "logical": "jdas_economicgrowthreport",
        "path": "/api/economic-growth-report",
        "columns": [],
        "map_to": [],
        "orderby": ""
    },
    {
        "name": "Economic Indicator (B)",
        "logical": "jdas_economicindicator1",  # fixed spelling from "indictator"
        "path": "/api/economic-indicator-1",
        "columns": [],
        "map_to": [],
        "orderby": ""
    },

    # ── Labor & Society ───────────────────────────────────────────────────────
    {
        "name": "Publicly Announced Revenue Loss",
        "logical": "cred8_publiclyannoucedrevenueloss",  # keep your exact logical name
        "path": "/api/publicly-annouced-revenue-loss",   # route spelling matches existing
        "columns": [],
        "map_to": [],
        "orderby": ""
    },
    {
        "name": "Layoff Tracking",
        "logical": "jdas_layofftracking",   # ← confirm actual logical name
        "path": "/api/layoffs",             # keep the working path used by your card
        "columns": [],
        "map_to": [],
        "orderby": "createdon desc"
    },
    {
        "name": "Acquisition Deal",
        "logical": "jdas_acquisitiondeal",
        "path": "/api/acquisition-deal",
        "columns": [],
        "map_to": [],
        "orderby": ""
    },
    {
        "name": "Bankruptcy Log",
        "logical": "cred8_bankruptcylog",
        "entity_set": "cred8_bankruptcylogs",
        "path": "/api/bankruptcies",
        "columns": [],
        "map_to": [],
        "orderby": ""
    },

    # ── Environmental & Energy ────────────────────────────────────────────────
    {
        "name": "Environmental Regulation",
        "logical": "jdas_environmentalregulation",
        "path": "/api/environmental-regulation",
        "columns": [],
        "map_to": [],
        "orderby": ""
    },
    {
        "name": "Environmental Policy",
        "logical": "jdas_environmentalpolicy",
        "path": "/api/environmental-policy",
        "columns": [],
        "map_to": [],
        "orderby": ""
    },
    {
        "name": "Infrastructure Investment",
        "logical": "jdas_infrastructureinvestment",
        "path": "/api/infrastructure-investment",
        "columns": [],
        "map_to": [],
        "orderby": ""
    },

    # ── Global Events ─────────────────────────────────────────────────────────
    {
        "name": "Corporate SpinOff",
        "logical": "jdas_corporatespinoff",
        "path": "/api/corporate-spinoff",
        "columns": [],
        "map_to": [],
        "orderby": ""
    },
    {
        "name": "Conflict Record",
        "logical": "jdas_conflictrecord",
        "path": "/api/conflict-record",
        "columns": [],
        "map_to": [],
        "orderby": ""
    },
    {
        "name": "Global Natural Disasters",
        "logical": "jdas_globalnaturaldisasters",
        "path": "/api/global-natural-disasters",
        "columns": [],
        "map_to": [],
        "orderby": ""
    },
]

TABLE_BY_PATH = {t["path"]: t for t in TABLES}
# -------------------------
# Cache + fetch wrapper per table (prevents 503 surfacing)

# -------------------------
async def get_table_data(es_or_logical: Dict[str, Any], top: int, orderby: Optional[str], extra: Optional[str], return_raw: bool, cols: List[str], keys: List[str]):
    # Pick explicit entity_set if supplied, else resolve logical
    if es_or_logical.get("entity_set"):
        es = es_or_logical["entity_set"]
    else:
        logical = es_or_logical.get("logical")
        if not logical:
            raise HTTPException(500, "No entity_set or logical provided")
        es = await resolve_entity_set_from_logical(logical)

    query = build_select(es, cols if cols else [], (orderby or es_or_logical.get("orderby") or ""), top=top, extra=extra)
    cache_key = f"{es}|{top}|{orderby}|{extra}|{','.join(cols) if cols else '*'}"
    item = table_cache.get(cache_key)
    if item and cache_fresh(item["ts"], CACHE_TTL_S):
        rows = item["data"]
    else:
        rows = await dv_paged_get(query)
        table_cache[cache_key] = {"ts": now_s(), "data": rows}

    if return_raw or not cols:
        return {"ok": True, "count": len(rows), "value": rows}

    shaped = [{k: r.get(c) for c, k in zip(cols, keys)} for r in rows]
    return {"ok": True, "count": len(shaped), "value": shaped}

# -------------------------
# Route factory (keeps your query params & raw-rows behavior)
# -------------------------
def make_handler(entity_set: Optional[str], logical: Optional[str],
                 cols: List[str], keys: List[str], default_order: Optional[str]):

    async def handler(
        top: int = Query(5000, ge=1, le=50000, description="$top limit"),
        orderby: Optional[str] = Query(None, description="Override $orderby"),
        extra: Optional[str] = Query(None, description="Extra OData query string to append (advanced)"),
        raw: bool = Query(False, description="Return raw rows even when columns are defined"),
    ):
        try:
            payload = await get_table_data(
                {"entity_set": entity_set, "logical": logical, "orderby": default_order},
                top=top, orderby=orderby, extra=extra,
                return_raw=(raw or not cols), cols=cols, keys=keys
            )
            return JSONResponse(content=payload, status_code=200)
        except HTTPException as e:
            # mask upstream errors to keep 200 for iframe; tell frontend ok:false
            return JSONResponse(status_code=200, content={"ok": False, "status": e.status_code, "error": str(e.detail)})
        except Exception as e:
            return JSONResponse(status_code=200, content={"ok": False, "status": 500, "error": f"Server error: {e}"})

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

@app.get("/api/_tables", summary="Quick table listing")
async def list_tables():
    return [{"name": t["name"], "path": t["path"], "logical": t.get("logical",""), "entity_set": t.get("entity_set","")} for t in TABLES]

@app.get("/api/describe", summary="Resolve entity set & return one sample row")
async def describe(logical: str):
    es = await resolve_entity_set_from_logical(logical)
    rows = await dv_paged_get(f"{es}?$top=1")
    return {"logical": logical, "entity_set": es, "sample": rows[:1]}

# -------------------------
# Lifecycle
# -------------------------
@app.on_event("startup")
async def _startup():
    # warm client and token (don't crash if auth fails here; /health will reflect)
    _ = await get_client()
    try:
        _ = await get_access_token()
    except Exception:
        pass

@app.on_event("shutdown")
async def _shutdown():
    global client
    if client:
        try:
            await client.aclose()
        finally:
            client = None
@app.get("/envcheck")
def _envcheck():
    import os
    keys = [
        "DATAVERSE_URL","TENANT_ID","CLIENT_ID","CLIENT_SECRET",
        "AZURE_TENANT_ID","AZURE_CLIENT_ID","AZURE_CLIENT_SECRET","DATAVERSE_API_BASE"
    ]
    # Only booleans — no secrets returned
    return {k: bool(os.getenv(k)) for k in keys}
