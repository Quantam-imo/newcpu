from pathlib import Path


PANEL_PATH = Path("/workspaces/newcpu/astroquant/frontend/market_causality_panel.js")


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
