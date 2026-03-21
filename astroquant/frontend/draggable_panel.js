export class DraggablePanel {
    constructor(id, title, contentHtml, onClose) {
        this.id = id;
        this.title = title;
        this.contentHtml = contentHtml;
        this.onClose = onClose;
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

        panel.querySelector('.close-btn').onclick = () => {
            if (this.onClose) this.onClose();
            panel.remove();
        };

        this.panel = panel;
    }

    makeDraggable(panel) {
        const header = panel.querySelector('.panel-header');
        let offsetX = 0, offsetY = 0, dragging = false;

        header.onmousedown = (e) => {
            dragging = true;
            offsetX = e.clientX - panel.offsetLeft;
            offsetY = e.clientY - panel.offsetTop;

            document.onmousemove = (ev) => {
                if (dragging) {
                    panel.style.left = `${ev.clientX - offsetX}px`;
                    panel.style.top = `${ev.clientY - offsetY}px`;
                }
            };

            document.onmouseup = () => {
                dragging = false;
                document.onmousemove = null;
                document.onmouseup = null;
            };
        };
    }
}
