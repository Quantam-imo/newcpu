async function updateDashboard() {
    const balanceEl = document.getElementById("balance");
    const dailyLossEl = document.getElementById("dailyLoss");
    if (!balanceEl || !dailyLossEl) return;

    try {
        const data = (typeof window.apiFetchJson === "function")
            ? await window.apiFetchJson("/prop/status")
            : await fetch(`${window.API_BASE}/prop/status`).then((res) => res.json());

        balanceEl.innerText = Number(data.balance || 0).toFixed(2);
        dailyLossEl.innerText = data.daily_loss ?? "0.00";
    } catch (error) {
        console.error("Dashboard refresh failed:", error.message);
    }
}

function toggleEmergency() {
    if (typeof window.apiFetchJson === "function") {
        window.apiFetchJson("/emergency/stop").catch((error) => console.error("Emergency stop failed:", error.message));
        return;
    }
    fetch(`${window.API_BASE}/emergency/stop`).catch(() => {});
}

setInterval(updateDashboard, 5000);
