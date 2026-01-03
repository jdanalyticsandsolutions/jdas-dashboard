# app.py — JDAS Tailored Industry Updates backend (Dataverse raw + normalized summary)
import os
import time
import asyncio
from pathlib import Path
from typing import Dict, List, Optional, Any
from urllib.parse import urlencode

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

# ============================================================
# App paths / static
# ============================================================
BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
TEMPLATES_DIR = BASE_DIR / "templates"

app = FastAPI(title="JDAS Tailored Industry Updates API", version="1.1.0")

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/", response_class=HTMLResponse)
def home():
    index_path = TEMPLATES_DIR / "index.html"
    if index_path.exists():
        return FileResponse(str(index_path))
    return HTMLResponse("<h1>JDAS</h1><p>templates/index.html not found.</p>", status_code=200)


# ============================================================
# Env / configuration
# ============================================================
load_dotenv()

TENANT_ID = os.getenv("TENANT_ID") or os.getenv("AZURE_TENANT_ID")
CLIENT_ID = os.getenv("CLIENT_ID") or os.getenv("AZURE_CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET") or os.getenv("AZURE_CLIENT_SECRET")

DATAVERSE_URL = (os.getenv("DATAVERSE_URL") or os.getenv("DATAVERSE_API_BASE") or "").rstrip("/")

ALLOW_ORIGINS = [o.strip() for o in os.getenv("ALLOW_ORIGINS", "*").split(",")]

CACHE_TTL_S = int(os.getenv("CACHE_TTL_S", "120"))
UPSTREAM_MAX_CONCURRENCY = int(os.getenv("UPSTREAM_MAX_CONCURRENCY", "4"))
HTTP_TIMEOUT_S = float(os.getenv("HTTP_TIMEOUT_S", "15.0"))
MAX_PAGE_TIMEOUT_S = float(os.getenv("MAX_PAGE_TIMEOUT_S", "60.0"))

DEFAULT_TOP = int(os.getenv("DEFAULT_TOP", "25"))
MAX_TOP = int(os.getenv("MAX_TOP", "200"))
DEFAULT_ORDERBY = os.getenv("DEFAULT_ORDERBY", "createdon desc")

DATAVERSE_ENABLED = all([TENANT_ID, CLIENT_ID, CLIENT_SECRET, DATAVERSE_URL])
TOKEN_URL = f"https://login.microsoftonline.com/{TENANT_ID}/oauth2/v2.0/token" if DATAVERSE_ENABLED else None
SCOPE = f"{DATAVERSE_URL}/.default" if DATAVERSE_ENABLED else None
API_BASE = f"{DATAVERSE_URL}/api/data/v9.2" if DATAVERSE_ENABLED else None

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOW_ORIGINS if ALLOW_ORIGINS != ["*"] else ["*"],
    allow_credentials=False,
    allow_methods=["GET", "OPTIONS"],
    allow_headers=["*"],
)

# ============================================================
# Health / info
# ============================================================
@app.get("/health", summary="Simple health check")
def health_root():
    return {"ok": True, "dataverse": DATAVERSE_ENABLED, "version": app.version}


@app.get("/api/health", summary="Health under /api")
def health_api():
    return {"ok": True, "dataverse": DATAVERSE_ENABLED, "version": app.version}


@app.get("/info", summary="Service info")
def root_info():
    return {
        "service": "JDAS Tailored Industry Updates API",
        "docs": "/docs",
        "health": "/health",
        "dataverse": DATAVERSE_ENABLED,
        "version": app.version,
    }


# ============================================================
# Dataverse helpers — token cache, client, retry/paging
# ============================================================
_token_cache: Dict[str, str] = {}
_token_expiry_ts: float = 0.0
_SKEW = 60  # seconds

_entityset_cache: Dict[str, str] = {}  # logical -> EntitySetName
client: Optional[httpx.AsyncClient] = None
gate = asyncio.Semaphore(UPSTREAM_MAX_CONCURRENCY)

# cache_key -> {"ts": float, "data": Any}
table_cache: Dict[str, Dict[str, Any]] = {}


def now_s() -> float:
    return time.time()


def cache_fresh(ts: float, ttl: int) -> bool:
    return (now_s() - ts) < ttl


async def get_client() -> httpx.AsyncClient:
    global client
    if client is None:
        client = httpx.AsyncClient(timeout=HTTP_TIMEOUT_S)
    return client


def _assert_cfg() -> None:
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


