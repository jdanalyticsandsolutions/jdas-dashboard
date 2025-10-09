<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover" />
  <title>JD Analytics &amp; Solutions — Current Events in Business</title>

  <!-- External styles -->
  <link rel="stylesheet" href="/static/style.css?v=2025-10-08-a" />
  <style>.hidden{display:none!important}.error{color:#ff99aa}</style>
</head>
<body>
  <!-- Top Bar -->
  <header class="appbar">
    <div class="title">JD Analytics &amp; Solutions — Current Events in Business</div>
    <div style="display:flex;gap:8px;align-items:center">
      <div class="pill">Build: 2025-10-08a</div>
      <div class="pill" id="apiPill">API: …</div>
    </div>
  </header>

  <main class="container">
    <!-- Category Tabs -->
    <nav class="category-bar" id="categoryBar" role="tablist" aria-label="Main categories"></nav>

    <!-- Subtable Tabs (auto-rendered) -->
    <div class="subtable-bar" id="subtabs" role="tablist" aria-label="Subtables"></div>

    <!-- Current selection -->
    <section id="contentHost" class="section-host" aria-live="polite">
      <h3 id="contentTitle" style="margin:0 0 8px;">Select a dataset</h3>
      <div class="hint">Choose a category and dataset to load live data from Dataverse.</div>
    </section>

    <!-- Status -->
    <section class="card" aria-label="Status">
      <div class="status">
        <span class="badge" id="statusBadge">Checking…</span>
        <span id="statusText">Warming up API.</span>
        <span class="hint" style="margin-left:auto">Docs: <a id="docsLink" href="#" target="_blank" rel="noopener">/docs</a></span>
      </div>
    </section>

    <!-- Content stack -->
    <div class="stack">
      <section class="card" aria-label="Data">
        <h2 id="cardTitle">Dataset</h2>
        <div id="mount" class="empty">No data loaded yet.</div>
      </section>

      <section class="card" aria-label="Slides">
        <h2>JDAS Charts (Google Slides)</h2>
        <iframe
          src="https://docs.google.com/presentation/d/e/2PACX-1vRGJlR4RGlAk94AcAzCwfCT4SoWWmQRjuLHqT7mQm-8skb7zhPzvJKyqGs60i-XT_siGPS4m_vKAHrc/embed?start=false&loop=false&delayms=3000"
          width="100%" height="480" frameborder="0" allowfullscreen
          style="border:0;border-radius:12px;background:#0b0f15"></iframe>
      </section>

      <section class="card" aria-label="Chatbot">
        <h2>Ask JDAS (Chatbot)</h2>
        <iframe
          src="https://www.chatbase.co/chatbot-iframe/Vndl5JBBKFxsFxy9De-K1"
          width="100%" height="560" frameborder="0"
          style="border:0;border-radius:12px;background:transparent"
          allow="clipboard-read; clipboard-write"></iframe>
        <div class="hint">First call may take a few seconds while the API wakes.</div>
      </section>
    </div>

    <div class="spacer"></div>
  </main>

  <!-- Auto dev/prod API base -->
  <script>
    window.API_BASE = (location.hostname === "localhost" || location.hostname === "127.0.0.1")
      ? `${location.protocol}//${location.host}`
      : "https://jdas-backend.onrender.com";
  </script>

  <!-- Page logic -->
  <script>
    // ---------- Config: categories, buttons, endpoints ----------
    // NOTE: Ensure your app.py TABLES uses these exact paths.
    const TABLES = {
      trade: {
        label: "U.S. Trade",
        items: [
          { key:"tradeDeficitAnnual",  label:"Trade Deficit Annual",  path:"/api/trade-deficit-annual" },
          { key:"tariffByCountry",     label:"Tariff % by Country",   path:"/api/tariff-by-country" },   // (exists in your app.py)
          { key:"tariffByItem",        label:"Tariff By Item",        path:"/api/tariff-by-item" },
          { key:"tradeDeals",          label:"Trade Deals",           path:"/api/trade-deals" },
          { key:"tariffRevenue",       label:"Tariff Revenue",        path:"/api/tariff-revenue" }
        ]
      },
      kpi: {
        label: "KPI / Key Stats",
        items: [
          { key:"unemploymentRate",    label:"Unemployment Rate",         path:"/api/unemployment-rate" },
          { key:"inflationRate",       label:"Inflation Rate",            path:"/api/inflation-rate" },
          { key:"economicIndicatorA",  label:"Economic Indicator (A)",    path:"/api/economic-indicator" },   // jdas_economicindicator
          { key:"manufacturingPMI",    label:"Manufacturing PMI Report",  path:"/api/manufacturing-pmi-report" },
          { key:"weeklyClaims",        label:"Weekly Claims Report",      path:"/api/weekly-claims-report" },
          { key:"consumerConfidence",  label:"Consumer Confidence Index", path:"/api/consumer-confidence-index" },
          { key:"treasuryYields",      label:"Treasury Yields Record",    path:"/api/treasury-yields-record" },
          { key:"economicGrowth",      label:"Economic Growth Report",    path:"/api/economic-growth-report" },
          { key:"economicIndicatorB",  label:"Economic Indicator (B)",    path:"/api/economic-indicator-1" }  // Jdas_economicindictator1
        ]
      },
      global: {
        label: "Global Events",
        items: [
          { key:"corporateSpinoff",    label:"Corporate SpinOff",         path:"/api/corporate-spinoff" },
          { key:"conflictRecord",      label:"Conflict Record",            path:"/api/conflict-record" },
          { key:"globalDisasters",     label:"Global Natural Disasters",   path:"/api/global-natural-disasters" }
        ]
      },
      labor: {
        label: "Labor & Society",
        items: [
          { key:"publicRevenueLoss",   label:"Publicly Annouced Revenue Loss", path:"/api/publicly-annouced-revenue-loss" },
          { key:"layoffAnnouncement",  label:"Layoff Announcement",             path:"/api/layoff-announcement" },
          { key:"acquisitionDeal",     label:"Acquisition Deal",                path:"/api/acquisition-deal" },
          { key:"bankruptcyLog",       label:"Bankruptcy Log",                  path:"/api/bankruptcies" } // your existing path
        ]
      },
      energy: {
        label: "Environmental & Energy",
        items: [
          { key:"envReg",              label:"Environmental Regulation",  path:"/api/environmental-regulation" },
          { key:"envPolicy",           label:"Environmental Policy",      path:"/api/environmental-policy" },
          { key:"infraInvestment",     label:"Infrastructure Investment", path:"/api/infrastructure-investment" }
        ]
      }
    };

    // ---------- Small helpers ----------
    const API_BASE   = window.API_BASE || `${location.protocol}//${location.host}`;
    const $          = (s) => document.querySelector(s);
    const apiPill    = $("#apiPill");
    const docsLink   = $("#docsLink");
    const contentTitle = $("#contentTitle");
    const statusBadge  = $("#statusBadge");
    const statusText   = $("#statusText");
    const categoryBar  = $("#categoryBar");
    const subtabs      = $("#subtabs");
    const cardTitle    = $("#cardTitle");
    const mount        = $("#mount");

    if (apiPill)  apiPill.textContent = `API: ${API_BASE}`;
    if (docsLink) docsLink.href       = `${API_BASE}/docs`;

    function escapeHTML(s){ return String(s).replaceAll("&","&amp;").replaceAll("<","&lt;").replaceAll(">","&gt;").replaceAll('"',"&quot;").replaceAll("'","&#39;"); }
    function valueToText(v){ if(v==null) return ""; if(typeof v==="object") return JSON.stringify(v); return String(v); }

    function setStatus(kind, text){
      statusBadge?.classList.remove("ok","err");
      if(kind==="ok")  statusBadge?.classList.add("ok");
      if(kind==="err") statusBadge?.classList.add("err");
      statusBadge && (statusBadge.textContent = kind==="ok" ? "OK" : kind==="err" ? "Error" : "Loading…");
      statusText && (statusText.textContent   = text);
    }

    async function fetchJSON(path, { method="GET", body=null } = {}){
      const url = `${API_BASE}${path}`;
      const res = await fetch(url, { method, body, cache:"no-store", headers:{ "Accept":"application/json" } });
      if(!res.ok){
        const txt = await res.text().catch(()=> "");
        throw new Error(`HTTP ${res.status} ${res.statusText} — ${url}\n${txt.slice(0,300)}`);
      }
      return res.json();
    }

    function renderTable(rows){
      if(!rows || !rows.length){
        mount.className = "empty";
        mount.innerHTML = "No rows found.";
        return;
      }
      const cols = Array.from(rows.reduce((s,r)=>{Object.keys(r).forEach(k=>s.add(k));return s;}, new Set()));
      const thead = `<thead><tr>${cols.map(c=>`<th>${escapeHTML(c)}</th>`).join("")}</tr></thead>`;
      const tbody = `<tbody>${rows.map(r=>`<tr>${
        cols.map(c=>`<td>${escapeHTML(valueToText(r[c]))}</td>`).join("")
      }</tr>`).join("")}</tbody>`;
      mount.className = "tablewrap";
      mount.innerHTML = `<table>${thead}${tbody}</table>`;
    }

    // ---------- UI wiring ----------
    let currentCat = null;
    let currentItem = null;

    function buildCategoryBar(){
      const cats = Object.keys(TABLES);
      categoryBar.innerHTML = cats.map((cat,i)=>{
        const active = i===0 ? "active" : "";
        return `<button class="nav-btn ${active}" data-cat="${cat}" role="tab" aria-selected="${i===0}">${escapeHTML(TABLES[cat].label)}</button>`;
      }).join("");
      currentCat = cats[0];
    }

    function buildSubtabs(){
      const items = TABLES[currentCat].items;
      subtabs.innerHTML = items.map((it,i)=>{
        const active = i===0 ? "active":"";
        return `<button class="nav-btn ${active}" data-key="${it.key}" role="tab" aria-selected="${i===0}">${escapeHTML(it.label)}</button>`;
      }).join("");
      currentItem = items[0].key;
    }

    async function loadCurrent(){
      const group = TABLES[currentCat];
      const item  = group.items.find(it=>it.key===currentItem);
      const title = `${group.label} — ${item.label}`;
      contentTitle.textContent = title;
      cardTitle.textContent    = item.label;
      try {
        setStatus("", `Loading ${item.label}…`);
        mount.className = "loading";
        mount.textContent = `Loading ${item.label}…`;
        const data = await fetchJSON(item.path);
        renderTable(Array.isArray(data) ? data : (data?.value || []));
        setStatus("ok", `Loaded ${item.label}.`);
      } catch (err) {
        mount.className = "empty";
        mount.innerHTML = `<div class="error">Failed to load ${escapeHTML(item.label)}.</div><div class="hint">${escapeHTML(err.message)}</div>`;
        setStatus("err", `Failed to load ${item.label}.`);
      }
    }

    // Events
    categoryBar.addEventListener("click", (e)=>{
      const btn = e.target.closest("button[data-cat]");
      if(!btn) return;
      if(btn.dataset.cat === currentCat) return;
      // toggle
      [...categoryBar.querySelectorAll("button[data-cat]")].forEach(b=>b.classList.toggle("active", b===btn));
      currentCat = btn.dataset.cat;
      buildSubtabs();
      loadCurrent();
    });

    subtabs.addEventListener("click", (e)=>{
      const btn = e.target.closest("button[data-key]");
      if(!btn) return;
      [...subtabs.querySelectorAll("button[data-key]")].forEach(b=>b.classList.toggle("active", b===btn));
      currentItem = btn.dataset.key;
      loadCurrent();
    });

    // ---------- Health warmup ----------
    (async ()=>{
      for(let i=0;i<6;i++){
        try{
          const j = await fetchJSON("/api/health");
          if(j && j.ok){ setStatus("ok","API ready."); break; }
        }catch{ setStatus("", "Warming API…"); }
        await new Promise(r=>setTimeout(r,5000));
      }
    })();

    // ---------- Boot ----------
    buildCategoryBar();
    buildSubtabs();
    loadCurrent();
  </script>
</body>
</html>
