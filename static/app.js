<script>
/* =========================================================
   JDAS Tailored Industry Updates — app.js (Industry -> Table)
   - Main tabs: Industry
   - Subtabs: Dataverse Table (per industry)
   - Cards filtered by selected table using backend field: row.table (logical)
   Requires backend (new app.py) cards to include:
     { table: "jdas_marketanalysis", title, subtitle, body, details, tag, createdOn, ... }
   ========================================================= */

(() => {
  "use strict";

  /* ---------- API base ---------- */
  const API_BASE =
    (window.API_BASE && String(window.API_BASE).trim()) ||
    (document.documentElement?.dataset?.apiBase && String(document.documentElement.dataset.apiBase).trim()) ||
    `${location.protocol}//${location.host}`;

  /* ---------- Helpers ---------- */
  const isObj = (x) => x && typeof x === "object" && !Array.isArray(x);

  function buildQS(params) {
    const usp = new URLSearchParams();
    for (const [k, v] of Object.entries(params || {})) {
      if (v === undefined || v === null || v === "") continue;
      usp.set(k, String(v));
    }
    const s = usp.toString();
    return s ? `?${s}` : "";
  }

  function escapeHtml(s) {
    return String(s ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  function setStatus(kind, text) {
    const badge = document.getElementById("statusBadge");
    const label = document.getElementById("statusText");
    if (badge) {
      badge.classList.remove("ok", "err");
      badge.classList.add(kind === "ok" ? "ok" : "err");
      badge.textContent = kind === "ok" ? "OK" : "ERR";
    }
    if (label) label.textContent = text || "";
  }

  async function fetchJSON(path, { method = "GET", body = null, timeoutMs = 20000 } = {}) {
    const url = `${API_BASE}${path}`;
    const ac = new AbortController();
    const timer = setTimeout(() => ac.abort(new DOMException("Timeout", "AbortError")), timeoutMs);

    try {
      const hasBody = body !== null && body !== undefined;

      const res = await fetch(url, {
        method,
        cache: "no-store",
        signal: ac.signal,
        headers: {
          "Accept": "application/json",
          ...(hasBody ? { "Content-Type": "application/json" } : {})
        },
        body: hasBody ? (typeof body === "string" ? body : JSON.stringify(body)) : null
      });

      if (!res.ok) {
        const text = await res.text().catch(() => "");
        throw new Error(`HTTP ${res.status} ${res.statusText} — ${url}\n${text.slice(0, 600)}`);
      }

      return await res.json();
    } finally {
      clearTimeout(timer);
    }
  }

  /* ---------- Response Normalizer ---------- */
  // Backend summary: { ok:true, blocks:{ industryKey:{ ok, items:[...] } } }
  function asSummaryBlocks(payload) {
    if (!isObj(payload) || payload.ok !== true || !isObj(payload.blocks)) return {};
    return payload.blocks;
  }

  async function getIndustrySummary({ top = 10, orderby = "createdon desc", timeoutMs = 25000 } = {}) {
    const qs = buildQS({ top, orderby });
    const data = await fetchJSON(`/api/v1/summary/industry-updates${qs}`, { timeoutMs });
    return asSummaryBlocks(data);
  }

  /* =========================================================
     UI MODEL
     Industry tabs + table subtabs mapping (logical names)
     Must match backend INDUSTRY_TABLE_MAP + normalize_row().table
     ========================================================= */
  const INDUSTRIES = Object.freeze([
    {
      key: "real_estate",
      label: "Real Estate",
      tables: [
        { key: "jdas_housingmarketinsight", label: "Housing Market Insight" },
        { key: "jdas_marketoutlook",       label: "Market Outlook" }
      ]
    },
    {
      key: "automotive",
      label: "Automotive",
      tables: [
        { key: "jdas_vehiclesalesforecast", label: "Vehicle Sales Forecast" }
      ]
    },
    {
      key: "analytics_ops",
      label: "Business Analytics & Ops",
      tables: [
        { key: "jdas_analyticsparadigm", label: "Analytics Paradigm" }
      ]
    },
    {
      key: "ai",
      label: "AI Developments",
      tables: [
        { key: "jdas_aiindustryinsight", label: "AI Industry Insight" }
      ]
    },
    {
      key: "market",
      label: "Market Insight",
      tables: [
        { key: "jdas_marketinsight",      label: "Market Insight" },
        { key: "jdas_markettrendinsight", label: "Market Trend Insight" },
        { key: "jdas_marketanalysis",     label: "Market Analysis" }
      ]
    }
  ]);

  /* ---------- Card field fallbacks ---------- */
  const FIELD = Object.freeze({
    title: ["title", "name", "topic", "headline"],
    subtitle: ["subtitle", "summary", "detail", "description"],
    body: ["body", "insight", "notes", "content", "text"],
    details: ["details"],
    tag: ["tag"],
    date: ["createdOn", "createdon", "date", "timestamp"]
  });

  function pick(obj, keys) {
    for (const k of keys) {
      if (obj && obj[k] !== undefined && obj[k] !== null && String(obj[k]).trim() !== "") return obj[k];
    }
    return "";
  }

  const norm = (s) => String(s || "").trim().toLowerCase();

  /* =========================================================
     Rendering
     ========================================================= */
  function renderShell() {
    const tabsEl = document.getElementById("industryTabs");
    const viewsEl = document.getElementById("industryViews");

    if (!tabsEl || !viewsEl) {
      console.warn("[JDAS] Missing #industryTabs or #industryViews in HTML.");
      return false;
    }

    tabsEl.innerHTML = "";
    viewsEl.innerHTML = "";

    for (const ind of INDUSTRIES) {
      const tab = document.createElement("button");
      tab.type = "button";
      tab.className = "tab";
      tab.textContent = ind.label;
      tab.dataset.industry = ind.key;
      tab.setAttribute("aria-selected", "false");
      tabsEl.appendChild(tab);

      const view = document.createElement("div");
      view.className = "view";
      view.dataset.industryView = ind.key;

      const subtabs = document.createElement("div");
      subtabs.className = "subtabs";
      subtabs.dataset.subtabs = ind.key;

      const content = document.createElement("div");
      content.dataset.content = ind.key;

      view.appendChild(subtabs);
      view.appendChild(content);
      viewsEl.appendChild(view);
    }

    return true;
  }

  function setActiveIndustry(industryKey) {
    document.querySelectorAll(".tab").forEach(btn => {
      btn.setAttribute("aria-selected", btn.dataset.industry === industryKey ? "true" : "false");
    });
    document.querySelectorAll(".view").forEach(v => {
      v.classList.toggle("active", v.dataset.industryView === industryKey);
    });
  }

  function setActiveTable(industryKey, tableKey) {
    const want = norm(tableKey);
    document.querySelectorAll(`.subtabs[data-subtabs="${industryKey}"] .subtab`).forEach(btn => {
      btn.setAttribute("aria-selected", norm(btn.dataset.table) === want ? "true" : "false");
    });
  }

  function renderCards(items) {
    if (!items.length) return `<div class="empty">No records found.</div>`;

    const html = items.map((row) => {
      const t = pick(row, FIELD.title) || "Update";
      const sub = pick(row, FIELD.subtitle);
      const b = pick(row, FIELD.body);
      const det = pick(row, FIELD.details);
      const tag = pick(row, FIELD.tag);

      return `
        <div class="carditem">
          <div class="t">${escapeHtml(t)}</div>
          ${tag ? `<div class="meta">${escapeHtml(tag)}</div>` : ""}
          ${sub ? `<div class="d">${escapeHtml(sub)}</div>` : ""}
          ${b ? `<div class="b">${escapeHtml(b)}</div>` : ""}
          ${det ? `<div class="b">${escapeHtml(det)}</div>` : ""}
        </div>
      `.trim();
    }).join("");

    return `<div class="cards">${html}</div>`;
  }

  function renderSubtabs(industryKey) {
    const ind = INDUSTRIES.find(x => x.key === industryKey);
    const subtabsEl = document.querySelector(`.subtabs[data-subtabs="${industryKey}"]`);
    if (!ind || !subtabsEl) return;

    subtabsEl.innerHTML = ind.tables.map((t, i) => {
      const selected = i === 0 ? "true" : "false";
      return `
        <button type="button"
                class="subtab"
                data-industry="${escapeHtml(industryKey)}"
                data-table="${escapeHtml(t.key)}"
                aria-selected="${selected}">
          ${escapeHtml(t.label)}
        </button>
      `.trim();
    }).join("");
  }

  function filterToTable(items, tableKey) {
    const want = norm(tableKey);
    if (!want) return items;

    // Primary: backend provides row.table = logical name (ex: jdas_marketanalysis)
    const filtered = items.filter(r => norm(r.table) === want);

    // If nothing matches (bad/missing table field), fall back to all so UI isn't blank
    return filtered.length ? filtered : items;
  }

  function renderIndustry(state, industryKey) {
    const block = state.blocks?.[industryKey];
    const items = (block && Array.isArray(block.items)) ? block.items : [];

    const contentEl = document.querySelector(`[data-content="${industryKey}"]`);
    if (!contentEl) return;

    // Always render subtabs from mapping
    renderSubtabs(industryKey);

    if (!items.length) {
      contentEl.innerHTML = `<div class="empty">No records found.</div>`;
      return;
    }

    const ind = INDUSTRIES.find(x => x.key === industryKey);
    const defaultTable = ind?.tables?.[0]?.key || "";

    const activeTable = state.activeTables[industryKey] || defaultTable;
    state.activeTables[industryKey] = activeTable;

    setActiveTable(industryKey, activeTable);
    contentEl.innerHTML = renderCards(filterToTable(items, activeTable));
  }

  function bindEvents(state) {
    const tabsEl = document.getElementById("industryTabs");
    const viewsEl = document.getElementById("industryViews");

    tabsEl.addEventListener("click", (e) => {
      const btn = e.target.closest(".tab");
      if (!btn) return;

      const key = btn.dataset.industry;
      state.activeIndustry = key;

      setActiveIndustry(key);

      // Ensure subtabs exist and table is selected
      const ind = INDUSTRIES.find(x => x.key === key);
      const defaultTable = ind?.tables?.[0]?.key || "";
      const tableToUse = state.activeTables[key] || defaultTable;
      state.activeTables[key] = tableToUse;

      setActiveTable(key, tableToUse);

      const items = (state.blocks?.[key]?.items) || [];
      const contentEl = document.querySelector(`[data-content="${key}"]`);
      if (contentEl) contentEl.innerHTML = renderCards(filterToTable(items, tableToUse));
    });

    viewsEl.addEventListener("click", (e) => {
      const btn = e.target.closest(".subtab");
      if (!btn) return;

      const industryKey = btn.dataset.industry;
      const tableKey = btn.dataset.table;

      state.activeIndustry = industryKey;
      state.activeTables[industryKey] = tableKey;

      setActiveIndustry(industryKey);
      setActiveTable(industryKey, tableKey);

      const items = (state.blocks?.[industryKey]?.items) || [];
      const contentEl = document.querySelector(`[data-content="${industryKey}"]`);
      if (contentEl) contentEl.innerHTML = renderCards(filterToTable(items, tableKey));
    });
  }

  /* ---------- Load + Boot ---------- */
  async function loadDashboard({ top = 10, orderby = "createdon desc" } = {}) {
    const state = {
      blocks: {},
      activeIndustry: INDUSTRIES[0]?.key || "real_estate",
      activeTables: Object.create(null)
    };

    if (!renderShell()) return;
    bindEvents(state);

    // Pre-render subtabs + loading
    for (const ind of INDUSTRIES) {
      renderSubtabs(ind.key);
      const contentEl = document.querySelector(`[data-content="${ind.key}"]`);
      if (contentEl) contentEl.innerHTML = `<div class="loading">Loading…</div>`;
    }

    setActiveIndustry(state.activeIndustry);
    setStatus("ok", "Loading latest updates…");

    try {
      const blocks = await getIndustrySummary({ top, orderby });
      state.blocks = blocks;

      for (const ind of INDUSTRIES) {
        renderIndustry(state, ind.key);
      }

      setStatus("ok", "Loaded latest updates.");
    } catch (err) {
      console.error(err);
      setStatus("err", "Failed to load updates. Check API_BASE / network / endpoint.");

      for (const ind of INDUSTRIES) {
        const contentEl = document.querySelector(`[data-content="${ind.key}"]`);
        if (contentEl) contentEl.innerHTML = `<div class="empty">Error loading data.</div>`;
      }
    }

    window.JDAS_UI = {
      reload: (opts) => loadDashboard(opts),
      get state() { return state; }
    };
  }

  window.JDAS = Object.freeze({
    API_BASE,
    api: Object.freeze({
      industryUpdatesSummary: (opts) => getIndustrySummary(opts),
      docsUrl: `${API_BASE}/docs`
    })
  });

  document.addEventListener("DOMContentLoaded", () => {
    console.log("[JDAS] API_BASE:", API_BASE);
    loadDashboard({ top: 10, orderby: "createdon desc" });
  });

})();
</script>
