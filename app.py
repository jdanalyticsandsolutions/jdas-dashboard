import os
import time
import asyncio
from pathlib import Path
from typing import Any, Dict, Optional
from datetime import datetime, timezone

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

# --- Initialization ---
load_dotenv()
BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
TEMPLATES_DIR = BASE_DIR / "templates"

app = FastAPI(title="JDAS Analytics API", version="3.0.0")

# --- Environment Config ---
TENANT_ID = os.getenv("TENANT_ID") or os.getenv("AZURE_TENANT_ID")
CLIENT_ID = os.getenv("CLIENT_ID") or os.getenv("AZURE_CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET") or os.getenv("AZURE_CLIENT_SECRET")
DATAVERSE_URL = (os.getenv("DATAVERSE_URL") or "").rstrip("/")
API_BASE = f"{DATAVERSE_URL}/api/data/v9.2"

DATAVERSE_ENABLED = all([TENANT_ID, CLIENT_ID, CLIENT_SECRET, DATAVERSE_URL])
BUILD_STAMP = os.getenv("BUILD_STAMP") or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

# --- Dashboard Registry (SINGLE source of truth) ---
# NOTE: table keys reference TABLE_MAPPINGS keys below
INDUSTRY_CONFIG = {
    "real_estate": {
        "label": "Real Estate",
        "tables": ["housingmarketinsight", "marketoutlook"]
    },
    "automotive": {
        "label": "Automotive",
        "tables": ["vehiclesalesforecast"]
    },
    "analytics_ops": {
        "label": "Analytics & Ops",
        "tables": ["analyticsparadigm"]
    },
    "ai": {
        "label": "AI Developments",
        "tables": ["aiindustryinsight"]
    },
    "market": {
        "label": "Market Insight",
        "tables": ["marketinsight", "markettrendinsight", "marketanalysis"]
    }
}

# --- Column Mappings ---
TABLE_MAPPINGS = {
    "marketinsight": {
        "logical": "jdas_marketinsight",
        "label": "Market Insight",
        "title": "jdas_marketcategory",
        "body": "jdas_markettrends",
        "tag": "Market",
    },
    "housingmarketinsight": {
        "logical": "jdas_housingmarketinsight",
        "label": "Housing Market Insight",
        "title": "jdas_insighttheme",
        "body": "jdas_currentinsight",
        "tag": "Housing",
    },
    "vehiclesalesforecast": {
        "logical": "jdas_vehiclesalesforecast",
        "label": "Vehicle Sales Forecast",
        "title": "jdas_salesmetric",
        "body": "jdas_strategicinsight",
        "tag": "Sales",
    },
    "analyticsparadigm": {
        "logical": "jdas_analyticsparadigm",
        "label": "Analytics Paradigm",
        "title": "jdas_analyticsfocus",
        "body": "jdas_significance",
        "tag": "Ops",
    },
    "marketoutlook": {
        "logical": "jdas_marketoutlook",
        "label": "Market Outlook",
        "title": "jdas_category",
        "body": "jdas_keydrivers",
        "tag": "Outlook",
    },
    "markettrendinsight": {
        "logical": "jdas_markettrendinsight",
        "label": "Market Trend Insight",
        "title": "jdas_keysignal",
        "body": "jdas_trendfor2026",
        "tag": "Trends",
    },
    "marketanalysis": {
        "logical": "jdas_marketanalysis",
        "label": "Market Analysis",
        "title": "jdas_theme",
        "body": "jdas_industryreality2026",
        "tag": "Analysis",
    },
    "aiindustryinsight": {
        "logical": "jdas_aiindustryinsight",
        "label": "AI Industry Insight",
        "title": "jdas_insightcategory",
        "body": "jdas_assistantperspective",
        "tag": "AI",
        "dv_fields": {
            "assistant_perspective": "jdas_assistantperspective",
            "future_unified_view": "jdas_futureunifiedview",
            "industry_phase_description": "jdas_industryphasedescription",
            "insight_category": "jdas_insightcategory"
        }
    },
}

# --- Dataverse Engine ---
_token_cache: Dict[str, str] = {}
_token_expiry_ts: float = 0.0
_entityset_cache: Dict[str, str] = {}
client_http: Optional[httpx.AsyncClient] = None

async def get_client() -> httpx.AsyncClient:
    global client_http
    if client_http is None:
        client_http = httpx.AsyncClient(timeout=20.0)
    return client_http

async def get_access_token() -> str:
    global _token_expiry_ts
    if "token" in _token_cache and time.time() < _token_expiry_ts:
        return _token_cache["token"]

    if not DATAVERSE_ENABLED:
        raise RuntimeError("Dataverse not configured (missing env vars).")

    url = f"https://login.microsoftonline.com/{TENANT_ID}/oauth2/v2.0/token"
    data = {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "grant_type": "client_credentials",
        "scope": f"{DATAVERSE_URL}/.default",
    }

    c = await get_client()
    r = await c.post(url, data=data)
    r.raise_for_status()
    j = r.json()

    _token_cache["token"] = j["access_token"]
    _token_expiry_ts = time.time() + int(j.get("expires_in", 3600)) - 60
    return _token_cache["token"]

