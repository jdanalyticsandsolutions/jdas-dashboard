"""
JDAS Industry Update Agent
Runs twice daily at 5:00 AM and 5:00 PM Central via APScheduler.
Searches news for all 10 categories, summarizes via Claude API,
saves drafts to PostgreSQL, emails digest + Chatbase .txt to Jason.
Stories older than 7 days are automatically purged before each run (handled in app.py).
"""

import json
import logging
import os
import re
import smtplib
import time
import uuid
from dataclasses import dataclass
from datetime import date, datetime
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any

import anthropic
import psycopg2
import psycopg2.extras

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("industry_agent")


@dataclass(frozen=True)
class Settings:
    industry_db_url: str
    anthropic_api_key: str
    gmail_address: str
    gmail_app_password: str
    agent_secret: str


def load_settings() -> Settings:
    return Settings(
        industry_db_url=os.environ["INDUSTRY_DB_URL"],
        anthropic_api_key=os.environ["ANTHROPIC_API_KEY"],
        gmail_address=os.environ["GMAIL_ADDRESS"],
        gmail_app_password=os.environ["GMAIL_APP_PASSWORD"],
        agent_secret=os.environ.get("AGENT_SECRET", ""),
    )


CATEGORIES = [
    {"slug": "real_estate",            "label": "Real Estate"},
    {"slug": "automotive",             "label": "Automotive"},
    {"slug": "analytics_ops",          "label": "Analytics & Ops"},
    {"slug": "ai_developments",        "label": "AI Developments"},
    {"slug": "market_insight",         "label": "Market Insight"},
    {"slug": "supply_chain_logistics", "label": "Supply Chain & Logistics"},
    {"slug": "labor_workforce_trends", "label": "Labor & Workforce Trends"},
    {"slug": "energy_commodities",     "label": "Energy & Commodities"},
    {"slug": "policy_regulation",      "label": "Policy & Regulation"},
    {"slug": "small_business_pulse",   "label": "Small Business Pulse"},
]

DIRECTIONAL_SIGNALS = [
    "positive", "mixed_positive", "neutral", "mixed",
    "mixed_negative", "negative", "risk_off", "tight_labor_market",
]

VALID_SOURCE_TYPES = {"wire_service", "government", "trade_org", "financial_press"}
VALID_GEO_SCOPES   = {"national", "international", "regional", "global"}


def extract_text_from_response(response: Any) -> str:
    parts: list[str] = []
    for block in getattr(response, "content", []):
        text = getattr(block, "text", None)
        if block.type == "text" and text:
            parts.append(text)
    return "".join(parts).strip()


def parse_date(value: Any) -> str:
    if not value:
        return date.today().isoformat()
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).date().isoformat()
        except ValueError:
            try:
                return datetime.strptime(value, "%Y-%m-%d").date().isoformat()
            except ValueError:
                return date.today().isoformat()
    return date.today().isoformat()


def normalize_source_type(value: Any) -> str:
    return str(value) if value in VALID_SOURCE_TYPES else "wire_service"


def normalize_geo_scope(value: Any) -> str:
    return str(value) if value in VALID_GEO_SCOPES else "global"


def normalize_record(raw: dict[str, Any], category: dict[str, str]) -> dict[str, Any]:
    return {
        "slug":               category["slug"],
        "label":              category["label"],
        "headline":           str(raw.get("headline", "")).strip(),
        "subtopic":           raw.get("subtopic"),
        "summary":            str(raw.get("summary", "")).strip(),
        "business_impact":    str(raw.get("business_impact", "")).strip(),
        "directional_signal": raw.get("directional_signal", "neutral")
                              if raw.get("directional_signal") in DIRECTIONAL_SIGNALS
                              else "neutral",
        "volatility_flag":    bool(raw.get("volatility_flag", False)),
        "source_name":        raw.get("source_name"),
        "source_url":         raw.get("source_url"),
        "source_type":        normalize_source_type(raw.get("source_type")),
        "geo_scope":          normalize_geo_scope(raw.get("geo_scope")),
        "country_code":       raw.get("country_code") or "MULTI",
        "verification_status":raw.get("verification_status", "reported"),
        "published_date":     parse_date(raw.get("published_date")),
        "tags":               [
            str(tag).strip()
            for tag in raw.get("tags", [])
            if isinstance(tag, str) and str(tag).strip()
        ][:4],
    }


