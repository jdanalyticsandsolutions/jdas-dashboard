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

  // ─────────────────────────────────────────────
  // All 10 categories
  // ─────────────────────────────────────────────
  const INDUSTRY_DISPLAY = {
    real_estate:            { label: "Real Estate",               icon: "🏠", desc: "Housing market & property trends" },
    automotive:             { label: "Automotive",                icon: "🚗", desc: "Vehicle sales & industry outlook" },
    analytics_ops:          { label: "Analytics & Ops",           icon: "⚙️", desc: "Business tools, analytics & efficiency" },
    ai_developments:        { label: "AI Developments",           icon: "🤖", desc: "AI developments & digital tools" },
    market_insight:         { label: "Market Insight",            icon: "📈", desc: "Economic signals & business trends" },
    supply_chain_logistics: { label: "Supply Chain & Logistics",  icon: "🚚", desc: "Freight, shipping & supply disruptions" },
    labor_workforce_trends: { label: "Labor & Workforce Trends",  icon: "👷", desc: "Hiring, wages & workforce shifts" },
    energy_commodities:     { label: "Energy & Commodities",      icon: "⚡", desc: "Oil, gas, utilities & raw materials" },
    policy_regulation:      { label: "Policy & Regulation",       icon: "⚖️", desc: "Laws, tariffs & regulatory changes" },
    small_business_pulse:   { label: "Small Business Pulse",      icon: "🏪", desc: "Main Street trends & owner sentiment" },
    _default:               { label: "Industry",                  icon: "📊", desc: "Industry updates" },
  };

  // Directional signal → display
  const SIGNAL_DISPLAY = {
    positive:           { label: "Positive",        color: "#2e7d32", icon: "▲" },
    mixed_positive:     { label: "Mixed Positive",  color: "#558b2f", icon: "▲" },
    neutral:            { label: "Neutral",         color: "#757575", icon: "●" },
    mixed:              { label: "Mixed",           color: "#f57c00", icon: "◆" },
    mixed_negative:     { label: "Mixed Negative",  color: "#e65100", icon: "▼" },
    negative:           { label: "Negative",        color: "#c62828", icon: "▼" },
    risk_off:           { label: "Risk Off",        color: "#6a1b9a", icon: "⚠" },
    tight_labor_market: { label: "Tight Labor",     color: "#1565c0", icon: "◆" },
  };

  const BADGE_CYCLE = [
    { cls: "badge-high",   label: "High Impact" },
    { cls: "badge-watch",  label: "Watch This" },
    { cls: "badge-opp",    label: "Opportunity" },
    { cls: "badge-info",   label: "Key Insight" },
    { cls: "badge-ai",     label: "Trending" },
    { cls: "badge-stable", label: "Steady Trend" },
  ];

  // ─────────────────────────────────────────────
  // State
  // ─────────────────────────────────────────────
  const state = {
    records: [],          // flat array from /get-updates
    activeCategory: "",   // slug or "" for all
    readMode: "quick",
    limit: 50,
    q: "",
  };

  // ─────────────────────────────────────────────
  // Helpers
  // ─────────────────────────────────────────────
  function getDisplay(slug) {
    return INDUSTRY_DISPLAY[slug] || INDUSTRY_DISPLAY._default;
  }

  function truncate(str, len) {
    if (!str) return "—";
    return str.length > len ? str.slice(0, len).trimEnd() + "…" : str;
  }

  function formatDate(iso) {
    if (!iso) return "";
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

  function setStatus(kind, text) {
    const dot = $("#statusDot");
    const label = $("#statusText");
    if (dot) { dot.classList.remove("ok", "err", "busy"); dot.classList.add(kind); }
    if (label) label.textContent = text || "";
  }

  async function fetchJSON(path) {
    const res = await fetch(`${API_BASE}${path}`, { cache: "no-store" });
    if (!res.ok) throw new Error(`HTTP ${res.status} ${res.statusText}`);
    return res.json();
  }

  // ─────────────────────────────────────────────
  // AI Assistant Drawer
  // ─────────────────────────────────────────────
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

  // ─────────────────────────────────────────────
  // Hero strip — smart signal-based assignment
  // ─────────────────────────────────────────────
  function updateHeroStrip() {
    const records = state.records;
    if (!records.length) return;

    const negative = records.filter(r =>
      ["negative", "mixed_negative", "risk_off"].includes(r.directional_signal)
    );
    const positive = records.filter(r =>
      ["positive", "mixed_positive"].includes(r.directional_signal)
    );
    const volatile = records.filter(r => r.volatility_flag);
    const neutral  = records.filter(r =>
      ["neutral", "mixed", "tight_labor_market"].includes(r.directional_signal)
    );

    const pick = (arr, fallback) => arr[0] || fallback || records[0];

    const risk       = pick(volatile.filter(r => negative.includes(r)), negative[0]);
    const opportunity = pick(positive, records[1]);
    const insight    = pick(neutral, records[2]);
    const watchThis  = pick(volatile, records[3]);

    const map = [
      { id: "heroRiskVal",  item: risk },
      { id: "heroOppVal",   item: opportunity },
      { id: "heroCostVal",  item: insight },
      { id: "heroShiftVal", item: watchThis },
    ];

    map.forEach(({ id, item }) => {
      const el = document.getElementById(id);
      if (el) el.textContent = item ? truncate(item.headline, 70) : "No data";
    });
  }

  // ─────────────────────────────────────────────
  // Industry nav (sidebar)
  // ─────────────────────────────────────────────
  function getCategories() {
    const slugs = [...new Set(state.records.map(r => r.category_slug))];
    return slugs.map(slug => ({ slug, ...getDisplay(slug) }));
  }

  function renderIndustryNav() {
    const nav = $("#industryNav");
    if (!nav) return;
    const cats = getCategories();
    if (!cats.length) {
      nav.innerHTML = `<div style="font-size:13px;color:var(--muted2);padding:4px 6px;">No categories yet</div>`;
      return;
    }
    nav.innerHTML = cats.map(cat => {
      const isActive = cat.slug === state.activeCategory;
      return `
        <button class="ind-btn${isActive ? " active" : ""}" data-ind="${esc(cat.slug)}" type="button">
          <span class="ind-icon">${cat.icon}</span>
          <span>${esc(cat.label)}</span>
        </button>`;
    }).join("");
  }

  function renderTableNav() {
    const nav = $("#tableNav");
    if (!nav) return;
    const cats = getCategories();
    nav.innerHTML = cats.map(cat => {
      const count = state.records.filter(r => r.category_slug === cat.slug).length;
      const isActive = cat.slug === state.activeCategory;
      return `
        <button class="topic-btn${isActive ? " active" : ""}" data-tbl="${esc(cat.slug)}" type="button">
          <span>${cat.icon} ${esc(cat.label)}</span>
          <span class="topic-tag">${count}</span>
        </button>`;
    }).join("");
  }

  function renderCategoryPills() {
    const container = $("#categoryPills");
    if (!container) return;
    const cats = getCategories();
    if (cats.length <= 1) { container.innerHTML = ""; return; }
    container.innerHTML = [
      `<button class="cat-pill${!state.activeCategory ? " active" : ""}" data-cat="all" type="button">All</button>`,
      ...cats.map(cat => {
        const isActive = cat.slug === state.activeCategory;
        return `<button class="cat-pill${isActive ? " active" : ""}" data-cat="${esc(cat.slug)}" type="button">${cat.icon} ${esc(cat.label)}</button>`;
      })
    ].join("");
  }

  // ─────────────────────────────────────────────
  // Cards
  // ─────────────────────────────────────────────
  function matchesSearch(record, q) {
    if (!q) return true;
    const hay = [
      record.headline, record.summary, record.business_impact,
      record.category_slug, record.subtopic, record.source_name,
      ...(record.tags || [])
    ].join(" ").toLowerCase();
    return hay.includes(q);
  }

  function renderCard(record, index) {
    const badge   = BADGE_CYCLE[index % BADGE_CYCLE.length];
    const signal  = SIGNAL_DISPLAY[record.directional_signal] || SIGNAL_DISPLAY.neutral;
    const dateStr = formatDate(record.published_date);
    const tags    = (record.tags || []).filter(Boolean).slice(0, 3);
    const volBadge = record.volatility_flag
      ? `<span class="badge badge-high" style="margin-left:6px;">⚠ Volatile</span>` : "";

    return `
      <div class="biz-card">
        <div class="card-top">
          <div class="card-title">${esc(record.headline || "Industry Update")}</div>
          <div style="display:flex;align-items:center;gap:4px;flex-shrink:0;">
            <span class="badge ${badge.cls}">${badge.label}</span>
            ${volBadge}
          </div>
        </div>

        <div class="card-signal" style="color:${signal.color};font-size:12px;font-weight:500;margin-bottom:6px;">
          ${signal.icon} ${signal.label}
          ${record.geo_scope ? `<span style="color:var(--muted);font-weight:400;margin-left:8px;">${esc(record.geo_scope)}</span>` : ""}
        </div>

        ${record.summary ? `<div class="card-body">${esc(truncate(record.summary, 220))}</div>` : ""}

        ${record.business_impact ? `
          <div class="card-takeaway">
            <span class="takeaway-icon">💼</span>
            <div class="takeaway-text">
              <span class="takeaway-label">Business Impact</span>
              ${esc(record.business_impact)}
            </div>
          </div>` : ""}

        <div class="card-meta">
          ${tags.map(t => `<span class="card-tag">${esc(t)}</span>`).join("")}
          ${record.source_name ? `<span class="card-tag" style="background:var(--blueSoft);color:var(--blue);">${esc(record.source_name)}</span>` : ""}
          ${dateStr ? `<span class="card-date">Updated ${dateStr}</span>` : ""}
        </div>
      </div>`;
  }

  // ─────────────────────────────────────────────
  // Sections renderer
  // ─────────────────────────────────────────────
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

  function renderSections() {
    const container = $("#sectionsView");
    if (!container) return;

    const q = state.q.trim().toLowerCase();
    const filtered = state.records.filter(r => {
      const catMatch = !state.activeCategory || r.category_slug === state.activeCategory;
      const searchMatch = matchesSearch(r, q);
      return catMatch && searchMatch;
    });

    if (!filtered.length) {
      container.innerHTML = emptyState("📭", "No updates found", "Try a different category or check back after the next agent run.");
      return;
    }

    // Group by category
    const grouped = {};
    filtered.forEach(r => {
      const slug = r.category_slug;
      if (!grouped[slug]) grouped[slug] = [];
      grouped[slug].push(r);
    });

    let cardIndex = 0;
    const html = Object.entries(grouped).map(([slug, records]) => {
      const disp = getDisplay(slug);
      const isOpen = !state.activeCategory || slug === state.activeCategory;
      const cards = records.map(r => renderCard(r, cardIndex++)).join("");

      return `
        <div class="section-block${isOpen ? " open" : ""}" id="section-${esc(slug)}">
          <button class="section-header" data-table="${esc(slug)}" type="button"
                  aria-expanded="${isOpen ? "true" : "false"}">
            <div class="section-header-left">
              <div class="section-icon" style="background:var(--blueSoft);">${disp.icon}</div>
              <div class="section-meta">
                <div class="section-title">${esc(disp.label)}</div>
                <div class="section-subtitle">${records.length} update${records.length !== 1 ? "s" : ""}</div>
              </div>
            </div>
            <div class="section-header-right">
              <span class="section-count">${records.length}</span>
              <span class="section-chevron">▼</span>
            </div>
          </button>
          <div class="section-body" style="display:${isOpen ? "flex" : "none"};">
            ${cards}
          </div>
        </div>`;
    }).join("");

    container.innerHTML = html;
  }

  function setActive(slug) {
    state.activeCategory = slug;
    const disp = getDisplay(slug);

    const title = $("#pageTitle");
    const sub   = $("#pageSubtitle");
    if (title) title.textContent = slug ? disp.label : "Industry Updates";
    if (sub)   sub.textContent   = slug ? disp.desc  : "All categories";

    renderIndustryNav();
    renderTableNav();
    renderCategoryPills();
    renderSections();
  }

  // ─────────────────────────────────────────────
  // Load data from PostgreSQL via /get-updates
  // ─────────────────────────────────────────────
  async function load() {
    setStatus("busy", "Loading…");
    $("#sectionsView").innerHTML = loadingState();

    const limit = Number($("#topSelect")?.value || 50);
    state.limit = limit;

    const data = await fetchJSON(`/get-updates?limit=${limit}`);
    state.records = data.updates || [];

    setStatus("ok", `Refreshed ${new Date().toLocaleTimeString()}`);
    updateHeroStrip();

    // Default to first category or all
    const firstSlug = state.records[0]?.category_slug || "";
    setActive(state.activeCategory || "");

    renderIndustryNav();
    renderTableNav();
    renderCategoryPills();
    renderSections();
  }

  // ─────────────────────────────────────────────
  // Event delegation
  // ─────────────────────────────────────────────
  document.addEventListener("click", e => {
    const assistantBtn = e.target.closest("#assistantOpenBtn, .assistant-btn");
    if (assistantBtn) { openAssistantDrawer(); return; }

    const toggleBtn = e.target.closest(".toggle-btn");
    if (toggleBtn?.dataset.mode) {
      state.readMode = toggleBtn.dataset.mode;
      if (state.readMode === "quick") {
        document.body.classList.add("quick-mode");
      } else {
        document.body.classList.remove("quick-mode");
      }
      $$(".toggle-btn").forEach(b => b.classList.toggle("active", b.dataset.mode === state.readMode));
      return;
    }

    const indBtn = e.target.closest(".ind-btn");
    if (indBtn) { setActive(indBtn.dataset.ind); return; }

    const tblBtn = e.target.closest(".topic-btn");
    if (tblBtn) { setActive(tblBtn.dataset.tbl); return; }

    const catPill = e.target.closest(".cat-pill");
    if (catPill) {
      setActive(catPill.dataset.cat === "all" ? "" : catPill.dataset.cat);
      return;
    }

    const sectionHead = e.target.closest(".section-header");
    if (sectionHead) {
      const block = sectionHead.closest(".section-block");
      const isOpen = block?.classList.contains("open");
      const body   = block?.querySelector(".section-body");
      if (block) block.classList.toggle("open", !isOpen);
      if (body)  body.style.display = isOpen ? "none" : "flex";
      sectionHead.setAttribute("aria-expanded", String(!isOpen));
      return;
    }
  });

  // ─────────────────────────────────────────────
  // DOM Ready
  // ─────────────────────────────────────────────
  document.addEventListener("DOMContentLoaded", async () => {
    try {
      $("#refreshBtn")?.addEventListener("click", load);
      $("#topSelect")?.addEventListener("change", load);

      const searchBar = $("#searchBar");
      $("#searchToggle")?.addEventListener("click", () => {
        const visible = searchBar.style.display !== "none";
        searchBar.style.display = visible ? "none" : "block";
        if (!visible) $("#searchInput")?.focus();
      });
      $("#searchClose")?.addEventListener("click", () => {
        searchBar.style.display = "none";
        state.q = "";
        renderSections();
      });
      $("#searchInput")?.addEventListener("input", e => {
        state.q = e.target.value || "";
        renderSections();
      });

      $("#assistantCloseBtn")?.addEventListener("click", closeAssistantDrawer);
      $("#assistantOverlay")?.addEventListener("click", closeAssistantDrawer);
      document.addEventListener("keydown", e => { if (e.key === "Escape") closeAssistantDrawer(); });

      document.body.classList.add("quick-mode");

      // Check for debug mode
      if (location.search.includes("debug=1")) {
        document.getElementById("debugView").style.display = "block";
      }

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
