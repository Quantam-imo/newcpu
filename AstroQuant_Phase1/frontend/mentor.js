const MENTOR_STATE_KEY = "aq_mentor_drawer_open";
const MENTOR_WIDTH_KEY = "aq_mentor_drawer_width";
const MENTOR_SECTIONS_KEY = "aq_mentor_sections";
const AQ_DEFAULT_MENTOR_API_ORIGIN = "http://127.0.0.1:8000";

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
    if (el) el.innerHTML = text;
}

function fmt(v) {
    if (v === null || v === undefined || v === "") return "--";
    if (typeof v === "number") return Number.isFinite(v) ? String(v) : "--";
    return String(v);
}

function fmtPrice(v) {
    const n = Number(v);
    if (!Number.isFinite(n)) return "--";
    return n.toFixed(2);
}

function row(label, value) {
    const isPrice = /price|last|open|high|low|support|resistance|target|poc|range/i.test(String(label || ""));
    return `<div class="mentor-row"><span>${fmt(label)}</span><strong class="${isPrice ? "mentor-live-price" : ""}">${fmt(value)}</strong></div>`;
}

function section(id, title, body, isOpen = true) {
    return `
        <details class="mentor-section mentor-section-${id}" data-section-id="${id}" ${isOpen ? "open" : ""}>
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

function narrative(title, text) {
    return `<div class="mentor-narrative mentor-tone-neutral"><div class="mentor-narrative-title">${fmt(title)}</div><p>${fmt(text)}</p></div>`;
}

function actionCall(verdict, detail, tone = "neutral") {
    const safeTone = ["bull", "bear", "warn", "neutral"].includes(tone) ? tone : "neutral";
    return `<div class="mentor-action-call mentor-tone-${safeTone}"><strong>${fmt(verdict)}</strong><span>${fmt(detail)}</span></div>`;
}

function normalizeMentorData(raw, symbol) {
    const payload = raw || {};
    if (payload.context && payload.probability) {
        return payload;
    }

    const market = payload.market || {};
    const model = payload.model || {};
    const risk = payload.risk || {};
    const prices = payload.prices || {};
    const iceberg = payload.iceberg || {};
    const summary = payload.orderflow_summary || {};
    const gannRows = Array.isArray(payload.gann) ? payload.gann : [];
    const astroRows = Array.isArray(payload.astro) ? payload.astro : [];

    const support = prices.nearest_support ?? null;
    const resistance = prices.nearest_resistance ?? null;
    const price = prices.last ?? null;
    const confidence = Number(model.confidence);
    const confidenceScore = Number.isFinite(confidence) ? Math.max(0, Math.min(100, confidence)) : 0;
    const signalStrengthRaw = Number(summary.signal_strength);
    const signalStrength = Number.isFinite(signalStrengthRaw) ? Math.max(0, Math.min(100, signalStrengthRaw)) : null;
    const decisionScore = signalStrength ?? confidenceScore;

    let verdict = "Low Probability / Wait";
    const modelReason = String(model.reason || "").toUpperCase();
    if (modelReason.includes("BUY") || modelReason.includes("LONG") || String(market.htf_bias || "").toUpperCase().includes("BULL")) {
        verdict = decisionScore >= 55 ? "Buy Setup" : "Watch Buy";
    } else if (modelReason.includes("SELL") || modelReason.includes("SHORT") || String(market.htf_bias || "").toUpperCase().includes("BEAR")) {
        verdict = decisionScore >= 55 ? "Sell Setup" : "Watch Sell";
    }

    return {
        symbol: market.symbol || symbol,
        context: {
            symbol: market.symbol || symbol,
            price,
            prev_low: prices.low ?? support,
            prev_high: prices.high ?? resistance,
            htf_bias: market.htf_bias,
            ltf_structure: market.ltf_structure,
            kill_zone: market.session,
            volatility: market.volatility,
        },
        liquidity: {
            external_high: resistance,
            external_low: support,
            sweep: summary.absorption_signal || "none",
            target: summary.direction || "--",
        },
        institution: {
            iceberg_buy: summary.absorption_signal === "BUY_ABSORPTION" ? "YES" : "NO",
            iceberg_sell: summary.absorption_signal === "SELL_ABSORPTION" ? "YES" : "NO",
            delta: summary.delta_state || "NEUTRAL",
            poc: price,
        },
        ict: {
            turtle_soup: "--",
            fvg_zone: model.entry_logic || "OFF",
            order_block: model.invalid_if || "OFF",
            liquidity_sweep: summary.absorption_signal || "none",
        },
        gann: {
            cycle: gannRows.length,
            target_100: resistance,
            target_200: support,
        },
        astro: {
            harmonic_window: astroRows.length > 0,
            planet_event: astroRows[0]?.label || "None",
            bias: "Neutral",
        },
        news: {
            next_event: market.news_state || "None",
            impact: market.news_state === "HALT" ? "High" : "Low",
            time: "--",
        },
        session: {
            session: market.session || "--",
            phase: market.ltf_structure || "--",
        },
        probability: {
            score: decisionScore,
            score_source: signalStrength !== null ? "orderflow_signal_strength" : "model_confidence",
            verdict,
        },
        story: summary.narrative || model.reason || "--",
        updated_at: payload.updated_at || new Date().toISOString(),
    };
}

function renderMentorSkeleton(message = "Loading mentor modules...") {
    const content = document.getElementById("mentorContent");
    if (!content) return;
    content.innerHTML = section("market", "AI Mentor", row("Status", message), true);
}

function renderMentorContext(data, sectionOverrides = null) {
    const content = document.getElementById("mentorContent");
    if (!content) return;

    const savedSections = sectionOverrides || JSON.parse(localStorage.getItem(MENTOR_SECTIONS_KEY) || "{}");
    const context = data.context || {};
    const liquidity = data.liquidity || {};
    const institution = data.institution || {};
    const ict = data.ict || {};
    const gann = data.gann || {};
    const astro = data.astro || {};
    const news = data.news || {};
    const session = data.session || {};
    const probability = data.probability || {};

    const marketBody = [
        narrative("HTF → LTF Narrative", `HTF ${fmt(context.htf_bias)}, LTF ${fmt(context.ltf_structure)}, session ${fmt(session.session)} (${fmt(session.phase)}).`),
        row("Symbol", context.symbol || data.symbol || selectedMentorSymbol()),
        row("Price", fmtPrice(context.price)),
        row("Prev Low", fmtPrice(context.prev_low)),
        row("Prev High", fmtPrice(context.prev_high)),
        row("Kill Zone", context.kill_zone),
        row("Volatility", context.volatility),
    ].join("");

    const liquidityBody = [
        narrative("Liquidity Sweep Detection", `Sweep: ${fmt(liquidity.sweep)} | Target: ${fmt(liquidity.target)}`),
        row("External High", fmtPrice(liquidity.external_high)),
        row("External Low", fmtPrice(liquidity.external_low)),
        row("Sweep", liquidity.sweep),
    ].join("");

    const institutionBody = [
        narrative("Institutional Orderflow", `Delta ${fmt(institution.delta)} | Iceberg buy ${fmt(institution.iceberg_buy)} vs sell ${fmt(institution.iceberg_sell)}.`),
        row("Delta", institution.delta),
        row("Iceberg Buy", institution.iceberg_buy),
        row("Iceberg Sell", institution.iceberg_sell),
        row("POC", fmtPrice(institution.poc)),
    ].join("");

    const ictBody = [
        narrative("ICT Pattern", `Turtle Soup ${fmt(ict.turtle_soup)}, FVG ${fmt(ict.fvg_zone)}, OB ${fmt(ict.order_block)}.`),
        row("Turtle Soup", ict.turtle_soup),
        row("FVG", ict.fvg_zone),
        row("Order Block", ict.order_block),
        row("Liquidity Sweep", ict.liquidity_sweep),
    ].join("");

    const gannBody = [
        narrative("Gann Time + Price", `Cycle ${fmt(gann.cycle)} bars | Targets ${fmtPrice(gann.target_100)} / ${fmtPrice(gann.target_200)}.`),
        row("Cycle", gann.cycle),
        row("Target 100", fmtPrice(gann.target_100)),
        row("Target 200", fmtPrice(gann.target_200)),
    ].join("");

    const astroBody = [
        narrative("Astro Timing", `${astro.harmonic_window ? "Window Active" : "Window Inactive"} | ${fmt(astro.planet_event)}`),
        row("Harmonic Window", astro.harmonic_window ? "ACTIVE" : "INACTIVE"),
        row("Planet Event", astro.planet_event),
        row("Astro Bias", astro.bias),
    ].join("");

    const newsBody = [
        narrative("News Impact", `${fmt(news.next_event)} at ${fmt(news.time)} | Impact ${fmt(news.impact)}`),
        row("Next Event", news.next_event),
        row("Impact", news.impact),
        row("Time", news.time),
    ].join("");

    const sessionBody = [
        row("Session", session.session),
        row("Phase", session.phase),
    ].join("");

    const probabilityBody = [
        narrative("Probability Scoring", `${fmt(probability.verdict)} (${fmt(probability.score)}%)`),
        row("Score", `${fmt(probability.score)}%`),
        row("Verdict", probability.verdict),
    ].join("");

    const storyBody = narrative("Institutional Story", data.story || "--");

    const score = Number(probability.score);
    const verdictRaw = String(probability.verdict || "").toUpperCase();
    const scoreSource = fmt(probability.score_source || "model_confidence");
    const side = verdictRaw.includes("SELL") || verdictRaw.includes("SHORT")
        ? "SELL"
        : (verdictRaw.includes("BUY") || verdictRaw.includes("LONG") ? "BUY" : "WAIT");
    const riskText = fmt(context.volatility || "--");
    let actionVerdict = "WAIT";
    let actionTone = "neutral";
    if ((side === "BUY" || side === "SELL") && Number.isFinite(score) && score >= 70) {
        actionVerdict = `EXECUTE ${side}`;
        actionTone = side === "BUY" ? "bull" : "bear";
    } else if ((side === "BUY" || side === "SELL") && Number.isFinite(score) && score >= 55) {
        actionVerdict = `WATCH ${side}`;
        actionTone = "warn";
    }
    const actionDetail = `Score ${fmt(probability.score)}% (${scoreSource}) | Risk ${riskText} | Last ${fmtPrice(context.price)} | Sweep ${fmt(liquidity.sweep)} | POC ${fmtPrice(institution.poc)}`;
    const actionBlock = actionCall(actionVerdict, actionDetail, actionTone);

    content.innerHTML = `
        ${actionBlock}
        ${section("market", "1) Market Context", marketBody, savedSections.market !== false)}
        ${section("liquidity", "2) Liquidity", liquidityBody, savedSections.liquidity !== false)}
        ${section("institution", "3) Institutional Flow", institutionBody, savedSections.institution !== false)}
        ${section("ict", "4) ICT", ictBody, savedSections.ict !== false)}
        ${section("gann", "5) Gann", gannBody, savedSections.gann !== false)}
        ${section("astro", "6) Astro", astroBody, savedSections.astro !== false)}
        ${section("news", "7) News", newsBody, savedSections.news !== false)}
        ${section("session", "8) Session", sessionBody, savedSections.session !== false)}
        ${section("probability", "9) Probability", probabilityBody, savedSections.probability !== false)}
        ${section("story", "10) Story", storyBody, savedSections.story !== false)}
    `;

    for (const details of content.querySelectorAll("details[data-section-id]")) {
        details.addEventListener("toggle", () => {
            const state = JSON.parse(localStorage.getItem(MENTOR_SECTIONS_KEY) || "{}");
            state[details.dataset.sectionId] = details.open;
            localStorage.setItem(MENTOR_SECTIONS_KEY, JSON.stringify(state));
        });
    }

    const last = fmtPrice(context.price);
    setMentorMeta(`Updated: ${new Date(data.updated_at || Date.now()).toLocaleString()} | ${fmt(context.symbol || data.symbol || selectedMentorSymbol())} | Last: <span class="mentor-live-price">${last}</span>`);
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
        let res = await mentorFetch(`/mentor/context?symbol=${encodeURIComponent(symbol)}`);
        if (!res.ok) {
            res = await mentorFetch(`/mentor?symbol=${encodeURIComponent(symbol)}`);
        }
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const raw = await res.json();
        const data = normalizeMentorData(raw, symbol);
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
