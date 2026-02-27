let currentSymbol = "GC.FUT";
let currentTF = "5m";
let autoMode = false;
let emergencyStopped = false;
let modelOverridePostPathCache = null;
let modelOverrideStatusPathCache = null;

window.API_BASE = `${window.location.protocol}//${window.location.hostname}:8000`;

function getAdminApiKey() {
    const fromWindow = typeof window.ADMIN_API_KEY === "string" ? window.ADMIN_API_KEY.trim() : "";
    if (fromWindow) return fromWindow;

    try {
        const fromStorage = window.localStorage.getItem("aq.adminKey");
        return typeof fromStorage === "string" ? fromStorage.trim() : "";
    } catch {
        return "";
    }
}

window.setAdminApiKey = function setAdminApiKey(value) {
    const key = String(value || "").trim();
    try {
        if (key) {
            window.localStorage.setItem("aq.adminKey", key);
        } else {
            window.localStorage.removeItem("aq.adminKey");
        }
    } catch (error) {
        console.warn("Unable to update admin key in localStorage:", error.message);
    }
};

window.apiFetchJson = async function(path, options = {}) {
    const headers = new Headers(options.headers || {});
    const adminApiKey = getAdminApiKey();
    if (adminApiKey) {
        headers.set("X-Admin-Key", adminApiKey);
    }

    const response = await fetch(`${window.API_BASE}${path}`, {
        ...options,
        headers,
    });
    if (!response.ok) {
        const text = await response.text();
        throw new Error(`API ${path} failed: ${response.status} ${text.slice(0, 120)}`);
    }
    return response.json();
};

window.formatTableTime = function(value) {
    if (!value) return "--";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return String(value);

    const hh = String(date.getUTCHours()).padStart(2, "0");
    const mm = String(date.getUTCMinutes()).padStart(2, "0");
    const ss = String(date.getUTCSeconds()).padStart(2, "0");
    return `<span title="${date.toISOString()}">${hh}:${mm}:${ss} UTC</span>`;
};

function setButtonActive(buttonId, active) {
    const button = document.getElementById(buttonId);
    if (!button) return;
    button.classList.toggle("is-active", !!active);
}

function safeCell(value, fallback = "--") {
    return value === null || value === undefined || value === "" ? fallback : value;
}

function stateBadge(text, kind = "neutral") {
    return `<span class="engine-state-badge is-${kind}">${text}</span>`;
}

function statusBadge(status) {
    const normalized = String(status || "--").toUpperCase();
    if (normalized === "ACTIVE") return stateBadge(normalized, "active");
    if (normalized === "ERROR") return stateBadge(normalized, "error");
    return stateBadge(normalized, "monitor");
}

function scoreGapBadge(value) {
    if (value === null || value === undefined || value === "--") {
        return stateBadge("--", "neutral");
    }

    const numeric = Number(value);
    if (Number.isNaN(numeric)) {
        return stateBadge(String(value), "neutral");
    }

    const pct = `${numeric.toFixed(2)}%`;
    if (numeric <= 8) return stateBadge(pct, "active");
    if (numeric <= 15) return stateBadge(pct, "monitor");
    return stateBadge(pct, "neutral");
}

function rolloverBadge(status) {
    const normalized = String(status || "--").toUpperCase();
    if (normalized === "WEEK") return stateBadge("ROLLOVER", "error");
    if (normalized === "NORMAL") return stateBadge("NORMAL", "active");
    return stateBadge("--", "neutral");
}

function dataFreshBadge(isFresh, ageSeconds, maxStalenessSeconds) {
    const threshold = Number(maxStalenessSeconds);
    const thresholdText = Number.isFinite(threshold) ? `${Math.round(threshold)}s` : "--";

    if (isFresh === true) {
        const age = Number(ageSeconds);
        const ageText = Number.isFinite(age) ? `${Math.round(age)}s` : "--";
        return stateBadge(`LIVE ${ageText}/${thresholdText}`, "active");
    }
    if (isFresh === false) {
        const age = Number(ageSeconds);
        const ageText = Number.isFinite(age) ? `${Math.round(age)}s` : "--";
        return stateBadge(`STALE ${ageText}/${thresholdText}`, "error");
    }
    return stateBadge("--", "neutral");
}

