const AQ_DEFAULT_ADMIN_API_ORIGIN = String(window.location.origin || "").trim();
const AQ_API_BASE = window.AQ_API_BASE || AQ_DEFAULT_ADMIN_API_ORIGIN;

function adminApiOrigins() {
  const existing = String(window.AQ_API_BASE || "").trim();
  if (existing) {
    return [existing, String(window.location.origin || "").trim()].filter(Boolean);
  }
  const origins = [];
  const uniqueOrigins = new Set();
  const baseOrigins = [
    String(window.location.origin || "").trim(),
  ];
  for (const origin of baseOrigins) {
    if (origin && !uniqueOrigins.has(origin)) {
      uniqueOrigins.add(origin);
      origins.push(origin);
    }
  }
  return origins.length ? origins : [String(window.location.origin || "").trim()].filter(Boolean);
}

function getCreds() {
  const storedToken = localStorage.getItem("AQ_ADMIN_TOKEN");
  const safeStoredToken = storedToken && storedToken !== "dev-admin-token" ? storedToken : "";
  return {
    token: document.getElementById("adminToken")?.value || safeStoredToken || "aq-admin-token-20260329",
    role: document.getElementById("adminRole")?.value || localStorage.getItem("AQ_ADMIN_ROLE") || "ADMIN",
    user: document.getElementById("adminUser")?.value || localStorage.getItem("AQ_ADMIN_USER") || "admin",
  };
}

function adminFetch(path, options = {}) {
  const creds = getCreds();
  const headers = {
    "Content-Type": "application/json",
    "x-admin-token": creds.token,
    "x-admin-role": creds.role,
    "x-admin-user": creds.user,
    ...(options.headers || {}),
  };
  
  // Priority 1: Try relative URL (same origin)
  const targets = [path];
  
  // Priority 2: Fallback origins (absolute URLs)
  const priorityOrigins = [
    window.location.origin,
    AQ_API_BASE,
  ]
    .filter((v, i, arr) => v && arr.indexOf(v) === i);
  
  for (const origin of priorityOrigins) {
    if (origin !== window.location.origin) {
      targets.push(`${origin}${path}`);
    }
  }
  
  let lastError = null;
  for (const target of targets) {
    try {
      return fetch(target, { ...options, headers });
    } catch (error) {
      lastError = error;
      console.debug(`adminFetch fallback: ${target} failed`, error);
    }
  }
  
  console.warn("adminFetch failed on all targets:", targets);
  return Promise.reject(lastError || new Error("all adminFetch attempts failed"));
}

function setValue(id, value) {
  const el = document.getElementById(id);
  if (el) el.value = value != null ? value : "";
}

function setText(id, value) {
  const el = document.getElementById(id);
  if (el) el.innerText = value;
}

async function refreshState() {
  const res = await adminFetch("/admin/control/state");
  if (!res.ok) {
    setText("stateMeta", `State load failed (${res.status})`);
    return;
  }
  const data = await res.json();
  setText("stateMeta", `Runtime auto-trading: ${data?.runtime?.auto_trading_enabled ? "ON" : "OFF"} | Execution halted: ${data?.runtime?.execution_halted ? "YES" : "NO"}`);

  const users = Array.isArray(data?.users) ? data.users : [];
  const usersBody = document.getElementById("usersBody");
  if (usersBody) {
    usersBody.innerHTML = users.map(u => `<tr><td>${u.username}</td><td>${u.role}</td><td>${u.phase}</td><td>${u.auto_trading_enabled ? "ON" : "OFF"}</td><td>${u.banned ? "YES" : "NO"}</td></tr>`).join("");
  }

  const prop = data?.prop_rules || {};
  setValue("propProfitTarget", prop.profit_target_pct);
  setValue("propDailyDd", prop.daily_dd_pct);
  setValue("propOverallDd", prop.overall_dd_pct);
  setValue("propLockLevel", prop.lock_level);
  setValue("propMinDays", prop.min_profitable_days);
  setValue("propLeverage", prop.leverage_limit);

  const engine = data?.engine_controls || {};
  window._engineToggles = {
    ict_enabled: Boolean(engine.ict_enabled),
    iceberg_enabled: Boolean(engine.iceberg_enabled),
    gann_enabled: Boolean(engine.gann_enabled),
    astro_enabled: Boolean(engine.astro_enabled),
  };
  setValue("engineConfluence", engine.confluence_threshold);
  setValue("engineConfidence", engine.confidence_threshold);

  const exec = data?.execution_controls || {};
  setValue("execSpread", exec.spread_max_limit);
  setValue("execSlippage", exec.slippage_tolerance);
  setValue("execCooldown", exec.cooldown_seconds);
  setValue("execMaxTrades", exec.max_trades_per_day);
  setValue("execMaxConcurrent", exec.max_concurrent_trades);
  setValue("execTimeout", exec.execution_timeout_seconds);

  const risk = data?.risk_limits || {};
  setValue("riskMaxLot", risk.max_lot_size);
  setValue("riskPerTrade", risk.max_risk_per_trade);
  setValue("riskDailyMaxTrades", risk.daily_max_trades);
  setValue("riskMultP1", risk.risk_multiplier_phase1);
  setValue("riskMultP2", risk.risk_multiplier_phase2);
  setValue("riskMultFunded", risk.risk_multiplier_funded);

  const symbolsBody = document.getElementById("symbolsBody");
  const symbols = Array.isArray(data?.symbol_activation) ? data.symbol_activation : [];
  if (symbolsBody) {
    symbolsBody.innerHTML = symbols.map(s => `<tr><td>${s.symbol}</td><td>${s.enabled ? "YES" : "NO"}</td><td>${s.updated_at ? new Date(Number(s.updated_at) * 1000).toLocaleString() : "--"}</td></tr>`).join("");
  }

  await refreshDynamicPropState();
}

