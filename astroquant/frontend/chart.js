let chart;
let candlesSeries;
let volumeSeries;
let vwapSeries;
let atrUpperSeries;
let atrLowerSeries;
let cumDeltaSeries;
let lastRenderKey = "";
let lastRenderedTime = 0;
let cachedPayload = null;
let livePriceLine = null;
let chartRequestInFlight = false;
let chartRefreshQueued = false;
let chartRetryTimer = null;
let chartRequestSerial = 0;
let chartAppliedSerial = 0;
let chartInteractionTimer = null;
const chartInteractionState = {
	isUserInteracting: false,
	lastInteractionAt: 0,
	userMovedAwayFromRightEdge: false,
	lastRenderKey: "",
};
let latestHudCandle = null;

function setChartStateMessage(type, text) {
	const state = document.getElementById("chartState");
	if (!state) return;
	if (!text) {
		state.className = "";
		state.innerText = "";
		state.style.display = "none";
		state.style.color = "";
		return;
	}
	state.className = type || "";
	state.innerText = text;
	state.style.display = "block";
	if (type === "error") {
		state.style.color = "#fca5a5";
	} else if (type === "loading") {
		state.style.color = "#fcd34d";
	} else {
		state.style.color = "";
	}
}

let liquidityLines = [];
let orderBlockLines = [];
let fvgLines = [];
let icebergLines = [];
let gannLines = [];
let vpLines = [];
let latestVpProfile = null;
let tradeLines = [];
let drawingPriceLines = [];

const toggleIds = [
	"toggleLiquidity",
	"toggleOrderBlocks",
	"toggleFVG",
	"toggleIceberg",
	"toggleVWAP",
	"toggleATR",
	"toggleCVD",
	"toggleVP",
	"toggleGann",
	"toggleAstro",
];

const AQ_DEFAULT_CHART_API_ORIGIN = String(window.location.port || "") === "8001"
	? window.location.origin
	: "http://127.0.0.1:8001";
const AQ_API_BASE_CHART = window.AQ_API_BASE || AQ_DEFAULT_CHART_API_ORIGIN;
const AQ_CHART_SETTINGS_KEY = "AQ_CHART_SETTINGS_V2";
const AQ_CHART_DRAWINGS_KEY = "AQ_CHART_DRAWINGS_V1";
const CHART_AUTO_REFRESH_MS = 3000;
const LIVE_PAINT_INTERVAL_MS = 350;
let latestLivePrice = null;
let latestLiveUpdatedAt = 0;
let latestCandleSnapshot = [];
let lastPaintedLivePrice = null;
let drawingMode = "cursor";
let drawingPendingPoint = null;
let drawingObjects = [];
let drawingLineSeries = [];
let selectedDrawingId = null;
let drawingUndoStack = [];
let drawingRedoStack = [];

function timeframeToSeconds(tf) {
	const key = String(tf || "1m").trim().toLowerCase();
	const map = {
		"1m": 60,
		"5m": 300,
		"15m": 900,
		"30m": 1800,
		"1h": 3600,
	};
	return map[key] || 60;
}

function isReasonableLivePrice(livePrice, referenceClose) {
	const live = Number(livePrice);
	const ref = Number(referenceClose);
	if (!Number.isFinite(live) || live <= 0) return false;
	if (!Number.isFinite(ref) || ref <= 0) return true;
	const deviation = Math.abs(live - ref) / ref;
	return deviation <= 0.05;
}

function markChartInteraction() {
	chartInteractionState.isUserInteracting = true;
	chartInteractionState.lastInteractionAt = Date.now();
	if (chartInteractionTimer) clearTimeout(chartInteractionTimer);
	chartInteractionTimer = setTimeout(() => {
		chartInteractionState.isUserInteracting = false;
	}, 1200);
}

function attachChartInteractionHandlers(container) {
	if (!container || container.dataset.aqChartInteractionsBound === "1") return;
	container.dataset.aqChartInteractionsBound = "1";
	container.addEventListener("wheel", markChartInteraction, { passive: true });
	container.addEventListener("mousedown", markChartInteraction);
	container.addEventListener("touchstart", markChartInteraction, { passive: true });
}

function shouldAutoFollow(candles, renderKey, timeframe) {
	if (!Array.isArray(candles) || !candles.length || !chart) return false;
	if (chartInteractionState.lastRenderKey !== renderKey) return true;
	if (chartInteractionState.isUserInteracting) return false;

	const latestTime = Number(candles[candles.length - 1]?.time || 0);
	const range = chart.timeScale()?.getVisibleRange?.();
	if (!range || !Number.isFinite(Number(range.to)) || !Number.isFinite(latestTime)) {
		return true;
	}

	const tfSec = timeframeToSeconds(timeframe);
	const barsFromRight = Math.max(0, Math.round((latestTime - Number(range.to)) / tfSec));
	chartInteractionState.userMovedAwayFromRightEdge = barsFromRight > 3;
	return !chartInteractionState.userMovedAwayFromRightEdge;
}

function addCandlestickSeriesCompat(chartRef, options = {}) {
	if (!chartRef || !window.LightweightCharts) return null;
	if (typeof chartRef.addCandlestickSeries === "function") {
		return chartRef.addCandlestickSeries(options);
	}
	if (typeof chartRef.addSeries === "function" && window.LightweightCharts.CandlestickSeries) {
		return chartRef.addSeries(window.LightweightCharts.CandlestickSeries, options);
	}
	return null;
}

function addHistogramSeriesCompat(chartRef, options = {}) {
	if (!chartRef || !window.LightweightCharts) return null;
	if (typeof chartRef.addHistogramSeries === "function") {
		return chartRef.addHistogramSeries(options);
	}
	if (typeof chartRef.addSeries === "function" && window.LightweightCharts.HistogramSeries) {
		return chartRef.addSeries(window.LightweightCharts.HistogramSeries, options);
	}
	return null;
}

function addLineSeriesCompat(chartRef, options = {}) {
	if (!chartRef || !window.LightweightCharts) return null;
	if (typeof chartRef.addLineSeries === "function") {
		return chartRef.addLineSeries(options);
	}
	if (typeof chartRef.addSeries === "function" && window.LightweightCharts.LineSeries) {
		return chartRef.addSeries(window.LightweightCharts.LineSeries, options);
	}
	return null;
}

function setSeriesMarkersCompat(series, markers) {
	if (!series) return;
	const safeMarkers = Array.isArray(markers) ? markers : [];
	if (typeof series.setMarkers === "function") {
		series.setMarkers(safeMarkers);
		return;
	}
	if (window.LightweightCharts && typeof window.LightweightCharts.createSeriesMarkers === "function") {
		window.LightweightCharts.createSeriesMarkers(series, safeMarkers);
	}
}

function readChartSettings() {
	try {
		const raw = localStorage.getItem(AQ_CHART_SETTINGS_KEY);
		if (!raw) return {};
		const parsed = JSON.parse(raw);
		return (parsed && typeof parsed === "object") ? parsed : {};
	} catch (_) {
		return {};
	}
}

function writeChartSettings(patch) {
	const current = readChartSettings();
	const next = { ...current, ...(patch || {}) };
	try {
		localStorage.setItem(AQ_CHART_SETTINGS_KEY, JSON.stringify(next));
	} catch (_) {
		// ignore quota/private mode failures
	}
}

function readDrawingStore() {
	try {
		const raw = localStorage.getItem(AQ_CHART_DRAWINGS_KEY);
		if (!raw) return {};
		const parsed = JSON.parse(raw);
		return parsed && typeof parsed === "object" ? parsed : {};
	} catch (_) {
		return {};
	}
}

function drawingScopeKey(symbol, timeframe) {
	return `${String(symbol || "GC.FUT")}|${String(timeframe || "1m")}`;
}

function saveDrawings(symbol, timeframe) {
	try {
		const store = readDrawingStore();
		store[drawingScopeKey(symbol, timeframe)] = Array.isArray(drawingObjects) ? drawingObjects : [];
		localStorage.setItem(AQ_CHART_DRAWINGS_KEY, JSON.stringify(store));
	} catch (_) {}
}

function loadDrawings(symbol, timeframe) {
	const store = readDrawingStore();
	const rows = store[drawingScopeKey(symbol, timeframe)];
	drawingObjects = ensureDrawingIds(Array.isArray(rows) ? rows : []);
	selectedDrawingId = null;
	drawingPendingPoint = null;
	drawingUndoStack = [];
	drawingRedoStack = [];
}

function makeDrawingId() {
	return `dw_${Date.now()}_${Math.random().toString(36).slice(2, 9)}`;
}

function ensureDrawingIds(rows) {
	const out = [];
	for (const row of (rows || [])) {
		if (!row || typeof row !== "object") continue;
		out.push({ ...row, id: row.id || makeDrawingId() });
	}
	return out;
}

function cloneDrawingObjects() {
	try {
		return JSON.parse(JSON.stringify(Array.isArray(drawingObjects) ? drawingObjects : []));
	} catch (_) {
		return [];
	}
}

function pushDrawingUndoSnapshot() {
	drawingUndoStack.push(cloneDrawingObjects());
	if (drawingUndoStack.length > 120) drawingUndoStack.shift();
	drawingRedoStack = [];
}

function syncDrawingsAfterMutation() {
	saveDrawings(selectedSymbol(), selectedTimeframe());
	renderDrawings();
}

function undoDrawingChange() {
	if (!drawingUndoStack.length) return;
	drawingRedoStack.push(cloneDrawingObjects());
	drawingObjects = ensureDrawingIds(drawingUndoStack.pop());
	if (!drawingObjects.some(row => row.id === selectedDrawingId)) selectedDrawingId = null;
	syncDrawingsAfterMutation();
}

function redoDrawingChange() {
	if (!drawingRedoStack.length) return;
	drawingUndoStack.push(cloneDrawingObjects());
	drawingObjects = ensureDrawingIds(drawingRedoStack.pop());
	if (!drawingObjects.some(row => row.id === selectedDrawingId)) selectedDrawingId = null;
	syncDrawingsAfterMutation();
}

