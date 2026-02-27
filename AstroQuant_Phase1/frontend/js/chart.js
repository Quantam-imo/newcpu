let chartState = {
    overlays: {
        iceberg: false,
        gann: false,
        astro: false,
        cycle: false,
        liquidity: false,
        news: false,
        volume: false
    },
    tf: "5m",
    symbol: "GC.FUT",
    symbols: ["GC.FUT"],
    scrollZoom: true
};
window.chartState = chartState;

const SCROLL_ZOOM_STORAGE_KEY = "aq.chart.scrollZoom";
const CHART_REQUEST_TIMEOUT_MS = 12000;
const COMPARE_REQUEST_TIMEOUT_MS = 3500;
const SAME_BAR_RELOAD_MS = 900;
const PERIODIC_STREAM_REFRESH_MS = 1200;
const DISCONNECTED_RELOAD_COOLDOWN_MS = 5000;
const NEW_BAR_RELOAD_GUARD_MS = 3000;

let chartLoadSequence = 0;
let chartLoadController = null;
let chartReloadTimer = null;
let chartLoadInProgress = false;
let chartLoadPending = false;
let liveChartInterval = null;
let chartStreamSocket = null;
let chartStreamReconnectTimer = null;
let chartStreamKey = null;
let lastStreamBarTime = null;
let lastStreamBarBucket = null;
let lastStreamReloadMs = 0;
let lastNewBarReloadMs = 0;
let lastDisconnectedReloadMs = 0;
let lastMultiSelectionSignature = '';
let lastMultiSelectionAtMs = 0;

let lwChart = null;
let candleSeries = null;
let volumeSeries = null;
let compareSeries = new Map();
let overlaySeries = [];
let resizeObserver = null;
let lastPrimaryBars = [];
let lastLivePriceValue = null;
let livePriceFlashTimer = null;
let candlePrintTimer = null;
let lastViewportKey = null;

function getPrimarySymbol() {
    const selected = Array.isArray(chartState.symbols) ? chartState.symbols : [];
    if (selected.length) return String(selected[0]);
    return String(chartState.symbol || "GC.FUT");
}

function readScrollZoomPreference() {
    try {
        const value = window.localStorage.getItem(SCROLL_ZOOM_STORAGE_KEY);
        if (value === 'true') return true;
        if (value === 'false') return false;
    } catch {
        // noop
    }
    return chartState.scrollZoom;
}

function saveScrollZoomPreference(value) {
    try {
        window.localStorage.setItem(SCROLL_ZOOM_STORAGE_KEY, String(!!value));
    } catch {
        // noop
    }
}

function toNumber(value) {
    const n = Number(value);
    return Number.isFinite(n) ? n : null;
}

function timeframeMinutes(tf) {
    const map = { '1m': 1, '5m': 5, '15m': 15, '1h': 60, '4h': 240 };
    return map[tf] || 5;
}

function timeframeMs(tf) {
    return timeframeMinutes(tf) * 60 * 1000;
}

function normalizeTimestamp(value) {
    if (value === null || value === undefined || value === "") return null;

    if (typeof value === 'number' && Number.isFinite(value)) {
        const millis = value > 1_000_000_000_000 ? value : value * 1000;
        const date = new Date(millis);
        return Number.isNaN(date.getTime()) ? null : date.toISOString();
    }

    if (typeof value === 'string') {
        const t = value.trim();
        if (!t) return null;
        if (/^\d+$/.test(t)) {
            const n = Number(t);
            if (Number.isFinite(n)) {
                const millis = n > 1_000_000_000_000 ? n : n * 1000;
                const date = new Date(millis);
                return Number.isNaN(date.getTime()) ? null : date.toISOString();
            }
        }
        const date = new Date(t);
        return Number.isNaN(date.getTime()) ? null : date.toISOString();
    }

    return null;
}

function normalizePrices(rawPrices) {
    if (!Array.isArray(rawPrices)) return [];
    const byTime = new Map();

    rawPrices.forEach((item) => {
        if (!item || typeof item !== 'object') return;
        const time = normalizeTimestamp(item.time ?? item.ts_event ?? item.timestamp ?? item.t);
        const open = toNumber(item.open ?? item.o);
        const high = toNumber(item.high ?? item.h);
        const low = toNumber(item.low ?? item.l);
        const close = toNumber(item.close ?? item.c);
        const volume = toNumber(item.volume ?? item.v) ?? 0;
        if (!time || open === null || high === null || low === null || close === null) return;

        byTime.set(time, {
            time,
            open,
            high: Math.max(open, high, low, close),
            low: Math.min(open, high, low, close),
            close,
            volume: Math.max(0, volume)
        });
    });

    return Array.from(byTime.values()).sort((a, b) => new Date(a.time) - new Date(b.time));
}

function shouldAggregateToTimeframe(prices, tf) {
    if (!Array.isArray(prices) || prices.length < 2) return false;
    const expectedMs = timeframeMs(tf);
    if (!Number.isFinite(expectedMs) || expectedMs <= 60_000) return false;

    const first = new Date(prices[0].time).getTime();
    const second = new Date(prices[1].time).getTime();
    if (!Number.isFinite(first) || !Number.isFinite(second)) return false;

    const observed = Math.max(1000, Math.abs(second - first));
    return observed < (expectedMs * 0.75);
}

