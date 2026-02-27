async function updateAutoTradingStatus() {
    const statusEl = document.getElementById("autoTradingStatus");
    if (!statusEl) return;

    try {
        const data = (typeof window.apiFetchJson === "function")
            ? await window.apiFetchJson("/auto-trading/status")
            : await fetch(`${window.API_BASE}/auto-trading/status`).then((res) => res.json());
        statusEl.innerText = `Status: ${data.status}`;
    } catch (error) {
        console.error("Auto trading status failed:", error.message);
        statusEl.innerText = "Status: Unknown";
    }
}

async function startAutoTrading() {
    if (typeof window.apiFetchJson === "function") {
        await window.apiFetchJson("/auto-trading/start", { method: "POST" });
    } else {
        await fetch(`${window.API_BASE}/auto-trading/start`, { method: "POST" });
    }
    updateAutoTradingStatus();
}

async function stopAutoTrading() {
    if (typeof window.apiFetchJson === "function") {
        await window.apiFetchJson("/auto-trading/stop", { method: "POST" });
    } else {
        await fetch(`${window.API_BASE}/auto-trading/stop`, { method: "POST" });
    }
    updateAutoTradingStatus();
}

setInterval(updateAutoTradingStatus, 5000);
window.addEventListener('DOMContentLoaded', updateAutoTradingStatus);
