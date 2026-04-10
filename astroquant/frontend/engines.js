(function mclEnginesPanelBootstrap() {
    const PANEL_ID = "mclEnginesPanel";
    const DEFAULT_SYMBOL = "XAUUSD";
    const DEFAULT_TIMEFRAME = "1d";

    function normalizeSymbol(v) {
        return String(v || "").trim().toUpperCase() || DEFAULT_SYMBOL;
    }
    function normalizeTimeframe(v) {
        return String(v || "").trim().toLowerCase() || DEFAULT_TIMEFRAME;
    }
    function chartSymbolOrDefault() {
        const el = document.getElementById("chartSymbolInput") || document.getElementById("chartSymbol");
        return normalizeSymbol(el ? el.value : DEFAULT_SYMBOL);
    }
    function chartTimeframeOrDefault() {
        const el = document.getElementById("chartTimeframe");
        return normalizeTimeframe(el ? el.value : DEFAULT_TIMEFRAME);
    }
    function setText(id, value) {
        const el = document.getElementById(id);
        if (el) el.textContent = value;
    }
    function setHtml(id, html) {
        const el = document.getElementById(id);
        if (el) el.innerHTML = html;
    }
    function fmt(v, decimals) {
        if (v == null) return "--";
        if (typeof decimals === "number") return Number(v).toFixed(decimals);
        return String(v);
    }
    function fmtBool(v) {
        if (v == null) return "--";
        return v ? "YES" : "NO";
    }
    function fmtPct(v, decimals) {
        if (v == null) return "--";
        return `${(Number(v) * 100).toFixed(decimals ?? 1)}%`;
    }
    function rowsHtml(pairs) {
        return pairs
            .map(([label, val]) => `<div><span>${label}</span><strong>${val}</strong></div>`)
            .join("");
    }
    function sectionHtml(title, inner) {
        return `
            <div class="eng-section" style="margin-top:8px;border-top:1px solid var(--border);padding-top:6px;">
                <div style="color:var(--muted);font-size:11px;font-weight:600;letter-spacing:0.05em;text-transform:uppercase;margin-bottom:4px;">${title}</div>
                <div class="row-list" style="display:grid;grid-template-columns:1fr 1fr;gap:4px;">
                    ${inner}
                </div>
            </div>`;
    }
    function kvHtml(obj) {
        if (!obj || typeof obj !== "object") return "<em style='color:var(--muted)'>—</em>";
        return Object.entries(obj)
            .slice(0, 12)
            .map(([k, v]) => {
                const val = (v != null && typeof v === "object") ? JSON.stringify(v).slice(0, 80) : String(v ?? "--");
                return `<div><span>${k.replaceAll("_", " ")}</span><strong style="word-break:break-all;">${val}</strong></div>`;
            })
            .join("");
    }

    function selectedContext() {
        const sym = document.getElementById("mclEngSymbolInput");
        const tf = document.getElementById("mclEngTimeframeSelect");
        return {
            symbol: normalizeSymbol(sym ? sym.value : chartSymbolOrDefault()),
            timeframe: normalizeTimeframe(tf ? tf.value : chartTimeframeOrDefault()),
        };
    }

    function syncContextWithChart() {
        const sym = document.getElementById("mclEngSymbolInput");
        const tf = document.getElementById("mclEngTimeframeSelect");
        if (sym) sym.value = chartSymbolOrDefault();
        if (tf) tf.value = chartTimeframeOrDefault();
    }

    async function loadEngines() {
        const statusEl = document.getElementById("mclEngStatus");
        if (statusEl) statusEl.textContent = "Loading…";

        try {
            const { symbol, timeframe } = selectedContext();
            const params = new URLSearchParams({ symbol, timeframe });
            const res = await apiFetch(`/market_causality/engines?${params.toString()}`, {}, 20000);
            const d = await res.json();

            if (d.status === "no_cache") {
                if (statusEl) statusEl.textContent = "No cache — open MCL Insight first";
                return;
            }
            if (statusEl) statusEl.textContent = `OK · ${symbol} ${String(timeframe).toUpperCase()}`;

            // State
            setText("mclEng_signal", d.signal || "--");
            setText("mclEng_confidence", d.confidence != null ? Number(d.confidence).toFixed(3) : "--");
            setText("mclEng_quality", d.quality || "--");
            setText("mclEng_clarity", d.clarity || "--");
            setText("mclEng_conviction", d.conviction != null ? String(d.conviction) : "--");
            setText("mclEng_bias", d.bias_label ? `${d.bias_label} (${d.bias_score})` : "--");
            setText("mclEng_phase", (d.state || {}).phase || "--");
            setText("mclEng_dominance", d.dominance_score != null ? String(d.dominance_score) : "--");
            setText("mclEng_rows", d.rows_analyzed != null ? String(d.rows_analyzed) : "--");

            // Physics
            const ph = d.physics || {};
            setHtml("mclEng_physics", rowsHtml([
                ["Force", fmt(ph.force)],
                ["Velocity", fmt(ph.velocity)],
                ["Energy", fmt(ph.energy)],
            ]));

            // Gann
            const g = d.gann || {};
            const gn = d.gann_nodes || {};
            setHtml("mclEng_gann", rowsHtml([
                ["Degree", fmt(g.degree)],
                ["Zone", g.zone || "--"],
                ["Time Cycle", fmt(g.time_cycle)],
                ["P/T Equal", fmt(g.price_time_equal)],
                ["P/T Ratio", fmt(g.price_time_ratio)],
                ["Node Active", fmtBool(gn.node_active)],
                ["Node Type", gn.node_type || "--"],
                ["Node Price", fmt(gn.node_price)],
                ["Time Harmonic", fmt(gn.time_harmonic)],
            ]));

            // Liquidity
            const liq = d.liquidity || {};
            setHtml("mclEng_liquidity", rowsHtml([
                ["Type", liq.type || "--"],
                ["Above", fmt(liq.above)],
                ["Below", fmt(liq.below)],
                ["Sweep", fmtBool(liq.sweep)],
                ["Pool Count", fmt(liq.pool_count)],
            ]));

            // Astro
            const astro = d.astro || {};
            const moon = astro.moon || {};
            const nearby = astro.nearby_event || {};
            setHtml("mclEng_astro", rowsHtml([
                ["Nakshatra", astro.nakshatra_name || "--"],
                ["Nakshatra Cycle", fmt(astro.nakshatra_cycle)],
                ["Strength", fmt(astro.strength)],
                ["Moon Phase", moon.phase_key || "--"],
                ["Moon Illum.", moon.illumination != null ? `${Number(moon.illumination).toFixed(1)}%` : "--"],
                ["Nearby Event", nearby.event_name || nearby.name || "--"],
                ["Event Impact", nearby.impact || "--"],
                ["Event Days", fmt(nearby.days_away)],
            ]));

            // Compression
            const comp = d.compression || {};
            setHtml("mclEng_compression", rowsHtml([
                ["Phase", comp.phase || "--"],
                ["Score", fmt(comp.score)],
                ["Silence Active", fmtBool(comp.silence_active)],
                ["Breakout Near", fmtBool(comp.breakout_near)],
                ["Direction Bias", comp.direction_bias || "--"],
                ["Energy Stored", fmt(comp.energy_stored)],
            ]));

            // Numerology
            const num = d.numerology || {};
            setHtml("mclEng_numerology", rowsHtml([
                ["Number", fmt(num.number)],
                ["Meaning", num.meaning || "--"],
                ["Vibration", num.vibration || "--"],
                ["Cycle", num.cycle || "--"],
            ]));

            // Harmonic
            const harm = d.harmonic || {};
            setHtml("mclEng_harmonic", rowsHtml([
                ["Pattern", harm.pattern || "--"],
                ["Ratio", fmt(harm.ratio)],
                ["Completion %", harm.completion_pct != null ? `${harm.completion_pct}%` : "--"],
                ["Direction", harm.direction || "--"],
                ["Quality", harm.quality || "--"],
            ]));

            // Psychology / Trap / Behavior
            const psy = d.psychology || {};
            const trap = d.trap || {};
            const beh = d.behavior || {};
            setHtml("mclEng_psychology", rowsHtml([
                ["Emotion", psy.emotion || "--"],
                ["Sentiment", psy.sentiment || "--"],
                ["Crowd Bias", psy.crowd_bias || "--"],
                ["Trap Probability", fmt(trap.probability)],
                ["Trap Type", trap.type || "--"],
                ["Behavior Next", beh.next || "--"],
                ["Behavior Mode", beh.mode || "--"],
            ]));

            // Time Signal
            const ts = d.time_signal || {};
            setHtml("mclEng_time", rowsHtml([
                ["Timing", ts.timing || "--"],
                ["Windows", Array.isArray(ts.signals) ? ts.signals.join(", ") : "--"],
                ["Convergence", fmt(ts.convergence)],
            ]));

            // Future
            const fut = d.future || {};
            setHtml("mclEng_future", rowsHtml([
                ["Direction", fut.direction || "--"],
                ["Cycle Event", fut.cycle_event || "--"],
                ["Strength", fmt(fut.strength)],
                ["Cycle Progress", fut.cycle_progress_pct != null ? `${Number(fut.cycle_progress_pct).toFixed(1)}%` : "--"],
                ["Numerology Energy", fmt(fut.numerology_energy)],
                ["Timing Window", fut.timing_window || "--"],
            ]));

            // Execution & Failure
            const exec = d.execution || {};
            const fail = d.failure || {};
            setHtml("mclEng_exec", rowsHtml([
                ["Verdict", exec.verdict || "--"],
                ["Score", fmt(exec.score)],
                ["Issues", Array.isArray(exec.issues) && exec.issues.length ? exec.issues.join("; ") : "none"],
                ["Fail Status", fail.status || "--"],
                ["Fail Severity", fail.severity || "--"],
                ["Fail Issues", Array.isArray(fail.issues) && fail.issues.length ? fail.issues.join("; ") : "none"],
            ]));

            // Backtest
            const bt = d.backtest || {};
            setHtml("mclEng_backtest", rowsHtml([
                ["Win Rate", bt.winrate != null ? fmtPct(bt.winrate) : "--"],
                ["Wins", fmt(bt.wins)],
                ["Losses", fmt(bt.losses)],
                ["Total", bt.wins != null && bt.losses != null ? String(bt.wins + bt.losses) : "--"],
                ["Avg Return", fmt(bt.avg_return)],
                ["Max DD", fmt(bt.max_drawdown)],
            ]));

            // Data Quality / Latency / Timescale
            const dq = d.data_quality || {};
            const lat = d.latency || {};
            const ts2 = d.timescale || {};
            const ov = d.overfit || {};
            setHtml("mclEng_dqSection", rowsHtml([
                ["DQ Score", fmt(dq.score)],
                ["DQ Status", dq.status || "--"],
                ["Latency Verdict", lat.timing_verdict || "--"],
                ["Latency Ms", fmt(lat.total_ms ?? lat.elapsed_ms)],
                ["Timescale Regime", ((ts2.volatility_regime || {}).regime) || "--"],
                ["Overfit Risk", ov.overfit_risk || "--"],
            ]));

            // Weights / Signals
            const weights = d.weights || {};
            const wEntries = Object.entries(weights).slice(0, 12);
            setHtml("mclEng_weights",
                wEntries.length
                    ? wEntries.map(([k, v]) => `<div><span>${k.replaceAll("_", " ")}</span><strong>${Number(v).toFixed(3)}</strong></div>`).join("")
                    : "<div style='color:var(--muted)'>—</div>"
            );

            // Updated timestamp
            if (d.updated_at) {
                const ts3 = new Date(d.updated_at * 1000);
                setText("mclEng_updatedAt", `Updated ${ts3.toLocaleTimeString()}`);
            }

        } catch (err) {
            if (statusEl) statusEl.textContent = `Error: ${err?.message || err}`;
            if (typeof showError === "function") {
                showError("mcl_engines", `MCL Engines load failed: ${err?.message || err}`);
            }
        }
    }

    function ensureEnginesToggleBtn() {
        if (document.getElementById("mclEnginesToggleBtn")) return;
        const anchor = document.getElementById("marketCausalityToggleBtn") || document.getElementById("journalToggleBtn");
        if (!anchor || !anchor.parentElement) return;
        const btn = document.createElement("button");
        btn.id = "mclEnginesToggleBtn";
        btn.textContent = "MCL Engines";
        btn.addEventListener("click", () => toggleEnginesPanel());
        anchor.parentElement.insertBefore(btn, anchor.nextSibling);
    }

    function ensureEnginesPanel() {
        if (document.getElementById(PANEL_ID)) return;

        const panel = document.createElement("div");
        panel.id = PANEL_ID;
        panel.className = "panel";
        panel.style.position = "fixed";
        panel.style.right = "490px";
        panel.style.bottom = "14px";
        panel.style.width = "min(500px, calc(100vw - 28px))";
        panel.style.maxHeight = "80vh";
        panel.style.overflow = "auto";
        panel.style.zIndex = "45";
        panel.style.display = "none";

        panel.innerHTML = `
            <div style="display:flex;justify-content:space-between;align-items:center;gap:8px;margin-bottom:8px;">
                <strong>MCL Engine Deep-Dive</strong>
                <div style="display:flex;gap:6px;">
                    <span id="mclEng_updatedAt" style="color:var(--muted);font-size:11px;align-self:center;"></span>
                    <button id="mclEngRefreshBtn">Refresh</button>
                    <button id="mclEngCloseBtn">Close</button>
                </div>
            </div>
            <div class="row" style="display:flex;gap:6px;align-items:center;margin-bottom:8px;">
                <input id="mclEngSymbolInput" type="text" placeholder="Symbol" style="flex:1;min-width:100px;" />
                <select id="mclEngTimeframeSelect" style="min-width:80px;">
                    <option value="1m">1m</option>
                    <option value="5m">5m</option>
                    <option value="15m">15m</option>
                    <option value="30m">30m</option>
                    <option value="1h">1h</option>
                    <option value="4h">4h</option>
                    <option value="1d" selected>1d</option>
                    <option value="1w">1w</option>
                    <option value="1month">1month</option>
                </select>
                <button id="mclEngUseChartBtn" title="Use current chart context">Chart</button>
            </div>
            <div style="font-size:12px;color:var(--muted);margin-bottom:6px;" id="mclEngStatus">—</div>

            <!-- Core State -->
            <div class="row-list" style="display:grid;grid-template-columns:repeat(3,1fr);gap:6px;padding-bottom:8px;">
                <div><span>Signal</span><strong id="mclEng_signal">--</strong></div>
                <div><span>Confidence</span><strong id="mclEng_confidence">--</strong></div>
                <div><span>Quality</span><strong id="mclEng_quality">--</strong></div>
                <div><span>Clarity</span><strong id="mclEng_clarity">--</strong></div>
                <div><span>Conviction</span><strong id="mclEng_conviction">--</strong></div>
                <div><span>Bias</span><strong id="mclEng_bias">--</strong></div>
                <div><span>Phase</span><strong id="mclEng_phase">--</strong></div>
                <div><span>Dominance</span><strong id="mclEng_dominance">--</strong></div>
                <div><span>Rows</span><strong id="mclEng_rows">--</strong></div>
            </div>

            <!-- Per-engine sections -->
            <div style="margin-top:8px;border-top:1px solid var(--border);padding-top:6px;">
                <div style="color:var(--muted);font-size:11px;font-weight:600;letter-spacing:0.05em;text-transform:uppercase;margin-bottom:4px;">Framework 1 — Market Physics</div>
                <div class="row-list" style="display:grid;grid-template-columns:1fr 1fr;gap:4px;" id="mclEng_physics"></div>
            </div>
            <div style="margin-top:8px;border-top:1px solid var(--border);padding-top:6px;">
                <div style="color:var(--muted);font-size:11px;font-weight:600;letter-spacing:0.05em;text-transform:uppercase;margin-bottom:4px;">Framework 2 — W.D. Gann</div>
                <div class="row-list" style="display:grid;grid-template-columns:1fr 1fr;gap:4px;" id="mclEng_gann"></div>
            </div>
            <div style="margin-top:8px;border-top:1px solid var(--border);padding-top:6px;">
                <div style="color:var(--muted);font-size:11px;font-weight:600;letter-spacing:0.05em;text-transform:uppercase;margin-bottom:4px;">Framework 3 — ICT / SMC Liquidity</div>
                <div class="row-list" style="display:grid;grid-template-columns:1fr 1fr;gap:4px;" id="mclEng_liquidity"></div>
            </div>
            <div style="margin-top:8px;border-top:1px solid var(--border);padding-top:6px;">
                <div style="color:var(--muted);font-size:11px;font-weight:600;letter-spacing:0.05em;text-transform:uppercase;margin-bottom:4px;">Framework 5 — Vedic Astrology + Moon</div>
                <div class="row-list" style="display:grid;grid-template-columns:1fr 1fr;gap:4px;" id="mclEng_astro"></div>
            </div>
            <div style="margin-top:8px;border-top:1px solid var(--border);padding-top:6px;">
                <div style="color:var(--muted);font-size:11px;font-weight:600;letter-spacing:0.05em;text-transform:uppercase;margin-bottom:4px;">Framework 6 — Time Compression</div>
                <div class="row-list" style="display:grid;grid-template-columns:1fr 1fr;gap:4px;" id="mclEng_compression"></div>
            </div>
            <div style="margin-top:8px;border-top:1px solid var(--border);padding-top:6px;">
                <div style="color:var(--muted);font-size:11px;font-weight:600;letter-spacing:0.05em;text-transform:uppercase;margin-bottom:4px;">Framework 7 — Pythagorean Numerology</div>
                <div class="row-list" style="display:grid;grid-template-columns:1fr 1fr;gap:4px;" id="mclEng_numerology"></div>
            </div>
            <div style="margin-top:8px;border-top:1px solid var(--border);padding-top:6px;">
                <div style="color:var(--muted);font-size:11px;font-weight:600;letter-spacing:0.05em;text-transform:uppercase;margin-bottom:4px;">Framework 8 — Harmonic Patterns</div>
                <div class="row-list" style="display:grid;grid-template-columns:1fr 1fr;gap:4px;" id="mclEng_harmonic"></div>
            </div>
            <div style="margin-top:8px;border-top:1px solid var(--border);padding-top:6px;">
                <div style="color:var(--muted);font-size:11px;font-weight:600;letter-spacing:0.05em;text-transform:uppercase;margin-bottom:4px;">Framework 9 — Psychology / Trap / Behavior</div>
                <div class="row-list" style="display:grid;grid-template-columns:1fr 1fr;gap:4px;" id="mclEng_psychology"></div>
            </div>
            <div style="margin-top:8px;border-top:1px solid var(--border);padding-top:6px;">
                <div style="color:var(--muted);font-size:11px;font-weight:600;letter-spacing:0.05em;text-transform:uppercase;margin-bottom:4px;">Time Convergence Engine</div>
                <div class="row-list" style="display:grid;grid-template-columns:1fr 1fr;gap:4px;" id="mclEng_time"></div>
            </div>
            <div style="margin-top:8px;border-top:1px solid var(--border);padding-top:6px;">
                <div style="color:var(--muted);font-size:11px;font-weight:600;letter-spacing:0.05em;text-transform:uppercase;margin-bottom:4px;">Gann Cycle Future Projection</div>
                <div class="row-list" style="display:grid;grid-template-columns:1fr 1fr;gap:4px;" id="mclEng_future"></div>
            </div>
            <div style="margin-top:8px;border-top:1px solid var(--border);padding-top:6px;">
                <div style="color:var(--muted);font-size:11px;font-weight:600;letter-spacing:0.05em;text-transform:uppercase;margin-bottom:4px;">Execution + Failure Analysis</div>
                <div class="row-list" style="display:grid;grid-template-columns:1fr 1fr;gap:4px;" id="mclEng_exec"></div>
            </div>
            <div style="margin-top:8px;border-top:1px solid var(--border);padding-top:6px;">
                <div style="color:var(--muted);font-size:11px;font-weight:600;letter-spacing:0.05em;text-transform:uppercase;margin-bottom:4px;">Backtest Memory</div>
                <div class="row-list" style="display:grid;grid-template-columns:1fr 1fr;gap:4px;" id="mclEng_backtest"></div>
            </div>
            <div style="margin-top:8px;border-top:1px solid var(--border);padding-top:6px;">
                <div style="color:var(--muted);font-size:11px;font-weight:600;letter-spacing:0.05em;text-transform:uppercase;margin-bottom:4px;">Data Quality / Precision</div>
                <div class="row-list" style="display:grid;grid-template-columns:1fr 1fr;gap:4px;" id="mclEng_dqSection"></div>
            </div>
            <div style="margin-top:8px;border-top:1px solid var(--border);padding-top:6px;">
                <div style="color:var(--muted);font-size:11px;font-weight:600;letter-spacing:0.05em;text-transform:uppercase;margin-bottom:4px;">Framework Weights</div>
                <div class="row-list" style="display:grid;grid-template-columns:1fr 1fr;gap:4px;" id="mclEng_weights"></div>
            </div>
        `;

        document.body.appendChild(panel);

        const refreshBtn = document.getElementById("mclEngRefreshBtn");
        if (refreshBtn) refreshBtn.addEventListener("click", () => loadEngines());

        const chartBtn = document.getElementById("mclEngUseChartBtn");
        if (chartBtn) chartBtn.addEventListener("click", () => { syncContextWithChart(); loadEngines(); });

        const symInput = document.getElementById("mclEngSymbolInput");
        if (symInput) {
            symInput.addEventListener("change", () => loadEngines());
            symInput.addEventListener("keyup", (e) => { if (e.key === "Enter") loadEngines(); });
        }

        const tfSelect = document.getElementById("mclEngTimeframeSelect");
        if (tfSelect) tfSelect.addEventListener("change", () => loadEngines());

        const closeBtn = document.getElementById("mclEngCloseBtn");
        if (closeBtn) closeBtn.addEventListener("click", () => toggleEnginesPanel(false));

        syncContextWithChart();
    }

    function toggleEnginesPanel(force) {
        const panel = document.getElementById(PANEL_ID);
        if (!panel) return;
        const shouldOpen = typeof force === "boolean" ? force : panel.style.display === "none";
        panel.style.display = shouldOpen ? "block" : "none";
        if (shouldOpen) {
            syncContextWithChart();
            loadEngines();
        }
    }

    ensureEnginesToggleBtn();
    ensureEnginesPanel();

    if (typeof setSingletonInterval === "function") {
        setSingletonInterval("mclEnginesPanelRefresh", () => {
            const panel = document.getElementById(PANEL_ID);
            if (panel && panel.style.display !== "none") loadEngines();
        }, 15000);
    } else {
        setInterval(() => {
            const panel = document.getElementById(PANEL_ID);
            if (panel && panel.style.display !== "none") loadEngines();
        }, 15000);
    }

    window.toggleMclEnginesPanel = toggleEnginesPanel;
})();
