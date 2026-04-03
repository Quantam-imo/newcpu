(function marketCausalityPanelBootstrap() {
    const PANEL_ID = "marketCausalityPanel";
    const PANEL_OPEN_CLASS = "open";
    const DEFAULT_SYMBOL = "XAUUSD";
    const DEFAULT_TIMEFRAME = "1d";
    const DEFAULT_LOOKBACK_YEARS = 25;
    const DEFAULT_SOURCE_MODE = "historical_first";

    function normalizeSymbol(value) {
        return String(value || "").trim().toUpperCase() || DEFAULT_SYMBOL;
    }

    function normalizeTimeframe(value) {
        return String(value || "").trim().toLowerCase() || DEFAULT_TIMEFRAME;
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

    function setWhyTone(tone) {
        const el = document.getElementById("mclWhyCard");
        if (!el) return;
        const normalized = String(tone || "neutral").toLowerCase();
        let border = "#7f8c8d";
        let bg = "rgba(127, 140, 141, 0.10)";
        if (normalized === "bullish") {
            border = "#1f7a4c";
            bg = "rgba(31, 122, 76, 0.12)";
        } else if (normalized === "bearish") {
            border = "#9f2d2d";
            bg = "rgba(159, 45, 45, 0.12)";
        } else if (normalized === "caution") {
            border = "#9a6b16";
            bg = "rgba(154, 107, 22, 0.12)";
        }
        el.style.border = `1px solid ${border}`;
        el.style.background = bg;
    }

    function selectedContext() {
        const symbolInput = document.getElementById("mclSymbolInput");
        const timeframeSelect = document.getElementById("mclTimeframeSelect");
        return {
            symbol: normalizeSymbol(symbolInput ? symbolInput.value : chartSymbolOrDefault()),
            timeframe: normalizeTimeframe(timeframeSelect ? timeframeSelect.value : chartTimeframeOrDefault()),
        };
    }

    function syncContextWithChart() {
        const symbolInput = document.getElementById("mclSymbolInput");
        const timeframeSelect = document.getElementById("mclTimeframeSelect");
        if (symbolInput) {
            symbolInput.value = chartSymbolOrDefault();
        }
        if (timeframeSelect) {
            timeframeSelect.value = chartTimeframeOrDefault();
        }
    }

    async function loadSummary(forceRefresh = false) {
        try {
            const { symbol, timeframe } = selectedContext();
            const params = new URLSearchParams();
            if (forceRefresh) params.set("refresh", "true");
            params.set("symbol", symbol);
            params.set("timeframe", timeframe);
            params.set("lookback_years", String(DEFAULT_LOOKBACK_YEARS));
            params.set("source_mode", DEFAULT_SOURCE_MODE);
            const q = `?${params.toString()}`;
            const res = await apiFetch(`/market_causality/summary${q}`, {}, 20000);
            const data = await res.json();

            setText("mclStatus", String(data.status || "--").toUpperCase());
            setText("mclSignal", data.signal || "--");
            setText("mclConfidence", data.confidence != null ? Number(data.confidence).toFixed(3) : "--");
            setText("mclQuality", data.quality || "--");
            setText("mclPhase", data.phase || "--");
            setText("mclTrend", data.trend || "--");
            setText("mclTrap", data.trap || "--");
            setText("mclReliability", data.reliability_score != null ? String(data.reliability_score) : "--");
            setText("mclBias", data.bias_label ? `${data.bias_label} (${data.bias_score})` : "--");
            setText("mclNewsGuard", data.news_guard_applied ? "ON" : "OFF");
            setText("mclRejection", data.rejection_reason || "none");
            setText("mclInstitutional", data.institutional_decision || "--");
            setText("mclInstitutionalScore", data.institutional_score != null ? String(data.institutional_score) : "--");
            setText("mclSource", data.source || "--");
            setText("mclLatency", data.elapsed_ms != null ? `${data.elapsed_ms} ms` : "--");

            const alignment = data.instrument_alignment || {};
            setText("mclRequested", `${alignment.requested_symbol || symbol} ${String(alignment.requested_timeframe || timeframe).toUpperCase()}`);
            setText("mclApplied", `${alignment.applied_symbol || "--"} ${String(alignment.applied_timeframe || "--").toUpperCase()}`);
            setText("mclLookback", `${data.lookback_years != null ? data.lookback_years : DEFAULT_LOOKBACK_YEARS}y`);
            setText("mclRows", data.rows_analyzed != null ? String(data.rows_analyzed) : "--");
            setText("mclDepth", data.historical_depth_years != null ? `${data.historical_depth_years}y` : "--");
            setText("mclDepthTarget", data.lookback_target_met ? "MET" : "NOT MET");
            setText("mclFallback", data.timeframe_fallback_applied ? "YES" : "NO");
            setText("mclFallbackReason", data.timeframe_fallback_reason || "none");
            setText("mclObsTrendStart", data.observation_trend_start_time || "--");
            setText("mclObsLatest", data.observation_latest_time || "--");
            setText("mclObsPrevEvent", data.observation_news_previous_time || "--");
            setText("mclObsNextEvent", data.observation_news_next_time || "--");
            setText("mclObsGann", data.observation_gann_degree != null ? String(data.observation_gann_degree) : "--");
            setText("mclObsGeom", data.observation_geometry_angle_deg != null ? String(data.observation_geometry_angle_deg) : "--");
            setText("mclObsPhys", data.observation_physics_velocity != null ? String(data.observation_physics_velocity) : "--");
            setText("mclObsPTR", data.observation_price_time_ratio != null ? String(data.observation_price_time_ratio) : "--");
            setText("mclObsDTR", data.observation_degree_time_ratio != null ? String(data.observation_degree_time_ratio) : "--");
            setText("mclAnalysisStart", data.analysis_started_at_utc || "--");
            setText("mclAnalysisEnd", data.analysis_completed_at_utc || "--");
            setText("mclAnalysisElapsed", data.analysis_elapsed_ms != null ? `${data.analysis_elapsed_ms} ms` : "--");
            setText("mclReasoningSummary", data.reasoning_summary || "--");
            setText("mclSlowestStage", data.slowest_process_stage?.name ? `${String(data.slowest_process_stage.name).replaceAll("_", " ")} (${data.slowest_process_stage.elapsed_ms} ms)` : "--");
            setText("mclWhyTitle", data.reasoning_tone ? String(data.reasoning_tone).toUpperCase() : "NEUTRAL");
            setText("mclWhySummary", data.reasoning_summary || "--");
            setWhyTone(data.reasoning_tone || "neutral");
            setText("mclDeltaSignal", data.reasoning_delta?.has_previous
                ? `${data.reasoning_delta.previous_signal || "--"} -> ${data.signal || "--"}${data.reasoning_delta.signal_changed ? " (CHANGED)" : " (UNCHANGED)"}`
                : "--");

            const reasoningChainEl = document.getElementById("mclReasoningChain");
            if (reasoningChainEl) {
                const chain = Array.isArray(data.reasoning_chain) ? data.reasoning_chain : [];
                reasoningChainEl.innerHTML = chain.length
                    ? chain.map((item) => `<li>${String(item)}</li>`).join("")
                    : "<li>--</li>";
            }

            const lifecycleStagesEl = document.getElementById("mclLifecycleStages");
            if (lifecycleStagesEl) {
                const stages = Array.isArray(data.analysis_lifecycle?.stages) ? data.analysis_lifecycle.stages : [];
                lifecycleStagesEl.innerHTML = stages.length
                    ? stages.map((stage) => {
                        const name = String(stage.name || "unknown_stage").replaceAll("_", " ");
                        const status = String(stage.status || "unknown").toUpperCase();
                        const elapsed = stage.elapsed_ms != null ? `${stage.elapsed_ms} ms` : "--";
                        const detail = String(stage.detail || "--");
                        return `<li><strong>${name}</strong> | ${status} | ${elapsed}<br><span style="color:var(--muted)">${detail}</span></li>`;
                    }).join("")
                    : "<li>--</li>";
            }

            const processTimingEl = document.getElementById("mclProcessTiming");
            if (processTimingEl) {
                const timings = Array.isArray(data.process_timing) ? data.process_timing : [];
                processTimingEl.innerHTML = timings.length
                    ? timings.map((stage) => {
                        const name = String(stage.name || "unknown_stage").replaceAll("_", " ");
                        const elapsed = stage.elapsed_ms != null ? `${stage.elapsed_ms} ms` : "--";
                        return `<li><strong>${name}</strong> | ${elapsed}</li>`;
                    }).join("")
                    : "<li>--</li>";
            }

            const topDriversEl = document.getElementById("mclTopDrivers");
            if (topDriversEl) {
                const drivers = Array.isArray(data.reasoning_top_drivers) ? data.reasoning_top_drivers : [];
                topDriversEl.innerHTML = drivers.length
                    ? drivers.slice(0, 5).map((driver) => {
                        const label = String(driver.label || "driver").replaceAll("_", " ");
                        const value = String(driver.value || "--");
                        const pct = driver.score_pct != null ? `${driver.score_pct}%` : "--";
                        const score = driver.score != null ? String(driver.score) : "--";
                        return `<li><strong>${label}</strong> | ${value} | contribution ${pct} (w=${score})</li>`;
                    }).join("")
                    : "<li>--</li>";
            }

            const deltaDriversEl = document.getElementById("mclDeltaDrivers");
            if (deltaDriversEl) {
                const deltas = Array.isArray(data.reasoning_delta?.top_driver_deltas) ? data.reasoning_delta.top_driver_deltas : [];
                deltaDriversEl.innerHTML = deltas.length
                    ? deltas.slice(0, 5).map((item) => {
                        const label = String(item.label || "driver").replaceAll("_", " ");
                        const curr = item.current_pct != null ? `${item.current_pct}%` : "--";
                        const prev = item.previous_pct != null ? `${item.previous_pct}%` : "--";
                        const delta = item.delta_pct != null ? `${item.delta_pct >= 0 ? "+" : ""}${item.delta_pct}%` : "--";
                        return `<li><strong>${label}</strong> | ${prev} -> ${curr} | delta ${delta}</li>`;
                    }).join("")
                    : "<li>--</li>";
            }

            const tl = data.trade_levels || null;
            setText("mclTradeLevels", tl ? `Entry ${tl.entry} | SL ${tl.stop_loss} | TP ${tl.take_profit} | R ${tl.r_ratio}` : "--");
        } catch (err) {
            setText("mclStatus", "ERROR");
            setText("mclSignal", "--");
            setText("mclLatency", "--");
            if (typeof showError === "function") {
                showError("mcl_panel", `Market Causality load failed: ${err?.message || err}`);
            }
        }
    }

    function ensureToggleButton() {
        if (document.getElementById("marketCausalityToggleBtn")) return;
        const anchor = document.getElementById("journalToggleBtn");
        if (!anchor || !anchor.parentElement) return;

        const btn = document.createElement("button");
        btn.id = "marketCausalityToggleBtn";
        btn.textContent = "MCL Insight";
        btn.addEventListener("click", () => togglePanel());
        anchor.parentElement.insertBefore(btn, anchor.nextSibling);
    }

    function ensurePanel() {
        if (document.getElementById(PANEL_ID)) return;

        const panel = document.createElement("div");
        panel.id = PANEL_ID;
        panel.className = "panel";
        panel.style.position = "fixed";
        panel.style.right = "14px";
        panel.style.bottom = "14px";
        panel.style.width = "min(460px, calc(100vw - 28px))";
        panel.style.maxHeight = "42vh";
        panel.style.overflow = "auto";
        panel.style.zIndex = "46";
        panel.style.display = "none";

        panel.innerHTML = `
            <div style="display:flex;justify-content:space-between;align-items:center;gap:8px;margin-bottom:8px;">
                <strong>Market Causality Intelligence</strong>
                <div style="display:flex;gap:6px;">
                    <button id="mclRefreshBtn">Refresh</button>
                    <button id="mclCloseBtn">Close</button>
                </div>
            </div>
            <div class="row" style="display:flex;gap:6px;align-items:center;margin-bottom:8px;">
                <input id="mclSymbolInput" type="text" placeholder="Symbol" style="flex:1;min-width:120px;" />
                <select id="mclTimeframeSelect" style="min-width:90px;">
                    <option value="1m">1m</option>
                    <option value="5m">5m</option>
                    <option value="15m">15m</option>
                    <option value="1h">1h</option>
                    <option value="4h">4h</option>
                    <option value="1d">1d</option>
                </select>
                <button id="mclUseChartContextBtn" title="Use current chart symbol/timeframe">Use Chart</button>
            </div>
            <div id="mclWhyCard" style="margin-bottom:8px;border:1px solid #7f8c8d;background:rgba(127, 140, 141, 0.10);padding:10px;border-radius:8px;">
                <div style="display:flex;justify-content:space-between;gap:8px;align-items:center;">
                    <strong>Why This Signal</strong>
                    <strong id="mclWhyTitle">NEUTRAL</strong>
                </div>
                <div id="mclWhySummary" style="margin-top:6px;line-height:1.45;">--</div>
                <ul id="mclTopDrivers" style="margin:8px 0 0 18px;padding:0;line-height:1.45;"><li>--</li></ul>
                <div style="color:var(--muted);font-size:12px;margin-top:8px;">Delta vs Previous</div>
                <div id="mclDeltaSignal" style="margin-top:4px;line-height:1.45;">--</div>
                <ul id="mclDeltaDrivers" style="margin:8px 0 0 18px;padding:0;line-height:1.45;"><li>--</li></ul>
            </div>
            <div class="row-list" style="display:grid;grid-template-columns:1fr 1fr;gap:6px;">
                <div><span>Status</span><strong id="mclStatus">--</strong></div>
                <div><span>Signal</span><strong id="mclSignal">--</strong></div>
                <div><span>Confidence</span><strong id="mclConfidence">--</strong></div>
                <div><span>Quality</span><strong id="mclQuality">--</strong></div>
                <div><span>Phase</span><strong id="mclPhase">--</strong></div>
                <div><span>Trend</span><strong id="mclTrend">--</strong></div>
                <div><span>Trap</span><strong id="mclTrap">--</strong></div>
                <div><span>Reliability</span><strong id="mclReliability">--</strong></div>
                <div><span>Bias</span><strong id="mclBias">--</strong></div>
                <div><span>News Guard</span><strong id="mclNewsGuard">--</strong></div>
                <div><span>Rejection</span><strong id="mclRejection">--</strong></div>
                <div><span>Institutional</span><strong id="mclInstitutional">--</strong></div>
                <div><span>Inst. Score</span><strong id="mclInstitutionalScore">--</strong></div>
                <div><span>Source</span><strong id="mclSource">--</strong></div>
                <div><span>Pipeline Time</span><strong id="mclLatency">--</strong></div>
                <div><span>Requested</span><strong id="mclRequested">--</strong></div>
                <div><span>Applied</span><strong id="mclApplied">--</strong></div>
                <div><span>Lookback</span><strong id="mclLookback">--</strong></div>
                <div><span>Rows</span><strong id="mclRows">--</strong></div>
                <div><span>Depth</span><strong id="mclDepth">--</strong></div>
                <div><span>Depth Target</span><strong id="mclDepthTarget">--</strong></div>
                <div><span>Fallback</span><strong id="mclFallback">--</strong></div>
                <div><span>Fallback Reason</span><strong id="mclFallbackReason">--</strong></div>
            </div>
            <div style="margin-top:8px;border-top:1px solid var(--border);padding-top:8px;">
                <div style="color:var(--muted);font-size:12px;">Trade Levels</div>
                <div id="mclTradeLevels" style="font-weight:600;">--</div>
            </div>
            <div style="margin-top:8px;border-top:1px solid var(--border);padding-top:8px;">
                <div style="color:var(--muted);font-size:12px;">Observation Telemetry</div>
                <div class="row-list" style="display:grid;grid-template-columns:1fr 1fr;gap:6px;">
                    <div><span>Trend Start</span><strong id="mclObsTrendStart">--</strong></div>
                    <div><span>Latest Bar</span><strong id="mclObsLatest">--</strong></div>
                    <div><span>Prev Event</span><strong id="mclObsPrevEvent">--</strong></div>
                    <div><span>Next Event</span><strong id="mclObsNextEvent">--</strong></div>
                    <div><span>Gann Degree</span><strong id="mclObsGann">--</strong></div>
                    <div><span>Geometry Angle</span><strong id="mclObsGeom">--</strong></div>
                    <div><span>Physics Velocity</span><strong id="mclObsPhys">--</strong></div>
                    <div><span>Price/Time</span><strong id="mclObsPTR">--</strong></div>
                    <div><span>Degree/Time</span><strong id="mclObsDTR">--</strong></div>
                </div>
            </div>
            <div style="margin-top:8px;border-top:1px solid var(--border);padding-top:8px;">
                <div style="color:var(--muted);font-size:12px;">Analysis Lifecycle</div>
                <div class="row-list" style="display:grid;grid-template-columns:1fr 1fr;gap:6px;">
                    <div><span>Started</span><strong id="mclAnalysisStart">--</strong></div>
                    <div><span>Completed</span><strong id="mclAnalysisEnd">--</strong></div>
                    <div><span>Elapsed</span><strong id="mclAnalysisElapsed">--</strong></div>
                    <div><span>Slowest Stage</span><strong id="mclSlowestStage">--</strong></div>
                </div>
                <ul id="mclLifecycleStages" style="margin:8px 0 0 18px;padding:0;line-height:1.45;"><li>--</li></ul>
                <div style="color:var(--muted);font-size:12px;margin-top:8px;">Internal Engine Timing</div>
                <ul id="mclProcessTiming" style="margin:8px 0 0 18px;padding:0;line-height:1.45;"><li>--</li></ul>
            </div>
            <div style="margin-top:8px;border-top:1px solid var(--border);padding-top:8px;">
                <div style="color:var(--muted);font-size:12px;">Reasoning Summary</div>
                <div id="mclReasoningSummary" style="font-weight:600;line-height:1.45;">--</div>
                <ul id="mclReasoningChain" style="margin:8px 0 0 18px;padding:0;line-height:1.45;"><li>--</li></ul>
            </div>
        `;

        document.body.appendChild(panel);

        const refreshBtn = document.getElementById("mclRefreshBtn");
        if (refreshBtn) refreshBtn.addEventListener("click", () => loadSummary(true));

        const useChartContextBtn = document.getElementById("mclUseChartContextBtn");
        if (useChartContextBtn) {
            useChartContextBtn.addEventListener("click", () => {
                syncContextWithChart();
                loadSummary(true);
            });
        }

        const symbolInput = document.getElementById("mclSymbolInput");
        if (symbolInput) {
            symbolInput.addEventListener("change", () => loadSummary(true));
            symbolInput.addEventListener("keyup", (e) => {
                if (e.key === "Enter") loadSummary(true);
            });
        }

        const timeframeSelect = document.getElementById("mclTimeframeSelect");
        if (timeframeSelect) {
            timeframeSelect.addEventListener("change", () => loadSummary(true));
        }

        const closeBtn = document.getElementById("mclCloseBtn");
        if (closeBtn) closeBtn.addEventListener("click", () => togglePanel(false));

        syncContextWithChart();
    }

    function togglePanel(force) {
        const panel = document.getElementById(PANEL_ID);
        if (!panel) return;

        const shouldOpen = typeof force === "boolean" ? force : panel.style.display === "none";
        panel.style.display = shouldOpen ? "block" : "none";
        panel.classList.toggle(PANEL_OPEN_CLASS, shouldOpen);

        if (shouldOpen) {
            syncContextWithChart();
            loadSummary(false);
        }
    }

    ensureToggleButton();
    ensurePanel();

    if (typeof setSingletonInterval === "function") {
        setSingletonInterval("marketCausalityPanelRefresh", () => {
            const panel = document.getElementById(PANEL_ID);
            if (panel && panel.style.display !== "none") {
                loadSummary(false);
            }
        }, 15000);
    } else {
        setInterval(() => {
            const panel = document.getElementById(PANEL_ID);
            if (panel && panel.style.display !== "none") {
                loadSummary(false);
            }
        }, 15000);
    }

    window.toggleMarketCausalityPanel = togglePanel;
})();
