import os
import time
import asyncio
import logging
import threading
from pathlib import Path
from typing import Any, Dict, Optional
from datetime import datetime, timezone
from contextlib import asynccontextmanager

import httpx
import psycopg2
import psycopg2.extras
import pytz
from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from agent_industry_updater import run_industry_update

# --- Initialization ---
load_dotenv()
BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
TEMPLATES_DIR = BASE_DIR / "templates"
logger = logging.getLogger("jdas_app")

# --- Environment Config ---
TENANT_ID = os.getenv("TENANT_ID") or os.getenv("AZURE_TENANT_ID")
CLIENT_ID = os.getenv("CLIENT_ID") or os.getenv("AZURE_CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET") or os.getenv("AZURE_CLIENT_SECRET")
DATAVERSE_URL = (os.getenv("DATAVERSE_URL") or "").rstrip("/")
API_BASE = f"{DATAVERSE_URL}/api/data/v9.2"

DATAVERSE_ENABLED = all([TENANT_ID, CLIENT_ID, CLIENT_SECRET, DATAVERSE_URL])
BUILD_STAMP = os.getenv("BUILD_STAMP") or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

# --- Dashboard Registry ---
INDUSTRY_CONFIG = {
    "real_estate":            {"label": "Real Estate",              "tables": ["housingmarketinsight", "marketoutlook"]},
    "automotive":             {"label": "Automotive",               "tables": ["vehiclesalesforecast"]},
    "analytics_ops":          {"label": "Analytics & Ops",          "tables": ["analyticsparadigm"]},
    "ai":                     {"label": "AI Developments",          "tables": ["aiindustryinsight"]},
    "market":                 {"label": "Market Insight",           "tables": ["marketinsight", "markettrendinsight", "marketanalysis"]},
}