function selectDrawing(drawingId) {
	selectedDrawingId = drawingId || null;
	renderDrawings();
}

function deleteSelectedDrawing() {
	if (!selectedDrawingId) return;
	const before = drawingObjects.length;
	pushDrawingUndoSnapshot();
	drawingObjects = drawingObjects.filter(row => row.id !== selectedDrawingId);
	selectedDrawingId = null;
	if (drawingObjects.length === before) {
		drawingUndoStack.pop();
		return;
	}
	syncDrawingsAfterMutation();
}

function findNearestDrawing(clickedTime, clickedPrice) {
	if (!Array.isArray(drawingObjects) || !drawingObjects.length) return null;
	let best = null;
	let bestScore = Number.POSITIVE_INFINITY;
	for (const row of drawingObjects) {
		if (!row || typeof row !== "object") continue;
		if (row.type === "hline") {
			const price = Number(row.price);
			if (!Number.isFinite(price)) continue;
			const score = Math.abs(clickedPrice - price);
			if (score < bestScore) {
				bestScore = score;
				best = row;
			}
			continue;
		}
		if (row.type === "trend") {
			const t1 = Number(row.t1);
			const p1 = Number(row.p1);
			const t2 = Number(row.t2);
			const p2 = Number(row.p2);
			if (![t1, p1, t2, p2].every(Number.isFinite)) continue;
			if (t1 === t2) continue;
			const minT = Math.min(t1, t2);
			const maxT = Math.max(t1, t2);
			if (clickedTime < minT - timeframeToSeconds(selectedTimeframe()) * 2 || clickedTime > maxT + timeframeToSeconds(selectedTimeframe()) * 2) continue;
			const slope = (p2 - p1) / (t2 - t1);
			const expected = p1 + ((clickedTime - t1) * slope);
			const score = Math.abs(clickedPrice - expected);
			if (score < bestScore) {
				bestScore = score;
				best = row;
			}
		}
	}
	if (!best) return null;
	const threshold = Math.max(0.8, Math.abs(clickedPrice) * 0.0012);
	return bestScore <= threshold ? best : null;
}

function restoreChartSettings() {
	const settings = readChartSettings();
	const symbol = document.getElementById("chartSymbol");
	const timeframe = document.getElementById("chartTimeframe");
	if (symbol && settings.symbol) {
		symbol.value = settings.symbol;
	}
	if (timeframe && settings.timeframe) {
		timeframe.value = settings.timeframe;
	}
	const toggles = settings.toggles || {};
	for (const id of toggleIds) {
		const el = document.getElementById(id);
		if (!el) continue;
		if (typeof toggles[id] === "boolean") {
			el.checked = toggles[id];
		} else {
			el.checked = false;
		}
	}
}

function captureToggleSettings() {
	const toggles = {};
	for (const id of toggleIds) {
		const el = document.getElementById(id);
		if (!el) continue;
		toggles[id] = Boolean(el.checked);
	}
	writeChartSettings({ toggles });
}

function resetChartSettings() {
	try {
		localStorage.removeItem(AQ_CHART_SETTINGS_KEY);
	} catch (_) {
		// ignore storage failures
	}
	const symbol = document.getElementById("chartSymbol");
	const timeframe = document.getElementById("chartTimeframe");
	if (symbol) symbol.value = "GC.FUT";
	if (timeframe) timeframe.value = "1m";
	for (const id of toggleIds) {
		const el = document.getElementById(id);
		if (el) el.checked = false;
	}
	writeChartSettings({ symbol: "GC.FUT", timeframe: "1m" });
	captureToggleSettings();
	applyOverlayVisibility();
	loadInstitutionalChart().catch(() => {});
}

function createChartIfNeeded() {
	if (chart) return;
	const container = document.getElementById("chart");
	if (!container || !window.LightweightCharts) return;

	chart = LightweightCharts.createChart(container, {
		layout: { background: { color: "#081423" }, textColor: "#b8c9dd" },
		watermark: {
			visible: true,
			fontSize: 32,
			horzAlign: "center",
			vertAlign: "center",
			color: "rgba(130, 146, 168, 0.14)",
			text: `${selectedSymbol()} · ${selectedTimeframe().toUpperCase()}`,
		},
		grid: { vertLines: { color: "#1d314d" }, horzLines: { color: "#1d314d" } },
		crosshair: {
			mode: LightweightCharts.CrosshairMode.Normal,
			vertLine: { labelVisible: true },
			horzLine: { labelVisible: true },
		},
		handleScroll: {
			mouseWheel: true,
			pressedMouseMove: true,
			horzTouchDrag: true,
			vertTouchDrag: true,
		},
		handleScale: {
			axisPressedMouseMove: true,
			mouseWheel: true,
			pinch: true,
		},
		kineticScroll: {
			mouse: true,
			touch: true,
		},
		timeScale: {
			timeVisible: true,
			secondsVisible: false,
			rightOffset: 6,
			barSpacing: 9,
			minBarSpacing: 3,
			rightBarStaysOnScroll: true,
			borderColor: "#2b3e5b",
		},
		rightPriceScale: {
			borderColor: "#2b3e5b",
			autoScale: true,
			scaleMargins: { top: 0.08, bottom: 0.24 },
		},
		leftPriceScale: { visible: false, borderColor: "#2b3e5b" },
		height: 520,
	});
	attachChartInteractionHandlers(container);

	candlesSeries = addCandlestickSeriesCompat(chart, {
		priceScaleId: "right",
		upColor: "#22c55e",
		downColor: "#ef4444",
		wickUpColor: "#22c55e",
		wickDownColor: "#ef4444",
		borderVisible: true,
		borderUpColor: "#22c55e",
		borderDownColor: "#ef4444",
		priceLineVisible: true,
		lastValueVisible: true,
		priceFormat: { type: "price", precision: 2, minMove: 0.01 },
	});
	volumeSeries = addHistogramSeriesCompat(chart, { priceFormat: { type: "volume" }, priceScaleId: "" });
	if (!candlesSeries || !volumeSeries) {
		setChartStateMessage("error", "⚠ Chart library version mismatch");
		return;
	}
	volumeSeries.priceScale().applyOptions({ scaleMargins: { top: 0.8, bottom: 0 } });

	vwapSeries = addLineSeriesCompat(chart, {
		priceScaleId: "right",
		color: "#22d3ee",
		lineWidth: 2,
		priceLineVisible: false,
		lastValueVisible: false,
	});
	atrUpperSeries = addLineSeriesCompat(chart, {
		priceScaleId: "left",
		color: "#f59e0b",
		lineWidth: 1,
		lineStyle: LightweightCharts.LineStyle.Dashed,
		priceLineVisible: false,
		lastValueVisible: false,
	});
	atrLowerSeries = addLineSeriesCompat(chart, {
		priceScaleId: "left",
		color: "#f59e0b",
		lineWidth: 1,
		lineStyle: LightweightCharts.LineStyle.Dashed,
		priceLineVisible: false,
		lastValueVisible: false,
	});
	cumDeltaSeries = addLineSeriesCompat(chart, {
		priceScaleId: "left",
		color: "#93c5fd",
		lineWidth: 2,
		lineStyle: LightweightCharts.LineStyle.Solid,
		priceLineVisible: false,
		lastValueVisible: false,
	});

	window.addEventListener("resize", () => {
		if (!chart || !container) return;
		chart.applyOptions({ width: container.clientWidth });
		refreshVpOverlay();
	});
	chart.applyOptions({ width: container.clientWidth });
	try {
		chart.timeScale()?.subscribeVisibleLogicalRangeChange?.(() => {
			refreshVpOverlay();
		});
	} catch (_) {}

	if (typeof chart.subscribeCrosshairMove === "function") {
		chart.subscribeCrosshairMove((param) => {
			if (!candlesSeries) return;
			let row = null;
			try {
				if (param && param.seriesData && typeof param.seriesData.get === "function") {
					row = param.seriesData.get(candlesSeries) || null;
				}
			} catch (_) {
				row = null;
			}

			if (!row || !Number.isFinite(Number(row.open))) {
				updateTvHud(latestHudCandle || latestCandleSnapshot[latestCandleSnapshot.length - 1] || null, selectedSymbol(), selectedTimeframe());
				return;
			}
			const normalized = {
				time: Number(row.time),
				open: Number(row.open),
				high: Number(row.high),
				low: Number(row.low),
				close: Number(row.close),
			};
			latestHudCandle = normalized;
			updateTvHud(normalized, selectedSymbol(), selectedTimeframe());
		});
	}
	installDrawingClickHandler();
}

function zoomChart(step) {
	if (!chart) return;
	const scale = chart.timeScale();
	if (!scale || typeof scale.options !== "function") return;
	const current = scale.options() || {};
	const spacing = Number(current.barSpacing || 9);
	const nextSpacing = Math.max(2, Math.min(42, spacing + Number(step || 0)));
	chart.applyOptions({
		timeScale: {
			barSpacing: nextSpacing,
			minBarSpacing: 2,
		},
	});
}

function panChartBars(deltaBars) {
	if (!chart) return;
	const scale = chart.timeScale();
	if (!scale || typeof scale.scrollPosition !== "function" || typeof scale.scrollToPosition !== "function") return;
	const current = Number(scale.scrollPosition() || 0);
	scale.scrollToPosition(current + Number(deltaBars || 0), false);
}

function fitChartView() {
	if (!chart) return;
	try {
		chart.timeScale().fitContent();
		chartInteractionState.userMovedAwayFromRightEdge = false;
		chartInteractionState.isUserInteracting = false;
	} catch (_) {}
}

function scrollChartToRealtime() {
	if (!chart) return;
	try {
		chart.timeScale().scrollToRealTime();
		chartInteractionState.userMovedAwayFromRightEdge = false;
	} catch (_) {}
}

