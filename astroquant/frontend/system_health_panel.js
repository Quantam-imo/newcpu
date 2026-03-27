import { fetchWithRetry, registerPanel } from "./core.js";
import { DraggablePanel } from "./draggable_panel.js";

export function openSystemHealthPanel() {
    // Remove any existing health panels
    const existing = document.getElementById("system-health-panel");
    if (existing) existing.remove();

    const panel = new DraggablePanel(
        "system-health-panel",
        "System Health Dashboard",
        `<div id="system-health-content">Loading...</div>`,
        () => {}
    );

    registerPanel(panel.panel, () => {});
    loadSystemHealth();
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
