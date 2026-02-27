async function setPhase(phase) {
    await window.apiFetchJson(`/set-phase/${phase}`, { method: "POST" });
    document.getElementById("phaseDisplay").innerText = phase;
}

async function checkAdminStatus() {
    const exec = await window.apiFetchJson("/execution/status");
    const tg = await window.apiFetchJson("/telegram/status");
    const claw = await window.apiFetchJson("/clawbot/status");
    const health = await window.apiFetchJson("/engine/health");

    const p = document.getElementById("playwrightStatus");
    p.innerText = exec.browser_connected ? "Browser: Connected" : "Browser: Disconnected";
    p.className = exec.browser_connected ? "status-green" : "status-red";

    document.getElementById("telegramStatus").innerText =
        tg.active ? "Bot: Online" : "Bot: Offline";
    document.getElementById("telegramStatus").className = tg.active ? "status-green" : "status-red";

    document.getElementById("clawStatus").innerText =
        claw.active ? "Active" : "Inactive";
    document.getElementById("clawStatus").className = claw.active ? "status-green" : "status-red";

    document.getElementById("engineHealth").innerText =
        `CPU: ${health.cpu}% | RAM: ${health.ram}% | Data: ${health.feed}`;
}

setInterval(() => {
    checkAdminStatus().catch(err => console.error("Admin status refresh failed:", err.message));
}, 4000);
checkAdminStatus().catch(err => console.error("Admin status load failed:", err.message));
