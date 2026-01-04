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

# --- Initialization ---
load_dotenv()
BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
TEMPLATES_DIR = BASE_DIR / "templates"

app = FastAPI(title="JDAS Analytics API", version="2.0.0")

# --- Environment Config ---
TENANT_ID = os.getenv("TENANT_ID") or os.getenv("AZURE_TENANT_ID")
CLIENT_ID = os.getenv("CLIENT_ID") or os.getenv("AZURE_CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET") or os.getenv("AZURE_CLIENT_SECRET")
DATAVERSE_URL = (os.getenv("DATAVERSE_URL") or "").rstrip("/")
API_BASE = f"{DATAVERSE_URL}/api/data/v9.2"
DATAVERSE_ENABLED = all([TENANT_ID, CLIENT_ID, CLIENT_SECRET, DATAVERSE_URL])

# --- Dashboard Design Registry ---
# Matches your index.html and style.css perfectly
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

TABLE_MAPPINGS = {
    "marketinsight": {"logical": "jdas_marketinsight", "title": "jdas_marketcategory", "body": "jdas_markettrends", "tag": "Market"},
    "housingmarketinsight": {"logical": "jdas_housingmarketinsight", "title": "jdas_insighttheme", "body": "jdas_currentinsight", "tag": "Housing"},
    "vehiclesalesforecast": {"logical": "jdas_vehiclesalesforecast", "title": "jdas_salesmetric", "body": "jdas_strategicinsight", "tag": "Sales"},
    "analyticsparadigm": {"logical": "jdas_analyticsparadigm", "title": "jdas_analyticsfocus", "body": "jdas_significance", "tag": "Ops"},
    "marketoutlook": {"logical": "jdas_marketoutlook", "title": "jdas_category", "body": "jdas_keydrivers", "tag": "Outlook"},
    "markettrendinsight": {"logical": "jdas_markettrendinsight", "title": "jdas_keysignal", "body": "jdas_trendfor2026", "tag": "Trends"},
    "marketanalysis": {"logical": "jdas_marketanalysis", "title": "jdas_theme", "body": "jdas_industryreality2026", "tag": "Analysis"},
    "aiindustryinsight": {"logical": "jdas_aiindustryinsight", "title": "jdas_insightcategory", "body": "jdas_assistantperspective", "tag": "AI"},
}

# --- Dataverse Engine (Your Working Logic) ---
_token_cache = {}
_token_expiry_ts = 0.0
_entityset_cache = {}
client_http = None

async def get_client():
    global client_http
    if client_http is None: client_http = httpx.AsyncClient(timeout=20.0)
    return client_http

async def get_access_token():
    global _token_expiry_ts
    if "token" in _token_cache and time.time() < _token_expiry_ts:
        return _token_cache["token"]
    
    url = f"https://login.microsoftonline.com/{TENANT_ID}/oauth2/v2.0/token"
    data = {
        "client_id": CLIENT_ID, "client_secret": CLIENT_SECRET,
        "grant_type": "client_credentials", "scope": f"{DATAVERSE_URL}/.default",
    }
    c = await get_client()
    r = await c.post(url, data=data)
    j = r.json()
    _token_cache["token"] = j["access_token"]
    _token_expiry_ts = time.time() + int(j.get("expires_in", 3600)) - 60
    return _token_cache["token"]

async def resolve_entity_set(logical_name: str):
    if logical_name in _entityset_cache: return _entityset_cache[logical_name]
    token = await get_access_token()
    url = f"{API_BASE}/EntityDefinitions(LogicalName='{logical_name}')?$select=EntitySetName"
    c = await get_client()
    r = await c.get(url, headers={"Authorization": f"Bearer {token}"})
    es = r.json().get("EntitySetName")
    _entityset_cache[logical_name] = es
    return es

async def fetch_dv_data(logical_name: str, top: int):
    es = await resolve_entity_set(logical_name)
    token = await get_access_token()
    url = f"{API_BASE}/{es}?$top={top}&$orderby=createdon desc"
    c = await get_client()
    r = await c.get(url, headers={"Authorization": f"Bearer {token}", "Prefer": "odata.maxpagesize=50"})
    return r.json().get("value", [])

# --- Normalization ---
def normalize(row: dict, table_key: str):
    cfg = TABLE_MAPPINGS.get(table_key)
    if not cfg: return None
    
    title = row.get(cfg["title"]) or row.get("jdas_name") or "Update"
    body = row.get(cfg["body"]) or ""
    
    return {
        "table": cfg["logical"],
        "title": str(title).strip(),
        "body": str(body).strip(),
        "tag": cfg["tag"],
        "createdOn": row.get("createdon")
    }

# --- Routes ---
@app.get("/", response_class=HTMLResponse)
async def home():
    return FileResponse(TEMPLATES_DIR / "index.html")

@app.get("/api/v1/summary/industry-updates")
async def industry_updates(top: int = Query(10)):
    blocks = {}
    
    async def process_industry(ind_key, config):
        items = []
        for t_key in config["tables"]:
            logical = TABLE_MAPPINGS[t_key]["logical"]
            try:
                raw_data = await fetch_dv_data(logical, top)
                for r in raw_data:
                    n = normalize(r, t_key)
                    if n: items.append(n)
            except Exception as e:
                print(f"Error fetching {t_key}: {e}")
        
        # Sort combined items by date
        items.sort(key=lambda x: x.get("createdOn", ""), reverse=True)
        blocks[ind_key] = {"items": items}

    await asyncio.gather(*[process_industry(k, v) for k, v in INDUSTRY_CONFIG.items()])
    return {"ok": True, "blocks": blocks}

# --- Middleware & Static ---
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET"])
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
