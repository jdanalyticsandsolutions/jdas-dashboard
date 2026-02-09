(() => {
  "use strict";

  // Use same origin; keep as-is for Render/GitHub hosted frontend + backend same host
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

  // Treat certain industry keys as the AI Assistant "button"
  function isAssistantKey(key) {
    const k = String(key || "").toLowerCase();
    // Adjust if your config uses a specific key like "ai_assistant"
    return (
      k === "ai_assistant" ||
      k === "assistant" ||
      k.includes("assistant") ||
      k.includes("chat") ||
      k.includes("chatbot")
    );
  }

  /* =========================
     Status
  ========================= */
  function setStatus(kind, text) {
    const dot = $("#statusDot");
    const label = $("#statusText");
    if (dot) {
      dot.classList.remove("ok", "err", "busy");
      dot.classList.add(kind);
    }
    if (label) label.textContent = text || "";
  }

  async function fetchJSON(path) {
    const res = await fetch(`${API_BASE}${path}`, { cache: "no-store" });
    if (!res.ok) throw new Error(`HTTP ${res.status} ${res.statusText}`);
    return await res.json();
  }

  /* =========================
     Chatbase Drawer (iframe)
     - Loads once on first open
  ========================= */
  let chatbaseLoaded = false;

  function loadChatbaseOnce() {
    const mount = document.getElementById("chatbaseMount");
    if (!mount) {
      console.warn("[JDAS] chatbaseMount not found in HTML.");
      return;
    }

    // If iframe already exists, consider it loaded
    if (mount.querySelector("iframe")) {
      chatbaseLoaded = true;
      return;
    }

    if (chatbaseLoaded) return;
    chatbaseLoaded = true;

    mount.innerHTML = `
      <iframe
        src="https://www.chatbase.co/chatbot-iframe/Vndl5JBBKFxsFxy9De-K1"
        width="100%"
        height="100%"
        style="border:0; min-height: 700px;"
        loading="lazy"
        allow="clipboard-write; microphone"
      ></iframe>
    `;
  }

  function openAssistantDrawer() {
    const drawer = document.getElementById("assistantDrawer");
    if (!drawer) {
      console.warn("[JDAS] assistantDrawer not found in HTML.");
      return;
    }

    loadChatbaseOnce();

    drawer.classList.add("open");
    drawer.setAttribute("aria-hidden", "false");
    document.body.classList.add("no-scroll");

    // Optional: focus for accessibility
    drawer.setAttribute("tabindex", "-1");
    drawer.focus?.();
  }

  function closeAssistantDrawer() {
    const drawer = document.getElementById("assistantDrawer");
    if (!drawer) return;

    drawer.classList.remove("open");
    drawer.setAttribute("aria-hidden", "true");
    document.body.classList.remove("no-scroll");
  }

  /* =========================
     App state
  ========================= */
  const state = {
    config: null,
    blocks: null,
    activeIndustry: null,
    activeTableKey: null,
    view: "sections",
    top: 10,
    q: "",
  };

  function getIndustry() {
    return state.config?.industries?.find((i) => i.key === state.activeIndustry) || null;
  }

  function getTable() {
    const ind = getIndustry();
    return ind?.tables?.find((t) => t.key === state.activeTableKey) || null;
  }

  function setView(view) {
    state.view = view;
    $("#sectionsView").style.display = view === "sections" ? "block" : "none";
    $("#cardsView").style.display = view === "cards" ? "block" : "none";
    $("#tableView").style.display = view === "table" ? "block" : "none";
    $("#debugView").style.display = view === "raw" ? "block" : "none";
    render();
  }

  function setActive(indKey, tableKey) {
    state.activeIndustry = indKey;
    state.activeTableKey = tableKey;

    // highlight nav (industry/table only)
    $$("#industryNav .navitem").forEach((b) =>
      b.classList.toggle("active", b.dataset.key === indKey)
    );
    $$("#tableNav .navitem").forEach((b) =>
      b.classList.toggle("active", b.dataset.key === tableKey)
    );

    const ind = getIndustry();
    const tbl = getTable();

    $("#pageTitle").textContent = ind?.label || "Industry Updates";
    $("#pageSubtitle").textContent = tbl ? `Table: ${tbl.label} (${tbl.logical})` : "—";

    render();
  }

  function renderIndustryNav() {
    const nav = $("#industryNav");

    nav.innerHTML = state.config.industries
      .map((ind) => {
        const assistantClass = isAssistantKey(ind.key) ? " assistant-btn" : "";
        return `
          <button class="navitem${assistantClass}" data-key="${esc(ind.key)}" type="button">
            <span>${esc(ind.label)}</span>
          </button>
        `;
      })
      .join("");
  }

  function renderTableNav(ind) {
    const nav = $("#tableNav");

    // If assistant industry, we usually don't want tables shown
    if (ind && isAssistantKey(ind.key)) {
      nav.innerHTML = `<div class="empty small">Chat assistant</div>`;
      return;
    }

    nav.innerHTML = (ind?.tables || [])
      .map(
        (t) => `
        <button class="navitem" data-key="${esc(t.key)}" type="button" title="${esc(t.logical)}">
          <span>${esc(t.label)}</span>
          <span class="chip">${esc(t.tag || "")}</span>
        </button>
      `
      )
      .join("");
  }

  function allItemsForActiveIndustry() {
    const blk = state.blocks?.[state.activeIndustry];
    if (!blk?.tables) return [];
    const out = [];
    for (const tKey of Object.keys(blk.tables)) {
      const t = blk.tables[tKey];
      for (const item of t.items || []) out.push(item);
    }
    return out;
  }

  function matchesSearch(item, q) {
    if (!q) return true;
    const hay = [item.title, item.body, item.tag, item.table_label, item.table, item.id]
      .join(" ")
      .toLowerCase();
    return hay.includes(q);
  }

  function renderSections() {
    const container = $("#sectionsView");
    const blk = state.blocks?.[state.activeIndustry];
    if (!blk?.tables) {
      container.innerHTML = `<div class="empty">No data.</div>`;
      return;
    }

    const q = state.q.trim().toLowerCase();

    const sections = Object.entries(blk.tables)
      .map(([tKey, tObj]) => {
        const items = (tObj.items || []).filter((it) => matchesSearch(it, q));
        const open = tKey === state.activeTableKey;

        const rows = items.length
          ? items
              .map(
                (it) => `
              <div class="rowcard">
                <div class="rowhead">
                  <div class="rowtitle">${esc(it.title || "Update")}</div>
                  <div class="rowmeta">
                    <span class="chip">${esc(it.tag || "")}</span>
                    <span class="mono">${esc((it.id || "").slice(0, 8))}</span>
                    <span class="mono">${esc(it.createdOn || "")}</span>
                  </div>
                </div>
                <div class="rowbody">${esc(it.body || "")}</div>
              </div>
            `
              )
              .join("")
          : `<div class="empty small">No matches.</div>`;

        return `
          <section class="section">
            <button class="sectionhead" data-table="${esc(tKey)}" aria-expanded="${open ? "true" : "false"}" type="button">
              <div>
                <div class="sectiontitle">${esc(tObj.label || tKey)}</div>
                <div class="muted mono">${esc(tObj.logical || "")}</div>
              </div>
              <div class="sectionright">
                <span class="count">${items.length}</span>
              </div>
            </button>

            <div class="sectionbody" style="display:${open ? "block" : "none"}">
              ${rows}
            </div>
          </section>
        `;
      })
      .join("");

    container.innerHTML = sections;
  }

  function renderCards() {
    const container = $("#cardsView");
    const q = state.q.trim().toLowerCase();

    const items = allItemsForActiveIndustry()
      .filter((it) => !state.activeTableKey || it.table_key === state.activeTableKey)
      .filter((it) => matchesSearch(it, q));

    if (!items.length) {
      container.innerHTML = `<div class="empty">No matches.</div>`;
      return;
    }

    container.innerHTML = `
      <div class="cards">
        ${items
          .map(
            (it) => `
          <div class="carditem">
            <div class="t">${esc(it.title || "Update")}</div>
            <div class="meta">
              <span class="chip">${esc(it.table_label || it.table_key)}</span>
              <span class="chip">${esc(it.tag || "")}</span>
              <span class="mono">${esc((it.id || "").slice(0, 8))}</span>
            </div>
            <div class="b">${esc(it.body || "")}</div>
          </div>
        `
          )
          .join("")}
      </div>
    `;
  }

  function renderTable() {
    const container = $("#tableView");
    const blk = state.blocks?.[state.activeIndustry];
    const tObj = blk?.tables?.[state.activeTableKey];
    const items = tObj?.items || [];

    if (!state.activeTableKey) {
      container.innerHTML = `<div class="empty">Pick a table on the left.</div>`;
      return;
    }
    if (!items.length) {
      container.innerHTML = `<div class="empty">No rows.</div>`;
      return;
    }

    const baseCols = ["title", "body", "tag", "createdOn", "id"];
    const extraCols = Object.keys(items[0])
      .filter((k) => !baseCols.includes(k) && !["source"].includes(k))
      .slice(0, 6);

    const cols = [...baseCols, ...extraCols];

    container.innerHTML = `
      <div class="tablewrap">
        <table class="dvtable">
          <thead><tr>${cols.map((c) => `<th>${esc(c)}</th>`).join("")}</tr></thead>
          <tbody>
            ${items
              .map(
                (it) => `
              <tr>
                ${cols.map((c) => `<td>${esc(it[c])}</td>`).join("")}
              </tr>
            `
              )
              .join("")}
          </tbody>
        </table>
      </div>
    `;
  }

  function renderRaw() {
    $("#rawJson").textContent = JSON.stringify(
      { config: state.config, blocks: state.blocks },
      null,
      2
    );
  }

  function render() {
    if (!state.config || !state.blocks) return;

    if (state.view === "sections") renderSections();
    if (state.view === "cards") renderCards();
    if (state.view === "table") renderTable();
    if (state.view === "raw") renderRaw();
  }

  async function load() {
    setStatus("busy", "Loading…");

    const health = await fetchJSON("/api/v1/health");
    $("#buildStamp").textContent = `Build: ${health.build_stamp} • v${health.version}`;

    state.config = await fetchJSON("/api/v1/config");
    state.top = Number($("#topSelect").value || 10);

    renderIndustryNav();

    // default selection: first NON-assistant industry if possible
    const firstNonAssistant =
      state.config.industries?.find((i) => !isAssistantKey(i.key)) || state.config.industries?.[0];

    state.activeIndustry = firstNonAssistant?.key || "real_estate";
    const ind = state.config.industries?.find((i) => i.key === state.activeIndustry);
    state.activeTableKey = ind?.tables?.[0]?.key || "";

    renderTableNav(ind);

    // load blocks
    const data = await fetchJSON(`/api/v1/summary/industry-updates?top=${state.top}`);
    state.blocks = data.blocks || {};

    setStatus("ok", `Updated: ${new Date().toLocaleTimeString()}`);
    setActive(state.activeIndustry, state.activeTableKey);
  }

  /* =========================
     Global Click Handler
     - IMPORTANT: assistant behavior first
  ========================= */
  document.addEventListener("click", (e) => {
    // 1) Dedicated assistant buttons (id or class)
    const assistantBtn = e.target.closest("#assistantOpenBtn, .assistant-btn");
    if (assistantBtn) {
      openAssistantDrawer();
      return;
    }

    const indBtn = e.target.closest("#industryNav .navitem");
    const tblBtn = e.target.closest("#tableNav .navitem");
    const sectHead = e.target.closest(".sectionhead");

    // 2) Industry click
    if (indBtn) {
      const indKey = indBtn.dataset.key;

      // If this "industry" is the assistant, open drawer instead of changing views
      if (isAssistantKey(indKey)) {
        openAssistantDrawer();
        return;
      }

      const ind = state.config.industries.find((i) => i.key === indKey);
      renderTableNav(ind);
      setActive(indKey, ind?.tables?.[0]?.key || "");
      return;
    }

    // 3) Table click
    if (tblBtn) {
      setActive(state.activeIndustry, tblBtn.dataset.key);
      return;
    }

    // 4) Section expand/collapse
    if (sectHead) {
      const tKey = sectHead.dataset.table;
      const isOpen = sectHead.getAttribute("aria-expanded") === "true";
      sectHead.setAttribute("aria-expanded", isOpen ? "false" : "true");
      const body = sectHead.parentElement.querySelector(".sectionbody");
      if (body) body.style.display = isOpen ? "none" : "block";
      if (!isOpen) setActive(state.activeIndustry, tKey);
      return;
    }
  });

  /* =========================
     DOM Ready: controls + drawer close behavior
  ========================= */
  document.addEventListener("DOMContentLoaded", async () => {
    try {
      // Dashboard core
      $("#refreshBtn")?.addEventListener("click", load);
      $("#topSelect")?.addEventListener("change", load);
      $("#viewSelect")?.addEventListener("change", (e) => setView(e.target.value));
      $("#searchInput")?.addEventListener("input", (e) => {
        state.q = e.target.value || "";
        render();
      });

      // Drawer close controls
      const assistantCloseBtn = document.getElementById("assistantCloseBtn");
      const assistantOverlay = document.getElementById("assistantOverlay");

      assistantCloseBtn?.addEventListener("click", closeAssistantDrawer);
      assistantOverlay?.addEventListener("click", closeAssistantDrawer);

      document.addEventListener("keydown", (e) => {
        if (e.key === "Escape") closeAssistantDrawer();
      });

      // Initial load
      await load();
      setView("sections");
    } catch (err) {
      console.error(err);
      setStatus("err", "Failed to load. Check Render logs / API.");
    }
  });
})();
