<script>
// ---------- API base resolution ----------
// If index.html sets window.API_BASE, use it; otherwise default to same-origin (local dev).
const API_BASE = (window.API_BASE && String(window.API_BASE).trim())
  || `${location.protocol}//${location.host}`;

// ---------- fetch helper with timeout & no-store ----------
async function fetchJSON(path, { method = "GET", body = null, timeoutMs = 15000 } = {}) {
  const url = `${API_BASE}${path}`;
  const ac = new AbortController();
  const t = setTimeout(() => ac.abort(new DOMException("Timeout", "AbortError")), timeoutMs);
  try {
    const res = await fetch(url, {
      method,
      body,
      cache: "no-store",
      headers: { "Accept": "application/json" },
      signal: ac.signal
    });
    if (!res.ok) {
      const text = await res.text().catch(() => "");
      throw new Error(`HTTP ${res.status} ${res.statusText} — ${url}\n${text.slice(0,300)}`);
    }
    return await res.json();
  } finally {
    clearTimeout(t);
  }
}

// ---------- Public loaders ----------
const api = {
  companyInvestments: (top = 5000) => fetchJSON(`/api/company-investments?top=${encodeURIComponent(top)}`),
  bankruptcies:       ()            => fetchJSON("/api/bankruptcies"),
  layoffs:            ()            => fetchJSON("/api/layoffs"),
  tariffByCountry:    ()            => fetchJSON("/api/tariff-by-country"),
  health:             ()            => fetchJSON("/health"),
  docsUrl:            ()            => `${API_BASE}/docs`
};

// Expose in a namespaced way
window.JDAS = { API_BASE, api };

// Optional quick smoke test (uncomment if needed):
// api.health().then(console.log).catch(console.error);
</script>