# --- Column Mappings ---
TABLE_MAPPINGS = {
    "marketinsight":        {"logical": "jdas_marketinsight",        "label": "Market Insight",       "title": "jdas_marketcategory",  "body": "jdas_markettrends",        "tag": "Market"},
    "housingmarketinsight": {"logical": "jdas_housingmarketinsight",  "label": "Housing Market Insight","title": "jdas_insighttheme",    "body": "jdas_currentinsight",      "tag": "Housing"},
    "vehiclesalesforecast": {"logical": "jdas_vehiclesalesforecast",  "label": "Vehicle Sales Forecast","title": "jdas_salesmetric",     "body": "jdas_strategicinsight",    "tag": "Sales"},
    "analyticsparadigm":    {"logical": "jdas_analyticsparadigm",    "label": "Analytics Paradigm",   "title": "jdas_analyticsfocus",  "body": "jdas_significance",        "tag": "Ops"},
    "marketoutlook":        {"logical": "jdas_marketoutlook",        "label": "Market Outlook",        "title": "jdas_category",        "body": "jdas_keydrivers",          "tag": "Outlook"},
    "markettrendinsight":   {"logical": "jdas_markettrendinsight",   "label": "Market Trend Insight",  "title": "jdas_keysignal",       "body": "jdas_trendfor2026",        "tag": "Trends"},
    "marketanalysis":       {"logical": "jdas_marketanalysis",       "label": "Market Analysis",       "title": "jdas_theme",           "body": "jdas_industryreality2026", "tag": "Analysis"},
    "aiindustryinsight":    {
        "logical": "jdas_aiindustryinsight", "label": "AI Industry Insight",
        "title": "jdas_insightcategory", "body": "jdas_assistantperspective", "tag": "AI",
        "dv_fields": {
            "assistant_perspective":    "jdas_assistantperspective",
            "future_unified_view":      "jdas_futureunifiedview",
            "industry_phase_description":"jdas_industryphasedescription",
            "insight_category":         "jdas_insightcategory",
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
    data = {"client_id": CLIENT_ID, "client_secret": CLIENT_SECRET,
            "grant_type": "client_credentials", "scope": f"{DATAVERSE_URL}/.default"}
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
        r = await c.get(url, headers={"Authorization": f"Bearer {token}", "Prefer": "odata.maxpagesize=50"})
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
        "id": row.get(cfg["logical"] + "id"),
        "industry_key": industry_key,
        "table_key": table_key,
        "table": cfg["logical"],
        "table_label": cfg.get("label", table_key),
        "tag": cfg.get("tag", ""),
        "title": str(title).strip(),
        "body": str(body).strip(),
        "createdOn": row.get("createdon") or "",
        "source": {"logical": cfg["logical"], "title_field": title_field, "body_field": body_field}
    }
    for out_key, dv_key in (cfg.get("dv_fields") or {}).items():
        out[out_key] = row.get(dv_key) or ""
    return out

# --- Purge Old Stories ---
def purge_old_stories():
    """Delete published news_events records older than 7 days to keep the dashboard fresh."""
    try:
        with psycopg2.connect(os.environ["INDUSTRY_DB_URL"]) as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    DELETE FROM news_events
                    WHERE published_date < NOW() - INTERVAL '7 days'
                    AND status = 'published'
                """)
                deleted = cur.rowcount
                conn.commit()
        logger.info(f"Purge complete — {deleted} stories older than 7 days removed")
    except Exception as e:
        logger.error(f"purge_old_stories error: {e}")

# Wrapper that purges first, then runs the update agent
def run_update_with_purge():
    purge_old_stories()
    run_industry_update()

# --- App Lifespan (scheduler) ---
@asynccontextmanager
async def lifespan(app):
    central = pytz.timezone("America/Chicago")
    scheduler = AsyncIOScheduler(timezone=central)

    # Morning run — 5:00 AM Central
    scheduler.add_job(
        lambda: threading.Thread(target=run_update_with_purge, daemon=True).start(),
        CronTrigger(hour=5, minute=0, timezone=central),
        id="industry_update_morning",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=300,
    )

    # Evening run — 5:00 PM Central
    scheduler.add_job(
        lambda: threading.Thread(target=run_update_with_purge, daemon=True).start(),
        CronTrigger(hour=17, minute=0, timezone=central),
        id="industry_update_evening",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=300,
    )

    scheduler.start()
    logger.info("JDAS Industry Update Agent scheduled — 5:00 AM & 5:00 PM Central daily")
    yield
    scheduler.shutdown()

# --- App Instance ---
app = FastAPI(title="JDAS Analytics API", version="3.0.0", lifespan=lifespan)

# --- Pydantic Models ---
class PublishRequest(BaseModel):
    record_id: str

# --- Auth Helper ---
def verify_secret(x_agent_secret: str = Header(default="")):
    expected = os.environ.get("AGENT_SECRET", "")
    if not expected or x_agent_secret != expected:
        raise HTTPException(status_code=401, detail="Unauthorized")

# --- Existing Routes ---
@app.get("/", response_class=HTMLResponse)
async def home():
    index_path = TEMPLATES_DIR / "index.html"
    if not index_path.exists():
        return HTMLResponse("<h1>Backend Running</h1><p>No index.html found in /templates</p>")
    return FileResponse(index_path, headers={
        "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
        "Pragma": "no-cache", "Expires": "0",
    })

@app.get("/api/v1/health")
async def health():
    return {"ok": True, "dataverse_enabled": DATAVERSE_ENABLED, "build_stamp": BUILD_STAMP, "version": app.version}

@app.get("/api/v1/config")
async def config():
    industries = []
    for ind_key, ind_cfg in INDUSTRY_CONFIG.items():
        industries.append({
            "key": ind_key, "label": ind_cfg["label"],
            "tables": [{"key": t_key, "label": TABLE_MAPPINGS.get(t_key, {}).get("label", t_key),
                        "logical": TABLE_MAPPINGS.get(t_key, {}).get("logical", ""),
                        "tag": TABLE_MAPPINGS.get(t_key, {}).get("tag", "")}
                       for t_key in ind_cfg["tables"]]
        })
    return {"ok": True, "build_stamp": BUILD_STAMP, "dataverse_enabled": DATAVERSE_ENABLED, "industries": industries}

@app.get("/api/v1/summary/industry-updates")
async def industry_updates(top: int = Query(10)):
    blocks: Dict[str, Dict[str, Any]] = {}
    async def process_industry(ind_key: str, config: Dict[str, Any]):
        tables_out: Dict[str, Any] = {}
        async def process_table(t_key: str):
            cfg = TABLE_MAPPINGS[t_key]
            raw = await fetch_dv_data(cfg["logical"], top)
            items = [n for r in raw if (n := normalize(r, t_key, ind_key))]
            items.sort(key=lambda x: x.get("createdOn", "") or "", reverse=True)
            tables_out[t_key] = {"label": cfg.get("label", t_key), "logical": cfg["logical"], "tag": cfg.get("tag", ""), "items": items}
        await asyncio.gather(*[process_table(t_key) for t_key in config["tables"]])
        blocks[ind_key] = {"label": config.get("label", ind_key), "tables": tables_out}
    await asyncio.gather(*[process_industry(k, v) for k, v in INDUSTRY_CONFIG.items()])
    return {"ok": True, "blocks": blocks}

# ─────────────────────────────────────────────────────────────────
# Industry Agent Endpoints
# ─────────────────────────────────────────────────────────────────

@app.post("/publish-update")
def publish_update(payload: PublishRequest, x_agent_secret: str = Header(default="")):
    verify_secret(x_agent_secret)
    try:
        with psycopg2.connect(os.environ["INDUSTRY_DB_URL"]) as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE news_events SET status = 'published'
                    WHERE record_id = %s
                    RETURNING record_id, headline, category_slug
                """, (payload.record_id,))
                row = cur.fetchone()
                conn.commit()
        if row:
            return {"success": True, "record_id": row[0], "headline": row[1], "category": row[2]}
        return {"error": "record_id not found"}
    except Exception as e:
        logger.error(f"publish_update error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/publish-all-drafts")
def publish_all_drafts(x_agent_secret: str = Header(default="")):
    verify_secret(x_agent_secret)
    try:
        with psycopg2.connect(os.environ["INDUSTRY_DB_URL"]) as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE news_events SET status = 'published'
                    WHERE status = 'draft'
                    RETURNING record_id, category_slug
                """)
                rows = cur.fetchall()
                conn.commit()
        return {
            "success": True,
            "published": len(rows),
            "records": [{"record_id": r[0], "category": r[1]} for r in rows]
        }
    except Exception as e:
        logger.error(f"publish_all_drafts error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/approve-all")
def approve_all(secret: str = ""):
    expected = os.environ.get("AGENT_SECRET", "")
    if not expected or secret != expected:
        return HTMLResponse("""
        <html><body style="font-family:Arial,sans-serif;max-width:500px;margin:60px auto;text-align:center;">
          <h2 style="color:#c62828;">Unauthorized</h2>
          <p style="color:#555;">Invalid or missing secret key.</p>
        </body></html>
        """, status_code=401)
    try:
        with psycopg2.connect(os.environ["INDUSTRY_DB_URL"]) as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE news_events SET status = 'published'
                    WHERE status = 'draft'
                    RETURNING record_id, headline, category_slug
                """)
                rows = cur.fetchall()
                conn.commit()

        count = len(rows)
        categories = list({r[2] for r in rows})
        cat_list = "".join(f"<li>{c.replace('_', ' ').title()}</li>" for c in sorted(categories))
        record_list = "".join(
            f'<li style="font-size:13px;color:#555;margin-bottom:4px;">{r[1]}</li>'
            for r in rows
        )

        return HTMLResponse(f"""
        <html><body style="font-family:Arial,sans-serif;max-width:600px;margin:60px auto;">
          <div style="text-align:center;margin-bottom:32px;">
            <div style="font-size:48px;">&#10003;</div>
            <h2 style="color:#2e7d32;margin:8px 0;">Published Successfully</h2>
            <p style="color:#555;">{count} update{"s" if count != 1 else ""} are now live on your dashboard.</p>
          </div>
          <div style="background:#f9f9f9;border-radius:8px;padding:20px;margin-bottom:20px;">
            <p style="margin:0 0 8px;font-weight:600;color:#1a3c6e;">Categories updated:</p>
            <ul style="margin:0;padding-left:20px;color:#333;">{cat_list}</ul>
          </div>
          <div style="background:#f9f9f9;border-radius:8px;padding:20px;margin-bottom:24px;">
            <p style="margin:0 0 8px;font-weight:600;color:#1a3c6e;">Published headlines:</p>
            <ul style="margin:0;padding-left:20px;">{record_list}</ul>
          </div>
          <div style="text-align:center;">
            <a href="https://jdas-backend.onrender.com"
               style="background:#1a3c6e;color:white;padding:12px 28px;border-radius:6px;
                      text-decoration:none;font-weight:600;display:inline-block;">
              View Live Dashboard
            </a>
          </div>
          <p style="text-align:center;color:#aaa;font-size:12px;margin-top:24px;">
            JDAS Analytics &amp; Solutions — Tailored Industry Updates
          </p>
        </body></html>
        """)

    except Exception as e:
        logger.error(f"approve_all error: {e}")
        return HTMLResponse(f"""
        <html><body style="font-family:Arial,sans-serif;max-width:500px;margin:60px auto;text-align:center;">
          <h2 style="color:#c62828;">Something went wrong</h2>
          <p style="color:#555;">{str(e)}</p>
        </body></html>
        """, status_code=500)