// Account size in dollars mapping
const ACCOUNT_SIZE_MAP = {
  "5K": 5000, "10K": 10000, "15K": 15000, "20K": 20000,
  "25K": 25000, "30K": 30000, "50K": 50000, "100K": 100000,
};

function _highlightPresetBtn(accountKey) {
  document.querySelectorAll(".preset-acct-btn").forEach((btn) => {
    const isActive = String(btn.dataset.account || "").toUpperCase() === String(accountKey || "").toUpperCase();
    btn.classList.toggle("active", isActive);
  });
}

async function refreshDynamicPropState() {
  const res = await adminFetch("/admin/prop_engine/state");
  if (!res.ok) return;
  const data = await res.json();
  const state = data?.state || {};
  const primary = String(state?.primary_account || "50K").toUpperCase();
  const mode = String(state?.primary_profile?.mode || "STANDARD").toUpperCase();
  const profile = state?.primary_profile || {};
  const accountSize = Number(profile?.account_size || 0);
  const dailyMax = Number(profile?.daily_max_loss || 0);
  const totalMax = Number(profile?.total_max_loss || 0);
  const phase1Target = Number(profile?.phase1_target || 0);
  const strictRisk = Number(state?.portfolio?.strict_risk_pct || 0) * 100;

  setValue("adminPrimaryAccount", primary);
  setValue("adminAccountMode", mode);
  _highlightPresetBtn(primary);

  setText(
    "dynamicPropMeta",
    `Account: ${primary} (${accountSize > 0 ? "$" + accountSize.toLocaleString() : "--"}) | Mode: ${mode}\n` +
    `Daily Max Loss: $${dailyMax.toFixed(0)} | Total Max Loss: $${totalMax.toFixed(0)} | Phase1 Target: $${phase1Target.toFixed(0)}\n` +
    `Risk/Trade: ${strictRisk.toFixed(2)}%`,
  );
}

async function applyDynamicPropEngine() {
  const primaryEl = document.getElementById("adminPrimaryAccount");
  const primary = String(primaryEl?.value || "50K").toUpperCase();
  const mode = String(document.getElementById("adminAccountMode")?.value || "STANDARD").toUpperCase();
  const strictMode = document.getElementById("adminStrictMode")?.value !== "false";
  const accountSizeDollars = ACCOUNT_SIZE_MAP[primary] || 50000;

  // Step 1: Update dynamic prop engine module
  await adminFetch("/admin/prop_engine/configure", {
    method: "POST",
    body: JSON.stringify({
      active_accounts: [primary],
      primary_account: primary,
      mode_map: { [primary]: mode },
      default_mode: mode,
    }),
  });

  // Step 2: Bootstrap challenge — applies account size to the live runner
  const bootstrapRes = await adminFetch("/admin/control/challenge/bootstrap", {
    method: "POST",
    body: JSON.stringify({ account_size: accountSizeDollars, strict_mode: strictMode }),
  });

  const metaEl = document.getElementById("dynamicPropMeta");
  if (bootstrapRes && bootstrapRes.ok) {
    const result = await bootstrapRes.json();
    if (metaEl) {
      metaEl.style.background = "#f0fdf4";
      metaEl.style.borderColor = "#86efac";
      setTimeout(() => {
        metaEl.style.background = "#f0f7ff";
        metaEl.style.borderColor = "#bfdbfe";
      }, 2000);
    }
    _highlightPresetBtn(primary);
  } else {
    if (metaEl) {
      metaEl.style.background = "#fff1f2";
      metaEl.style.borderColor = "#fca5a5";
      setText("dynamicPropMeta", `Apply failed (${bootstrapRes?.status}) — check ADMIN_API_TOKEN`);
      setTimeout(() => {
        metaEl.style.background = "#f0f7ff";
        metaEl.style.borderColor = "#bfdbfe";
      }, 3000);
      return;
    }
  }

  await refreshDynamicPropState();
}