function bindChartHotkeys() {
	document.addEventListener("keydown", (event) => {
		const target = event.target;
		const tag = String(target?.tagName || "").toLowerCase();
		if (tag === "input" || tag === "textarea" || tag === "select" || target?.isContentEditable) return;
		if (!chart) return;

		const key = String(event.key || "");
		if ((event.ctrlKey || event.metaKey) && key.toLowerCase() === "z") {
			event.preventDefault();
			undoDrawingChange();
			return;
		}
		if ((event.ctrlKey || event.metaKey) && key.toLowerCase() === "y") {
			event.preventDefault();
			redoDrawingChange();
			return;
		}
		if (key === "Delete" || key === "Backspace") {
			event.preventDefault();
			deleteSelectedDrawing();
			return;
		}
		if (key === "+" || key === "=") {
			event.preventDefault();
			zoomChart(+1.6);
			return;
		}
		if (key === "-" || key === "_") {
			event.preventDefault();
			zoomChart(-1.6);
			return;
		}
		if (key === "ArrowLeft") {
			event.preventDefault();
			panChartBars(-8);
			return;
		}
		if (key === "ArrowRight") {
			event.preventDefault();
			panChartBars(+8);
			return;
		}
		if (key === "0") {
			event.preventDefault();
			fitChartView();
			return;
		}
		if (key === "Escape") {
			event.preventDefault();
			setDrawingMode("cursor");
			return;
		}
		if (key.toLowerCase() === "r") {
			event.preventDefault();
			scrollChartToRealtime();
			return;
		}
	});
}

function updateChartWatermark(symbol, timeframe) {
	if (!chart) return;
	try {
		chart.applyOptions({
			watermark: {
				visible: true,
				fontSize: 32,
				horzAlign: "center",
				vertAlign: "center",
				color: "rgba(130, 146, 168, 0.14)",
				text: `${String(symbol || "--")} · ${String(timeframe || "1m").toUpperCase()}`,
			},
		});
	} catch (_) {}
}

function updateTvHud(candle, symbol, timeframe) {
	const hud = document.getElementById("chartTvHud");
	if (!hud) return;
	if (!candle || !Number.isFinite(Number(candle.open)) || !Number.isFinite(Number(candle.close))) {
		hud.innerText = "--";
		return;
	}
	const open = Number(candle.open);
	const high = Number(candle.high);
	const low = Number(candle.low);
	const close = Number(candle.close);
	const delta = close - open;
	const deltaPct = open !== 0 ? (delta / open) * 100.0 : 0.0;
	const cls = delta >= 0 ? "tv-pos" : "tv-neg";
	hud.innerHTML = [
		`<span>${String(symbol || "--")} ${String(timeframe || "1m").toUpperCase()}</span>`,
		`<span>O ${open.toFixed(2)}</span>`,
		`<span>H ${high.toFixed(2)}</span>`,
		`<span>L ${low.toFixed(2)}</span>`,
		`<span>C ${close.toFixed(2)}</span>`,
		`<span class="${cls}">${delta >= 0 ? "+" : ""}${delta.toFixed(2)} (${delta >= 0 ? "+" : ""}${deltaPct.toFixed(2)}%)</span>`,
	].join(" ");
}

function selectedSymbol() {
	const select = document.getElementById("chartSymbol");
	return select ? select.value : "GC.FUT";
}

function selectedTimeframe() {
	const select = document.getElementById("chartTimeframe");
	return select ? select.value : "1m";
}

function chartApiOrigins() {
	window.AQ_API_BASE = "http://127.0.0.1:8001";
	return ["http://127.0.0.1:8001", "http://127.0.0.1:8000"];
}

async function fetchJson(url, timeoutMs = 12000) {
	const isAbsolute = String(url || "").startsWith("http");
	const targets = isAbsolute
		? [String(url)]
		: chartApiOrigins().map(origin => `${origin}${url}`);

	let lastError = null;
	for (const target of targets) {
		const controller = new AbortController();
		const timer = setTimeout(() => controller.abort(), Math.max(1000, Number(timeoutMs) || 12000));
		try {
			const res = await fetch(target, { signal: controller.signal });
			if (!res.ok) throw new Error(`HTTP ${res.status}`);
			return await res.json();
		} catch (err) {
			lastError = err;
		} finally {
			clearTimeout(timer);
		}
	}
	throw lastError || new Error("Chart request failed");
}

function toSeries(candles, timeframe) {
	const out = [];
	const normalizePriceLike = (value) => {
		const n = Number(value);
		if (!Number.isFinite(n)) return NaN;
		if (Math.abs(n) >= 1_000_000_000) return n / 1_000_000_000;
		return n;
	};
	const tfSec = timeframeToSeconds(timeframe);

	for (const c of (candles || [])) {
		const time = Number(c?.time);
		let open = normalizePriceLike(c?.open);
		let high = normalizePriceLike(c?.high);
		let low = normalizePriceLike(c?.low);
		let close = normalizePriceLike(c?.close);
		const volume = Number(c?.volume || 0);

		if (![time, open, high, low, close].every(Number.isFinite)) continue;
		if (time <= 0) continue;
		if (open <= 0 || high <= 0 || low <= 0 || close <= 0) continue;

		if (low > high) {
			const tmp = low;
			low = high;
			high = tmp;
		}
		high = Math.max(high, open, close);
		low = Math.min(low, open, close);

		out.push({
			time: Math.floor(time),
			open,
			high,
			low,
			close,
			volume: Number.isFinite(volume) ? Math.max(0, volume) : 0,
		});
	}

	if (!out.length) return out;
	out.sort((a, b) => a.time - b.time);

	const bucketed = [];
	for (const row of out) {
		const bucket = Math.floor(Number(row.time) / tfSec) * tfSec;
		const last = bucketed[bucketed.length - 1];
		if (!last || Number(last.time) !== bucket) {
			bucketed.push({
				time: bucket,
				open: Number(row.open),
				high: Number(row.high),
				low: Number(row.low),
				close: Number(row.close),
				volume: Math.max(0, Number(row.volume || 0)),
			});
			continue;
		}
		last.high = Math.max(Number(last.high), Number(row.high));
		last.low = Math.min(Number(last.low), Number(row.low));
		last.close = Number(row.close);
		last.volume = Math.max(0, Number(last.volume || 0)) + Math.max(0, Number(row.volume || 0));
	}

	if (bucketed.length < 2) return bucketed;

	const filled = [bucketed[0]];
	for (let i = 1; i < bucketed.length; i += 1) {
		const prev = filled[filled.length - 1];
		const next = bucketed[i];
		const diff = Number(next.time) - Number(prev.time);
		const missingBars = Math.max(0, Math.floor(diff / tfSec) - 1);

		if (missingBars > 0 && missingBars <= 2) {
			for (let gap = 1; gap <= missingBars; gap += 1) {
				const carry = Number(prev.close);
				filled.push({
					time: Number(prev.time) + (gap * tfSec),
					open: carry,
					high: carry,
					low: carry,
					close: carry,
					volume: 0,
					synthetic_gap_fill: true,
				});
			}
		}

		filled.push(next);
	}

	return filled;
}

function sanitizeLineRows(rows) {
	const out = [];
	for (const row of (rows || [])) {
		const time = Number(row?.time);
		const value = Number(row?.value);
		if (!Number.isFinite(time) || time <= 0) continue;
		if (!Number.isFinite(value)) continue;
		out.push({ time: Math.floor(time), value });
	}
	out.sort((a, b) => a.time - b.time);
	return out;
}

function sanitizeVolumeRows(rows) {
	const out = [];
	for (const row of (rows || [])) {
		const time = Number(row?.time);
		const value = Number(row?.value);
		if (!Number.isFinite(time) || time <= 0) continue;
		if (!Number.isFinite(value) || value < 0) continue;
		const color = typeof row?.color === "string" && row.color ? row.color : "#64748b66";
		out.push({ time: Math.floor(time), value, color });
	}
	out.sort((a, b) => a.time - b.time);

	const deduped = [];
	for (const row of out) {
		if (deduped.length && deduped[deduped.length - 1].time === row.time) {
			deduped[deduped.length - 1] = row;
		} else {
			deduped.push(row);
		}
	}
	return deduped;
}

function volumeColorForCandle(candle) {
	if (candle?.synthetic_gap_fill) return "#64748b33";
	const open = Number(candle?.open);
	const close = Number(candle?.close);
	if (!Number.isFinite(open) || !Number.isFinite(close)) return "#64748b66";
	return close >= open ? "#22c55e66" : "#ef444466";
}

function styleCandlesForRender(candles) {
	const out = [];
	for (const row of (candles || [])) {
		if (!row || typeof row !== "object") continue;
		if (row.synthetic_gap_fill) {
			out.push({
				...row,
				color: "#64748b66",
				borderColor: "#94a3b8",
				wickColor: "#94a3b8",
			});
			continue;
		}
		out.push(row);
	}
	return out;
}

function clearPriceLines(lines) {
	for (const line of lines) {
		try { candlesSeries.removePriceLine(line); } catch (_) {}
	}
	lines.length = 0;
}

function vpOverlayElement() {
	return document.getElementById("chartVpOverlay");
}

function clearVpOverlay() {
	const overlay = vpOverlayElement();
	if (!overlay) return;
	overlay.innerHTML = "";
	overlay.style.display = "none";
}

