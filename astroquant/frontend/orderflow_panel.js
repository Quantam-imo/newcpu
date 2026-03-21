// Draggable and closable orderflow panel
class DraggablePanel {
    constructor(id, title, contentHtml) {
        this.id = id;
        this.title = title;
        this.contentHtml = contentHtml;
        this.createPanel();
    }

    createPanel() {
        const panel = document.createElement('div');
        panel.id = this.id;
        panel.className = 'draggable-panel';
        panel.innerHTML = `
            <div class="panel-header">
                <span>${this.title}</span>
                <button class="close-btn">×</button>
            </div>
            <div class="panel-content">${this.contentHtml}</div>
        `;
        document.body.appendChild(panel);
        this.makeDraggable(panel);
        panel.querySelector('.close-btn').onclick = () => panel.remove();
    }

    makeDraggable(panel) {
        const header = panel.querySelector('.panel-header');
        let offsetX = 0, offsetY = 0, isDragging = false;
        header.onmousedown = (e) => {
            isDragging = true;
            offsetX = e.clientX - panel.offsetLeft;
            offsetY = e.clientY - panel.offsetTop;
            document.onmousemove = (ev) => {
                if (isDragging) {
                    panel.style.left = (ev.clientX - offsetX) + 'px';
                    panel.style.top = (ev.clientY - offsetY) + 'px';
                }
            };
            document.onmouseup = () => {
                isDragging = false;
                document.onmousemove = null;
                document.onmouseup = null;
            };
        };
    }
}


import { DraggablePanel } from './draggable_panel.js';
import { registerPanel, fetchWithRetry } from './core.js';
import { WSManager } from './ws_manager.js';

export function createOrderflowPanel(symbol) {
    let wsManager = null;
    let restInterval = null;
    const contentHtml = `<table id="orderflow-table">
        <thead><tr><th>Time</th><th>Price</th><th>Size</th><th>Side</th></tr></thead>
        <tbody></tbody>
    </table>
    <div id="orderflow-error" style="color:red;"></div>`;
    const panel = new DraggablePanel(
        'orderflow-panel',
        `Orderflow: ${symbol}`,
        contentHtml,
        () => {
            if (wsManager) wsManager.close();
            if (restInterval) clearInterval(restInterval);
        }
    );

    function setOrderflowError(msg) {
        const el = document.getElementById('orderflow-error');
        if (el) el.textContent = msg || '';
    }

    function renderOrderflowTable(trades, errorMsg) {
        const tbody = document.querySelector('#orderflow-table tbody');
        if (!tbody) return;
        tbody.innerHTML = '';
        if (errorMsg) {
            tbody.innerHTML = `<tr><td colspan="4">${errorMsg}</td></tr>`;
            return;
        }
        (trades || []).forEach(([price, size, side, trade_time]) => {
            const row = document.createElement('tr');
            row.innerHTML = `<td>${trade_time}</td><td>${price}</td><td>${size}</td><td>${side}</td>`;
            row.style.color = side === 'buy' ? 'green' : 'red';
            tbody.appendChild(row);
        });
    }

    // Try WebSocket first
    try {
        wsManager = new WSManager(`/ws/orderflow/${symbol}`, (data) => {
            if (data && Array.isArray(data.trades)) {
                renderOrderflowTable(data.trades, '');
                setOrderflowError('');
            } else if (data && data.error) {
                renderOrderflowTable([], 'Live error: ' + data.error);
                setOrderflowError('Live error: ' + data.error);
            }
        });
        wsManager.ws.onclose = () => {
            setOrderflowError('Live connection lost, switching to REST fallback.');
            renderOrderflowTable([], 'Error');
            if (wsManager) wsManager.close();
            restInterval = setInterval(loadOrderflowRest, 3000);
        };
        wsManager.ws.onerror = (e) => {
            setOrderflowError('WebSocket error, switching to REST fallback.');
            renderOrderflowTable([], 'Error');
            if (wsManager) wsManager.close();
            restInterval = setInterval(loadOrderflowRest, 3000);
        };
    } catch (err) {
        setOrderflowError('WebSocket init failed, using REST fallback.');
        renderOrderflowTable([], 'Error');
        restInterval = setInterval(loadOrderflowRest, 3000);
    }

    async function loadOrderflowRest() {
        try {
            const res = await fetchWithRetry(`${window.AQ_BASE}/orderflow/${symbol}`);
            const data = await res.json();
            if (data.error) {
                renderOrderflowTable([], data.error);
                setOrderflowError(data.error);
                return;
            }
            renderOrderflowTable(data.trades, '');
            setOrderflowError('');
        } catch (err) {
            renderOrderflowTable([], 'REST error');
            setOrderflowError('REST error');
        }
    }

    registerPanel(panel.panel, () => {
        if (wsManager) wsManager.close();
        if (restInterval) clearInterval(restInterval);
    });
}

// Button to open/close panel
function addOrderflowButton(symbol) {
    const btn = document.createElement('button');
    btn.textContent = `Open Orderflow: ${symbol}`;
    btn.onclick = () => createOrderflowPanel(symbol);
    document.body.appendChild(btn);
}

// Add basic styles
const style = document.createElement('style');
style.innerHTML = `
.draggable-panel {
    position: absolute;
    top: 100px;
    left: 100px;
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
    max-height: 300px;
    overflow-y: auto;
}
#orderflow-table {
    width: 100%;
    border-collapse: collapse;
}
#orderflow-table th, #orderflow-table td {
    padding: 4px 8px;
    border-bottom: 1px solid #444;
}
`;
document.head.appendChild(style);

// Example: add button for GC.c.0
addOrderflowButton('GC.c.0');