def fetch_updates_for_category(
    client: anthropic.Anthropic, category: dict[str, str]
) -> list[dict[str, Any]]:
    today = date.today().isoformat()
    prompt = f"""
You are a business intelligence analyst for JDAS Analytics & Solutions,
a consulting firm serving small and rural business owners.

Search for the top 2-3 most important news stories published today or
in the last 48 hours for this category: {category['label']}

For each story return a JSON object with exactly these fields:
- headline: concise factual headline (max 15 words)
- subtopic: snake_case subtopic label (e.g. oil_price_level, fed_policy)
- summary: 2-3 sentence factual summary, no fluff
- business_impact: 1 sentence on what this means for small business owners
- directional_signal: one of {DIRECTIONAL_SIGNALS}
- volatility_flag: true or false
- source_name: name of the publication or agency
- source_url: direct URL to the article if available, otherwise null
- source_type: one of wire_service, government, trade_org, financial_press
- geo_scope: one of national, international, regional, global
- country_code: 2-letter ISO code or MULTI or GULF
- published_date: article publication date in YYYY-MM-DD when available
- tags: list of 2-4 relevant snake_case tags

Return ONLY a valid JSON array of objects. No explanation, no markdown.
If no significant news exists for this category today, return an empty array [].
Today's date: {today}
"""

    try:
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=2000,
            tools=[{"type": "web_search_20250305", "name": "web_search"}],
            messages=[{"role": "user", "content": prompt}],
        )
    except Exception as exc:
        logger.error("Anthropic API error for %s: %s", category["label"], exc)
        return []

    raw_text = extract_text_from_response(response)
    if not raw_text:
        logger.warning("No text response for %s", category["label"])
        return []

    clean = re.sub(r"```json|```", "", raw_text).strip()

    # Find JSON array even if Claude adds preamble text
    match = re.search(r"\[.*\]", clean, re.DOTALL)
    if not match:
        logger.warning("No JSON array found for %s", category["label"])
        return []

    try:
        records = json.loads(match.group())
        if not isinstance(records, list):
            return []
        normalized = [
            normalize_record(r, category)
            for r in records
            if isinstance(r, dict)
        ]
        valid = [r for r in normalized if r["headline"] and r["summary"]]
        logger.info("  %s: %d stories found", category["label"], len(valid))
        return valid
    except Exception as exc:
        logger.error("JSON parse error for %s: %s", category["label"], exc)
        return []


