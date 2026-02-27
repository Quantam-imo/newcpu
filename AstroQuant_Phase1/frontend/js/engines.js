async function loadEngines() {
    const tbody = document.querySelector("#engineTable tbody");
    if (!tbody) return;

    const data = (typeof window.apiFetchJson === "function")
        ? await window.apiFetchJson("/engines")
        : await fetch(`${window.API_BASE}/engines`).then((res) => res.json());

    tbody.innerHTML = "";
    // Sort by confidence descending
    data.sort((a, b) => (b.confidence || 0) - (a.confidence || 0));
    data.forEach((engine, idx) => {
        let row = `<tr${idx % 2 === 0 ? ' class=\"even\"' : ''}>
            <td>${engine.symbol}</td>
            <td>${engine.status}</td>
            <td>${engine.confidence}</td>
            <td>${engine.spread}</td>
        </tr>`;
        tbody.innerHTML += row;
    });
}

setInterval(loadEngines, 5000);
