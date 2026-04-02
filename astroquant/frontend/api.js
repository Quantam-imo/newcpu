// ---------- ERROR BANNER (GLOBAL) ----------
function showError(key, message, retryFn = null, autoDismiss = true) {
	let errorBannerContainerEl = document.getElementById("errorBannerContainer");
	if (!errorBannerContainerEl) {
		errorBannerContainerEl = document.createElement("div");
		errorBannerContainerEl.id = "errorBannerContainer";
		errorBannerContainerEl.style.position = "fixed";
		errorBannerContainerEl.style.top = "10px";
		errorBannerContainerEl.style.right = "10px";
		errorBannerContainerEl.style.zIndex = 9999;
		document.body.appendChild(errorBannerContainerEl);
	}
	if (!window._activeErrors) window._activeErrors = new Map();
	if (window._activeErrors.has(key)) clearTimeout(window._activeErrors.get(key).timeout);
	const errorDiv = document.createElement("div");
	errorDiv.id = `error-${key}`;
	errorDiv.className = "error-banner";
	errorDiv.style.background = "#2a3b59";
	errorDiv.style.color = "#fff";
	errorDiv.style.padding = "10px 18px";
	errorDiv.style.margin = "8px 0";
	errorDiv.style.borderRadius = "8px";
	errorDiv.style.boxShadow = "0 2px 8px rgba(0,0,0,0.18)";
	errorDiv.style.display = "flex";
	errorDiv.style.alignItems = "center";
	errorDiv.style.gap = "10px";
	const errorText = document.createElement("div");
	errorText.className = "error-text";
	errorText.textContent = message;
	errorDiv.appendChild(errorText);
	if (retryFn) {
		const retryBtn = document.createElement("button");
		retryBtn.className = "retry-btn";
		retryBtn.textContent = "Retry";
		retryBtn.onclick = () => { retryFn(); removeError(key); };
		retryBtn.style.marginLeft = "8px";
		errorDiv.appendChild(retryBtn);
	}
	const closeBtn = document.createElement("button");
	closeBtn.className = "close-btn";
	closeBtn.textContent = "×";
	closeBtn.onclick = () => removeError(key);
	closeBtn.style.marginLeft = "8px";
	errorDiv.appendChild(closeBtn);
	errorBannerContainerEl.appendChild(errorDiv);
	const timeout = autoDismiss ? setTimeout(() => removeError(key), 12000) : null;
	window._activeErrors.set(key, { errorDiv, retryFn, timeout });
}

function removeError(key) {
	if (!window._activeErrors) return;
	if (window._activeErrors.has(key)) {
		const { errorDiv, timeout } = window._activeErrors.get(key);
		if (timeout) clearTimeout(timeout);
		if (errorDiv && errorDiv.parentNode) errorDiv.remove();
		window._activeErrors.delete(key);
	}
}
// ==========================
// PRO API ENGINE (ASTRAQUANT)
// ==========================

// ---------- CONFIG ----------
const API_CONFIG = {
	TIMEOUT: 30000,
  MAX_RETRIES: 3,
  BASE_DELAY: 400,
  FAILURE_THRESHOLD: 3,
  CIRCUIT_RESET_TIME: 15000,
};

const CIRCUIT_EXEMPT_WRITE_PATHS = [
	"/execution/reconnect",
	"/execution/recover",
	"/status/broker_bridge/recover",
];

function isCircuitExemptWritePath(path) {
	const target = String(path || "");
	return CIRCUIT_EXEMPT_WRITE_PATHS.some(prefix => target.startsWith(prefix));
}

// ---------- ENDPOINTS ----------
// Use the same origin the page was loaded from so VS Code port-forwarding
// (8001→8000) proxies API calls transparently without CORS headers needed.
const API_ENDPOINTS = [
	"",
	(typeof window !== "undefined" && window.AQ_API_BASE) ? window.AQ_API_BASE : ""
];

// ---------- STATE ----------
const circuitState = {
  failures: 0,
  open: false,
  lastFailureTime: 0,
};

const inFlightRequests = new Map();

if (!window.__aqSingletonIntervals) {
	window.__aqSingletonIntervals = {};
}

function setSingletonInterval(key, fn, ms) {
	const k = String(key || "");
	if (!k) return null;
	const existing = window.__aqSingletonIntervals[k];
	if (existing) {
		clearInterval(existing);
	}
	const id = setInterval(fn, ms);
	window.__aqSingletonIntervals[k] = id;
	return id;
}

// ---------- CACHE ----------
const CACHE_PREFIX = "AQ_CACHE_";

function cacheKey(path) {
  return CACHE_PREFIX + path;
}

function setCache(path, data, ttl = 5000) {
  try {
    localStorage.setItem(
      cacheKey(path),
      JSON.stringify({ data, exp: Date.now() + ttl })
    );
  } catch {}
}

function getCache(path) {
  try {
    const raw = localStorage.getItem(cacheKey(path));
    if (!raw) return null;

    const parsed = JSON.parse(raw);
    if (Date.now() > parsed.exp) {
      localStorage.removeItem(cacheKey(path));
      return null;
    }
    return parsed.data;
  } catch {
    return null;
  }
}

// ---------- CIRCUIT BREAKER ----------
function isCircuitOpen() {
  if (!circuitState.open) return false;

  const now = Date.now();
  if (now - circuitState.lastFailureTime > API_CONFIG.CIRCUIT_RESET_TIME) {
    circuitState.open = false;
    circuitState.failures = 0;
    return false;
  }

  return true;
}

function recordFailure() {
  circuitState.failures++;

  if (circuitState.failures >= API_CONFIG.FAILURE_THRESHOLD) {
    circuitState.open = true;
    circuitState.lastFailureTime = Date.now();
    console.warn("🚨 Circuit OPEN (API unstable)");
  }
}

function recordSuccess() {
  circuitState.failures = 0;
  circuitState.open = false;
}

function resetCircuitState() {
	circuitState.failures = 0;
	circuitState.open = false;
	circuitState.lastFailureTime = 0;
}

function isTimeoutLikeError(err) {
	const name = String(err?.name || "").toLowerCase();
	const msg = String(err?.message || err || "").toLowerCase();
	return name.includes("abort") || msg.includes("timeout") || msg.includes("aborted");
}

function shouldRetryError(err) {
	const status = Number(err?.status);
	if (Number.isFinite(status) && status >= 400 && status < 500 && status !== 408 && status !== 429) {
		return false;
	}
	return true;
}

// ---------- RETRY WITH JITTER ----------
async function retry(fn, retries = API_CONFIG.MAX_RETRIES) {
  let attempt = 0;

  while (attempt <= retries) {
    try {
      return await fn();
    } catch (err) {
		if (!shouldRetryError(err)) throw err;
      if (attempt === retries) throw err;

      const delay =
        API_CONFIG.BASE_DELAY *
        Math.pow(2, attempt) *
        (1 + Math.random());

      await new Promise((r) => setTimeout(r, delay));
      attempt++;
    }
  }
}

// ---------- CORE FETCH ----------
async function coreFetch(url, options, timeout) {
  const controller = new AbortController();
	const timer = setTimeout(() => controller.abort(new Error("request_timeout")), timeout);

  try {
    const res = await fetch(url, {
      ...options,
      signal: controller.signal,
    });

    clearTimeout(timer);

		if (!res.ok) {
			const httpErr = new Error("HTTP " + res.status);
			httpErr.status = res.status;
			throw httpErr;
		}

    return res;
  } catch (err) {
    clearTimeout(timer);
    throw err;
  }
}