function paintVpOverlay(profile) {
	const overlay = vpOverlayElement();
	if (!overlay || !candlesSeries) return;
	overlay.innerHTML = "";
	if (!profile || !Array.isArray(profile.bins) || !profile.bins.length) {
		overlay.style.display = "none";
		return;
	}

	const maxBinVolume = Math.max(1, ...profile.bins.map(row => Number(row.volume || 0)));
	const maxWidth = Math.max(20, Math.round((overlay.clientWidth || 0) * 0.34));
	overlay.style.display = "block";

	for (const row of profile.bins) {
		const y = candlesSeries.priceToCoordinate(Number(row.price));
		if (!Number.isFinite(y)) continue;
		const ratio = Math.max(0, Math.min(1, Number(row.volume || 0) / maxBinVolume));
		if (ratio <= 0) continue;

		const bar = document.createElement("div");
		bar.className = "vp-bar";
		if (Math.abs(Number(row.price) - Number(profile.poc?.price || 0)) <= Number(profile.step || 0) * 0.51) {
			bar.classList.add("vp-poc");
		} else if (Number(row.price) >= Number(profile.val) && Number(row.price) <= Number(profile.vah)) {
			bar.classList.add("vp-va");
		}

		const barHeight = Math.max(2, Math.floor((profile.stepPx || 0) * 0.82) || 4);
		const top = Math.max(0, y - Math.floor(barHeight / 2));
		bar.style.top = `${top}px`;
		bar.style.height = `${barHeight}px`;
		bar.style.width = `${Math.max(2, Math.round(maxWidth * ratio))}px`;
		overlay.appendChild(bar);
	}
}

function refreshVpOverlay() {
	const enabled = document.getElementById("toggleVP")?.checked !== false;
	if (!enabled || !latestVpProfile) {
		clearVpOverlay();
		return;
	}
	paintVpOverlay(latestVpProfile);
}

