import { createSpreadOffsetPanel } from './spread_offset_panel.js';
import { registerPanel } from './core.js';

export function addSpreadOffsetButton(symbol) {
    const btn = document.createElement('button');
    btn.textContent = `Open Spread/Offset: ${symbol}`;
    btn.onclick = () => {
        createSpreadOffsetPanel(symbol);
    };
    document.body.appendChild(btn);
}