// ---------- MAIN ENGINE ----------
async function apiFetch(path, options = {}, timeout = API_CONFIG.TIMEOUT) {
  const method = String(options.method || "GET").toUpperCase();
	const cachePath = path;
  const isReadOnly = method === "GET" || method === "HEAD";
	const exemptWritePath = !isReadOnly && isCircuitExemptWritePath(path);

  // 🚫 CIRCUIT BREAKER
  // Keep read-only observability endpoints available even when trading safety trips.
	if (isCircuitOpen() && !isReadOnly && !exemptWritePath) {
    console.warn("⚠️ API blocked by circuit breaker");

    return new Response(
      JSON.stringify({
        status: "blocked",
        reason: "circuit_open",
      }),
      { status: 503 }
    );
  }

  // ⚡ REQUEST DEDUPLICATION
  // inFlightRequests stores data promises (not Response objects) so each caller
  // gets its own fresh Response and cannot see "body stream already read" errors.
  const key = method + ":" + path;
  if (inFlightRequests.has(key)) {
    try {
      const { status, bodyText } = await inFlightRequests.get(key);
      return new Response(bodyText, { status, headers: { "Content-Type": "application/json" } });
    } catch (err) {
      throw err;
    }
  }

  // 💾 CACHE
  if (method === "GET") {
		const cached = getCache(cachePath);
    if (cached) {
      return new Response(JSON.stringify(cached), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }
  }

  // 🔁 EXECUTION
  const dataPromise = retry(async () => {
    let lastError;

    for (const base of API_ENDPOINTS) {
      const url = base + path;

      try {
        const res = await coreFetch(url, options, timeout);
        const bodyText = await res.text();

        // Cache successful JSON responses
        if (isReadOnly && res.headers.get("content-type")?.includes("application/json")) {
          try { setCache(cachePath, JSON.parse(bodyText)); } catch (_) {}
        }

				// Read-only calls should not mutate global circuit breaker state.
				if (!isReadOnly && !exemptWritePath) recordSuccess();
        return { ok: res.ok, status: res.status, bodyText };
      } catch (err) {
        lastError = err;
      }
    }

		if (!isReadOnly && !exemptWritePath && !isTimeoutLikeError(lastError)) {
			recordFailure();
		}
    throw lastError;
  });

  inFlightRequests.set(key, dataPromise);

  try {
    const { status, bodyText } = await dataPromise;
    return new Response(bodyText, { status, headers: { "Content-Type": "application/json" } });
  } finally {
    inFlightRequests.delete(key);
  }
}

// ---------- HEALTH CHECK ----------
function getApiHealth() {
  return {
    circuitOpen: circuitState.open,
    failures: circuitState.failures,
    inFlight: inFlightRequests.size,
    timestamp: new Date().toISOString(),
  };
}

// ---------- TRADING SAFETY ----------
function canExecuteTrade() {
  if (isCircuitOpen()) return false;
  if (circuitState.failures >= 2) return false;
  return true;
}

// ---------- EXPORT ----------
window.apiFetch = apiFetch;
window.apiHealth = getApiHealth;
window.canExecuteTrade = canExecuteTrade;
window.apiResetCircuit = resetCircuitState;
const _storedAdminToken = localStorage.getItem("AQ_ADMIN_TOKEN");
const AQ_ADMIN_TOKEN =
	window.AQ_ADMIN_TOKEN
	|| ((_storedAdminToken && _storedAdminToken !== "dev-admin-token") ? _storedAdminToken : "")
	|| "aq-admin-token-20260329";
const AQ_ADMIN_ROLE = window.AQ_ADMIN_ROLE || localStorage.getItem("AQ_ADMIN_ROLE") || "ADMIN";
const AQ_ADMIN_USER = window.AQ_ADMIN_USER || localStorage.getItem("AQ_ADMIN_USER") || "admin";
const AQ_MICRO_PANEL_STATE_PREFIX = "AQ_MICRO_PANEL_OPEN_";
const AQ_MICRO_PANEL_POS_PREFIX = "AQ_MICRO_PANEL_POS_";
const AQ_OPS_PANEL_STATE_KEY = "AQ_OPS_PANEL_OPEN_V1";
const AQ_OPS_PANEL_POS_KEY = "AQ_OPS_PANEL_POS_V1";
const AQ_JOURNAL_PANEL_STATE_KEY = "AQ_JOURNAL_PANEL_OPEN_V1";
const AQ_JOURNAL_PANEL_POS_KEY = "AQ_JOURNAL_PANEL_POS_V1";
const AQ_GOV_PANEL_STATE_KEY = "AQ_GOV_PANEL_OPEN_V1";
const AQ_GOV_PANEL_LAYOUT_KEY = "AQ_GOV_PANEL_LAYOUT_V1";
const AQ_HEALTH_PANEL_STATE_KEY = "AQ_HEALTH_PANEL_OPEN_V1";
const AQ_HEALTH_PANEL_LAYOUT_KEY = "AQ_HEALTH_PANEL_LAYOUT_V1";

const MICRO_PANEL_CONFIG = {
	iceberg: { panelId: "microIcebergPanel", buttonId: "microIcebergToggleBtn", dragHandleId: "microIcebergDragHandle", label: "Iceberg" },
	orderflow: { panelId: "microOrderflowPanel", buttonId: "microOrderflowToggleBtn", dragHandleId: "microOrderflowDragHandle", label: "Order Flow" },
	summary: { panelId: "microOrderflowSummaryPanel", buttonId: "microSummaryToggleBtn", dragHandleId: "microSummaryDragHandle", label: "OF Summary" },
	timesales: { panelId: "microTimeSalesPanel", buttonId: "microTimeSalesToggleBtn", dragHandleId: "microTimeSalesDragHandle", label: "Time & Sales" },
	ladder: { panelId: "microLadderPanel", buttonId: "microLadderToggleBtn", dragHandleId: "microLadderDragHandle", label: "Ladder" },
};

function setSummaryField(id, value, className) {
	const el = document.getElementById(id);
	if (!el) return;
	el.classList.remove("delta-pos", "delta-neg", "side-buy", "side-sell");
	if (className) el.classList.add(className);
	el.innerText = value;
}

async function refreshOrderflowSummaryPanel() {
	const symbol = typeof selectedSymbol === "function"
		? String(selectedSymbol() || "XAUUSD")
		: String(document.getElementById("chartSymbolInput")?.value || document.getElementById("chartSymbol")?.value || "XAUUSD");
	const timeframe = typeof selectedTimeframe === "function"
		? String(selectedTimeframe() || "1m")
		: "1m";
	try {
		const res = await apiFetch(`/market/orderflow_summary?symbol=${encodeURIComponent(symbol)}&timeframe=${encodeURIComponent(timeframe)}`);
		if (!res.ok) return;
		const payload = await res.json();
		const s = payload?.summary || {};
		const alertLevel = String(s?.alert_level || "LOW").toUpperCase();
		const absorption = String(s?.absorption || "NEUTRAL").toUpperCase();
		const delta = Number(s?.delta || 0);
		const cvd = Number(s?.cumulative_delta || 0);
		setSummaryField("summaryRegime", String(s?.regime_mode || "--"), null);
		setSummaryField("summaryAlert", alertLevel, alertLevel === "HIGH" ? "delta-neg" : (alertLevel === "MEDIUM" ? "side-sell" : "side-buy"));
		setSummaryField("summarySignalStrength", `${Number(s?.signal_strength || 0).toFixed(1)}%`, null);
		setSummaryField("summaryBuyAgg", `${Number(s?.buy_aggression || 0).toFixed(1)}%`, "side-buy");
		setSummaryField("summarySellAgg", `${Number(s?.sell_aggression || 0).toFixed(1)}%`, "side-sell");
		setSummaryField("summaryDelta", `${delta >= 0 ? "+" : ""}${Math.round(delta)}`, delta >= 0 ? "delta-pos" : "delta-neg");
		setSummaryField("summaryCvd", `${cvd >= 0 ? "+" : ""}${Math.round(cvd)}`, cvd >= 0 ? "delta-pos" : "delta-neg");
		setSummaryField("summaryImbalance", String(s?.imbalance || "--"), null);
		setSummaryField("summarySpread", Number(s?.dom_spread || 0).toFixed(2), null);
		setSummaryField("summaryIceberg", `${Math.max(0, Math.round(Number(s?.iceberg_count || 0)))}`, null);
		setSummaryField("summaryAbsorption", absorption, absorption === "BULLISH" ? "side-buy" : (absorption === "BEARISH" ? "side-sell" : null));
		setSummaryField("summaryConfidence", `${Number(s?.confidence || 0).toFixed(1)}%`, null);
		setSummaryField("summaryNarrative", String(s?.narrative || "--"), null);
	} catch (_) {
		// Keep existing values if snapshot refresh fails.
	}
}

function keepPanelInViewport(panel) {
	if (!panel) return;
	const rect = panel.getBoundingClientRect();
	const maxLeft = Math.max(0, window.innerWidth - rect.width);
	const maxTop = Math.max(0, window.innerHeight - rect.height);
	let left = rect.left;
	let top = rect.top;
	if (!Number.isFinite(left) || !Number.isFinite(top)) return;
	left = Math.max(0, Math.min(maxLeft, left));
	top = Math.max(0, Math.min(maxTop, top));
	panel.style.left = `${left}px`;
	panel.style.top = `${top}px`;
	panel.style.right = "auto";
}

function toggleMicroPanel(kind, forceOpen) {
	const cfg = MICRO_PANEL_CONFIG[kind];
	if (!cfg) return;
	const panel = document.getElementById(cfg.panelId);
	const btn = document.getElementById(cfg.buttonId);
	if (!panel) return;
	const shouldOpen = typeof forceOpen === "boolean"
		? forceOpen
		: !panel.classList.contains("open");
	panel.classList.toggle("open", shouldOpen);
	if (shouldOpen) {
		keepPanelInViewport(panel);
		if (kind === "summary") {
			   refreshOrderflowSummaryPanel().catch(console.error);
		}
	}
	if (btn) btn.innerText = shouldOpen ? `Hide ${cfg.label}` : `Open ${cfg.label}`;
	try {
		localStorage.setItem(`${AQ_MICRO_PANEL_STATE_PREFIX}${kind.toUpperCase()}`, shouldOpen ? "1" : "0");
	} catch (_) {
		// ignore storage issues
	}
	return shouldOpen;
}


function restoreMicroPanelStates() {
	for (const kind of Object.keys(MICRO_PANEL_CONFIG)) {
		let open = false;
		try {
			const saved = localStorage.getItem(`${AQ_MICRO_PANEL_STATE_PREFIX}${kind.toUpperCase()}`);
			if (saved === "1") open = true;
		} catch (_) {
			open = false;
		}
		toggleMicroPanel(kind, open);
	}
}

function initMicroPanelDrags() {
	for (const [kind, cfg] of Object.entries(MICRO_PANEL_CONFIG)) {
		const panel = document.getElementById(cfg.panelId);
		const handle = document.getElementById(cfg.dragHandleId);
		if (!panel || !handle) continue;

		try {
			const saved = JSON.parse(localStorage.getItem(`${AQ_MICRO_PANEL_POS_PREFIX}${kind.toUpperCase()}`) || "{}");
			const left = Number(saved?.left);
			const top = Number(saved?.top);
			if (Number.isFinite(left) && Number.isFinite(top)) {
				panel.style.left = `${Math.max(0, left)}px`;
				panel.style.top = `${Math.max(0, top)}px`;
				panel.style.right = "auto";
				keepPanelInViewport(panel);
			}
		} catch (_) {
			// ignore position restore issues
		}

		let dragging = false;
		let offsetX = 0;
		let offsetY = 0;

		handle.addEventListener("mousedown", (ev) => {
			if (ev.button !== 0) return;
			if (ev.target && ev.target.closest("button")) return;
			const rect = panel.getBoundingClientRect();
			dragging = true;
			offsetX = ev.clientX - rect.left;
			offsetY = ev.clientY - rect.top;
			panel.style.right = "auto";
			document.body.style.userSelect = "none";
		});

		const moveHandler = (ev) => {
			if (!dragging) return;
			const panelRect = panel.getBoundingClientRect();
			const maxLeft = Math.max(0, window.innerWidth - panelRect.width);
			const maxTop = Math.max(0, window.innerHeight - panelRect.height);
			const left = Math.max(0, Math.min(maxLeft, ev.clientX - offsetX));
			const top = Math.max(0, Math.min(maxTop, ev.clientY - offsetY));
			panel.style.left = `${left}px`;
			panel.style.top = `${top}px`;
		};

		const upHandler = () => {
			if (!dragging) return;
			dragging = false;
			document.body.style.userSelect = "";
			const rect = panel.getBoundingClientRect();
			try {
				localStorage.setItem(
					`${AQ_MICRO_PANEL_POS_PREFIX}${kind.toUpperCase()}`,
					JSON.stringify({ left: rect.left, top: rect.top }),
				);
			} catch (_) {
				// ignore storage issues
			}
		};

		window.addEventListener("mousemove", moveHandler);
		window.addEventListener("mouseup", upHandler);
	}
	window.addEventListener("resize", () => {
		for (const cfg of Object.values(MICRO_PANEL_CONFIG)) {
			const panel = document.getElementById(cfg.panelId);
			if (panel && panel.classList.contains("open")) {
				keepPanelInViewport(panel);
			}
		}
	});
}

function toggleJournalPanel(forceOpen) {
	const panel = document.getElementById("journalPanel");
	const btn = document.getElementById("journalToggleBtn");
	if (!panel) return;
	const shouldOpen = typeof forceOpen === "boolean"
		? forceOpen
		: !panel.classList.contains("open");
	panel.classList.toggle("open", shouldOpen);
	if (btn) btn.innerText = shouldOpen ? "Hide Journal" : "Open Journal";
	try {
		localStorage.setItem(AQ_JOURNAL_PANEL_STATE_KEY, shouldOpen ? "1" : "0");
	} catch (_) {
		// ignore storage errors
	}
	if (shouldOpen) {
		loadJournal().catch(console.error);
	}
	return shouldOpen;
}

function restoreJournalPanelState() {
	let open = false;
	try {
		const saved = localStorage.getItem(AQ_JOURNAL_PANEL_STATE_KEY);
		if (saved === "1") open = true;
	} catch (_) {
		open = false;
	}
	toggleJournalPanel(open);
}

function initJournalPanelDrag() {
	const panel = document.getElementById("journalPanel");
	const handle = document.getElementById("journalDragHandle");
	if (!panel || !handle) return;

	try {
		const saved = JSON.parse(localStorage.getItem(AQ_JOURNAL_PANEL_POS_KEY) || "{}");
		const left = Number(saved?.left);
		const top = Number(saved?.top);
		if (Number.isFinite(left) && Number.isFinite(top)) {
			panel.style.left = `${Math.max(0, left)}px`;
			panel.style.top = `${Math.max(0, top)}px`;
			panel.style.bottom = "auto";
		}
	} catch (_) {
		// ignore restore issues
	}

	let dragging = false;
	let offsetX = 0;
	let offsetY = 0;

	handle.addEventListener("mousedown", (ev) => {
		if (ev.button !== 0) return;
		if (ev.target && ev.target.closest("button")) return;
		const rect = panel.getBoundingClientRect();
		dragging = true;
		offsetX = ev.clientX - rect.left;
		offsetY = ev.clientY - rect.top;
		panel.style.bottom = "auto";
		document.body.style.userSelect = "none";
	});

	window.addEventListener("mousemove", (ev) => {
		if (!dragging) return;
		const panelRect = panel.getBoundingClientRect();
		const maxLeft = Math.max(0, window.innerWidth - panelRect.width);
		const maxTop = Math.max(0, window.innerHeight - panelRect.height);
		const left = Math.max(0, Math.min(maxLeft, ev.clientX - offsetX));
		const top = Math.max(0, Math.min(maxTop, ev.clientY - offsetY));
		panel.style.left = `${left}px`;
		panel.style.top = `${top}px`;
	});

	window.addEventListener("mouseup", () => {
		if (!dragging) return;
		dragging = false;
		document.body.style.userSelect = "";
		const rect = panel.getBoundingClientRect();
		try {
			localStorage.setItem(AQ_JOURNAL_PANEL_POS_KEY, JSON.stringify({ left: rect.left, top: rect.top }));
		} catch (_) {
			// ignore storage issues
		}
	});
}

function _toggleFloatingPanel(panelId, buttonId, storageKey, label, forceOpen) {
	const panel = document.getElementById(panelId);
	const btn = document.getElementById(buttonId);
	if (!panel) return;
	const shouldOpen = typeof forceOpen === "boolean"
		? forceOpen
		: !panel.classList.contains("open");
	panel.classList.toggle("open", shouldOpen);
	if (btn) btn.innerText = shouldOpen ? `Hide ${label}` : `Open ${label}`;
	try {
		localStorage.setItem(storageKey, shouldOpen ? "1" : "0");
	} catch (_) {
		// ignore storage errors
	}
	return shouldOpen;
}

function toggleGovernancePanel(forceOpen) {
	const opened = _toggleFloatingPanel("governancePanel", "governanceToggleBtn", AQ_GOV_PANEL_STATE_KEY, "Governance", forceOpen);
	if (opened) {
		loadStatus().catch(console.error);
		updateVolatility().catch(console.error);
		updatePropStatus().catch(console.error);
		updateEquityBar().catch(console.error);
		updateDrawdownBar().catch(console.error);
		updateModelStats().catch(console.error);
		updateNewsSeverity().catch(console.error);
		syncPropEngineControls().catch(console.error);
	}
	return opened;
}

function toggleSystemHealthPanel(forceOpen) {
	const opened = _toggleFloatingPanel("systemHealthPanel", "systemHealthToggleBtn", AQ_HEALTH_PANEL_STATE_KEY, "System Health", forceOpen);
	if (opened) {
		updateSystemHealth().catch(console.error);
	}
	return opened;
}

function _restorePanelState(storageKey, toggler) {
	let open = false;
	try {
		const saved = localStorage.getItem(storageKey);
		if (saved === "1") open = true;
	} catch (_) {
		open = false;
	}
	toggler(open);
}

function restoreGovernancePanelState() {
	_restorePanelState(AQ_GOV_PANEL_STATE_KEY, toggleGovernancePanel);
}

function restoreSystemHealthPanelState() {
	_restorePanelState(AQ_HEALTH_PANEL_STATE_KEY, toggleSystemHealthPanel);
}

function _initFloatingPanelDragResize(panelId, handleId, layoutKey, fallback) {
	const panel = document.getElementById(panelId);
	const handle = document.getElementById(handleId);
	if (!panel || !handle) return;

	try {
		const saved = JSON.parse(localStorage.getItem(layoutKey) || "{}");
		const left = Number(saved?.left);
		const top = Number(saved?.top);
		const width = Number(saved?.width);
		const height = Number(saved?.height);
		if (Number.isFinite(left) && Number.isFinite(top)) {
			panel.style.left = `${Math.max(0, left)}px`;
			panel.style.top = `${Math.max(0, top)}px`;
			panel.style.right = "auto";
		}
		if (Number.isFinite(width) && width >= 320) panel.style.width = `${width}px`;
		if (Number.isFinite(height) && height >= 220) panel.style.height = `${height}px`;
	} catch (_) {
		if (fallback?.left) panel.style.left = fallback.left;
		if (fallback?.top) panel.style.top = fallback.top;
		if (fallback?.width) panel.style.width = fallback.width;
	}

	let dragging = false;
	let offsetX = 0;
	let offsetY = 0;

	handle.addEventListener("mousedown", (ev) => {
		if (ev.button !== 0) return;
		if (ev.target && ev.target.closest("button")) return;
		const rect = panel.getBoundingClientRect();
		dragging = true;
		offsetX = ev.clientX - rect.left;
		offsetY = ev.clientY - rect.top;
		panel.style.right = "auto";
		document.body.style.userSelect = "none";
	});

	const saveLayout = () => {
		const rect = panel.getBoundingClientRect();
		try {
			localStorage.setItem(layoutKey, JSON.stringify({
				left: rect.left,
				top: rect.top,
				width: rect.width,
				height: rect.height,
			}));
		} catch (_) {
			// ignore storage issues
		}
	};

	window.addEventListener("mousemove", (ev) => {
		if (!dragging) return;
		const rect = panel.getBoundingClientRect();
		const maxLeft = Math.max(0, window.innerWidth - rect.width);
		const maxTop = Math.max(0, window.innerHeight - rect.height);
		const left = Math.max(0, Math.min(maxLeft, ev.clientX - offsetX));
		const top = Math.max(0, Math.min(maxTop, ev.clientY - offsetY));
		panel.style.left = `${left}px`;
		panel.style.top = `${top}px`;
	});

	window.addEventListener("mouseup", () => {
		if (!dragging) return;
		dragging = false;
		document.body.style.userSelect = "";
		saveLayout();
	});

	panel.addEventListener("mouseup", saveLayout);
}

function initGovernancePanelInteractions() {
	_initFloatingPanelDragResize("governancePanel", "governanceDragHandle", AQ_GOV_PANEL_LAYOUT_KEY, {
		left: "14px",
		top: "86px",
		width: "470px",
	});
}

function initSystemHealthPanelInteractions() {
	_initFloatingPanelDragResize("systemHealthPanel", "systemHealthDragHandle", AQ_HEALTH_PANEL_LAYOUT_KEY, {
		left: "500px",
		top: "86px",
		width: "470px",
	});
}

function resetFloatingPanelLayout() {
	try {
		localStorage.removeItem(AQ_GOV_PANEL_STATE_KEY);
		localStorage.removeItem(AQ_GOV_PANEL_LAYOUT_KEY);
		localStorage.removeItem(AQ_HEALTH_PANEL_STATE_KEY);
		localStorage.removeItem(AQ_HEALTH_PANEL_LAYOUT_KEY);
		localStorage.removeItem(AQ_OPS_PANEL_POS_KEY);
		localStorage.removeItem(AQ_OPS_PANEL_STATE_KEY);
		localStorage.removeItem(AQ_JOURNAL_PANEL_POS_KEY);
		localStorage.removeItem(AQ_JOURNAL_PANEL_STATE_KEY);
		for (const kind of Object.keys(MICRO_PANEL_CONFIG)) {
			localStorage.removeItem(`${AQ_MICRO_PANEL_POS_PREFIX}${kind.toUpperCase()}`);
			localStorage.removeItem(`${AQ_MICRO_PANEL_STATE_PREFIX}${kind.toUpperCase()}`);
		}
	} catch (_) {
		// ignore storage issues
	}

	const opsPanel = document.getElementById("operationsConsolePanel");
	if (opsPanel) {
		opsPanel.style.left = "";
		opsPanel.style.top = "";
		opsPanel.style.right = "14px";
	}

	const journalPanel = document.getElementById("journalPanel");
	if (journalPanel) {
		journalPanel.style.left = "14px";
		journalPanel.style.bottom = "14px";
		journalPanel.style.top = "";
		journalPanel.style.right = "";
	}

	const governancePanel = document.getElementById("governancePanel");
	if (governancePanel) {
		governancePanel.style.left = "14px";
		governancePanel.style.top = "86px";
		governancePanel.style.right = "auto";
		governancePanel.style.width = "min(470px, calc(100vw - 28px))";
		governancePanel.style.height = "";
	}

	const healthPanel = document.getElementById("systemHealthPanel");
	if (healthPanel) {
		healthPanel.style.left = "500px";
		healthPanel.style.top = "86px";
		healthPanel.style.right = "auto";
		healthPanel.style.width = "min(470px, calc(100vw - 28px))";
		healthPanel.style.height = "";
	}

	const defaults = {
		iceberg: { right: "14px", top: "86px" },
		orderflow: { right: "14px", top: "calc(86px + 38vh)" },
		timesales: { right: "460px", top: "86px" },
		ladder: { right: "460px", top: "calc(86px + 38vh)" },
	};

	for (const [kind, cfg] of Object.entries(MICRO_PANEL_CONFIG)) {
		const panel = document.getElementById(cfg.panelId);
		if (!panel) continue;
		panel.style.left = "";
		panel.style.top = defaults[kind]?.top || "";
		panel.style.right = defaults[kind]?.right || "";
		toggleMicroPanel(kind, true);
	}

	toggleOperationsConsole(false);
	toggleJournalPanel(false);
	toggleGovernancePanel(false);
	toggleSystemHealthPanel(false);
}

window.toggleMicroPanel = toggleMicroPanel;
window.resetFloatingPanelLayout = resetFloatingPanelLayout;
window.toggleJournalPanel = toggleJournalPanel;
window.toggleGovernancePanel = toggleGovernancePanel;
window.toggleSystemHealthPanel = toggleSystemHealthPanel;

function toggleOperationsConsole(forceOpen) {
	const panel = document.getElementById("operationsConsolePanel");
	const btn = document.getElementById("opsConsoleToggleBtn");
	if (!panel) return;
	const shouldOpen = typeof forceOpen === "boolean"
		? forceOpen
		: !panel.classList.contains("open");
	panel.classList.toggle("open", shouldOpen);
	if (btn) btn.innerText = shouldOpen ? "Hide Operations" : "Open Operations";
	try {
		localStorage.setItem(AQ_OPS_PANEL_STATE_KEY, shouldOpen ? "1" : "0");
	} catch (_) {
		// ignore storage errors
	}
	if (shouldOpen) {
		updateBasisOps().catch(console.error);
		updateOpsStatus().catch(console.error);
		updateMultiSymbolDashboard().catch(console.error);
		// Run lightweight probe on open; deep probe remains manual via button.
		runFeedProbe(false).catch(console.error);
	}
	return shouldOpen;
}

function restoreOperationsConsoleState() {
	let open = false;
	try {
		const saved = localStorage.getItem(AQ_OPS_PANEL_STATE_KEY);
		if (saved === "1") open = true;
	} catch (_) {
		open = false;
	}
	toggleOperationsConsole(open);
}

function initOperationsConsoleDrag() {
	const panel = document.getElementById("operationsConsolePanel");
	const handle = document.getElementById("opsConsoleDragHandle");
	if (!panel || !handle) return;

	try {
		const saved = JSON.parse(localStorage.getItem(AQ_OPS_PANEL_POS_KEY) || "{}");
		const left = Number(saved?.left);
		const top = Number(saved?.top);
		if (Number.isFinite(left) && Number.isFinite(top)) {
			panel.style.left = `${Math.max(0, left)}px`;
			panel.style.top = `${Math.max(0, top)}px`;
			panel.style.right = "auto";
		}
	} catch (_) {
		// ignore position restore issues
	}

	let dragging = false;
	let offsetX = 0;
	let offsetY = 0;

	handle.addEventListener("mousedown", (ev) => {
		if (ev.button !== 0) return;
		if (ev.target && ev.target.closest("button")) return;
		const rect = panel.getBoundingClientRect();
		dragging = true;
		offsetX = ev.clientX - rect.left;
		offsetY = ev.clientY - rect.top;
		panel.style.right = "auto";
		document.body.style.userSelect = "none";
	});

	window.addEventListener("mousemove", (ev) => {
		if (!dragging) return;
		const panelRect = panel.getBoundingClientRect();
		const maxLeft = Math.max(0, window.innerWidth - panelRect.width);
		const maxTop = Math.max(0, window.innerHeight - panelRect.height);
		const left = Math.max(0, Math.min(maxLeft, ev.clientX - offsetX));
		const top = Math.max(0, Math.min(maxTop, ev.clientY - offsetY));
		panel.style.left = `${left}px`;
		panel.style.top = `${top}px`;
	});

	window.addEventListener("mouseup", () => {
		if (!dragging) return;
		dragging = false;
		document.body.style.userSelect = "";
		const rect = panel.getBoundingClientRect();
		try {
			localStorage.setItem(AQ_OPS_PANEL_POS_KEY, JSON.stringify({ left: rect.left, top: rect.top }));
		} catch (_) {
			// ignore storage errors
		}
	});
}

window.toggleOperationsConsole = toggleOperationsConsole;

function adminHeaders(extra = {}) {
	return {
		"Content-Type": "application/json",
		"x-admin-token": AQ_ADMIN_TOKEN,
		"x-admin-role": AQ_ADMIN_ROLE,
		"x-admin-user": AQ_ADMIN_USER,
		...extra,
	};
}

async function loadStatus() {

	const res = await apiFetch("/status");
	const data = await res.clone().json();

	document.getElementById("balance").innerText = data.balance;
	document.getElementById("phase").innerText = data.phase;
	const dailyLoss = document.getElementById("dailyLoss");
	if (dailyLoss) dailyLoss.innerText = Number(data.daily_loss || 0).toFixed(2);

	const newsStatus = document.getElementById("news-status");
	if (newsStatus) {
		if (data.news_halt) {
			newsStatus.innerText = "HIGH IMPACT NEWS — TRADING HALTED";
		} else {
			newsStatus.innerText = "News: Normal";
		}
	}

	renderNews(data.next_news || []);
}

async function updatePropStatus() {
	const res = await apiFetch("/prop_status");
	if (!res.ok) return;
	const data = await res.clone().json();

	const phaseDisplay = document.getElementById("phaseDisplay");
	const floorDisplay = document.getElementById("floorDisplay");
	const profitDays = document.getElementById("profitDays");
	const tradeStatus = document.getElementById("tradeStatus");
	const phaseCompletion = document.getElementById("phaseCompletion");

	if (phaseDisplay) phaseDisplay.innerText = data.phase;
	if (floorDisplay) floorDisplay.innerText = data.static_floor;
	if (profitDays) profitDays.innerText = data.profitable_days;
	if (tradeStatus) tradeStatus.innerText = data.trading_enabled ? "ACTIVE" : "DISABLED";
	if (phaseCompletion) phaseCompletion.innerText = data.phase_completion_status || "IN_PROGRESS";
	setText("accountModeDisplay", data.profile_mode || "STANDARD");
	setText("dailyMaxLossDisplay", fmtMoney(data.daily_max_loss));
	setText("totalMaxLossDisplay", fmtMoney(data.total_max_loss));
	setText("phase1TargetDisplay", fmtMoney(data.phase1_target));
	setText("phase2TargetDisplay", fmtMoney(data.phase2_target));
	setText("riskPerTradeDisplay", data.risk_per_trade_pct != null ? `${Number(data.risk_per_trade_pct).toFixed(2)}%` : "--");
	setText("activeAccountsDisplay", Array.isArray(data.active_accounts) && data.active_accounts.length ? data.active_accounts.join(", ") : "--");
}

async function updateEquityBar() {
	const res = await apiFetch("/equity");
	if (!res.ok) {
		setText("accountSizeDisplay", "--");
		const bar = document.getElementById("equityBar");
		if (bar) bar.style.width = "0%";
		const label = document.getElementById("equityLabel");
		if (label) label.innerText = "Equity data unavailable";
		return;
	}
	const data = await res.clone().json();

	const base = Number(data.base || 50000);
	const target = Number(data.target || base);
	const equity = Number(data.equity || base);
	const primaryAccount = String(data.primary_account || "").toUpperCase();
	setText("accountSizeDisplay", primaryAccount || (base > 0 ? `${Math.round(base / 1000)}K` : "--"));

	const denominator = Math.max(1, target - base);
	let progress = ((equity - base) / denominator) * 100;
	progress = Math.max(0, Math.min(100, progress));

	const bar = document.getElementById("equityBar");
	if (bar) bar.style.width = progress + "%";

	const label = document.getElementById("equityLabel");
	if (label) label.innerText = `Equity ${equity.toFixed(2)} / Target ${target.toFixed(2)} (${progress.toFixed(1)}%)`;
}

async function updateDrawdownBar() {
	const [equityRes, propRes] = await Promise.all([
		apiFetch("/equity"),
		apiFetch("/prop_status"),
	]);
	if (!equityRes.ok || !propRes.ok) {
		const bar = document.getElementById("drawdownBar");
		if (bar) bar.style.width = "0%";
		const label = document.getElementById("drawdownLabel");
		if (label) label.innerText = "Drawdown data unavailable";
		return;
	}

	const equityData = await equityRes.clone().json();
	const propData = await propRes.clone().json();

	const equity = Number(equityData.equity || 0);
	const floor = Number(propData.static_floor || 0);
	const base = Number(equityData.base || 50000);

	const riskRange = Math.max(1, base - floor);
	const drawdownUsed = Math.max(0, base - equity);
	let pct = (drawdownUsed / riskRange) * 100;
	pct = Math.max(0, Math.min(100, pct));

	const bar = document.getElementById("drawdownBar");
	if (bar) {
		bar.style.width = pct + "%";
		bar.className = "bar drawdown" + (equity <= floor ? " red" : "");
	}

	const label = document.getElementById("drawdownLabel");
	if (label) label.innerText = `Drawdown used: ${drawdownUsed.toFixed(2)} / ${(base - floor).toFixed(2)} (${pct.toFixed(1)}%)`;
}

async function updateModelStats() {
	const symbol = selectedChartSymbol();
	const res = await apiFetch(`/model_stats?symbol=${encodeURIComponent(symbol)}`);
	const body = document.getElementById("modelStatsBody");
	if (!body) return;
	if (!res.ok) {
		body.innerHTML = "";
		const tr = document.createElement("tr");
		tr.innerHTML = `<td colspan="4">Model stats endpoint unavailable (${res.status})</td>`;
		body.appendChild(tr);
		return;
	}
	const data = await res.json();
	body.innerHTML = "";

	const entries = Object.entries(data || {});
	if (!entries.length) {
		const tr = document.createElement("tr");
		tr.innerHTML = `<td colspan="4">No symbol-specific model data for ${symbol}</td>`;
		body.appendChild(tr);
		return;
	}

	entries.forEach(([model, stats]) => {
		const wins = Number(stats.wins || 0);
		const losses = Number(stats.losses || 0);
		const total = wins + losses;
		const wr = total > 0 ? (wins / total) * 100 : 0;

		const tr = document.createElement("tr");
		tr.innerHTML = `<td>${model}</td><td>${wins}</td><td>${losses}</td><td>${wr.toFixed(1)}%</td>`;
		body.appendChild(tr);
	});
}

async function updateNewsSeverity() {
	const panel = document.getElementById("newsPanel");
	if (!panel) return;

	let data = null;
	try {
		const res = await apiFetch("/news_severity");
		if (res.ok) data = await res.json();
	} catch (_) {
		data = null;
	}

	if (!data) {
		try {
			const statusRes = await apiFetch("/status");
			if (statusRes.ok) {
				const status = await statusRes.json();
				const next = Array.isArray(status?.next_news) ? status.next_news[0] : null;
				data = {
					halt_active: Boolean(status?.news_halt),
					upcoming_title: next?.title || null,
					upcoming_currency: next?.currency || null,
					minutes_to_news: next?.time ? Math.max(0, Math.round((new Date(next.time).getTime() - Date.now()) / 60000)) : null,
				};
			}
		} catch (_) {
			data = null;
		}
	}

	if (!data) {
		panel.innerText = "News severity unavailable";
		return;
	}

	const halt = data.halt_active ? "HALT ACTIVE" : "No Halt";
	const upcoming = data.upcoming_title ? `${data.upcoming_title} (${data.upcoming_currency || "--"})` : "No upcoming event";
	const countdown = data.minutes_to_news != null ? `${data.minutes_to_news} min` : "--";

	panel.innerText = `${halt} | Next: ${upcoming} | T-${countdown}`;
}

function healthClass(ok) {
	return ok ? "health-ok" : "health-bad";
}

async function updateSystemHealth() {
	const res = await apiFetch("/system_health");
	if (!res.ok) return;
	const data = await res.json();
	const legacyShape = Boolean(data?.System || data?.Broker || data?.DataFeed);
	const normalized = legacyShape
		? {
			health_state: String(data?.System?.status || "UNKNOWN").toUpperCase() === "ERROR" ? "CRITICAL" : "HEALTHY",
			health_score: null,
			playwright: String(data?.Broker?.status || "").toUpperCase() === "CONNECTED",
			databento: String(data?.DataFeed?.status || "").toUpperCase() === "OK",
			governance: true,
			execution_status: String(data?.Broker?.status || "UNKNOWN").toUpperCase() === "CONNECTED" ? "CONNECTED" : "DISCONNECTED",
			reconciliation_status: "UNKNOWN",
			equity_verification_status: "UNKNOWN",
			cpu_load_1m: null,
			cpu_cores: null,
			memory_used_pct: null,
			disk_used_pct: null,
			uptime_seconds: null,
			issues: [data?.Broker?.details, data?.System?.details].filter(Boolean),
		}
		: (data || {});

	const p = document.getElementById("healthPlaywright");
	const d = document.getElementById("healthDatabento");
	const g = document.getElementById("healthGovernance");
	const e = document.getElementById("healthExecution");
	const r = document.getElementById("healthReconciliation");
	const eq = document.getElementById("healthEquityVerify");
	const cpu = document.getElementById("healthCpuLoad");
	const mem = document.getElementById("healthMemory");
	const disk = document.getElementById("healthDisk");
	const uptime = document.getElementById("healthUptime");
	const issues = document.getElementById("healthIssues");
	const summary = document.getElementById("healthSummary");

	const toTone = (ok) => ok ? "good" : "bad";
	const execOk = String(normalized.execution_status || "OK").toUpperCase() !== "HALTED";
	const recOk = !Boolean(normalized.reconciliation_halt);
	const equityOk = !Boolean(normalized.equity_verification_halt);
	const memPct = Number(normalized.memory_used_pct);
	const diskPct = Number(normalized.disk_used_pct);
	const cpuLoad = Number(normalized.cpu_load_1m);
	const cpuCores = Number(normalized.cpu_cores || 0);

	if (summary) {
		const state = String(normalized.health_state || "UNKNOWN").toUpperCase();
		const score = Number(normalized.health_score);
		const text = Number.isFinite(score) ? `${state} (${score})` : state;
		setOpsValue("healthSummary", text, state === "HEALTHY" ? "good" : state === "DEGRADED" ? "warn" : "bad");
	}

	if (p) {
		setOpsValue("healthPlaywright", normalized.playwright ? "OK" : "DOWN", toTone(Boolean(normalized.playwright)));
	}
	if (d) {
		setOpsValue("healthDatabento", normalized.databento ? "OK" : "DOWN", toTone(Boolean(normalized.databento)));
	}
	if (g) {
		setOpsValue("healthGovernance", normalized.governance ? "OK" : "LOCKED", normalized.governance ? "good" : "warn");
	}
	if (e) {
		setOpsValue("healthExecution", execOk ? "OK" : "HALTED", execOk ? "good" : "bad");
	}
	if (r) {
		setOpsValue("healthReconciliation", recOk ? (normalized.reconciliation_status || "OK") : "HALTED", recOk ? "good" : "bad");
	}
	if (eq) {
		setOpsValue("healthEquityVerify", equityOk ? (normalized.equity_verification_status || "OK") : "HALTED", equityOk ? "good" : "bad");
	}
	if (cpu) {
		const text = Number.isFinite(cpuLoad)
			? `${cpuLoad.toFixed(2)}${cpuCores > 0 ? ` / ${cpuCores}c` : ""}`
			: "--";
		const ratio = (Number.isFinite(cpuLoad) && cpuCores > 0) ? (cpuLoad / cpuCores) : null;
		const tone = ratio == null ? "neutral" : ratio > 1.2 ? "bad" : ratio > 0.85 ? "warn" : "good";
		setOpsValue("healthCpuLoad", text, tone);
	}
	if (mem) {
		const text = Number.isFinite(memPct) ? `${memPct.toFixed(1)}%` : "--";
		const tone = Number.isFinite(memPct) ? (memPct >= 90 ? "bad" : memPct >= 80 ? "warn" : "good") : "neutral";
		setOpsValue("healthMemory", text, tone);
	}
	if (disk) {
		const text = Number.isFinite(diskPct) ? `${diskPct.toFixed(1)}%` : "--";
		const tone = Number.isFinite(diskPct) ? (diskPct >= 90 ? "bad" : diskPct >= 80 ? "warn" : "good") : "neutral";
		setOpsValue("healthDisk", text, tone);
	}
	if (uptime) {
		const sec = Number(normalized.uptime_seconds);
		if (Number.isFinite(sec)) {
			const h = Math.floor(sec / 3600);
			const m = Math.floor((sec % 3600) / 60);
			setOpsValue("healthUptime", `${h}h ${m}m`, "neutral");
		} else {
			setOpsValue("healthUptime", "--", "neutral");
		}
	}
	if (issues) {
		const items = Array.isArray(normalized.issues) ? normalized.issues : [];
		if (!items.length) {
			setOpsValue("healthIssues", "None", "good");
		} else {
			setOpsChips("healthIssues", items.join("|"));
		}
	}
}

async function loadJournal() {
	const symbol = selectedChartSymbol();
	const res = await apiFetch(`/journal?symbol=${encodeURIComponent(symbol)}`);
	const tbody = document.querySelector("#journalTable tbody");
	if (!tbody) return;
	tbody.innerHTML = "";
	if (!res.ok) {
		const tr = document.createElement("tr");
		tr.innerHTML = `<td colspan="7">Journal endpoint unavailable (${res.status})</td>`;
		tbody.appendChild(tr);
		return;
	}
	const data = await res.json();

	if (!Array.isArray(data) || data.length === 0) {
		const tr = document.createElement("tr");
		tr.innerHTML = `<td colspan="7">No symbol-specific journal rows for ${symbol}</td>`;
		tbody.appendChild(tr);
		return;
	}

	data.forEach(row => {
		const tr = document.createElement("tr");
		row.forEach(col => {
			const td = document.createElement("td");
			td.innerText = col;
			tr.appendChild(td);
		});
		tbody.appendChild(tr);
	});
}

async function updateVolatility() {
	try {
		const res = await apiFetch("/volatility_status");
		if (!res.ok) return;
		const data = await res.json();

		const bar = document.getElementById("volatilityBar");
		if (!bar) return;

		const mode = (data.mode || "NORMAL").toUpperCase();
		bar.className = "vol-bar " + mode;
		bar.innerText = "VOL: " + mode;
	} catch (_) {
		// keep last shown state on transient API errors
	}
}

function renderNews(news) {
	const container = document.getElementById("news-list");
	if (!container) return;

	container.innerHTML = "";

	news.forEach(e => {
		const div = document.createElement("div");
		div.innerHTML = `
			<strong>${e.currency}</strong> - ${e.title}
			<br/>
			${new Date(e.time).toLocaleString()}
			<hr/>
		`;
		container.appendChild(div);
	});
}

function selectedChartSymbol() {
	const input = document.getElementById("chartSymbolInput");
	if (input && input.value) return input.value;
	const select = document.getElementById("chartSymbol");
	return select && select.value ? select.value : "GC.FUT";
}

function setText(id, value) {
	const el = document.getElementById(id);
	if (el) el.innerText = value;
}

function fmtMoney(value) {
	const n = Number(value);
	if (!Number.isFinite(n)) return "--";
	return n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function fmtPct(value) {
	const n = Number(value);
	if (!Number.isFinite(n)) return "--";
	return `${n.toFixed(2)}%`;
}

function fmtPrice(value, digits = 2) {
	const n = Number(value);
	if (!Number.isFinite(n)) return "--";
	return n.toLocaleString(undefined, { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

function setOpsValue(id, value, tone = "neutral") {
	const el = document.getElementById(id);
	if (!el) return;
	el.innerText = value ?? "--";
	el.classList.remove("ops-good", "ops-warn", "ops-bad", "ops-neutral");
	const cls = tone === "good" ? "ops-good"
		: tone === "warn" ? "ops-warn"
		: tone === "bad" ? "ops-bad"
		: "ops-neutral";
	el.classList.add(cls);
}

function setOpsChips(id, raw, defaultTone = "neutral") {
	const el = document.getElementById(id);
	if (!el) return;
	const text = String(raw ?? "").trim();
	if (!text || text === "--" || text === "NONE") {
		setOpsValue(id, text || "--", defaultTone);
		return;
	}
	const tokens = text
		.split(/\s*\|\s*|\s*,\s*/)
		.map(t => String(t || "").trim())
		.filter(Boolean)
		.slice(0, 8);
	if (!tokens.length) {
		setOpsValue(id, "--", defaultTone);
		return;
	}
	el.classList.remove("ops-good", "ops-warn", "ops-bad", "ops-neutral");
	const classForToken = (token) => {
		const t = token.toUpperCase();
		if (t.includes("HALT") || t.includes("BLOCK") || t.includes("ERROR") || t.includes("FAIL") || t.includes("LOCK")) return "bad";
		if (t.includes("WARN") || t.includes("DEFENSIVE") || t.includes("COOLDOWN") || t.includes("LIMIT")) return "warn";
		if (t.includes("OK") || t.includes("ACTIVE") || t.includes("CALIBRATED") || t.includes("LIVE") || t.includes("ICT") || t.includes("ICEBERG") || t.includes("GANN") || t.includes("ASTRO")) return "good";
		return "";
	};
	el.innerHTML = `<span class="ops-chip-wrap">${tokens.map(token => {
		const tone = classForToken(token);
		return `<span class="ops-chip${tone ? ` ${tone}` : ""}">${token}</span>`;
	}).join("")}</span>`;
}

async function updateMultiSymbolDashboard() {
	const res = await apiFetch("/dashboard/multi_symbol");
	const tbody = document.getElementById("multiSymbolBody");
	if (!res.ok) {
		setText("msFeedHealth", "DOWN");
		setText("msRowCount", "0");
		setText("msUpdated", "--");
		setText("msExecHalted", "--");
		if (tbody) {
			tbody.innerHTML = "";
			const tr = document.createElement("tr");
			tr.innerHTML = `<td colspan="15">Multi-symbol endpoint unavailable (${res.status})</td>`;
			tbody.appendChild(tr);
		}
		return;
	}
	const data = await res.json();

	const rows = Array.isArray(data?.rows) ? data.rows : [];
	const feed = data?.feed || {};

	setText("msFeedHealth", feed?.healthy ? "OK" : "DOWN");
	setText("msRowCount", rows.length);
	setText("msUpdated", data?.timestamp ? new Date(data.timestamp).toLocaleTimeString() : "--");
	setText("msExecHalted", rows.some(r => r?.execution_halted) ? "YES" : "NO");

	if (!tbody) return;
	tbody.innerHTML = "";

	for (const row of rows) {
		const market = row.market || {};
		const model = row.model || {};
		const risk = row.risk || {};
		const basis = row.basis || {};
		const resolver = row.resolver || {};

		const tr = document.createElement("tr");
		tr.style.cursor = "pointer";
		   tr.innerHTML = `
			   <td>${row.symbol || "--"}</td>
			   <td>${market.htf_bias || "--"}</td>
			   <td>${market.ltf_structure || "--"}</td>
			   <td>${model.active_model || "--"}</td>
			   <td>${model.confidence != null ? Number(model.confidence).toFixed(2) : "--"}</td>
			   <td>${risk.risk_percent != null ? Number(risk.risk_percent).toFixed(2) : "--"}</td>
			   <td>${risk.phase || "--"}</td>
			   <td>${(row.prop_behavior || {}).mode || "--"}</td>
			   <td>${basis.status || "--"}</td>
			   <td>${resolver.status || "--"}</td>
			   <td>${resolver.watch_only ? "YES" : "NO"}</td>
			   <td>${market.news_state || "--"}</td>
			   <td>${row.broker_price != null ? fmtPrice(row.broker_price, 2) : "--"}</td>
			   <td>${row.system_price != null ? fmtPrice(row.system_price, 2) : "--"}</td>
			   <td>${row.offset_diff != null ? fmtPrice(row.offset_diff, 2) : "--"}</td>
		   `;

		tr.addEventListener("click", () => {
			const symbolEl = document.getElementById("chartSymbolInput") || document.getElementById("chartSymbol");
			if (!symbolEl) return;
			const canonicalToFeed = {
				XAUUSD: "GC.FUT",
				NQ: "NQ.FUT",
				EURUSD: "6E.FUT",
				US30: "YM.FUT",
			};
			const feedSymbol = canonicalToFeed[row.symbol] || row.symbol;
			symbolEl.value = feedSymbol;
			symbolEl.dispatchEvent(new Event("input", { bubbles: true }));
			symbolEl.dispatchEvent(new Event("change", { bubbles: true }));
		});

		tbody.appendChild(tr);
	}
}

async function updateBasisOps(forceRefresh = false) {
	const symbol = selectedChartSymbol();
	setText("basisSymbol", symbol);

	const [basisRes, contractsRes, contextRes] = await Promise.all([
		apiFetch(`/market/basis?symbol=${encodeURIComponent(symbol)}&refresh=${forceRefresh ? "true" : "false"}`),
		apiFetch(`/market/contracts?symbol=${encodeURIComponent(symbol)}`),
		apiFetch(`/market/context?symbol=${encodeURIComponent(symbol)}`),
	]);

	if (!basisRes.ok || !contractsRes.ok || !contextRes.ok) {
		// Compatibility fallback for runtimes that only expose offset_quality + symbol_registry.
		const [offsetRes, registryRes] = await Promise.all([
			apiFetch(`/market/offset_quality?symbol=${encodeURIComponent(symbol)}`),
			apiFetch("/status/symbol_registry"),
		]);
		if (!offsetRes.ok || !registryRes.ok) return;
		const offset = await offsetRes.json();
		const registry = await registryRes.json();
		const rows = Array.isArray(registry?.symbols) ? registry.symbols : [];
		const row = rows.find((item) => String(item?.symbol || "").toUpperCase() === String(symbol || "").toUpperCase()) || null;
		const resolver = row?.resolver || {};

		setText("basisStatus", offset?.basis?.status || "--");
		setText("basisBps", "--");
		setText("basisZ", "--");
		setText("basisGuard", offset?.basis?.safety_block ? "BLOCKED" : "OK");
		setText("basisPolicyBlock", offset?.basis_policy?.hard_block ? "YES" : "NO");
		setText("basisPolicyRisk", offset?.basis_policy?.risk_modifier != null ? Number(offset.basis_policy.risk_modifier).toFixed(2) : "--");
		setOpsChips(
			"basisPolicyReasons",
			Array.isArray(offset?.basis_policy?.reasons) && offset.basis_policy.reasons.length
				? offset.basis_policy.reasons.join(" | ")
				: "--",
		);

		setText("resolverActive", resolver?.active_symbol || row?.active_symbol || offset?.sources?.futures_source || "--");
		setText("resolverStatus", resolver?.last_status || row?.last_status || offset?.basis_policy?.resolver_status || "--");
		setText("resolverFailures", resolver?.consecutive_failures != null ? String(resolver.consecutive_failures) : "--");
		setText("resolverAttempts", resolver?.attempts != null ? String(resolver.attempts) : "--");
		setText("resolverTtl", resolver?.ttl_seconds != null ? `${resolver.ttl_seconds}s` : "--");
		setText("resolverWatchOnly", row?.enabled === false ? "YES" : "NO");
		setText("resolverWatchReason", row?.disable_reason || resolver?.disable_reason || "--");
		return;
	}

	const basis = await basisRes.json();
	const contracts = await contractsRes.json();
	const context = await contextRes.json();
	const resolver = contracts?.resolver || {};
	const policy = context?.basis_policy || {};
	const watch = context?.resolver_watch || {};

	setText("basisStatus", basis?.status || "--");
	setText("basisBps", basis?.smooth_bps != null ? Number(basis.smooth_bps).toFixed(2) : "--");
	setText("basisZ", basis?.zscore != null ? Number(basis.zscore).toFixed(2) : "--");
	setText("basisGuard", basis?.safety_block ? (basis?.guard_reason || "BLOCKED") : "OK");
	setText("basisPolicyBlock", policy?.hard_block ? "YES" : "NO");
	setText("basisPolicyRisk", policy?.risk_modifier != null ? Number(policy.risk_modifier).toFixed(2) : "--");
	setOpsChips("basisPolicyReasons", Array.isArray(policy?.reasons) && policy.reasons.length ? policy.reasons.join(" | ") : "--");

	setText("resolverActive", resolver?.active_symbol || "--");
	setText("resolverStatus", resolver?.last_status || "--");
	setText("resolverFailures", resolver?.consecutive_failures != null ? String(resolver.consecutive_failures) : "--");
	setText("resolverAttempts", resolver?.attempts != null ? String(resolver.attempts) : "--");
	setText("resolverTtl", resolver?.ttl_seconds != null ? `${resolver.ttl_seconds}s` : "--");
	setText("resolverWatchOnly", watch?.watch_only ? "YES" : "NO");
	setText("resolverWatchReason", watch?.reason || "--");
}

async function warmupContracts() {
	const btn = document.getElementById("basisWarmupBtn");
	if (btn) {
		btn.disabled = true;
		btn.innerText = "Warming...";
	}
	try {
		await apiFetch("/market/contracts/warmup?force_refresh=true&max_candidates=1&max_probe_seconds=0.8", {
			method: "POST",
		});
		await updateBasisOps();
	} finally {
		if (btn) {
			btn.disabled = false;
			btn.innerText = "Warmup Contracts";
		}
	}
}

async function prewarmSymbolRegistry() {
	const btn = document.getElementById("opsRegistryPrewarmBtn");
	if (btn) {
		btn.disabled = true;
		btn.innerText = "Prewarming...";
	}
	setText("opsProbeSnapshot", "Triggering symbol registry prewarm...");
	try {
		const res = await apiFetch("/status/symbol_registry/prewarm", { method: "POST" });
		if (res.ok) {
			const data = await res.json();
			const symbols = Object.keys(data?.resolver || {});
			const summary = data?.summary || {};
			const resolved = Number(summary?.resolved);
			const unresolved = Number(summary?.unresolved);
			if (Number.isFinite(resolved) && Number.isFinite(unresolved)) {
				setText("opsProbeSnapshot", `Prewarm OK: resolved ${resolved}, unresolved ${unresolved}`);
			} else {
				setText("opsProbeSnapshot", symbols.length ? `Prewarm OK: ${symbols.join(", ")}` : "Prewarm requested");
			}
		} else {
			setText("opsProbeSnapshot", `Prewarm failed (${res.status})`);
		}
	} catch (_) {
		setText("opsProbeSnapshot", "Prewarm request failed");
	} finally {
		if (btn) {
			btn.disabled = false;
			btn.innerText = "Prewarm Registry";
		}
		await updateOpsStatus();
	}
}

function canonicalRuntimeSymbolForOps(symbol) {
	const key = String(symbol || "").toUpperCase();
	const map = {
		"GC": "XAUUSD",
		"GC.FUT": "XAUUSD",
		"NQ.FUT": "NQ",
		"6E": "EURUSD",
		"6E.FUT": "EURUSD",
		"YM": "US30",
		"YM.FUT": "US30",
	};
	return map[key] || key || "XAUUSD";
}

let _brokerAutoConnectInFlight = false;
let _brokerAutoConnectLastAttemptAt = 0;
let _brokerAutoConnectLastEscalationAt = 0;
let _brokerAutoConnectLastResult = null; // { ts: Date, success: boolean, state: string }

async function ensureBrokerFeedAutoConnect(opts = {}) {
	const symbol = canonicalRuntimeSymbolForOps(opts?.symbol || selectedChartSymbol() || "XAUUSD");
	let runtimeRegistered = false;
	try {
		const registerRes = await apiFetch(
			`/status/symbol_registry/${encodeURIComponent(symbol)}/register`,
			{ method: "POST" },
			8000,
		);
		runtimeRegistered = registerRes.ok;
	} catch (_) {
		runtimeRegistered = false;
	}
	if (symbol !== "XAUUSD") return runtimeRegistered;

	const forceReconnect = Boolean(opts?.forceReconnect);
	const minIntervalMs = Number.isFinite(Number(opts?.minIntervalMs)) ? Number(opts.minIntervalMs) : 15000;
	const now = Date.now();
	if (!forceReconnect && (now - _brokerAutoConnectLastAttemptAt) < Math.max(0, minIntervalMs)) return false;
	if (_brokerAutoConnectInFlight) return false;

	_brokerAutoConnectInFlight = true;
	_brokerAutoConnectLastAttemptAt = now;
	try {
		let bridgeReady = false;
		let debuggerReachable = false;
		let brokerTabs = 0;
		try {
			const bridgeRes = await apiFetch("/status/broker_bridge", {}, 8000);
			if (bridgeRes.ok) {
				const bridge = await bridgeRes.json();
				bridgeReady = Boolean(bridge?.bridge_ready);
				debuggerReachable = Boolean(bridge?.debugger_reachable);
				brokerTabs = Number(bridge?.tabs_broker || 0);
			}
		} catch (_) {
			// Keep going; recover endpoint may still succeed.
		}

		const needRecover = forceReconnect || !bridgeReady || !debuggerReachable || brokerTabs <= 0;
		if (needRecover) {
			await apiFetch(`/status/broker_bridge/recover?force_reconnect=${forceReconnect ? "true" : "false"}`, {
				method: "POST",
			}, 8000);
		}

		let brokerPrice = null;
		try {
			const offsetRes = await apiFetch(`/market/offset_quality?symbol=${encodeURIComponent(symbol)}`, {}, 8000);
			if (offsetRes.ok) {
				const offset = await offsetRes.json();
				brokerPrice = offset?.prices?.broker_xauusd_price;
			}
		} catch (_) {
			brokerPrice = null;
		}

		if (brokerPrice == null && !forceReconnect && (Date.now() - _brokerAutoConnectLastEscalationAt) > 60000) {
			_brokerAutoConnectLastEscalationAt = Date.now();
			await apiFetch("/status/broker_bridge/recover?force_reconnect=true", { method: "POST" }, 8000);
		}

		const success = brokerPrice != null;
		_brokerAutoConnectLastResult = { ts: new Date(), success, state: bridgeReady ? (success ? "price_ok" : "no_price") : (brokerTabs > 0 ? "tab_not_ready" : "no_tab") };
		return success;
	} catch (_) {
		_brokerAutoConnectLastResult = { ts: new Date(), success: false, state: "error" };
		return false;
	} finally {
		_brokerAutoConnectInFlight = false;
	}
}

async function pinRegistryActiveContract() {
	const btn = document.getElementById("opsRegistryPinBtn");
	const input = document.getElementById("opsRegistryContractInput");
	const forceProbeCb = document.getElementById("opsRegistryForceProbeCb");
	const selected = canonicalRuntimeSymbolForOps(selectedChartSymbol());
	const contract = String(input?.value || "").trim();
	const forceProbe = Boolean(forceProbeCb?.checked);
	if (!contract) {
		setText("opsProbeSnapshot", "Enter a contract first (example: GC.c.1)");
		return;
	}

	if (btn) {
		btn.disabled = true;
		btn.innerText = "Pinning...";
	}
	setText("opsProbeSnapshot", `Pinning ${selected} -> ${contract} ...`);

	try {
		let res = await apiFetch(
			`/status/symbol_registry/${encodeURIComponent(selected)}/set_active_verify?contract=${encodeURIComponent(contract)}&force_probe=${forceProbe ? "true" : "false"}`,
			{ method: "POST" },
		);
		// Backward-compatible fallback if verify endpoint is unavailable.
		if (!res.ok && res.status === 404) {
			res = await apiFetch(
				`/status/symbol_registry/${encodeURIComponent(selected)}/set_active?contract=${encodeURIComponent(contract)}`,
				{ method: "POST" },
			);
		}
		if (!res.ok) {
			setText("opsProbeSnapshot", `Pin failed (${res.status})`);
			return;
		}

		const pinData = await res.json();
		const verifiedMode = String(pinData?.verify?.mode || "").toLowerCase();
		const verifiedSource = String(pinData?.verify?.futures_source || "");
		const verifiedCandles = Number(pinData?.verify?.candles);
		const reprobeQueued = Boolean(pinData?.verify?.reprobe_queued);
		if (verifiedMode) {
			const details = [
				`mode=${verifiedMode}`,
				verifiedSource ? `src=${verifiedSource}` : null,
				Number.isFinite(verifiedCandles) ? `candles=${verifiedCandles}` : null,
				reprobeQueued ? "reprobe=queued" : null,
			].filter(Boolean).join(" ");
			setText("opsProbeSnapshot", `Pinned ${selected} -> ${contract}; ${details}`);
		} else {
			setText("opsProbeSnapshot", `Pinned ${selected} -> ${contract}`);
		}

		if (Number.isFinite(verifiedCandles) && verifiedCandles <= 0) {
			const existing = document.getElementById("opsProbeSnapshot")?.textContent || "";
			const guidance = reprobeQueued
				? "No candles yet; background reprobe queued. Keep fast fallback and recheck in 10-20s."
				: "No candles yet; keep fast fallback and run Prewarm Registry or retry with force probe.";
			setText("opsProbeSnapshot", `${existing} | ${guidance}`.trim());
		}

		const modeRes = await apiFetch(`/market/offset_quality?symbol=${encodeURIComponent(selected)}`);
		if (modeRes.ok) {
			const data = await modeRes.json();
			const apiMode = String(data?.market_data_mode || "--");
			setText("opsProbeSnapshot", `${document.getElementById("opsProbeSnapshot")?.textContent || ""} api_mode=${apiMode}`.trim());
		}
	} catch (_) {
		setText("opsProbeSnapshot", "Pin request failed");
	} finally {
		if (btn) {
			btn.disabled = false;
			btn.innerText = "Pin Active Contract";
		}
		await updateOpsStatus();
	}
}

async function setPhaseDashboard(phase) {
	const res = await apiFetch("/admin/set_phase", {
		method: "POST",
		headers: { "Content-Type": "application/json" },
		body: JSON.stringify({ phase }),
	});
	if (!res.ok) return;
	await loadStatus();
	await updatePropStatus();
}

async function setAccountSizeDashboard(accountSize) {
	const key = `${Math.max(1, Math.round(Number(accountSize) / 1000))}K`;
	const res = await apiFetch("/admin/prop_engine/configure", {
		method: "POST",
		headers: { "Content-Type": "application/json" },
		body: JSON.stringify({
			active_accounts: [key],
			primary_account: key,
			mode_map: { [key]: "STANDARD" },
		}),
	});
	if (!res.ok) return;
	await updatePropStatus();
	await updateEquityBar();
	await updateDrawdownBar();
	await syncPropEngineControls();
}

function selectedPropAccounts() {
	const checkboxes = Array.from(document.querySelectorAll(".prop-account-cb"));
	const selected = checkboxes
		.filter((node) => node.checked)
		.map((node) => String(node.value || "").toUpperCase())
		.filter(Boolean);
	return selected.length ? selected : [String(document.getElementById("propPrimaryAccountSelect")?.value || "50K").toUpperCase()];
}

async function configurePropEngineDashboard() {
	const primary = String(document.getElementById("propPrimaryAccountSelect")?.value || "50K").toUpperCase();
	const mode = String(document.getElementById("propModeSelect")?.value || "STANDARD").toUpperCase();
	const active = selectedPropAccounts();
	if (!active.includes(primary)) active.push(primary);

	const modeMap = {};
	active.forEach((key) => {
		modeMap[key] = mode;
	});

	const res = await apiFetch("/admin/prop_engine/configure", {
		method: "POST",
		headers: { "Content-Type": "application/json" },
		body: JSON.stringify({
			active_accounts: active,
			primary_account: primary,
			mode_map: modeMap,
			default_mode: mode,
		}),
	});
	if (!res.ok) return;
	await syncPropEngineControls();
	await updatePropStatus();
	await updateEquityBar();
	await updateDrawdownBar();
}

async function syncPropEngineControls() {
	const res = await apiFetch("/admin/prop_engine/state");
	if (!res.ok) return;
	const data = await res.json();
	const state = data?.state || {};
	const primary = String(state?.primary_account || "50K").toUpperCase();
	const active = Array.isArray(state?.active_accounts) ? state.active_accounts.map((item) => String(item).toUpperCase()) : [];
	const profileMode = String(state?.primary_profile?.mode || "STANDARD").toUpperCase();

	const primarySelect = document.getElementById("propPrimaryAccountSelect");
	if (primarySelect) primarySelect.value = primary;

	const modeSelect = document.getElementById("propModeSelect");
	if (modeSelect) modeSelect.value = profileMode;

	Array.from(document.querySelectorAll(".prop-account-cb")).forEach((node) => {
		node.checked = active.includes(String(node.value || "").toUpperCase());
	});
}

let _opsStatusInFlight = false;
let _adminControlUnavailable = false;
let _lastGoodOffsetQuality = null;
async function updateOpsStatus() {
	// Guard: skip if a previous call is still in progress to prevent connection-pool saturation.
	if (_opsStatusInFlight) return;
	_opsStatusInFlight = true;
	try {
	const symbol = selectedChartSymbol();
	// Batch 1: fast endpoints (<5 ms each) – keep within Chrome's 6-per-host limit
	const [execRes, recRes, eqRes, propBehaviorRes, propRes, bridgeRes] = await Promise.all([
		apiFetch("/status/execution"),
		apiFetch("/status/reconciliation"),
		apiFetch("/status/equity_verification"),
		apiFetch(`/prop/auto_behavior?symbol=${encodeURIComponent(symbol)}`),
		apiFetch("/prop_status"),
		apiFetch("/status/broker_bridge"),
	]);
	// Batch 2: slower/upstream endpoints – run after batch 1 so chart can use freed connections.
	// Keep offset quality non-fatal for the full ops refresh: if it times out, use last good snapshot.
	const [feedRes, statusRes, registryRes] = await Promise.all([
		apiFetch("/status/feed"),
		apiFetch("/status"),
		apiFetch("/status/symbol_registry"),
	]);
	const offsetQualityRes = await apiFetch(
		`/market/offset_quality?symbol=${encodeURIComponent(symbol)}`,
		{},
		8000,
	).catch(() => null);
	// If any response is not ok, try to show error in the console panel
	if (!feedRes.ok || !execRes.ok || !recRes.ok || !eqRes.ok || !propRes.ok || !statusRes.ok || !bridgeRes.ok) {
		const panel = document.getElementById("operationsConsolePanel");
		if (panel) {
			panel.innerHTML = `<div style='color:#ef4444;font-size:14px;padding:12px;'>Backend error: One or more status endpoints failed to respond.<br/>Please check backend logs and network connectivity.</div>`;
		}
		return;
	}

	const feed = await feedRes.json();
	const exec = await execRes.json();
	const rec = await recRes.json();
	const eq = await eqRes.json();
	const prop = await propRes.json();
	const status = await statusRes.json();
	let offsetQuality = null;
	if (offsetQualityRes && offsetQualityRes.ok) {
		offsetQuality = await offsetQualityRes.json();
		_lastGoodOffsetQuality = offsetQuality;
	} else if (_lastGoodOffsetQuality) {
		offsetQuality = _lastGoodOffsetQuality;
	}
	const bridge = await bridgeRes.json();
	const registry = registryRes.ok ? await registryRes.json() : null;
	const propBehaviorData = propBehaviorRes.ok
		? await propBehaviorRes.json()
		: { behavior: {}, override: {}, unavailable: true };

	// Defensive: If any required object is missing, show error and return
	if (!feed || !exec || !rec || !eq || !prop || !status || !bridge) {
		const panel = document.getElementById("operationsConsolePanel");
		if (panel) {
			panel.innerHTML = `<div style='color:#ef4444;font-size:14px;padding:12px;'>Backend returned incomplete data for operations console.<br/>Please check backend health.</div>`;
		}
		return;
	}
	if (!offsetQuality) {
		offsetQuality = {
			symbol,
			market_data_mode: "UNAVAILABLE",
			sources: {},
			basis: {},
			offset_guard: {},
			trade_quality: {},
			signal_detection: {},
			prices: {},
			broker_quote: {},
		};
	}
	const behavior = propBehaviorData?.behavior || {};
	const override = propBehaviorData?.override || {};
	const feedHealthy = Boolean(feed?.healthy);
	const execStatus = String(exec?.execution_status || "--").toUpperCase();
	const recStatus = String(rec?.status || "--").toUpperCase();
	const eqStatus = String(eq?.status || "--").toUpperCase();
	const lockRule = String(prop?.lock_rule_status || "--").toUpperCase();
	const connected = Boolean(exec?.connected);
	const overrideEnabled = Boolean(override?.enabled);
	const dailyDd = Number(prop?.daily_drawdown_pct);
	const overallDd = Number(prop?.overall_drawdown_pct);

	setOpsValue("opsFeedStatus", feedHealthy ? "OK" : "DOWN", feedHealthy ? "good" : "bad");
	setOpsChips("opsFeedReason", feed?.healthy ? "OK" : (feed?.last_error || feed?.reason || "--"), feedHealthy ? "good" : "warn");
	setOpsChips("opsFeedError", feed?.last_error || "--", "neutral");
	setText("opsFeedCandles", feed?.candles != null ? String(feed.candles) : "--");
	const selectorProfile = exec?.selector_profile || {};
	setText("opsActivePhase", prop?.phase || "--");
	setText("opsCurrentBalance", fmtMoney(prop?.current_balance));
	setText("opsCurrentEquity", fmtMoney(prop?.current_equity));
	setOpsValue("opsDailyDdPct", fmtPct(prop?.daily_drawdown_pct), Number.isFinite(dailyDd) ? (dailyDd > 4 ? "bad" : dailyDd > 2.5 ? "warn" : "good") : "neutral");
	setOpsValue("opsOverallDdPct", fmtPct(prop?.overall_drawdown_pct), Number.isFinite(overallDd) ? (overallDd > 7 ? "bad" : overallDd > 4 ? "warn" : "good") : "neutral");
	setOpsValue("opsLockRule", prop?.lock_rule_status || "--", lockRule.includes("LOCK") || lockRule.includes("BREACH") ? "warn" : "good");
	setText("opsBreachRoom", fmtMoney(prop?.remaining_room_to_breach));
	setOpsValue("opsPlaywrightConnected", connected ? "YES" : "NO", connected ? "good" : "bad");
	setOpsValue("opsBridgeReady", bridge?.bridge_ready ? "YES" : "NO", bridge?.bridge_ready ? "good" : "warn");
	{
		const tabState = bridge?.broker_tab_state || "unknown";
		const tabStateColor = tabState === "logged_in" ? "good" : tabState === "login_page" ? "bad" : tabState === "challenge_page" ? "bad" : tabState === "loading" ? "warn" : "neutral";
		setOpsValue("opsBrokerTabState", tabState.toUpperCase().replace(/_/g, " "), tabStateColor);
		setOpsValue("opsLoginRequired", bridge?.login_required ? "YES – Log in to Maven" : "NO", bridge?.login_required ? "bad" : "good");
		const tabUrl = bridge?.broker_tab_url || "--";
		const urlEl = document.getElementById("opsBrokerTabUrl");
		if (urlEl) { urlEl.textContent = tabUrl; urlEl.title = tabUrl; }
		const acr = _brokerAutoConnectLastResult;
		const acText = acr ? `${acr.ts.toLocaleTimeString()} · ${acr.state}${acr.success ? " ✓" : ""}` : (bridge?.login_required ? "Waiting – login needed" : "Idle");
		setOpsValue("opsBrokerAutoConnect", acText, acr?.success ? "good" : (bridge?.login_required ? "bad" : "neutral"));
	}
	// Execution mode (PAPER / LIVE) + paper trade log
	apiFetch("/execution/mode", {}, 5000).then(async (modeRes) => {
		if (!modeRes.ok) return;
		const modeData = await modeRes.json();
		const isPaper = Boolean(modeData?.paper_mode);
		setOpsValue("opsExecutionMode", isPaper ? "PAPER (debug)" : "LIVE", isPaper ? "warn" : "good");
		setText("opsPaperTradeCount", modeData?.paper_trade_count != null ? String(modeData.paper_trade_count) : "--");
		const log = Array.isArray(modeData?.paper_trade_log) ? modeData.paper_trade_log : [];
		const last = log.length > 0 ? log[log.length - 1] : null;
		if (last) {
			const ts = last.ts ? new Date(Number(last.ts) * 1000).toLocaleTimeString() : "";
			const el = document.getElementById("opsLastPaperTrade");
			const summary = `${ts} ${last.direction || ""} ${last.symbol || ""} @${Number(last.entry_price || 0).toFixed(2)} lot=${last.lot_size || "?"}`;
			if (el) { el.textContent = summary; el.title = JSON.stringify(last, null, 2); }
		} else {
			setText("opsLastPaperTrade", "--");
		}
		// Update toggle button label
		const btn = document.getElementById("opsToggleExecModeBtn");
		if (btn) btn.textContent = isPaper ? "📋 Mode: PAPER" : "⚡ Mode: LIVE";
	}).catch(() => {});
	apiFetch("/execution/spot_fidelity", {}, 5000).then(async (spotRes) => {
		if (!spotRes.ok) return;
		const spotData = await spotRes.json();
		const strict = Boolean(spotData?.spot_fidelity_strict ?? spotData?.strict);
		setOpsValue("opsSpotFidelity", strict ? "STRICT" : "FLEX", strict ? "warn" : "good");
		const btn = document.getElementById("opsToggleSpotFidelityBtn");
		if (btn) btn.textContent = strict ? "🛡 Spot: STRICT" : "🛡 Spot: FLEX";
	}).catch(() => {});
	setOpsValue("opsSameBrowserMode", bridge?.same_browser_mode ? "YES" : "NO", bridge?.same_browser_mode ? "good" : "warn");
	setOpsValue("opsCdpReachable", bridge?.debugger_reachable ? "YES" : "NO", bridge?.debugger_reachable ? "good" : "bad");
	setText("opsBrokerTabs", bridge?.tabs_broker != null ? String(bridge.tabs_broker) : "--");
	setText("opsDashboardTabs", bridge?.tabs_dashboard != null ? String(bridge.tabs_dashboard) : "--");
	setText("opsBrowserHeartbeat", exec?.browser_heartbeat_status ? `${exec.browser_heartbeat_status}${exec?.browser_heartbeat_age_seconds != null ? ` (${exec.browser_heartbeat_age_seconds}s)` : ""}` : "--");
	setText("opsLastExecutionTs", exec?.last_trade_time ? new Date(Number(exec.last_trade_time) * 1000).toLocaleString() : "--");
	setOpsValue("opsSelectorProfile", selectorProfile?.calibrated ? "CALIBRATED" : "NOT_CALIBRATED", selectorProfile?.calibrated ? "good" : "warn");
	setText("opsSelectorUpdated", selectorProfile?.updated_at ? new Date(selectorProfile.updated_at).toLocaleString() : "--");
	setOpsValue("opsExecutionStatus", exec?.execution_status || "--", execStatus === "HALTED" ? "bad" : "good");
	const panel = exec?.order_panel || {};
	setOpsValue("opsOrderPanelReady", panel?.ready ? "READY" : "MISSING", panel?.ready ? "good" : "warn");
	setText("opsOrderPanelReason", panel?.reason || "--");
	setOpsValue("opsVolumeControl", panel?.volume_control ? "YES" : "NO", panel?.volume_control ? "good" : "warn");
	const buyPriceVal = panel?.buy_price;
	const sellPriceVal = panel?.sell_price;
	setText("opsBuyButtonPrice", buyPriceVal == null || buyPriceVal === "" || Number.isNaN(Number(buyPriceVal)) ? "--" : Number(buyPriceVal).toFixed(2));
	setText("opsSellButtonPrice", sellPriceVal == null || sellPriceVal === "" || Number.isNaN(Number(sellPriceVal)) ? "--" : Number(sellPriceVal).toFixed(2));
	setOpsValue("opsReconciliationStatus", rec?.status || "--", recStatus.includes("HALT") || recStatus.includes("FAIL") ? "bad" : recStatus.includes("WARN") ? "warn" : "good");
	setOpsValue("opsEquityStatus", eq?.status || "--", eqStatus.includes("HALT") || eqStatus.includes("FAIL") ? "bad" : eqStatus.includes("WARN") ? "warn" : "good");
	setText("opsPropMode", behavior?.mode || (propBehaviorData?.unavailable ? "UNAVAILABLE" : "--"));
	setText("opsPropRiskMult", behavior?.risk_multiplier != null ? Number(behavior.risk_multiplier).toFixed(2) : "--");
	setOpsChips(
		"opsPropReasons",
		Array.isArray(behavior?.reasons) && behavior.reasons.length
			? behavior.reasons.join(" | ")
			: (propBehaviorData?.unavailable ? "prop_auto_behavior_missing" : "--"),
	);
	setOpsValue("opsPropOverride", overrideEnabled ? (override?.mode || "CUSTOM") : "NONE", overrideEnabled ? "warn" : "neutral");
	setText("opsPropOverrideExpiry", override?.enabled && override?.expires_at ? new Date(Number(override.expires_at) * 1000).toLocaleString() : "--");
	setOpsValue("opsGovCanTrade", prop?.trading_enabled ? "YES" : "NO", prop?.trading_enabled ? "good" : "warn");
	setOpsValue("opsGovNewsHalt", status?.news_halt ? "YES" : "NO", status?.news_halt ? "warn" : "good");
	setOpsValue("opsGovStrictStartup", status?.strict_startup ? "ON" : "OFF", status?.strict_startup ? "good" : "neutral");

	const oqBasisStatus = String(offsetQuality?.basis?.status || "--").toUpperCase();
	const oqOffsetStatus = String(offsetQuality?.offset_guard?.status || "--").toUpperCase();
	const oqHardBlock = Boolean(offsetQuality?.trade_quality?.hard_block);
	const oqScore = Number(offsetQuality?.trade_quality?.score);
	const oqSignals = Number(offsetQuality?.signal_detection?.count || 0);
	const oqMode = String(offsetQuality?.market_data_mode || "--").toUpperCase();
	if (canonicalRuntimeSymbolForOps(symbol) === "XAUUSD" && offsetQuality?.prices?.broker_xauusd_price == null) {
		ensureBrokerFeedAutoConnect({ symbol: "XAUUSD", minIntervalMs: 15000 }).catch(() => {});
	}

	setText("opsOqSymbol", offsetQuality?.symbol || "--");
	setText("opsOqFuturesSource", offsetQuality?.sources?.futures_source || "--");
	setText("opsOqBrokerSymbol", offsetQuality?.sources?.broker_symbol || "--");
	setOpsValue("opsOqBasisStatus", oqBasisStatus, oqBasisStatus === "LIVE" ? "good" : (oqBasisStatus === "STALE" ? "warn" : "bad"));
	setOpsValue("opsOqOffsetStatus", oqOffsetStatus, oqOffsetStatus === "OK" ? "good" : (oqOffsetStatus === "HALT" ? "warn" : "bad"));
	setOpsValue(
		"opsOqMarketMode",
		oqMode,
		oqMode === "CACHED_REALTIME" ? "good" : (oqMode === "FAST_FALLBACK" ? "warn" : "neutral"),
	);
	setText(
		"opsOqOffsetDeviation",
		offsetQuality?.offset_guard?.deviation == null
			? "--"
			: `${Number(offsetQuality.offset_guard.deviation).toFixed(3)} pts`,
	);
	setText(
		"opsOqOffsetDifference",
		offsetQuality?.prices?.offset_difference == null
			? "--"
			: `${Number(offsetQuality.prices.offset_difference).toFixed(3)} pts`,
	);
	setText(
		"opsOqBrokerXauusd",
		offsetQuality?.prices?.broker_xauusd_price == null
			? "--"
			: fmtPrice(offsetQuality.prices.broker_xauusd_price, 2),
	);
	const bq = offsetQuality?.broker_quote || {};
	const quoteParts = [];
	if (bq?.bid != null) quoteParts.push(`B ${fmtPrice(bq.bid, 3)}`);
	if (bq?.ask != null) quoteParts.push(`A ${fmtPrice(bq.ask, 3)}`);
	if (bq?.price != null) quoteParts.push(`P ${fmtPrice(bq.price, 3)}`);
	if (bq?.last != null) quoteParts.push(`L ${fmtPrice(bq.last, 3)}`);
	setText("opsOqBrokerQuote", quoteParts.length ? quoteParts.join(" | ") : "--");
	setOpsValue(
		"opsOqQualityScore",
		Number.isFinite(oqScore) ? oqScore.toFixed(2) : "--",
		Number.isFinite(oqScore) ? (oqScore >= 80 ? "good" : oqScore >= 60 ? "warn" : "bad") : "neutral",
	);
	setOpsValue(
		"opsOqQualityGrade",
		offsetQuality?.trade_quality?.grade || "--",
		oqHardBlock ? "bad" : "good",
	);
	setOpsValue("opsOqSignalCount", String(oqSignals), oqSignals > 0 ? "good" : "warn");
	setOpsValue("opsOqHardBlock", oqHardBlock ? "YES" : "NO", oqHardBlock ? "bad" : "good");
	setOpsChips(
		"opsOqReasons",
		Array.isArray(offsetQuality?.trade_quality?.reasons) && offsetQuality.trade_quality.reasons.length
			? offsetQuality.trade_quality.reasons.join(" | ")
			: "NONE",
	);

	const registryRows = Array.isArray(registry?.symbols) ? registry.symbols : [];
	const selectedRegistrySymbol = canonicalRuntimeSymbolForOps(selectedChartSymbol());
	const selectedRegistryRow = registryRows.find((row) => String(row?.symbol || "").toUpperCase() === selectedRegistrySymbol) || null;
	const registryUnresolved = registryRows.filter((row) => {
		const status = String(row?.last_status || "").toUpperCase();
		const hasActive = Boolean(row?.resolver?.active_symbol || row?.active_symbol);
		return !(hasActive && (status === "LIVE" || status === "OK"));
	}).length;
	const registrySummaries = registryRows
		.slice(0, 6)
		.map((row) => `${row?.symbol || "--"}:${row?.resolver?.active_symbol || row?.active_symbol || "--"}`);
	setOpsValue(
		"opsRegistryStatus",
		registry?.status || "--",
		!registryRows.length ? "neutral" : (registryUnresolved === 0 ? "good" : "warn"),
	);
	setText("opsRegistryUnresolved", registryRows.length ? `${registryUnresolved}/${registryRows.length}` : "--");
	setOpsChips("opsRegistrySymbols", registrySummaries.length ? registrySummaries.join(" | ") : "--");
	setOpsValue(
		"opsRegistrySelectedStatus",
		selectedRegistryRow?.last_status || "--",
		String(selectedRegistryRow?.last_status || "").toUpperCase() === "LIVE" ? "good" : "warn",
	);
	setText("opsRegistrySelectedActive", selectedRegistryRow?.active_symbol || selectedRegistryRow?.resolver?.active_symbol || "--");
	setText("opsRegistrySelectedAttempts", selectedRegistryRow?.attempts != null ? String(selectedRegistryRow.attempts) : "--");
	setText(
		"opsRegistrySelectedFailures",
		selectedRegistryRow?.consecutive_failures != null ? String(selectedRegistryRow.consecutive_failures) : "--",
	);
	setText(
		"opsRegistrySelectedLastProbe",
		selectedRegistryRow?.resolver?.last_probe_at
			? new Date(Number(selectedRegistryRow.resolver.last_probe_at) * 1000).toLocaleString()
			: "--",
	);
	setOpsChips(
		"opsRegistrySelectedTried",
		Array.isArray(selectedRegistryRow?.resolver?.candidates_tried) && selectedRegistryRow.resolver.candidates_tried.length
			? selectedRegistryRow.resolver.candidates_tried.join(" | ")
			: "--",
	);
	setText("opsRegistrySelectedDisableReason", selectedRegistryRow?.disable_reason || selectedRegistryRow?.resolver?.disable_reason || "--");
	const registryContractInput = document.getElementById("opsRegistryContractInput");
	if (registryContractInput && !registryContractInput.value) {
		registryContractInput.value = String(offsetQuality?.sources?.futures_source || "");
	}

	// Non-blocking multi-symbol scan (don't wait for slow offset_quality)
	const scanSymbols = ["XAUUSD", "NQ", "EURUSD", "US30", "GC.FUT"];
	const timeoutMs = 4000; // 4s timeout per fetch
	Promise.allSettled(scanSymbols.map(async (sym) => {
		try {
			const controller = new AbortController();
			const timer = setTimeout(() => controller.abort(), timeoutMs);
			const r = await fetch(`${window.location.origin}/market/offset_quality?symbol=${encodeURIComponent(sym)}`, { signal: controller.signal });
			clearTimeout(timer);
			if (!r.ok) return { sym, text: `${sym}: --` };
			const d = await r.json();
			const brokerSym = d?.sources?.broker_symbol || "--";
			const xauPx = d?.prices?.broker_xauusd_price;
			const priceText = xauPx == null ? "" : ` ${fmtPrice(xauPx, 2)}`;
			return { sym, text: `${sym}: ${brokerSym}${priceText}` };
		} catch (_) {
			return { sym, text: `${sym}: --` };
		}
	})).then(results => {
		const snapRows = results
			.filter(r => r.status === "fulfilled")
			.map(r => r.value?.text || "")
			.filter(Boolean);
		if (snapRows.length > 0) {
			setOpsChips("opsOqBrokerMulti", snapRows.join(" | "), "neutral");
		} else {
			setText("opsOqBrokerMulti", "--");
		}
	}).catch(() => {
		setText("opsOqBrokerMulti", "--");
	});

	const runtime = String(exec?.execution_status || "UNKNOWN").toUpperCase() === "HALTED" ? "HALTED" : "ACTIVE";
	setOpsValue("engineRuntimeStatus", runtime, runtime === "HALTED" ? "bad" : "good");

	if (!_adminControlUnavailable) {
		try {
			const rvRes = await apiFetch("/admin/control/risk_violations?limit=200", {
				headers: adminHeaders(),
			});
			if (rvRes.status === 404) {
				_adminControlUnavailable = true;
			} else if (rvRes.ok) {
				const rv = await rvRes.json();
				const items = Array.isArray(rv?.items) ? rv.items : [];
				setOpsValue("opsRiskViolations", String(items.length), items.length > 0 ? "bad" : "good");
			}
		} catch (_) {
			setOpsValue("opsRiskViolations", "--", "neutral");
		}

		try {
			const stateRes = await apiFetch("/admin/control/state", {
				headers: adminHeaders(),
			});
			if (stateRes.status === 404) {
				_adminControlUnavailable = true;
			} else if (stateRes.ok) {
				const state = await stateRes.json();
				const execCfg = state?.execution_controls || {};
				const riskCfg = state?.risk_limits || {};
				const engineCfg = state?.engine_controls || {};
				const runtime = state?.runtime || {};
				setText("opsCfgSpreadMax", execCfg?.spread_max_limit != null ? Number(execCfg.spread_max_limit).toFixed(2) : "--");
				setText("opsCfgCooldown", execCfg?.cooldown_seconds != null ? `${execCfg.cooldown_seconds}s` : "--");
				setText("opsCfgMaxTrades", execCfg?.max_trades_per_day != null ? String(execCfg.max_trades_per_day) : "--");
				setText("opsCfgMaxRisk", riskCfg?.max_risk_per_trade != null ? `${Number(riskCfg.max_risk_per_trade).toFixed(2)}%` : "--");
				setOpsValue("opsRuntimeAutoTrading", runtime?.auto_trading_enabled ? "ON" : "OFF", runtime?.auto_trading_enabled ? "good" : "warn");
				setOpsChips(
					"opsRuntimeDisabledSymbols",
					Array.isArray(runtime?.disabled_symbols) && runtime.disabled_symbols.length
						? runtime.disabled_symbols.join(" | ")
						: "NONE",
				);
				const flags = [
					engineCfg?.ict_enabled ? "ICT" : null,
					engineCfg?.iceberg_enabled ? "ICEBERG" : null,
					engineCfg?.gann_enabled ? "GANN" : null,
					engineCfg?.astro_enabled ? "ASTRO" : null,
				].filter(Boolean);
				setOpsChips("opsCfgEngineFlags", flags.length ? flags.join("|") : "NONE");
				setText("opsCfgLastSync", new Date().toLocaleTimeString());
			}
		} catch (_) {
			setText("opsCfgSpreadMax", "--");
			setText("opsCfgCooldown", "--");
			setText("opsCfgMaxTrades", "--");
			setText("opsCfgMaxRisk", "--");
			setOpsValue("opsRuntimeAutoTrading", "--", "neutral");
			setOpsValue("opsRuntimeDisabledSymbols", "--", "neutral");
			setOpsValue("opsCfgEngineFlags", "--", "neutral");
			setText("opsCfgLastSync", "--");
		}
	}

	if (_adminControlUnavailable) {
		setOpsValue("opsRiskViolations", "N/A", "neutral");
		setText("opsCfgSpreadMax", "N/A");
		setText("opsCfgCooldown", "N/A");
		setText("opsCfgMaxTrades", "N/A");
		setText("opsCfgMaxRisk", "N/A");
		setOpsValue("opsRuntimeAutoTrading", "N/A", "neutral");
		setOpsValue("opsRuntimeDisabledSymbols", "N/A", "neutral");
		setOpsValue("opsCfgEngineFlags", "N/A", "neutral");
		setText("opsCfgLastSync", "Admin controls unavailable");
	}

	const simPhase = document.getElementById("opsSimPhase");
	if (simPhase && !simPhase.dataset.bound) {
		simPhase.value = behavior?.phase || "PHASE1";
		simPhase.dataset.bound = "1";
	}

	const simDailyLoss = document.getElementById("opsSimDailyLoss");
	if (simDailyLoss && simDailyLoss.value === "") {
		simDailyLoss.value = Number(dataOrZero(await safeStatusValue("daily_loss"))).toFixed(2);
	}

	const simDrawdown = document.getElementById("opsSimDrawdown");
	if (simDrawdown && simDrawdown.value === "") {
		simDrawdown.value = Number(dataOrZero(await safeStatusValue("capital.current_drawdown"))).toFixed(2);
	}
	} finally {
		_opsStatusInFlight = false;
	}
}

function dataOrZero(value) {
	const n = Number(value);
	return Number.isFinite(n) ? n : 0;
}

async function safeStatusValue(path) {
	try {
		const res = await apiFetch("/status");
		if (!res.ok) return 0;
		const data = await res.json();
		const parts = String(path || "").split(".");
		let cur = data;
		for (const p of parts) {
			if (cur == null) return 0;
			cur = cur[p];
		}
		return cur ?? 0;
	} catch (_) {
		return 0;
	}
}

async function runPropBehaviorScenario() {
	const symbol = selectedChartSymbol();
	const canonicalMap = {
		"GC.FUT": "XAUUSD",
		"NQ.FUT": "NQ",
		"6E.FUT": "EURUSD",
		"YM.FUT": "US30",
	};
	const canonical = canonicalMap[symbol] || symbol;

	const phase = document.getElementById("opsSimPhase")?.value || "PHASE1";
	const volatility = document.getElementById("opsSimVolatility")?.value || "NORMAL";
	const news = document.getElementById("opsSimNews")?.value || "NORMAL";
	const dailyLoss = dataOrZero(document.getElementById("opsSimDailyLoss")?.value);
	const drawdown = dataOrZero(document.getElementById("opsSimDrawdown")?.value);
	const equity = dataOrZero(await safeStatusValue("balance"));

	const res = await apiFetch("/prop/auto_behavior/simulate", {
		method: "POST",
		headers: { "Content-Type": "application/json" },
		body: JSON.stringify({
			symbol: canonical,
			phase,
			volatility_mode: volatility,
			news_mode: news,
			daily_loss: dailyLoss,
			drawdown,
			equity,
		}),
	});
	if (!res.ok) return;

	const data = await res.json();
	const sim = data?.simulated_with_override || data?.simulated || {};
	setText("opsSimMode", sim?.mode || "--");
	setText("opsSimRisk", sim?.risk_multiplier != null ? Number(sim.risk_multiplier).toFixed(2) : "--");
	setText("opsSimBlock", sim?.hard_block ? "YES" : "NO");
	setText("opsSimReasons", Array.isArray(sim?.reasons) && sim.reasons.length ? sim.reasons.join(" | ") : "--");
}

async function setPropBehaviorOverride(mode, riskMultiplier, hardBlock, expiresMinutes, reasons) {
	const symbol = selectedChartSymbol();
	const canonicalMap = {
		"GC.FUT": "XAUUSD",
		"NQ.FUT": "NQ",
		"6E.FUT": "EURUSD",
		"YM.FUT": "US30",
	};
	const canonical = canonicalMap[symbol] || symbol;

	const payload = {
		symbol: canonical,
		mode,
		risk_multiplier: riskMultiplier,
		hard_block: hardBlock,
		expires_minutes: expiresMinutes,
		reasons: Array.isArray(reasons) ? reasons : [],
	};

	const res = await apiFetch("/prop/auto_behavior/override", {
		method: "POST",
		headers: { "Content-Type": "application/json" },
		body: JSON.stringify(payload),
	});
	if (!res.ok) return;
	await updateOpsStatus();
}

async function clearPropBehaviorOverride() {
	const symbol = selectedChartSymbol();
	const canonicalMap = {
		"GC.FUT": "XAUUSD",
		"NQ.FUT": "NQ",
		"6E.FUT": "EURUSD",
		"YM.FUT": "US30",
	};
	const canonical = canonicalMap[symbol] || symbol;

	const res = await apiFetch("/prop/auto_behavior/override/clear", {
		method: "POST",
		headers: { "Content-Type": "application/json" },
		body: JSON.stringify({ symbol: canonical }),
	});
	if (!res.ok) return;
	await updateOpsStatus();
}

async function runFeedProbe(forceDeep = false) {
	const symbol = selectedChartSymbol();
	const canonicalMap = {
		"GC.FUT": "XAUUSD",
		"NQ.FUT": "NQ",
		"6E.FUT": "EURUSD",
		"YM.FUT": "US30",
	};
	const canonical = canonicalMap[symbol] || symbol;

	if (forceDeep) {
		try {
			const deepRes = await apiFetch(
				`/status/feed/deep_probe?symbols=${encodeURIComponent(canonical)}&max_candidates=6&lookback_minutes=240&record_limit=400&force_resolve=true&resolve_probe_seconds=2.5`,
				{},
				12000,
			);
			if (deepRes.ok) {
				const deep = await deepRes.json();
				const symbolRow = Array.isArray(deep?.symbols) ? deep.symbols[0] : null;
				const results = Array.isArray(symbolRow?.results) ? symbolRow.results : [];
				const summary = symbolRow?.summary || {};
				const globalSummary = deep?.summary || {};
				const parts = [];
				if (symbolRow?.dataset) parts.push(`dataset:${symbolRow.dataset}`);
				if (symbolRow?.active_after) parts.push(`active:${symbolRow.active_after}`);
				if (summary?.status) parts.push(`status:${summary.status}`);
				if (summary?.best_candidate) parts.push(`best:${summary.best_candidate}:${summary?.best_count != null ? summary.best_count : "--"}`);
				if (summary?.recommendation) parts.push(`action:${summary.recommendation}`);
				if (globalSummary?.candidates != null && globalSummary?.candidates_with_data != null) {
					parts.push(`coverage:${globalSummary.candidates_with_data}/${globalSummary.candidates}`);
				}
				for (const row of results.slice(0, 8)) {
					parts.push(`${row?.candidate || "--"}:${row?.count != null ? row.count : "--"}`);
				}
				setText("opsProbeSnapshot", parts.length ? parts.join(" | ") : "No deep probe results");
				await updateOpsStatus();
				return;
			}
		} catch (_) {
			setText("opsProbeSnapshot", "Deep probe timed out, using lightweight probe...");
		}
	}

	const res = await apiFetch(
		`/market/symbol_probe?symbol=${encodeURIComponent(canonical)}&lookback_minutes=240&include_contracts=false&max_candidates=4`,
		{},
		10000,
	);
	if (!res.ok) {
		// Compatibility fallback when symbol_probe endpoint is unavailable.
		const [offsetRes, registryRes] = await Promise.all([
			apiFetch(`/market/offset_quality?symbol=${encodeURIComponent(canonical)}`),
			apiFetch("/status/symbol_registry"),
		]);
		if (!offsetRes.ok || !registryRes.ok) return;
		const offset = await offsetRes.json();
		const registry = await registryRes.json();
		const rows = Array.isArray(registry?.symbols) ? registry.symbols : [];
		const row = rows.find((item) => String(item?.symbol || "").toUpperCase() === String(canonical || "").toUpperCase()) || null;
		const tried = Array.isArray(row?.resolver?.candidates_tried) ? row.resolver.candidates_tried : [];
		const fallbackPreview = [];
		if (offset?.sources?.futures_source) fallbackPreview.push(`active:${offset.sources.futures_source}`);
		for (const candidate of tried.slice(0, 6)) fallbackPreview.push(`${candidate}:--`);
		setText("opsProbeSnapshot", fallbackPreview.length ? fallbackPreview.join(" | ") : "Probe endpoint unavailable");
		await updateOpsStatus();
		return;
	}
	const data = await res.json();
	const rows = Array.isArray(data?.results) ? data.results : [];
	const preview = rows.map(r => `${r.candidate}:${r.count}`).join(" | ");
	setText("opsProbeSnapshot", preview || "No probe results");
	await updateOpsStatus();
}

async function runDeepProbeAll() {
	const symbols = ["XAUUSD", "NQ", "EURUSD", "US30", "GC.FUT"];
	const res = await apiFetch(
		`/status/feed/deep_probe?symbols=${encodeURIComponent(symbols.join(","))}&max_candidates=6&lookback_minutes=240&record_limit=400&force_resolve=true&resolve_probe_seconds=2.5`,
	);
	if (!res.ok) {
		setText("opsProbeMultiSummary", `Deep probe failed (${res.status})`);
		const body = document.getElementById("opsProbeMultiBody");
		if (body) body.innerHTML = `<tr><td colspan="5">Deep probe failed (${res.status})</td></tr>`;
		return;
	}
	const payload = await res.json();
	const rows = Array.isArray(payload?.symbols) ? payload.symbols : [];
	const summary = [];
	for (const row of rows) {
		const sym = String(row?.symbol || "--");
		const s = row?.summary || {};
		const st = String(s?.status || "UNKNOWN");
		const best = s?.best_candidate ? `${s.best_candidate}:${s?.best_count != null ? s.best_count : "--"}` : "--";
		summary.push(`${sym} ${st} ${best}`);
	}
	const globalSummary = payload?.summary || {};
	const coverage = (globalSummary?.candidates != null && globalSummary?.candidates_with_data != null)
		? ` coverage=${globalSummary.candidates_with_data}/${globalSummary.candidates}`
		: "";
	const action = globalSummary?.recommendation ? ` action=${globalSummary.recommendation}` : "";
	setText(
		"opsProbeMultiSummary",
		summary.length ? `${summary.join(" | ")}${coverage}${action}` : "No deep probe rows",
	);

	const body = document.getElementById("opsProbeMultiBody");
	if (body) {
		if (!rows.length) {
			body.innerHTML = `<tr><td colspan="5">No deep probe rows</td></tr>`;
		} else {
			body.innerHTML = rows
				.map((row) => {
					const sym = String(row?.symbol || "--");
					const s = row?.summary || {};
					const status = String(s?.status || "UNKNOWN");
					const best = s?.best_candidate
						? `${String(s.best_candidate)}:${s?.best_count != null ? s.best_count : "--"}`
						: "--";
					const failures = s?.resolver_failures_before != null ? String(s.resolver_failures_before) : "--";
					const rec = String(s?.recommendation || "--");
					return `<tr><td>${sym}</td><td>${status}</td><td>${best}</td><td>${failures}</td><td>${rec}</td></tr>`;
				})
				.join("");
		}
	}
}

function showOpsToast(message, tone = "info") {
	if (!message) return;
	let host = document.getElementById("opsToastHost");
	if (!host) {
		host = document.createElement("div");
		host.id = "opsToastHost";
		host.style.position = "fixed";
		host.style.right = "14px";
		host.style.bottom = "14px";
		host.style.zIndex = "12000";
		host.style.display = "flex";
		host.style.flexDirection = "column";
		host.style.gap = "8px";
		document.body.appendChild(host);
	}

	const toast = document.createElement("div");
	toast.setAttribute("role", "status");
	toast.style.padding = "8px 10px";
	toast.style.borderRadius = "8px";
	toast.style.fontSize = "12px";
	toast.style.fontWeight = "700";
	toast.style.letterSpacing = "0.2px";
	toast.style.border = "1px solid #2a3b59";
	toast.style.boxShadow = "0 8px 24px rgba(0,0,0,0.28)";
	toast.style.background = "#0f1b2f";
	toast.style.color = "#dbe6f4";
	if (tone === "success") {
		toast.style.borderColor = "#22c55e";
		toast.style.color = "#86efac";
	}
	if (tone === "error") {
		toast.style.borderColor = "#f87171";
		toast.style.color = "#fca5a5";
	}
	toast.textContent = String(message);
	host.appendChild(toast);

	setTimeout(() => {
		try {
			toast.remove();
			if (host && host.childElementCount === 0) host.remove();
		} catch (_) {
			// no-op
		}
	}, 2500);
}

async function copyOpsDiagnostics() {
	const snapshot = String(document.getElementById("opsProbeSnapshot")?.textContent || "--").trim();
	const multi = String(document.getElementById("opsProbeMultiSummary")?.textContent || "--").trim();
	const payload = [
		`probe_snapshot: ${snapshot}`,
		`probe_multi: ${multi}`,
		`copied_at: ${new Date().toISOString()}`,
	].join("\n");

	let copied = false;
	try {
		if (navigator?.clipboard?.writeText) {
			await navigator.clipboard.writeText(payload);
			copied = true;
		}
	} catch (_) {
		copied = false;
	}

	if (!copied) {
		try {
			const ta = document.createElement("textarea");
			ta.value = payload;
			ta.setAttribute("readonly", "true");
			ta.style.position = "fixed";
			ta.style.opacity = "0";
			document.body.appendChild(ta);
			ta.select();
			copied = document.execCommand("copy");
			ta.remove();
		} catch (_) {
			copied = false;
		}
	}

	if (copied) {
		showOpsToast("Diagnostics copied", "success");
	} else {
		showOpsToast("Copy failed", "error");
	}
}

async function engineAction(action) {
	const endpoint = action === "start" ? "/engine/start" : "/engine/stop";
	const res = await apiFetch(endpoint, { method: "POST" });
	if (!res.ok) return;
	const data = await res.json();
	setText("engineRuntimeStatus", data?.status || "--");
	await updateOpsStatus();
}

async function reconnectExecutionBrowser() {
	if (typeof window.apiResetCircuit === "function") window.apiResetCircuit();
	setText("opsProbeSnapshot", "Reconnect requested...");
	await apiFetch("/execution/reconnect?async_mode=false&force=true", { method: "POST" });
	setText("opsProbeSnapshot", "Reconnecting browser session...");
	await new Promise(resolve => setTimeout(resolve, 500));
	setText("opsProbeSnapshot", "Validating selectors...");
	await apiFetch("/execution/recover?force_reconnect=true", { method: "POST" });
	await updateOpsStatus();
	setTimeout(() => updateOpsStatus().catch(console.error), 1200);
	setTimeout(() => updateOpsStatus().catch(console.error), 2600);
	setText("opsProbeSnapshot", "Reconnect completed");
}



window.reconnectExecutionBrowserSafe = function reconnectExecutionBrowserSafe() {
	reconnectExecutionBrowser().catch((err) => {
		setText("opsProbeSnapshot", `Reconnect failed: ${String(err || "unknown error")}`);
	});
};

window.recoverBrokerBridgeSafe = function recoverBrokerBridgeSafe() {
	if (typeof window.apiResetCircuit === "function") window.apiResetCircuit();
	apiFetch("/status/broker_bridge/recover?force_reconnect=true", { method: "POST" })
		.then((res) => {
			if (!res.ok) throw new Error("recover endpoint failed");
			return updateOpsStatus();
		})
		.catch((err) => {
			setText("opsProbeSnapshot", `Bridge recover failed: ${String(err || "unknown error")}`);
		});
};

window.toggleExecutionModeSafe = async function toggleExecutionModeSafe() {
	const btn = document.getElementById("opsToggleExecModeBtn");
	if (btn) { btn.disabled = true; btn.textContent = "Switching\u2026"; }
	try {
		const modeRes = await apiFetch("/execution/mode", {}, 5000);
		if (!modeRes.ok) throw new Error("mode GET failed");
		const current = await modeRes.json();
		const newMode = current?.paper_mode ? "LIVE" : "PAPER";
		const setRes = await apiFetch(`/execution/mode?mode=${newMode}`, { method: "POST" }, 5000);
		if (!setRes.ok) throw new Error("mode POST failed");
		const updated = await setRes.json();
		const isPaper = Boolean(updated?.paper_mode);
		setOpsValue("opsExecutionMode", isPaper ? "PAPER (debug)" : "LIVE", isPaper ? "warn" : "good");
		if (btn) btn.textContent = isPaper ? "\uD83D\uDCCB Mode: PAPER" : "\u26A1 Mode: LIVE";
		setText("opsProbeSnapshot", `Execution mode \u2192 ${updated?.mode || newMode}`);
	} catch (err) {
		setText("opsProbeSnapshot", `Mode switch failed: ${String(err || "unknown")}`);
	} finally {
		if (btn) btn.disabled = false;
	}
};

window.toggleSpotFidelitySafe = async function toggleSpotFidelitySafe() {
	const btn = document.getElementById("opsToggleSpotFidelityBtn");
	if (btn) { btn.disabled = true; btn.textContent = "Switching\u2026"; }
	try {
		const currentRes = await apiFetch("/execution/spot_fidelity", {}, 5000);
		if (!currentRes.ok) throw new Error("spot fidelity GET failed");
		const current = await currentRes.json();
		const currentStrict = Boolean(current?.spot_fidelity_strict ?? current?.strict);
		const nextStrict = !currentStrict;
		const setRes = await apiFetch(`/execution/spot_fidelity?strict=${nextStrict ? "true" : "false"}`, { method: "POST" }, 5000);
		if (!setRes.ok) throw new Error("spot fidelity POST failed");
		const updated = await setRes.json();
		const strict = Boolean(updated?.spot_fidelity_strict ?? updated?.strict);
		setOpsValue("opsSpotFidelity", strict ? "STRICT" : "FLEX", strict ? "warn" : "good");
		if (btn) btn.textContent = strict ? "🛡 Spot: STRICT" : "🛡 Spot: FLEX";
		setText("opsProbeSnapshot", `Spot fidelity \u2192 ${strict ? "STRICT" : "FLEX"}`);
	} catch (err) {
		setText("opsProbeSnapshot", `Spot fidelity switch failed: ${String(err || "unknown")}`);
	} finally {
		if (btn) btn.disabled = false;
	}
};

window.triggerExecutionSafe = async function triggerExecutionSafe() {
	const btn = document.getElementById("opsTriggerTradeBtn");
	if (btn) { btn.disabled = true; btn.textContent = "Triggering\u2026"; }
	const symbol = selectedChartSymbol() || "XAUUSD";
	try {
		const res = await apiFetch(`/execution/trigger?symbol=${encodeURIComponent(symbol)}`, { method: "POST" }, 12000);
		if (!res.ok) throw new Error(`trigger failed (${res.status})`);
		const data = await res.json();
		const result = data?.result || data;
		const statusTxt = `${result?.status || "?"} \u00b7 ${result?.mode || ""} \u00b7 ${result?.direction || result?.reason || ""}`;
		setText("opsProbeSnapshot", `Trigger: ${statusTxt}`);
		apiFetch("/execution/mode", {}, 5000).then(async (mr) => {
			if (!mr.ok) return;
			const md = await mr.json();
			setText("opsPaperTradeCount", md?.paper_trade_count != null ? String(md.paper_trade_count) : "--");
			const log = Array.isArray(md?.paper_trade_log) ? md.paper_trade_log : [];
			const last = log.length > 0 ? log[log.length - 1] : null;
			if (last) {
				const ts = last.ts ? new Date(Number(last.ts) * 1000).toLocaleTimeString() : "";
				const el = document.getElementById("opsLastPaperTrade");
				const summary = `${ts} ${last.direction || ""} ${last.symbol || ""} @${Number(last.entry_price || 0).toFixed(2)} lot=${last.lot_size || "?"}`;
				if (el) { el.textContent = summary; el.title = JSON.stringify(last, null, 2); }
			}
		}).catch(() => {});
	} catch (err) {
		setText("opsProbeSnapshot", `Trigger failed: ${String(err || "unknown")}`);
	} finally {
		if (btn) { btn.disabled = false; btn.textContent = "\u26A1 Trigger Trade"; }
	}
};

window.openBrokerPage = function openBrokerPage() {
	// Try to fetch broker URL from backend config endpoint
	apiFetch("/status/broker_config")
		.then((res) => {
			if (!res.ok) {
				// Fallback to known Maven broker URL
				const brokerUrl = "https://manager.maven.markets/app/trade";
				window.open(brokerUrl, "maven_broker", "width=1200,height=800");
				return;
			}
			return res.json();
		})
		.then((data) => {
			if (data && data.broker_url) {
				window.open(data.broker_url, "maven_broker", "width=1200,height=800");
			} else if (!data) {
				// Fallback already opened above
			}
		})
		.catch((err) => {
			// Fallback to known Maven broker URL on error
			const brokerUrl = "https://manager.maven.markets/app/trade";
			window.open(brokerUrl, "maven_broker", "width=1200,height=800");
			console.warn("Failed to fetch broker config, using fallback URL:", err);
		});
};
async function adminEmergency(action, enabled = null) {
	const endpointMap = {
		kill: "/admin/control/emergency/kill",
		restart: "/admin/control/emergency/restart_execution",
		disable_auto: "/admin/control/emergency/auto_trading",
	};
	const endpoint = endpointMap[action];
	if (!endpoint) return;
	const options = {
		method: "POST",
		headers: adminHeaders(),
	};
	if (action === "disable_auto") {
		options.body = JSON.stringify({ enabled: Boolean(enabled) });
	}
	await apiFetch(endpoint, options);
	await updateOpsStatus();
}

async function setGannEngineEnabled(enabled) {
	const stateRes = await apiFetch("/admin/control/state", {
		headers: adminHeaders(),
	});
	if (!stateRes.ok) {
		setText("opsProbeSnapshot", "Failed to load admin state for GANN toggle");
		return;
	}
	const state = await stateRes.json();
	const cfg = state?.engine_controls || {};
	const nextEnabled = Boolean(enabled);

	const payload = {
		ict_enabled: Boolean(cfg?.ict_enabled),
		iceberg_enabled: Boolean(cfg?.iceberg_enabled),
		gann_enabled: nextEnabled,
		astro_enabled: Boolean(cfg?.astro_enabled),
		confluence_threshold: Number(cfg?.confluence_threshold ?? 0.5),
		confidence_threshold: Number(cfg?.confidence_threshold ?? 55),
	};

	const res = await apiFetch("/admin/control/engine_controls", {
		method: "POST",
		headers: {
			"Content-Type": "application/json",
			...adminHeaders(),
		},
		body: JSON.stringify(payload),
	});
	if (!res.ok) {
		setText("opsProbeSnapshot", `GANN toggle failed (${res.status})`);
		return;
	}

	setText("opsProbeSnapshot", `GANN ${nextEnabled ? "enabled" : "disabled"}`);
	await updateOpsStatus();
}

setSingletonInterval("governancePanelRefresh", () => {
	if (!document.getElementById("governancePanel")?.classList.contains("open")) return;
	loadStatus().catch(console.error);
	updateVolatility().catch(console.error);
	updatePropStatus().catch(console.error);
	updateEquityBar().catch(console.error);
	updateDrawdownBar().catch(console.error);
	updateModelStats().catch(console.error);
	updateNewsSeverity().catch(console.error);
}, 5000);

setSingletonInterval("systemHealthPanelRefresh", () => {
	if (!document.getElementById("systemHealthPanel")?.classList.contains("open")) return;
	updateSystemHealth().catch(console.error);
}, 5000);

setSingletonInterval("journalPanelRefresh", () => {
	if (!document.getElementById("journalPanel")?.classList.contains("open")) return;
	loadJournal().catch(console.error);
}, 8000);

setSingletonInterval("operationsConsoleRefresh", () => {
	if (!document.getElementById("operationsConsolePanel")?.classList.contains("open")) return;
	updateBasisOps().catch(console.error);
	updateOpsStatus().catch(console.error);
	updateMultiSymbolDashboard().catch(console.error);
}, 7000);

const warmupBtn = document.getElementById("basisWarmupBtn");
if (warmupBtn) warmupBtn.addEventListener("click", () => warmupContracts().catch(console.error));

const opsRegistryPrewarmBtn = document.getElementById("opsRegistryPrewarmBtn");
if (opsRegistryPrewarmBtn) opsRegistryPrewarmBtn.addEventListener("click", () => prewarmSymbolRegistry().catch(console.error));

const opsRegistryPinBtn = document.getElementById("opsRegistryPinBtn");
if (opsRegistryPinBtn) opsRegistryPinBtn.addEventListener("click", () => pinRegistryActiveContract().catch(console.error));

const chartSymbolControl = document.getElementById("chartSymbolInput") || document.getElementById("chartSymbol");
if (chartSymbolControl) {
	let symbolSideEffectsTimer = null;
	chartSymbolControl.addEventListener("change", () => {
		if (symbolSideEffectsTimer) clearTimeout(symbolSideEffectsTimer);
		symbolSideEffectsTimer = setTimeout(() => {
			// Keep symbol panels in sync without triggering expensive deep probes on every symbol change.
			updateBasisOps(false).catch(console.error);
			updateModelStats().catch(console.error);
			loadJournal().catch(console.error);
			updateOpsStatus().catch(console.error);
			ensureBrokerFeedAutoConnect({ symbol: selectedChartSymbol(), minIntervalMs: 3000 }).catch(() => {});
		}, 300);
	});
}

const phase1Btn = document.getElementById("phase1Btn");
if (phase1Btn) phase1Btn.addEventListener("click", () => setPhaseDashboard("PHASE1").catch(console.error));

const phase2Btn = document.getElementById("phase2Btn");
if (phase2Btn) phase2Btn.addEventListener("click", () => setPhaseDashboard("PHASE2").catch(console.error));

const fundedBtn = document.getElementById("fundedBtn");
if (fundedBtn) fundedBtn.addEventListener("click", () => setPhaseDashboard("FUNDED").catch(console.error));

const applyPropEngineBtn = document.getElementById("applyPropEngineBtn");
if (applyPropEngineBtn) applyPropEngineBtn.addEventListener("click", () => configurePropEngineDashboard().catch(console.error));

const engineStartBtn = document.getElementById("engineStartBtn");
if (engineStartBtn) engineStartBtn.addEventListener("click", () => engineAction("start").catch(console.error));

const engineStopBtn = document.getElementById("engineStopBtn");
if (engineStopBtn) engineStopBtn.addEventListener("click", () => engineAction("stop").catch(console.error));

const opsProbeBtn = document.getElementById("opsProbeBtn");
if (opsProbeBtn) opsProbeBtn.addEventListener("click", () => runFeedProbe(true).catch(console.error));

const opsDeepProbeAllBtn = document.getElementById("opsDeepProbeAllBtn");
if (opsDeepProbeAllBtn) opsDeepProbeAllBtn.addEventListener("click", () => runDeepProbeAll().catch(console.error));

const opsCopyDiagBtn = document.getElementById("opsCopyDiagBtn");
if (opsCopyDiagBtn) opsCopyDiagBtn.addEventListener("click", () => copyOpsDiagnostics().catch(console.error));

const opsGannOnBtn = document.getElementById("opsGannOnBtn");
if (opsGannOnBtn) opsGannOnBtn.addEventListener("click", () => setGannEngineEnabled(true).catch(console.error));

const opsGannOffBtn = document.getElementById("opsGannOffBtn");
if (opsGannOffBtn) opsGannOffBtn.addEventListener("click", () => setGannEngineEnabled(false).catch(console.error));

const opsReconnectBtn = document.getElementById("opsReconnectBtn");
if (opsReconnectBtn) opsReconnectBtn.addEventListener("click", () => window.reconnectExecutionBrowserSafe());

const opsBridgeRecoverBtn = document.getElementById("opsBridgeRecoverBtn");
if (opsBridgeRecoverBtn) opsBridgeRecoverBtn.addEventListener("click", () => window.recoverBrokerBridgeSafe());

const opsKillSwitchBtn = document.getElementById("opsKillSwitchBtn");
if (opsKillSwitchBtn) opsKillSwitchBtn.addEventListener("click", () => adminEmergency("kill").catch(console.error));

const opsRestartExecBtn = document.getElementById("opsRestartExecBtn");
if (opsRestartExecBtn) opsRestartExecBtn.addEventListener("click", () => adminEmergency("restart").catch(console.error));

const opsDisableAutoBtn = document.getElementById("opsDisableAutoBtn");
if (opsDisableAutoBtn) opsDisableAutoBtn.addEventListener("click", () => adminEmergency("disable_auto", false).catch(console.error));

const opsDefensiveBtn = document.getElementById("opsDefensiveBtn");
if (opsDefensiveBtn) {
	opsDefensiveBtn.addEventListener("click", () => setPropBehaviorOverride(
		"DEFENSIVE_OVERRIDE",
		0.5,
		false,
		60,
		["Manual defensive override"],
	).catch(console.error));
}

const opsHaltBtn = document.getElementById("opsHaltBtn");
if (opsHaltBtn) {
	opsHaltBtn.addEventListener("click", () => setPropBehaviorOverride(
		"HALT_OVERRIDE",
		0.0,
		true,
		60,
		["Manual halt override"],
	).catch(console.error));
}
const opsClearOverrideBtn = document.getElementById("opsClearOverrideBtn");
if (opsClearOverrideBtn) {
	opsClearOverrideBtn.addEventListener("click", () => clearPropBehaviorOverride().catch(console.error));
}

const opsSimRunBtn = document.getElementById("opsSimRunBtn");
if (opsSimRunBtn) {
	opsSimRunBtn.addEventListener("click", () => runPropBehaviorScenario().catch(console.error));
}

for (const kind of Object.keys(MICRO_PANEL_CONFIG)) {
	toggleMicroPanel(kind, false);
}
initMicroPanelDrags();
toggleGovernancePanel(false);
toggleSystemHealthPanel(false);
initGovernancePanelInteractions();
initSystemHealthPanelInteractions();
toggleOperationsConsole(false);
initOperationsConsoleDrag();
toggleJournalPanel(false);
initJournalPanelDrag();

// Performance Dashboard initialization
function updatePerfDashboard() {
	const perfDiv = document.getElementById("perfMetrics");
	if (!perfDiv) return;
	
	const summary = getPerformanceSummary();
	if (!summary || summary.totalRequests === 0) {
		perfDiv.innerHTML = "<p>No metrics yet</p>";
		return;
	}
	
	let html = `<p><strong>Total Requests:</strong> ${summary.totalRequests}</p>`;
	html += "<p><strong>Avg Time by Endpoint:</strong></p>";
	html += "<table style='width:100%;'>";
	for (const [path, avg] of Object.entries(summary.averageByPath)) {
		html += `<tr><td>${path}</td><td style='text-align:right;'>${avg}ms</td></tr>`;
	}
	html += "</table>";
	
	perfDiv.innerHTML = html;
}

function updateCacheStatus() {
	const cacheDiv = document.getElementById("cacheStatus");
	if (!cacheDiv) return;
	cacheDiv.innerHTML = "Cache status UI removed (no CACHE_CONFIG)";
}

function initPerfDashboard() {
	const perfBtn = document.getElementById("perfDashBtn");
	const perfDash = document.getElementById("perfDashboard");
	const perfClose = document.getElementById("perfDashClose");
	const clearCacheBtn = document.getElementById("clearCacheBtn");
	const refreshMetricsBtn = document.getElementById("refreshMetricsBtn");
	
	if (perfBtn) {
		perfBtn.addEventListener("click", () => {
			if (perfDash) {
				perfDash.classList.toggle("hidden");
				if (!perfDash.classList.contains("hidden")) {
					updatePerfDashboard();
					updateCacheStatus();
				}
			}
		});
	}
	
	if (perfClose) {
		perfClose.addEventListener("click", () => {
			if (perfDash) perfDash.classList.add("hidden");
		});
	}
	
	if (clearCacheBtn) {
		clearCacheBtn.addEventListener("click", () => {
			clearCache("*");
			showError("cache_cleared", "✓ All caches cleared", null, true);
			updateCacheStatus();
		});
	}
	
	if (refreshMetricsBtn) {
		refreshMetricsBtn.addEventListener("click", () => {
			updatePerfDashboard();
			updateCacheStatus();
		});
	}
}

initPerfDashboard();

function dedupeElementsById(ids) {
	for (const id of (ids || [])) {
		const nodes = Array.from(document.querySelectorAll(`#${id}`));
		if (nodes.length <= 1) continue;
		for (const node of nodes.slice(1)) {
			node.remove();
		}
	}
}

function dedupeFloatingPanelsOnLoad() {
	dedupeElementsById([
		"governancePanel",
		"systemHealthPanel",
		"journalPanel",
		"microIcebergPanel",
		"microOrderflowPanel",
		"microOrderflowSummaryPanel",
		"microTimeSalesPanel",
		"microLadderPanel",
		"propChallengePanel",
		"openPropChallengeBtn",
	]);

	const spreadButtons = Array.from(document.querySelectorAll("button")).filter((button) =>
		String(button.textContent || "").trim().startsWith("Open Spread/Offset:")
	);
	for (const button of spreadButtons.slice(1)) {
		button.remove();
	}
}

// Health check: Ping backend every 30 seconds to detect recovery
setSingletonInterval("backendHealthPing", async () => {
    try {
        const res = await apiFetch("/status", {}, 5000);
        if (res && res.ok) {
            updateConnectionStatus(true, "Connected");
        }
    } catch (err) {
        // apiFetch() already shows errors, just track them here
    }
}, 30000); // Every 30 seconds

// Force-refresh all panels, tables, and feeds on page load
window.addEventListener("load", () => {
	dedupeFloatingPanelsOnLoad();
	ensureBrokerFeedAutoConnect({ symbol: "XAUUSD", minIntervalMs: 0 }).catch(() => {});
	// Chart
	if (typeof loadInstitutionalChart === "function") loadInstitutionalChart();
	// Micro panels
	for (const kind of Object.keys(MICRO_PANEL_CONFIG)) {
		if (typeof toggleMicroPanel === "function") toggleMicroPanel(kind, true);
		if (kind === "summary" && typeof refreshOrderflowSummaryPanel === "function") refreshOrderflowSummaryPanel();
	}
	// Journal
	if (typeof loadJournal === "function") loadJournal();
	// Governance
	if (typeof loadStatus === "function") loadStatus();
	if (typeof updateVolatility === "function") updateVolatility();
	if (typeof updatePropStatus === "function") updatePropStatus();
	if (typeof updateEquityBar === "function") updateEquityBar();
	if (typeof updateDrawdownBar === "function") updateDrawdownBar();
	if (typeof updateModelStats === "function") updateModelStats();
	if (typeof updateNewsSeverity === "function") updateNewsSeverity();
	// System Health
	if (typeof updateSystemHealth === "function") updateSystemHealth();
	// Operations Console
	if (typeof updateBasisOps === "function") updateBasisOps();
	if (typeof updateOpsStatus === "function") updateOpsStatus();
	if (typeof updateMultiSymbolDashboard === "function") updateMultiSymbolDashboard();
	});


