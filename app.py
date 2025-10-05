# app.py — JDAS backend (serve index.html + Dataverse API)
import os
import time
from pathlib import Path
from typing import Dict, List, Optional
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

app = FastAPI(title="JDAS Dataverse API", version="0.1.0")

# Serve /static/* from ./static (absolute)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# Serve the SPA/HTML (with a tiny fallback if index is missing)
@app.get("/", response_class=HTMLResponse)
def home():
  index_path = TEMPLATES_DIR / "index.html"
  if index_path.exists():
    return FileResponse(str(index_path))
  return HTMLResponse("<h1>JDAS</h1><p>templates/index.html not found.</p>", status_code=200)

# -------------------------
# Env & constants
# -------------------------
load_dotenv()

TENANT_ID      = os.getenv("TENANT_ID")
CLIENT_ID      = os.getenv("CLIENT_ID")
CLIENT_SECRET  = os.getenv("CLIENT_SECRET")
DATAVERSE_URL  = os.getenv("DATAVERSE_URL")  # e.g. https://yourorg.crm.dynamics.com
ALLOW_ORIGINS  = os.getenv("ALLOW_ORIGINS", "*").split(",")

DATAVERSE_ENABLED = all([TENANT_ID, CLIENT_ID, CLIENT_SECRET, DATAVERSE_URL])

TOKEN_URL = f"https://login.microsoftonline.com/{TENANT_ID}/oauth2/v2.0/token" if DATAVERSE_ENABLED else None
SCOPE     = f"{DATAVERSE_URL}/.default" if DATAVERSE_ENABLED else None

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

# -------------------------
# Dataverse helpers (guarded)
# -------------------------
_token_cache: Dict[str, str] = {}
_token_expiry_ts: float = 0.0
_SKEW = 60  # seconds

async def fetch_access_token() -> str:
  if not DATAVERSE_ENABLED:
    raise HTTPException(503, "Dataverse env not configured")
  data = {
    "client_id": CLIENT_ID,
    "client_secret": CLIENT_SECRET,
    "grant_type": "client_credentials",
    "scope": SCOPE,
  }
  async with httpx.AsyncClient(timeout=30) as c:
    r = await c.post(TOKEN_URL, data=data)
    if r.status_code != 200:
      raise HTTPException(500, f"Token error: {r.text}")
    j = r.json()
    tok = j["access_token"]
    expires_in = int(j.get("expires_in", 3600))
    global _token_expiry_ts
    _token_expiry_ts = time.time() + max(60, expires_in - _SKEW)
    _token_cache["token"] = tok
    return tok

async def get_access_token() -> str:
  if not DATAVERSE_ENABLED:
    raise HTTPException(503, "Dataverse env not configured")
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
  }

async def dv_paged_get(path: str) -> List[dict]:
  if not DATAVERSE_ENABLED:
    raise HTTPException(503, "Dataverse env not configured")
  async def _run(url: str, headers: Dict[str, str]) -> httpx.Response:
    async with httpx.AsyncClient(timeout=60) as c:
      return await c.get(url, headers=headers)

  next_url = path if path.startswith("http") else f"{DATAVERSE_URL}/api/data/v9.2/{path}"
  token = await get_access_token()
  headers = build_headers(token)
  out: List[dict] = []

  while True:
    r = await _run(next_url, headers)
    if r.status_code == 401:
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

def build_select(
  entity_set: str,
  columns: List[str],
  orderby: Optional[str] = None,
  top: int = 5000,
  extra: Optional[str] = None,
) -> str:
  params = {"$select": ",".join(columns), "$top": str(top)}
  if orderby:
    params["$orderby"] = orderby
  qs = urlencode(params)
  return f"{entity_set}?{qs}" + (f"&{extra}" if extra else "")

# -------------------------
# TABLE CONFIG
# -------------------------
TABLES = [
  {
    "name": "Company Investment",
    "entity_set": "cred8_companyinvestments",
    "path": "/api/company-investments",
    "columns": ["cred8_companyname", "cred8_investmentnotes"],
    "map_to": ["companyName", "investmentNotes"],
    "orderby": "cred8_companyname asc",
  },
  {
    "name": "Bankruptcy Log",
    "entity_set": "cred8_bankruptcylogs",
    "path": "/api/bankruptcies",
    "columns": ["cred8_company", "cred8_datelogged"],
    "map_to": ["company", "dateLogged"],
    "orderby": "cred8_datelogged desc",
  },
  {
    "name": "Layoff Tracking",
    "entity_set": "cred8_layoffannouncements",
    "path": "/api/layoffs",
    "columns": ["cred8_announcementdate", "cred8_companyname"],
    "map_to": ["announcementDate", "companyName"],
    "orderby": "cred8_announcementdate desc",
  },
  {
    "name": "Tariff % by Country",
    "entity_set": "cred8_tariffbycountries",
    "path": "/api/tariff-by-country",
    "columns": ["cred8_country", "cred8_tariffrateasofaug1"],
    "map_to": ["country", "tariffRateAsOfAug1"],
    "orderby": "cred8_country asc",
  },
]

# -------------------------
# Route factory (register endpoints)
# -------------------------
def make_handler(entity_set: str, cols: List[str], keys: List[str], default_order: Optional[str]):
  async def handler(
    top: int = Query(5000, ge=1, le=50000, description="$top limit"),
    orderby: Optional[str] = Query(None, description="Override $orderby"),
  ):
    if not DATAVERSE_ENABLED:
      raise HTTPException(503, "Dataverse env not configured")
    query = build_select(entity_set, cols, orderby or default_order, top=top)
    rows = await dv_paged_get(query)
    shaped = [{k: r.get(c) for c, k in zip(cols, keys)} for r in rows]
    return JSONResponse(content=shaped)
  return handler

for cfg in TABLES:
  app.get(cfg["path"], name=cfg["name"])(
    make_handler(cfg["entity_set"], cfg["columns"], cfg["map_to"], cfg.get("orderby"))
  )

# -------------------------
# Metadata utility
# -------------------------
@app.get("/api/metadata", summary="List available resources")
async def list_resources():
  return [
    {"name": t["name"], "path": t["path"], "entity_set": t["entity_set"], "columns": t["columns"]}
    for t in TABLES
  ]
