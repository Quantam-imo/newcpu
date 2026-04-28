import { fetchWithRetry, registerPanel } from "./core.js";
import { DraggablePanel } from "./draggable_panel.js";

export function openSystemHealthPanel() {
    // Remove any existing health panels
    const existing = document.getElementById("system-health-panel");
    if (existing) existing.remove();

    const panel = new DraggablePanel(
        "system-health-panel",
        "System Health Dashboard",
        `<div id="system-health-content">Loading...</div>
         <div id="system-mcl-status" style="margin-top:8px;"></div>`,
        () => {}
    );

    registerPanel(panel.panel, () => {});
    loadSystemHealth();
    loadMclStatus();
}

async function loadSystemHealth() {
    const el = document.getElementById("system-health-content");
    if (!el) return;
    try {
        const res = await fetchWithRetry("/health");
        const data = await res.json();
        el.innerHTML = renderHealthTable(data);
    } catch (err) {
        el.innerHTML = `<span style='color:#f87171'>Failed to load health status.</span>`;
    }
}

async function loadMclStatus() {
    const el = document.getElementById("system-mcl-status");
    if (!el) return;
    try {
        const [tsRes, calRes] = await Promise.allSettled([
            fetchWithRetry("/market_causality/system/training-status"),
            fetchWithRetry("/market_causality/system/model-calibration"),
        ]);

        let html = `<table style='width:100%;border-collapse:collapse;margin-top:4px;'>
            <tr><th colspan='3' style='text-align:left;padding:4px 2px;color:#94a3b8;font-size:11px;letter-spacing:.05em;'>MCL MODEL STATUS</th></tr>`;

        if (tsRes.status === "fulfilled") {
            const d = await tsRes.value.json();
            const statusColors = { ALL_READY: "#10b981", PARTIAL: "#fbbf24", NOT_READY: "#ef4444" };
            const col = statusColors[d.status] || "#6b7280";
            html += `<tr><td>Training</td><td style='color:${col};font-weight:700;'>${d.status || "--"}</td><td>${d.ready_models ?? "--"}/${d.total_models ?? "--"} models</td></tr>`;
            if (d.timeframes) {
                const tfs = Object.entries(d.timeframes);
                const tfStr = tfs.map(([tf, info]) => {
                    const c = info.ready ? "#10b981" : "#ef4444";
                    return `<span style='color:${c}'>${tf.toUpperCase()}${info.ready ? "✓" : "✗"}</span>`;
                }).join(" ");
                html += `<tr><td colspan='3' style='font-size:11px;padding:2px 2px 6px;'>${tfStr}</td></tr>`;
            }
        }

        if (calRes.status === "fulfilled") {
            const d = await calRes.value.json();
            const statusColors = { CALIBRATED: "#10b981", LEARNING: "#fbbf24", ABSORBING: "#60a5fa", DEGRADED: "#ef4444" };
            const col = statusColors[d.calibration_status] || "#6b7280";
            const drift = d.drift_percentage != null ? `${d.drift_percentage.toFixed(1)}%` : "--";
            const preds = d.total_predictions != null ? String(d.total_predictions) : "--";
            const wr = d.win_rate != null ? `${(d.win_rate * 100).toFixed(1)}%` : "--";
            html += `<tr><td>Calibration</td><td style='color:${col};font-weight:700;'>${d.calibration_status || "--"}</td><td>drift ${drift}</td></tr>`;
            html += `<tr><td>Predictions</td><td>${preds}</td><td>win rate ${wr}</td></tr>`;
        }

        html += `</table>`;
        el.innerHTML = html;
    } catch (err) {
        el.innerHTML = `<span style='color:#f87171;font-size:11px'>MCL status unavailable.</span>`;
    }
}

function renderHealthTable(data) {
    if (!data || typeof data !== "object") return "No health data.";
    let html = `<table style='width:100%;border-collapse:collapse;'>`;
    html += `<tr><th style='text-align:left'>Component</th><th>Status</th><th>Details</th></tr>`;
    for (const [key, val] of Object.entries(data)) {
        html += `<tr><td>${key}</td><td>${val.status || "-"}</td><td>${val.details || ""}</td></tr>`;
    }
    html += `</table>`;
    return html;
}
