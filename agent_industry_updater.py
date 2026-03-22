"""
JDAS Industry Update Agent — Production Safe
Runs daily at 5am Central via APScheduler.
Searches news for all 10 categories, summarizes via Claude API,
saves drafts to PostgreSQL, emails digest + Chatbase .txt to Jason.

Fixes applied per Codex review:
- Per-record savepoints so one failure never rolls back others
- Email only includes records confirmed inserted to DB
- Robust Claude response parsing handles tool-use blocks
- trigger-update endpoint requires AGENT_SECRET env variable
- All DB connections use context managers (no leaks)
- limit capped at 200
- published_date parsed from Claude response if provided
- run_industry_update runs in thread executor (non-blocking)
"""

import os
import re
import uuid
import json
import smtplib
import logging
from datetime import date, datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders

import anthropic
import psycopg2
import psycopg2.extras

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("industry_agent")

# ─────────────────────────────────────────────
# CONFIG — all values from environment variables
# ─────────────────────────────────────────────
INDUSTRY_DB_URL    = os.environ["INDUSTRY_DB_URL"]
ANTHROPIC_API_KEY  = os.environ["ANTHROPIC_API_KEY"]
GMAIL_ADDRESS      = os.environ["GMAIL_ADDRESS"]
GMAIL_APP_PASSWORD = os.environ["GMAIL_APP_PASSWORD"]
AGENT_SECRET       = os.environ.get("AGENT_SECRET", "")

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
    "mixed_negative", "negative", "risk_off", "tight_labor_market"
]


# ─────────────────────────────────────────────
# STEP 1: SEARCH + SUMMARIZE VIA CLAUDE
# ─────────────────────────────────────────────
def fetch_updates_for_category(client: anthropic.Anthropic, category: dict) -> list[dict]:
    """
    Ask Claude to search for today's top news in a category.
    Handles tool-use response blocks robustly.
    Returns list of record dicts or empty list on failure.
    """
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
- published_date: article publication date in YYYY-MM-DD format if known, otherwise null
- tags: list of 2-4 relevant snake_case tags

