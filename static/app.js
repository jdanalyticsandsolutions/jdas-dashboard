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
    // Backend always returns 200, even on upstream errors (ok:false),
    // so we only error on non-2xx here.
    if (!res.ok) {
      const text = await res.text().catch(() => "");
      throw new Error(`HTTP ${res.status} ${res.statusText} — ${url}\n${text.slice(0,300)}`);
    }
    return await res.json();
  } finally {
    clearTimeout(t);
  }
}

// ---------- normalize to rows ----------
function toRows(data, { allowEmpty = true } = {}) {
  // old behavior: endpoint returned an array
  if (Array.isArray(data)) return data;

  // new behavior: { ok, value: [] } or { ok:false, error }
  if (data && typeof data === "object") {
    if (data.ok === true && Array.isArray(data.value)) return data.value;
    if (data.ok === false) {
      console.warn("API returned ok:false", data);
      return allowEmpty ? [] : [];
    }
  }
  console.warn("Unexpected API payload shape:", data);
  return allowEmpty ? [] : [];
}

// ---------- Public loaders (fixed paths) ----------
async function getRows(path) {
  const data = await fetchJSON(path);
  return toRows(data);
}

const api = {
  // NOTE: this route doesn't exist in your backend TABLES yet.
  // Either implement it server-side or comment out here to avoid 404s.
  // companyInvestments: (top=5000)=> getRows(`/api/company-investments?top=${encodeURIComponent(top)}`),

  bankruptcies: (top=500) => getRows(`/api/bankruptcies?top=${encodeURIComponent(top)}&nocache=1`),

  // FIX: backend path is /api/layoff-announcement (not /api/layoffs)
  layoffs: (top=500) => getRows(`/api/layoff-announcement?top=${encodeURIComponent(top)}&nocache=1`),

  tariffByCountry: (top=500) => getRows(`/api/tariff-by-country?top=${encodeURIComponent(top)}&nocache=1`),

  health: () => fetchJSON(`/health`),
  metadata: () => fetchJSON(`/api/metadata`),
  docsUrl: `${API_BASE}/docs`
};

// Expose
window.JDAS = { API_BASE, api };

// Optional: quick smoke test
// api.health().then(console.log).catch(console.error);
// api.metadata().then(console.table).catch(console.error);
</script>