function blockedReasonBadge(reason) {
    const text = safeCell(reason);
    const normalized = String(text).toLowerCase();

    if (normalized.includes("stale data")) {
        return stateBadge(text, "error");
    }
    if (normalized.includes("timeout")) {
        return stateBadge(text, "monitor");
    }
    if (normalized === "--") {
        return stateBadge("--", "active");
    }
    return stateBadge(text, "neutral");
}

document.getElementById("autoToggle")?.addEventListener("click", async () => {
    const btn = document.getElementById("autoToggle");
    if (!btn) return;

    autoMode = !autoMode;
    btn.innerText = autoMode ? "AUTO: ON" : "AUTO: OFF";
    setButtonActive("autoToggle", autoMode);

    try {
        if (autoMode) {
            await window.apiFetchJson("/auto-trading/start", { method: "POST" });
        } else {
            await window.apiFetchJson("/auto-trading/stop", { method: "POST" });
        }
    } catch (error) {
        autoMode = !autoMode;
        btn.innerText = autoMode ? "AUTO: ON" : "AUTO: OFF";
        setButtonActive("autoToggle", autoMode);
        console.error("Auto trading toggle failed:", error.message);
    }
});

document.getElementById("emergencyBtn")?.addEventListener("click", async () => {
    try {
        if (!emergencyStopped) {
            await window.apiFetchJson("/emergency/stop");
            emergencyStopped = true;
            document.getElementById("emergencyBtn").innerText = "RESUME TRADING";
            setButtonActive("emergencyBtn", true);
        } else {
            await window.apiFetchJson("/emergency/start");
            emergencyStopped = false;
            document.getElementById("emergencyBtn").innerText = "EMERGENCY STOP";
            setButtonActive("emergencyBtn", false);
        }
    } catch (error) {
        console.error("Emergency control failed:", error.message);
    }
});

document.getElementById("manualTradeBtn")?.addEventListener("click", () => {
    (async () => {
        const symbol = String(window.chartState?.symbol || currentSymbol || "XAUUSD").trim();
        const directionInput = window.prompt(`Manual trade direction for ${symbol} (BUY/SELL):`, "BUY");
        if (directionInput === null) return;

        const direction = String(directionInput).trim().toUpperCase();
        if (!["BUY", "SELL"].includes(direction)) {
            window.alert("Direction must be BUY or SELL");
            return;
        }

        try {
            const payload = {
                symbol,
                direction,
                confidence: 75,
                risk_percent: 0.2,
                allow_concurrent: false,
            };
            const result = await window.apiFetchJson("/manual-trade", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload),
            });
            window.alert(`Manual trade ${result.status}: ${result.symbol} ${result.direction}`);
        } catch (error) {
            console.error("Manual trade failed:", error.message);
            window.alert(`Manual trade failed: ${error.message}`);
        }
    })();
});

document.getElementById("alertBtn")?.addEventListener("click", () => {
    (async () => {
        const message = window.prompt("Broadcast alert message:", "Manual operator check-in");
        if (message === null) return;
        const trimmed = String(message).trim();
        if (!trimmed) {
            window.alert("Alert message cannot be empty");
            return;
        }

        try {
            const result = await window.apiFetchJson("/alerts/broadcast", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ message: trimmed, severity: "INFO" }),
            });
            window.alert(`Alert ${result.status} (${result.severity})`);
        } catch (error) {
            console.error("Alert broadcast failed:", error.message);
            window.alert(`Alert failed: ${error.message}`);
        }
    })();
});

document.getElementById("modelOverrideBtn")?.addEventListener("click", () => {
    (async () => {
        const button = document.getElementById("modelOverrideBtn");
        if (!button) return;

        const currentMode = String(button.dataset.mode || "NORMAL").toUpperCase();
        const cycle = ["SAFE", "NORMAL", "AGGRESSIVE"];
        const index = cycle.indexOf(currentMode);
        const nextMode = cycle[(index + 1 + cycle.length) % cycle.length];

        try {
            const body = JSON.stringify({ mode: nextMode });
            let result = null;
            let lastError = null;

            const candidatePaths = modelOverridePostPathCache
                ? [modelOverridePostPathCache]
                : ["/model-override", "/admin/model-override"];

            for (const path of candidatePaths) {
                try {
                    result = await window.apiFetchJson(path, {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body,
                    });
                    modelOverridePostPathCache = path;
                    break;
                } catch (error) {
                    lastError = error;
                }
            }

            if (!result) {
                throw lastError || new Error("model override endpoint unavailable");
            }

            button.dataset.mode = result.mode;
            button.innerText = `Override: ${result.mode}`;
        } catch (error) {
            console.error("Model override failed:", error.message);
            window.alert(`Model override failed: ${error.message}`);
        }
    })();
});