async def dv_get_json(url: str, headers: Dict[str, str]) -> dict:
    """Single GET with retry/backoff; returns parsed JSON."""
    delays = [0.2, 0.5, 1.0, 2.0]
    last_exc: Optional[Exception] = None
    c = await get_client()

    for delay in delays:
        try:
            r = await c.get(url, headers=headers, timeout=MAX_PAGE_TIMEOUT_S)

            # Refresh once on 401
            if r.status_code == 401:
                tok = await fetch_access_token()
                headers = build_headers(tok)
                r = await c.get(url, headers=headers, timeout=MAX_PAGE_TIMEOUT_S)

            if r.status_code == 200:
                return r.json()

            if r.status_code in (429, 500, 502, 503, 504):
                await asyncio.sleep(delay)
                continue

            raise HTTPException(r.status_code, f"Upstream error {r.status_code}: {r.text[:300]}")
        except (httpx.ReadTimeout, httpx.ConnectTimeout, httpx.RemoteProtocolError) as e:
            last_exc = e
            await asyncio.sleep(delay)
            continue

    if last_exc:
        raise HTTPException(504, f"Upstream timeout: {last_exc}")
    raise HTTPException(503, "Upstream unavailable after retries")


async def dv_paged_get(path_or_url: str) -> List[dict]:
    """
    GET with paging; accepts 'EntitySet?$top=..' or a full URL.
    Returns aggregated "value" across pages.
    """
    _assert_cfg()
    next_url = path_or_url if path_or_url.startswith("http") else f"{API_BASE}/{path_or_url}"
    out: List[dict] = []

    async with gate:
        tok = await get_access_token()
        headers = build_headers(tok)

        while True:
            data = await dv_get_json(next_url, headers=headers)
            out.extend(data.get("value", []))
            next_link = data.get("@odata.nextLink")
            if not next_link:
                return out
            next_url = next_link


def build_query(
    entity_set: str,
    top: int,
    orderby: str,
    extra: Optional[str] = None,
    include_select: bool = False,
    columns: Optional[List[str]] = None,
) -> str:
    """
    Build an OData query.
    If include_select=False -> fetch all columns (Dataverse will include @odata.etag metadata too).
    """
    params = {"$top": str(top)}
    if orderby:
        params["$orderby"] = orderby
    if include_select and columns:
        params["$select"] = ",".join(columns)

    qs = urlencode(params)
    return f"{entity_set}?{qs}" + (f"&{extra}" if extra else "")


# ============================================================
# Table registry (logical names)
# ============================================================
TABLE_REGISTRY: Dict[str, Dict[str, str]] = {
    "marketinsight": {"logical": "jdas_marketinsight"},
    "housingmarketinsight": {"logical": "jdas_housingmarketinsight"},
    "vehiclesalesforecast": {"logical": "jdas_vehiclesalesforecast"},
    "analyticsparadigm": {"logical": "jdas_analyticsparadigm"},
    "marketoutlook": {"logical": "jdas_marketoutlook"},
    "markettrendinsight": {"logical": "jdas_markettrendinsight"},
    "marketanalysis": {"logical": "jdas_marketanalysis"},
    "aiindustryinsight": {"logical": "jdas_aiindustryinsight"},
}

# Which blocks the dashboard asks for (block_name -> table_key)
SUMMARY_MAP: Dict[str, str] = {
    # industries
    "real_estate": "housingmarketinsight",
    "automotive": "vehiclesalesforecast",
    "analytics_ops": "analyticsparadigm",
    "ai": "aiindustryinsight",
    # general market blocks
    "market": "marketinsight",
    "outlook": "marketoutlook",
    "trends": "markettrendinsight",
    "analysis": "marketanalysis",
}

# ============================================================
# NORMALIZATION (this is what stops W/"####" from ever showing)
# ============================================================
TABLE_DISPLAY_NAMES: Dict[str, str] = {
    "marketinsight": "Market Insight",
    "housingmarketinsight": "Housing Market Insight",
    "vehiclesalesforecast": "Vehicle Sales Forecast",
    "analyticsparadigm": "Analytics Paradigm",
    "marketoutlook": "Market Outlook",
    "markettrendinsight": "Market Trend Insight",
    "marketanalysis": "Market Analysis",
    "aiindustryinsight": "AI Industry Insight",
}

TABLE_MAPPINGS: Dict[str, Dict[str, str]] = {
    # table_key -> which columns become title/subtitle/body/etc.
    "marketinsight": {
        "title": "jdas_marketcategory",
        "subtitle": "jdas_marketsizeoverview",
        "body": "jdas_markettrends",
        "details": "jdas_businessimpactanalysis",
    },
    "housingmarketinsight": {
        "title": "jdas_insighttheme",
        "subtitle": "jdas_insightcategory",
        "body": "jdas_currentinsight",
        "details": "jdas_keymarketimplication",
    },
    "vehiclesalesforecast": {
        "title": "jdas_salesmetric",
        "subtitle": "jdas_salesvolumeforecast",
        "body": "jdas_strategicinsight",
    },
    "analyticsparadigm": {
        "title": "jdas_analyticsfocus",
        "subtitle": "jdas_dimension",
        "body": "jdas_significance",
        "tag": "jdas_paradigmstage",
    },
    "marketoutlook": {
        "title": "jdas_category",
        "subtitle": "jdas_outlookstatus",
        "body": "jdas_keydrivers",
        "details": "jdas_operationalimpact",
    },
    "markettrendinsight": {
        "title": "jdas_keysignal",
        "subtitle": "jdas_insightcategory",
        "body": "jdas_trendfor2026",
    },
    "marketanalysis": {
        "title": "jdas_theme",
        "subtitle": "jdas_industryreality2026",
        "body": "jdas_futureimplications",
    },
    "aiindustryinsight": {
        "title": "jdas_insightcategory",
        "subtitle": "jdas_industryphasedescription",
        "body": "jdas_assistantperspective",
        "details": "jdas_futureunifiedview",
    },
}


