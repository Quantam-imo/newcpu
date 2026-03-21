// GLOBAL CONFIG
window.AQ_BASE = window.AQ_API_BASE || window.location.origin;

// ================================
// SAFE DOM HELPERS
// ================================
export function safeSet(id, value) {
    const el = document.getElementById(id);
    if (el) el.textContent = value;
}

// ================================
// RETRY FETCH ENGINE
// ================================
export async function fetchWithRetry(url, options = {}, retries = 3) {
    for (let i = 0; i < retries; i++) {
        try {
            const controller = new AbortController();
            const timeout = setTimeout(() => controller.abort(), 10000);

            const res = await fetch(url, {
                ...options,
                signal: controller.signal
            });

            clearTimeout(timeout);

            if (res.ok) return res;

        } catch (err) {
            if (i === retries - 1) throw err;
            await new Promise(r => setTimeout(r, 500 * (i + 1)));
        }
    }
}

// ================================
// PANEL REGISTRY (MEMORY SAFE)
// ================================
window.AQ_PANELS = [];

export function registerPanel(panel, cleanup) {
    window.AQ_PANELS.push({ panel, cleanup });
}

export function clearPanels() {
    window.AQ_PANELS.forEach(p => {
        if (p.cleanup) p.cleanup();
        p.panel.remove();
    });
    window.AQ_PANELS = [];
}