async function refreshModelOverrideStatus() {
    const button = document.getElementById("modelOverrideBtn");
    if (!button) return;

    try {
        let result = null;
        let lastError = null;

        const candidatePaths = modelOverrideStatusPathCache
            ? [modelOverrideStatusPathCache]
            : ["/model-override/status", "/admin/model-override/status"];

        for (const path of candidatePaths) {
            try {
                result = await window.apiFetchJson(path);
                modelOverrideStatusPathCache = path;
                break;
            } catch (error) {
                lastError = error;
            }
        }

        if (!result) {
            throw lastError || new Error("model override status endpoint unavailable");
        }

        const mode = String(result.mode || "NORMAL").toUpperCase();
        button.dataset.mode = mode;
        button.innerText = `Override: ${mode}`;
    } catch (error) {
        button.dataset.mode = "NORMAL";
        button.innerText = "Override";
        console.error("Model override status load failed:", error.message);
    }
}

async function loadEngines() {
    try {
        const data = await window.apiFetchJson("/engines");
        const tbody = document.querySelector("#engineTable tbody");
        if (!tbody) return;
        tbody.innerHTML = "";
        data.sort((first, second) => (second.confidence || 0) - (first.confidence || 0));
        data.forEach((engine, index) => {
            const row = `<tr${index % 2 === 0 ? ' class="even"' : ''}>
                <td>${window.formatTableTime(engine.time)}</td>
                <td>${engine.symbol ?? '--'}</td>
                <td>${statusBadge(engine.status)}</td>
                <td>${engine.model ?? '--'}</td>
                <td>${engine.confidence ?? '--'}</td>
                <td>${safeCell(engine.top_signals)}</td>
                <td>${safeCell(engine.ai_score)}</td>
                <td>${safeCell(engine.chosen_model)}</td>
                <td>${blockedReasonBadge(engine.reason_blocked)}</td>
                <td>${safeCell(engine.active_model)} ${safeCell(engine.active_direction) !== '--' ? stateBadge(engine.active_direction, String(engine.active_direction).toUpperCase() === 'BUY' ? 'active' : 'error') : ''}</td>
                <td>${scoreGapBadge(engine.score_gap)}</td>
                <td>${stateBadge(safeCell(engine.concurrent_slots), "monitor")}</td>
                <td>${dataFreshBadge(engine.data_fresh, engine.data_age_seconds, engine.max_staleness_seconds)}</td>
                <td>${rolloverBadge(engine.rollover_status)}</td>
                <td>${safeCell(engine.rollover_contract)}</td>
                <td>${engine.spread ?? '--'}</td>
                <td>${engine.pnl ?? '--'}</td>
            </tr>`;
            tbody.innerHTML += row;
        });
    } catch (error) {
        console.error("Engine table load failed:", error.message);
    }
}

setInterval(loadEngines, 5000);
loadEngines();

function bindPanelToggle(toggleId, panelId, closeId) {
    document.getElementById(toggleId)?.addEventListener("click", () => {
        const panel = document.getElementById(panelId);
        if (!panel) return;
        const showPanel = panel.style.display === "none";
        panel.style.display = showPanel ? "block" : "none";
        setButtonActive(toggleId, showPanel);
    });

    document.getElementById(closeId)?.addEventListener("click", () => {
        const panel = document.getElementById(panelId);
        if (!panel) return;
        panel.style.display = "none";
        setButtonActive(toggleId, false);
    });
}

bindPanelToggle("enginesToggleBtn", "enginePanel", "enginePanelClose");
bindPanelToggle("journalToggleBtn", "journalTablePanel", "journalTableClose");
bindPanelToggle("icebergToggleBtn", "icebergPanel", "icebergPanelClose");
bindPanelToggle("orderflowToggleBtn", "orderflowPanel", "orderflowPanelClose");
bindPanelToggle("ladderToggleBtn", "ladderPanel", "ladderPanelClose");
bindPanelToggle("timeSalesToggleBtn", "timeSalesPanel", "timeSalesPanelClose");
bindPanelToggle("cycleToggleBtn", "cyclePanel", "cyclePanelClose");
bindPanelToggle("liquidityToggleBtn", "liquidityPanel", "liquidityPanelClose");