function alignToTimeframeBucket(timeIso, tf) {
    const dateMs = new Date(timeIso).getTime();
    if (!Number.isFinite(dateMs)) return null;
    const bucketMs = Math.max(60_000, timeframeMs(tf));
    const alignedMs = Math.floor(dateMs / bucketMs) * bucketMs;
    return new Date(alignedMs).toISOString();
}

function aggregatePricesToTimeframe(prices, tf) {
    if (!Array.isArray(prices) || !prices.length) return [];
    const sorted = [...prices].sort((a, b) => new Date(a.time) - new Date(b.time));
    const buckets = new Map();

    sorted.forEach((price) => {
        const t = alignToTimeframeBucket(price.time, tf);
        if (!t) return;
        const existing = buckets.get(t);
        if (!existing) {
            buckets.set(t, { ...price, time: t });
            return;
        }
        existing.high = Math.max(existing.high, price.high, price.open, price.close, price.low);
        existing.low = Math.min(existing.low, price.low, price.open, price.close, price.high);
        existing.close = price.close;
        existing.volume += price.volume || 0;
    });

    return Array.from(buckets.values()).sort((a, b) => new Date(a.time) - new Date(b.time));
}

function isoToSec(iso) {
    const ms = new Date(iso).getTime();
    if (!Number.isFinite(ms)) return null;
    return Math.floor(ms / 1000);
}

function formatUtcTick(value) {
    const iso = normalizeTimestamp(value);
    if (!iso) return '--';
    const d = new Date(iso);
    const hh = String(d.getUTCHours()).padStart(2, '0');
    const mm = String(d.getUTCMinutes()).padStart(2, '0');
    return `${hh}:${mm} UTC`;
}

function updateDataQualityBadge({ status = 'unknown', label = '--' } = {}) {
    const badge = document.getElementById('chartDataQualityBadge');
    if (!badge) return;
    badge.classList.remove('is-normal', 'is-sparse', 'is-unknown');
    badge.classList.add(status === 'normal' ? 'is-normal' : status === 'sparse' ? 'is-sparse' : 'is-unknown');
    badge.textContent = label;
}

function updateStreamStatusBadge(status = 'unknown', label = '--') {
    const badge = document.getElementById('chartStreamStatusBadge');
    if (!badge) return;
    badge.classList.remove('is-live', 'is-reconnect', 'is-unknown');
    badge.classList.add(status === 'live' ? 'is-live' : status === 'reconnect' ? 'is-reconnect' : 'is-unknown');
    badge.textContent = label;
}

function updateLivePriceBadge(price, time) {
    const badge = document.getElementById('chartLivePriceBadge');
    if (!badge) return;
    const numeric = Number(price);
    if (!Number.isFinite(numeric)) {
        badge.textContent = '--';
        badge.classList.remove('is-up', 'is-down', 'is-flash');
        lastLivePriceValue = null;
        return;
    }

    const previous = Number(lastLivePriceValue);
    badge.classList.remove('is-up', 'is-down');
    if (Number.isFinite(previous)) {
        if (numeric > previous) badge.classList.add('is-up');
        if (numeric < previous) badge.classList.add('is-down');
    }
    badge.classList.add('is-flash');
    if (livePriceFlashTimer) clearTimeout(livePriceFlashTimer);
    livePriceFlashTimer = setTimeout(() => {
        badge.classList.remove('is-flash');
    }, 260);
    lastLivePriceValue = numeric;

    const stamp = time || new Date().toISOString();
    const nowMs = Date.now();
    const barMs = new Date(stamp).getTime();
    const lagMin = Number.isFinite(barMs) ? Math.max(0, Math.round((nowMs - barMs) / 60000)) : null;
    const lagText = lagMin === null ? '' : ` (${lagMin}m lag)`;
    badge.textContent = `${numeric.toFixed(2)} @ ${formatUtcTick(stamp)}${lagText}`;
}

function triggerCandlePrintAnimation(direction = 0) {
    const chartEl = document.getElementById('chart');
    if (!chartEl) return;

    chartEl.classList.remove('candle-print-up', 'candle-print-down');
    if (direction > 0) chartEl.classList.add('candle-print-up');
    if (direction < 0) chartEl.classList.add('candle-print-down');

    if (candlePrintTimer) clearTimeout(candlePrintTimer);
    candlePrintTimer = setTimeout(() => {
        chartEl.classList.remove('candle-print-up', 'candle-print-down');
    }, 220);
}

function assessDataQuality(prices, tf) {
    if (!Array.isArray(prices) || !prices.length) return { status: 'unknown', label: 'Data Unknown' };
    const last = prices[prices.length - 1];
    const lastMs = new Date(last.time).getTime();
    if (!Number.isFinite(lastMs)) return { status: 'unknown', label: 'Data Unknown' };

    const lagMin = (Date.now() - lastMs) / 60000;
    const tfMin = timeframeMinutes(tf);
    if (lagMin <= Math.max(2, tfMin * 2.5)) return { status: 'normal', label: 'Live' };
    return { status: 'sparse', label: 'Feed Slow' };
}

function updateTimeframeButtons() {
    const map = { '1m': 'M1', '5m': 'M5', '15m': 'M15', '1h': 'H1', '4h': 'H4' };
    const activeLabel = map[chartState.tf];
    document.querySelectorAll('.tf-btns button').forEach((button) => {
        button.classList.toggle('is-active', button.textContent.trim() === activeLabel);
    });
}

