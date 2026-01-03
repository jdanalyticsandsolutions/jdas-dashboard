<script>
/* ======================================
   JDAS Tailored Industry Updates — app.js
   Clean + Efficient API client
   ====================================== */

(() => {
  "use strict";

  // ---- Configure API base ----
  // Priority order:
  //  1) window.API_BASE (set this in your HTML when embedding in Wix)
  //  2) data-api-base attribute on <html> (optional)
  //  3) same-origin fallback (works when serving UI from backend)
  const API_BASE =
    (window.API_BASE && String(window.API_BASE).trim()) ||
    (document.documentElement?.dataset?.apiBase && String(document.documentElement.dataset.apiBase).trim()) ||
    `${location.protocol}//${location.host}`;

  // ---- Small utilities ----
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

  // ---- Fetch wrapper ----
  async function fetchJSON(path, { method = "GET", body = null, timeoutMs = 15000 } = {}) {
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

      // If server returns non-JSON unexpectedly, this will throw (good).
      return await res.json();
    } finally {
      clearTimeout(timer);
    }
  }

  // ---- Response normalizers ----
  // Summary endpoint: { ok:true, blocks:{ key:{ ok, items:[...] } } }
  function asSummaryBlocks(payload) {
    if (!isObj(payload) || payload.ok !== true || !isObj(payload.blocks)) return null;
    return payload.blocks;
  }

  // Raw endpoint: { ok:true, value:[...] }  OR  [] (if you ever return arrays directly)
  function asRows(payload) {
    if (Array.isArray(payload)) return payload;
    if (isObj(payload) && payload.ok === true && Array.isArray(payload.value)) return payload.value;
    return [];
  }

  // ---- API calls ----
  async function getRawTable(tableKey, { top = 25, orderby = "createdon desc", extra = null, timeoutMs = 20000 } = {}) {
    const qs = buildQS({ top, orderby, extra });
    const data = await fetchJSON(`/api/v1/raw/${encodeURIComponent(tableKey)}${qs}`, { timeoutMs });
    return asRows(data);
  }

  async function getIndustrySummary({ top = 10, orderby = "createdon desc", timeoutMs = 25000 } = {}) {
    const qs = buildQS({ top, orderby });
    const data = await fetchJSON(`/api/v1/summary/industry-updates${qs}`, { timeoutMs });
    return asSummaryBlocks(data) || {};
  }

  // ---- Known tables/blocks ----
  const tables = Object.freeze({
    // general market
    marketInsight:        "marketinsight",
    marketOutlook:        "marketoutlook",
    marketTrends:         "markettrendinsight",
    marketAnalysis:       "marketanalysis",

    // industries
    housingMarketInsight: "housingmarketinsight",   // real estate
    vehicleSalesForecast: "vehiclesalesforecast",   // automotive
    analyticsParadigm:    "analyticsparadigm",      // analytics & ops
    aiIndustryInsight:    "aiindustryinsight"       // ai
  });

  const summaryBlocks = Object.freeze([
    "real_estate",
    "automotive",
    "analytics_ops",
    "ai",
    "market",
    "outlook",
    "trends",
    "analysis"
  ]);

  // ---- Public API object (kept compatible with your old pattern) ----
  const api = Object.freeze({
    // meta
    API_BASE,
    docsUrl: `${API_BASE}/docs`,
    health:    () => fetchJSON(`/health`),
    healthApi: () => fetchJSON(`/api/health`).catch(() => fetchJSON(`/health`)),
    metadata:  () => fetchJSON(`/api/v1/metadata`),
    rawTables: () => fetchJSON(`/api/v1/raw/tables`),

    // raw
    raw: (tableKey, opts) => getRawTable(tableKey, opts),

    // named helpers
    marketInsight:        (opts) => getRawTable(tables.marketInsight, opts),
    marketOutlook:        (opts) => getRawTable(tables.marketOutlook, opts),
    marketTrends:         (opts) => getRawTable(tables.marketTrends, opts),
    marketAnalysis:       (opts) => getRawTable(tables.marketAnalysis, opts),

    housingMarketInsight: (opts) => getRawTable(tables.housingMarketInsight, opts),
    vehicleSalesForecast: (opts) => getRawTable(tables.vehicleSalesForecast, opts),
    analyticsParadigm:    (opts) => getRawTable(tables.analyticsParadigm, opts),
    aiIndustryInsight:    (opts) => getRawTable(tables.aiIndustryInsight, opts),

    // summary
    industryUpdatesSummary: (opts) => getIndustrySummary(opts),

    // keys
    tables,
    summaryBlocks
  });

  // Expose globally
  window.JDAS = Object.freeze({ API_BASE, api });

  // Optional: quick log so you can confirm base in Wix vs backend
  console.log("[JDAS] API_BASE:", API_BASE);

})();
</script>
