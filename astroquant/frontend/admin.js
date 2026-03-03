async function setPhase(phase) {
    const res = await fetch('/admin/set_phase', {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ phase: phase })
    });

    const data = await res.json();
    if (data.error) {
        alert(data.error);
    }
}

async function checkExecutionStatus() {
    const res = await fetch('/status/execution');
    const data = await res.json();
    document.getElementById("playwright-status").innerText = data.connected ? "Connected" : "Disconnected";
}