Return ONLY a valid JSON array of objects. No explanation, no markdown, no code fences.
If no significant news exists for this category today, return an empty array [].
Today's date: {today}
"""

    try:
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=2000,
            tools=[{"type": "web_search_20250305", "name": "web_search"}],
            messages=[{"role": "user", "content": prompt}]
        )
    except Exception as e:
        logger.error(f"Anthropic API error for {category['label']}: {e}")
        return []

    # Robustly extract text — response may include tool_use and tool_result blocks
    raw_text = ""
    for block in response.content:
        if hasattr(block, "type") and block.type == "text":
            raw_text += block.text

    if not raw_text.strip():
        logger.warning(f"No text content in response for {category['label']}")
        return []

    # Strip markdown fences if present
    clean = re.sub(r"```(?:json)?", "", raw_text).strip()

    # Find JSON array — handles cases where Claude adds preamble text
    match = re.search(r"\[.*\]", clean, re.DOTALL)
    if not match:
        logger.warning(f"No JSON array found for {category['label']}: {clean[:200]}")
        return []

    try:
        records = json.loads(match.group())
        if not isinstance(records, list):
            return []
        logger.info(f"  {category['label']}: {len(records)} stories found")
        return records
    except json.JSONDecodeError as e:
        logger.error(f"JSON parse error for {category['label']}: {e}")
        return []


# ─────────────────────────────────────────────
# STEP 2: SAVE DRAFTS TO POSTGRESQL
# Per-record savepoints — one failure never rolls back others
# Returns only confirmed-inserted record dicts
# ─────────────────────────────────────────────
def save_drafts(records: list[dict]) -> list[dict]:
    """
    Insert records as drafts using per-record savepoints.
    Returns only the records that were actually committed to DB.
    """
    confirmed = []
    today = date.today().isoformat()

    with psycopg2.connect(INDUSTRY_DB_URL) as conn:
        conn.autocommit = False
        with conn.cursor() as cur:
            for item in records:
                record_id = (
                    f"{item['slug']}_{today.replace('-', '_')}"
                    f"_{str(uuid.uuid4())[:12]}"
                )
                try:
                    cur.execute("SAVEPOINT sp1")

                    # Parse published_date from Claude response if available
                    raw_date = item.get("published_date")
                    try:
                        pub_date = (
                            datetime.strptime(raw_date, "%Y-%m-%d").date()
                            if raw_date else date.today()
                        )
                    except (ValueError, TypeError):
                        pub_date = date.today()

                    cur.execute("""
                        INSERT INTO news_events (
                            record_id, category_slug, subtopic, headline,
                            summary, business_impact, published_date,
                            created_at, geo_scope, country_code,
                            source_name, source_url, source_type,
                            verification_status, directional_signal,
                            volatility_flag, status
                        ) VALUES (
                            %s, %s, %s, %s,
                            %s, %s, %s,
                            NOW(), %s, %s,
                            %s, %s, %s,
                            %s, %s,
                            %s, 'draft'
                        )
                        ON CONFLICT (record_id) DO NOTHING
                    """, (
                        record_id,
                        item["slug"],
                        item.get("subtopic"),
                        item.get("headline"),
                        item.get("summary"),
                        item.get("business_impact"),
                        pub_date,
                        item.get("geo_scope"),
                        item.get("country_code"),
                        item.get("source_name"),
                        item.get("source_url"),
                        item.get("source_type"),
                        item.get("verification_status", "reported"),
                        item.get("directional_signal", "neutral"),
                        bool(item.get("volatility_flag", False)),
                    ))

                    for tag in item.get("tags", []):
                        if tag and isinstance(tag, str):
                            cur.execute("""
                                INSERT INTO event_tags (record_id, tag)
                                VALUES (%s, %s)
                                ON CONFLICT (record_id, tag) DO NOTHING
                            """, (record_id, tag.strip()))

                    cur.execute("RELEASE SAVEPOINT sp1")
                    item["_record_id"] = record_id
                    confirmed.append(item)
                    logger.info(f"  Drafted: {record_id}")

                except Exception as e:
                    cur.execute("ROLLBACK TO SAVEPOINT sp1")
                    logger.error(f"  Failed to insert {record_id}: {e}")
                    continue

            conn.commit()

    logger.info(f"Saved {len(confirmed)}/{len(records)} records to PostgreSQL")
    return confirmed


# ─────────────────────────────────────────────
# STEP 3: GENERATE CHATBASE TRAINING DOC
# ─────────────────────────────────────────────
def generate_chatbase_doc(confirmed_records: list[dict]) -> str:
    """
    Returns formatted plain text ready to upload to Chatbase.
    Only includes records confirmed saved to the database.
    """
    today = date.today().strftime("%B %d, %Y")
    total = len(confirmed_records)

    lines = [
        f"JDAS TAILORED INDUSTRY UPDATES — {today}",
        "Generated by JDAS Industry Update Agent",
        "=" * 60,
        "",
        "This document contains the latest industry intelligence across",
        "10 categories tracked by JDAS Analytics & Solutions.",
        "Use this to answer client questions about current business trends.",
        f"Total updates this run: {total}",
        "",
    ]

    by_category: dict[str, list] = {}
    for item in confirmed_records:
        label = item.get("label", item.get("slug", "Unknown"))
        by_category.setdefault(label, []).append(item)

    for label, items in by_category.items():
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
        "Next update: tomorrow at 5:00 AM Central",
    ]
    return "\n".join(lines)


# ─────────────────────────────────────────────
# STEP 4: SEND GMAIL DIGEST
# ─────────────────────────────────────────────
def send_gmail_digest(confirmed_records: list[dict], chatbase_txt: str):
    """
    Sends HTML digest to Jason with Chatbase .txt attached.
    Only reports records confirmed in the database.
    """
    today = date.today().strftime("%B %d, %Y")
    total = len(confirmed_records)

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

    by_category: dict[str, list] = {}
    for item in confirmed_records:
        label = item.get("label", item.get("slug", "Unknown"))
        by_category.setdefault(label, []).append(item)

    html_parts = [f"""
