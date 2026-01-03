<script>
/* ======================================
   JDAS Tailored Industry Updates — app.js
   Tabs (Industry) + Subtabs (Sections)
   Matches new style.css: .tabs/.tab + .subtabs/.subtab + .view/.active + .cards/.carditem
   ====================================== */

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
    if (!params) return "";
    const usp = new URLSearchParams();
    for (const [k, v] of Object.entries(params)) {
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

  /* ---------- Fetch ---------- */
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
        throw new Error(`HTTP ${res.status} ${res.statusText} — ${url}\n${text.slice(0, 500)}`);
      }

      return await res.json();
    } finally {
      clearTimeout(timer);
    }
  }

  /* ---------- Normalizers ---------- */
  // Summary endpoint: { ok:true, blocks:{ key:{ ok, items:[...] } } }
  function asSummaryBlocks(payload) {
    if (!isObj(payload) || payload.ok !== true || !isObj(payload.blocks)) return {};
    return payload.blocks;
  }

  /* ---------- API calls ---------- */
  async function getIndustrySummary({ top = 10, orderby = "createdon desc", timeoutMs = 25000 } = {}) {
    const qs = buildQS({ top, orderby });
    const data = await fetchJSON(`/api/v1/summary/industry-updates${qs}`, { timeoutMs });
    return asSummaryBlocks(data);
  }

  /* ---------- UI Model ---------- */
  // Industry tabs (top-level)
  const INDUSTRIES = Object.freeze([
    { key: "real_estate",   label: "Real Estate" },
    { key: "automotive",    label: "Automotive" },
    { key: "analytics_ops", label: "Business Analytics & Ops" },
    { key: "ai",            label: "AI Developments" },
    { key: "market",        label: "Market Insight" },
    { key: "outlook",       label: "Market Outlook" },
    { key: "trends",        label: "Market Trends" },
    { key: "analysis",      label: "Market Analysis" }
  ]);

  // Field fallback order for cards (adjustable without breaking)
  const FIELD = Object.freeze({
    title: ["title", "name", "topic", "headline"],
    desc:  ["description", "summary", "detail", "subtitle"],
    body:  ["body", "insight", "notes", "content", "text"],
    date:  ["createdon", "createdOn", "date", "timestamp"],
    source:["source", "publisher", "link_source", "origin"]
  });

  function pick(obj, keys) {
    for (const k of keys) {
      if (obj && obj[k] !== undefined && obj[k] !== null && String(obj[k]).trim() !== "") return obj[k];
    }
    return "";
  }

  function getSubtabKeys(items) {
    // Prefer a "section" style field if you have it; otherwise use titles.
    // If your backend already groups by "title" (like you showed), titles work well.
    const titles = items.map(x => String(pick(x, FIELD.title) || "").trim()).filter(Boolean);
    return [...new Set(titles)];
  }

  /* ---------- Rendering ---------- */
  function renderShell() {
    const tabsEl = document.getElementById("industryTabs");
    const viewsEl = document.getElementById("industryViews");

    if (!tabsEl || !viewsEl) {
      console.warn("[JDAS] Missing #industryTabs or #industryViews in HTML.");
      return false;
    }

    tabsEl.innerHTML = "";
    viewsEl.innerHTML = "";

    // Create industry tabs + empty views
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

  function setActiveSubtab(industryKey, subtabLabel) {
    document.querySelectorAll(`.subtabs[data-subtabs="${industryKey}"] .subtab`).forEach(btn => {
      btn.setAttribute("aria-selected", btn.dataset.subtab === subtabLabel ? "true" : "false");
    });
  }

  function renderCards(items) {
    if (!items.length) return `<div class="empty">No records found.</div>`;

    const html = items.map((row) => {
      const t = pick(row, FIELD.title) || "Update";
      const d = pick(row, FIELD.desc);
      const b = pick(row, FIELD.body);

      // keep it clean: only show sections that exist
      return `
        <div class="carditem">
          <div class="t">${escapeHtml(t)}</div>
          ${d ? `<div class="d">${escapeHtml(d)}</div>` : ""}
          ${b ? `<div class="b">${escapeHtml(b)}</div>` : ""}
        </div>
      `.trim();
    }).join("");

    return `<div class="cards">${html}</div>`;
  }

  function renderIndustry(blocks, industryKey) {
    const block = blocks[industryKey];
    const items = (block && Array.isArray(block.items)) ? block.items : [];

    const subtabsEl = document.querySelector(`.subtabs[data-subtabs="${industryKey}"]`);
    const contentEl = document.querySelector(`[data-content="${industryKey}"]`);
    if (!subtabsEl || !contentEl) return;

    // Empty state
    if (!items.length) {
      subtabsEl.innerHTML = "";
      contentEl.innerHTML = `<div class="empty">No records found.</div>`;
      return;
    }

    // Build subtabs from unique titles (or whatever you want)
    const subtabKeys = getSubtabKeys(items);

    // If titles are blank, fallback to "All"
    if (!subtabKeys.length) {
      subtabsEl.innerHTML = "";
      contentEl.innerHTML = renderCards(items);
      return;
    }

    subtabsEl.innerHTML = subtabKeys.map((label, i) => {
      const selected = i === 0 ? "true" : "false";
      return `
        <button type="button"
                class="subtab"
                data-industry="${escapeHtml(industryKey)}"
                data-subtab="${escapeHtml(label)}"
                aria-selected="${selected}">
          ${escapeHtml(label)}
        </button>
      `.trim();
    }).join("");

    // Default to first subtab: filter to that title
    const first = subtabKeys[0];
    const bucket = items.filter(x => String(pick(x, FIELD.title) || "").trim() === first);
    contentEl.innerHTML = renderCards(bucket);
  }

  function bindEvents(state) {
    const tabsEl = document.getElementById("industryTabs");
    const viewsEl = document.getElementById("industryViews");

    // Industry tab clicks
    tabsEl.addEventListener("click", (e) => {
      const btn = e.target.closest(".tab");
      if (!btn) return;

      const key = btn.dataset.industry;
      state.activeIndustry = key;

      setActiveIndustry(key);

      // Ensure a sensible subtab is selected (if exists)
      const firstSub = document.querySelector(`.subtabs[data-subtabs="${key}"] .subtab`);
      if (firstSub) {
        const sub = firstSub.dataset.subtab;
        state.activeSubtabs[key] = sub;
        setActiveSubtab(key, sub);
      }
    });

    // Subtab clicks
    viewsEl.addEventListener("click", (e) => {
      const btn = e.target.closest(".subtab");
      if (!btn) return;

      const industryKey = btn.dataset.industry;
      const subtabLabel = btn.dataset.subtab;

      state.activeIndustry = industryKey;
      state.activeSubtabs[industryKey] = subtabLabel;

      setActiveIndustry(industryKey);
      setActiveSubtab(industryKey, subtabLabel);

      // Re-render filtered cards
      const items = (state.blocks?.[industryKey]?.items) || [];
      const bucket = items.filter(x => String(pick(x, FIELD.title) || "").trim() === subtabLabel);
      const contentEl = document.querySelector(`[data-content="${industryKey}"]`);
      if (contentEl) contentEl.innerHTML = renderCards(bucket);
    });
  }

  /* ---------- Load + Boot ---------- */
  async function loadDashboard({ top = 10, orderby = "createdon desc" } = {}) {
    const state = {
      blocks: {},
      activeIndustry: INDUSTRIES[0]?.key || "real_estate",
      activeSubtabs: Object.create(null)
    };

    // Render base UI
    if (!renderShell()) return;
    bindEvents(state);

    // Show initial selected tab/view immediately (even before data)
    setActiveIndustry(state.activeIndustry);

    // Loading UI per view
    for (const ind of INDUSTRIES) {
      const contentEl = document.querySelector(`[data-content="${ind.key}"]`);
      if (contentEl) contentEl.innerHTML = `<div class="loading">Loading…</div>`;
    }
    setStatus("ok", "Loading latest updates…");

    try {
      const blocks = await getIndustrySummary({ top, orderby });
      state.blocks = blocks;

      // Render each industry view
      for (const ind of INDUSTRIES) {
        renderIndustry(blocks, ind.key);
      }

      // Select first available subtab for the active industry (if any)
      const firstSub = document.querySelector(`.subtabs[data-subtabs="${state.activeIndustry}"] .subtab[aria-selected="true"]`)
                    || document.querySelector(`.subtabs[data-subtabs="${state.activeIndustry}"] .subtab`);
      if (firstSub) {
        const sub = firstSub.dataset.subtab;
        state.activeSubtabs[state.activeIndustry] = sub;
        setActiveSubtab(state.activeIndustry, sub);
      }

      setStatus("ok", "Loaded latest updates.");
    } catch (err) {
      console.error(err);
      setStatus("err", "Failed to load updates. Check API_BASE / network / endpoint.");

      // Render error into each view
      for (const ind of INDUSTRIES) {
        const contentEl = document.querySelector(`[data-content="${ind.key}"]`);
        if (contentEl) contentEl.innerHTML = `<div class="empty">Error loading data.</div>`;
      }
    }

    // Expose for manual refresh/debug
    window.JDAS_UI = {
      reload: (opts) => loadDashboard(opts),
      get state() { return state; }
    };
  }

  // Expose minimal API like before
  window.JDAS = Object.freeze({
    API_BASE,
    api: Object.freeze({
      industryUpdatesSummary: (opts) => getIndustrySummary(opts),
      docsUrl: `${API_BASE}/docs`
    })
  });

  // Boot on DOM ready
  document.addEventListener("DOMContentLoaded", () => {
    console.log("[JDAS] API_BASE:", API_BASE);
    loadDashboard({ top: 10, orderby: "createdon desc" });
  });

})();
</script>
