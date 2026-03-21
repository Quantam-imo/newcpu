
import { DraggablePanel } from './draggable_panel.js';
import { fetchWithRetry, registerPanel } from './core.js';
import { WSManager } from './ws_manager.js';

export function createIcebergPanel(symbol) {
    let wsManager = null;
    let restInterval = null;
    const contentHtml = `<table id="iceberg-table">
        <thead><tr><th>Price Level</th><th>Volume</th><th>Repetitions</th><th>Side</th><th>Confidence</th></tr></thead>
        <tbody></tbody>
    </table>
    <div id="iceberg-error" style="color:red;"></div>`;
    const panel = new DraggablePanel(
        'iceberg-panel',
        `Iceberg: ${symbol}`,
        contentHtml,
        () => {
            if (wsManager) wsManager.close();
            if (restInterval) clearInterval(restInterval);
        }
    );

    function setIcebergError(msg) {
        const el = document.getElementById('iceberg-error');
        if (el) el.textContent = msg || '';
    }

    function renderIcebergTable(events, errorMsg) {
        const tbody = document.querySelector('#iceberg-table tbody');
        if (!tbody) return;
        tbody.innerHTML = '';
        if (errorMsg) {
            tbody.innerHTML = `<tr><td colspan="5">${errorMsg}</td></tr>`;
            return;
        }
        (events || []).forEach(ev => {
            const row = document.createElement('tr');
            row.innerHTML = `<td>${ev.price_level}</td><td>${ev.total_volume}</td><td>${ev.repetition_count}</td><td>${ev.dominant_side}</td><td>${(ev.confidence * 100).toFixed(1)}%</td>`;
            row.style.color = ev.dominant_side === 'absorption' ? 'blue' : 'orange';
            tbody.appendChild(row);
        });
    }

    // Try WebSocket first
    try {
        wsManager = new WSManager(`/ws/iceberg/${symbol}`, (data) => {
            if (data && Array.isArray(data.events)) {
                renderIcebergTable(data.events, '');
                setIcebergError('');
            } else if (data && data.error) {
                renderIcebergTable([], 'Live error: ' + data.error);
                setIcebergError('Live error: ' + data.error);
            }
        });
        wsManager.ws.onclose = () => {
            setIcebergError('Live connection lost, switching to REST fallback.');
            renderIcebergTable([], 'Error');
            if (wsManager) wsManager.close();
            restInterval = setInterval(loadIcebergRest, 3000);
        };
        wsManager.ws.onerror = (e) => {
            setIcebergError('WebSocket error, switching to REST fallback.');
            renderIcebergTable([], 'Error');
            if (wsManager) wsManager.close();
            restInterval = setInterval(loadIcebergRest, 3000);
        };
    } catch (err) {
        setIcebergError('WebSocket init failed, using REST fallback.');
        renderIcebergTable([], 'Error');
        restInterval = setInterval(loadIcebergRest, 3000);
    }

    async function loadIcebergRest() {
        try {
            const res = await fetchWithRetry(`${window.AQ_BASE}/iceberg/${symbol}`);
            const data = await res.json();
            if (data.error) {
                renderIcebergTable([], data.error);
                setIcebergError(data.error);
                return;
            }
            renderIcebergTable(data.events, '');
            setIcebergError('');
        } catch (err) {
            renderIcebergTable([], 'REST error');
            setIcebergError('REST error');
        }
    }

    registerPanel(panel.panel, () => {
        if (wsManager) wsManager.close();
        if (restInterval) clearInterval(restInterval);
    });
}

function addIcebergButton(symbol) {
    const btn = document.createElement('button');
    btn.textContent = `Open Iceberg: ${symbol}`;
    btn.onclick = () => createIcebergPanel(symbol);
    document.body.appendChild(btn);
}

// Add basic styles if not present
if (!document.getElementById('iceberg-panel-style')) {
    const style = document.createElement('style');
    style.id = 'iceberg-panel-style';
    style.innerHTML = `
.draggable-panel {
    position: absolute;
    top: 400px;
    left: 400px;
    width: 350px;
    background: #222;
    color: #fff;
    border: 2px solid #444;
    border-radius: 8px;
    box-shadow: 0 4px 16px rgba(0,0,0,0.2);
    z-index: 1000;
}
.panel-header {
    background: #333;
    padding: 8px;
    cursor: move;
    display: flex;
    justify-content: space-between;
    align-items: center;
    border-bottom: 1px solid #444;
    font-weight: bold;
}
.close-btn {
    background: #444;
    color: #fff;
    border: none;
    font-size: 18px;
    cursor: pointer;
    border-radius: 4px;
    width: 28px;
    height: 28px;
}
.panel-content {
    padding: 10px;
    max-height: 250px;
    overflow-y: auto;
}
#iceberg-table {
    width: 100%;
    border-collapse: collapse;
}
#iceberg-table th, #iceberg-table td {
    padding: 4px 8px;
    border-bottom: 1px solid #444;
}
`;
    document.head.appendChild(style);
}

// Example: add button for GC.c.0
addIcebergButton('GC.c.0');
