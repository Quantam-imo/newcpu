// Draggable and closable Confluence panel
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

function createConfluencePanel(symbol) {
    const contentHtml = `<div id="confluence-summary">
        <p><strong>ICT Score:</strong> <span id="ict-score">0</span></p>
        <p><strong>Delta Score:</strong> <span id="delta-score">0</span></p>
        <p><strong>Iceberg Score:</strong> <span id="iceberg-score">0</span></p>
        <p><strong>Gann Score:</strong> <span id="gann-score">0</span></p>
        <p><strong>Astro Score:</strong> <span id="astro-score">0</span></p>
        <p><strong>Confidence:</strong> <span id="confidence">0</span></p>
    </div>`;
    new DraggablePanel('confluence-panel', `Confluence: ${symbol}`, contentHtml);
    startConfluenceWebSocket(symbol);
}

function startConfluenceWebSocket(symbol) {
    // Use REST for now, can upgrade to WebSocket for confluence
    function fetchConfluence() {
        fetch(`/confluence/${symbol}`)
            .then(res => {
                if (!res.ok) throw new Error(`HTTP ${res.status}`);
                return res.json();
            })
            .then(data => {
                document.getElementById('ict-score').textContent = data.ict_score;
                document.getElementById('delta-score').textContent = data.delta_score;
                document.getElementById('iceberg-score').textContent = data.iceberg_score;
                document.getElementById('gann-score').textContent = data.gann_score;
                document.getElementById('astro-score').textContent = data.astro_score;
                document.getElementById('confidence').textContent = (data.confidence * 100).toFixed(2) + '%';
            })
            .catch(err => {
                document.getElementById('ict-score').textContent = 'Error';
                document.getElementById('delta-score').textContent = 'Error';
                document.getElementById('iceberg-score').textContent = 'Error';
                document.getElementById('gann-score').textContent = 'Error';
                document.getElementById('astro-score').textContent = 'Error';
                document.getElementById('confidence').textContent = '';
                console.error('Confluence fetch failed:', err);
            });
    }
    fetchConfluence();
    setInterval(fetchConfluence, 2000);
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