def save_drafts(
    settings: Settings, records: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    inserted_records: list[dict[str, Any]] = []

    with psycopg2.connect(settings.industry_db_url) as conn:
        with conn.cursor() as cur:
            for item in records:
                record_id = (
                    f"{item['slug']}_{item['published_date'].replace('-', '_')}"
                    f"_{uuid.uuid4().hex[:12]}"
                )
                try:
                    cur.execute("SAVEPOINT before_record_insert")
                    cur.execute(
                        """
                        INSERT INTO news_events (
                            record_id, category_slug, subtopic, headline, summary,
                            business_impact, published_date, created_at, geo_scope,
                            country_code, source_name, source_url, source_type,
                            verification_status, directional_signal, volatility_flag,
                            status
                        ) VALUES (
                            %s, %s, %s, %s, %s,
                            %s, %s, NOW(), %s,
                            %s, %s, %s, %s,
                            %s, %s, %s,
                            'draft'
                        )
                        ON CONFLICT (record_id) DO NOTHING
                        """,
                        (
                            record_id,
                            item["slug"],
                            item.get("subtopic"),
                            item.get("headline"),
                            item.get("summary"),
                            item.get("business_impact"),
                            item["published_date"],
                            item.get("geo_scope"),
                            item.get("country_code"),
                            item.get("source_name"),
                            item.get("source_url"),
                            item.get("source_type"),
                            item.get("verification_status", "reported"),
                            item.get("directional_signal", "neutral"),
                            item.get("volatility_flag", False),
                        ),
                    )

                    for tag in item.get("tags", []):
                        cur.execute(
                            """
                            INSERT INTO event_tags (record_id, tag)
                            VALUES (%s, %s)
                            ON CONFLICT (record_id, tag) DO NOTHING
                            """,
                            (record_id, tag),
                        )

                    cur.execute("RELEASE SAVEPOINT before_record_insert")
                    inserted_item = dict(item)
                    inserted_item["record_id"] = record_id
                    inserted_records.append(inserted_item)
                    logger.info("Drafted: %s", record_id)

                except Exception as exc:
                    logger.error("DB insert error for %s: %s", record_id, exc)
                    cur.execute("ROLLBACK TO SAVEPOINT before_record_insert")

        conn.commit()

    logger.info("Saved %d/%d records to PostgreSQL", len(inserted_records), len(records))
    return inserted_records


def generate_chatbase_doc(records: list[dict[str, Any]]) -> str:
    now = datetime.now()
    run_label = "Morning" if now.hour < 12 else "Evening"
    today = date.today().strftime("%B %d, %Y")
    lines = [
        f"JDAS TAILORED INDUSTRY UPDATES -- {today} ({run_label} Edition)",
        "Generated by JDAS Industry Update Agent",
        "=" * 60,
        "",
        "This document contains the latest industry intelligence across",
        "10 categories tracked by JDAS Analytics & Solutions.",
        "Use this to answer client questions about current business trends.",
        "",
    ]

    by_category: dict[str, list[dict[str, Any]]] = {}
    for item in records:
        by_category.setdefault(item["label"], []).append(item)

    for label, items in by_category.items():
        if not items:
            continue
        lines += ["=" * 60, f"CATEGORY: {label.upper()}", "=" * 60]
        for item in items:
            lines += [
                f"\nHeadline: {item.get('headline', 'N/A')}",
                f"Summary: {item.get('summary', 'N/A')}",
                f"Business Impact: {item.get('business_impact', 'N/A')}",
                f"Signal: {item.get('directional_signal', 'N/A')}",
            ]
            if item.get("source_name"):
                lines.append(f"Source: {item['source_name']}")
            if item.get("source_url"):
                lines.append(f"URL: {item['source_url']}")
            lines.append("")

    lines += [
        "=" * 60,
        "END OF JDAS INDUSTRY UPDATE DOCUMENT",
        "Updates run twice daily: 5:00 AM & 5:00 PM Central",
        "Stories older than 7 days are automatically removed.",
    ]
    return "\n".join(lines)


def send_gmail_digest(
    settings: Settings, records: list[dict[str, Any]], chatbase_txt: str
):
    now = datetime.now()
    run_label = "Morning" if now.hour < 12 else "Evening"
    today = date.today().strftime("%B %d, %Y")
    total = len(records)

    # One-click approve URL
    approve_url = (
        f"https://jdas-backend.onrender.com/approve-all"
        f"?secret={settings.agent_secret}"
    )

    signal_colors = {
        "positive":           "#2e7d32",
        "mixed_positive":     "#558b2f",
        "neutral":            "#757575",
        "mixed":              "#f57c00",
        "mixed_negative":     "#e65100",
        "negative":           "#c62828",
        "risk_off":           "#6a1b9a",
        "tight_labor_market": "#1565c0",
    }

    by_category: dict[str, list[dict[str, Any]]] = {}
    for item in records:
        by_category.setdefault(item["label"], []).append(item)

    html_parts = [f"""
<html><body style="font-family:Arial,sans-serif;max-width:700px;margin:0 auto;">
<h2 style="color:#1a3c6e;">JDAS Industry Update Digest — {today} ({run_label})</h2>
<p style="color:#555;">
  <strong>{total} new draft records</strong> saved and verified in PostgreSQL.
  Review below then publish.
</p>

<div style="margin:20px 0;padding:20px;background:#e8f5e9;border-radius:8px;
     border-left:4px solid #2e7d32;text-align:center;">
  <p style="margin:0 0 6px;font-weight:600;color:#1b5e20;font-size:16px;">
    Ready to publish all {total} updates?
  </p>
  <p style="margin:0 0 16px;font-size:13px;color:#2e7d32;">
    Click the button below — opens in your browser and publishes everything instantly.
  </p>
  <a href="{approve_url}"
     style="background:#1a3c6e;color:white;padding:12px 32px;border-radius:6px;
            text-decoration:none;font-weight:600;font-size:15px;display:inline-block;">
    Publish All Updates
  </a>
  <p style="margin:12px 0 0;font-size:11px;color:#888;">
    This link is unique to your account. Do not forward this email.
  </p>
</div>

<hr style="border:1px solid #eee;margin:20px 0;">
"""]

    for label, items in by_category.items():
        if not items:
            continue
        html_parts.append(
            f'<h3 style="color:#1a3c6e;border-bottom:2px solid #1a3c6e;'
            f'padding-bottom:4px;">{label}</h3>'
        )
        for item in items:
            signal  = item.get("directional_signal", "neutral")
            color   = signal_colors.get(signal, "#757575")
            vol_tag = "&#9888; Volatile " if item.get("volatility_flag") else ""
            rid     = item.get("record_id", "")

            if item.get("source_url"):
                src = (
                    f'<a href="{item["source_url"]}" style="color:#1a3c6e;">'
                    f'{item.get("source_name", "Source")}</a>'
                )
            elif item.get("source_name"):
                src = item["source_name"]
            else:
                src = ""

            html_parts.append(f"""
<div style="background:#f9f9f9;border-left:4px solid {color};
     padding:12px;margin-bottom:12px;border-radius:4px;">
  <strong>{item.get('headline', '')}</strong>
  <span style="color:{color};font-size:12px;margin-left:8px;">
    {signal.replace('_', ' ').upper()}
  </span>
  <span style="color:#e65100;font-size:12px;margin-left:6px;">{vol_tag}</span>
  <p style="margin:6px 0;color:#333;">{item.get('summary', '')}</p>
  <p style="margin:4px 0;color:#555;font-size:13px;">
    <strong>Impact:</strong> {item.get('business_impact', '')}
  </p>
  <p style="margin:4px 0;color:#888;font-size:12px;">{src}</p>
  <p style="margin:2px 0;color:#bbb;font-size:11px;">record_id: {rid}</p>
</div>
""")

    html_parts.append("""
<hr style="border:1px solid #eee;">
<p style="color:#888;font-size:12px;">
  JDAS Industry Update Agent — runs at 5:00 AM &amp; 5:00 PM Central<br>
  Stories older than 7 days are automatically removed from the dashboard.<br>
  Chatbase training document attached. Upload to your bot after review.
</p>
</body></html>
""")

    msg = MIMEMultipart("mixed")
    msg["From"]    = settings.gmail_address
    msg["To"]      = settings.gmail_address
    msg["Subject"] = f"JDAS Industry Updates ({run_label}) — {total} new drafts — {today}"
    msg.attach(MIMEText("".join(html_parts), "html"))

    attachment = MIMEBase("application", "octet-stream")
    attachment.set_payload(chatbase_txt.encode("utf-8"))
    encoders.encode_base64(attachment)
    attachment.add_header(
        "Content-Disposition",
        f'attachment; filename="jdas_chatbase_{date.today().isoformat()}_{run_label.lower()}.txt"',
    )
    msg.attach(attachment)

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(settings.gmail_address, settings.gmail_app_password)
            server.sendmail(
                settings.gmail_address,
                settings.gmail_address,
                msg.as_string(),
            )
        logger.info("Gmail digest sent successfully (%s run)", run_label)
    except Exception as exc:
        logger.error("Gmail send error: %s", exc)


def run_industry_update():
    now = datetime.now()
    run_label = "Morning" if now.hour < 12 else "Evening"

    logger.info("=" * 50)
    logger.info("JDAS Industry Update Agent starting... (%s run)", run_label)
    logger.info("Run date: %s", date.today().isoformat())
    logger.info("=" * 50)

    settings = load_settings()
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    all_records: list[dict[str, Any]] = []

    for i, category in enumerate(CATEGORIES):
        logger.info("Fetching: %s", category["label"])
        try:
            updates = fetch_updates_for_category(client, category)
            all_records.extend(updates)
        except Exception as exc:
            logger.error("Error fetching %s: %s", category["label"], exc)

        # Pause between categories to stay under Anthropic's 30k token/min rate limit
        if i < len(CATEGORIES) - 1:
            logger.info("  Pausing 5s before next category...")
            time.sleep(5)

    logger.info("Total fetched: %d records", len(all_records))

    if not all_records:
        logger.warning("No records found — skipping email (%s run)", run_label)
        return

    inserted_records = save_drafts(settings, all_records)

    if not inserted_records:
        logger.warning("No records inserted — skipping email (%s run)", run_label)
        return

    chatbase_txt = generate_chatbase_doc(inserted_records)
    send_gmail_digest(settings, inserted_records, chatbase_txt)

    logger.info("Agent complete. %d drafts ready for review. (%s run)", len(inserted_records), run_label)


if __name__ == "__main__":
    run_industry_update()