function updateOverlayButtons() {
    document.querySelectorAll('.overlay-btns button').forEach((button) => {
        const name = button.getAttribute('onclick')?.match(/'([^']+)'/)?.[1];
        if (!name) return;
        button.classList.toggle('is-active', !!chartState.overlays[name]);
    });
}

function updateScrollZoomButton() {
    const button = document.getElementById('scrollZoomToggle');
    if (!button) return;
    button.textContent = `Scroll Zoom: ${chartState.scrollZoom ? 'ON' : 'OFF'}`;
    button.classList.toggle('is-active', !!chartState.scrollZoom);
}

function updateVolumeToggleButton() {
    const button = document.getElementById('volumeToggleBtn');
    if (!button) return;
    button.textContent = `Volume: ${chartState.overlays.volume ? 'ON' : 'OFF'}`;
    button.classList.toggle('is-active', !!chartState.overlays.volume);
}

function renderChartMessage(message) {
    const el = document.getElementById('chart');
    if (!el) return;
    el.innerHTML = `<div style="height:100%;display:flex;align-items:center;justify-content:center;color:#ffd180;font-size:14px;">${message}</div>`;
}

function addCandlestickSeriesCompat(chart, options = {}) {
    if (!chart || !window.LightweightCharts) return null;
    if (typeof chart.addCandlestickSeries === 'function') {
        return chart.addCandlestickSeries(options);
    }
    if (typeof chart.addSeries === 'function' && window.LightweightCharts.CandlestickSeries) {
        return chart.addSeries(window.LightweightCharts.CandlestickSeries, options);
    }
    return null;
}

function addHistogramSeriesCompat(chart, options = {}) {
    if (!chart || !window.LightweightCharts) return null;
    if (typeof chart.addHistogramSeries === 'function') {
        return chart.addHistogramSeries(options);
    }
    if (typeof chart.addSeries === 'function' && window.LightweightCharts.HistogramSeries) {
        return chart.addSeries(window.LightweightCharts.HistogramSeries, options);
    }
    return null;
}

function addLineSeriesCompat(chart, options = {}) {
    if (!chart || !window.LightweightCharts) return null;
    if (typeof chart.addLineSeries === 'function') {
        return chart.addLineSeries(options);
    }
    if (typeof chart.addSeries === 'function' && window.LightweightCharts.LineSeries) {
        return chart.addSeries(window.LightweightCharts.LineSeries, options);
    }
    return null;
}

function ensureChart() {
    const el = document.getElementById('chart');
    if (!el || !window.LightweightCharts) return false;
    if (lwChart) return true;

    el.innerHTML = '';
    lwChart = window.LightweightCharts.createChart(el, {
        width: el.clientWidth || 800,
        height: el.clientHeight || 500,
        layout: {
            background: { color: '#0d1420' },
            textColor: '#e7edf7'
        },
        grid: {
            vertLines: { color: 'rgba(255,255,255,0.08)' },
            horzLines: { color: 'rgba(255,255,255,0.08)' }
        },
        rightPriceScale: { borderColor: 'rgba(255,255,255,0.2)' },
        crosshair: {
            mode: 0,
            vertLine: { color: 'rgba(255,255,255,0.35)', width: 1, style: 2, visible: true, labelVisible: true },
            horzLine: { color: 'rgba(255,255,255,0.35)', width: 1, style: 2, visible: true, labelVisible: true }
        },
        timeScale: {
            borderColor: 'rgba(255,255,255,0.2)',
            rightOffset: 6,
            barSpacing: 8,
            timeVisible: true,
            secondsVisible: false,
            rightBarStaysOnScroll: true,
            shiftVisibleRangeOnNewBar: true
        },
        handleScroll: { mouseWheel: !!chartState.scrollZoom, pressedMouseMove: true, horzTouchDrag: true, vertTouchDrag: true },
        handleScale: { mouseWheel: !!chartState.scrollZoom, pinch: true, axisPressedMouseMove: true }
    });

    candleSeries = addCandlestickSeriesCompat(lwChart, {
        upColor: '#26a69a',
        downColor: '#ef5350',
        borderVisible: false,
        wickUpColor: '#26a69a',
        wickDownColor: '#ef5350'
    });

    volumeSeries = addHistogramSeriesCompat(lwChart, {
        priceScaleId: 'volume',
        priceFormat: { type: 'volume' },
        color: 'rgba(57,73,171,0.45)'
    });
    if (!candleSeries || !volumeSeries) {
        renderChartMessage('Unsupported lightweight-charts build');
        return false;
    }

    const volumeScale = lwChart.priceScale && lwChart.priceScale('volume');
    if (volumeScale && typeof volumeScale.applyOptions === 'function') {
        volumeScale.applyOptions({
            scaleMargins: { top: 0.8, bottom: 0 },
            visible: !!chartState.overlays.volume
        });
    }

    if (!resizeObserver) {
        resizeObserver = new ResizeObserver(() => {
            if (!lwChart) return;
            lwChart.applyOptions({ width: el.clientWidth, height: el.clientHeight });
        });
        resizeObserver.observe(el);
    }

    return true;
}

function clearCompareSeries() {
    if (!lwChart) return;
    compareSeries.forEach((series) => {
        try { lwChart.removeSeries(series); } catch { /* noop */ }
    });
    compareSeries.clear();
}

function clearOverlaySeries() {
    if (!lwChart) return;
    overlaySeries.forEach((series) => {
        try { lwChart.removeSeries(series); } catch { /* noop */ }
    });
    overlaySeries = [];
    if (candleSeries && typeof candleSeries.setMarkers === 'function') {
        candleSeries.setMarkers([]);
    }
}

