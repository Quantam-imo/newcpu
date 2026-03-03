// Draggable and closable DOM Lite panel
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

function createDomLitePanel(symbol) {
    const contentHtml = `<div id="dom-lite-summary">
        <p><strong>Best Bid:</strong> <span id="bid-price">0</span> (<span id="bid-size">0</span>)</p>
        <p><strong>Best Ask:</strong> <span id="ask-price">0</span> (<span id="ask-size">0</span>)</p>
        <p><strong>Spread:</strong> <span id="spread">0</span></p>
        <p><strong>Imbalance Ratio:</strong> <span id="imbalance">0</span></p>
    </div>`;
    new DraggablePanel('dom-lite-panel', `DOM Lite: ${symbol}`, contentHtml);
    startDomLiteWebSocket(symbol);
}

function startDomLiteWebSocket(symbol) {
    // Use REST for now, can upgrade to WebSocket for DOM Lite
    function fetchDomLite() {
        fetch(`/dom_lite/${symbol}`)
            .then(res => {
                if (!res.ok) throw new Error(`HTTP ${res.status}`);
                return res.json();
            })
            .then(data => {
                document.getElementById('bid-price').textContent = data.bid_price;
                document.getElementById('bid-size').textContent = data.bid_size;
                document.getElementById('ask-price').textContent = data.ask_price;
                document.getElementById('ask-size').textContent = data.ask_size;
                document.getElementById('spread').textContent = (data.ask_price - data.bid_price).toFixed(2);
                document.getElementById('imbalance').textContent = (data.imbalance * 100).toFixed(2) + '%';
            })
            .catch(err => {
                document.getElementById('bid-price').textContent = 'Error';
                document.getElementById('bid-size').textContent = '';
                document.getElementById('ask-price').textContent = 'Error';
                document.getElementById('ask-size').textContent = '';
                document.getElementById('spread').textContent = '';
                document.getElementById('imbalance').textContent = '';
                console.error('DOM Lite fetch failed:', err);
            });
    }
    fetchDomLite();
    setInterval(fetchDomLite, 2000);
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
