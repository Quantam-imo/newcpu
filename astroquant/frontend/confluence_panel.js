
import { DraggablePanel } from './draggable_panel.js';
import { fetchWithRetry, safeSet, registerPanel } from './core.js';
import { WSManager } from './ws_manager.js';

export function createConfluencePanel(symbol) {
    let wsManager = null;
    let restInterval = null;
    const contentHtml = `<div id="confluence-summary">
        <p><strong>ICT Score:</strong> <span id="ict-score">0</span></p>
        <p><strong>Delta Score:</strong> <span id="delta-score">0</span></p>
        <p><strong>Iceberg Score:</strong> <span id="iceberg-score">0</span></p>
        <p><strong>Gann Score:</strong> <span id="gann-score">0</span></p>
        <p><strong>Astro Score:</strong> <span id="astro-score">0</span></p>
        <p><strong>Confidence:</strong> <span id="confidence">0</span></p>
        <div id="confluence-error" style="color:red;"></div>
    </div>`;
    const panel = new DraggablePanel(
        'confluence-panel',
        `Confluence: ${symbol}`,
        contentHtml,
        () => {
            if (wsManager) wsManager.close();
            if (restInterval) clearInterval(restInterval);
        }
    );

    function setConfluenceError(msg) {
        const el = document.getElementById('confluence-error');
        if (el) el.textContent = msg || '';
    }

    function renderConfluence(data, errorMsg) {
        if (errorMsg) {
            safeSet('ict-score', errorMsg);
            safeSet('delta-score', '');
            safeSet('iceberg-score', '');
            safeSet('gann-score', '');
            safeSet('astro-score', '');
            safeSet('confidence', '');
            return;
        }
        safeSet('ict-score', data.ict_score);
        safeSet('delta-score', data.delta_score);
        safeSet('iceberg-score', data.iceberg_score);
        safeSet('gann-score', data.gann_score);
        safeSet('astro-score', data.astro_score);
        safeSet('confidence', (data.confidence * 100).toFixed(2) + '%');
    }

    // Try WebSocket first
    try {
        wsManager = new WSManager(`/ws/confluence/${symbol}`, (data) => {
            if (data && typeof data.ict_score !== 'undefined') {
                renderConfluence(data, '');
                setConfluenceError('');
            } else if (data && data.error) {
                renderConfluence({}, 'Live error: ' + data.error);
                setConfluenceError('Live error: ' + data.error);
            }
        });
        wsManager.ws.onclose = () => {
            setConfluenceError('Live connection lost, switching to REST fallback.');
            renderConfluence({}, 'Error');
            if (wsManager) wsManager.close();
            restInterval = setInterval(loadConfluenceRest, 2000);
        };
        wsManager.ws.onerror = (e) => {
            setConfluenceError('WebSocket error, switching to REST fallback.');
            renderConfluence({}, 'Error');
            if (wsManager) wsManager.close();
            restInterval = setInterval(loadConfluenceRest, 2000);
        };
    } catch (err) {
        setConfluenceError('WebSocket init failed, using REST fallback.');
        renderConfluence({}, 'Error');
        restInterval = setInterval(loadConfluenceRest, 2000);
    }

    async function loadConfluenceRest() {
        try {
            const res = await fetchWithRetry(`${window.AQ_BASE}/confluence/${symbol}`);
            const data = await res.json();
            if (data.error) {
                renderConfluence({}, data.error);
                setConfluenceError(data.error);
                return;
            }
            renderConfluence(data, '');
            setConfluenceError('');
        } catch (err) {
            renderConfluence({}, 'REST error');
            setConfluenceError('REST error');
        }
    }

    registerPanel(panel.panel, () => {
        if (wsManager) wsManager.close();
        if (restInterval) clearInterval(restInterval);
    });
}

function addConfluenceButton(symbol) {
    const btn = document.createElement('button');
    btn.textContent = `Open Confluence: ${symbol}`;
    btn.onclick = () => createConfluencePanel(symbol);
    document.body.appendChild(btn);
}

// Add basic styles if not present
if (!document.getElementById('confluence-panel-style')) {
    const style = document.createElement('style');
    style.id = 'confluence-panel-style';
    style.innerHTML = `
.draggable-panel {
    position: absolute;
    top: 500px;
    left: 500px;
    width: 320px;
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
addConfluenceButton('GC.c.0');
