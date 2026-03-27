// Pin/favorite symbol and layout management for AstroQuant
// Stores favorites in localStorage and exposes UI helpers

const AQ_FAVORITE_SYMBOLS_KEY = "AQ_FAVORITE_SYMBOLS_V1";

export function getFavoriteSymbols() {
    try {
        const raw = localStorage.getItem(AQ_FAVORITE_SYMBOLS_KEY);
        if (!raw) return [];
        const arr = JSON.parse(raw);
        return Array.isArray(arr) ? arr : [];
    } catch {
        return [];
    }
}

export function setFavoriteSymbols(symbols) {
    try {
        localStorage.setItem(AQ_FAVORITE_SYMBOLS_KEY, JSON.stringify(Array.from(new Set(symbols))));
    } catch {}
}

export function toggleFavoriteSymbol(symbol) {
    const favs = getFavoriteSymbols();
    const idx = favs.indexOf(symbol);
    if (idx === -1) {
        favs.push(symbol);
    } else {
        favs.splice(idx, 1);
    }
    setFavoriteSymbols(favs);
    return favs;
}

export function isFavoriteSymbol(symbol) {
    return getFavoriteSymbols().includes(symbol);
}
