<script>
// ---------- API base resolution ----------
const API_BASE =
  (window.API_BASE && String(window.API_BASE).trim())
  || `${location.protocol}//${location.host}`;

// ---------- low-level fetch ----------
async function fetchJSON(path, { method = "GET", body = null, timeoutMs = 15000 } = {}) {
  const url = `${API_BASE}${path}`;
  const ac = new AbortController();
  const t = setTimeout(() => ac.abort(new DOMException("Timeout","AbortError")), timeoutMs);
  try {
    const res = await fetch(url, {
      method, body, cache: "no-store",
      headers: { "Accept": "application/json" },
      signal: ac.signal
    });

    // Backend returns 200 even when ok:false, so only hard-fail non-2xx here.
    if (!res.ok) {
      const text = await res.text().catch(() => "");
      throw new Error(`HTTP ${res.status} ${res.statusText} — ${url}\n${text.slice(0,300)}`);
    }
    return await res.json();
  } finally {
    clearTimeout(t);
  }
}

// ---------- helpers ----------
function isObj(x){ return x && typeof x === "object" && !Array.isArray(x); }

// Summary endpoint shape: { ok:true, blocks:{ key:{ ok, items:[...] } } }
function toSummaryBlocks(data){
  if (!isObj(data)) return null;
  if (data.ok !== true) return null;
  if (!isObj(data.blocks)) return null;
  return data.blocks;
}

// Raw table endpoint shape: { ok:true, value:[...] }
function toRows(data, { allowEmpty = true } = {}){
  if (Array.isArray(data)) return data;
  if (isObj(data)) {
    if (data.ok === true && Array.isArray(data.value)) return data.value;
    if (data.ok === false) return allowEmpty ? [] : [];
  }
  return allowEmpty ? [] : [];
}

function encodeQS(params){
  const out = [];
  for (const [k,v] of Object.entries(params || {})){
    if (v === undefined || v === null || v === "") continue;
    out.push(`${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`);
  }
  return out.length ? `?${out.join("&")}` : "";
}

// ---------- Public loaders (NEW APP paths) ----------
async function getRawTable(tableKey, { top = 25, orderby = "createdon desc", extra = null, timeoutMs = 20000 } = {}) {
  // extra is optional raw OData append (advanced). Example: "$filter=..."
  // Your backend expects it as "extra" (already appended server-side).
  const qs = encodeQS({ top, orderby, extra });
  const data = await fetchJSON(`/api/v1/raw/${encodeURIComponent(tableKey)}${qs}`, { timeoutMs });
  return toRows(data);
}

async function getIndustrySummary({ top = 10, orderby = "createdon desc", timeoutMs = 25000 } = {}) {
  const qs = encodeQS({ top, orderby });
  const data = await fetchJSON(`/api/v1/summary/industry-updates${qs}`, { timeoutMs });

  const blocks = toSummaryBlocks(data);
  if (!blocks) {
    console.warn("Unexpected summary payload:", data);
    return {};
  }
  return blocks;
}

// ---------- Convenience: known tables/blocks ----------
const tables = {
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
};

// Blocks returned by /summary/industry-updates
const summaryBlocks = [
  "real_estate",
  "automotive",
  "analytics_ops",
  "ai",
  "market",
  "outlook",
  "trends",
  "analysis"
];

// ---------- API object ----------
const api = {
  // health & meta
  health:   () => fetchJSON(`/health`),
  healthApi:() => fetchJSON(`/api/health`).catch(()=> fetchJSON(`/health`)),
  docsUrl:  `${API_BASE}/docs`,
  metadata: () => fetchJSON(`/api/v1/metadata`), // new metadata route

  // list available table keys
  rawTables: () => fetchJSON(`/api/v1/raw/tables`),

  // raw table fetch (all columns)
  raw: (tableKey, opts) => getRawTable(tableKey, opts),

  // named raw helpers
  marketInsight: (opts)        => getRawTable(tables.marketInsight, opts),
  marketOutlook: (opts)        => getRawTable(tables.marketOutlook, opts),
  marketTrends:  (opts)        => getRawTable(tables.marketTrends, opts),
  marketAnalysis:(opts)        => getRawTable(tables.marketAnalysis, opts),

  housingMarketInsight: (opts) => getRawTable(tables.housingMarketInsight, opts),
  vehicleSalesForecast: (opts) => getRawTable(tables.vehicleSalesForecast, opts),
  analyticsParadigm:    (opts) => getRawTable(tables.analyticsParadigm, opts),
  aiIndustryInsight:    (opts) => getRawTable(tables.aiIndustryInsight, opts),

  // one-call dashboard loader
  industryUpdatesSummary: (opts) => getIndustrySummary(opts),

  // expose known keys
  tables,
  summaryBlocks
};

// Expose globally (same style as your old app)
window.JDAS = { API_BASE, api };

// Optional quick smoke tests:
// api.healthApi().then(console.log).catch(console.error);
// api.rawTables().then(console.log).catch(console.error);
// api.industryUpdatesSummary({ top: 5 }).then(console.log).catch(console.error);
</script>