function buildLinePoints(times, levels) {
    if (!Array.isArray(times) || !Array.isArray(levels) || !times.length || times.length !== levels.length) return [];
    const rows = [];
    for (let i = 0; i < times.length; i += 1) {
        const timeIso = normalizeTimestamp(times[i]);
        const sec = isoToSec(timeIso);
        const value = toNumber(levels[i]);
        if (sec === null || value === null) continue;
        rows.push({ time: sec, value });
    }
    return rows;
}

function addOverlayLine(name, points, color = '#90caf9', width = 1, style) {
    if (!lwChart || !Array.isArray(points) || !points.length) return;
    const opts = {
        color,
        lineWidth: width,
        priceLineVisible: false,
        lastValueVisible: false,
        title: name
    };
    if (style && window.LightweightCharts && window.LightweightCharts.LineStyle && window.LightweightCharts.LineStyle[style] !== undefined) {
        opts.lineStyle = window.LightweightCharts.LineStyle[style];
    }

    const series = addLineSeriesCompat(lwChart, opts);
    if (!series) return;
    series.setData(points);
    overlaySeries.push(series);
}

function addHorizontalOverlay(name, value, fromTime, toTime, color = '#90caf9', style) {
    const numeric = toNumber(value);
    const fromSec = isoToSec(fromTime);
    const toSec = isoToSec(toTime);
    if (numeric === null || fromSec === null || toSec === null) return;
    addOverlayLine(name, [{ time: fromSec, value: numeric }, { time: toSec, value: numeric }], color, 1, style);
}

function applySignalMarkers(fusion) {
    if (!candleSeries || typeof candleSeries.setMarkers !== 'function') return;
    if (!Array.isArray(fusion?.signals)) {
        candleSeries.setMarkers([]);
        return;
    }

    const markers = fusion.signals
        .map((sig) => {
            const timeIso = normalizeTimestamp(sig?.time);
            const sec = isoToSec(timeIso);
            const price = toNumber(sig?.price);
            if (sec === null || price === null) return null;
            const type = String(sig?.type || '').toUpperCase();
            return {
                time: sec,
                position: type === 'SELL' ? 'aboveBar' : 'belowBar',
                color: type === 'SELL' ? '#ff1744' : '#00e676',
                shape: type === 'SELL' ? 'arrowDown' : 'arrowUp',
                text: type || 'SIG'
            };
        })
        .filter(Boolean);

    candleSeries.setMarkers(markers);
}

function applyOverlays(data, prices) {
    if (!lwChart || !Array.isArray(prices) || !prices.length) return;
    const fusion = data?.fusion || {};
    const engine = data?.engine_overlays || {};
    const firstTime = prices[0].time;
    const lastTime = prices[prices.length - 1].time;

    if (chartState.overlays.iceberg && Array.isArray(fusion?.iceberg?.times) && Array.isArray(fusion?.iceberg?.levels)) {
        addOverlayLine('Iceberg', buildLinePoints(fusion.iceberg.times, fusion.iceberg.levels), '#00e676', 2, 'Dashed');
    }
    if (chartState.overlays.gann) {
        if (engine?.gann?.enabled) {
            const lvl0 = toNumber(engine?.gann?.level_0);
            const lvl50 = toNumber(engine?.gann?.level_50);
            const lvl100 = toNumber(engine?.gann?.level_100);
            addHorizontalOverlay('Gann 0', lvl0, firstTime, lastTime, '#ffb74d', 'Dotted');
            addHorizontalOverlay('Gann 50', lvl50, firstTime, lastTime, '#ff9100', 'Dotted');
            addHorizontalOverlay('Gann 100', lvl100, firstTime, lastTime, '#ff6f00', 'Dashed');
        } else if (Array.isArray(fusion?.gann?.times) && Array.isArray(fusion?.gann?.levels)) {
            addOverlayLine('Gann', buildLinePoints(fusion.gann.times, fusion.gann.levels), '#ff9100', 2, 'Dotted');
        }
    }
    if (chartState.overlays.astro && Array.isArray(fusion?.astro?.times) && Array.isArray(fusion?.astro?.levels)) {
        addOverlayLine('Astro', buildLinePoints(fusion.astro.times, fusion.astro.levels), '#7c4dff', 2, 'Dotted');
    }
    if (chartState.overlays.cycle && Array.isArray(fusion?.cycle?.times) && Array.isArray(fusion?.cycle?.levels)) {
        addOverlayLine('Cycle', buildLinePoints(fusion.cycle.times, fusion.cycle.levels), '#40c4ff', 2, 'Dotted');
    }
    if (chartState.overlays.news) {
        if (engine?.news?.enabled && Array.isArray(engine?.news?.line?.times) && Array.isArray(engine?.news?.line?.levels)) {
            addOverlayLine('News', buildLinePoints(engine.news.line.times, engine.news.line.levels), '#ef9a9a', 2, 'Dotted');
        } else if (Array.isArray(fusion?.news?.times) && Array.isArray(fusion?.news?.levels)) {
            addOverlayLine('News', buildLinePoints(fusion.news.times, fusion.news.levels), '#ff1744', 2, 'Dotted');
        }
    }
    if (chartState.overlays.liquidity) {
        const low = toNumber(fusion?.liquidity?.range_low);
        const high = toNumber(fusion?.liquidity?.range_high);
        addHorizontalOverlay('Liquidity Low', low, firstTime, lastTime, '#00bfa5', 'Dotted');
        addHorizontalOverlay('Liquidity High', high, firstTime, lastTime, '#00bfa5', 'Dotted');
        if (Array.isArray(fusion?.liquidity?.times) && Array.isArray(fusion?.liquidity?.equilibrium)) {
            addOverlayLine('Liquidity EQ', buildLinePoints(fusion.liquidity.times, fusion.liquidity.equilibrium), '#64ffda', 2, 'Dashed');
        }
    }

    applySignalMarkers(fusion);
}

