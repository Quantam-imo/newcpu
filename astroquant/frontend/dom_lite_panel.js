
import { DraggablePanel } from './draggable_panel.js';
import { fetchWithRetry, safeSet, registerPanel } from './core.js';
import { WSManager } from './ws_manager.js';

export function createDomLitePanel(symbol) {
    let wsManager = null;
    let restInterval = null;
    const contentHtml = `<div id="dom-lite-summary">
        <p><strong>Best Bid:</strong> <span id="bid-price">0</span> (<span id="bid-size">0</span>)</p>
        <p><strong>Best Ask:</strong> <span id="ask-price">0</span> (<span id="ask-size">0</span>)</p>
        <p><strong>Spread:</strong> <span id="spread">0</span></p>
        <p><strong>Imbalance:</strong> <span id="imbalance">0</span></p>
        <div id="dom-lite-error" style="color:red;"></div>
    </div>`;
    const panel = new DraggablePanel(
        'dom-lite-panel',
        `DOM Lite: ${symbol}`,
        contentHtml,
        () => {
            if (wsManager) wsManager.close();
            if (restInterval) clearInterval(restInterval);
        }
    );

    function setDomLiteError(msg) {
        const el = document.getElementById('dom-lite-error');
        if (el) el.textContent = msg || '';
    }

    function renderDomLite(data, errorMsg) {
        if (errorMsg) {
            safeSet('bid-price', errorMsg);
            safeSet('bid-size', '');
            safeSet('ask-price', '');
            safeSet('ask-size', '');
            safeSet('spread', '');
            safeSet('imbalance', '');
            return;
        }
        safeSet('bid-price', data.bid_price);
        safeSet('bid-size', data.bid_size);
        safeSet('ask-price', data.ask_price);
        safeSet('ask-size', data.ask_size);
        safeSet('spread', (data.ask_price - data.bid_price).toFixed(2));
        safeSet('imbalance', (data.imbalance * 100).toFixed(2) + '%');
    }

    // Try WebSocket first
    try {
        wsManager = new WSManager(`/ws/dom_lite/${symbol}`, (data) => {
            if (data && typeof data.bid_price !== 'undefined') {
                renderDomLite(data, '');
                setDomLiteError('');
            } else if (data && data.error) {
                renderDomLite({}, 'Live error: ' + data.error);
                setDomLiteError('Live error: ' + data.error);
            }
        });
        wsManager.ws.onclose = () => {
            setDomLiteError('Live connection lost, switching to REST fallback.');
            renderDomLite({}, 'Error');
            if (wsManager) wsManager.close();
            restInterval = setInterval(loadDomLiteRest, 2000);
        };
        wsManager.ws.onerror = (e) => {
            setDomLiteError('WebSocket error, switching to REST fallback.');
            renderDomLite({}, 'Error');
            if (wsManager) wsManager.close();
            restInterval = setInterval(loadDomLiteRest, 2000);
        };
    } catch (err) {
        setDomLiteError('WebSocket init failed, using REST fallback.');
        renderDomLite({}, 'Error');
        restInterval = setInterval(loadDomLiteRest, 2000);
    }

    async function loadDomLiteRest() {
        try {
            const res = await fetchWithRetry(`${window.AQ_BASE}/dom_lite/${symbol}`);
            const data = await res.json();
            if (data.error) {
                renderDomLite({}, data.error);
                setDomLiteError(data.error);
                return;
            }
            renderDomLite(data, '');
            setDomLiteError('');
        } catch (err) {
            renderDomLite({}, 'REST error');
            setDomLiteError('REST error');
        }
    }

    registerPanel(panel.panel, () => {
        if (wsManager) wsManager.close();
        if (restInterval) clearInterval(restInterval);
    });
}

function addDomLiteButton(symbol) {
    const btn = document.createElement('button');
    btn.textContent = `Open DOM Lite: ${symbol}`;
    btn.onclick = () => createDomLitePanel(symbol);
    document.body.appendChild(btn);
}

// Add basic styles if not present
if (!document.getElementById('dom-lite-panel-style')) {
    const style = document.createElement('style');
    style.id = 'dom-lite-panel-style';
    style.innerHTML = `
.draggable-panel {
    position: absolute;
    top: 300px;
    left: 300px;
    width: 300px;
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
    max-height: 200px;
    overflow-y: auto;
}
`;
    document.head.appendChild(style);
}

// Example: add button for GC.c.0
addDomLiteButton('GC.c.0');