function hideFloatingPanelsForSmallScreens() {
    if (window.innerWidth > 1400) return;

    [
        ["enginesToggleBtn", "enginePanel"],
        ["journalToggleBtn", "journalTablePanel"],
        ["icebergToggleBtn", "icebergPanel"],
        ["orderflowToggleBtn", "orderflowPanel"],
        ["ladderToggleBtn", "ladderPanel"],
        ["timeSalesToggleBtn", "timeSalesPanel"],
        ["cycleToggleBtn", "cyclePanel"],
        ["liquidityToggleBtn", "liquidityPanel"]
    ].forEach(([toggleId, panelId]) => {
        const panel = document.getElementById(panelId);
        if (!panel) return;
        panel.style.display = "none";
        setButtonActive(toggleId, false);
    });
}

window.addEventListener("resize", hideFloatingPanelsForSmallScreens);
hideFloatingPanelsForSmallScreens();

document.getElementById("checkGuards")?.addEventListener("click", async () => {
    try {
        const [health, execution, telegram, clawbot] = await Promise.all([
            window.apiFetchJson("/engine/health"),
            window.apiFetchJson("/execution/status"),
            window.apiFetchJson("/telegram/status"),
            window.apiFetchJson("/clawbot/status")
        ]);
        const guardsEl = document.getElementById("guardsStatus");
        if (!guardsEl) return;
        guardsEl.innerHTML = `
            <div>Execution: ${execution.browser_connected ? "OK" : "Not Connected"}</div>
            <div>Telegram: ${telegram.active ? "Online" : "Offline"}</div>
            <div>Clawbot: ${clawbot.active ? "Active" : "Inactive"}</div>
            <div>CPU: ${health.cpu}% | RAM: ${health.ram}%</div>
        `;
    } catch (error) {
        console.error("Guard check failed:", error.message);
    }
});

async function refreshTopbarMetrics() {
    try {
        const prop = await window.apiFetchJson("/prop/status");
        document.getElementById("balance").innerText = Number(prop.balance || 0).toFixed(2);
        document.getElementById("dailyLoss").innerText = prop.daily_loss ?? "0.00";
        if (prop.phase) {
            document.getElementById("phaseDisplay").innerText = prop.phase;
        }
    } catch (error) {
        console.error("Topbar metrics refresh failed:", error.message);
    }
}

setInterval(refreshTopbarMetrics, 5000);
refreshTopbarMetrics();
setInterval(refreshModelOverrideStatus, 10000);
refreshModelOverrideStatus();

async function refreshRolloverWatch() {
    const statusEl = document.getElementById("rolloverStatus");
    if (!statusEl) return;

    const activeSymbol = window.chartState?.symbol || currentSymbol || "GC.FUT";
    try {
        const data = await window.apiFetchJson(`/futures/rollover-status?symbol=${encodeURIComponent(activeSymbol)}`);
        statusEl.classList.remove("status-red", "status-green");

        if (data.rollover_detected || data.rollover_week) {
            statusEl.classList.add("status-red");
            statusEl.textContent = `Rollover Week: ACTIVE | ${data.current_front} → ${data.next_contract} | ratio ${Number(data.volume_ratio || 0).toFixed(2)}`;
            return;
        }

        if (data.rollover_imminent) {
            statusEl.classList.add("status-red");
            statusEl.textContent = `Rollover Watch: IMMINENT | ${data.current_front} → ${data.next_contract} | ratio ${Number(data.volume_ratio || 0).toFixed(2)}`;
            return;
        }

        statusEl.classList.add("status-green");
        statusEl.textContent = `Rollover: NORMAL | Active ${data.active_contract || '--'} | ratio ${Number(data.volume_ratio || 0).toFixed(2)}`;
    } catch (error) {
        statusEl.classList.remove("status-green");
        statusEl.classList.add("status-red");
        statusEl.textContent = `Rollover status unavailable`;
        console.error("Rollover watch refresh failed:", error.message);
    }
}

setInterval(refreshRolloverWatch, 8000);
refreshRolloverWatch();

let brokerFeedSocket = null;
let brokerFeedSocketTimer = null;