function setPrimarySeries(prices, viewportKey = null) {
    if (!ensureChart()) return;

    const candles = prices
        .map((p) => ({
            time: isoToSec(p.time),
            open: p.open,
            high: p.high,
            low: p.low,
            close: p.close
        }))
        .filter((row) => row.time !== null);

    const volumes = prices
        .map((p) => {
            const time = isoToSec(p.time);
            if (time === null) return null;
            return {
                time,
                value: p.volume || 0,
                color: p.close >= p.open ? 'rgba(38,166,154,0.45)' : 'rgba(239,83,80,0.45)'
            };
        })
        .filter(Boolean);

    candleSeries.setData(candles);
    volumeSeries.setData(chartState.overlays.volume ? volumes : []);
    if (!lastViewportKey || (viewportKey && viewportKey !== lastViewportKey)) {
        lwChart.timeScale().fitContent();
        lastViewportKey = viewportKey || lastViewportKey;
    }
}

async function loadComparisonSeries(extraSymbols, tf, sequenceId) {
    if (!ensureChart() || !extraSymbols.length) return;
    const palette = ['#64b5f6', '#ffb74d', '#81c784', '#ba68c8', '#4dd0e1', '#ffd54f'];

    const comparePayloads = await Promise.all(
        extraSymbols.map(async (extraSymbol) => {
            const controller = new AbortController();
            const timer = setTimeout(() => controller.abort(), COMPARE_REQUEST_TIMEOUT_MS);
            try {
                const response = await window.apiFetchJson(`/analyze/${extraSymbol}?tf=${tf}`, { signal: controller.signal });
                return { symbol: extraSymbol, response };
            } catch {
                return null;
            } finally {
                clearTimeout(timer);
            }
        })
    );

    if (sequenceId !== chartLoadSequence) return;

    comparePayloads.filter(Boolean).forEach((entry, index) => {
        const f = entry.response?.fusion || {};
        let prices = normalizePrices(Array.isArray(f.prices) ? f.prices : (Array.isArray(entry.response?.prices) ? entry.response.prices : []));
        if (shouldAggregateToTimeframe(prices, tf)) prices = aggregatePricesToTimeframe(prices, tf);
        if (!prices.length) return;

        const series = addLineSeriesCompat(lwChart, {
            color: palette[index % palette.length],
            lineWidth: 1,
            priceLineVisible: false,
            lastValueVisible: false
        });
        if (!series) return;
        series.setData(prices.map((p) => ({ time: isoToSec(p.time), value: p.close })).filter((row) => row.time !== null));
        compareSeries.set(entry.symbol, series);
    });
}

function applyTickToLastCandle(price, barTimeIso) {
    if (!ensureChart() || !Array.isArray(lastPrimaryBars) || !lastPrimaryBars.length) return;
    const numeric = Number(price);
    if (!Number.isFinite(numeric)) return;

    const latest = lastPrimaryBars[lastPrimaryBars.length - 1];
    const latestSec = isoToSec(latest.time);
    const tickSec = isoToSec(barTimeIso || latest.time);
    if (latestSec === null || tickSec === null || latestSec !== tickSec) return;

    const previousClose = Number(latest.close);
    latest.close = numeric;
    latest.high = Math.max(latest.high, latest.open, numeric);
    latest.low = Math.min(latest.low, latest.open, numeric);

    candleSeries.update({ time: latestSec, open: latest.open, high: latest.high, low: latest.low, close: latest.close });
    const direction = numeric > previousClose ? 1 : (numeric < previousClose ? -1 : 0);
    triggerCandlePrintAnimation(direction);
}

function currentStreamKey(symbol = chartState.symbol, tf = chartState.tf) {
    return `${symbol}|${tf}`;
}

function buildChartStreamUrl(symbol = chartState.symbol, tf = chartState.tf) {
    const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws';
    const host = window.location.hostname;
    return `${protocol}://${host}:8000/ws/chart/${encodeURIComponent(symbol)}?tf=${encodeURIComponent(tf)}&interval=1`;
}

function stopChartStream() {
    if (chartStreamReconnectTimer) {
        clearTimeout(chartStreamReconnectTimer);
        chartStreamReconnectTimer = null;
    }
    if (!chartStreamSocket) return;

    try {
        const socket = chartStreamSocket;
        if (socket.readyState === WebSocket.CONNECTING) {
            socket.onopen = () => { try { socket.close(); } catch { /* noop */ } };
            socket.onerror = null;
            socket.onmessage = null;
            socket.onclose = null;
        } else {
            socket.close();
        }
    } catch {
        // noop
    }

    chartStreamSocket = null;
    updateStreamStatusBadge('reconnect', 'Paused');
}