def _safe_text(v: Any) -> Optional[str]:
    if v is None:
        return None
    if isinstance(v, str):
        s = v.strip()
        return s if s else None
    return str(v).strip() or None


def _guess_id(row: dict, table_key: str) -> Optional[str]:
    """
    Best-effort ID extraction:
    - primary key usually is {logical}id, e.g. jdas_marketinsightid
    - but we only have table_key in SUMMARY_MAP; use registry logical too
    """
    logical = TABLE_REGISTRY.get(table_key, {}).get("logical")
    if logical:
        maybe_pk = f"{logical}id"  # common Dataverse convention
        if maybe_pk in row:
            return _safe_text(row.get(maybe_pk))

    # fallbacks
    for k in ("id", "Id", "ID"):
        if k in row:
            return _safe_text(row.get(k))
    return None


def normalize_row(row: dict, table_key: str) -> Optional[dict]:
    """
    Convert a raw Dataverse row into a clean 'card' object.
    IMPORTANT: We do not pass through raw keys (like @odata.etag).
    """
    mapping = TABLE_MAPPINGS.get(table_key)
    if not mapping:
        return None

    title = _safe_text(row.get(mapping.get("title", "")))
    subtitle = _safe_text(row.get(mapping.get("subtitle", "")))
    body = _safe_text(row.get(mapping.get("body", "")))
    details = _safe_text(row.get(mapping.get("details", ""))) if mapping.get("details") else None
    tag = _safe_text(row.get(mapping.get("tag", ""))) if mapping.get("tag") else None

    # If there's no title at all, this record won't render well as a card
    if not title:
        return None

    return {
        "id": _guess_id(row, table_key),
        "table_key": table_key,
        "table_name": TABLE_DISPLAY_NAMES.get(table_key, table_key),
        "title": title,
        "subtitle": subtitle,
        "body": body,
        "details": details,
        "tag": tag,
        "createdOn": _safe_text(row.get("createdon")),
    }


# ============================================================
# Cache-backed fetchers
# ============================================================
async def fetch_table_all_columns(
    table_key: str,
    top: int,
    orderby: str,
    extra: Optional[str],
) -> Dict[str, Any]:
    cfg = TABLE_REGISTRY.get(table_key)
    if not cfg:
        raise HTTPException(404, f"Unknown table_key '{table_key}'")

    logical = cfg["logical"]
    entity_set = await resolve_entity_set_from_logical(logical)

    # All columns (no $select)
    query = build_query(entity_set, top=top, orderby=orderby, extra=extra, include_select=False)

    cache_key = f"{table_key}|{entity_set}|{top}|{orderby}|{extra or ''}|ALL"
    item = table_cache.get(cache_key)

    if item and cache_fresh(item["ts"], CACHE_TTL_S):
        rows = item["data"]
    else:
        rows = await dv_paged_get(query)
        table_cache[cache_key] = {"ts": now_s(), "data": rows}

    return {
        "ok": True,
        "table_key": table_key,
        "logical": logical,
        "entity_set": entity_set,
        "top": top,
        "orderby": orderby,
        "count": len(rows),
        "value": rows,
    }


async def fetch_table_cards(
    table_key: str,
    top: int,
    orderby: str,
) -> Dict[str, Any]:
    """
    Returns a normalized, frontend-safe payload for a single table_key.
    """
    data = await fetch_table_all_columns(table_key=table_key, top=top, orderby=orderby, extra=None)
    raw_items = data.get("value", [])
    cards = [c for c in (normalize_row(r, table_key) for r in raw_items) if c]

    return {
        "ok": True,
        "table_key": table_key,
        "table_name": TABLE_DISPLAY_NAMES.get(table_key, table_key),
        "logical": data.get("logical"),
        "entity_set": data.get("entity_set"),
        "count_raw": data.get("count"),
        "count_cards": len(cards),
        "items": cards,
    }