async function useAccountPreset(accountKey) {
  const normalized = String(accountKey || "50K").toUpperCase();
  const primaryEl = document.getElementById("adminPrimaryAccount");
  if (primaryEl) primaryEl.value = normalized;
  _highlightPresetBtn(normalized);
  await applyDynamicPropEngine();
}

async function saveUser(autoEnabled, banned) {
  const payload = {
    username: document.getElementById("userName")?.value || "",
    role: document.getElementById("userRole")?.value || "VIEWER",
    phase: document.getElementById("userPhase")?.value || "PHASE1",
    auto_trading_enabled: Boolean(autoEnabled),
    risk_multiplier: Number(document.getElementById("userRiskMultiplier")?.value || 1),
    banned: Boolean(banned),
  };
  if (!payload.username) return;
  await adminFetch("/admin/control/users/upsert", { method: "POST", body: JSON.stringify(payload) });
  await refreshState();
}

async function banUser(flag) {
  const username = document.getElementById("userName")?.value || "";
  if (!username) return;
  await adminFetch("/admin/control/users/ban", { method: "POST", body: JSON.stringify({ username, banned: Boolean(flag) }) });
  await refreshState();
}

async function savePropRules() {
  const payload = {
    profit_target_pct: Number(document.getElementById("propProfitTarget")?.value || 8),
    daily_dd_pct: Number(document.getElementById("propDailyDd")?.value || 1.5),
    overall_dd_pct: Number(document.getElementById("propOverallDd")?.value || 8),
    lock_level: Number(document.getElementById("propLockLevel")?.value || 52000),
    min_profitable_days: Number(document.getElementById("propMinDays")?.value || 3),
    leverage_limit: Number(document.getElementById("propLeverage")?.value || 20),
  };
  await adminFetch("/admin/control/prop_rules", { method: "POST", body: JSON.stringify(payload) });
  await refreshState();
}

async function saveEngineControls() {
  const toggles = window._engineToggles || { ict_enabled: true, iceberg_enabled: true, gann_enabled: true, astro_enabled: true };
  const payload = {
    ict_enabled: Boolean(toggles.ict_enabled),
    iceberg_enabled: Boolean(toggles.iceberg_enabled),
    gann_enabled: Boolean(toggles.gann_enabled),
    astro_enabled: Boolean(toggles.astro_enabled),
    confluence_threshold: Number(document.getElementById("engineConfluence")?.value || 0.5),
    confidence_threshold: Number(document.getElementById("engineConfidence")?.value || 55),
  };
  await adminFetch("/admin/control/engine_controls", { method: "POST", body: JSON.stringify(payload) });
  await refreshState();
}

async function saveExecutionControls() {
  const payload = {
    spread_max_limit: Number(document.getElementById("execSpread")?.value || 2.5),
    slippage_tolerance: Number(document.getElementById("execSlippage")?.value || 0.5),
    cooldown_seconds: Number(document.getElementById("execCooldown")?.value || 300),
    max_trades_per_day: Number(document.getElementById("execMaxTrades")?.value || 20),
    max_concurrent_trades: Number(document.getElementById("execMaxConcurrent")?.value || 2),
    execution_timeout_seconds: Number(document.getElementById("execTimeout")?.value || 10),
  };
  await adminFetch("/admin/control/execution_controls", { method: "POST", body: JSON.stringify(payload) });
  await refreshState();
}

async function saveRiskLimits() {
  const payload = {
    max_lot_size: Number(document.getElementById("riskMaxLot")?.value || 10),
    max_risk_per_trade: Number(document.getElementById("riskPerTrade")?.value || 1),
    daily_max_trades: Number(document.getElementById("riskDailyMaxTrades")?.value || 20),
    risk_multiplier_phase1: Number(document.getElementById("riskMultP1")?.value || 1),
    risk_multiplier_phase2: Number(document.getElementById("riskMultP2")?.value || 1),
    risk_multiplier_funded: Number(document.getElementById("riskMultFunded")?.value || 1),
  };
  await adminFetch("/admin/control/risk_limits", { method: "POST", body: JSON.stringify(payload) });
  await refreshState();
}