function scheduleChartReload(delayMs = 120) {
    if (chartReloadTimer) clearTimeout(chartReloadTimer);
    chartReloadTimer = setTimeout(() => {
        chartReloadTimer = null;
        if (chartLoadInProgress) {
            chartLoadPending = true;
            return;
        }
        loadChart(getPrimarySymbol(), chartState.tf);
    }, Math.max(0, delayMs));
}

function startChartStream() {
    const symbol = getPrimarySymbol();
    const tf = chartState.tf;
    const nextKey = currentStreamKey(symbol, tf);

    if (
        chartStreamSocket &&
        (chartStreamSocket.readyState === WebSocket.OPEN || chartStreamSocket.readyState === WebSocket.CONNECTING) &&
        chartStreamKey === nextKey
    ) return;

    stopChartStream();
    chartStreamKey = nextKey;

    try {
        chartStreamSocket = new WebSocket(buildChartStreamUrl(symbol, tf));
        updateStreamStatusBadge('reconnect', 'Connecting');
    } catch (error) {
        console.warn('Chart stream open failed:', error.message);
        updateStreamStatusBadge('unknown', 'Error');
        return;
    }

    const socket = chartStreamSocket;
    socket.onopen = () => {
        if (chartStreamSocket !== socket) return;
        console.info('Chart stream connected', chartStreamKey);
        updateStreamStatusBadge('live', 'Live');
    };

    socket.onmessage = (event) => {
        if (chartStreamSocket !== socket) return;
        if (currentStreamKey() !== chartStreamKey) return;

        try {
            const message = JSON.parse(event.data);
            if (message.type !== 'analyze_tick') return;

            const incomingBarTime = normalizeTimestamp(message.last_bar_time) || null;
            const tickPrice = Number.isFinite(Number(message.live_price))
                ? Number(message.live_price)
                : (Number.isFinite(Number(message.last_close)) ? Number(message.last_close) : null);

            const latestLocalBarTime = lastPrimaryBars.length
                ? (normalizeTimestamp(lastPrimaryBars[lastPrimaryBars.length - 1].time) || null)
                : null;
            const localBucket = latestLocalBarTime ? alignToTimeframeBucket(latestLocalBarTime, tf) : null;
            const incomingBucket = incomingBarTime ? alignToTimeframeBucket(incomingBarTime, tf) : null;

            updateLivePriceBadge(tickPrice, message.last_bar_time || message.server_time);

            const nowMs = Date.now();
            const sameBar = !!(
                incomingBarTime &&
                (
                    (incomingBucket && localBucket && incomingBucket === localBucket) ||
                    incomingBarTime === lastStreamBarTime
                )
            );
            if (sameBar) {
                applyTickToLastCandle(tickPrice, latestLocalBarTime || incomingBarTime);
                if (nowMs - lastStreamReloadMs < PERIODIC_STREAM_REFRESH_MS) return;
            }

            if (!sameBar && nowMs - lastStreamReloadMs < SAME_BAR_RELOAD_MS) return;

            const bucketAdvanced = !!(
                incomingBucket &&
                lastStreamBarBucket &&
                incomingBucket !== lastStreamBarBucket
            );

            if (!sameBar && !bucketAdvanced) {
                lastStreamBarTime = incomingBarTime;
                if (incomingBucket) lastStreamBarBucket = incomingBucket;
                return;
            }

            if (bucketAdvanced && (nowMs - lastNewBarReloadMs < NEW_BAR_RELOAD_GUARD_MS)) {
                lastStreamBarTime = incomingBarTime;
                lastStreamBarBucket = incomingBucket;
                return;
            }

            lastStreamBarTime = incomingBarTime;
            if (incomingBucket) lastStreamBarBucket = incomingBucket;
            lastStreamReloadMs = nowMs;
            if (bucketAdvanced) lastNewBarReloadMs = nowMs;
            scheduleChartReload(80);
        } catch {
            // noop
        }
    };

    socket.onerror = () => {
        if (chartStreamSocket !== socket) return;
        console.warn('Chart stream error; using fallback polling');
        updateStreamStatusBadge('unknown', 'Error');
    };

    socket.onclose = () => {
        if (chartStreamSocket !== socket) return;
        chartStreamSocket = null;
        updateStreamStatusBadge('reconnect', 'Reconnecting');
        if (currentStreamKey() !== chartStreamKey) return;

        if (!chartStreamReconnectTimer) {
            chartStreamReconnectTimer = setTimeout(() => {
                chartStreamReconnectTimer = null;
                if (currentStreamKey() === chartStreamKey) startChartStream();
            }, 2500);
        }
    };
}

