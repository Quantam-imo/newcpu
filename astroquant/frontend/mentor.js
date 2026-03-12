const MENTOR_STATE_KEY = "aq_mentor_drawer_open";
const MENTOR_WIDTH_KEY = "aq_mentor_drawer_width";
const MENTOR_SECTIONS_KEY = "aq_mentor_sections";
const MENTOR_COMPACT_KEY = "aq_mentor_compact_mode";
const AQ_DEFAULT_MENTOR_API_ORIGIN = "http://127.0.0.1:8000";

function resolveMentorApiBase() {
    const configured = String(window.AQ_API_BASE || "").trim();
    return configured || AQ_DEFAULT_MENTOR_API_ORIGIN;
}

const mentorFetch = async (path, options, timeoutMs = 25000) => {
    const startTime = performance.now();
    const pathBase = path.split('?')[0];
    
    // Check cache first for GET requests
    if (!options?.method || options?.method === "GET") {
        const cached = getCachedResponse(path);
        if (cached) {
            trackPerformance(path, 0, true);
            console.debug(`mentorFetch: Cache hit for ${path}`);
            // Return cached data as Response object
            return new Response(JSON.stringify(cached), {
                status: 200,
                headers: { "Content-Type": "application/json", "X-From-Cache": "true" }
            });
        }
    }
    
    // Build comprehensive list of targets to try
    const targets = [];
    
    // Always try relative URL first (same origin as page)
    targets.push(path);
    
    // Then try absolute URLs in priority order
    const uniqueOrigins = new Set();
    const baseOrigins = [
        window.location.origin,              // Current page origin
        "http://localhost:8000",              // Localhost
        "http://127.0.0.1:8000",              // Loopback
    ];
    
    for (const origin of baseOrigins) {
        const trimmed = String(origin || "").trim();
        if (trimmed && !uniqueOrigins.has(trimmed)) {
            uniqueOrigins.add(trimmed);
            targets.push(`${trimmed}${path}`);
        }
    }
    
    let lastError = null;
    for (const target of targets) {
        const controller = new AbortController();
        const timer = setTimeout(() => controller.abort(), timeoutMs);
        try {
            const response = await fetch(target, { ...options, signal: controller.signal });
            clearTimeout(timer);
            
            if (response.ok) {
                const duration = performance.now() - startTime;
                trackPerformance(path, duration, false);
                
                // Update AQ_API_BASE on success
                if (target.startsWith("http")) {
                    try {
                        const origin = new URL(target).origin;
                        if (origin && origin !== window.location.origin) {
                            window.AQ_API_BASE = origin;
                        }
                    } catch (_) {}
                }
                
                // Cache successful JSON responses
                try {
                    const jsonData = await response.clone().json();
                    if (CACHE_CONFIG[pathBase]) {
                        cacheResponse(path, jsonData);
                    }
                } catch (_) {}
                
                return response;
            }
            lastError = response;
        } catch (error) {
            clearTimeout(timer);
            lastError = error;
            console.debug(`mentorFetch: ${target} failed -`, error.message || error);
        }
    }
    
    console.warn("mentorFetch failed on all targets:", targets, "lastError:", lastError);
    return new Response(
        JSON.stringify({ status: "error", message: "fetch failed" }),
        { status: 599, headers: { "Content-Type": "application/json" } },
    );
};
let mentorLoadedOnce = false;
let mentorRequestInFlight = false;
let mentorRefreshQueued = false;
let mentorRequestSerial = 0;
let mentorLastRenderSignature = "";

function selectedMentorSymbol() {
    const select = document.getElementById("chartSymbol");
    return select ? select.value : "XAUUSD";
}

function setMentorMeta(text) {
    const el = document.getElementById("mentorMeta");
    if (el) el.innerHTML = text;
}

