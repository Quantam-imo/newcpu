// Draggable and closable delta panel
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


import { WSManager } from './ws_manager.js';

function createDeltaPanel(symbol) {
    let wsManager = null;
    let restInterval = null;
    const contentHtml = `<div id="delta-summary">
        <p><strong>Delta %:</strong> <span id="delta-percent">0</span></p>
        <div id="delta-error" style="color:red;"></div>
    </div>`;
    const panel = new DraggablePanel(
        'delta-panel',
        `Delta: ${symbol}`,
        contentHtml,
        () => {
            if (wsManager) wsManager.close();
            if (restInterval) clearInterval(restInterval);
        }
    );

    function setDeltaError(msg) {
        const el = document.getElementById('delta-error');
        if (el) el.textContent = msg || '';
    }

    function setDeltaValue(val) {
        const el = document.getElementById('delta-percent');
        if (el) el.textContent = val;
    }

    // Try WebSocket first
    try {
        wsManager = new WSManager(`/ws/delta/${symbol}`, (data) => {
            if (data && typeof data.delta_percent === 'number') {
                setDeltaValue((data.delta_percent * 100).toFixed(2) + '%');
                setDeltaError('');
            } else if (data && data.error) {
                setDeltaError('Live error: ' + data.error);
                setDeltaValue('Error');
            }
        });
        // If WebSocket closes, fallback to REST
        wsManager.ws.onclose = () => {
            setDeltaError('Live connection lost, switching to REST fallback.');
            setDeltaValue('Error');
            if (wsManager) wsManager.close();
            // Start REST fallback
            restInterval = setInterval(loadDeltaRest, 2000);
        };
        wsManager.ws.onerror = (e) => {
            setDeltaError('WebSocket error, switching to REST fallback.');
            setDeltaValue('Error');
            if (wsManager) wsManager.close();
            restInterval = setInterval(loadDeltaRest, 2000);
        };
    } catch (err) {
        setDeltaError('WebSocket init failed, using REST fallback.');
        setDeltaValue('Error');
        restInterval = setInterval(loadDeltaRest, 2000);
    }

    async function loadDeltaRest() {
        try {
            const res = await fetchWithRetry(`${window.AQ_BASE}/delta/${symbol}`);
            const data = await res.json();
            if (data.error) {
                setDeltaError(data.error);
                setDeltaValue('Error');
                return;
            }
            setDeltaValue((data.delta_percent * 100).toFixed(2) + '%');
            setDeltaError('');
        } catch (e) {
            setDeltaError('REST error');
            setDeltaValue('Error');
        }
    }

    registerPanel(panel.panel, () => {
        if (wsManager) wsManager.close();
        if (restInterval) clearInterval(restInterval);
    });
}

function addDeltaButton(symbol) {
    const btn = document.createElement('button');
    btn.textContent = `Open Delta: ${symbol}`;
    btn.onclick = () => createDeltaPanel(symbol);
    document.body.appendChild(btn);
}

// Add basic styles if not present
if (!document.getElementById('delta-panel-style')) {
    const style = document.createElement('style');
    style.id = 'delta-panel-style';
    style.innerHTML = `
.draggable-panel {
    position: absolute;
    top: 200px;
    left: 200px;
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
addDeltaButton('GC.c.0');
