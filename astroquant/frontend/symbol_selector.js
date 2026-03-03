// Symbol selector for institutional panels
function createSymbolSelector(symbols) {
    const selector = document.createElement('select');
    selector.id = 'symbol-selector';
    symbols.forEach(sym => {
        const option = document.createElement('option');
        option.value = sym;
        option.textContent = sym;
        selector.appendChild(option);
    });
    selector.onchange = () => {
        const symbol = selector.value;
        updateAllPanels(symbol);
    };
    document.body.appendChild(selector);
}

function updateAllPanels(symbol) {
    // Remove existing panels
    document.querySelectorAll('.draggable-panel').forEach(panel => panel.remove());
    // Re-create all panels for selected symbol
    createOrderflowPanel(symbol);
    createDeltaPanel(symbol);
    createDomLitePanel(symbol);
    createIcebergPanel(symbol);
    createConfluencePanel(symbol);
}

// Example: available symbols
const availableSymbols = ['GC.c.0', 'XAUUSD', 'ES.c.0'];
createSymbolSelector(availableSymbols);
// Initial load
updateAllPanels(availableSymbols[0]);