function formatLargeVolume(value) {
	const n = Number(value);
	if (!Number.isFinite(n)) return "--";
	if (n >= 1_000_000_000) return `${(n / 1_000_000_000).toFixed(2)}B`;
	if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(2)}M`;
	if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
	return `${Math.round(n)}`;
}

function computeVolumeProfile(candles, requestedBins = 24) {
	const rows = (candles || []).filter(row =>
		Number.isFinite(Number(row?.high))
		&& Number.isFinite(Number(row?.low))
		&& Number.isFinite(Number(row?.close))
		&& Number.isFinite(Number(row?.volume))
		&& Number(row?.high) > 0
		&& Number(row?.low) > 0
		&& Number(row?.volume) >= 0
	);
	if (!rows.length) return null;

	const minPrice = Math.min(...rows.map(row => Number(row.low)));
	const maxPrice = Math.max(...rows.map(row => Number(row.high)));
	if (!Number.isFinite(minPrice) || !Number.isFinite(maxPrice) || maxPrice <= minPrice) return null;

	const binsCount = Math.max(10, Math.min(40, Number(requestedBins) || 24));
	const step = (maxPrice - minPrice) / binsCount;
	if (!Number.isFinite(step) || step <= 0) return null;

	const bins = Array.from({ length: binsCount }, (_, idx) => ({
		idx,
		price: minPrice + ((idx + 0.5) * step),
		volume: 0,
	}));

	const clampIndex = value => Math.max(0, Math.min(binsCount - 1, value));

	for (const row of rows) {
		const high = Number(row.high);
		const low = Number(row.low);
		const close = Number(row.close);
		const volume = Math.max(0, Number(row.volume || 0));
		if (volume <= 0) continue;

		const span = Math.max(0, high - low);
		if (span <= 0) {
			const idx = clampIndex(Math.floor((close - minPrice) / step));
			bins[idx].volume += volume;
			continue;
		}

		const start = clampIndex(Math.floor((low - minPrice) / step));
		const end = clampIndex(Math.floor((high - minPrice) / step));
		const touched = Math.max(1, (end - start) + 1);
		const share = volume / touched;
		for (let idx = start; idx <= end; idx += 1) {
			bins[idx].volume += share;
		}
	}

	const totalVolume = bins.reduce((acc, row) => acc + Number(row.volume || 0), 0);
	if (!Number.isFinite(totalVolume) || totalVolume <= 0) return null;

	const sortedByVol = [...bins].sort((a, b) => b.volume - a.volume);
	const poc = sortedByVol[0];

	let covered = 0;
	const target = totalVolume * 0.7;
	const selected = [];
	for (const row of sortedByVol) {
		selected.push(row);
		covered += Number(row.volume || 0);
		if (covered >= target) break;
	}

	const vah = selected.reduce((acc, row) => Math.max(acc, Number(row.price)), Number.NEGATIVE_INFINITY);
	const val = selected.reduce((acc, row) => Math.min(acc, Number(row.price)), Number.POSITIVE_INFINITY);

	return {
		bins,
		topBins: sortedByVol.slice(0, 8),
		poc,
		vah,
		val,
		totalVolume,
	};
}

function updateVpLegend(profile, enabled) {
	const legend = document.getElementById("chartVpLegend");
	const pocEl = document.getElementById("vpPoc");
	const vahEl = document.getElementById("vpVah");
	const valEl = document.getElementById("vpVal");
	const totalEl = document.getElementById("vpTotal");
	const levelsEl = document.getElementById("vpTopLevels");
	if (!legend || !pocEl || !vahEl || !valEl || !totalEl || !levelsEl) return;

	if (!enabled || !profile) {
		legend.style.display = "none";
		pocEl.innerText = "--";
		vahEl.innerText = "--";
		valEl.innerText = "--";
		totalEl.innerText = "--";
		levelsEl.innerText = "--";
		return;
	}

	legend.style.display = "block";
	pocEl.innerText = Number(profile.poc?.price || 0).toFixed(2);
	vahEl.innerText = Number(profile.vah || 0).toFixed(2);
	valEl.innerText = Number(profile.val || 0).toFixed(2);
	totalEl.innerText = formatLargeVolume(profile.totalVolume);
	levelsEl.innerText = profile.topBins
		.map((row, idx) => `${idx + 1}:${Number(row.price).toFixed(2)}`)
		.join(" · ");
}

function renderVolumeProfile(candles) {
	clearPriceLines(vpLines);
	const enabled = document.getElementById("toggleVP")?.checked !== false;
	if (!enabled || !Array.isArray(candles) || !candles.length) {
		latestVpProfile = null;
		clearVpOverlay();
		updateVpLegend(null, false);
		return;
	}

	const profile = computeVolumeProfile(candles, 24);
	if (!profile) {
		latestVpProfile = null;
		clearVpOverlay();
		updateVpLegend(null, false);
		return;
	}
	profile.step = Number(profile.bins?.[1]?.price || profile.bins?.[0]?.price || 0) - Number(profile.bins?.[0]?.price || 0);
	const yA = candlesSeries?.priceToCoordinate?.(Number(profile.bins[0]?.price));
	const yB = candlesSeries?.priceToCoordinate?.(Number(profile.bins[1]?.price || profile.bins[0]?.price));
	profile.stepPx = Number.isFinite(yA) && Number.isFinite(yB) ? Math.abs(yA - yB) : 5;
	latestVpProfile = profile;
	paintVpOverlay(profile);

	const maxBinVolume = Math.max(1, ...profile.topBins.map(row => Number(row.volume || 0)));
	for (const row of profile.topBins) {
		const ratio = Math.max(0.12, Math.min(1, Number(row.volume || 0) / maxBinVolume));
		const inValueArea = Number(row.price) >= Number(profile.val) && Number(row.price) <= Number(profile.vah);
		const color = inValueArea
			? `rgba(56,189,248,${(0.25 + (ratio * 0.55)).toFixed(3)})`
			: `rgba(148,163,184,${(0.18 + (ratio * 0.35)).toFixed(3)})`;
		const pct = (Number(row.volume || 0) / Number(profile.totalVolume || 1)) * 100;
		addHorizontalLine(Number(row.price), `VP ${pct.toFixed(1)}%`, color, vpLines);
	}

	if (Number.isFinite(Number(profile.poc?.price))) {
		addHorizontalLine(Number(profile.poc.price), "POC", "#facc15", vpLines);
	}
	if (Number.isFinite(Number(profile.vah))) {
		addHorizontalLine(Number(profile.vah), "VAH", "#60a5fa", vpLines);
	}
	if (Number.isFinite(Number(profile.val))) {
		addHorizontalLine(Number(profile.val), "VAL", "#60a5fa", vpLines);
	}

	updateVpLegend(profile, true);
}

function clearDrawingSeries() {
	clearPriceLines(drawingPriceLines);
	for (const series of drawingLineSeries) {
		try { chart.removeSeries(series); } catch (_) {}
	}
	drawingLineSeries = [];
}

function renderDrawings() {
	if (!chart || !candlesSeries) return;
	clearDrawingSeries();
	for (const row of drawingObjects) {
		if (!row || typeof row !== "object") continue;
		const selected = row.id && row.id === selectedDrawingId;
		if (row.type === "hline") {
			const price = Number(row.price);
			if (!Number.isFinite(price)) continue;
			const line = candlesSeries.createPriceLine({
				price,
				color: selected ? "#facc15" : "#60a5fa",
				lineWidth: selected ? 2 : 1,
				lineStyle: LightweightCharts.LineStyle.Solid,
				title: selected ? `${row.label || "HLine"}*` : (row.label || "HLine"),
				axisLabelVisible: true,
			});
			drawingPriceLines.push(line);
			continue;
		}
		if (row.type === "trend") {
			const t1 = Number(row.t1);
			const p1 = Number(row.p1);
			const t2 = Number(row.t2);
			const p2 = Number(row.p2);
			if (![t1, p1, t2, p2].every(Number.isFinite)) continue;
			const series = addLineSeriesCompat(chart, {
				priceScaleId: "right",
				color: selected ? "#facc15" : "#60a5fa",
				lineWidth: selected ? 3 : 2,
				priceLineVisible: false,
				lastValueVisible: false,
			});
			if (!series) continue;
			series.setData([
				{ time: Math.floor(t1), value: p1 },
				{ time: Math.floor(t2), value: p2 },
			]);
			drawingLineSeries.push(series);
		}
	}
}

function setDrawingMode(mode) {
	drawingMode = String(mode || "cursor").toLowerCase();
	drawingPendingPoint = null;
	const ids = ["chartToolCrosshair", "chartToolHLine", "chartToolTrend", "chartToolMove"];
	for (const id of ids) {
		const el = document.getElementById(id);
		if (!el) continue;
		el.style.borderColor = "";
		el.style.background = "";
	}
	const activeMap = {
		cursor: "chartToolCrosshair",
		hline: "chartToolHLine",
		trend: "chartToolTrend",
		move: "chartToolMove",
	};
	const active = document.getElementById(activeMap[drawingMode]);
	if (active) {
		active.style.borderColor = "#38bdf8";
		active.style.background = "#11304d";
	}
	if (drawingMode === "trend") {
		setChartStateMessage("loading", "Trend mode: click start point, then click end point");
	} else if (drawingMode === "hline") {
		setChartStateMessage("loading", "HLine mode: click chart to place horizontal line");
	} else if (drawingMode === "move") {
		setChartStateMessage("loading", "Move mode: click a drawing, then click new location");
	} else {
		setChartStateMessage("", "");
	}
}

function normalizeChartClickTime(rawTime) {
	if (typeof rawTime === "number" && Number.isFinite(rawTime)) return Math.floor(rawTime);
	if (!rawTime || typeof rawTime !== "object") return null;
	if (Number.isFinite(Number(rawTime.timestamp))) return Math.floor(Number(rawTime.timestamp));
	const year = Number(rawTime.year);
	const month = Number(rawTime.month);
	const day = Number(rawTime.day);
	if (![year, month, day].every(Number.isFinite)) return null;
	return Math.floor(Date.UTC(year, month - 1, day) / 1000);
}

function installDrawingClickHandler() {
	if (!chart || typeof chart.subscribeClick !== "function") return;
	if (chart.__aqDrawingClickInstalled) return;
	chart.__aqDrawingClickInstalled = true;
	chart.subscribeClick((param) => {
		if (!candlesSeries) return;
		if (!param || !param.point) return;

		const clickedTime = normalizeChartClickTime(param.time);
		const clickedPrice = Number(candlesSeries.coordinateToPrice(param.point.y));
		if (!Number.isFinite(clickedTime) || !Number.isFinite(clickedPrice)) return;

		if (drawingMode === "cursor") {
			const nearest = findNearestDrawing(clickedTime, clickedPrice);
			selectDrawing(nearest?.id || null);
			return;
		}

		if (drawingMode === "move") {
			if (!selectedDrawingId) {
				const nearest = findNearestDrawing(clickedTime, clickedPrice);
				selectDrawing(nearest?.id || null);
				if (nearest) setChartStateMessage("loading", "Move mode: click new location");
				return;
			}
			const idx = drawingObjects.findIndex(row => row.id === selectedDrawingId);
			if (idx < 0) return;
			const target = drawingObjects[idx];
			pushDrawingUndoSnapshot();
			if (target.type === "hline") {
				target.price = clickedPrice;
				syncDrawingsAfterMutation();
				setChartStateMessage("loading", "Move mode: click a drawing, then click new location");
				return;
			}
			if (target.type === "trend") {
				const t1 = Number(target.t1);
				const p1 = Number(target.p1);
				const t2 = Number(target.t2);
				const p2 = Number(target.p2);
				if (![t1, p1, t2, p2].every(Number.isFinite)) return;
				const midT = (t1 + t2) / 2.0;
				const midP = (p1 + p2) / 2.0;
				const dt = clickedTime - midT;
				const dp = clickedPrice - midP;
				target.t1 = Math.floor(t1 + dt);
				target.t2 = Math.floor(t2 + dt);
				target.p1 = p1 + dp;
				target.p2 = p2 + dp;
				syncDrawingsAfterMutation();
				setChartStateMessage("loading", "Move mode: click a drawing, then click new location");
			}
			return;
		}

		if (drawingMode === "hline") {
			pushDrawingUndoSnapshot();
			drawingObjects.push({ id: makeDrawingId(), type: "hline", price: clickedPrice, label: "HLine" });
			selectedDrawingId = drawingObjects[drawingObjects.length - 1]?.id || null;
			syncDrawingsAfterMutation();
			return;
		}

		if (drawingMode === "trend") {
			if (!drawingPendingPoint) {
				drawingPendingPoint = { t: clickedTime, p: clickedPrice };
				setChartStateMessage("loading", "Trend mode: click end point");
				return;
			}
			pushDrawingUndoSnapshot();
			drawingObjects.push({
				id: makeDrawingId(),
				type: "trend",
				t1: drawingPendingPoint.t,
				p1: drawingPendingPoint.p,
				t2: clickedTime,
				p2: clickedPrice,
			});
			selectedDrawingId = drawingObjects[drawingObjects.length - 1]?.id || null;
			drawingPendingPoint = null;
			syncDrawingsAfterMutation();
			setChartStateMessage("loading", "Trend mode: click start point, then click end point");
		}
	});
}

function addHorizontalLine(price, title, color, store) {
	const line = candlesSeries.createPriceLine({
		price: Number(price),
		color,
		lineWidth: 1,
		lineStyle: LightweightCharts.LineStyle.Dotted,
		title,
		axisLabelVisible: true,
	});
	store.push(line);
}

function setLineGroupFromPrices(store, rows, color, titleBuilder) {
	clearPriceLines(store);
	for (const row of rows || []) {
		const price = Number(row.price);
		if (!Number.isFinite(price)) continue;
		addHorizontalLine(price, titleBuilder(row), color, store);
	}
}

function renderOverlayPriceLines(overlays) {
	setLineGroupFromPrices(liquidityLines, overlays?.liquidity || [], "#38bdf8", row => `Liquidity ${row.strength || ""}`);

	clearPriceLines(orderBlockLines);
	for (const row of overlays?.order_blocks || []) {
		const color = String(row.direction || "").toUpperCase() === "BULLISH" ? "#22c55e" : "#ef4444";
		if (Number.isFinite(Number(row.high))) addHorizontalLine(Number(row.high), "OB High", color, orderBlockLines);
		if (Number.isFinite(Number(row.low))) addHorizontalLine(Number(row.low), "OB Low", color, orderBlockLines);
	}

	clearPriceLines(fvgLines);
	for (const row of overlays?.fvg || []) {
		if (Number.isFinite(Number(row.high))) addHorizontalLine(Number(row.high), "FVG High", "#fb7185", fvgLines);
		if (Number.isFinite(Number(row.low))) addHorizontalLine(Number(row.low), "FVG Low", "#fb7185", fvgLines);
	}

	setLineGroupFromPrices(icebergLines, overlays?.iceberg || [], "#f97316", row => `Iceberg ${row.absorption_strength || ""}`);
	setLineGroupFromPrices(gannLines, overlays?.gann_lines || [], "#a78bfa", row => row.label || "Gann");
}

function renderTradeLines(meta, candles) {
	clearPriceLines(tradeLines);
	const position = meta?.position;
	if (position) {
		if (position.entry_price != null) addHorizontalLine(position.entry_price, "Entry", "#22c55e", tradeLines);
		if (position.sl != null) addHorizontalLine(position.sl, "SL", "#ef4444", tradeLines);
		if (position.tp != null) addHorizontalLine(position.tp, `TP${position.rr ? ` RR:${position.rr}` : ""}`, "#10b981", tradeLines);
	}

	const lastClose = Number(candles[candles.length - 1]?.close);
	const liveCandidate = Number(latestLivePrice);
	const current = isReasonableLivePrice(liveCandidate, lastClose) ? liveCandidate : lastClose;
	if (current != null) {
		upsertLivePriceLine(Number(current));
	}
}

function upsertLivePriceLine(price) {
	if (!candlesSeries || !Number.isFinite(Number(price))) return;
	const px = Number(price);
	if (livePriceLine && typeof livePriceLine.applyOptions === "function") {
		try {
			livePriceLine.applyOptions({ price: px });
			return;
		} catch (_) {}
	}
	if (livePriceLine) {
		try { candlesSeries.removePriceLine(livePriceLine); } catch (_) {}
	}
	livePriceLine = candlesSeries.createPriceLine({
		price: px,
		color: "#facc15",
		lineWidth: 1,
		lineStyle: LightweightCharts.LineStyle.Solid,
		title: "Live",
		axisLabelVisible: true,
	});
}

function paintLiveCandleFromQuote(timeframe) {
	if (!chart || !candlesSeries || !volumeSeries) return;
	if (!Array.isArray(latestCandleSnapshot) || latestCandleSnapshot.length === 0) return;
	if (!Number.isFinite(Number(latestLivePrice)) || Number(latestLivePrice) <= 0) return;
	if (lastPaintedLivePrice != null && Math.abs(Number(latestLivePrice) - Number(lastPaintedLivePrice)) < 0.000001) return;

	const price = Number(latestLivePrice);
	const tfSec = timeframeToSeconds(timeframe);
	const nowSec = Math.floor(Date.now() / 1000);
	const bucket = Math.floor(nowSec / tfSec) * tfSec;
	const prev = latestCandleSnapshot[latestCandleSnapshot.length - 1];
	if (!prev || !Number.isFinite(Number(prev.time))) return;
	if (!isReasonableLivePrice(price, Number(prev.close))) return;

	let updated;
	if (Number(prev.time) === bucket) {
		updated = {
			time: Number(prev.time),
			open: Number(prev.open),
			high: Math.max(Number(prev.high), price),
			low: Math.min(Number(prev.low), price),
			close: price,
			volume: Math.max(0, Number(prev.volume || 0)),
		};
		latestCandleSnapshot[latestCandleSnapshot.length - 1] = updated;
	} else if (bucket > Number(prev.time)) {
		updated = {
			time: bucket,
			open: Number(prev.close),
			high: Math.max(Number(prev.close), price),
			low: Math.min(Number(prev.close), price),
			close: price,
			volume: 0,
		};
		latestCandleSnapshot.push(updated);
		if (latestCandleSnapshot.length > 400) {
			latestCandleSnapshot = latestCandleSnapshot.slice(-400);
		}
	} else {
		return;
	}

	try {
		candlesSeries.update(updated);
		volumeSeries.update({ time: updated.time, value: updated.volume, color: volumeColorForCandle(updated) });
	} catch (_) {
		try {
			candlesSeries.setData(latestCandleSnapshot);
			volumeSeries.setData(latestCandleSnapshot.map(row => ({
				time: Number(row.time),
				value: Math.max(0, Number(row.volume || 0)),
				color: volumeColorForCandle(row),
			})));
		} catch (_) {}
	}

	const livePriceLabel = document.getElementById("chartLivePrice");
	if (livePriceLabel) livePriceLabel.innerText = price.toFixed(2);
	upsertLivePriceLine(price);
	lastPaintedLivePrice = price;
}

function buildMarkers(payload) {
	const signals = (payload?.signals || []).map(m => ({
		time: Number(m.time),
		position: String(m.direction || "").toUpperCase() === "BUY" ? "belowBar" : "aboveBar",
		shape: String(m.direction || "").toUpperCase() === "BUY" ? "arrowUp" : "arrowDown",
		color: String(m.direction || "").toUpperCase() === "BUY" ? "#22c55e" : "#ef4444",
		text: m.model || "SIG",
	}));
	return [...signals]
		.filter(m => Number.isFinite(Number(m?.time)) && Number(m.time) > 0)
		.sort((a, b) => a.time - b.time);
}

function updateChartMeta(payload, timeframe, candles) {
	const meta = payload?.meta || {};
	document.getElementById("chartInstrument").innerText = selectedSymbol();
	document.getElementById("chartTf").innerText = timeframe || "--";
	const liveFromMeta = Number(meta?.live_quote?.price);
	const lastClose = candles.length ? Number(candles[candles.length - 1].close) : NaN;
	const safeLiveFromMeta = isReasonableLivePrice(liveFromMeta, lastClose) ? liveFromMeta : NaN;
	const safeLiveState = isReasonableLivePrice(Number(latestLivePrice), lastClose) ? Number(latestLivePrice) : NaN;
	const uiPrice = Number.isFinite(safeLiveFromMeta) && safeLiveFromMeta > 0
		? safeLiveFromMeta
		: (Number.isFinite(safeLiveState) && safeLiveState > 0
			? safeLiveState
			: lastClose);
	document.getElementById("chartLivePrice").innerText = Number.isFinite(uiPrice) ? uiPrice.toFixed(2) : "--";
	document.getElementById("chartAutoMode").innerText = meta.auto_mode || "--";
	document.getElementById("chartRisk").innerText = meta.risk_percent != null ? `${Number(meta.risk_percent).toFixed(2)}%` : "--";
	document.getElementById("chartVolatility").innerText = meta.volatility_state || "--";
	document.getElementById("chartSpread").innerText = "--";
	document.getElementById("chartSession").innerText = "--";

	document.getElementById("chartConfidence").innerText = meta.confidence != null ? Number(meta.confidence).toFixed(2) : "--";
	document.getElementById("chartVolBadge").innerText = meta.volatility_state || "--";
	document.getElementById("chartPhaseBadge").innerText = meta.phase || "--";
	document.getElementById("chartNewsBadge").innerText = meta.news || "--";
	document.getElementById("chartDataSource").innerText = meta.data_source || "--";

	const state = document.getElementById("chartState");
	if (state) {
		const degradedData = Boolean(meta.degraded_data);
		const cooldownActive = Boolean(meta.feed_cooldown_active);
		const cooldownSeconds = Number(meta.feed_cooldown_seconds || 0);
		if (meta.system_paused) {
			state.className = "paused";
			state.innerText = `⚠ SYSTEM PAUSED${meta.pause_reason ? ` — ${meta.pause_reason}` : ""}${degradedData ? ` · ${meta.degraded_message || "Degraded feed"}` : ""}`;
			state.style.display = "block";
		} else if (degradedData) {
			state.className = "";
			state.innerText = `⚠ ${meta.degraded_message || "Degraded feed data"}${cooldownActive ? ` (${cooldownSeconds.toFixed(1)}s)` : ""}`;
			state.style.display = "block";
		} else {
			state.className = "";
			state.innerText = "";
			state.style.display = "none";
		}
	}
}

function fmtChartTime(epochSec) {
	if (!Number.isFinite(Number(epochSec))) return "--";
	return new Date(Number(epochSec) * 1000).toLocaleTimeString();
}

function fmtTimeCell(epochSec) {
	const n = Number(epochSec);
	if (!Number.isFinite(n) || n <= 0) return `<div class="time-main">--</div><div class="time-sub">IST --</div>`;
	const dt = new Date(n * 1000);
	const local = dt.toLocaleTimeString(undefined, { hour12: false });
	const ist = dt.toLocaleTimeString("en-IN", { timeZone: "Asia/Kolkata", hour12: false });
	return `<div class="time-main">${local}</div><div class="time-sub">IST ${ist}</div>`;
}

function setTableBodyRows(bodyId, rows, emptyText, colCount) {
	const body = document.getElementById(bodyId);
	if (!body) return;
	body.innerHTML = "";
	if (!Array.isArray(rows) || rows.length === 0) {
		const tr = document.createElement("tr");
		tr.innerHTML = `<td colspan="${Math.max(1, Number(colCount) || 1)}">${emptyText}</td>`;
		body.appendChild(tr);
		return;
	}
	for (const html of rows) {
		const tr = document.createElement("tr");
		tr.innerHTML = html;
		body.appendChild(tr);
	}
}

function renderMicrostructureTables(payload, candles) {
	const overlays = payload?.overlays || {};
	const recent = Array.isArray(candles) ? candles.slice(-20) : [];
	const newestFirst = [...recent].reverse();

	const icebergRowsRaw = Array.isArray(overlays.iceberg) ? overlays.iceberg.slice(-12).reverse() : [];
	const icebergRows = icebergRowsRaw.map(row => {
		const strength = Number(row?.absorption_strength || 0);
		const confidence = Math.max(0, Math.min(99, strength * 45));
		return `<td>${fmtTimeCell(Number(row?.time || 0))}</td><td>${Number(row?.price || 0).toFixed(2)}</td><td>${strength.toFixed(2)}</td><td>${confidence.toFixed(0)}%</td>`;
	});
	setTableBodyRows("icebergTableBody", icebergRows, "No iceberg levels", 4);

	const orderflowRows = newestFirst.slice(0, 16).map(row => {
		const volume = Math.max(0, Number(row?.volume || 0));
		const upCandle = Number(row?.close || 0) >= Number(row?.open || 0);
		const buyVol = upCandle ? volume * 0.65 : volume * 0.35;
		const sellVol = Math.max(0, volume - buyVol);
		const delta = buyVol - sellVol;
		const deltaCls = delta >= 0 ? "delta-pos" : "delta-neg";
		return `<td>${fmtTimeCell(Number(row?.time || 0))}</td><td class="side-buy">${Math.round(buyVol)}</td><td class="side-sell">${Math.round(sellVol)}</td><td class="${deltaCls}">${delta >= 0 ? "+" : ""}${Math.round(delta)}</td>`;
	});
	const deltaRows = Array.isArray(payload?.meta?.delta_candles) ? payload.meta.delta_candles : [];
	const orderflowRowsRendered = deltaRows.length
		? deltaRows.slice(-16).reverse().map(row => {
			const buyVol = Math.max(0, Number(row?.buy_volume || 0));
			const sellVol = Math.max(0, Number(row?.sell_volume || 0));
			const delta = Number(row?.delta || (buyVol - sellVol));
			const deltaCls = delta >= 0 ? "delta-pos" : "delta-neg";
			return `<td>${fmtTimeCell(Number(row?.time || 0))}</td><td class="side-buy">${Math.round(buyVol)}</td><td class="side-sell">${Math.round(sellVol)}</td><td class="${deltaCls}">${delta >= 0 ? "+" : ""}${Math.round(delta)}</td>`;
		})
		: orderflowRows;
	setTableBodyRows("orderflowTableBody", orderflowRowsRendered, "No order flow rows", 4);

	const deltaSummary = payload?.meta?.delta_summary || {};
	const orderflowSummary = payload?.meta?.orderflow_summary || {};
	const setText = (id, value, cls) => {
		const el = document.getElementById(id);
		if (!el) return;
		el.classList.remove("delta-pos", "delta-neg", "side-buy", "side-sell");
		if (cls) el.classList.add(cls);
		el.innerText = value;
	};
	const netDelta = Number(deltaSummary?.delta || 0);
	const cumDelta = Number(deltaSummary?.cumulative_delta || 0);
	setText("orderflowDeltaNet", `${netDelta >= 0 ? "+" : ""}${Math.round(netDelta)}`, netDelta >= 0 ? "delta-pos" : "delta-neg");
	setText("orderflowCumDelta", `${cumDelta >= 0 ? "+" : ""}${Math.round(cumDelta)}`, cumDelta >= 0 ? "delta-pos" : "delta-neg");
	setText("orderflowBuyAggr", `${Number(deltaSummary?.buy_aggression || 0).toFixed(1)}%`, "side-buy");
	setText("orderflowSellAggr", `${Number(deltaSummary?.sell_aggression || 0).toFixed(1)}%`, "side-sell");

	setText("summaryBuyAgg", `${Number(orderflowSummary?.buy_aggression || 0).toFixed(1)}%`, "side-buy");
	setText("summarySellAgg", `${Number(orderflowSummary?.sell_aggression || 0).toFixed(1)}%`, "side-sell");
	setText("summaryRegime", String(orderflowSummary?.regime_mode || "--"), null);
	const alertLevel = String(orderflowSummary?.alert_level || "LOW").toUpperCase();
	setText("summaryAlert", alertLevel, alertLevel === "HIGH" ? "delta-neg" : (alertLevel === "MEDIUM" ? "side-sell" : "side-buy"));
	setText("summarySignalStrength", `${Number(orderflowSummary?.signal_strength || 0).toFixed(1)}%`, null);
	const summaryDelta = Number(orderflowSummary?.delta || 0);
	const summaryCvd = Number(orderflowSummary?.cumulative_delta || 0);
	setText("summaryDelta", `${summaryDelta >= 0 ? "+" : ""}${Math.round(summaryDelta)}`, summaryDelta >= 0 ? "delta-pos" : "delta-neg");
	setText("summaryCvd", `${summaryCvd >= 0 ? "+" : ""}${Math.round(summaryCvd)}`, summaryCvd >= 0 ? "delta-pos" : "delta-neg");
	setText("summaryImbalance", String(orderflowSummary?.imbalance || "--"), null);
	setText("summarySpread", Number(orderflowSummary?.dom_spread || 0).toFixed(2), null);
	setText("summaryIceberg", `${Math.max(0, Math.round(Number(orderflowSummary?.iceberg_count || 0)))}`, null);
	const absorption = String(orderflowSummary?.absorption || "NEUTRAL").toUpperCase();
	setText("summaryAbsorption", absorption, absorption === "BULLISH" ? "side-buy" : (absorption === "BEARISH" ? "side-sell" : null));
	setText("summaryConfidence", `${Number(orderflowSummary?.confidence || 0).toFixed(1)}%`, null);
	setText("summaryNarrative", String(orderflowSummary?.narrative || "--"), null);

	const tapeSource = Array.isArray(payload?.meta?.time_sales) ? payload.meta.time_sales : [];
	let tapeRows = [];
	if (tapeSource.length) {
		tapeRows = tapeSource.slice(-24).reverse().map(row => {
			const side = String(row?.side || "").toUpperCase() === "SELL" ? "SELL" : "BUY";
			const sideCls = side === "BUY" ? "side-buy" : "side-sell";
			const delta = Number(row?.delta || 0);
			const deltaCls = delta >= 0 ? "delta-pos" : "delta-neg";
			return `<td>${fmtTimeCell(Number(row?.time || 0))}</td><td>${Number(row?.price || 0).toFixed(2)}</td><td>${Math.round(Math.max(0, Number(row?.size || 0)))}</td><td class="${sideCls}">${side}</td><td class="${deltaCls}">${delta >= 0 ? "+" : ""}${Math.round(delta)}</td>`;
		});
	} else {
		let runningDelta = 0;
		tapeRows = newestFirst.slice(0, 20).map(row => {
			const close = Number(row?.close || 0);
			const volume = Math.max(0, Number(row?.volume || 0));
			const side = close >= Number(row?.open || 0) ? "BUY" : "SELL";
			const sideCls = side === "BUY" ? "side-buy" : "side-sell";
			const delta = side === "BUY" ? volume : -volume;
			runningDelta += delta;
			const deltaCls = delta >= 0 ? "delta-pos" : "delta-neg";
			return `<td>${fmtTimeCell(Number(row?.time || 0))}</td><td>${close.toFixed(2)}</td><td>${Math.round(volume)}</td><td class="${sideCls}">${side}</td><td class="${deltaCls}">${delta >= 0 ? "+" : ""}${Math.round(delta)}</td>`;
		});
	}
	setTableBodyRows("timeSalesTableBody", tapeRows, "No time & sales rows", 5);

	const latest = candles[candles.length - 1] || null;
	const ladderRows = Array.isArray(payload?.meta?.dom_ladder) ? payload.meta.dom_ladder : [];
	let ladderRowsRaw = [];
	if (ladderRows.length) {
		ladderRowsRaw = ladderRows.slice(-28).map(row => {
			const bid = Math.max(0, Math.round(Number(row?.bid_size || 0)));
			const ask = Math.max(0, Math.round(Number(row?.ask_size || 0)));
			return `<td>${fmtTimeCell(Number(row?.time || 0))}</td><td>${Number(row?.price || 0).toFixed(2)}</td><td class="ladder-bid">${bid > 0 ? bid : ""}</td><td class="ladder-ask">${ask > 0 ? ask : ""}</td>`;
		});
	} else {
		const recentSpan = recent.length
			? (Math.max(...recent.map(c => Number(c?.high || 0))) - Math.min(...recent.map(c => Number(c?.low || 0))))
			: 0;
		const base = latest ? Number(latest.close || 0) : 0;
		const tick = Math.max(0.01, recentSpan > 0 ? recentSpan / 24 : base * 0.0004 || 0.01);
		for (let i = 6; i >= -5; i -= 1) {
			const price = base + (i * tick);
			if (!Number.isFinite(price) || price <= 0) continue;
			const proximity = Math.max(0.2, 1.0 - (Math.abs(i) / 8));
			const refVol = Math.max(1, Number(latest?.volume || 1));
			const bid = Math.round(refVol * proximity * (i <= 0 ? 0.8 : 0.5));
			const ask = Math.round(refVol * proximity * (i >= 0 ? 0.8 : 0.5));
			ladderRowsRaw.push(`<td>${fmtTimeCell(Number(latest?.time || 0))}</td><td>${price.toFixed(2)}</td><td class="ladder-bid">${bid}</td><td class="ladder-ask">${ask}</td>`);
		}
	}
	setTableBodyRows("ladderTableBody", ladderRowsRaw, "No ladder levels", 4);

	const domSummary = payload?.meta?.dom_summary || {};
	setText("ladderSpread", Number(domSummary?.spread || 0).toFixed(2), null);
	const imbalance = Number(domSummary?.imbalance || 0);
	setText("ladderImbalance", `${imbalance >= 0 ? "+" : ""}${imbalance.toFixed(1)}%`, imbalance >= 0 ? "delta-pos" : "delta-neg");
	const bidWallPx = Number(domSummary?.bid_wall?.price || 0);
	const bidWallSz = Math.round(Math.max(0, Number(domSummary?.bid_wall?.size || 0)));
	const askWallPx = Number(domSummary?.ask_wall?.price || 0);
	const askWallSz = Math.round(Math.max(0, Number(domSummary?.ask_wall?.size || 0)));
	setText("ladderBidWall", bidWallPx > 0 ? `${bidWallPx.toFixed(2)} @ ${bidWallSz}` : "--", "side-buy");
	setText("ladderAskWall", askWallPx > 0 ? `${askWallPx.toFixed(2)} @ ${askWallSz}` : "--", "side-sell");
}

function updateCandlesSmoothly(candles, volumeRows, renderKey, timeframe) {
	if (!Array.isArray(candles) || candles.length === 0) {
		candlesSeries.setData([]);
		volumeSeries.setData([]);
		latestCandleSnapshot = [];
		latestHudCandle = null;
		lastRenderKey = renderKey;
		lastRenderedTime = 0;
		return;
	}

	const safeCandles = candles.filter(row =>
		Number.isFinite(Number(row?.time))
		&& Number.isFinite(Number(row?.open))
		&& Number.isFinite(Number(row?.high))
		&& Number.isFinite(Number(row?.low))
		&& Number.isFinite(Number(row?.close))
	);
	const renderCandles = styleCandlesForRender(safeCandles);
	const safeVolumes = sanitizeVolumeRows(volumeRows || []);

	if (!renderCandles.length) {
		candlesSeries.setData([]);
		volumeSeries.setData([]);
		latestCandleSnapshot = [];
		latestHudCandle = null;
		updateTvHud(null, selectedSymbol(), timeframe);
		lastRenderKey = renderKey;
		lastRenderedTime = 0;
		return;
	}

	let appliedIncremental = false;
	if (lastRenderKey === renderKey && Array.isArray(latestCandleSnapshot) && latestCandleSnapshot.length > 0) {
		const oldLastTime = Number(latestCandleSnapshot[latestCandleSnapshot.length - 1]?.time || 0);
		const newLastTime = Number(renderCandles[renderCandles.length - 1]?.time || 0);
		if (oldLastTime > 0 && newLastTime >= oldLastTime) {
			const newByTime = new Map(renderCandles.map(row => [Number(row.time), row]));
			const volumeByTime = new Map(safeVolumes.map(row => [Number(row.time), row]));
			try {
				const replacement = newByTime.get(oldLastTime);
				if (replacement) {
					candlesSeries.update(replacement);
					const rv = volumeByTime.get(oldLastTime);
					if (rv) volumeSeries.update(rv);
				}
				for (const row of renderCandles) {
					if (Number(row.time) <= oldLastTime) continue;
					candlesSeries.update(row);
					const vv = volumeByTime.get(Number(row.time));
					if (vv) volumeSeries.update(vv);
				}
				appliedIncremental = true;
			} catch (_) {
				appliedIncremental = false;
			}
		}
	}

	if (!appliedIncremental) {
		try {
			candlesSeries.setData(renderCandles);
			volumeSeries.setData(safeVolumes);
		} catch (_) {
			candlesSeries.setData(renderCandles.slice(-Math.max(40, Math.floor(renderCandles.length / 2))));
			volumeSeries.setData(safeVolumes.slice(-Math.max(40, Math.floor(safeVolumes.length / 2))));
		}
	}

	if (shouldAutoFollow(renderCandles, renderKey, timeframe)) {
		if (lastRenderKey !== renderKey || lastRenderedTime === 0 || renderCandles.length < 2) {
			chart.timeScale().fitContent();
		} else {
			chart.timeScale().scrollToRealTime();
		}
	}
	latestCandleSnapshot = renderCandles.slice(-400);
	latestHudCandle = latestCandleSnapshot[latestCandleSnapshot.length - 1] || null;
	updateTvHud(latestHudCandle, selectedSymbol(), timeframe);
	renderDrawings();
	lastRenderKey = renderKey;
	chartInteractionState.lastRenderKey = renderKey;
	lastRenderedTime = renderCandles[renderCandles.length - 1]?.time || lastRenderedTime;
}

function applyOverlayVisibility() {
	const on = id => document.getElementById(id)?.checked !== false;
	const atrEnabled = on("toggleATR");
	const cvdEnabled = on("toggleCVD");
	vwapSeries.applyOptions({ visible: on("toggleVWAP") });
	atrUpperSeries.applyOptions({ visible: atrEnabled });
	atrLowerSeries.applyOptions({ visible: atrEnabled });
	cumDeltaSeries?.applyOptions({ visible: cvdEnabled });
	try {
		chart?.applyOptions({
			leftPriceScale: { visible: (atrEnabled || cvdEnabled), borderColor: "#2b3e5b" },
			rightPriceScale: {
				borderColor: "#2b3e5b",
				autoScale: true,
				scaleMargins: { top: 0.08, bottom: 0.24 },
			},
		});
	} catch (_) {}

	const show = (lines, enabled) => {
		for (const line of lines) {
			try { line.applyOptions({ lineVisible: enabled, axisLabelVisible: enabled }); } catch (_) {}
		}
	};
	show(liquidityLines, on("toggleLiquidity"));
	show(orderBlockLines, on("toggleOrderBlocks"));
	show(fvgLines, on("toggleFVG"));
	show(icebergLines, on("toggleIceberg"));
	show(gannLines, on("toggleGann"));
	show(vpLines, on("toggleVP"));
	if (on("toggleVP")) {
		if (!latestVpProfile && Array.isArray(latestCandleSnapshot) && latestCandleSnapshot.length) {
			renderVolumeProfile(latestCandleSnapshot);
		} else {
			updateVpLegend(latestVpProfile, true);
			refreshVpOverlay();
		}
	} else {
		updateVpLegend(null, false);
		clearVpOverlay();
	}

	if (cachedPayload) {
		const markers = buildMarkers(cachedPayload);
		setSeriesMarkersCompat(candlesSeries, markers);
	}
}

async function loadInstitutionalChart() {
	if (chartRequestInFlight) {
		chartRefreshQueued = true;
		chartRequestSerial += 1;
		return;
	}
	chartRequestInFlight = true;

	try {
	createChartIfNeeded();
	if (!chart) return;
	if (!cachedPayload) {
		setChartStateMessage("loading", "⏳ Loading chart data...");
	}

	const symbol = selectedSymbol();
	const timeframe = selectedTimeframe();
	const requestSerial = ++chartRequestSerial;
	loadDrawings(symbol, timeframe);
	const renderKey = `${symbol}|${timeframe}`;
	updateChartWatermark(symbol, timeframe);
	const payload = await fetchJson(`/chart/data?symbol=${encodeURIComponent(symbol)}&timeframe=${encodeURIComponent(timeframe)}&limit=220`, 26000);
	if (requestSerial < chartRequestSerial) {
		return;
	}
	if (selectedSymbol() !== symbol || selectedTimeframe() !== timeframe) {
		return;
	}
	chartAppliedSerial = requestSerial;
	cachedPayload = payload;

	const candles = toSeries(payload?.candles || [], timeframe);
	const lastClose = candles.length ? Number(candles[candles.length - 1].close) : NaN;
	const liveQuotePrice = Number(payload?.meta?.live_quote?.price);
	const degraded = Boolean(payload?.meta?.degraded_data);
	if (!degraded && isReasonableLivePrice(liveQuotePrice, lastClose)) {
		latestLivePrice = liveQuotePrice;
		latestLiveUpdatedAt = Date.now();
	} else if (!isReasonableLivePrice(Number(latestLivePrice), lastClose)) {
		latestLivePrice = Number.isFinite(lastClose) ? lastClose : null;
	}
	const volumeRows = sanitizeVolumeRows((candles || []).map(row => ({
		time: Number(row.time),
		value: Math.max(0, Number(row.volume || 0)),
		color: volumeColorForCandle(row),
	})));

	if (candles.length === 0) {
		candlesSeries.setData([]);
		volumeSeries.setData([]);
		vwapSeries.setData([]);
		atrUpperSeries.setData([]);
		atrLowerSeries.setData([]);
		cumDeltaSeries.setData([]);
		clearPriceLines(liquidityLines);
		clearPriceLines(orderBlockLines);
		clearPriceLines(fvgLines);
		clearPriceLines(icebergLines);
		clearPriceLines(gannLines);
		clearPriceLines(vpLines);
		clearPriceLines(tradeLines);
		latestVpProfile = null;
		clearVpOverlay();
		setSeriesMarkersCompat(candlesSeries, []);
		updateVpLegend(null, false);
		updateChartMeta(payload, timeframe, candles);
		renderMicrostructureTables(payload, candles);
		lastRenderKey = renderKey;
		lastRenderedTime = 0;
		return;
	}

	updateCandlesSmoothly(candles, volumeRows, renderKey, timeframe);
	vwapSeries.setData(sanitizeLineRows(payload?.overlays?.vwap || []));
	atrUpperSeries.setData(sanitizeLineRows(payload?.overlays?.atr_band?.upper || []));
	atrLowerSeries.setData(sanitizeLineRows(payload?.overlays?.atr_band?.lower || []));
	cumDeltaSeries.setData(sanitizeLineRows(payload?.overlays?.cumulative_delta || []));

	renderOverlayPriceLines(payload?.overlays || {});
	renderVolumeProfile(candles);
	renderTradeLines(payload?.meta || {}, candles);
	setSeriesMarkersCompat(candlesSeries, buildMarkers(payload));
	updateChartMeta(payload, timeframe, candles);
	renderMicrostructureTables(payload, candles);
	applyOverlayVisibility();
	setChartStateMessage("", "");
	paintLiveCandleFromQuote(timeframe);
	} catch (err) {
		const timeoutLike = err && (err.name === "AbortError" || /timeout/i.test(String(err.message || err)));
		const text = timeoutLike
			? "⚠ Chart load timed out. Retrying automatically..."
			: `⚠ Chart load failed${err?.message ? `: ${err.message}` : ""}`;
		setChartStateMessage("error", text);
		if (timeoutLike) {
			if (chartRetryTimer) clearTimeout(chartRetryTimer);
			chartRetryTimer = setTimeout(() => {
				chartRetryTimer = null;
				loadInstitutionalChart().catch(() => {});
			}, 1500);
		}
	} finally {
		chartRequestInFlight = false;
		if (chartRefreshQueued) {
			chartRefreshQueued = false;
			setTimeout(() => loadInstitutionalChart().catch(() => {}), 0);
		}
	}
}

function bindChartControls() {
	restoreChartSettings();

	const reload = document.getElementById("reloadChart");
	if (reload) reload.addEventListener("click", () => loadInstitutionalChart().catch(() => {}));
	const zoomIn = document.getElementById("chartZoomIn");
	if (zoomIn) zoomIn.addEventListener("click", () => zoomChart(+1.8));
	const zoomOut = document.getElementById("chartZoomOut");
	if (zoomOut) zoomOut.addEventListener("click", () => zoomChart(-1.8));
	const fit = document.getElementById("chartFit");
	if (fit) fit.addEventListener("click", () => fitChartView());
	const realtime = document.getElementById("chartRealtime");
	if (realtime) realtime.addEventListener("click", () => scrollChartToRealtime());
	const toolCursor = document.getElementById("chartToolCrosshair");
	if (toolCursor) toolCursor.addEventListener("click", () => setDrawingMode("cursor"));
	const toolHLine = document.getElementById("chartToolHLine");
	if (toolHLine) toolHLine.addEventListener("click", () => setDrawingMode("hline"));
	const toolTrend = document.getElementById("chartToolTrend");
	if (toolTrend) toolTrend.addEventListener("click", () => setDrawingMode("trend"));
	const toolMove = document.getElementById("chartToolMove");
	if (toolMove) toolMove.addEventListener("click", () => setDrawingMode("move"));
	const drawDelete = document.getElementById("chartDrawDelete");
	if (drawDelete) drawDelete.addEventListener("click", () => deleteSelectedDrawing());
	const drawUndo = document.getElementById("chartDrawUndo");
	if (drawUndo) drawUndo.addEventListener("click", () => undoDrawingChange());
	const drawRedo = document.getElementById("chartDrawRedo");
	if (drawRedo) drawRedo.addEventListener("click", () => redoDrawingChange());
	const toolClear = document.getElementById("chartToolClear");
	if (toolClear) {
		toolClear.addEventListener("click", () => {
			if (drawingObjects.length) pushDrawingUndoSnapshot();
			drawingObjects = [];
			drawingPendingPoint = null;
			selectedDrawingId = null;
			saveDrawings(selectedSymbol(), selectedTimeframe());
			clearDrawingSeries();
			setChartStateMessage("", "");
		});
	}
	const reset = document.getElementById("resetChartSettings");
	if (reset) reset.addEventListener("click", () => resetChartSettings());
	const symbolSelect = document.getElementById("chartSymbol");
	if (symbolSelect) symbolSelect.addEventListener("change", () => {
		writeChartSettings({ symbol: symbolSelect.value });
		latestCandleSnapshot = [];
		latestLivePrice = null;
		latestLiveUpdatedAt = 0;
		lastRenderKey = "";
		lastRenderedTime = 0;
		lastPaintedLivePrice = null;
		loadInstitutionalChart().catch(() => {});
	});
	const timeframeSelect = document.getElementById("chartTimeframe");
	if (timeframeSelect) timeframeSelect.addEventListener("change", () => {
		writeChartSettings({ timeframe: timeframeSelect.value });
		latestCandleSnapshot = [];
		latestLivePrice = null;
		latestLiveUpdatedAt = 0;
		lastRenderKey = "";
		lastRenderedTime = 0;
		lastPaintedLivePrice = null;
		loadInstitutionalChart().catch(() => {});
	});

	for (const id of toggleIds) {
		const el = document.getElementById(id);
		if (el) el.addEventListener("change", () => {
			captureToggleSettings();
			applyOverlayVisibility();
		});
	}

	if (symbolSelect) writeChartSettings({ symbol: symbolSelect.value });
	if (timeframeSelect) writeChartSettings({ timeframe: timeframeSelect.value });
	captureToggleSettings();
	bindChartHotkeys();
	setDrawingMode("cursor");
}

bindChartControls();
loadInstitutionalChart().catch(() => {});
setInterval(() => loadInstitutionalChart().catch(() => {}), CHART_AUTO_REFRESH_MS);
setInterval(() => {
	const ageMs = Date.now() - Number(latestLiveUpdatedAt || 0);
	if (ageMs > 20000) return;
	paintLiveCandleFromQuote(selectedTimeframe());
}, LIVE_PAINT_INTERVAL_MS);
