# app.py — JDAS Optimized Industry Updates Backend
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

# --- Configuration & Environment ---
load_dotenv()
BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
TEMPLATES_DIR = BASE_DIR / "templates"

app = FastAPI(title="JDAS Analytics API", version="2.0.0")

# --- Constants & Dataverse Config ---
DATAVERSE_URL = (os.getenv("DATAVERSE_URL") or "").rstrip("/")
TENANT_ID = os.getenv("TENANT_ID")
CLIENT_ID = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")
DATAVERSE_ENABLED = all([TENANT_ID, CLIENT_ID, CLIENT_SECRET, DATAVERSE_URL])

# --- Dashboard Mapping (UI Logic) ---
# This ensures the backend and frontend speak the same 'Industry' language
INDUSTRY_CONFIG = {
    "real_estate": {
        "label": "Real Estate",
        "tables": ["housingmarketinsight", "marketoutlook"],
        "accent": "#2563eb" # Blue
    },
    "automotive": {
        "label": "Automotive",
        "tables": ["vehiclesalesforecast"],
        "accent": "#475569" # Slate
    },
    "analytics_ops": {
        "label": "Analytics & Ops",
        "tables": ["analyticsparadigm"],
        "accent": "#7c3aed" # Violet
    },
    "ai": {
        "label": "AI Developments",
        "tables": ["aiindustryinsight"],
        "accent": "#db2777" # Pink
    },
    "market": {
        "label": "Market Insight",
        "tables": ["marketinsight", "markettrendinsight", "marketanalysis"],
        "accent": "#059669" # Emerald
    }
}

# Mapping Dataverse logical names to friendly names and UI fields
TABLE_REGISTRY = {
    "marketinsight": {"logical": "jdas_marketinsight", "title": "jdas_marketcategory", "body": "jdas_markettrends", "tag": "Market"},
    "housingmarketinsight": {"logical": "jdas_housingmarketinsight", "title": "jdas_insighttheme", "body": "jdas_currentinsight", "tag": "Housing"},
    "vehiclesalesforecast": {"logical": "jdas_vehiclesalesforecast", "title": "jdas_salesmetric", "body": "jdas_strategicinsight", "tag": "Sales"},
    "analyticsparadigm": {"logical": "jdas_analyticsparadigm", "title": "jdas_analyticsfocus", "body": "jdas_significance", "tag": "Ops"},
    "marketoutlook": {"logical": "jdas_marketoutlook", "title": "jdas_category", "body": "jdas_keydrivers", "tag": "Outlook"},
    "markettrendinsight": {"logical": "jdas_markettrendinsight", "title": "jdas_keysignal", "body": "jdas_trendfor2026", "tag": "Trends"},
    "marketanalysis": {"logical": "jdas_marketanalysis", "title": "jdas_theme", "body": "jdas_industryreality2026", "tag": "Analysis"},
    "aiindustryinsight": {"logical": "jdas_aiindustryinsight", "title": "jdas_insightcategory", "body": "jdas_assistantperspective", "tag": "AI"},
}

# --- Shared Utilities (Caching/Client) ---
client = None
table_cache = {}
CACHE_TTL = 300 # 5 minutes

async def get_client():
    global client
    if client is None: client = httpx.AsyncClient(timeout=15.0)
    return client

async def get_access_token():
    # ... logic stays largely same as your original ...
    # Simplified for space; assume your original token logic here
    pass

# --- Core Logic: Normalization ---
def normalize_row(row: dict, table_key: str) -> Optional[dict]:
    """Transforms raw Dataverse JSON into clean UI Cards."""
    cfg = TABLE_REGISTRY.get(table_key)
    if not cfg: return None
    
    # Extract data with fallbacks to empty strings (prevents 'None' appearing in UI)
    title = row.get(cfg["title"]) or row.get("jdas_name") or "Untitled Update"
    body = row.get(cfg["body"]) or row.get("jdas_description") or ""
    tag = cfg.get("tag", "General")
    
    return {
        "id": row.get(f"{cfg['logical']}id"),
        "table": cfg["logical"],
        "title": str(title).strip(),
        "body": str(body).strip(),
        "tag": tag,
        "createdOn": row.get("createdon")
    }

# --- API Endpoints ---

@app.get("/", response_class=HTMLResponse)
def home():
    return FileResponse(str(TEMPLATES_DIR / "index.html"))

@app.get("/api/v1/summary/industry-updates")
async def industry_updates(top: int = 10):
    """Main dashboard data provider."""
    blocks = {}
    
    async def fetch_industry(key, config):
        industry_items = []
        for t_key in config["tables"]:
            # Logic: Fetch from Dataverse (Simplified for this snippet)
            # In your real code, call your existing dv_paged_get logic here
            raw_rows = [] # Placeholder for actual DV fetch
            
            # Normalize and add to list
            for r in raw_rows:
                norm = normalize_row(r, t_key)
                if norm: industry_items.append(norm)
        
        blocks[key] = {
            "label": config["label"],
            "accent": config["accent"],
            "items": industry_items
        }

    # Parallel execution for speed
    await asyncio.gather(*[fetch_industry(k, v) for k, v in INDUSTRY_CONFIG.items()])
    
    return {"ok": True, "blocks": blocks}

# --- Static Mounting & Lifecycle ---
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
