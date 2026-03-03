// Draggable and closable Iceberg panel
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

function createIcebergPanel(symbol) {
    const contentHtml = `<table id="iceberg-table">
        <thead><tr><th>Price Level</th><th>Volume</th><th>Repetitions</th><th>Side</th><th>Confidence</th></tr></thead>
        <tbody></tbody>
    </table>`;
    new DraggablePanel('iceberg-panel', `Iceberg: ${symbol}`, contentHtml);
    startIcebergWebSocket(symbol);
}

function startIcebergWebSocket(symbol) {
    // Use REST for now, can upgrade to WebSocket for iceberg
    function fetchIceberg() {
        fetch(`/iceberg/${symbol}`)
            .then(res => {
                if (!res.ok) throw new Error(`HTTP ${res.status}`);
                return res.json();
            })
            .then(data => {
                const tbody = document.querySelector('#iceberg-table tbody');
                if (!tbody) return;
                tbody.innerHTML = '';
                data.events.forEach(ev => {
                    const row = document.createElement('tr');
                    row.innerHTML = `<td>${ev.price_level}</td><td>${ev.total_volume}</td><td>${ev.repetition_count}</td><td>${ev.dominant_side}</td><td>${(ev.confidence * 100).toFixed(1)}%</td>`;
                    row.style.color = ev.dominant_side === 'absorption' ? 'blue' : 'orange';
                    tbody.appendChild(row);
                });
            })
            .catch(err => {
                const tbody = document.querySelector('#iceberg-table tbody');
                if (tbody) tbody.innerHTML = '<tr><td colspan="5">Error loading iceberg data</td></tr>';
                console.error('Iceberg fetch failed:', err);
            });
    }
    fetchIceberg();
    setInterval(fetchIceberg, 3000);
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