# ============================================================
# API — Raw (debug) endpoints
# ============================================================
@app.get("/api/v1/raw/tables", summary="List available table keys")
async def raw_tables():
    return {"ok": True, "tables": sorted(TABLE_REGISTRY.keys())}


@app.get("/api/v1/raw/{table_key}", summary="Fetch raw rows (all columns) from a Dataverse table")
async def raw_table(
    table_key: str,
    top: int = Query(DEFAULT_TOP, ge=1, le=MAX_TOP, description="Number of rows to return ($top)"),
    orderby: str = Query(DEFAULT_ORDERBY, description="OData $orderby (default: createdon desc)"),
    extra: Optional[str] = Query(None, description="Extra OData query string to append (advanced). Example: $filter=..."),
):
    try:
        payload = await fetch_table_all_columns(table_key=table_key, top=top, orderby=orderby, extra=extra)
        return JSONResponse(content=payload, status_code=200)
    except HTTPException as e:
        # Mask upstream errors to keep 200 for iframe; tell frontend ok:false
        return JSONResponse(status_code=200, content={"ok": False, "status": e.status_code, "error": str(e.detail)})
    except Exception as e:
        return JSONResponse(status_code=200, content={"ok": False, "status": 500, "error": f"Server error: {e}"})


# ============================================================
# API — Summary endpoints (what your Wix dashboard should use)
# ============================================================
@app.get(
    "/api/v1/summary/industry-updates",
    summary="One-call endpoint for the Tailored Industry Updates dashboard (normalized cards)",
)
async def industry_updates(
    top: int = Query(10, ge=1, le=MAX_TOP, description="Rows per block"),
    orderby: str = Query(DEFAULT_ORDERBY, description="OData $orderby (default: createdon desc)"),
):
    """
    Returns multiple blocks in one payload for fast Wix loading.
    Each block returns NORMALIZED card objects:
      {id, title, subtitle, body, details, tag, createdOn, ...}
    So the frontend never sees @odata.etag and won't render W/\"####\" ever again.
    """
    blocks: Dict[str, Any] = {}

    async def _fetch_block(block_name: str, table_key: str):
        try:
            blocks[block_name] = await fetch_table_cards(table_key=table_key, top=top, orderby=orderby)
        except HTTPException as e:
            blocks[block_name] = {"ok": False, "status": e.status_code, "error": str(e.detail)}
        except Exception as e:
            blocks[block_name] = {"ok": False, "status": 500, "error": f"Server error: {e}"}

    tasks = [_fetch_block(block, key) for block, key in SUMMARY_MAP.items()]
    await asyncio.gather(*tasks)

    return {"ok": True, "top": top, "orderby": orderby, "blocks": blocks}


@app.get("/api/v1/summary/cards/{table_key}", summary="Fetch one table as normalized cards (single block)")
async def summary_cards_single(
    table_key: str,
    top: int = Query(10, ge=1, le=MAX_TOP, description="Rows for this table"),
    orderby: str = Query(DEFAULT_ORDERBY, description="OData $orderby"),
):
    try:
        payload = await fetch_table_cards(table_key=table_key, top=top, orderby=orderby)
        return JSONResponse(content=payload, status_code=200)
    except HTTPException as e:
        return JSONResponse(status_code=200, content={"ok": False, "status": e.status_code, "error": str(e.detail)})
    except Exception as e:
        return JSONResponse(status_code=200, content={"ok": False, "status": 500, "error": f"Server error: {e}"})


# ============================================================
# Metadata utilities (debug)
# ============================================================
@app.get("/api/v1/metadata", summary="List registry + resolved entity set names (best-effort)")
async def metadata():
    out = []
    for k, v in TABLE_REGISTRY.items():
        logical = v["logical"]
        try:
            es = await resolve_entity_set_from_logical(logical)
        except Exception:
            es = ""
        out.append({"table_key": k, "logical": logical, "entity_set": es})
    return {"ok": True, "tables": out}


@app.get("/api/v1/describe", summary="Resolve entity set & return one sample row")
async def describe(logical: str):
    es = await resolve_entity_set_from_logical(logical)
    rows = await dv_paged_get(f"{es}?$top=1")
    return {"ok": True, "logical": logical, "entity_set": es, "sample": rows[:1]}


# ============================================================
# Lifecycle
# ============================================================
@app.on_event("startup")
async def _startup():
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


@app.get("/envcheck", summary="Show which env vars are present (no secrets)")
def _envcheck():
    keys = [
        "DATAVERSE_URL",
        "TENANT_ID",
        "CLIENT_ID",
        "CLIENT_SECRET",
        "AZURE_TENANT_ID",
        "AZURE_CLIENT_ID",
        "AZURE_CLIENT_SECRET",
        "DATAVERSE_API_BASE",
        "ALLOW_ORIGINS",
    ]
    return {k: bool(os.getenv(k)) for k in keys}
