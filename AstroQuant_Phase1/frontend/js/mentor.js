let mentorDrawerOpen = true;
let mentorInterval = null;
const mentorSectionState = {
    pricing: true,
    context: true,
    ict: false,
    iceberg: false,
    gann: false,
    astro: false,
    news: false,
    reasoning: true,
    justification: true,
    risk: false,
    verdict: true,
};

function safe(value, fallback = "--") {
    return value === null || value === undefined || value === "" ? fallback : value;
}

function boolText(value) {
    return value ? "Yes" : "No";
}

function formatUtcTime(value) {
    if (!value) return "--";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return String(value);
    const hh = String(date.getUTCHours()).padStart(2, "0");
    const mm = String(date.getUTCMinutes()).padStart(2, "0");
    const ss = String(date.getUTCSeconds()).padStart(2, "0");
    return `${hh}:${mm}:${ss} UTC`;
}

function sideClass(side) {
    const normalized = String(side || "WAIT").toUpperCase();
    if (normalized === "BUY") return "is-buy";
    if (normalized === "SELL") return "is-sell";
    return "is-wait";
}

function sideBadge(side) {
    const normalized = String(side || "WAIT").toUpperCase();
    return `<span class="mentor-side-badge ${sideClass(normalized)}">${normalized}</span>`;
}

function updateChartSideBadge(side) {
    const badge = document.getElementById("chartMentorSideBadge");
    if (!badge) return;
    const normalized = String(side || "WAIT").toUpperCase();
    badge.classList.remove("is-buy", "is-sell", "is-wait");
    badge.classList.add(sideClass(normalized));
    badge.textContent = normalized;
}

function section(key, title, body) {
    const isOpen = mentorSectionState[key] ? "open" : "";
    return `
        <div class="mentor-section ${isOpen}" data-section="${key}">
            <div class="mentor-section-header">${title}</div>
            <div class="mentor-section-body">${body}</div>
        </div>
    `;
}

function attachSectionListeners() {
    document.querySelectorAll(".mentor-section-header").forEach((header) => {
        header.onclick = () => {
            const container = header.parentElement;
            if (!container) return;
            container.classList.toggle("open");
            const key = container.dataset.section;
            if (key) mentorSectionState[key] = container.classList.contains("open");
        };
    });
}

function stopMentorRefresh() {
    if (mentorInterval) {
        clearInterval(mentorInterval);
        mentorInterval = null;
    }
}

function startMentorRefresh() {
    stopMentorRefresh();
    window.loadMentor(window.chartState?.symbol);
    mentorInterval = setInterval(() => {
        window.loadMentor(window.chartState?.symbol);
    }, 5000);
}

function syncMentorDrawerState() {
    const layout = document.getElementById("layout");
    const drawer = document.getElementById("mentorDrawer");
    const toggleBtn = document.getElementById("mentorToggleBtn");
    if (!layout || !drawer || !toggleBtn) return;

    drawer.classList.toggle("collapsed", !mentorDrawerOpen);
    layout.classList.toggle("mentor-collapsed", !mentorDrawerOpen);
    toggleBtn.textContent = mentorDrawerOpen ? "Close" : "Open";

    if (mentorDrawerOpen) {
        startMentorRefresh();
    } else {
        stopMentorRefresh();
    }
}

window.toggleMentor = function toggleMentor() {
    mentorDrawerOpen = !mentorDrawerOpen;
    syncMentorDrawerState();
};

