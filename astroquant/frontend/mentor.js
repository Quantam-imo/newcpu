const MENTOR_STATE_KEY = "aq_mentor_drawer_open";
const MENTOR_WIDTH_KEY = "aq_mentor_drawer_width";
const MENTOR_SECTIONS_KEY = "aq_mentor_sections";
const AQ_DEFAULT_MENTOR_API_ORIGIN = "http://127.0.0.1:8001";

function resolveMentorApiBase() {
    const normalized = AQ_DEFAULT_MENTOR_API_ORIGIN;
    window.AQ_API_BASE = normalized;
    return normalized;
}

const mentorFetch = async (path, options) => {
    const primary = `${resolveMentorApiBase()}${path}`;
    const backup = `http://127.0.0.1:8000${path}`;
    for (const target of [primary, backup]) {
        try {
            return await fetch(target, options);
        } catch (error) {
            console.warn("mentorFetch failed", target, error);
        }
    }
    return new Response(
        JSON.stringify({ status: "error", message: "fetch failed" }),
        { status: 599, headers: { "Content-Type": "application/json" } },
    );
};
let mentorLoadedOnce = false;

function selectedMentorSymbol() {
    const select = document.getElementById("chartSymbol");
    return select ? select.value : "GC.FUT";
}

function setMentorMeta(text) {
    const el = document.getElementById("mentorMeta");
    if (el) el.innerText = text;
}

function formatMentorValue(value) {
    if (value === null || value === undefined || value === "") return "--";
    if (Array.isArray(value)) return value.length ? value.join(", ") : "--";
    if (typeof value === "object") {
        try {
            return JSON.stringify(value);
        } catch (_) {
            return "--";
        }
    }
    return String(value);
}

function row(label, value) {
    return `<div><span>${label}</span><strong>${formatMentorValue(value)}</strong></div>`;
}

function mentorTag(text, cls) {
    const safeText = formatMentorValue(text);
    const safeCls = cls ? ` ${cls}` : "";
    return `<span class="mentor-tag${safeCls}">${safeText}</span>`;
}

function biasTag(value) {
    const v = String(value || "").toUpperCase();
    if (v.includes("BULL") || v === "UP") return mentorTag(value || "BULLISH", "bull");
    if (v.includes("BEAR") || v === "DOWN") return mentorTag(value || "BEARISH", "bear");
    return mentorTag(value || "NEUTRAL", "neutral");
}

function riskTag(value) {
    const n = Number(value);
    if (!Number.isFinite(n)) return mentorTag(value || "--", "neutral");
    if (n <= 0.5) return mentorTag(`${n}%`, "risk-low");
    if (n <= 1.0) return mentorTag(`${n}%`, "risk-med");
    return mentorTag(`${n}%`, "risk-high");
}

function newsTag(value) {
    const v = String(value || "").toUpperCase();
    if (v.includes("HALT") || v.includes("HIGH")) return mentorTag(value || "HALT", "bear");
    if (v.includes("NORMAL") || v.includes("CLEAR")) return mentorTag(value || "NORMAL", "bull");
    return mentorTag(value || "--", "neutral");
}

function sessionTag(value) {
    const v = String(value || "").toUpperCase();
    if (v.includes("NEWYORK") || v.includes("LONDON") || v.includes("ASIA")) {
        return mentorTag(value || "--", "neutral");
    }
    return mentorTag(value || "--", "neutral");
}

function section(id, title, body, isOpen = true) {
    return `
        <details class="mentor-section" data-section-id="${id}" ${isOpen ? "open" : ""}>
            <summary>${title}</summary>
            <div class="mentor-content">${body}</div>
        </details>
    `;
}

function getCurrentSectionState() {
    const content = document.getElementById("mentorContent");
    const state = {};
    if (!content) return state;
    for (const details of content.querySelectorAll("details[data-section-id]")) {
        state[details.dataset.sectionId] = details.open;
    }
    return state;
}

function openMentorSection(sectionId) {
    if (!sectionId) return;
    const state = {
        ...(JSON.parse(localStorage.getItem(MENTOR_SECTIONS_KEY) || "{}") || {}),
        [sectionId]: true,
    };
    localStorage.setItem(MENTOR_SECTIONS_KEY, JSON.stringify(state));
    const content = document.getElementById("mentorContent");
    const node = content ? content.querySelector(`details[data-section-id="${sectionId}"]`) : null;
    if (node) {
        node.open = true;
        node.scrollIntoView({ behavior: "smooth", block: "start" });
    }
}

