from pathlib import Path


PANEL_PATH = Path("/workspaces/newcpu/astroquant/frontend/market_causality_panel.js")
DASHBOARD_PATH = Path("/workspaces/newcpu/market-causality-lab/dashboard/index.html")


def test_panel_contains_fallback_fields_and_bindings():
    text = PANEL_PATH.read_text(encoding="utf-8")

    # UI bindings from summary payload.
    assert 'setText("mclFallback", data.timeframe_fallback_applied ? "YES" : "NO")' in text
    assert 'setText("mclFallbackReason", data.timeframe_fallback_reason || "none")' in text

    # Corresponding panel DOM IDs.
    assert 'id="mclFallback"' in text
    assert 'id="mclFallbackReason"' in text

    # Lifecycle bindings and DOM IDs.
    assert 'setText("mclAnalysisStart", data.analysis_started_at_utc || "--")' in text
    assert 'setText("mclAnalysisEnd", data.analysis_completed_at_utc || "--")' in text
    assert 'setText("mclReasoningSummary", data.reasoning_summary || "--")' in text
    assert 'id="mclAnalysisStart"' in text
    assert 'id="mclAnalysisEnd"' in text
    assert 'id="mclReasoningSummary"' in text
    assert 'id="mclReasoningChain"' in text
    assert 'id="mclLifecycleStages"' in text
    assert 'const lifecycleStagesEl = document.getElementById("mclLifecycleStages")' in text
    assert 'id="mclSlowestStage"' in text
    assert 'id="mclProcessTiming"' in text
    assert 'setText("mclSlowestStage", data.slowest_process_stage?.name ?' in text
    assert 'const processTimingEl = document.getElementById("mclProcessTiming")' in text
    assert 'id="mclWhyCard"' in text
    assert 'id="mclWhyTitle"' in text
    assert 'id="mclWhySummary"' in text
    assert 'id="mclTopDrivers"' in text
    assert 'id="mclDeltaSignal"' in text
    assert 'id="mclDeltaDrivers"' in text
    assert 'setText("mclWhyTitle", data.reasoning_tone ? String(data.reasoning_tone).toUpperCase() : "NEUTRAL")' in text
    assert 'setText("mclDeltaSignal", data.reasoning_delta?.has_previous' in text
    assert 'data.reasoning_delta.signal_changed ? " (CHANGED)" : " (UNCHANGED)"' in text
    assert 'const topDriversEl = document.getElementById("mclTopDrivers")' in text
    assert 'const deltaDriversEl = document.getElementById("mclDeltaDrivers")' in text
    assert 'const delta = item.delta_pct != null ? `${item.delta_pct >= 0 ? "+" : ""}${item.delta_pct}%` : "--";' in text
    assert 'return `<li><strong>${label}</strong> | ${prev} -> ${curr} | delta ${delta}</li>`;' in text
    assert 'function setOperationalState(status, errorMsg)' in text
    assert 'normalized === "timeout" || normalized === "stale_timeout" || normalized === "error"' in text
    assert 'setOperationalState(statusNormalized, data.error);' in text


def test_panel_timeframe_select_has_all_supported_timeframes():
    """All 9 canonical MCL timeframes must be present in the panel dropdown."""
    text = PANEL_PATH.read_text(encoding="utf-8")
    for tf in ("1m", "5m", "15m", "30m", "1h", "4h", "1d", "1w", "1month"):
        assert f'value="{tf}"' in text, f"MCL panel dropdown missing timeframe option: {tf}"


def test_dashboard_has_live_price_badge_and_poll():
    """MCL dashboard must contain live price badge and polling infrastructure."""
    text = DASHBOARD_PATH.read_text(encoding="utf-8")
    assert 'id="livePriceBadge"' in text, "Missing livePriceBadge element"
    assert 'id="livePriceSource"' in text, "Missing livePriceSource element"
    assert "_pollLivePrice" in text, "Missing _pollLivePrice function"
    assert "startLivePricePoll" in text, "Missing startLivePricePoll function"
    assert "/market_causality/live_price" in text, "Missing live_price API call"
    assert "_livePriceLine" in text, "Missing live price line logic"
    assert "createPriceLine" in text, "Missing createPriceLine call for live price"


def test_panel_contains_fallback_fields_and_bindings():
    text = PANEL_PATH.read_text(encoding="utf-8")

    # UI bindings from summary payload.
    assert 'setText("mclFallback", data.timeframe_fallback_applied ? "YES" : "NO")' in text
    assert 'setText("mclFallbackReason", data.timeframe_fallback_reason || "none")' in text

    # Corresponding panel DOM IDs.
    assert 'id="mclFallback"' in text
    assert 'id="mclFallbackReason"' in text

    # Lifecycle bindings and DOM IDs.
    assert 'setText("mclAnalysisStart", data.analysis_started_at_utc || "--")' in text
    assert 'setText("mclAnalysisEnd", data.analysis_completed_at_utc || "--")' in text
    assert 'setText("mclReasoningSummary", data.reasoning_summary || "--")' in text
    assert 'id="mclAnalysisStart"' in text
    assert 'id="mclAnalysisEnd"' in text
    assert 'id="mclReasoningSummary"' in text
    assert 'id="mclReasoningChain"' in text
    assert 'id="mclLifecycleStages"' in text
    assert 'const lifecycleStagesEl = document.getElementById("mclLifecycleStages")' in text
    assert 'id="mclSlowestStage"' in text
    assert 'id="mclProcessTiming"' in text
    assert 'setText("mclSlowestStage", data.slowest_process_stage?.name ?' in text
    assert 'const processTimingEl = document.getElementById("mclProcessTiming")' in text
    assert 'id="mclWhyCard"' in text
    assert 'id="mclWhyTitle"' in text
    assert 'id="mclWhySummary"' in text
    assert 'id="mclTopDrivers"' in text
    assert 'id="mclDeltaSignal"' in text
    assert 'id="mclDeltaDrivers"' in text
    assert 'setText("mclWhyTitle", data.reasoning_tone ? String(data.reasoning_tone).toUpperCase() : "NEUTRAL")' in text
    assert 'setText("mclDeltaSignal", data.reasoning_delta?.has_previous' in text
    assert 'data.reasoning_delta.signal_changed ? " (CHANGED)" : " (UNCHANGED)"' in text
    assert 'const topDriversEl = document.getElementById("mclTopDrivers")' in text
    assert 'const deltaDriversEl = document.getElementById("mclDeltaDrivers")' in text
    assert 'const delta = item.delta_pct != null ? `${item.delta_pct >= 0 ? "+" : ""}${item.delta_pct}%` : "--";' in text
    assert 'return `<li><strong>${label}</strong> | ${prev} -> ${curr} | delta ${delta}</li>`;' in text
    assert 'function setOperationalState(status, errorMsg)' in text
    assert 'normalized === "timeout" || normalized === "stale_timeout" || normalized === "error"' in text
    assert 'setOperationalState(statusNormalized, data.error);' in text
