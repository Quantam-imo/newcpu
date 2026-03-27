// Autocomplete symbol selector for AstroQuant
// Replaces static <select> with a fast, searchable dropdown using /symbols

export function setupSymbolAutocomplete({
    inputId = "chartSymbolInput",
    dropdownId = "chartSymbolDropdown",
    onSelect = null,
    apiUrl = "/symbols",
    minQueryLength = 0
} = {}) {
    const input = document.getElementById(inputId);
    const dropdown = document.getElementById(dropdownId);
    if (!input || !dropdown) return;

    let symbols = [];
    let lastQuery = "";
    let debounceTimer = null;

    async function fetchSymbols(query) {
        const candidates = [apiUrl, "/symbols", "/api/symbols"];
        try {
            for (const base of candidates) {
                const url = base + (query ? `?q=${encodeURIComponent(query)}` : "");
                const res = await fetch(url);
                if (!res.ok) continue;
                const data = await res.json();
                if (Array.isArray(data.symbols)) {
                    return data.symbols;
                }
            }
            return [];
        } catch (e) {
            return [];
        }
    }

    function renderDropdown(items) {
        dropdown.innerHTML = "";
        if (!items.length) {
            dropdown.style.display = "none";
            return;
        }
        for (const item of items) {
            const option = document.createElement("div");
            option.className = "autocomplete-option";
            option.textContent = `${item.symbol} (${item.exchange}) - ${item.description}`;
            option.tabIndex = 0;
            option.onclick = () => {
                input.value = item.symbol;
                dropdown.style.display = "none";
                // Keep other frontend modules in sync with selected symbol.
                input.dispatchEvent(new Event("input", { bubbles: true }));
                input.dispatchEvent(new Event("change", { bubbles: true }));
                if (onSelect) onSelect(item.symbol, item);
            };
            dropdown.appendChild(option);
        }
        dropdown.style.display = "block";
    }

    input.addEventListener("input", (e) => {
        const query = input.value.trim();
        if (query === lastQuery) return;
        lastQuery = query;
        if (debounceTimer) clearTimeout(debounceTimer);
        if (query.length < minQueryLength) {
            renderDropdown([]);
            return;
        }
        debounceTimer = setTimeout(async () => {
            symbols = await fetchSymbols(query);
            renderDropdown(symbols);
        }, 180);
    });

    input.addEventListener("focus", async () => {
        if (input.value.trim().length < minQueryLength) {
            symbols = await fetchSymbols("");
            renderDropdown(symbols);
        }
    });

    document.addEventListener("click", (e) => {
        if (!dropdown.contains(e.target) && e.target !== input) {
            dropdown.style.display = "none";
        }
    });
}