<html><body style="font-family:Arial,sans-serif;max-width:700px;margin:0 auto;">
<h2 style="color:#1a3c6e;">JDAS Industry Update Digest — {today}</h2>
<p style="color:#555;">
  <strong>{total} new draft records</strong> saved and verified in PostgreSQL.
  Review below and publish what looks good.
</p>
<p style="color:#555;font-size:13px;">
  To publish: <code>POST https://jdas-backend.onrender.com/publish-update</code><br>
  Body: <code>{{"record_id": "the_record_id"}}</code><br>
  Header: <code>X-Agent-Secret: [your AGENT_SECRET value]</code>
</p>
<hr style="border:1px solid #eee;">
"""]

    for label, items in by_category.items():
        html_parts.append(
            f'<h3 style="color:#1a3c6e;border-bottom:2px solid #1a3c6e;'
            f'padding-bottom:4px;">{label}</h3>'
        )
        for item in items:
            signal  = item.get("directional_signal", "neutral")
            color   = signal_colors.get(signal, "#757575")
            vol_tag = "&#9888; Volatile " if item.get("volatility_flag") else ""
            rid     = item.get("_record_id", "")

            if item.get("source_url"):
                src = (f'<a href="{item["source_url"]}" style="color:#1a3c6e;">'
                       f'{item.get("source_name", "Source")}</a>')
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
  JDAS Industry Update Agent — automated daily digest<br>
  Chatbase training document attached. Upload to your bot after review.
</p>
</body></html>
""")

    msg = MIMEMultipart("mixed")
    msg["From"]    = GMAIL_ADDRESS
    msg["To"]      = GMAIL_ADDRESS
    msg["Subject"] = f"JDAS Industry Updates — {total} new drafts — {today}"
    msg.attach(MIMEText("".join(html_parts), "html"))

    attachment = MIMEBase("application", "octet-stream")
    attachment.set_payload(chatbase_txt.encode("utf-8"))
    encoders.encode_base64(attachment)
    attachment.add_header(
        "Content-Disposition",
        f'attachment; filename="jdas_chatbase_{date.today().isoformat()}.txt"'
    )
    msg.attach(attachment)

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
            server.sendmail(GMAIL_ADDRESS, GMAIL_ADDRESS, msg.as_string())
        logger.info("Gmail digest sent successfully")
    except Exception as e:
        logger.error(f"Gmail send error: {e}")


# ─────────────────────────────────────────────
# MAIN AGENT RUNNER
# ─────────────────────────────────────────────
def run_industry_update():
    """
    Main entry point — safe to call from a background thread.
    Called by APScheduler at 5am Central daily.
    """
    logger.info("=" * 50)
    logger.info("JDAS Industry Update Agent starting...")
    logger.info(f"Run date: {date.today().isoformat()}")
    logger.info("=" * 50)

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    all_fetched: list[dict] = []

    for category in CATEGORIES:
        logger.info(f"Fetching: {category['label']}")
        try:
            updates = fetch_updates_for_category(client, category)
            for update in updates:
                update["slug"]  = category["slug"]
                update["label"] = category["label"]
            all_fetched.extend(updates)
        except Exception as e:
            logger.error(f"Unhandled error fetching {category['label']}: {e}")
            continue

    logger.info(f"Total fetched: {len(all_fetched)} records")

    if not all_fetched:
        logger.warning("No records fetched today — skipping DB write and email")
        return

    confirmed = save_drafts(all_fetched)

    if not confirmed:
        logger.warning("No records saved to DB — skipping email")
        return

    chatbase_txt = generate_chatbase_doc(confirmed)
    send_gmail_digest(confirmed, chatbase_txt)

    logger.info(f"Agent complete. {len(confirmed)} drafts ready for review.")


if __name__ == "__main__":
    run_industry_update()
