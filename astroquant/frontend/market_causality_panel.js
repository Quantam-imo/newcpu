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

    function setOperationalState(status, errorMsg) {
        const normalized = String(status || "").toLowerCase();
        if (normalized === "timeout" || normalized === "stale_timeout" || normalized === "error") {
            setWhyTone("caution");
            if (typeof showError === "function") {
                const msg = errorMsg ? `MCL degraded: ${errorMsg}` : `MCL degraded (${String(status || "unknown").toUpperCase()})`;
                showError("mcl_panel", msg);
            }
        }
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

    async function loadModelStatus() {
        // Fetch training status and model calibration in parallel
        try {
            const [tsRes, calRes] = await Promise.allSettled([
                apiFetch("/market_causality/system/training-status", {}, 8000),
                apiFetch("/market_causality/system/model-calibration", {}, 8000),
            ]);

            // Training status
            if (tsRes.status === "fulfilled") {
                const d = await tsRes.value.json();
                const el = document.getElementById("mclTrainingStatus");
                if (el) {
                    const statusColors = { ALL_READY: "#10b981", PARTIAL: "#fbbf24", NOT_READY: "#ef4444", UNKNOWN: "#6b7280" };
                    const color = statusColors[d.status] || "#6b7280";
                    const ready = d.ready_models ?? "--";
                    const total = d.total_models ?? "--";
                    el.innerHTML = `<span style="color:${color};font-weight:700;">${d.status || "--"}</span> <span style="color:#94a3b8">${ready}/${total} models</span>`;
                }
                const tfEl = document.getElementById("mclTrainingTFs");
                if (tfEl && d.timeframes) {
                    const tfs = Object.entries(d.timeframes);
                    tfEl.innerHTML = tfs.map(([tf, info]) => {
                        const rdy = info.ready;
                        const ver = info.version || "--";
                        const col = rdy ? "#10b981" : "#ef4444";
                        return `<span style="color:${col};margin-right:6px;">${tf.toUpperCase()}${rdy ? "✓" : "✗"}(${ver})</span>`;
                    }).join("");
                }
                // Update header badge
                const badge = document.getElementById("mclModelBadge");
                if (badge) {
                    const statusColors = { ALL_READY: "#10b981", PARTIAL: "#fbbf24", NOT_READY: "#ef4444", UNKNOWN: "#6b7280" };
                    badge.style.color = statusColors[d.status] || "#6b7280";
                    badge.textContent = `🤖 ${d.status || "?"}`;
                }
            }

            // Model calibration
            if (calRes.status === "fulfilled") {
                const d = await calRes.value.json();
                const el = document.getElementById("mclCalibrationStatus");
                if (el) {
                    const statusColors = { CALIBRATED: "#10b981", LEARNING: "#fbbf24", ABSORBING: "#60a5fa", DEGRADED: "#ef4444", UNKNOWN: "#6b7280" };
                    const color = statusColors[d.calibration_status] || "#6b7280";
                    const drift = d.drift_percentage != null ? ` drift=${d.drift_percentage.toFixed(1)}%` : "";
                    el.innerHTML = `<span style="color:${color};font-weight:700;">${d.calibration_status || "--"}</span>` +
                        (drift ? `<span style="color:#94a3b8">${drift}</span>` : "");
                }
                setText("mclDriftPct", d.drift_percentage != null ? `${d.drift_percentage.toFixed(1)}%` : "--");
                setText("mclTotalPreds", d.total_predictions != null ? String(d.total_predictions) : "--");
                setText("mclWinRate", d.win_rate != null ? `${(d.win_rate * 100).toFixed(1)}%` : "--");
                // Update header calibration badge
                const calBadge = document.getElementById("mclCalibrationBadge");
                if (calBadge) {
                    const statusColors = { CALIBRATED: "#10b981", LEARNING: "#fbbf24", ABSORBING: "#60a5fa", DEGRADED: "#ef4444", UNKNOWN: "#6b7280" };
                    calBadge.style.color = statusColors[d.calibration_status] || "#6b7280";
                    const driftStr = d.drift_percentage != null ? ` ${d.drift_percentage.toFixed(0)}%` : "";
                    calBadge.textContent = `📈 ${d.calibration_status || "?"}${driftStr}`;
                }
            }
        } catch (_) { /* model status is non-critical */ }
    }

    async function loadSummary(forceRefresh = false) {        try {
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
            const statusNormalized = String(data.status || "").toLowerCase();

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
            setOperationalState(statusNormalized, data.error);
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

            // ── MCL Engines ─────────────────────────────────────────────────
            setText("mclEngGannDegree", data.mcl_gann_degree != null ? String(data.mcl_gann_degree) : "--");
            setText("mclEngGannZone", data.mcl_gann_zone || "--");
            setText("mclEngGannNodeType", data.mcl_gann_node_type || "--");
            setText("mclEngGannNodePrice", data.mcl_gann_node_price != null ? String(data.mcl_gann_node_price) : "--");
            setText("mclEngGannTimeCycle", data.mcl_gann_time_cycle != null ? String(data.mcl_gann_time_cycle) : "--");
            setText("mclEngGannPTEqual", data.mcl_gann_price_time_equal != null ? String(data.mcl_gann_price_time_equal) : "--");
            setText("mclEngAstroNakshatra", data.mcl_astro_nakshatra || "--");
            setText("mclEngAstroStrength", data.mcl_astro_strength != null ? String(data.mcl_astro_strength) : "--");
            setText("mclEngMoonPhase", data.mcl_astro_moon_phase || "--");
            setText("mclEngMoonIllum", data.mcl_astro_moon_illumination != null ? `${Number(data.mcl_astro_moon_illumination).toFixed(1)}%` : "--");
            setText("mclEngNumNum", data.mcl_numerology_number != null ? String(data.mcl_numerology_number) : "--");
            setText("mclEngNumMeaning", data.mcl_numerology_meaning || "--");
            setText("mclEngHarmPattern", data.mcl_harmonic_pattern || "--");
            setText("mclEngHarmRatio", data.mcl_harmonic_ratio != null ? String(data.mcl_harmonic_ratio) : "--");
            setText("mclEngPhysForce", data.mcl_physics_force != null ? String(data.mcl_physics_force) : "--");
            setText("mclEngPhysVelocity", data.mcl_physics_velocity != null ? String(data.mcl_physics_velocity) : "--");
            setText("mclEngPhysEnergy", data.mcl_physics_energy != null ? String(data.mcl_physics_energy) : "--");
            setText("mclEngComprPhase", data.mcl_compression_phase || "--");
            setText("mclEngComprScore", data.mcl_compression_score != null ? String(data.mcl_compression_score) : "--");
            setText("mclEngComprBreakout", data.mcl_compression_breakout_near === true ? "YES" : data.mcl_compression_breakout_near === false ? "NO" : "--");
            setText("mclEngComprBias", data.mcl_compression_direction_bias || "--");
            setText("mclEngComprSilence", data.mcl_compression_silence_active === true ? "YES" : data.mcl_compression_silence_active === false ? "NO" : "--");
            setText("mclEngFutureDir", data.mcl_future_direction || "--");
            setText("mclEngCycleEvent", data.mcl_future_cycle_event || "--");
            setText("mclEngFutureStrength", data.mcl_future_strength != null ? String(data.mcl_future_strength) : "--");
            setText("mclEngCycleProgress", data.mcl_future_cycle_progress_pct != null ? `${Number(data.mcl_future_cycle_progress_pct).toFixed(1)}%` : "--");
            setText("mclEngLiqType", data.mcl_liquidity_type || "--");
            setText("mclEngLiqAbove", data.mcl_liquidity_above != null ? String(data.mcl_liquidity_above) : "--");
            setText("mclEngLiqBelow", data.mcl_liquidity_below != null ? String(data.mcl_liquidity_below) : "--");
            setText("mclEngPsychEmotion", data.mcl_psychology_emotion || "--");
            setText("mclEngBehaviorNext", data.mcl_behavior_next || "--");
            setText("mclEngTrapProb", data.mcl_trap_probability != null ? String(data.mcl_trap_probability) : "--");
            setText("mclEngExecVerdict", data.mcl_execution_verdict || "--");
            setText("mclEngExecScore", data.mcl_execution_score != null ? String(data.mcl_execution_score) : "--");
            setText("mclEngBtWinrate", data.mcl_backtest_winrate != null ? `${(Number(data.mcl_backtest_winrate) * 100).toFixed(1)}%` : "--");
            setText("mclEngBtWinsLosses", (data.mcl_backtest_wins != null && data.mcl_backtest_losses != null) ? `${data.mcl_backtest_wins}W / ${data.mcl_backtest_losses}L` : "--");
            setText("mclEngFailStatus", data.mcl_failure_status || "--");
            setText("mclEngFailSeverity", data.mcl_failure_severity || "--");
            setText("mclEngDataQuality", data.mcl_data_quality_status ? `${data.mcl_data_quality_status} (${data.mcl_data_quality_score ?? "--"})` : "--");
            setText("mclEngClarity", data.mcl_clarity || "--");
            setText("mclEngConviction", data.mcl_conviction != null ? String(data.mcl_conviction) : "--");
            setText("mclEngDominance", data.mcl_dominance_score != null ? String(data.mcl_dominance_score) : "--");
        } catch (err) {
            setText("mclStatus", "ERROR");
            setText("mclSignal", "--");
            setText("mclLatency", "--");
            setWhyTone("caution");
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
                    <option value="30m">30m</option>
                    <option value="1h">1h</option>
                    <option value="4h">4h</option>
                    <option value="1d" selected>1d</option>
                    <option value="1w">1w</option>
                    <option value="1month">1month</option>
                </select>
                <button id="mclUseChartContextBtn" title="Use current chart symbol/timeframe">Use Chart</button>
            </div>
            <div id="mclWhyCard" style="margin-bottom:8px;border:1px solid #7f8c8d;background:rgba(127, 140, 141, 0.10);padding:10px;border-radius:8px;">
            <div style="margin-bottom:8px;border:1px solid rgba(16,185,129,0.3);background:rgba(16,185,129,0.06);padding:8px 10px;border-radius:8px;">
                <div style="display:flex;justify-content:space-between;align-items:center;gap:8px;margin-bottom:6px;">
                    <strong style="font-size:12px;color:#94a3b8;letter-spacing:.04em;">AI MODEL STATUS</strong>
                    <button id="mclModelRefreshBtn" style="font-size:10px;padding:2px 8px;">↻ Refresh</button>
                </div>
                <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:4px;">
                    <div><span style="color:#64748b;font-size:11px;">Training</span><br><span id="mclTrainingStatus" style="font-size:12px;">--</span></div>
                    <div><span style="color:#64748b;font-size:11px;">Calibration</span><br><span id="mclCalibrationStatus" style="font-size:12px;">--</span></div>
                    <div><span style="color:#64748b;font-size:11px;">Drift</span><br><strong id="mclDriftPct" style="font-size:12px;">--</strong></div>
                    <div><span style="color:#64748b;font-size:11px;">Predictions</span><br><strong id="mclTotalPreds" style="font-size:12px;">--</strong></div>
                    <div><span style="color:#64748b;font-size:11px;">Win Rate</span><br><strong id="mclWinRate" style="font-size:12px;">--</strong></div>
                </div>
                <div id="mclTrainingTFs" style="font-size:10px;line-height:1.8;flex-wrap:wrap;"></div>
            </div>                <div style="display:flex;justify-content:space-between;gap:8px;align-items:center;">
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
            <div style="margin-top:8px;border-top:1px solid var(--border);padding-top:8px;">
                <div style="color:var(--muted);font-size:12px;font-weight:600;letter-spacing:0.04em;">MCL Engines</div>
                <div class="row-list" style="display:grid;grid-template-columns:1fr 1fr;gap:6px;margin-top:6px;">
                    <div><span>Gann Degree</span><strong id="mclEngGannDegree">--</strong></div>
                    <div><span>Gann Zone</span><strong id="mclEngGannZone">--</strong></div>
                    <div><span>Gann Node Type</span><strong id="mclEngGannNodeType">--</strong></div>
                    <div><span>Gann Node Price</span><strong id="mclEngGannNodePrice">--</strong></div>
                    <div><span>Gann Cycle</span><strong id="mclEngGannTimeCycle">--</strong></div>
                    <div><span>Gann P/T Equal</span><strong id="mclEngGannPTEqual">--</strong></div>
                    <div><span>Astro Nakshatra</span><strong id="mclEngAstroNakshatra">--</strong></div>
                    <div><span>Astro Strength</span><strong id="mclEngAstroStrength">--</strong></div>
                    <div><span>Moon Phase</span><strong id="mclEngMoonPhase">--</strong></div>
                    <div><span>Moon Illumination</span><strong id="mclEngMoonIllum">--</strong></div>
                    <div><span>Numerology #</span><strong id="mclEngNumNum">--</strong></div>
                    <div><span>Numerology Meaning</span><strong id="mclEngNumMeaning">--</strong></div>
                    <div><span>Harmonic Pattern</span><strong id="mclEngHarmPattern">--</strong></div>
                    <div><span>Harmonic Ratio</span><strong id="mclEngHarmRatio">--</strong></div>
                    <div><span>Physics Force</span><strong id="mclEngPhysForce">--</strong></div>
                    <div><span>Physics Velocity</span><strong id="mclEngPhysVelocity">--</strong></div>
                    <div><span>Physics Energy</span><strong id="mclEngPhysEnergy">--</strong></div>
                    <div><span>Compression Phase</span><strong id="mclEngComprPhase">--</strong></div>
                    <div><span>Compression Score</span><strong id="mclEngComprScore">--</strong></div>
                    <div><span>Breakout Near</span><strong id="mclEngComprBreakout">--</strong></div>
                    <div><span>Compr Bias</span><strong id="mclEngComprBias">--</strong></div>
                    <div><span>Silence Active</span><strong id="mclEngComprSilence">--</strong></div>
                    <div><span>Future Direction</span><strong id="mclEngFutureDir">--</strong></div>
                    <div><span>Cycle Event</span><strong id="mclEngCycleEvent">--</strong></div>
                    <div><span>Future Strength</span><strong id="mclEngFutureStrength">--</strong></div>
                    <div><span>Cycle Progress</span><strong id="mclEngCycleProgress">--</strong></div>
                    <div><span>Liquidity Type</span><strong id="mclEngLiqType">--</strong></div>
                    <div><span>Liq Above</span><strong id="mclEngLiqAbove">--</strong></div>
                    <div><span>Liq Below</span><strong id="mclEngLiqBelow">--</strong></div>
                    <div><span>Psychology</span><strong id="mclEngPsychEmotion">--</strong></div>
                    <div><span>Behavior Next</span><strong id="mclEngBehaviorNext">--</strong></div>
                    <div><span>Trap Probability</span><strong id="mclEngTrapProb">--</strong></div>
                    <div><span>Execution Verdict</span><strong id="mclEngExecVerdict">--</strong></div>
                    <div><span>Execution Score</span><strong id="mclEngExecScore">--</strong></div>
                    <div><span>Backtest Winrate</span><strong id="mclEngBtWinrate">--</strong></div>
                    <div><span>BT Wins / Losses</span><strong id="mclEngBtWinsLosses">--</strong></div>
                    <div><span>Failure Status</span><strong id="mclEngFailStatus">--</strong></div>
                    <div><span>Failure Severity</span><strong id="mclEngFailSeverity">--</strong></div>
                    <div><span>Data Quality</span><strong id="mclEngDataQuality">--</strong></div>
                    <div><span>Clarity</span><strong id="mclEngClarity">--</strong></div>
                    <div><span>Conviction</span><strong id="mclEngConviction">--</strong></div>
                    <div><span>Dominance Score</span><strong id="mclEngDominance">--</strong></div>
                </div>
            </div>
        `;

        document.body.appendChild(panel);

        const refreshBtn = document.getElementById("mclRefreshBtn");
        if (refreshBtn) refreshBtn.addEventListener("click", () => loadSummary(true));

        const modelRefreshBtn = document.getElementById("mclModelRefreshBtn");
        if (modelRefreshBtn) modelRefreshBtn.addEventListener("click", () => loadModelStatus());

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
            loadModelStatus();
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
        setSingletonInterval("marketCausalityModelStatusRefresh", () => {
            const panel = document.getElementById(PANEL_ID);
            if (panel && panel.style.display !== "none") {
                loadModelStatus();
            }
        }, 60000);
    } else {
        setInterval(() => {
            const panel = document.getElementById(PANEL_ID);
            if (panel && panel.style.display !== "none") {
                loadSummary(false);
            }
        }, 15000);
        setInterval(() => {
            const panel = document.getElementById(PANEL_ID);
            if (panel && panel.style.display !== "none") {
                loadModelStatus();
            }
        }, 60000);
    }

    window.toggleMarketCausalityPanel = togglePanel;
})();