function renderMentorSkeleton(message = "Loading mentor modules...") {
    const content = document.getElementById("mentorContent");
    if (!content) return;
    content.innerHTML = `
        ${section("market", "1) Market Context", row("Status", message), true)}
        ${section("model", "2) Active Model", row("Status", message), true)}
        ${section("iceberg", "3) Iceberg Narrative", row("Status", message), true)}
        ${section("gann", "4) Gann Framework", row("Status", message), true)}
        ${section("astro", "5) Astro Timing", row("Status", message), true)}
        ${section("risk", "6) Risk Context", row("Status", message), true)}
        ${section("exit", "7) Exit Reason", row("Status", message), true)}
    `;
}

function renderMentorContext(data, sectionOverrides = null) {
    const content = document.getElementById("mentorContent");
    if (!content) return;

    const savedSections = sectionOverrides || JSON.parse(localStorage.getItem(MENTOR_SECTIONS_KEY) || "{}");
    const market = data.market || {};
    const model = data.model || {};
    const risk = data.risk || {};
    const iceberg = data.iceberg || null;
    const exitData = data.exit || {};
    const audit = data.prop_audit || {};
    const controls = data.controls || {};
    const gann = Array.isArray(data.gann) ? data.gann : [];
    const astro = Array.isArray(data.astro) ? data.astro : [];

    const concept = {
        market: {
            symbol: market.symbol || selectedMentorSymbol(),
            canonical_symbol: market.canonical_symbol || "--",
            pricing_source: market.pricing_source || "--",
            spot_fidelity: market.spot_fidelity || {},
            htf_bias: market.htf_bias || "--",
            ltf_structure: market.ltf_structure || "--",
            session: market.session || "--",
            volatility: market.volatility || "--",
            news_state: market.news_state || "--",
        },
        model: {
            active_model: model.active_model || "--",
            confidence: model.confidence != null ? model.confidence : "--",
            reason: model.reason || "--",
            entry_logic: model.entry_logic || "--",
            invalid_if: model.invalid_if || "--",
            rr: model.rr || "--",
        },
        risk: {
            phase: risk.phase || "--",
            risk_percent: risk.risk_percent != null ? risk.risk_percent : "--",
            static_floor: risk.static_floor != null ? risk.static_floor : "--",
            daily_buffer: risk.daily_buffer != null ? risk.daily_buffer : "--",
            cooldown: risk.cooldown || "--",
        },
        exit: {
            last_result: exitData.last_result || "--",
            reason: exitData.reason || "--",
        },
        audit: {
            profitable_days_completed: audit.profitable_days_completed != null ? audit.profitable_days_completed : "--",
            target_left: audit.target_left != null ? audit.target_left : "--",
            drawdown_remaining: audit.drawdown_remaining != null ? audit.drawdown_remaining : "--",
        },
        controls: {
            aggressive_mode: Boolean(controls.aggressive_mode),
            disabled_models: Array.isArray(controls.disabled_models) ? controls.disabled_models : [],
        },
    };

    const marketBody = [
        row("Selected Symbol", concept.market.symbol),
        row("Canonical Symbol", concept.market.canonical_symbol),
        row("Pricing Source", concept.market.pricing_source),
        row("Spot Fidelity", (concept.market.spot_fidelity && concept.market.spot_fidelity.spot_primary) ? ((concept.market.spot_fidelity.strict ? "STRICT" : "ON") + (concept.market.spot_fidelity.spot_data_available ? " | SPOT LIVE" : " | SPOT MISSING")) : "OFF"),
        row("HTF Bias", biasTag(concept.market.htf_bias)),
        row("LTF Structure", biasTag(concept.market.ltf_structure)),
        row("Session", sessionTag(concept.market.session)),
        row("Volatility", concept.market.volatility),
        row("News State", newsTag(concept.market.news_state)),
    ].join("");

    const modelBody = [
        row("Active Model", concept.model.active_model),
        row("Confidence %", concept.model.confidence),
        row("Reason", concept.model.reason),
        row("Entry Logic", concept.model.entry_logic),
        row("Invalid If", concept.model.invalid_if),
        row("R:R Planned", concept.model.rr),
    ].join("");

    const riskBody = [
        row("Phase", concept.risk.phase),
        row("Risk %", riskTag(concept.risk.risk_percent)),
        row("Static Floor", concept.risk.static_floor),
        row("Daily Buffer Left", concept.risk.daily_buffer),
        row("Cooldown", concept.risk.cooldown),
    ].join("");

    const gannBody = gann.length
        ? gann.slice(0, 8).map((line, idx) => {
            return row(line.label || `Level ${idx + 1}`, line.price != null ? Number(line.price).toFixed(2) : "--");
        }).join("")
        : row("Status", "No Gann levels available");

    const astroBody = astro.length
        ? astro.slice(0, 8).map((marker, idx) => {
            const t = Number(marker.time || 0);
            const ts = Number.isFinite(t) && t > 0 ? new Date(t * 1000).toLocaleString() : "--";
            return row(marker.label || `Event ${idx + 1}`, ts);
        }).join("")
        : row("Status", "No Astro markers available");

    const icebergBody = iceberg
        ? [
            row("Absorption", iceberg.absorption || "YES"),
            row("Price", iceberg.price),
            row("Strength", iceberg.strength),
            row("Institutional Bias", iceberg.bias),
        ].join("")
        : row("Status", "No iceberg absorption detected");

    const exitBody = [
        row("Last Result", concept.exit.last_result),
        row("Exit Reason", concept.exit.reason),
    ].join("");

    const propBody = [
        row("Profitable Days", concept.audit.profitable_days_completed),
        row("Target Left", concept.audit.target_left),
        row("Drawdown Remaining", concept.audit.drawdown_remaining),
    ].join("");

    const lastTradesRows = (data.last_trades || []).slice(0, 5).map(t => {
        return `<tr><td>${t.time || "--"}</td><td>${t.model || "--"}</td><td>${t.result || "--"}</td><td>${t.r_multiple ?? "--"}</td><td>${t.pnl ?? "--"}</td></tr>`;
    }).join("") || `<tr><td colspan="5">No recent trades</td></tr>`;

    const modelStatsRows = Object.entries(data.model_stats || {}).map(([name, stats]) => {
        return `<tr><td>${name}</td><td>${stats.wins ?? 0}</td><td>${stats.losses ?? 0}</td></tr>`;
    }).join("") || `<tr><td colspan="3">No model stats</td></tr>`;

    content.innerHTML = `
        ${section("market", "1) Market Context", marketBody, savedSections.market !== false)}
        ${section("model", "2) Active Model", modelBody, savedSections.model !== false)}
        ${section("iceberg", "3) Iceberg Narrative", icebergBody, savedSections.iceberg !== false)}
        ${section("gann", "4) Gann Framework", gannBody, savedSections.gann !== false)}
        ${section("astro", "5) Astro Timing", astroBody, savedSections.astro !== false)}
        ${section("risk", "6) Risk Context", riskBody, savedSections.risk !== false)}
        ${section("exit", "7) Exit Reason", exitBody, savedSections.exit !== false)}
        ${section("audit", "Prop Audit", propBody, savedSections.audit !== false)}
        ${section("actions", "Institutional Controls", `
            <div class="mentor-actions">
                <button id="mentorDisableModelBtn">Disable Model</button>
                <button id="mentorReduceRiskBtn">Reduce Risk</button>
                <button id="mentorAggressiveBtn">Aggressive Mode</button>
                <button id="mentorGannBtn">View Gann</button>
                <button id="mentorAstroBtn">View Astro</button>
                <button id="mentorLastTradesBtn">View Last 5 Trades</button>
                <button id="mentorModelStatsBtn">View Model Stats</button>
            </div>
            ${row("Aggressive Mode", concept.controls.aggressive_mode ? "ON" : "OFF")}
            ${row("Disabled Models", (concept.controls.disabled_models || []).join(", ") || "--")}
        `, savedSections.actions !== false)}
        ${section("trades", "Last 5 Trades", `
            <table><thead><tr><th>Time</th><th>Model</th><th>Result</th><th>R</th><th>PnL</th></tr></thead><tbody>${lastTradesRows}</tbody></table>
        `, savedSections.trades !== false)}
        ${section("stats", "Model Stats", `
            <table><thead><tr><th>Model</th><th>Wins</th><th>Losses</th></tr></thead><tbody>${modelStatsRows}</tbody></table>
        `, savedSections.stats !== false)}
    `;

    for (const details of content.querySelectorAll("details[data-section-id]")) {
        details.addEventListener("toggle", () => {
            const state = JSON.parse(localStorage.getItem(MENTOR_SECTIONS_KEY) || "{}");
            state[details.dataset.sectionId] = details.open;
            localStorage.setItem(MENTOR_SECTIONS_KEY, JSON.stringify(state));
        });
    }

    bindMentorActionButtons();
    setMentorMeta(`Updated: ${new Date(data.updated_at || Date.now()).toLocaleString()} | Symbol: ${concept.market.symbol || "--"}`);
}