async def resolve_entity_set(logical_name: str) -> str:
    if logical_name in _entityset_cache:
        return _entityset_cache[logical_name]

    token = await get_access_token()
    url = f"{API_BASE}/EntityDefinitions(LogicalName='{logical_name}')?$select=EntitySetName"
    c = await get_client()
    r = await c.get(url, headers={"Authorization": f"Bearer {token}"})
    r.raise_for_status()

    es = r.json().get("EntitySetName")
    if not es:
        raise RuntimeError(f"Could not resolve EntitySetName for {logical_name}")

    _entityset_cache[logical_name] = es
    return es

async def fetch_dv_data(logical_name: str, top: int):
    try:
        es = await resolve_entity_set(logical_name)
        token = await get_access_token()
        url = f"{API_BASE}/{es}?$top={top}&$orderby=createdon desc"

        c = await get_client()
        r = await c.get(
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "Prefer": "odata.maxpagesize=50",
            },
        )
        r.raise_for_status()
        return r.json().get("value", [])
    except Exception as e:
        print(f"FAILED to fetch {logical_name}: {str(e)}")
        return []

# --- Normalization ---
def normalize(row: dict, table_key: str, industry_key: str):
    cfg = TABLE_MAPPINGS.get(table_key)
    if not cfg:
        return None

    title_field = cfg.get("title")
    body_field = cfg.get("body")

    title = (row.get(title_field) if title_field else None) or row.get("jdas_name") or "Update"
    body = (row.get(body_field) if body_field else None) or ""

    out = {
        # traceability
        "id": row.get(cfg["logical"] + "id"),
        "industry_key": industry_key,
        "table_key": table_key,             # stable key (matches registry)
        "table": cfg["logical"],            # Dataverse logical name (what you already used)
        "table_label": cfg.get("label", table_key),
        "tag": cfg.get("tag", ""),

        # display
        "title": str(title).strip(),
        "body": str(body).strip(),
        "createdOn": row.get("createdon") or "",

        # debugging (optional but helpful)
        "source": {
            "logical": cfg["logical"],
            "title_field": title_field,
            "body_field": body_field,
        }
    }

    dv_fields = cfg.get("dv_fields") or {}
    for out_key, dv_key in dv_fields.items():
        val = row.get(dv_key)
        out[out_key] = val if val is not None else ""

    return out

# --- Routes ---
@app.get("/", response_class=HTMLResponse)
async def home():
    index_path = TEMPLATES_DIR / "index.html"
    if not index_path.exists():
        return HTMLResponse("<h1>Backend Running</h1><p>No index.html found in /templates</p>")

    return FileResponse(
        index_path,
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )

@app.get("/api/v1/health")
async def health():
    return {
        "ok": True,
        "dataverse_enabled": DATAVERSE_ENABLED,
        "build_stamp": BUILD_STAMP,
        "version": app.version,
    }

@app.get("/api/v1/config")
async def config():
    industries = []
    for ind_key, ind_cfg in INDUSTRY_CONFIG.items():
        industries.append({
            "key": ind_key,
            "label": ind_cfg["label"],
            "tables": [
                {
                    "key": t_key,
                    "label": TABLE_MAPPINGS.get(t_key, {}).get("label", t_key),
                    "logical": TABLE_MAPPINGS.get(t_key, {}).get("logical", ""),
                    "tag": TABLE_MAPPINGS.get(t_key, {}).get("tag", ""),
                }
                for t_key in ind_cfg["tables"]
            ]
        })

    return {
        "ok": True,
        "build_stamp": BUILD_STAMP,
        "dataverse_enabled": DATAVERSE_ENABLED,
        "industries": industries,
    }

@app.get("/api/v1/summary/industry-updates")
async def industry_updates(top: int = Query(10)):
    """
    Grouped output:
    blocks[industry].tables[table_key].items[]
    """
    blocks: Dict[str, Dict[str, Any]] = {}

    async def process_industry(ind_key: str, config: Dict[str, Any]):
        tables_out: Dict[str, Any] = {}

        async def process_table(t_key: str):
            cfg = TABLE_MAPPINGS[t_key]
            raw = await fetch_dv_data(cfg["logical"], top)
            items = []
            for r in raw:
                n = normalize(r, t_key, ind_key)
                if n:
                    items.append(n)
            items.sort(key=lambda x: x.get("createdOn", "") or "", reverse=True)
            tables_out[t_key] = {
                "label": cfg.get("label", t_key),
                "logical": cfg["logical"],
                "tag": cfg.get("tag", ""),
                "items": items,
            }

        await asyncio.gather(*[process_table(t_key) for t_key in config["tables"]])

        blocks[ind_key] = {
            "label": config.get("label", ind_key),
            "tables": tables_out
        }

    await asyncio.gather(*[process_industry(k, v) for k, v in INDUSTRY_CONFIG.items()])
    return {"ok": True, "blocks": blocks}

# --- Middleware & Static ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
