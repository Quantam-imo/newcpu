// --- No-op for missing performance tracking ---
function trackPerformance() {}
const MENTOR_STATE_KEY = "aq_mentor_drawer_open";
const MENTOR_WIDTH_KEY = "aq_mentor_drawer_width";
const MENTOR_SECTIONS_KEY = "aq_mentor_sections";
const MENTOR_COMPACT_KEY = "aq_mentor_compact_mode";

function resetMentorUiState() {
    localStorage.removeItem(MENTOR_SECTIONS_KEY);
    localStorage.removeItem(MENTOR_COMPACT_KEY);
    localStorage.removeItem(MENTOR_WIDTH_KEY);
    localStorage.setItem(MENTOR_STATE_KEY, "1");
    mentorLoadedOnce = false;
    mentorLastRenderSignature = "";
}

function mentorApiOrigins() {
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

const mentorFetch = async (path, options, timeoutMs = 25000) => {
    const startTime = performance.now();
    
    // Check cache first for GET requests using getCache from api.js if available
    if ((!options?.method || options?.method === "GET") && typeof getCache === "function") {
        const cached = getCache(path);
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
    
    // Build target list: relative first (same-origin), then absolute same-origin.
    // Do NOT include hardcoded :8000 origins — they cause CORS blocks when the
    // page is served from a different port (e.g. 8001).
    const targets = [];

    // Always try relative URL first (same origin as page)
    targets.push(path);

    const uniqueOrigins = new Set();
    const baseOrigins = [
        String(window.AQ_API_BASE || window.location.origin || "").trim(),
        String(window.location.origin || "").trim(),
    ].filter(Boolean);

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
                    if ((!options?.method || options?.method === "GET") && typeof setCache === "function") {
                        setCache(path, jsonData);
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
    
    const isAbort = lastError && (lastError.name === "AbortError" || /aborted/i.test(String(lastError.message || "")));
    if (isAbort) {
        console.debug("mentorFetch aborted:", targets, "lastError:", lastError);
    } else {
        console.warn("mentorFetch failed on all targets:", targets, "lastError:", lastError);
    }
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
    const input = document.getElementById("chartSymbolInput");
    if (input && input.value) return input.value;
    const select = document.getElementById("chartSymbol");
    return select && select.value ? select.value : "XAUUSD";
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

function fmtObj(v) {
    if (!v || typeof v !== "object" || Array.isArray(v)) return fmt(v);
    const rows = [];
    for (const [key, value] of Object.entries(v)) {
        if (value === null || value === undefined || value === "") continue;
        if (typeof value === "object") continue;
        rows.push(`${key}:${fmt(value)}`);
    }
    return rows.length ? rows.join(" | ") : "--";
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

function renderMentorSkeleton(message = "Loading mentor context...") {
    const content = document.getElementById("mentorContent");
    if (!content) return;

    const placeholder = narrative("AI Mentor", message);
    const sections = [
        "1) Market Context",
        "2) Liquidity",
        "3) Institutional Flow",
        "4) Iceberg",
        "5) ICT",
        "6) Gann",
        "7) Astro",
        "8) News",
        "9) Session",
        "10) Probability",
        "11) Story",
    ];

    content.innerHTML = [
        actionCall("WAIT", message, "neutral"),
        ...sections.map((title, idx) => section(`skeleton-${idx + 1}`, title, placeholder, true)),
    ].join("");

    setMentorMeta("Initializing mentor...");
}

function sectionOpen(savedSections, id) {
    if (!savedSections || typeof savedSections !== "object") return true;
    const boolStates = Object.values(savedSections).filter(v => typeof v === "boolean");
    if (boolStates.length > 0 && boolStates.every(v => v === false)) return true;
    if (!Object.prototype.hasOwnProperty.call(savedSections, id)) return true;
    return Boolean(savedSections[id]);
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
        const gannRaw = (payload.gann && typeof payload.gann === "object") ? payload.gann : {};
        const signals = (gannRaw.signals && typeof gannRaw.signals === "object") ? gannRaw.signals : {};
        const enrichedGann = {
            ...gannRaw,
            square_of_9: gannRaw.square_of_9 ?? signals.square_of_9,
            price_time: gannRaw.price_time ?? signals.price_time,
            vector: gannRaw.vector ?? signals.vector,
            octave: gannRaw.octave ?? signals.octave,
            planet_alignment: gannRaw.planet_alignment ?? signals.planet_alignment,
            spiral: gannRaw.spiral ?? signals.spiral,
            spiral_vector: gannRaw.spiral_vector ?? signals.spiral_vector,
            angle: gannRaw.angle ?? signals.angle,
            angle_lines: gannRaw.angle_lines ?? signals.angle_lines,
        };
        return {
            ...payload,
            gann: enrichedGann,
        };
    }

    // Handle /mentor/context response: {"context": {market:{...}, model:{...}, price:X, narrative:"...", ...}}
    // This is the format returned by the backend's build_context() wrapped in a "context" key.
    if (payload.context && !payload.market && typeof payload.context === "object" && payload.context.market) {
        const inner = payload.context;
        const iMarket = inner.market || {};
        const iModel = inner.model || {};
        const iIceberg = inner.iceberg || {};
        const iPrice = inner.price ?? null;

        const iConfRaw = Number(iModel.confidence ?? 0);
        // Backend stores 0-1 float; convert to 0-100
        const iConfScore = Number.isFinite(iConfRaw)
            ? Math.round(Math.max(0, Math.min(100, iConfRaw <= 1 ? iConfRaw * 100 : iConfRaw)))
            : 0;

        const iHtfBias = String(iMarket.htf_bias || "").toUpperCase();
        let iVerdict = "Low Probability / Wait";
        if (iHtfBias.includes("BULL")) iVerdict = iConfScore >= 55 ? "Buy Setup" : "Watch Buy";
        else if (iHtfBias.includes("BEAR")) iVerdict = iConfScore >= 55 ? "Sell Setup" : "Watch Sell";

        // Map enriched backend-derived fields if present
        const iLiq  = (inner.liquidity_sweep && typeof inner.liquidity_sweep === "object") ? inner.liquidity_sweep : {};
        const iIct  = (inner.ict && typeof inner.ict === "object") ? inner.ict : {};
        const iFlow = (inner.orderflow && typeof inner.orderflow === "object") ? inner.orderflow : {};
        const iSrc  = (inner.data_source && typeof inner.data_source === "object") ? inner.data_source : {};
        const iGann = (inner.gann && typeof inner.gann === "object") ? inner.gann : null;
        const iAstro = (inner.astro && typeof inner.astro === "object") ? inner.astro : null;

        // Probability: use orderflow signal_strength when available; adjust verdict for neutral bias
        const iFlowScore = Number.isFinite(Number(iFlow.signal_strength)) ? Number(iFlow.signal_strength) : null;
        const iFinalScore = iFlowScore ?? iConfScore;
        const iScoreSource = iFlowScore != null ? "candle_orderflow" : "model_confidence";
        let iVerdict2;
        if (iHtfBias.includes("BULL")) {
            iVerdict2 = iFinalScore >= 70 ? "Buy Setup" : iFinalScore >= 55 ? "Watch Buy" : "Low Probability / Wait";
        } else if (iHtfBias.includes("BEAR")) {
            iVerdict2 = iFinalScore >= 70 ? "Sell Setup" : iFinalScore >= 55 ? "Watch Sell" : "Low Probability / Wait";
        } else {
            iVerdict2 = iFinalScore >= 70 ? "Await Confluence (High Score)" : iFinalScore >= 55 ? "Await Confluence" : "No Edge — Wait";
        }

        return {
            symbol: iMarket.symbol || symbol,
            context: {
                symbol: iMarket.symbol || symbol,
                price: iPrice,
                prev_low: inner.prev_low ?? null,
                prev_high: inner.prev_high ?? null,
                htf_bias: iMarket.htf_bias,
                ltf_structure: iMarket.ltf_structure,
                kill_zone: iMarket.session,
                volatility: iMarket.volatility,
            },
            liquidity: {
                external_high: inner.prev_high ?? null,
                external_low: inner.prev_low ?? null,
                sweep: iLiq.sweep || "none",
                target: iLiq.target || (iHtfBias === "BULLISH" ? "LONG" : iHtfBias === "BEARISH" ? "SHORT" : "--"),
            },
            institution: {
                iceberg_buy: iFlow.absorption_signal === "BUY_ABSORPTION" ? "YES" : "NO",
                iceberg_sell: iFlow.absorption_signal === "SELL_ABSORPTION" ? "YES" : "NO",
                delta: iFlow.delta_state || iHtfBias || "NEUTRAL",
                poc: iPrice,
            },
            iceberg: {
                detected: !!(iIceberg && iIceberg.detected),
                price: (iIceberg && iIceberg.price) ?? null,
                strength: (iIceberg && iIceberg.strength) ?? null,
                bias: (iIceberg && iIceberg.bias) ?? null,
                absorption: (iIceberg && iIceberg.absorption) ?? null,
            },
            ict: {
                turtle_soup: iIct.turtle_soup || "--",
                fvg_zone: iIct.fvg_zone || iModel.entry_logic || "--",
                order_block: iIct.order_block || "--",
                liquidity_sweep: iLiq.sweep || "none",
            },
            gann: iGann || {
                _engine: "NOT_ACTIVE",
                enabled: false,
                detected: false,
                reason: "ENGINE_NOT_AVAILABLE",
            },
            astro: iAstro || {
                harmonic_window: false,
                planet_event: "ENGINE_NOT_ACTIVE",
                bias: "--",
                _engine: "NOT_ACTIVE",
                reason: "ENGINE_NOT_AVAILABLE",
            },
            news: {
                next_event: iMarket.news_state || "None",
                impact: iMarket.news_state === "HALT" ? "High" : "Low",
                time: "--",
            },
            session: {
                session: iMarket.session || "--",
                phase: iMarket.ltf_structure || "--",
            },
            probability: {
                score: iFinalScore,
                score_source: iScoreSource,
                verdict: iVerdict2,
            },
            story: iFlow.narrative ? `${iFlow.narrative} ${inner.narrative || ""}`.trim() : (inner.narrative || iModel.reason || "--"),
            data_source: iSrc,
            updated_at: inner.updated_at || new Date().toISOString(),
        };
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
            square_of_9: gannRaw.square_of_9,
            price_time: gannRaw.price_time,
            vector: gannRaw.vector,
            octave: gannRaw.octave,
            planet_alignment: gannRaw.planet_alignment,
            spiral: gannRaw.spiral,
            spiral_vector: gannRaw.spiral_vector,
            angle: gannRaw.angle,
            angle_lines: gannRaw.angle_lines,
        },
        astro: {
            harmonic_window: astroRows.length > 0 && astroRows[0]?.harmonic_window,
            planet_event: astroRows.length > 0 ? astroRows[0]?.planet_event : "None",
            bias: astroRows.length > 0 ? astroRows[0]?.bias : "Neutral",
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
            score: confidenceScore,
            score_source: "model_confidence",
            verdict,
        },
        story: model.reason || "--",
        updated_at: payload.updated_at || new Date().toISOString(),
    };
}

function mentorRenderSignature(data) {
    const context = data.context || {};
    const probability = data.probability || {};
    const gann = data.gann || {};
    const iceberg = data.iceberg || {};
    const summary = {
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

    // Gann: show real data if engine active, otherwise ENGINE_NOT_ACTIVE pill
    const gannEngineOff = gann._engine === "NOT_ACTIVE" || (gann.enabled === undefined && gann.detected === undefined && !gann.score && !gann.cycle);
    const gannDetected = Boolean(gann.detected);
    const gannEnabled = !gannEngineOff && gann.enabled !== false;
    const gannStatus = gannEngineOff
        ? "NOT_ACTIVE"
        : !gannEnabled ? "OFF"
        : (gannDetected
            ? `${fmt(gann.direction)} ${gann.confidence != null ? `${fmt(gann.confidence)}%` : ""}`.trim()
            : "NO ACTIVE SIGNAL");
    const gannBody = !gannEngineOff ? [
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
        row("Price-Time", fmtObj(gann.price_time)),
        row("Square of 9", fmtObj(gann.square_of_9)),
        row("Angle", fmtObj(gann.angle)),
        row("Angle Lines", fmtObj(gann.angle_lines)),
        row("Vector", fmtObj(gann.vector)),
        row("Octave", fmtObj(gann.octave)),
        row("Planet Align", fmtObj(gann.planet_alignment)),
        row("Spiral", fmtObj(gann.spiral)),
        row("Spiral Vector", fmtObj(gann.spiral_vector)),
        row("Support", fmtPrice(gann.support)),
        row("Resistance", fmtPrice(gann.resistance)),
        row("Target 100", fmtPrice(gann.target_100)),
        row("Target 200", fmtPrice(gann.target_200)),
    ].join("") : [
        `<span class="mentor-status-badge warn">GANN ENGINE NOT ACTIVE</span>`,
        narrative("Gann Time + Price", "Gann analysis engine not running. Enable the Gann module to see cycle, degree, vibration, and price-time alignment signals."),
    ].join("");

    // Astro: show real data if engine active, otherwise ENGINE_NOT_ACTIVE pill
    const astroEngineOff = astro._engine === "NOT_ACTIVE" || astro.planet_event === "ENGINE_NOT_ACTIVE";
    const astroBody = !astroEngineOff ? [
        narrative("Astro Timing", `${astro.harmonic_window ? "Window Active" : "Window Inactive"} | ${fmt(astro.planet_event)}`),
        row("Harmonic Window", astro.harmonic_window ? "ACTIVE" : "INACTIVE"),
        row("Planet Event", astro.planet_event),
        row("Astro Bias", astro.bias),
    ].join("") : [
        `<span class="mentor-status-badge warn">ASTRO ENGINE NOT ACTIVE</span>`,
        narrative("Astro Timing", "AstroQuant planetary harmonic engine not running. Enable the astro module to see harmonic windows and planet event signals."),
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
    const ds = data.data_source || {};
    const staleBadge = ds.stale ? statusBadge(`DATA ${ds.stale_hours ?? "?"}h OLD`, "bad") : "";
    const fallbackBadge = ds.fallback_used && !ds.stale ? statusBadge("FALLBACK DATA", "warn") : "";
    const srcSymbol = ds.symbol && ds.symbol !== (context.symbol || selectedMentorSymbol()) ? ` (${fmt(ds.symbol)})` : "";
    setMentorMeta(`
        <div class="mentor-meta-line">
            <span class="mentor-meta-text">Updated: ${updatedAt.toLocaleString()} | ${fmt(context.symbol || data.symbol || selectedMentorSymbol())}${srcSymbol} | Last: <span class="mentor-live-price">${last}</span></span>
            ${statusBadge(`Fresh ${ageSec}s`, freshnessTone)}
            ${statusBadge(`Completeness ${completenessCount}/3`, completenessTone)}
            ${staleBadge}${fallbackBadge}
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
    const resetBtn = document.getElementById("mentorResetBtn");
    const symbolSelect = document.getElementById("chartSymbolInput") || document.getElementById("chartSymbol");
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
    if (resetBtn) {
        resetBtn.addEventListener("click", () => {
            resetMentorUiState();
            drawer.classList.add("open");
            drawer.classList.remove("mentor-compact");
            drawer.style.width = "420px";
            if (compactBtn) compactBtn.innerText = "Compact";
            renderMentorSkeleton("Resetting mentor UI state...");
            loadMentor().catch(() => {});
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
window.resetMentorUiState = resetMentorUiState;
initMentorDrawer();
