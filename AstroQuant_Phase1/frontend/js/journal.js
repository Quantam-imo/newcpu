
async function loadJournal() {
    const data = await window.apiFetchJson("/journal");
    let tbody = document.querySelector("#journalTable tbody");
    tbody.innerHTML = "";
    // Sort by time descending
    data.sort((a, b) => new Date(b.time) - new Date(a.time));
    data.forEach((trade, idx) => {
        const timeDisplay = (typeof window.formatTableTime === "function")
            ? window.formatTableTime(trade.time)
            : (trade.time ?? "--");

        let row = `<tr${idx % 2 === 0 ? ' class="even"' : ''}>
            <td>${timeDisplay}</td>
            <td>${trade.symbol}</td>
            <td>${trade.model}</td>
            <td>${trade.direction}</td>
            <td>${trade.entry}</td>
            <td>${trade.sl}</td>
            <td>${trade.tp}</td>
            <td>${trade.confidence}</td>
            <td>${trade.result}</td>
            <td>${trade.slippage}</td>
        </tr>`;
        tbody.innerHTML += row;
    });
}

setInterval(() => {
    loadJournal().catch(err => console.error("Journal refresh failed:", err.message));
}, 5000);
loadJournal().catch(err => console.error("Journal load failed:", err.message));