async function mentorAction(action, payload = {}) {
    const res = await mentorFetch("/mentor/action", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action, ...payload }),
    });
    if (!res.ok) return null;
    return res.json();
}

function bindMentorActionButtons() {
    const disableBtn = document.getElementById("mentorDisableModelBtn");
    if (disableBtn) {
        disableBtn.onclick = async () => {
            const modelName = prompt("Model to disable (e.g. ICT):", "ICT");
            if (!modelName) return;
            await mentorAction("disable_model", { model_name: modelName });
            await loadMentor();
        };
    }

    const reduceRiskBtn = document.getElementById("mentorReduceRiskBtn");
    if (reduceRiskBtn) {
        reduceRiskBtn.onclick = async () => {
            await mentorAction("reduce_risk");
            await loadMentor();
        };
    }

    const aggressiveBtn = document.getElementById("mentorAggressiveBtn");
    if (aggressiveBtn) {
        aggressiveBtn.onclick = async () => {
            const password = prompt("Aggressive mode password:", "");
            if (password == null) return;
            await mentorAction("aggressive_mode", { enabled: true, password });
            await loadMentor();
        };
    }

    const gannBtn = document.getElementById("mentorGannBtn");
    if (gannBtn) {
        gannBtn.onclick = async () => {
            openMentorSection("gann");
        };
    }

    const astroBtn = document.getElementById("mentorAstroBtn");
    if (astroBtn) {
        astroBtn.onclick = async () => {
            openMentorSection("astro");
        };
    }

    const tradesBtn = document.getElementById("mentorLastTradesBtn");
    if (tradesBtn) {
        tradesBtn.onclick = async () => {
            openMentorSection("trades");
            await mentorAction("last_trades", { symbol: selectedMentorSymbol() });
            await loadMentor();
            openMentorSection("trades");
        };
    }

    const statsBtn = document.getElementById("mentorModelStatsBtn");
    if (statsBtn) {
        statsBtn.onclick = async () => {
            openMentorSection("stats");
            await mentorAction("model_stats");
            await loadMentor();
            openMentorSection("stats");
        };
    }
}

