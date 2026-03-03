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

function createDeltaPanel(symbol) {
    const contentHtml = `<div id="delta-summary">
        <p><strong>Buy Volume:</strong> <span id="buy-volume">0</span></p>
        <p><strong>Sell Volume:</strong> <span id="sell-volume">0</span></p>
        <p><strong>Delta:</strong> <span id="delta">0</span></p>
        <p><strong>Delta %:</strong> <span id="delta-percent">0</span></p>
    </div>`;
    new DraggablePanel('delta-panel', `Delta: ${symbol}`, contentHtml);
    startDeltaWebSocket(symbol);
}

function startDeltaWebSocket(symbol) {
    // Use REST for now, can upgrade to WebSocket for delta
    function fetchDelta() {
        fetch(`/delta/${symbol}`)
            .then(res => {
                if (!res.ok) throw new Error(`HTTP ${res.status}`);
                return res.json();
            })
            .then(data => {
                document.getElementById('delta-percent').textContent = (data.delta_percent * 100).toFixed(2) + '%';
                // Optionally update buy/sell/delta if available
            })
            .catch(err => {
                document.getElementById('delta-percent').textContent = 'Error';
                console.error('Delta fetch failed:', err);
            });
    }
    fetchDelta();
    setInterval(fetchDelta, 2000);
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