async function loadChart(symbol = getPrimarySymbol(), tf = chartState.tf) {
    chartLoadInProgress = true;
    const sequenceId = ++chartLoadSequence;
    if (chartLoadController) chartLoadController.abort();
    chartLoadController = new AbortController();

    let timeoutHandle = null;
    let timedOut = false;

    try {
        if (!ensureChart()) {
            renderChartMessage('Chart engine unavailable');
            return;
        }

        timeoutHandle = setTimeout(() => {
            timedOut = true;
            if (chartLoadController) chartLoadController.abort();
        }, CHART_REQUEST_TIMEOUT_MS);

        const data = await window.apiFetchJson(`/analyze/${symbol}?tf=${tf}`, { signal: chartLoadController.signal });
        if (sequenceId !== chartLoadSequence) return;

        const fusion = data.fusion || {};
        let prices = normalizePrices(Array.isArray(fusion.prices) ? fusion.prices : (Array.isArray(data.prices) ? data.prices : []));
        if (shouldAggregateToTimeframe(prices, tf)) prices = aggregatePricesToTimeframe(prices, tf);

        if (!prices.length) {
            updateDataQualityBadge({ status: 'unknown', label: 'Data Unknown' });
            updateLivePriceBadge(null, null);
            renderChartMessage(`No chart data for ${symbol}`);
            return;
        }

        lastPrimaryBars = prices;
        const viewportKey = `${symbol}|${tf}`;
        setPrimarySeries(prices, viewportKey);
        clearCompareSeries();
        clearOverlaySeries();
        applyOverlays(data, prices);

        const quality = assessDataQuality(prices, tf);
        updateDataQualityBadge(quality);

        const latest = prices[prices.length - 1];
        lastStreamBarTime = normalizeTimestamp(latest?.time) || null;
        lastStreamBarBucket = lastStreamBarTime ? alignToTimeframeBucket(lastStreamBarTime, tf) : null;
        updateLivePriceBadge(latest?.close, latest?.time);

        const extraSymbols = (Array.isArray(chartState.symbols) ? chartState.symbols : [])
            .map((item) => String(item || '').trim())
            .filter((item) => !!item && item !== symbol);

        if (extraSymbols.length) {
            loadComparisonSeries(extraSymbols, tf, sequenceId);
        }
    } catch (error) {
        if (error?.name === 'AbortError') {
            if (timedOut) {
                updateDataQualityBadge({ status: 'sparse', label: 'Feed Slow' });
                if (!lastPrimaryBars.length) {
                    updateLivePriceBadge(null, null);
                    renderChartMessage(`Feed slow for ${symbol} (${tf.toUpperCase()})`);
                }
            }
            return;
        }

        console.error('Chart load failed:', error.message);
        updateDataQualityBadge({ status: 'unknown', label: 'Data Unknown' });
        if (!lastPrimaryBars.length) {
            updateLivePriceBadge(null, null);
            renderChartMessage(`Chart load error: ${error.message}`);
        }
    } finally {
        chartLoadInProgress = false;
        if (timeoutHandle) clearTimeout(timeoutHandle);
        if (sequenceId === chartLoadSequence) chartLoadController = null;
        if (chartLoadPending) {
            chartLoadPending = false;
            scheduleChartReload(140);
        }
    }
}

function startLiveChartRefresh() {
    if (liveChartInterval) clearInterval(liveChartInterval);
    liveChartInterval = setInterval(() => {
        if (!chartStreamSocket || chartStreamSocket.readyState !== WebSocket.OPEN) {
            const nowMs = Date.now();
            if (nowMs - lastDisconnectedReloadMs < DISCONNECTED_RELOAD_COOLDOWN_MS) return;
            lastDisconnectedReloadMs = nowMs;
            scheduleChartReload(0);
        }
    }, PERIODIC_STREAM_REFRESH_MS);
}

window.toggleScrollZoom = function() {
    chartState.scrollZoom = !chartState.scrollZoom;
    saveScrollZoomPreference(chartState.scrollZoom);
    updateScrollZoomButton();
    if (lwChart) {
        lwChart.applyOptions({
            handleScroll: { mouseWheel: !!chartState.scrollZoom, pressedMouseMove: true, horzTouchDrag: true, vertTouchDrag: true },
            handleScale: { mouseWheel: !!chartState.scrollZoom, pinch: true, axisPressedMouseMove: true }
        });
    }
};

window.toggleVolumePanel = function() {
    chartState.overlays.volume = !chartState.overlays.volume;
    updateVolumeToggleButton();
    if (lwChart) {
        const volumeScale = lwChart.priceScale && lwChart.priceScale('volume');
        if (volumeScale && typeof volumeScale.applyOptions === 'function') {
            volumeScale.applyOptions({ visible: !!chartState.overlays.volume });
        }
        if (chartState.overlays.volume && lastPrimaryBars.length) {
            const volumes = lastPrimaryBars.map((p) => ({
                time: isoToSec(p.time),
                value: p.volume || 0,
                color: p.close >= p.open ? 'rgba(38,166,154,0.45)' : 'rgba(239,83,80,0.45)'
            })).filter((v) => v.time !== null);
            volumeSeries.setData(volumes);
        } else {
            volumeSeries.setData([]);
        }
    }
};

window.changeTF = function(tf) {
    chartState.tf = tf;
    lastStreamBarTime = null;
    lastStreamBarBucket = null;
    lastStreamReloadMs = 0;
    lastNewBarReloadMs = 0;
    updateTimeframeButtons();
    updateDataQualityBadge({ status: 'unknown', label: `Loading ${String(tf).toUpperCase()}` });
    stopChartStream();
    startChartStream();
    scheduleChartReload(0);
    if (window.loadMentor) window.loadMentor(getPrimarySymbol());
};

window.toggleOverlay = function(name) {
    chartState.overlays[name] = !chartState.overlays[name];
    updateOverlayButtons();
    scheduleChartReload(0);
};

window.reloadChartData = function() {
    lastStreamBarTime = null;
    lastStreamBarBucket = null;
    lastStreamReloadMs = 0;
    lastNewBarReloadMs = 0;
    stopChartStream();
    startChartStream();
    scheduleChartReload(0);
    if (window.loadMentor) window.loadMentor(getPrimarySymbol());
};

window.resetChartView = function() {
    if (!lwChart) return;
    lwChart.timeScale().fitContent();
};