async function loadMentor() {
    try {
        const mergedState = {
            ...(JSON.parse(localStorage.getItem(MENTOR_SECTIONS_KEY) || "{}") || {}),
            ...getCurrentSectionState(),
        };
        localStorage.setItem(MENTOR_SECTIONS_KEY, JSON.stringify(mergedState));

        const wrap = document.querySelector("#mentorDrawer .mentor-content-wrap");
        const prevScrollTop = wrap ? wrap.scrollTop : 0;

        if (!mentorLoadedOnce) {
            renderMentorSkeleton();
        } else {
            setMentorMeta("Updating mentor...");
        }

        const symbol = selectedMentorSymbol();
        const res = await mentorFetch(`/mentor/context?symbol=${encodeURIComponent(symbol)}`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        renderMentorContext(data, mergedState);
        mentorLoadedOnce = true;

        if (wrap) {
            const maxScrollTop = Math.max(0, wrap.scrollHeight - wrap.clientHeight);
            wrap.scrollTop = Math.min(prevScrollTop, maxScrollTop);
        }
    } catch (err) {
        renderMentorSkeleton("Mentor data unavailable");
        setMentorMeta(`Mentor unavailable: ${err}`);
    }
}

function toggleMentor(forceOpen) {
    const drawer = document.getElementById("mentorDrawer");
    if (!drawer) return;
    const nextOpen = typeof forceOpen === "boolean" ? forceOpen : !drawer.classList.contains("open");
    drawer.classList.toggle("open", nextOpen);
    localStorage.setItem(MENTOR_STATE_KEY, nextOpen ? "1" : "0");
    if (nextOpen) loadMentor().catch(() => {});
}

function initMentorDrawer() {
    const drawer = document.getElementById("mentorDrawer");
    const refreshBtn = document.getElementById("mentorRefreshBtn");
    const symbolSelect = document.getElementById("chartSymbol");
    if (!drawer) return;

    const savedOpen = localStorage.getItem(MENTOR_STATE_KEY) === "1";
    if (savedOpen) drawer.classList.add("open");

    const savedWidth = Number(localStorage.getItem(MENTOR_WIDTH_KEY) || 420);
    if (Number.isFinite(savedWidth) && savedWidth >= 320 && savedWidth <= 760) {
        drawer.style.width = `${savedWidth}px`;
    }

    if (refreshBtn) refreshBtn.addEventListener("click", () => loadMentor().catch(() => {}));
    if (symbolSelect) symbolSelect.addEventListener("change", () => loadMentor().catch(() => {}));

    const resizer = document.getElementById("mentorResizer");
    if (resizer) {
        let resizing = false;
        resizer.addEventListener("mousedown", () => {
            resizing = true;
            document.body.style.userSelect = "none";
        });
        window.addEventListener("mousemove", ev => {
            if (!resizing) return;
            const width = Math.max(320, Math.min(760, ev.clientX));
            drawer.style.width = `${width}px`;
            localStorage.setItem(MENTOR_WIDTH_KEY, String(width));
        });
        window.addEventListener("mouseup", () => {
            resizing = false;
            document.body.style.userSelect = "";
        });
    }

    renderMentorSkeleton();
    loadMentor().catch(() => {});
    setInterval(() => loadMentor().catch(() => {}), 8000);
}

window.toggleMentor = toggleMentor;
initMentorDrawer();
