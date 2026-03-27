// Broker/Futures Spread & Offset History Panel

async function fetchPanelJson(path) {
    const response = await fetch(path, { method: 'GET' });
    if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
    }
    return response.json();
}


export async function createSpreadOffsetPanel(symbol) {
    const panel = document.createElement('div');
    panel.className = 'aq-panel spread-offset-panel';
    panel.innerHTML = `<h3>Spread & Offset History: ${symbol}</h3><div id="spreadOffsetTable">Loading...</div>`;
    document.body.appendChild(panel);
    try {
        const data = await fetchPanelJson(`/spread_offset_history?symbol=${encodeURIComponent(symbol)}`);
        renderSpreadOffsetTable(data, symbol);
    } catch (err) {
        document.getElementById('spreadOffsetTable').innerText = 'Failed to load data.';
    }
}


function renderSpreadOffsetTable(data, symbol) {
    const tableDiv = document.getElementById('spreadOffsetTable');
    if (!data || !Array.isArray(data.spot_candles) || !data.spot_candles.length) {
        tableDiv.innerText = 'No spread/offset history available.';
        return;
    }
    let html = '<table class="aq-table"><tr><th>Time</th><th>Spot Price</th><th>Basis (Spread)</th><th>Status</th></tr>';
    const basis = data.basis || {};
    for (const row of data.spot_candles) {
        html += `<tr><td>${new Date(row.time * 1000).toLocaleString()}</td><td>${row.close?.toFixed(2) ?? '--'}</td><td>${basis.raw_basis?.toFixed(2) ?? '--'}</td><td>${basis.status ?? '--'}</td></tr>`;
    }
    html += '</table>';
    tableDiv.innerHTML = html;
}