window.zoomInChart = function() {
    if (!lwChart) return;
    const ts = lwChart.timeScale();
    const range = ts.getVisibleLogicalRange();
    if (!range) return;
    const center = (range.from + range.to) / 2;
    const half = ((range.to - range.from) / 2) * 0.8;
    ts.setVisibleLogicalRange({ from: center - half, to: center + half });
};

window.zoomOutChart = function() {
    if (!lwChart) return;
    const ts = lwChart.timeScale();
    const range = ts.getVisibleLogicalRange();
    if (!range) return;
    const center = (range.from + range.to) / 2;
    const half = ((range.to - range.from) / 2) * 1.25;
    ts.setVisibleLogicalRange({ from: center - half, to: center + half });
};

window.onSymbolChange = function() {
    const symbol = document.getElementById('symbolSelect').value;
    chartState.symbol = symbol;
    chartState.symbols = [symbol];

    const multi = document.getElementById('symbolMultiSelect');
    if (multi) {
        Array.from(multi.options).forEach((option) => {
            option.selected = option.value === symbol;
        });
    }

    lastStreamBarTime = null;
    lastStreamBarBucket = null;
    lastStreamReloadMs = 0;
    lastNewBarReloadMs = 0;
    updateDataQualityBadge({ status: 'unknown', label: `Loading ${chartState.tf.toUpperCase()}` });
    stopChartStream();
    startChartStream();
    scheduleChartReload(0);
    if (window.loadMentor) window.loadMentor(symbol);
};

window.onMultiSymbolChange = function() {
    const multi = document.getElementById('symbolMultiSelect');
    if (!multi) return;

    const selected = Array.from(multi.selectedOptions).map((option) => option.value).filter(Boolean);
    const signature = selected.join('|');
    const nowMs = Date.now();
    if (signature && signature === lastMultiSelectionSignature && (nowMs - lastMultiSelectionAtMs) < 250) {
        return;
    }
    lastMultiSelectionSignature = signature;
    lastMultiSelectionAtMs = nowMs;

    if (!selected.length) {
        chartState.symbols = [chartState.symbol || getPrimarySymbol()];
    } else {
        const primary = multi.value || selected[0];
        chartState.symbol = primary;
        chartState.symbols = [primary, ...selected.filter((sym) => sym !== primary)];
    }

    const single = document.getElementById('symbolSelect');
    if (single) single.value = getPrimarySymbol();

    lastStreamBarTime = null;
    lastStreamBarBucket = null;
    lastStreamReloadMs = 0;
    lastNewBarReloadMs = 0;
    updateDataQualityBadge({ status: 'unknown', label: `Loading ${chartState.tf.toUpperCase()}` });
    stopChartStream();
    startChartStream();
    scheduleChartReload(0);
    if (window.loadMentor) window.loadMentor(getPrimarySymbol());
};

async function populateSymbols() {
    const data = await window.apiFetchJson('/symbols');
    const symbols = Array.isArray(data) ? data : [];

    const sel = document.getElementById('symbolSelect');
    const multi = document.getElementById('symbolMultiSelect');

    if (sel) {
        sel.innerHTML = '';
        symbols.forEach((sym) => {
            const opt = document.createElement('option');
            opt.value = sym;
            opt.innerText = sym;
            sel.appendChild(opt);
        });
    }

    if (multi) {
        multi.innerHTML = '';
        symbols.forEach((sym) => {
            const opt = document.createElement('option');
            opt.value = sym;
            opt.innerText = sym;
            multi.appendChild(opt);
        });
    }

    if (!symbols.includes(chartState.symbol) && symbols.length) {
        chartState.symbol = symbols[0];
    }

    chartState.symbols = (chartState.symbols || []).filter((sym) => symbols.includes(sym));
    if (!chartState.symbols.length && chartState.symbol) chartState.symbols = [chartState.symbol];

    if (sel) {
        sel.value = chartState.symbol;
        sel.onchange = window.onSymbolChange;
    }

    if (multi) {
        const selectedSet = new Set(chartState.symbols);
        Array.from(multi.options).forEach((option) => {
            option.selected = selectedSet.has(option.value);
        });
        if (!multi.dataset.bound) {
            const handler = () => window.onMultiSymbolChange && window.onMultiSymbolChange();
            multi.addEventListener('input', handler);
            multi.addEventListener('change', handler);
            multi.dataset.bound = '1';
        }
    }
}

async function initChart() {
    try {
        chartState.scrollZoom = readScrollZoomPreference();
        updateScrollZoomButton();
        updateVolumeToggleButton();
        updateTimeframeButtons();
        updateOverlayButtons();
        updateDataQualityBadge({ status: 'unknown', label: 'Loading' });
        updateStreamStatusBadge('reconnect', 'Connecting');

        await populateSymbols();
        await loadChart();
        startChartStream();
        startLiveChartRefresh();
    } catch (error) {
        console.error('Chart initialization failed:', error.message);
        renderChartMessage(`Chart initialization failed: ${error.message}`);
    }
}

function teardownChartRuntime() {
    stopChartStream();
    if (liveChartInterval) {
        clearInterval(liveChartInterval);
        liveChartInterval = null;
    }
}

window.addEventListener('beforeunload', teardownChartRuntime);
window.addEventListener('pagehide', teardownChartRuntime);
document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'hidden') {
        teardownChartRuntime();
    }
});

initChart();
