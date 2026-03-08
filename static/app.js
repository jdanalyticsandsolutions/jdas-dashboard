(() => {
  "use strict";

  const API_BASE = `${location.protocol}//${location.host}`;
  const $ = (sel) => document.querySelector(sel);
  const $$ = (sel) => Array.from(document.querySelectorAll(sel));

  const esc = (s) =>
    String(s ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");

  // -------------------------
  // Industry display config
  // Maps internal keys → friendly labels + icons
  // -------------------------
  const INDUSTRY_DISPLAY = {
    real_estate:    { label: "Real Estate",       icon: "🏠", desc: "Housing market & property trends" },
    automotive:     { label: "Automotive",         icon: "🚗", desc: "Vehicle sales & industry outlook" },
    analytics_ops:  { label: "Operations & AI",   icon: "⚙️", desc: "Business tools, analytics & efficiency" },
    ai:             { label: "Technology & AI",   icon: "🤖", desc: "AI developments & digital tools" },
    market:         { label: "Market Insights",   icon: "📈", desc: "Economic signals & business trends" },
    // fallback for unknown keys:
    _default:       { label: "Industry",           icon: "📊", desc: "Industry updates" }
  };

  // Table key → friendly sub-label
  const TABLE_DISPLAY = {
    housingmarketinsight: { label: "Housing Market",      icon: "🏡" },
    marketoutlook:        { label: "Market Outlook",      icon: "🔭" },
    vehiclesalesforecast: { label: "Vehicle Sales",       icon: "🚙" },
    analyticsparadigm:    { label: "Analytics Trends",   icon: "📊" },
    marketinsight:        { label: "Market Signals",      icon: "💹" },
    markettrendinsight:   { label: "Key Trends",          icon: "📉" },
    marketanalysis:       { label: "Market Analysis",     icon: "🔍" },
    aiindustryinsight:    { label: "AI in Business",      icon: "🤖" },
    _default:             { label: "Updates",             icon: "📋" }
  };

  // Priority badge assignment — rotate through styles by position
  const BADGE_CYCLE = [
    { cls: "badge-high",  label: "High Impact" },
    { cls: "badge-watch", label: "Watch This" },
    { cls: "badge-opp",   label: "Opportunity" },
    { cls: "badge-info",  label: "Key Insight" },
    { cls: "badge-ai",    label: "Trending" },
    { cls: "badge-stable",label: "Steady Trend" },
  ];

  function isAssistantKey(key) {
    const k = String(key || "").toLowerCase();
    return k === "ai_assistant" || k === "assistant" || k.includes("assistant") || k.includes("chatbot");
  }

  // -------------------------
  // Status indicator
  // -------------------------
  function setStatus(kind, text) {
    const dot = $("#statusDot");
    const label = $("#statusText");
    if (dot) { dot.classList.remove("ok", "err", "busy"); dot.classList.add(kind); }
    if (label) label.textContent = text || "";
  }

  async function fetchJSON(path) {
    const res = await fetch(`${API_BASE}${path}`, { cache: "no-store" });
    if (!res.ok) throw new Error(`HTTP ${res.status} ${res.statusText}`);
    return await res.json();
  }

  // -------------------------
  // AI Assistant Drawer
  // -------------------------
  let chatbaseLoaded = false;

  function loadChatbaseOnce() {
    const mount = document.getElementById("chatbaseMount");
    if (!mount || mount.querySelector("iframe") || chatbaseLoaded) return;
    chatbaseLoaded = true;
    mount.innerHTML = `
      <iframe
        src="https://www.chatbase.co/chatbot-iframe/Vndl5JBBKFxsFxy9De-K1"
        width="100%" height="100%"
        style="border:0; min-height:600px;"
        loading="lazy"
        allow="clipboard-write; microphone"
      ></iframe>`;
  }

  function openAssistantDrawer() {
    const drawer = document.getElementById("assistantDrawer");
    if (!drawer) return;
    loadChatbaseOnce();
    drawer.classList.add("open");
    drawer.setAttribute("aria-hidden", "false");
    document.body.classList.add("no-scroll");
  }

  function closeAssistantDrawer() {
    const drawer = document.getElementById("assistantDrawer");
    if (!drawer) return;
    drawer.classList.remove("open");
    drawer.setAttribute("aria-hidden", "true");
    document.body.classList.remove("no-scroll");
  }

  // -------------------------
  // App state
  // -------------------------
  const state = {
    config: null,
    blocks: null,
    activeIndustry: null,
    activeTableKey: null,
    readMode: "quick",   // "quick" or "detailed"
    top: 10,
    q: "",
  };

  function getIndustryDisplay(key) {
    return INDUSTRY_DISPLAY[key] || INDUSTRY_DISPLAY._default;
  }
  function getTableDisplay(key) {
    return TABLE_DISPLAY[key] || TABLE_DISPLAY._default;
  }

  function setReadMode(mode) {
    state.readMode = mode;
    if (mode === "quick") {
      document.body.classList.add("quick-mode");
    } else {
      document.body.classList.remove("quick-mode");
    }
    // Update toggle UI
    $$(".toggle-btn").forEach(btn => {
      btn.classList.toggle("active", btn.dataset.mode === mode);
    });
  }

  // -------------------------
  // Hero strip
  // -------------------------
  function updateHeroStrip() {
    const allItems = getAllItems();
    if (!allItems.length) return;

    // Pull first items from each slot (can be customized later with priority fields)
    const safe = (i) => allItems[i] ? truncate(allItems[i].title, 60) : "—";

    const heroMap = [
      { id: "heroRiskVal",  item: allItems[0] },
      { id: "heroOppVal",   item: allItems[1] },
      { id: "heroCostVal",  item: allItems[2] },
      { id: "heroShiftVal", item: allItems[3] },
    ];

    heroMap.forEach(({ id, item }) => {
      const el = document.getElementById(id);
      if (el) el.textContent = item ? truncate(item.title, 60) : "No data";
    });
  }

  function getAllItems() {
    if (!state.blocks) return [];
    const out = [];
    for (const [indKey, indData] of Object.entries(state.blocks)) {
      for (const [tKey, tObj] of Object.entries(indData.tables || {})) {
        for (const item of tObj.items || []) out.push(item);
      }
    }
    return out;
  }

  function truncate(str, len) {
    if (!str) return "—";
    return str.length > len ? str.slice(0, len).trimEnd() + "…" : str;
  }

  // -------------------------
  // Render industry nav
  // -------------------------
  function renderIndustryNav() {
    const nav = $("#industryNav");
    nav.innerHTML = state.config.industries
      .filter(ind => !isAssistantKey(ind.key))
      .map(ind => {
        const disp = getIndustryDisplay(ind.key);
        const isActive = ind.key === state.activeIndustry;
        return `
          <button class="ind-btn${isActive ? " active" : ""}" data-ind="${esc(ind.key)}" type="button">
            <span class="ind-icon">${disp.icon}</span>
            <span>${esc(ind.label)}</span>
          </button>`;
      }).join("");
  }

  function renderTableNav(ind) {
    const nav = $("#tableNav");
    if (!ind || isAssistantKey(ind.key)) {
      nav.innerHTML = `<div style="font-size:13px;color:var(--muted2);padding:4px 6px;">No topics</div>`;
      return;
    }
    nav.innerHTML = (ind.tables || []).map(t => {
      const disp = getTableDisplay(t.key);
      const isActive = t.key === state.activeTableKey;
      return `
        <button class="topic-btn${isActive ? " active" : ""}" data-tbl="${esc(t.key)}" type="button">
          <span>${disp.icon} ${esc(t.label)}</span>
          <span class="topic-tag">${esc(t.tag || "")}</span>
        </button>`;
    }).join("");
  }

  // -------------------------
  // Render category pills
  // -------------------------
  function renderCategoryPills(ind) {
    const container = $("#categoryPills");
    if (!ind || !ind.tables || ind.tables.length <= 1) {
      container.innerHTML = "";
      return;
    }
    container.innerHTML = [
      `<button class="cat-pill${!state.activeTableKey ? " active" : ""}" data-cat="all" type="button">All Topics</button>`,
      ...ind.tables.map(t => {
        const disp = getTableDisplay(t.key);
        const isActive = t.key === state.activeTableKey;
        return `<button class="cat-pill${isActive ? " active" : ""}" data-cat="${esc(t.key)}" type="button">${disp.icon} ${esc(t.label)}</button>`;
      })
    ].join("");
  }

  // -------------------------
  // Main sections renderer
  // -------------------------
  function matchesSearch(item, q) {
    if (!q) return true;
    const hay = [item.title, item.body, item.tag, item.table_label, item.table, item.id]
      .join(" ").toLowerCase();
    return hay.includes(q);
  }

  function renderSections() {
    const container = $("#sectionsView");
    const blk = state.blocks?.[state.activeIndustry];

    if (!blk?.tables) {
      container.innerHTML = emptyState("📭", "No data available", "Select an industry from the left to explore updates.");
      return;
    }

    const q = state.q.trim().toLowerCase();
    let sectionIndex = 0;

    const tablesEntries = Object.entries(blk.tables);

    const html = tablesEntries
      .filter(([tKey]) => !state.activeTableKey || tKey === state.activeTableKey)
      .map(([tKey, tObj]) => {
        const items = (tObj.items || []).filter(it => matchesSearch(it, q));
        const disp = getTableDisplay(tKey);
        const isOpen = tKey === state.activeTableKey || !state.activeTableKey;
        const sectionClass = `section-block${isOpen ? " open" : ""}`;

        const cards = items.length
          ? items.map((it, i) => renderCard(it, sectionIndex * 10 + i)).join("")
          : `<div style="padding:16px;color:var(--muted);font-size:13px;">No matches for your search.</div>`;

        sectionIndex++;

        return `
          <div class="${sectionClass}" id="section-${esc(tKey)}">
            <button class="section-header" data-table="${esc(tKey)}" type="button"
                    aria-expanded="${isOpen ? 'true' : 'false'}">
              <div class="section-header-left">
                <div class="section-icon" style="background:var(--blueSoft);">${disp.icon}</div>
                <div class="section-meta">
                  <div class="section-title">${esc(disp.label)}</div>
                  <div class="section-subtitle">${esc(tObj.label || tKey)}</div>
                </div>
              </div>
              <div class="section-header-right">
                <span class="section-count">${items.length} update${items.length !== 1 ? "s" : ""}</span>
                <span class="section-chevron">▼</span>
              </div>
            </button>
            <div class="section-body" style="display:${isOpen ? "flex" : "none"};">
              ${cards}
            </div>
          </div>`;
      }).join("");

    container.innerHTML = html || emptyState("🔍", "No results", "Try a different search or select another industry.");
  }

  function renderCard(item, index) {
    const badge = BADGE_CYCLE[index % BADGE_CYCLE.length];
    const dateStr = item.createdOn ? formatDate(item.createdOn) : "";
    const hasExtras = item.body && item.body.length > 20;

    // Build extras for detailed mode
    // These fields come from Dataverse via normalize():
    // For aiindustryinsight: assistant_perspective, future_unified_view, industry_phase_description
    // Other tables: just title + body
    const extraRows = [];

    if (item.assistant_perspective) {
      extraRows.push({ label: "AI Perspective", val: item.assistant_perspective });
    }
    if (item.future_unified_view) {
      extraRows.push({ label: "Future Outlook", val: item.future_unified_view });
    }
    if (item.industry_phase_description) {
      extraRows.push({ label: "Industry Phase", val: item.industry_phase_description });
    }

    const extraHtml = extraRows.length ? `
      <div class="card-extras">
        ${extraRows.map(r => `
          <div class="card-extra-row">
            <span class="card-extra-label">${esc(r.label)}</span>
            <span class="card-extra-val">${esc(r.val)}</span>
          </div>`).join("")}
      </div>` : "";

    // Owner takeaway — surfaces the body as a concise action note in quick mode
    const takeaway = item.body ? truncate(item.body, 120) : "";

    return `
      <div class="biz-card">
        <div class="card-top">
          <div class="card-title">${esc(item.title || "Business Update")}</div>
          <span class="badge ${badge.cls}">${badge.label}</span>
        </div>

        ${hasExtras ? `<div class="card-body">${esc(truncate(item.body, 200))}</div>` : ""}

        ${takeaway ? `
          <div class="card-takeaway">
            <span class="takeaway-icon">💼</span>
            <div class="takeaway-text">
              <span class="takeaway-label">Owner Takeaway</span>
              ${esc(takeaway)}
            </div>
          </div>` : ""}

        ${extraHtml}

        <div class="card-meta">
          ${item.tag ? `<span class="card-tag">${esc(item.tag)}</span>` : ""}
          ${dateStr ? `<span class="card-date">Updated ${dateStr}</span>` : ""}
        </div>
      </div>`;
  }

  function emptyState(icon, text, sub) {
    return `<div class="empty-state">
      <div class="empty-state-icon">${icon}</div>
      <div class="empty-state-text">${esc(text)}</div>
      <div class="empty-state-sub">${esc(sub)}</div>
    </div>`;
  }

  function loadingState() {
    return `<div class="section-block open">
      <div class="section-body">
        <div class="loading-state">
          <div class="skeleton"></div>
          <div class="skeleton"></div>
          <div class="skeleton short"></div>
        </div>
      </div>
    </div>`;
  }

  function formatDate(iso) {
    try {
      const d = new Date(iso);
      if (isNaN(d)) return iso;
      const now = new Date();
      const diff = Math.floor((now - d) / 86400000);
      if (diff === 0) return "today";
      if (diff === 1) return "yesterday";
      if (diff < 7) return `${diff} days ago`;
      return d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
    } catch { return iso; }
  }

  function render() {
    if (!state.config || !state.blocks) return;
    renderSections();
  }

  // -------------------------
  // Set active industry/table
  // -------------------------
  function setActive(indKey, tableKey) {
    state.activeIndustry = indKey;
    state.activeTableKey = tableKey;

    const ind = state.config?.industries?.find(i => i.key === indKey);

    // Update page title/subtitle
    const disp = getIndustryDisplay(indKey);
    $("#pageTitle").textContent = ind?.label || disp.label || "Industry Updates";
    $("#pageSubtitle").textContent = disp.desc || "Select a topic below";

    // Re-render navs
    renderIndustryNav();
    renderTableNav(ind);
    renderCategoryPills(ind);
    render();
  }

  // -------------------------
  // Load data
  // -------------------------
  async function load() {
    setStatus("busy", "Loading…");
    $("#sectionsView").innerHTML = loadingState();

    const health = await fetchJSON("/api/v1/health");
    state.config = await fetchJSON("/api/v1/config");
    state.top = Number($("#topSelect")?.value || 10);

    // Pick first non-assistant industry
    const firstInd = state.config.industries?.find(i => !isAssistantKey(i.key)) || state.config.industries?.[0];
    state.activeIndustry = firstInd?.key || "";
    state.activeTableKey = ""; // show all tables on load

    const data = await fetchJSON(`/api/v1/summary/industry-updates?top=${state.top}`);
    state.blocks = data.blocks || {};

    setStatus("ok", `Refreshed ${new Date().toLocaleTimeString()}`);
    updateHeroStrip();
    setActive(state.activeIndustry, state.activeTableKey);
  }

  // -------------------------
  // Event delegation
  // -------------------------
  document.addEventListener("click", e => {
    // Assistant open
    const assistantBtn = e.target.closest("#assistantOpenBtn, .assistant-btn");
    if (assistantBtn) { openAssistantDrawer(); return; }

    // Read mode toggle
    const toggleBtn = e.target.closest(".toggle-btn");
    if (toggleBtn && toggleBtn.dataset.mode) {
      setReadMode(toggleBtn.dataset.mode);
      return;
    }

    // Industry nav click
    const indBtn = e.target.closest(".ind-btn");
    if (indBtn) {
      const indKey = indBtn.dataset.ind;
      const ind = state.config?.industries?.find(i => i.key === indKey);
      state.activeTableKey = ""; // reset to show all topics
      setActive(indKey, "");
      return;
    }

    // Topic nav click
    const tblBtn = e.target.closest(".topic-btn");
    if (tblBtn) {
      const tKey = tblBtn.dataset.tbl;
      setActive(state.activeIndustry, tKey);
      return;
    }

    // Category pill click
    const catPill = e.target.closest(".cat-pill");
    if (catPill) {
      const cat = catPill.dataset.cat;
      setActive(state.activeIndustry, cat === "all" ? "" : cat);
      return;
    }

    // Section header expand/collapse
    const sectionHead = e.target.closest(".section-header");
    if (sectionHead) {
      const tKey = sectionHead.dataset.table;
      const block = sectionHead.closest(".section-block");
      const isOpen = block?.classList.contains("open");
      const body = block?.querySelector(".section-body");

      if (block) block.classList.toggle("open", !isOpen);
      if (body)  body.style.display = isOpen ? "none" : "flex";
      sectionHead.setAttribute("aria-expanded", isOpen ? "false" : "true");

      if (!isOpen) {
        state.activeTableKey = tKey;
        // Update sidebar topic highlight without full re-render
        $$(".topic-btn").forEach(b => b.classList.toggle("active", b.dataset.tbl === tKey));
        $$(".cat-pill").forEach(b => b.classList.toggle("active", b.dataset.cat === tKey));
      }
      return;
    }
  });

  // -------------------------
  // DOM Ready
  // -------------------------
  document.addEventListener("DOMContentLoaded", async () => {
    try {
      // Refresh
      $("#refreshBtn")?.addEventListener("click", load);

      // Rows select
      $("#topSelect")?.addEventListener("change", load);

      // Search toggle
      const searchBar = $("#searchBar");
      $("#searchToggle")?.addEventListener("click", () => {
        const visible = searchBar.style.display !== "none";
        searchBar.style.display = visible ? "none" : "block";
        if (!visible) $("#searchInput")?.focus();
      });
      $("#searchClose")?.addEventListener("click", () => {
        searchBar.style.display = "none";
        state.q = "";
        render();
      });
      $("#searchInput")?.addEventListener("input", e => {
        state.q = e.target.value || "";
        render();
      });

      // Drawer close
      $("#assistantCloseBtn")?.addEventListener("click", closeAssistantDrawer);
      $("#assistantOverlay")?.addEventListener("click", closeAssistantDrawer);
      document.addEventListener("keydown", e => { if (e.key === "Escape") closeAssistantDrawer(); });

      // Init read mode
      setReadMode("quick");

      await load();
    } catch (err) {
      console.error(err);
      setStatus("err", "Load failed — check API");
      $("#sectionsView").innerHTML = `<div class="empty-state">
        <div class="empty-state-icon">⚠️</div>
        <div class="empty-state-text">Could not load updates</div>
        <div class="empty-state-sub">Check your API connection and try refreshing.</div>
      </div>`;
    }
  });
})();