function setBrokerStatus(feedData, brainData) {
    const feedEl = document.getElementById("brokerFeedStatus");
    const priceEl = document.getElementById("brokerPriceStatus");
    const brainEl = document.getElementById("brokerBrainStatus");
    const bannerEl = document.getElementById("brokerKillBanner");
    if (!feedEl || !priceEl || !brainEl) return;

    const health = (feedData || {}).health || {};
    const price = (feedData || {}).price || {};
    const reasons = Array.isArray(health.reasons) ? health.reasons.join(", ") : "--";

    feedEl.classList.remove("status-green", "status-red");
    if (health.kill_switch) {
        feedEl.classList.add("status-red");
        feedEl.textContent = `Feed: BLOCKED (${reasons})`;
        if (bannerEl) {
            bannerEl.style.display = "block";
            bannerEl.textContent = `BROKER KILL SWITCH ACTIVE • ${reasons}`;
        }
    } else {
        feedEl.classList.add("status-green");
        feedEl.textContent = "Feed: LIVE";
        if (bannerEl) {
            bannerEl.style.display = "none";
            bannerEl.textContent = "BROKER KILL SWITCH ACTIVE";
        }
    }

    const bid = price.bid ?? "--";
    const ask = price.ask ?? "--";
    const spread = price.spread ?? "--";
    priceEl.textContent = `Bid/Ask: ${bid} / ${ask} | Spr: ${spread}`;

    const symbols = ((brainData || {}).symbols) || {};
    const symbolKeys = Object.keys(symbols);
    const latestSymbol = symbolKeys.length ? symbolKeys[0] : null;
    const latest = latestSymbol ? symbols[latestSymbol] : null;

    brainEl.classList.remove("status-green", "status-red");
    if (latest && latest.last_decision === "ALLOW") {
        brainEl.classList.add("status-green");
        brainEl.textContent = `Adaptation: ${latestSymbol} ${latest.last_decision}`;
    } else if (latest) {
        brainEl.classList.add("status-red");
        brainEl.textContent = `Adaptation: ${latestSymbol} ${latest.last_decision} (${latest.last_reason || '--'})`;
    } else {
        brainEl.classList.add("status-red");
        brainEl.textContent = "Adaptation: --";
    }
}

async function refreshBrokerStatusFallback() {
    try {
        const [feed, brain] = await Promise.all([
            window.apiFetchJson("/broker-feed/status"),
            window.apiFetchJson("/broker-brain/status")
        ]);
        setBrokerStatus(feed, brain);
    } catch (error) {
        const feedEl = document.getElementById("brokerFeedStatus");
        const brainEl = document.getElementById("brokerBrainStatus");
        const bannerEl = document.getElementById("brokerKillBanner");
        if (feedEl) {
            feedEl.classList.remove("status-green");
            feedEl.classList.add("status-red");
            feedEl.textContent = "Feed: Unavailable";
        }
        if (brainEl) {
            brainEl.classList.remove("status-green");
            brainEl.classList.add("status-red");
            brainEl.textContent = "Adaptation: Unavailable";
        }
        if (bannerEl) {
            bannerEl.style.display = "block";
            bannerEl.textContent = "BROKER KILL SWITCH ACTIVE • Feed unavailable";
        }
        console.error("Broker status fallback failed:", error.message);
    }
}

function connectBrokerFeedSocket() {
    if (brokerFeedSocket) {
        try { brokerFeedSocket.close(); } catch {}
        brokerFeedSocket = null;
    }

    const protocol = window.location.protocol === "https:" ? "wss" : "ws";
    const url = `${protocol}://${window.location.hostname}:8000/ws/broker-feed?interval=1`;
    brokerFeedSocket = new WebSocket(url);

    brokerFeedSocket.onmessage = (event) => {
        try {
            const payload = JSON.parse(event.data || "{}");
            if (payload.type !== "broker_feed_tick") return;
            setBrokerStatus(payload.broker_feed, payload.broker_brain);
        } catch (error) {
            console.error("Broker WS parse error:", error.message);
        }
    };

    brokerFeedSocket.onerror = () => {
        refreshBrokerStatusFallback();
    };

    brokerFeedSocket.onclose = () => {
        refreshBrokerStatusFallback();
        if (brokerFeedSocketTimer) clearTimeout(brokerFeedSocketTimer);
        brokerFeedSocketTimer = setTimeout(connectBrokerFeedSocket, 5000);
    };
}

connectBrokerFeedSocket();
setInterval(refreshBrokerStatusFallback, 15000);
refreshBrokerStatusFallback();

document.getElementById("guardsPanel")?.style.setProperty("display", "block");