async function setSymbol(enabled) {
  const symbol = (document.getElementById("symbolName")?.value || "").toUpperCase();
  if (!symbol) return;
  await adminFetch("/admin/control/symbols", { method: "POST", body: JSON.stringify({ symbol, enabled: Boolean(enabled) }) });
  await refreshState();
}

async function loadAudit(path) {
  const res = await adminFetch(path);
  if (!res.ok) return;
  const data = await res.json();
  setText("auditList", JSON.stringify(data?.items || [], null, 2));
}

function bind() {
  const tokenEl = document.getElementById("adminToken");
  const roleEl = document.getElementById("adminRole");
  const userEl = document.getElementById("adminUser");
  if (tokenEl) {
    const savedToken = localStorage.getItem("AQ_ADMIN_TOKEN");
    tokenEl.value = (savedToken && savedToken !== "dev-admin-token") ? savedToken : "aq-admin-token-20260329";
  }
  if (roleEl) roleEl.value = localStorage.getItem("AQ_ADMIN_ROLE") || "ADMIN";
  if (userEl) userEl.value = localStorage.getItem("AQ_ADMIN_USER") || "admin";

  document.getElementById("saveCredsBtn")?.addEventListener("click", () => {
    localStorage.setItem("AQ_ADMIN_TOKEN", tokenEl?.value || "aq-admin-token-20260329");
    localStorage.setItem("AQ_ADMIN_ROLE", roleEl?.value || "ADMIN");
    localStorage.setItem("AQ_ADMIN_USER", userEl?.value || "admin");
  });

  document.getElementById("refreshStateBtn")?.addEventListener("click", () => refreshState().catch(() => {}));

  document.getElementById("userAutoOnBtn")?.addEventListener("click", () => saveUser(true, false).catch(() => {}));
  document.getElementById("userAutoOffBtn")?.addEventListener("click", () => saveUser(false, false).catch(() => {}));
  document.getElementById("userBanBtn")?.addEventListener("click", () => banUser(true).catch(() => {}));
  document.getElementById("userUnbanBtn")?.addEventListener("click", () => banUser(false).catch(() => {}));

  document.getElementById("savePropBtn")?.addEventListener("click", () => savePropRules().catch(() => {}));
  document.getElementById("saveEngineBtn")?.addEventListener("click", () => saveEngineControls().catch(() => {}));
  document.getElementById("saveExecBtn")?.addEventListener("click", () => saveExecutionControls().catch(() => {}));
  document.getElementById("saveRiskBtn")?.addEventListener("click", () => saveRiskLimits().catch(() => {}));

  document.getElementById("ictToggleBtn")?.addEventListener("click", () => {
    window._engineToggles = window._engineToggles || {};
    window._engineToggles.ict_enabled = !window._engineToggles.ict_enabled;
  });
  document.getElementById("icebergToggleBtn")?.addEventListener("click", () => {
    window._engineToggles = window._engineToggles || {};
    window._engineToggles.iceberg_enabled = !window._engineToggles.iceberg_enabled;
  });
  document.getElementById("gannToggleBtn")?.addEventListener("click", () => {
    window._engineToggles = window._engineToggles || {};
    window._engineToggles.gann_enabled = !window._engineToggles.gann_enabled;
  });
  document.getElementById("astroToggleBtn")?.addEventListener("click", () => {
    window._engineToggles = window._engineToggles || {};
    window._engineToggles.astro_enabled = !window._engineToggles.astro_enabled;
  });

  document.getElementById("symbolEnableBtn")?.addEventListener("click", () => setSymbol(true).catch(() => {}));
  document.getElementById("symbolDisableBtn")?.addEventListener("click", () => setSymbol(false).catch(() => {}));

  document.getElementById("loadAuditBtn")?.addEventListener("click", () => loadAudit("/admin/control/audit?limit=100").catch(() => {}));
  document.getElementById("loadRiskBtn")?.addEventListener("click", () => loadAudit("/admin/control/risk_violations?limit=100").catch(() => {}));
  document.getElementById("loadRejectedBtn")?.addEventListener("click", () => loadAudit("/admin/control/rejected_trades?limit=100").catch(() => {}));
  document.getElementById("applyDynamicPropBtn")?.addEventListener("click", () => applyDynamicPropEngine().catch(() => {}));

  Array.from(document.querySelectorAll(".preset-acct-btn")).forEach((btn) => {
    btn.addEventListener("click", () => useAccountPreset(btn.dataset.account).catch(() => {}));
  });
}

bind();
refreshState().catch(() => {});