function statusBadge(label, tone = "warn") {
    const safeTone = ["good", "warn", "bad"].includes(String(tone)) ? tone : "warn";
    return `<span class="mentor-status-badge ${safeTone}">${fmt(label)}</span>`;
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

function sectionOpen(savedSections, id) {
    return Boolean(savedSections && savedSections[id] === true);
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

function gannStatusPill(gann) {
    const enabled = gann?.enabled !== false;
    const detected = Boolean(gann?.detected);
    const direction = String(gann?.direction || "").toUpperCase();
    const confidence = gann?.confidence != null ? `${fmt(gann.confidence)}%` : "";

    if (!enabled) return `<span class="mentor-gann-pill gann-off">GANN OFF</span>`;
    if (!detected) return `<span class="mentor-gann-pill gann-none">GANN NO SIGNAL</span>`;
    if (direction === "SELL") return `<span class="mentor-gann-pill gann-sell">GANN SELL ${confidence}</span>`;
    return `<span class="mentor-gann-pill gann-buy">GANN BUY ${confidence}</span>`;
}

function normalizeMentorData(raw, symbol) {
    const payload = raw || {};
    if (payload.context && payload.probability && !Array.isArray(payload.gann)) {
        return payload;
    }

    const market = payload.market || {};
    const model = payload.model || {};
    const risk = payload.risk || {};
    const prices = payload.prices || {};
    const iceberg = payload.iceberg || {};
    const summary = payload.orderflow_summary || {};
    const gannRows = Array.isArray(payload.gann) ? payload.gann : [];
    const gannRaw = (!Array.isArray(payload.gann) && payload.gann && typeof payload.gann === "object") ? payload.gann : {};
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
        iceberg: {
            detected: iceberg.detected,
            price: iceberg.price,
            strength: iceberg.strength,
            bias: iceberg.bias,
            absorption: iceberg.absorption,
        },
        ict: {
            turtle_soup: "--",
            fvg_zone: model.entry_logic || "OFF",
            order_block: model.invalid_if || "OFF",
            liquidity_sweep: summary.absorption_signal || "none",
        },
        gann: {
            cycle: gannRaw.cycle ?? gannRows.length,
            target_100: gannRaw.target_100 ?? resistance,
            target_200: gannRaw.target_200 ?? support,
            enabled: gannRaw.enabled,
            detected: gannRaw.detected,
            direction: gannRaw.direction,
            confidence: gannRaw.confidence,
            score: gannRaw.score,
            degree: gannRaw.degree,
            key_degree: gannRaw.key_degree,
            cross: gannRaw.cross,
            vibration: gannRaw.vibration,
            time_vibration: gannRaw.time_vibration,
            cycle_144: gannRaw.cycle_144,
            master_cycle: gannRaw.master_cycle,
            price_time_alignment: gannRaw.price_time_alignment,
            support: gannRaw.support,
            resistance: gannRaw.resistance,
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
    content.innerHTML = `<div class="mentor-action-call mentor-tone-neutral"><strong>AI Mentor</strong><span>${fmt(message)}</span></div>`;
}

function mentorRenderSignature(data) {
    const context = data?.context || {};
    const probability = data?.probability || {};
    const gann = data?.gann || {};
    const iceberg = data?.iceberg || {};
    const summary = {
        symbol: data?.symbol,
        price: context?.price,
        htf: context?.htf_bias,
        ltf: context?.ltf_structure,
        vol: context?.volatility,
        score: probability?.score,
        verdict: probability?.verdict,
        story: data?.story,
        gannDetected: gann?.detected,
        gannDir: gann?.direction,
        gannConf: gann?.confidence,
        iceDetected: iceberg?.detected,
        iceBias: iceberg?.bias,
        iceAbsorption: iceberg?.absorption,
        iceStrength: iceberg?.strength,
    };
    try {
        return JSON.stringify(summary);
    } catch (_) {
        return String(Date.now());
    }
}

function renderMentorContext(data, sectionOverrides = null) {
    const content = document.getElementById("mentorContent");
    if (!content) return;
    const previousHeight = Math.max(0, content.getBoundingClientRect().height || 0);
    if (previousHeight > 0) {
        content.style.minHeight = `${Math.ceil(previousHeight)}px`;
    }

    const savedSections = sectionOverrides || JSON.parse(localStorage.getItem(MENTOR_SECTIONS_KEY) || "{}");
    const context = data.context || {};
    const liquidity = data.liquidity || {};
    const institution = data.institution || {};
    const iceberg = data.iceberg || {};
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

    const icebergBody = [
        narrative(
            "Iceberg Detection",
            `${Boolean(iceberg.detected) ? "Detected" : "Not detected"} | Bias ${fmt(iceberg.bias)} | Absorption ${fmt(iceberg.absorption)}.`,
        ),
        row("Detected", iceberg.detected ? "YES" : "NO"),
        row("Price", fmtPrice(iceberg.price)),
        row("Strength", iceberg.strength != null ? fmt(iceberg.strength) : "--"),
        row("Bias", iceberg.bias),
        row("Absorption", iceberg.absorption),
    ].join("");

    const ictBody = [
        narrative("ICT Pattern", `Turtle Soup ${fmt(ict.turtle_soup)}, FVG ${fmt(ict.fvg_zone)}, OB ${fmt(ict.order_block)}.`),
        row("Turtle Soup", ict.turtle_soup),
        row("FVG", ict.fvg_zone),
        row("Order Block", ict.order_block),
        row("Liquidity Sweep", ict.liquidity_sweep),
    ].join("");

    const gannDetected = Boolean(gann.detected);
    const gannEnabled = gann.enabled !== false;
    const gannStatus = !gannEnabled
        ? "OFF"
        : (gannDetected
            ? `${fmt(gann.direction)} ${gann.confidence != null ? `${fmt(gann.confidence)}%` : ""}`.trim()
            : "NO ACTIVE SIGNAL");
    const gannBody = [
        `<div style="margin-bottom:6px;">${gannStatusPill(gann)}</div>`,
        narrative(
            "Gann Time + Price",
            `Status ${gannStatus} | Score ${fmt(gann.score)} | Cycle ${fmt(gann.cycle)} bars | Targets ${fmtPrice(gann.target_100)} / ${fmtPrice(gann.target_200)}.`,
        ),
        row("Engine", gannEnabled ? "ON" : "OFF"),
        row("Signal", gannDetected ? "DETECTED" : "NONE"),
        row("Direction", gann.direction),
        row("Confidence", gann.confidence != null ? `${fmt(gann.confidence)}%` : "--"),
        row("Score", gann.score),
        row("Cycle", gann.cycle),
        row("Cycle 144", gann.cycle_144 ? "YES" : "NO"),
        row("Master Cycle", gann.master_cycle ? "YES" : "NO"),
        row("Cross", gann.cross),
        row("Degree", gann.degree),
        row("Key Degree", gann.key_degree),
        row("Vibration", gann.vibration),
        row("Time Vibration", gann.time_vibration),
        row("Price-Time Align", gann.price_time_alignment ? "YES" : "NO"),
        row("Support", fmtPrice(gann.support)),
        row("Resistance", fmtPrice(gann.resistance)),
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
    const performanceStrip = `
        <div class="mentor-exec-summary mentor-tone-${actionTone}">
            <div class="mentor-exec-item">Verdict<br/><strong>${fmt(actionVerdict)}</strong></div>
            <div class="mentor-exec-item">Score<br/><strong>${fmt(probability.score)}%</strong></div>
            <div class="mentor-exec-item">Signal<br/><strong>${fmt(scoreSource)}</strong></div>
            <div class="mentor-exec-item">Bias<br/><strong>${fmt(context.htf_bias)}</strong></div>
            <div class="mentor-exec-item">Volatility<br/><strong>${fmt(context.volatility)}</strong></div>
            <div class="mentor-exec-item">Last Price<br/><strong class="mentor-live-price">${fmtPrice(context.price)}</strong></div>
        </div>
    `;

    content.innerHTML = `
        ${actionBlock}
        ${performanceStrip}
        ${section("market", "1) Market Context", marketBody, sectionOpen(savedSections, "market"))}
        ${section("liquidity", "2) Liquidity", liquidityBody, sectionOpen(savedSections, "liquidity"))}
        ${section("institution", "3) Institutional Flow", institutionBody, sectionOpen(savedSections, "institution"))}
        ${section("iceberg", "4) Iceberg", icebergBody, sectionOpen(savedSections, "iceberg"))}
        ${section("ict", "5) ICT", ictBody, sectionOpen(savedSections, "ict"))}
        ${section("gann", "6) Gann", gannBody, sectionOpen(savedSections, "gann"))}
        ${section("astro", "7) Astro", astroBody, sectionOpen(savedSections, "astro"))}
        ${section("news", "8) News", newsBody, sectionOpen(savedSections, "news"))}
        ${section("session", "9) Session", sessionBody, sectionOpen(savedSections, "session"))}
        ${section("probability", "10) Probability", probabilityBody, sectionOpen(savedSections, "probability"))}
        ${section("story", "11) Story", storyBody, sectionOpen(savedSections, "story"))}
    `;

    for (const details of content.querySelectorAll("details[data-section-id]")) {
        details.addEventListener("toggle", () => {
            if (details.open && window.innerWidth <= 900) {
                for (const other of content.querySelectorAll("details[data-section-id]")) {
                    if (other !== details) other.open = false;
                }
            }
            const state = JSON.parse(localStorage.getItem(MENTOR_SECTIONS_KEY) || "{}");
            state[details.dataset.sectionId] = details.open;
            localStorage.setItem(MENTOR_SECTIONS_KEY, JSON.stringify(state));
        });
    }

    const last = fmtPrice(context.price);
    const updatedAt = new Date(data.updated_at || Date.now());
    const ageSec = Math.max(0, Math.round((Date.now() - updatedAt.getTime()) / 1000));
    const freshnessTone = ageSec <= 15 ? "good" : (ageSec <= 60 ? "warn" : "bad");
    const hasPrice = Number.isFinite(Number(context.price));
    const hasOrderflow = institution?.delta != null && String(institution.delta || "").trim() !== "";
    const hasIceberg = iceberg?.detected != null || iceberg?.strength != null;
    const completenessCount = [hasPrice, hasOrderflow, hasIceberg].filter(Boolean).length;
    const completenessTone = completenessCount >= 3 ? "good" : (completenessCount >= 2 ? "warn" : "bad");
    setMentorMeta(`
        <div class="mentor-meta-line">
            <span class="mentor-meta-text">Updated: ${updatedAt.toLocaleString()} | ${fmt(context.symbol || data.symbol || selectedMentorSymbol())} | Last: <span class="mentor-live-price">${last}</span></span>
            ${statusBadge(`Fresh ${ageSec}s`, freshnessTone)}
            ${statusBadge(`Completeness ${completenessCount}/3`, completenessTone)}
        </div>
    `);
    requestAnimationFrame(() => {
        content.style.minHeight = "";
    });
}

async function loadMentor() {
    if (mentorRequestInFlight) {
        mentorRefreshQueued = true;
        return;
    }
    mentorRequestInFlight = true;
    try {
        const requestSerial = ++mentorRequestSerial;
        const mergedState = {
            ...(JSON.parse(localStorage.getItem(MENTOR_SECTIONS_KEY) || "{}") || {}),
            ...getCurrentSectionState(),
        };
        localStorage.setItem(MENTOR_SECTIONS_KEY, JSON.stringify(mergedState));

        const wrap = document.querySelector("#mentorDrawer .mentor-content-wrap");
        const prevScrollTop = wrap ? wrap.scrollTop : 0;

        if (!mentorLoadedOnce) {
            renderMentorSkeleton();
        }

        const symbol = selectedMentorSymbol();
        let res = await mentorFetch(`/mentor/context?symbol=${encodeURIComponent(symbol)}`);
        if (!res.ok) {
            res = await mentorFetch(`/mentor?symbol=${encodeURIComponent(symbol)}`);
        }
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const raw = await res.json();
        if (requestSerial !== mentorRequestSerial) return;
        if (selectedMentorSymbol() !== symbol) return;
        const data = normalizeMentorData(raw, symbol);
        const signature = mentorRenderSignature(data);
        if (!mentorLoadedOnce || signature !== mentorLastRenderSignature) {
            renderMentorContext(data, mergedState);
            mentorLastRenderSignature = signature;
        } else {
            const context = data.context || {};
            const last = fmtPrice(context.price);
            setMentorMeta(`Updated: ${new Date(data.updated_at || Date.now()).toLocaleString()} | ${fmt(context.symbol || data.symbol || selectedMentorSymbol())} | Last: <span class="mentor-live-price">${last}</span>`);
        }
        mentorLoadedOnce = true;

        if (wrap) {
            const maxScrollTop = Math.max(0, wrap.scrollHeight - wrap.clientHeight);
            wrap.scrollTop = Math.min(prevScrollTop, maxScrollTop);
        }
    } catch (err) {
        renderMentorSkeleton("Mentor data unavailable");
        setMentorMeta(`Mentor unavailable: ${err}`);
        
        // Show error banner with retry capability
        const symbol = selectedMentorSymbol();
        const errorMsg = `Failed to load mentor data for ${symbol}. ${err.message || err}`;
        showError(
            "mentor_load_error",
            errorMsg,
            () => loadMentor().catch(() => {}),
            true
        );
    } finally {
        mentorRequestInFlight = false;
        if (mentorRefreshQueued) {
            mentorRefreshQueued = false;
            setTimeout(() => loadMentor().catch(() => {}), 0);
        }
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
    const compactBtn = document.getElementById("mentorCompactBtn");
    const symbolSelect = document.getElementById("chartSymbol");
    if (!drawer) return;

    const savedOpen = localStorage.getItem(MENTOR_STATE_KEY) === "1";
    if (savedOpen) drawer.classList.add("open");

    const savedWidth = Number(localStorage.getItem(MENTOR_WIDTH_KEY) || 420);
    if (Number.isFinite(savedWidth) && savedWidth >= 320 && savedWidth <= 760) {
        drawer.style.width = `${savedWidth}px`;
    }

    const compactMode = localStorage.getItem(MENTOR_COMPACT_KEY) === "1";
    drawer.classList.toggle("mentor-compact", compactMode);
    if (compactBtn) compactBtn.innerText = compactMode ? "Expanded" : "Compact";

    if (refreshBtn) refreshBtn.addEventListener("click", () => loadMentor().catch(() => {}));
    if (compactBtn) {
        compactBtn.addEventListener("click", () => {
            const nextCompact = !drawer.classList.contains("mentor-compact");
            drawer.classList.toggle("mentor-compact", nextCompact);
            compactBtn.innerText = nextCompact ? "Expanded" : "Compact";
            localStorage.setItem(MENTOR_COMPACT_KEY, nextCompact ? "1" : "0");
        });
    }
    if (symbolSelect) {
        symbolSelect.addEventListener("change", () => {
            if (!drawer.classList.contains("open")) return;
            loadMentor().catch(() => {});
        });
    }

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
    if (savedOpen) {
        loadMentor().catch(() => {});
    }
    setInterval(() => {
        if (!drawer.classList.contains("open")) return;
        loadMentor().catch(() => {});
    }, 8000);
}

window.toggleMentor = toggleMentor;
initMentorDrawer();
