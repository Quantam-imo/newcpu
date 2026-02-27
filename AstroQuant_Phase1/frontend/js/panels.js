(function initPanels() {
    const panels = Array.from(document.querySelectorAll('.floating-panel'));
    if (!panels.length) return;

    let zIndexCounter = 10000;

    function bringToFront(panel) {
        zIndexCounter += 1;
        panel.style.zIndex = String(zIndexCounter);
    }

    function makeDraggable(panel) {
        const header = panel.querySelector('.floating-header');
        if (!header) return;

        let dragging = false;
        let offsetX = 0;
        let offsetY = 0;

        const onMouseMove = (event) => {
            if (!dragging) return;
            const panelRect = panel.getBoundingClientRect();
            const maxX = Math.max(4, window.innerWidth - panelRect.width - 4);
            const maxY = Math.max(4, window.innerHeight - panelRect.height - 4);

            const nextLeft = Math.min(maxX, Math.max(4, event.clientX - offsetX));
            const nextTop = Math.min(maxY, Math.max(4, event.clientY - offsetY));

            panel.style.right = 'auto';
            panel.style.left = `${nextLeft}px`;
            panel.style.top = `${nextTop}px`;
        };

        const onMouseUp = () => {
            dragging = false;
            document.removeEventListener('mousemove', onMouseMove);
            document.removeEventListener('mouseup', onMouseUp);
        };

        header.addEventListener('mousedown', (event) => {
            if (event.target.closest('button')) return;
            bringToFront(panel);
            const rect = panel.getBoundingClientRect();
            dragging = true;
            offsetX = event.clientX - rect.left;
            offsetY = event.clientY - rect.top;
            panel.style.left = `${rect.left}px`;
            panel.style.top = `${rect.top}px`;
            panel.style.right = 'auto';
            document.addEventListener('mousemove', onMouseMove);
            document.addEventListener('mouseup', onMouseUp);
        });
    }

    function clampPanelInViewport(panel) {
        if (!panel || panel.style.display === 'none') return;

        const rect = panel.getBoundingClientRect();
        if (!rect.width || !rect.height) return;

        const maxLeft = Math.max(4, window.innerWidth - rect.width - 4);
        const maxTop = Math.max(4, window.innerHeight - rect.height - 4);

        let nextLeft = rect.left;
        let nextTop = rect.top;

        if (nextLeft < 4) nextLeft = 4;
        if (nextTop < 4) nextTop = 4;
        if (nextLeft > maxLeft) nextLeft = maxLeft;
        if (nextTop > maxTop) nextTop = maxTop;

        if (nextLeft !== rect.left || nextTop !== rect.top) {
            panel.style.left = `${nextLeft}px`;
            panel.style.top = `${nextTop}px`;
            panel.style.right = 'auto';
        }
    }

    function makeMinimizable(panel) {
        const btn = panel.querySelector('.floating-minimize');
        if (!btn) return;

        btn.addEventListener('click', () => {
            panel.classList.toggle('minimized');
            btn.innerText = panel.classList.contains('minimized') ? '+' : '—';
            bringToFront(panel);
        });
    }

    panels.forEach((panel) => {
        makeDraggable(panel);
        makeMinimizable(panel);

        panel.addEventListener('mousedown', () => bringToFront(panel));
    });

    const clampAllPanels = () => {
        panels.forEach((panel) => clampPanelInViewport(panel));
    };

    setTimeout(clampAllPanels, 120);
    window.addEventListener('resize', clampAllPanels);
})();