@app.get("/get-updates")
def get_updates(category: str = None, limit: int = 50):
    limit = min(max(1, limit), 200)
    try:
        with psycopg2.connect(os.environ["INDUSTRY_DB_URL"]) as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                if category:
                    cur.execute("""
                        SELECT n.record_id, n.category_slug, n.subtopic,
                               n.headline, n.summary, n.business_impact,
                               n.published_date, n.source_name, n.source_url,
                               n.directional_signal, n.volatility_flag,
                               n.geo_scope, n.country_code,
                               ARRAY(SELECT tag FROM event_tags WHERE record_id = n.record_id ORDER BY tag) as tags
                        FROM news_events n
                        WHERE n.status = 'published' AND n.category_slug = %s
                        ORDER BY n.published_date DESC, n.created_at DESC
                        LIMIT %s
                    """, (category, limit))
                else:
                    cur.execute("""
                        SELECT n.record_id, n.category_slug, n.subtopic,
                               n.headline, n.summary, n.business_impact,
                               n.published_date, n.source_name, n.source_url,
                               n.directional_signal, n.volatility_flag,
                               n.geo_scope, n.country_code,
                               ARRAY(SELECT tag FROM event_tags WHERE record_id = n.record_id ORDER BY tag) as tags
                        FROM news_events n
                        WHERE n.status = 'published'
                        ORDER BY n.published_date DESC, n.created_at DESC
                        LIMIT %s
                    """, (limit,))
                rows = cur.fetchall()
        return {"count": len(rows), "updates": [dict(r) for r in rows]}
    except Exception as e:
        logger.error(f"get_updates error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/trigger-update")
async def trigger_update(x_agent_secret: str = Header(default="")):
    verify_secret(x_agent_secret)
    thread = threading.Thread(target=run_update_with_purge, daemon=True)
    thread.start()
    return {"success": True, "message": "Agent triggered — check email in ~3 minutes"}

# --- Middleware & Static ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
