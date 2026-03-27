import { clearPanels } from './core.js';
import { createDeltaPanel } from './delta_panel.js';

export function updateAllPanels(symbol) {
    clearPanels();
    createDeltaPanel(symbol);
    // add others here safely
}