window.loadMentor = async function loadMentor(symbol) {
    const mentorContent = document.getElementById("mentorContent");
    const mentorMeta = document.getElementById("mentorMeta");
    if (!mentorContent || !mentorMeta) return;

    const activeSymbol = symbol || (window.chartState?.symbol ?? "GC.FUT");

    try {
        const data = await window.apiFetchJson(`/ai/mentor?symbol=${encodeURIComponent(activeSymbol)}`);

        mentorMeta.innerHTML = `
            <b>${safe(data.symbol, activeSymbol)}</b> @ ${safe(data.price)}
            <span style="float:right;">${formatUtcTime(data.timestamp)}</span><br>
            Confidence: ${safe(data.confidence, 0)}% | Side: ${sideBadge(safe(data.recommended_side, "WAIT"))}
        `;
        updateChartSideBadge(safe(data.recommended_side, "WAIT"));

        mentorContent.innerHTML = `
            ${section("pricing", "Price Template", `
                Current Price: ${safe(data.prices?.current_price, data.price)}<br>
                Equilibrium: ${safe(data.prices?.equilibrium)}<br>
                Range: ${safe(data.prices?.range_low)} - ${safe(data.prices?.range_high)}<br>
                Execution Zone: ${safe(data.prices?.execution_zone)}
            `)}

            ${section("context", "Market Context", `
                HTF Bias: ${safe(data.context?.htf_bias)}<br>
                LTF Structure: ${safe(data.context?.ltf_structure)}<br>
                Liquidity Zones: ${safe(data.context?.liquidity_zones)}<br>
                Kill Zone: ${safe(data.context?.kill_zone)}
            `)}

            ${section("ict", "ICT Concepts", `
                FVG Detected: ${boolText(!!data.ict?.fvg_detected)}<br>
                Order Block: ${safe(data.ict?.order_block)}<br>
                Breaker: ${safe(data.ict?.breaker)}<br>
                Structure Shift: ${safe(data.ict?.structure_shift)}
            `)}

            ${section("iceberg", "Iceberg Absorption", `
                Absorption: ${boolText(!!data.iceberg?.absorption_detected)}<br>
                Institutional Side: ${safe(data.iceberg?.institutional_side)}<br>
                Pressure Type: ${safe(data.iceberg?.pressure)}<br>
                Zone: ${safe(data.iceberg?.zone)}<br>
                Institutional Buying Pressure: ${safe(data.iceberg?.institutional_buying_pressure, data.iceberg?.buy_volume ?? 0)}<br>
                Institutional Selling Pressure: ${safe(data.iceberg?.institutional_selling_pressure, data.iceberg?.sell_volume ?? 0)}<br>
                Net Pressure: ${safe(data.iceberg?.net_pressure, 0)}<br>
                Dominant Pressure: ${safe(data.iceberg?.dominant_pressure)}
            `)}

            ${section("gann", "Gann Timing", `
                Day Count: ${safe(data.gann?.day_count)}<br>
                Bar Count: ${safe(data.gann?.bar_count)}<br>
                Angle Alignment: ${safe(data.gann?.angle_alignment)}<br>
                Square Level: ${safe(data.gann?.square_level)}
            `)}

            ${section("astro", "Astro Cycles", `
                Active Cycle: ${safe(data.astro?.cycle_active)}<br>
                Alignment: ${safe(data.astro?.planetary_alignment)}<br>
                Phase: ${safe(data.astro?.phase)}<br>
                Window: ${safe(data.astro?.window)}
            `)}

            ${section("news", "News Bias", `
                News Bias: ${safe(data.news?.news_bias)}<br>
                Volatility: ${safe(data.news?.volatility_expected)}<br>
                High Impact: ${safe(data.news?.high_impact)}<br>
                Trade Halt: ${boolText(!!data.news?.trade_halt)}
            `)}

            ${section("reasoning", "Institutional Reasoning", `${safe(data.institutional_reasoning)}`)}

            ${section("justification", "Trade Justification", `${safe(data.trade_justification)}`)}

            ${section("risk", "Risk Explanation", `
                Risk %: ${safe(data.risk?.risk_percent, 0)}<br>
                RR Ratio: ${safe(data.risk?.rr_ratio)}<br>
                Max Loss Today: ${safe(data.risk?.max_loss_today)}<br>
                Risk Mode: ${safe(data.risk?.risk_mode)}
            `)}

            ${section("verdict", "Final Verdict", `
                <b>${safe(data.verdict)}</b><br>
                Confidence: ${safe(data.confidence, 0)}%<br>
                Recommended Side: ${sideBadge(safe(data.recommended_side, "WAIT"))}
            `)}
        `;

        attachSectionListeners();
    } catch (error) {
        mentorMeta.textContent = `Mentor unavailable for ${activeSymbol}`;
        updateChartSideBadge("WAIT");
        mentorContent.innerHTML = section(
            "verdict",
            "Mentor Status",
            `Service error: ${safe(error.message, "Unknown error")}`
        );
        attachSectionListeners();
    }
};

syncMentorDrawerState();
