const AQ_DEFAULT_API_ORIGIN = ["8000", "8001"].includes(String(window.location.port || ""))
	? window.location.origin
	: "http://127.0.0.1:8001";
const AQ_API_BASE_API = String(window.AQ_API_BASE || AQ_DEFAULT_API_ORIGIN)
	.replace(/:8000(?=\/|$)/, ":8001");
const apiFetch = async (path, options) => {
	const target = `${AQ_API_BASE_API}${path}`;
	try {
		return await fetch(target, options);
	} catch (error) {
		console.warn("apiFetch failed", target, error);
		return new Response(
			JSON.stringify({ status: "error", message: String(error || "fetch failed") }),
			{ status: 599, headers: { "Content-Type": "application/json" } },
		);
	}
};
const AQ_ADMIN_TOKEN = window.AQ_ADMIN_TOKEN || localStorage.getItem("AQ_ADMIN_TOKEN") || "dev-admin-token";
const AQ_ADMIN_ROLE = window.AQ_ADMIN_ROLE || localStorage.getItem("AQ_ADMIN_ROLE") || "ADMIN";
const AQ_MICRO_PANEL_STATE_PREFIX = "AQ_MICRO_PANEL_OPEN_";
const AQ_MICRO_PANEL_POS_PREFIX = "AQ_MICRO_PANEL_POS_";
const AQ_OPS_PANEL_STATE_KEY = "AQ_OPS_PANEL_OPEN_V1";
const AQ_OPS_PANEL_POS_KEY = "AQ_OPS_PANEL_POS_V1";
const AQ_JOURNAL_PANEL_STATE_KEY = "AQ_JOURNAL_PANEL_OPEN_V1";
const AQ_JOURNAL_PANEL_POS_KEY = "AQ_JOURNAL_PANEL_POS_V1";
const AQ_GOV_PANEL_STATE_KEY = "AQ_GOV_PANEL_OPEN_V1";
const AQ_GOV_PANEL_LAYOUT_KEY = "AQ_GOV_PANEL_LAYOUT_V1";
const AQ_HEALTH_PANEL_STATE_KEY = "AQ_HEALTH_PANEL_OPEN_V1";
const AQ_HEALTH_PANEL_LAYOUT_KEY = "AQ_HEALTH_PANEL_LAYOUT_V1";

const MICRO_PANEL_CONFIG = {
	iceberg: { panelId: "microIcebergPanel", buttonId: "microIcebergToggleBtn", dragHandleId: "microIcebergDragHandle", label: "Iceberg" },
	orderflow: { panelId: "microOrderflowPanel", buttonId: "microOrderflowToggleBtn", dragHandleId: "microOrderflowDragHandle", label: "Order Flow" },
	timesales: { panelId: "microTimeSalesPanel", buttonId: "microTimeSalesToggleBtn", dragHandleId: "microTimeSalesDragHandle", label: "Time & Sales" },
	ladder: { panelId: "microLadderPanel", buttonId: "microLadderToggleBtn", dragHandleId: "microLadderDragHandle", label: "Ladder" },
};

function toggleMicroPanel(kind, forceOpen) {
	const cfg = MICRO_PANEL_CONFIG[kind];
	if (!cfg) return;
	const panel = document.getElementById(cfg.panelId);
	const btn = document.getElementById(cfg.buttonId);
	if (!panel) return;
	const shouldOpen = typeof forceOpen === "boolean"
		? forceOpen
		: !panel.classList.contains("open");
	panel.classList.toggle("open", shouldOpen);
	if (btn) btn.innerText = shouldOpen ? `Hide ${cfg.label}` : `Open ${cfg.label}`;
	try {
		localStorage.setItem(`${AQ_MICRO_PANEL_STATE_PREFIX}${kind.toUpperCase()}`, shouldOpen ? "1" : "0");
	} catch (_) {
		// ignore storage issues
	}
	return shouldOpen;
}


function restoreMicroPanelStates() {
	for (const kind of Object.keys(MICRO_PANEL_CONFIG)) {
		let open = false;
		try {
			const saved = localStorage.getItem(`${AQ_MICRO_PANEL_STATE_PREFIX}${kind.toUpperCase()}`);
			if (saved === "1") open = true;
		} catch (_) {
			open = false;
		}
		toggleMicroPanel(kind, open);
	}
}

function initMicroPanelDrags() {
	for (const [kind, cfg] of Object.entries(MICRO_PANEL_CONFIG)) {
		const panel = document.getElementById(cfg.panelId);
		const handle = document.getElementById(cfg.dragHandleId);
		if (!panel || !handle) continue;

		try {
			const saved = JSON.parse(localStorage.getItem(`${AQ_MICRO_PANEL_POS_PREFIX}${kind.toUpperCase()}`) || "{}");
			const left = Number(saved?.left);
			const top = Number(saved?.top);
			if (Number.isFinite(left) && Number.isFinite(top)) {
				panel.style.left = `${Math.max(0, left)}px`;
				panel.style.top = `${Math.max(0, top)}px`;
				panel.style.right = "auto";
			}
		} catch (_) {
			// ignore position restore issues
		}

		let dragging = false;
		let offsetX = 0;
		let offsetY = 0;

		handle.addEventListener("mousedown", (ev) => {
			if (ev.button !== 0) return;
			if (ev.target && ev.target.closest("button")) return;
			const rect = panel.getBoundingClientRect();
			dragging = true;
			offsetX = ev.clientX - rect.left;
			offsetY = ev.clientY - rect.top;
			panel.style.right = "auto";
			document.body.style.userSelect = "none";
		});

		const moveHandler = (ev) => {
			if (!dragging) return;
			const panelRect = panel.getBoundingClientRect();
			const maxLeft = Math.max(0, window.innerWidth - panelRect.width);
			const maxTop = Math.max(0, window.innerHeight - panelRect.height);
			const left = Math.max(0, Math.min(maxLeft, ev.clientX - offsetX));
			const top = Math.max(0, Math.min(maxTop, ev.clientY - offsetY));
			panel.style.left = `${left}px`;
			panel.style.top = `${top}px`;
		};

		const upHandler = () => {
			if (!dragging) return;
			dragging = false;
			document.body.style.userSelect = "";
			const rect = panel.getBoundingClientRect();
			try {
				localStorage.setItem(
					`${AQ_MICRO_PANEL_POS_PREFIX}${kind.toUpperCase()}`,
					JSON.stringify({ left: rect.left, top: rect.top }),
				);
			} catch (_) {
				// ignore storage issues
			}
		};

		window.addEventListener("mousemove", moveHandler);
		window.addEventListener("mouseup", upHandler);
	}
}

function toggleJournalPanel(forceOpen) {
	const panel = document.getElementById("journalPanel");
	const btn = document.getElementById("journalToggleBtn");
	if (!panel) return;
	const shouldOpen = typeof forceOpen === "boolean"
		? forceOpen
		: !panel.classList.contains("open");
	panel.classList.toggle("open", shouldOpen);
	if (btn) btn.innerText = shouldOpen ? "Hide Journal" : "Open Journal";
	try {
		localStorage.setItem(AQ_JOURNAL_PANEL_STATE_KEY, shouldOpen ? "1" : "0");
	} catch (_) {
		// ignore storage errors
	}
	if (shouldOpen) {
		loadJournal().catch(() => {});
	}
	return shouldOpen;
}

function restoreJournalPanelState() {
	let open = true;
	try {
		const saved = localStorage.getItem(AQ_JOURNAL_PANEL_STATE_KEY);
		if (saved === "0") open = false;
	} catch (_) {
		open = true;
	}
	toggleJournalPanel(open);
}

function initJournalPanelDrag() {
	const panel = document.getElementById("journalPanel");
	const handle = document.getElementById("journalDragHandle");
	if (!panel || !handle) return;

	try {
		const saved = JSON.parse(localStorage.getItem(AQ_JOURNAL_PANEL_POS_KEY) || "{}");
		const left = Number(saved?.left);
		const top = Number(saved?.top);
		if (Number.isFinite(left) && Number.isFinite(top)) {
			panel.style.left = `${Math.max(0, left)}px`;
			panel.style.top = `${Math.max(0, top)}px`;
			panel.style.bottom = "auto";
		}
	} catch (_) {
		// ignore restore issues
	}

	let dragging = false;
	let offsetX = 0;
	let offsetY = 0;

	handle.addEventListener("mousedown", (ev) => {
		if (ev.button !== 0) return;
		if (ev.target && ev.target.closest("button")) return;
		const rect = panel.getBoundingClientRect();
		dragging = true;
		offsetX = ev.clientX - rect.left;
		offsetY = ev.clientY - rect.top;
		panel.style.bottom = "auto";
		document.body.style.userSelect = "none";
	});

	window.addEventListener("mousemove", (ev) => {
		if (!dragging) return;
		const panelRect = panel.getBoundingClientRect();
		const maxLeft = Math.max(0, window.innerWidth - panelRect.width);
		const maxTop = Math.max(0, window.innerHeight - panelRect.height);
		const left = Math.max(0, Math.min(maxLeft, ev.clientX - offsetX));
		const top = Math.max(0, Math.min(maxTop, ev.clientY - offsetY));
		panel.style.left = `${left}px`;
		panel.style.top = `${top}px`;
	});

	window.addEventListener("mouseup", () => {
		if (!dragging) return;
		dragging = false;
		document.body.style.userSelect = "";
		const rect = panel.getBoundingClientRect();
		try {
			localStorage.setItem(AQ_JOURNAL_PANEL_POS_KEY, JSON.stringify({ left: rect.left, top: rect.top }));
		} catch (_) {
			// ignore storage issues
		}
	});
}

function _toggleFloatingPanel(panelId, buttonId, storageKey, label, forceOpen) {
	const panel = document.getElementById(panelId);
	const btn = document.getElementById(buttonId);
	if (!panel) return;
	const shouldOpen = typeof forceOpen === "boolean"
		? forceOpen
		: !panel.classList.contains("open");
	panel.classList.toggle("open", shouldOpen);
	if (btn) btn.innerText = shouldOpen ? `Hide ${label}` : `Open ${label}`;
	try {
		localStorage.setItem(storageKey, shouldOpen ? "1" : "0");
	} catch (_) {
		// ignore storage errors
	}
	return shouldOpen;
}

function toggleGovernancePanel(forceOpen) {
	const opened = _toggleFloatingPanel("governancePanel", "governanceToggleBtn", AQ_GOV_PANEL_STATE_KEY, "Governance", forceOpen);
	if (opened) {
		loadStatus().catch(() => {});
		updateVolatility().catch(() => {});
		updatePropStatus().catch(() => {});
		updateEquityBar().catch(() => {});
		updateDrawdownBar().catch(() => {});
		updateModelStats().catch(() => {});
		updateNewsSeverity().catch(() => {});
		syncPropEngineControls().catch(() => {});
	}
	return opened;
}

function toggleSystemHealthPanel(forceOpen) {
	const opened = _toggleFloatingPanel("systemHealthPanel", "systemHealthToggleBtn", AQ_HEALTH_PANEL_STATE_KEY, "System Health", forceOpen);
	if (opened) {
		updateSystemHealth().catch(() => {});
	}
	return opened;
}

function _restorePanelState(storageKey, toggler) {
	let open = true;
	try {
		const saved = localStorage.getItem(storageKey);
		if (saved === "0") open = false;
	} catch (_) {
		open = true;
	}
	toggler(open);
}

function restoreGovernancePanelState() {
	_restorePanelState(AQ_GOV_PANEL_STATE_KEY, toggleGovernancePanel);
}

function restoreSystemHealthPanelState() {
	_restorePanelState(AQ_HEALTH_PANEL_STATE_KEY, toggleSystemHealthPanel);
}

function _initFloatingPanelDragResize(panelId, handleId, layoutKey, fallback) {
	const panel = document.getElementById(panelId);
	const handle = document.getElementById(handleId);
	if (!panel || !handle) return;

	try {
		const saved = JSON.parse(localStorage.getItem(layoutKey) || "{}");
		const left = Number(saved?.left);
		const top = Number(saved?.top);
		const width = Number(saved?.width);
		const height = Number(saved?.height);
		if (Number.isFinite(left) && Number.isFinite(top)) {
			panel.style.left = `${Math.max(0, left)}px`;
			panel.style.top = `${Math.max(0, top)}px`;
			panel.style.right = "auto";
		}
		if (Number.isFinite(width) && width >= 320) panel.style.width = `${width}px`;
		if (Number.isFinite(height) && height >= 220) panel.style.height = `${height}px`;
	} catch (_) {
		if (fallback?.left) panel.style.left = fallback.left;
		if (fallback?.top) panel.style.top = fallback.top;
		if (fallback?.width) panel.style.width = fallback.width;
	}

	let dragging = false;
	let offsetX = 0;
	let offsetY = 0;

	handle.addEventListener("mousedown", (ev) => {
		if (ev.button !== 0) return;
		if (ev.target && ev.target.closest("button")) return;
		const rect = panel.getBoundingClientRect();
		dragging = true;
		offsetX = ev.clientX - rect.left;
		offsetY = ev.clientY - rect.top;
		panel.style.right = "auto";
		document.body.style.userSelect = "none";
	});

	const saveLayout = () => {
		const rect = panel.getBoundingClientRect();
		try {
			localStorage.setItem(layoutKey, JSON.stringify({
				left: rect.left,
				top: rect.top,
				width: rect.width,
				height: rect.height,
			}));
		} catch (_) {
			// ignore storage issues
		}
	};

	window.addEventListener("mousemove", (ev) => {
		if (!dragging) return;
		const rect = panel.getBoundingClientRect();
		const maxLeft = Math.max(0, window.innerWidth - rect.width);
		const maxTop = Math.max(0, window.innerHeight - rect.height);
		const left = Math.max(0, Math.min(maxLeft, ev.clientX - offsetX));
		const top = Math.max(0, Math.min(maxTop, ev.clientY - offsetY));
		panel.style.left = `${left}px`;
		panel.style.top = `${top}px`;
	});

	window.addEventListener("mouseup", () => {
		if (!dragging) return;
		dragging = false;
		document.body.style.userSelect = "";
		saveLayout();
	});

	panel.addEventListener("mouseup", saveLayout);
}

function initGovernancePanelInteractions() {
	_initFloatingPanelDragResize("governancePanel", "governanceDragHandle", AQ_GOV_PANEL_LAYOUT_KEY, {
		left: "14px",
		top: "86px",
		width: "470px",
	});
}

function initSystemHealthPanelInteractions() {
	_initFloatingPanelDragResize("systemHealthPanel", "systemHealthDragHandle", AQ_HEALTH_PANEL_LAYOUT_KEY, {
		left: "500px",
		top: "86px",
		width: "470px",
	});
}

function resetFloatingPanelLayout() {
	try {
		localStorage.removeItem(AQ_GOV_PANEL_STATE_KEY);
		localStorage.removeItem(AQ_GOV_PANEL_LAYOUT_KEY);
		localStorage.removeItem(AQ_HEALTH_PANEL_STATE_KEY);
		localStorage.removeItem(AQ_HEALTH_PANEL_LAYOUT_KEY);
		localStorage.removeItem(AQ_OPS_PANEL_POS_KEY);
		localStorage.removeItem(AQ_OPS_PANEL_STATE_KEY);
		localStorage.removeItem(AQ_JOURNAL_PANEL_POS_KEY);
		localStorage.removeItem(AQ_JOURNAL_PANEL_STATE_KEY);
		for (const kind of Object.keys(MICRO_PANEL_CONFIG)) {
			localStorage.removeItem(`${AQ_MICRO_PANEL_POS_PREFIX}${kind.toUpperCase()}`);
			localStorage.removeItem(`${AQ_MICRO_PANEL_STATE_PREFIX}${kind.toUpperCase()}`);
		}
	} catch (_) {
		// ignore storage issues
	}

	const opsPanel = document.getElementById("operationsConsolePanel");
	if (opsPanel) {
		opsPanel.style.left = "";
		opsPanel.style.top = "";
		opsPanel.style.right = "14px";
	}

	const journalPanel = document.getElementById("journalPanel");
	if (journalPanel) {
		journalPanel.style.left = "14px";
		journalPanel.style.bottom = "14px";
		journalPanel.style.top = "";
		journalPanel.style.right = "";
	}

	const governancePanel = document.getElementById("governancePanel");
	if (governancePanel) {
		governancePanel.style.left = "14px";
		governancePanel.style.top = "86px";
		governancePanel.style.right = "auto";
		governancePanel.style.width = "min(470px, calc(100vw - 28px))";
		governancePanel.style.height = "";
	}

	const healthPanel = document.getElementById("systemHealthPanel");
	if (healthPanel) {
		healthPanel.style.left = "500px";
		healthPanel.style.top = "86px";
		healthPanel.style.right = "auto";
		healthPanel.style.width = "min(470px, calc(100vw - 28px))";
		healthPanel.style.height = "";
	}

	const defaults = {
		iceberg: { right: "14px", top: "86px" },
		orderflow: { right: "14px", top: "calc(86px + 38vh)" },
		timesales: { right: "460px", top: "86px" },
		ladder: { right: "460px", top: "calc(86px + 38vh)" },
	};

	for (const [kind, cfg] of Object.entries(MICRO_PANEL_CONFIG)) {
		const panel = document.getElementById(cfg.panelId);
		if (!panel) continue;
		panel.style.left = "";
		panel.style.top = defaults[kind]?.top || "";
		panel.style.right = defaults[kind]?.right || "";
		toggleMicroPanel(kind, true);
	}

	toggleOperationsConsole(true);
	toggleJournalPanel(true);
	toggleGovernancePanel(true);
	toggleSystemHealthPanel(true);
}

window.toggleMicroPanel = toggleMicroPanel;
window.resetFloatingPanelLayout = resetFloatingPanelLayout;
window.toggleJournalPanel = toggleJournalPanel;
window.toggleGovernancePanel = toggleGovernancePanel;
window.toggleSystemHealthPanel = toggleSystemHealthPanel;

function toggleOperationsConsole(forceOpen) {
	const panel = document.getElementById("operationsConsolePanel");
	const btn = document.getElementById("opsConsoleToggleBtn");
	if (!panel) return;
	const shouldOpen = typeof forceOpen === "boolean"
		? forceOpen
		: !panel.classList.contains("open");
	panel.classList.toggle("open", shouldOpen);
	if (btn) btn.innerText = shouldOpen ? "Hide Operations" : "Open Operations";
	try {
		localStorage.setItem(AQ_OPS_PANEL_STATE_KEY, shouldOpen ? "1" : "0");
	} catch (_) {
		// ignore storage errors
	}
	if (shouldOpen) {
		updateBasisOps().catch(() => {});
		updateOpsStatus().catch(() => {});
		updateMultiSymbolDashboard().catch(() => {});
		runFeedProbe().catch(() => {});
	}
	return shouldOpen;
}

function restoreOperationsConsoleState() {
	let open = true;
	try {
		const saved = localStorage.getItem(AQ_OPS_PANEL_STATE_KEY);
		if (saved === "0") open = false;
	} catch (_) {
		open = true;
	}
	toggleOperationsConsole(open);
}

function initOperationsConsoleDrag() {
	const panel = document.getElementById("operationsConsolePanel");
	const handle = document.getElementById("opsConsoleDragHandle");
	if (!panel || !handle) return;

	try {
		const saved = JSON.parse(localStorage.getItem(AQ_OPS_PANEL_POS_KEY) || "{}");
		const left = Number(saved?.left);
		const top = Number(saved?.top);
		if (Number.isFinite(left) && Number.isFinite(top)) {
			panel.style.left = `${Math.max(0, left)}px`;
			panel.style.top = `${Math.max(0, top)}px`;
			panel.style.right = "auto";
		}
	} catch (_) {
		// ignore position restore issues
	}

	let dragging = false;
	let offsetX = 0;
	let offsetY = 0;

	handle.addEventListener("mousedown", (ev) => {
		if (ev.button !== 0) return;
		if (ev.target && ev.target.closest("button")) return;
		const rect = panel.getBoundingClientRect();
		dragging = true;
		offsetX = ev.clientX - rect.left;
		offsetY = ev.clientY - rect.top;
		panel.style.right = "auto";
		document.body.style.userSelect = "none";
	});

	window.addEventListener("mousemove", (ev) => {
		if (!dragging) return;
		const panelRect = panel.getBoundingClientRect();
		const maxLeft = Math.max(0, window.innerWidth - panelRect.width);
		const maxTop = Math.max(0, window.innerHeight - panelRect.height);
		const left = Math.max(0, Math.min(maxLeft, ev.clientX - offsetX));
		const top = Math.max(0, Math.min(maxTop, ev.clientY - offsetY));
		panel.style.left = `${left}px`;
		panel.style.top = `${top}px`;
	});

	window.addEventListener("mouseup", () => {
		if (!dragging) return;
		dragging = false;
		document.body.style.userSelect = "";
		const rect = panel.getBoundingClientRect();
		try {
			localStorage.setItem(AQ_OPS_PANEL_POS_KEY, JSON.stringify({ left: rect.left, top: rect.top }));
		} catch (_) {
			// ignore storage errors
		}
	});
}

window.toggleOperationsConsole = toggleOperationsConsole;

function adminHeaders(extra = {}) {
	return {
		"Content-Type": "application/json",
		"x-admin-token": AQ_ADMIN_TOKEN,
		"x-admin-role": AQ_ADMIN_ROLE,
		...extra,
	};
}

async function loadStatus() {

	const res = await apiFetch("/status");
	const data = await res.json();

	document.getElementById("balance").innerText = data.balance;
	document.getElementById("phase").innerText = data.phase;
	const dailyLoss = document.getElementById("dailyLoss");
	if (dailyLoss) dailyLoss.innerText = Number(data.daily_loss || 0).toFixed(2);

	const newsStatus = document.getElementById("news-status");
	if (newsStatus) {
		if (data.news_halt) {
			newsStatus.innerText = "HIGH IMPACT NEWS — TRADING HALTED";
		} else {
			newsStatus.innerText = "News: Normal";
		}
	}

	renderNews(data.next_news || []);
}

async function updatePropStatus() {
	const res = await apiFetch("/prop_status");
	if (!res.ok) return;
	const data = await res.json();

	const phaseDisplay = document.getElementById("phaseDisplay");
	const floorDisplay = document.getElementById("floorDisplay");
	const profitDays = document.getElementById("profitDays");
	const tradeStatus = document.getElementById("tradeStatus");
	const phaseCompletion = document.getElementById("phaseCompletion");

	if (phaseDisplay) phaseDisplay.innerText = data.phase;
	if (floorDisplay) floorDisplay.innerText = data.static_floor;
	if (profitDays) profitDays.innerText = data.profitable_days;
	if (tradeStatus) tradeStatus.innerText = data.trading_enabled ? "ACTIVE" : "DISABLED";
	if (phaseCompletion) phaseCompletion.innerText = data.phase_completion_status || "IN_PROGRESS";
	setText("accountModeDisplay", data.profile_mode || "STANDARD");
	setText("dailyMaxLossDisplay", fmtMoney(data.daily_max_loss));
	setText("totalMaxLossDisplay", fmtMoney(data.total_max_loss));
	setText("phase1TargetDisplay", fmtMoney(data.phase1_target));
	setText("phase2TargetDisplay", fmtMoney(data.phase2_target));
	setText("riskPerTradeDisplay", data.risk_per_trade_pct != null ? `${Number(data.risk_per_trade_pct).toFixed(2)}%` : "--");
	setText("activeAccountsDisplay", Array.isArray(data.active_accounts) && data.active_accounts.length ? data.active_accounts.join(", ") : "--");
}

async function updateEquityBar() {
	const res = await apiFetch("/equity");
	if (!res.ok) return;
	const data = await res.json();

	const base = Number(data.base || 50000);
	const target = Number(data.target || base);
	const equity = Number(data.equity || base);
	const primaryAccount = String(data.primary_account || "").toUpperCase();
	setText("accountSizeDisplay", primaryAccount || (base > 0 ? `${Math.round(base / 1000)}K` : "--"));

	const denominator = Math.max(1, target - base);
	let progress = ((equity - base) / denominator) * 100;
	progress = Math.max(0, Math.min(100, progress));

	const bar = document.getElementById("equityBar");
	if (bar) bar.style.width = progress + "%";

	const label = document.getElementById("equityLabel");
	if (label) label.innerText = `Equity ${equity.toFixed(2)} / Target ${target.toFixed(2)} (${progress.toFixed(1)}%)`;
}

async function updateDrawdownBar() {
	const [equityRes, propRes] = await Promise.all([
		apiFetch("/equity"),
		apiFetch("/prop_status"),
	]);
	if (!equityRes.ok || !propRes.ok) return;

	const equityData = await equityRes.json();
	const propData = await propRes.json();

	const equity = Number(equityData.equity || 0);
	const floor = Number(propData.static_floor || 0);
	const base = Number(equityData.base || 50000);

	const riskRange = Math.max(1, base - floor);
	const drawdownUsed = Math.max(0, base - equity);
	let pct = (drawdownUsed / riskRange) * 100;
	pct = Math.max(0, Math.min(100, pct));

	const bar = document.getElementById("drawdownBar");
	if (bar) {
		bar.style.width = pct + "%";
		bar.className = "bar drawdown" + (equity <= floor ? " red" : "");
	}

	const label = document.getElementById("drawdownLabel");
	if (label) label.innerText = `Drawdown used: ${drawdownUsed.toFixed(2)} / ${(base - floor).toFixed(2)} (${pct.toFixed(1)}%)`;
}

async function updateModelStats() {
	const symbol = selectedChartSymbol();
	const res = await apiFetch(`/model_stats?symbol=${encodeURIComponent(symbol)}`);
	if (!res.ok) return;
	const data = await res.json();

	const body = document.getElementById("modelStatsBody");
	if (!body) return;
	body.innerHTML = "";

	const entries = Object.entries(data || {});
	if (!entries.length) {
		const tr = document.createElement("tr");
		tr.innerHTML = `<td colspan="4">No symbol-specific model data for ${symbol}</td>`;
		body.appendChild(tr);
		return;
	}

	entries.forEach(([model, stats]) => {
		const wins = Number(stats.wins || 0);
		const losses = Number(stats.losses || 0);
		const total = wins + losses;
		const wr = total > 0 ? (wins / total) * 100 : 0;

		const tr = document.createElement("tr");
		tr.innerHTML = `<td>${model}</td><td>${wins}</td><td>${losses}</td><td>${wr.toFixed(1)}%</td>`;
		body.appendChild(tr);
	});
}

async function updateNewsSeverity() {
	const res = await apiFetch("/news_severity");
	if (!res.ok) return;
	const data = await res.json();

	const panel = document.getElementById("newsPanel");
	if (!panel) return;

	const halt = data.halt_active ? "HALT ACTIVE" : "No Halt";
	const upcoming = data.upcoming_title ? `${data.upcoming_title} (${data.upcoming_currency || "--"})` : "No upcoming event";
	const countdown = data.minutes_to_news != null ? `${data.minutes_to_news} min` : "--";

	panel.innerText = `${halt} | Next: ${upcoming} | T-${countdown}`;
}

function healthClass(ok) {
	return ok ? "health-ok" : "health-bad";
}

async function updateSystemHealth() {
	const res = await apiFetch("/system_health");
	if (!res.ok) return;
	const data = await res.json();

	const p = document.getElementById("healthPlaywright");
	const d = document.getElementById("healthDatabento");
	const g = document.getElementById("healthGovernance");
	const e = document.getElementById("healthExecution");
	const r = document.getElementById("healthReconciliation");
	const eq = document.getElementById("healthEquityVerify");
	const cpu = document.getElementById("healthCpuLoad");
	const mem = document.getElementById("healthMemory");
	const disk = document.getElementById("healthDisk");
	const uptime = document.getElementById("healthUptime");
	const issues = document.getElementById("healthIssues");
	const summary = document.getElementById("healthSummary");

	const toTone = (ok) => ok ? "good" : "bad";
	const execOk = String(data.execution_status || "OK").toUpperCase() !== "HALTED";
	const recOk = !Boolean(data.reconciliation_halt);
	const equityOk = !Boolean(data.equity_verification_halt);
	const memPct = Number(data.memory_used_pct);
	const diskPct = Number(data.disk_used_pct);
	const cpuLoad = Number(data.cpu_load_1m);
	const cpuCores = Number(data.cpu_cores || 0);

	if (summary) {
		const state = String(data.health_state || "UNKNOWN").toUpperCase();
		const score = Number(data.health_score);
		const text = Number.isFinite(score) ? `${state} (${score})` : state;
		setOpsValue("healthSummary", text, state === "HEALTHY" ? "good" : state === "DEGRADED" ? "warn" : "bad");
	}

	if (p) {
		setOpsValue("healthPlaywright", data.playwright ? "OK" : "DOWN", toTone(Boolean(data.playwright)));
	}
	if (d) {
		setOpsValue("healthDatabento", data.databento ? "OK" : "DOWN", toTone(Boolean(data.databento)));
	}
	if (g) {
		setOpsValue("healthGovernance", data.governance ? "OK" : "LOCKED", data.governance ? "good" : "warn");
	}
	if (e) {
		setOpsValue("healthExecution", execOk ? "OK" : "HALTED", execOk ? "good" : "bad");
	}
	if (r) {
		setOpsValue("healthReconciliation", recOk ? (data.reconciliation_status || "OK") : "HALTED", recOk ? "good" : "bad");
	}
	if (eq) {
		setOpsValue("healthEquityVerify", equityOk ? (data.equity_verification_status || "OK") : "HALTED", equityOk ? "good" : "bad");
	}
	if (cpu) {
		const text = Number.isFinite(cpuLoad)
			? `${cpuLoad.toFixed(2)}${cpuCores > 0 ? ` / ${cpuCores}c` : ""}`
			: "--";
		const ratio = (Number.isFinite(cpuLoad) && cpuCores > 0) ? (cpuLoad / cpuCores) : null;
		const tone = ratio == null ? "neutral" : ratio > 1.2 ? "bad" : ratio > 0.85 ? "warn" : "good";
		setOpsValue("healthCpuLoad", text, tone);
	}
	if (mem) {
		const text = Number.isFinite(memPct) ? `${memPct.toFixed(1)}%` : "--";
		const tone = Number.isFinite(memPct) ? (memPct >= 90 ? "bad" : memPct >= 80 ? "warn" : "good") : "neutral";
		setOpsValue("healthMemory", text, tone);
	}
	if (disk) {
		const text = Number.isFinite(diskPct) ? `${diskPct.toFixed(1)}%` : "--";
		const tone = Number.isFinite(diskPct) ? (diskPct >= 90 ? "bad" : diskPct >= 80 ? "warn" : "good") : "neutral";
		setOpsValue("healthDisk", text, tone);
	}
	if (uptime) {
		const sec = Number(data.uptime_seconds);
		if (Number.isFinite(sec)) {
			const h = Math.floor(sec / 3600);
			const m = Math.floor((sec % 3600) / 60);
			setOpsValue("healthUptime", `${h}h ${m}m`, "neutral");
		} else {
			setOpsValue("healthUptime", "--", "neutral");
		}
	}
	if (issues) {
		const items = Array.isArray(data.issues) ? data.issues : [];
		if (!items.length) {
			setOpsValue("healthIssues", "None", "good");
		} else {
			setOpsChips("healthIssues", items.join("|"));
		}
	}
}

async function loadJournal() {
	const symbol = selectedChartSymbol();
	const res = await apiFetch(`/journal?symbol=${encodeURIComponent(symbol)}`);
	if (!res.ok) return;
	const data = await res.json();

	const tbody = document.querySelector("#journalTable tbody");
	if (!tbody) return;
	tbody.innerHTML = "";

	if (!Array.isArray(data) || data.length === 0) {
		const tr = document.createElement("tr");
		tr.innerHTML = `<td colspan="7">No symbol-specific journal rows for ${symbol}</td>`;
		tbody.appendChild(tr);
		return;
	}

	data.forEach(row => {
		const tr = document.createElement("tr");
		row.forEach(col => {
			const td = document.createElement("td");
			td.innerText = col;
			tr.appendChild(td);
		});
		tbody.appendChild(tr);
	});
}

async function updateVolatility() {
	try {
		const res = await apiFetch("/volatility_status");
		if (!res.ok) return;
		const data = await res.json();

		const bar = document.getElementById("volatilityBar");
		if (!bar) return;

		const mode = (data.mode || "NORMAL").toUpperCase();
		bar.className = "vol-bar " + mode;
		bar.innerText = "VOL: " + mode;
	} catch (_) {
		// keep last shown state on transient API errors
	}
}

function renderNews(news) {
	const container = document.getElementById("news-list");
	if (!container) return;

	container.innerHTML = "";

	news.forEach(e => {
		const div = document.createElement("div");
		div.innerHTML = `
			<strong>${e.currency}</strong> - ${e.title}
			<br/>
			${new Date(e.time).toLocaleString()}
			<hr/>
		`;
		container.appendChild(div);
	});
}

function selectedChartSymbol() {
	const select = document.getElementById("chartSymbol");
	return select ? select.value : "GC.FUT";
}

function setText(id, value) {
	const el = document.getElementById(id);
	if (el) el.innerText = value;
}

function fmtMoney(value) {
	const n = Number(value);
	if (!Number.isFinite(n)) return "--";
	return n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function fmtPct(value) {
	const n = Number(value);
	if (!Number.isFinite(n)) return "--";
	return `${n.toFixed(2)}%`;
}

function setOpsValue(id, value, tone = "neutral") {
	const el = document.getElementById(id);
	if (!el) return;
	el.innerText = value ?? "--";
	el.classList.remove("ops-good", "ops-warn", "ops-bad", "ops-neutral");
	const cls = tone === "good" ? "ops-good"
		: tone === "warn" ? "ops-warn"
		: tone === "bad" ? "ops-bad"
		: "ops-neutral";
	el.classList.add(cls);
}

function setOpsChips(id, raw, defaultTone = "neutral") {
	const el = document.getElementById(id);
	if (!el) return;
	const text = String(raw ?? "").trim();
	if (!text || text === "--" || text === "NONE") {
		setOpsValue(id, text || "--", defaultTone);
		return;
	}
	const tokens = text
		.split(/\s*\|\s*|\s*,\s*/)
		.map(t => String(t || "").trim())
		.filter(Boolean)
		.slice(0, 8);
	if (!tokens.length) {
		setOpsValue(id, "--", defaultTone);
		return;
	}
	el.classList.remove("ops-good", "ops-warn", "ops-bad", "ops-neutral");
	const classForToken = (token) => {
		const t = token.toUpperCase();
		if (t.includes("HALT") || t.includes("BLOCK") || t.includes("ERROR") || t.includes("FAIL") || t.includes("LOCK")) return "bad";
		if (t.includes("WARN") || t.includes("DEFENSIVE") || t.includes("COOLDOWN") || t.includes("LIMIT")) return "warn";
		if (t.includes("OK") || t.includes("ACTIVE") || t.includes("CALIBRATED") || t.includes("LIVE") || t.includes("ICT") || t.includes("ICEBERG") || t.includes("ASTRO")) return "good";
		return "";
	};
	el.innerHTML = `<span class="ops-chip-wrap">${tokens.map(token => {
		const tone = classForToken(token);
		return `<span class="ops-chip${tone ? ` ${tone}` : ""}">${token}</span>`;
	}).join("")}</span>`;
}

async function updateMultiSymbolDashboard() {
	const res = await apiFetch("/dashboard/multi_symbol");
	if (!res.ok) return;
	const data = await res.json();

	const rows = Array.isArray(data?.rows) ? data.rows : [];
	const feed = data?.feed || {};

	setText("msFeedHealth", feed?.healthy ? "OK" : "DOWN");
	setText("msRowCount", rows.length);
	setText("msUpdated", data?.timestamp ? new Date(data.timestamp).toLocaleTimeString() : "--");
	setText("msExecHalted", rows.some(r => r?.execution_halted) ? "YES" : "NO");

	const tbody = document.getElementById("multiSymbolBody");
	if (!tbody) return;
	tbody.innerHTML = "";

	for (const row of rows) {
		const market = row.market || {};
		const model = row.model || {};
		const risk = row.risk || {};
		const basis = row.basis || {};
		const resolver = row.resolver || {};

		const tr = document.createElement("tr");
		tr.style.cursor = "pointer";
		tr.innerHTML = `
			<td>${row.symbol || "--"}</td>
			<td>${market.htf_bias || "--"}</td>
			<td>${market.ltf_structure || "--"}</td>
			<td>${model.active_model || "--"}</td>
			<td>${model.confidence != null ? Number(model.confidence).toFixed(2) : "--"}</td>
			<td>${risk.risk_percent != null ? Number(risk.risk_percent).toFixed(2) : "--"}</td>
			<td>${risk.phase || "--"}</td>
			<td>${(row.prop_behavior || {}).mode || "--"}</td>
			<td>${basis.status || "--"}</td>
			<td>${resolver.status || "--"}</td>
			<td>${resolver.watch_only ? "YES" : "NO"}</td>
			<td>${market.news_state || "--"}</td>
		`;

		tr.addEventListener("click", () => {
			const select = document.getElementById("chartSymbol");
			if (!select) return;
			const canonicalToFeed = {
				XAUUSD: "GC.FUT",
				NQ: "NQ.FUT",
				EURUSD: "6E.FUT",
				BTC: "BTC.FUT",
				US30: "YM.FUT",
			};
			const feedSymbol = canonicalToFeed[row.symbol] || row.symbol;
			select.value = feedSymbol;
			select.dispatchEvent(new Event("change"));
		});

		tbody.appendChild(tr);
	}
}

async function updateBasisOps(forceRefresh = false) {
	const symbol = selectedChartSymbol();
	setText("basisSymbol", symbol);

	const [basisRes, contractsRes, contextRes] = await Promise.all([
		apiFetch(`/market/basis?symbol=${encodeURIComponent(symbol)}&refresh=${forceRefresh ? "true" : "false"}`),
		apiFetch(`/market/contracts?symbol=${encodeURIComponent(symbol)}`),
		apiFetch(`/market/context?symbol=${encodeURIComponent(symbol)}`),
	]);
	if (!basisRes.ok || !contractsRes.ok || !contextRes.ok) return;

	const basis = await basisRes.json();
	const contracts = await contractsRes.json();
	const context = await contextRes.json();
	const resolver = contracts?.resolver || {};
	const policy = context?.basis_policy || {};
	const watch = context?.resolver_watch || {};

	setText("basisStatus", basis?.status || "--");
	setText("basisBps", basis?.smooth_bps != null ? Number(basis.smooth_bps).toFixed(2) : "--");
	setText("basisZ", basis?.zscore != null ? Number(basis.zscore).toFixed(2) : "--");
	setText("basisGuard", basis?.safety_block ? (basis?.guard_reason || "BLOCKED") : "OK");
	setText("basisPolicyBlock", policy?.hard_block ? "YES" : "NO");
	setText("basisPolicyRisk", policy?.risk_modifier != null ? Number(policy.risk_modifier).toFixed(2) : "--");
	setOpsChips("basisPolicyReasons", Array.isArray(policy?.reasons) && policy.reasons.length ? policy.reasons.join(" | ") : "--");

	setText("resolverActive", resolver?.active_symbol || "--");
	setText("resolverStatus", resolver?.last_status || "--");
	setText("resolverFailures", resolver?.consecutive_failures != null ? String(resolver.consecutive_failures) : "--");
	setText("resolverAttempts", resolver?.attempts != null ? String(resolver.attempts) : "--");
	setText("resolverTtl", resolver?.ttl_seconds != null ? `${resolver.ttl_seconds}s` : "--");
	setText("resolverWatchOnly", watch?.watch_only ? "YES" : "NO");
	setText("resolverWatchReason", watch?.reason || "--");
}

async function warmupContracts() {
	const btn = document.getElementById("basisWarmupBtn");
	if (btn) {
		btn.disabled = true;
		btn.innerText = "Warming...";
	}
	try {
		await apiFetch("/market/contracts/warmup?force_refresh=true&max_candidates=1&max_probe_seconds=0.8", {
			method: "POST",
		});
		await updateBasisOps();
	} finally {
		if (btn) {
			btn.disabled = false;
			btn.innerText = "Warmup Contracts";
		}
	}
}

async function setPhaseDashboard(phase) {
	const res = await apiFetch("/admin/set_phase", {
		method: "POST",
		headers: { "Content-Type": "application/json" },
		body: JSON.stringify({ phase }),
	});
	if (!res.ok) return;
	await loadStatus();
	await updatePropStatus();
}

async function setAccountSizeDashboard(accountSize) {
	const key = `${Math.max(1, Math.round(Number(accountSize) / 1000))}K`;
	const res = await apiFetch("/admin/prop_engine/configure", {
		method: "POST",
		headers: { "Content-Type": "application/json" },
		body: JSON.stringify({
			active_accounts: [key],
			primary_account: key,
			mode_map: { [key]: "STANDARD" },
		}),
	});
	if (!res.ok) return;
	await updatePropStatus();
	await updateEquityBar();
	await updateDrawdownBar();
	await syncPropEngineControls();
}

function selectedPropAccounts() {
	const checkboxes = Array.from(document.querySelectorAll(".prop-account-cb"));
	const selected = checkboxes
		.filter((node) => node.checked)
		.map((node) => String(node.value || "").toUpperCase())
		.filter(Boolean);
	return selected.length ? selected : [String(document.getElementById("propPrimaryAccountSelect")?.value || "50K").toUpperCase()];
}

async function configurePropEngineDashboard() {
	const primary = String(document.getElementById("propPrimaryAccountSelect")?.value || "50K").toUpperCase();
	const mode = String(document.getElementById("propModeSelect")?.value || "STANDARD").toUpperCase();
	const active = selectedPropAccounts();
	if (!active.includes(primary)) active.push(primary);

	const modeMap = {};
	active.forEach((key) => {
		modeMap[key] = mode;
	});

	const res = await apiFetch("/admin/prop_engine/configure", {
		method: "POST",
		headers: { "Content-Type": "application/json" },
		body: JSON.stringify({
			active_accounts: active,
			primary_account: primary,
			mode_map: modeMap,
			default_mode: mode,
		}),
	});
	if (!res.ok) return;
	await syncPropEngineControls();
	await updatePropStatus();
	await updateEquityBar();
	await updateDrawdownBar();
}

async function syncPropEngineControls() {
	const res = await apiFetch("/admin/prop_engine/state");
	if (!res.ok) return;
	const data = await res.json();
	const state = data?.state || {};
	const primary = String(state?.primary_account || "50K").toUpperCase();
	const active = Array.isArray(state?.active_accounts) ? state.active_accounts.map((item) => String(item).toUpperCase()) : [];
	const profileMode = String(state?.primary_profile?.mode || "STANDARD").toUpperCase();

	const primarySelect = document.getElementById("propPrimaryAccountSelect");
	if (primarySelect) primarySelect.value = primary;

	const modeSelect = document.getElementById("propModeSelect");
	if (modeSelect) modeSelect.value = profileMode;

	Array.from(document.querySelectorAll(".prop-account-cb")).forEach((node) => {
		node.checked = active.includes(String(node.value || "").toUpperCase());
	});
}

async function updateOpsStatus() {
	const symbol = selectedChartSymbol();
	const [feedRes, execRes, recRes, eqRes, propBehaviorRes, propRes] = await Promise.all([
		apiFetch("/status/feed"),
		apiFetch("/status/execution"),
		apiFetch("/status/reconciliation"),
		apiFetch("/status/equity_verification"),
		apiFetch(`/prop/auto_behavior?symbol=${encodeURIComponent(symbol)}`),
		apiFetch("/prop_status"),
	]);
	if (!feedRes.ok || !execRes.ok || !recRes.ok || !eqRes.ok || !propBehaviorRes.ok || !propRes.ok) return;

	const feed = await feedRes.json();
	const exec = await execRes.json();
	const rec = await recRes.json();
	const eq = await eqRes.json();
	const prop = await propRes.json();
	const propBehaviorData = await propBehaviorRes.json();
	const behavior = propBehaviorData?.behavior || {};
	const override = propBehaviorData?.override || {};
	const feedHealthy = Boolean(feed?.healthy);
	const execStatus = String(exec?.execution_status || "--").toUpperCase();
	const recStatus = String(rec?.status || "--").toUpperCase();
	const eqStatus = String(eq?.status || "--").toUpperCase();
	const lockRule = String(prop?.lock_rule_status || "--").toUpperCase();
	const connected = Boolean(exec?.connected);
	const overrideEnabled = Boolean(override?.enabled);
	const dailyDd = Number(prop?.daily_drawdown_pct);
	const overallDd = Number(prop?.overall_drawdown_pct);

	setOpsValue("opsFeedStatus", feedHealthy ? "OK" : "DOWN", feedHealthy ? "good" : "bad");
	setOpsChips("opsFeedReason", feed?.healthy ? "OK" : (feed?.last_error || feed?.reason || "--"), feedHealthy ? "good" : "warn");
	setOpsChips("opsFeedError", feed?.last_error || "--", "neutral");
	setText("opsFeedCandles", feed?.candles != null ? String(feed.candles) : "--");
	const selectorProfile = exec?.selector_profile || {};
	setText("opsActivePhase", prop?.phase || "--");
	setText("opsCurrentBalance", fmtMoney(prop?.current_balance));
	setText("opsCurrentEquity", fmtMoney(prop?.current_equity));
	setOpsValue("opsDailyDdPct", fmtPct(prop?.daily_drawdown_pct), Number.isFinite(dailyDd) ? (dailyDd > 4 ? "bad" : dailyDd > 2.5 ? "warn" : "good") : "neutral");
	setOpsValue("opsOverallDdPct", fmtPct(prop?.overall_drawdown_pct), Number.isFinite(overallDd) ? (overallDd > 7 ? "bad" : overallDd > 4 ? "warn" : "good") : "neutral");
	setOpsValue("opsLockRule", prop?.lock_rule_status || "--", lockRule.includes("LOCK") || lockRule.includes("BREACH") ? "warn" : "good");
	setText("opsBreachRoom", fmtMoney(prop?.remaining_room_to_breach));
	setOpsValue("opsPlaywrightConnected", connected ? "YES" : "NO", connected ? "good" : "bad");
	setText("opsBrowserHeartbeat", exec?.browser_heartbeat_status ? `${exec.browser_heartbeat_status}${exec?.browser_heartbeat_age_seconds != null ? ` (${exec.browser_heartbeat_age_seconds}s)` : ""}` : "--");
	setText("opsLastExecutionTs", exec?.last_trade_time ? new Date(Number(exec.last_trade_time) * 1000).toLocaleString() : "--");
	setOpsValue("opsSelectorProfile", selectorProfile?.calibrated ? "CALIBRATED" : "NOT_CALIBRATED", selectorProfile?.calibrated ? "good" : "warn");
	setText("opsSelectorUpdated", selectorProfile?.updated_at ? new Date(selectorProfile.updated_at).toLocaleString() : "--");
	setOpsValue("opsExecutionStatus", exec?.execution_status || "--", execStatus === "HALTED" ? "bad" : "good");
	setOpsValue("opsReconciliationStatus", rec?.status || "--", recStatus.includes("HALT") || recStatus.includes("FAIL") ? "bad" : recStatus.includes("WARN") ? "warn" : "good");
	setOpsValue("opsEquityStatus", eq?.status || "--", eqStatus.includes("HALT") || eqStatus.includes("FAIL") ? "bad" : eqStatus.includes("WARN") ? "warn" : "good");
	setText("opsPropMode", behavior?.mode || "--");
	setText("opsPropRiskMult", behavior?.risk_multiplier != null ? Number(behavior.risk_multiplier).toFixed(2) : "--");
	setOpsChips("opsPropReasons", Array.isArray(behavior?.reasons) && behavior.reasons.length ? behavior.reasons.join(" | ") : "--");
	setOpsValue("opsPropOverride", overrideEnabled ? (override?.mode || "CUSTOM") : "NONE", overrideEnabled ? "warn" : "neutral");
	setText("opsPropOverrideExpiry", override?.enabled && override?.expires_at ? new Date(Number(override.expires_at) * 1000).toLocaleString() : "--");

	const runtime = String(exec?.execution_status || "UNKNOWN").toUpperCase() === "HALTED" ? "HALTED" : "ACTIVE";
	setOpsValue("engineRuntimeStatus", runtime, runtime === "HALTED" ? "bad" : "good");

	try {
		const rvRes = await apiFetch("/admin/control/risk_violations?limit=200", {
			headers: adminHeaders(),
		});
		if (rvRes.ok) {
			const rv = await rvRes.json();
			const items = Array.isArray(rv?.items) ? rv.items : [];
			setOpsValue("opsRiskViolations", String(items.length), items.length > 0 ? "bad" : "good");
		}
	} catch (_) {
		setOpsValue("opsRiskViolations", "--", "neutral");
	}

	try {
		const stateRes = await apiFetch("/admin/control/state", {
			headers: adminHeaders(),
		});
		if (stateRes.ok) {
			const state = await stateRes.json();
			const execCfg = state?.execution_controls || {};
			const riskCfg = state?.risk_limits || {};
			const engineCfg = state?.engine_controls || {};
			setText("opsCfgSpreadMax", execCfg?.spread_max_limit != null ? Number(execCfg.spread_max_limit).toFixed(2) : "--");
			setText("opsCfgCooldown", execCfg?.cooldown_seconds != null ? `${execCfg.cooldown_seconds}s` : "--");
			setText("opsCfgMaxTrades", execCfg?.max_trades_per_day != null ? String(execCfg.max_trades_per_day) : "--");
			setText("opsCfgMaxRisk", riskCfg?.max_risk_per_trade != null ? `${Number(riskCfg.max_risk_per_trade).toFixed(2)}%` : "--");
			const flags = [
				engineCfg?.ict_enabled ? "ICT" : null,
				engineCfg?.iceberg_enabled ? "ICEBERG" : null,
				engineCfg?.astro_enabled ? "ASTRO" : null,
			].filter(Boolean);
			setOpsChips("opsCfgEngineFlags", flags.length ? flags.join("|") : "NONE");
			setText("opsCfgLastSync", new Date().toLocaleTimeString());
		}
	} catch (_) {
		setText("opsCfgSpreadMax", "--");
		setText("opsCfgCooldown", "--");
		setText("opsCfgMaxTrades", "--");
		setText("opsCfgMaxRisk", "--");
		setOpsValue("opsCfgEngineFlags", "--", "neutral");
		setText("opsCfgLastSync", "--");
	}

	const simPhase = document.getElementById("opsSimPhase");
	if (simPhase && !simPhase.dataset.bound) {
		simPhase.value = behavior?.phase || "PHASE1";
		simPhase.dataset.bound = "1";
	}

	const simDailyLoss = document.getElementById("opsSimDailyLoss");
	if (simDailyLoss && simDailyLoss.value === "") {
		simDailyLoss.value = Number(dataOrZero(await safeStatusValue("daily_loss"))).toFixed(2);
	}

	const simDrawdown = document.getElementById("opsSimDrawdown");
	if (simDrawdown && simDrawdown.value === "") {
		simDrawdown.value = Number(dataOrZero(await safeStatusValue("capital.current_drawdown"))).toFixed(2);
	}
}

function dataOrZero(value) {
	const n = Number(value);
	return Number.isFinite(n) ? n : 0;
}

async function safeStatusValue(path) {
	try {
		const res = await apiFetch("/status");
		if (!res.ok) return 0;
		const data = await res.json();
		const parts = String(path || "").split(".");
		let cur = data;
		for (const p of parts) {
			if (cur == null) return 0;
			cur = cur[p];
		}
		return cur ?? 0;
	} catch (_) {
		return 0;
	}
}

async function runPropBehaviorScenario() {
	const symbol = selectedChartSymbol();
	const canonicalMap = {
		"GC.FUT": "XAUUSD",
		"NQ.FUT": "NQ",
		"6E.FUT": "EURUSD",
		"BTC.FUT": "BTC",
		"YM.FUT": "US30",
	};
	const canonical = canonicalMap[symbol] || symbol;

	const phase = document.getElementById("opsSimPhase")?.value || "PHASE1";
	const volatility = document.getElementById("opsSimVolatility")?.value || "NORMAL";
	const news = document.getElementById("opsSimNews")?.value || "NORMAL";
	const dailyLoss = dataOrZero(document.getElementById("opsSimDailyLoss")?.value);
	const drawdown = dataOrZero(document.getElementById("opsSimDrawdown")?.value);
	const equity = dataOrZero(await safeStatusValue("balance"));

	const res = await apiFetch("/prop/auto_behavior/simulate", {
		method: "POST",
		headers: { "Content-Type": "application/json" },
		body: JSON.stringify({
			symbol: canonical,
			phase,
			volatility_mode: volatility,
			news_mode: news,
			daily_loss: dailyLoss,
			drawdown,
			equity,
		}),
	});
	if (!res.ok) return;

	const data = await res.json();
	const sim = data?.simulated_with_override || data?.simulated || {};
	setText("opsSimMode", sim?.mode || "--");
	setText("opsSimRisk", sim?.risk_multiplier != null ? Number(sim.risk_multiplier).toFixed(2) : "--");
	setText("opsSimBlock", sim?.hard_block ? "YES" : "NO");
	setText("opsSimReasons", Array.isArray(sim?.reasons) && sim.reasons.length ? sim.reasons.join(" | ") : "--");
}

async function setPropBehaviorOverride(mode, riskMultiplier, hardBlock, expiresMinutes, reasons) {
	const symbol = selectedChartSymbol();
	const canonicalMap = {
		"GC.FUT": "XAUUSD",
		"NQ.FUT": "NQ",
		"6E.FUT": "EURUSD",
		"BTC.FUT": "BTC",
		"YM.FUT": "US30",
	};
	const canonical = canonicalMap[symbol] || symbol;

	const payload = {
		symbol: canonical,
		mode,
		risk_multiplier: riskMultiplier,
		hard_block: hardBlock,
		expires_minutes: expiresMinutes,
		reasons: Array.isArray(reasons) ? reasons : [],
	};

	const res = await apiFetch("/prop/auto_behavior/override", {
		method: "POST",
		headers: { "Content-Type": "application/json" },
		body: JSON.stringify(payload),
	});
	if (!res.ok) return;
	await updateOpsStatus();
}

async function clearPropBehaviorOverride() {
	const symbol = selectedChartSymbol();
	const canonicalMap = {
		"GC.FUT": "XAUUSD",
		"NQ.FUT": "NQ",
		"6E.FUT": "EURUSD",
		"BTC.FUT": "BTC",
		"YM.FUT": "US30",
	};
	const canonical = canonicalMap[symbol] || symbol;

	const res = await apiFetch("/prop/auto_behavior/override/clear", {
		method: "POST",
		headers: { "Content-Type": "application/json" },
		body: JSON.stringify({ symbol: canonical }),
	});
	if (!res.ok) return;
	await updateOpsStatus();
}

async function runFeedProbe() {
	const symbol = selectedChartSymbol();
	const res = await apiFetch(`/market/symbol_probe?symbol=${encodeURIComponent(symbol)}&lookback_minutes=240&include_contracts=false&max_candidates=4`);
	if (!res.ok) return;
	const data = await res.json();
	const rows = Array.isArray(data?.results) ? data.results : [];
	const preview = rows.map(r => `${r.candidate}:${r.count}`).join(" | ");
	setText("opsProbeSnapshot", preview || "No probe results");
	await updateOpsStatus();
}

async function engineAction(action) {
	const endpoint = action === "start" ? "/engine/start" : "/engine/stop";
	const res = await apiFetch(endpoint, { method: "POST" });
	if (!res.ok) return;
	const data = await res.json();
	setText("engineRuntimeStatus", data?.status || "--");
	await updateOpsStatus();
}

async function reconnectExecutionBrowser() {
	await apiFetch("/execution/reconnect?async_mode=true&force=false", { method: "POST" });
	await updateOpsStatus();
	setTimeout(() => updateOpsStatus().catch(() => {}), 1200);
	setTimeout(() => updateOpsStatus().catch(() => {}), 2600);
}

async function adminEmergency(action, enabled = null) {
	const endpointMap = {
		kill: "/admin/control/emergency/kill",
		restart: "/admin/control/emergency/restart_execution",
		disable_auto: "/admin/control/emergency/auto_trading",
	};
	const endpoint = endpointMap[action];
	if (!endpoint) return;
	const options = {
		method: "POST",
		headers: adminHeaders(),
	};
	if (action === "disable_auto") {
		options.body = JSON.stringify({ enabled: Boolean(enabled) });
	}
	await apiFetch(endpoint, options);
	await updateOpsStatus();
}

setInterval(() => {
	if (!document.getElementById("governancePanel")?.classList.contains("open")) return;
	loadStatus().catch(() => {});
	updateVolatility().catch(() => {});
	updatePropStatus().catch(() => {});
	updateEquityBar().catch(() => {});
	updateDrawdownBar().catch(() => {});
	updateModelStats().catch(() => {});
	updateNewsSeverity().catch(() => {});
}, 5000);

setInterval(() => {
	if (!document.getElementById("systemHealthPanel")?.classList.contains("open")) return;
	updateSystemHealth().catch(() => {});
}, 5000);

setInterval(() => {
	if (!document.getElementById("journalPanel")?.classList.contains("open")) return;
	loadJournal().catch(() => {});
}, 8000);

setInterval(() => {
	if (!document.getElementById("operationsConsolePanel")?.classList.contains("open")) return;
	updateBasisOps().catch(() => {});
	updateOpsStatus().catch(() => {});
	updateMultiSymbolDashboard().catch(() => {});
}, 7000);

const warmupBtn = document.getElementById("basisWarmupBtn");
if (warmupBtn) warmupBtn.addEventListener("click", () => warmupContracts().catch(() => {}));

const chartSymbolSelect = document.getElementById("chartSymbol");
if (chartSymbolSelect) {
	chartSymbolSelect.addEventListener("change", () => updateBasisOps(true).catch(() => {}));
	chartSymbolSelect.addEventListener("change", () => runFeedProbe().catch(() => {}));
	chartSymbolSelect.addEventListener("change", () => updateModelStats().catch(() => {}));
	chartSymbolSelect.addEventListener("change", () => loadJournal().catch(() => {}));
	chartSymbolSelect.addEventListener("change", () => updateOpsStatus().catch(() => {}));
}

const phase1Btn = document.getElementById("phase1Btn");
if (phase1Btn) phase1Btn.addEventListener("click", () => setPhaseDashboard("PHASE1").catch(() => {}));

const phase2Btn = document.getElementById("phase2Btn");
if (phase2Btn) phase2Btn.addEventListener("click", () => setPhaseDashboard("PHASE2").catch(() => {}));

const fundedBtn = document.getElementById("fundedBtn");
if (fundedBtn) fundedBtn.addEventListener("click", () => setPhaseDashboard("FUNDED").catch(() => {}));

const applyPropEngineBtn = document.getElementById("applyPropEngineBtn");
if (applyPropEngineBtn) applyPropEngineBtn.addEventListener("click", () => configurePropEngineDashboard().catch(() => {}));

const engineStartBtn = document.getElementById("engineStartBtn");
if (engineStartBtn) engineStartBtn.addEventListener("click", () => engineAction("start").catch(() => {}));

const engineStopBtn = document.getElementById("engineStopBtn");
if (engineStopBtn) engineStopBtn.addEventListener("click", () => engineAction("stop").catch(() => {}));

const opsProbeBtn = document.getElementById("opsProbeBtn");
if (opsProbeBtn) opsProbeBtn.addEventListener("click", () => runFeedProbe().catch(() => {}));

const opsReconnectBtn = document.getElementById("opsReconnectBtn");
if (opsReconnectBtn) opsReconnectBtn.addEventListener("click", () => reconnectExecutionBrowser().catch(() => {}));

const opsKillSwitchBtn = document.getElementById("opsKillSwitchBtn");
if (opsKillSwitchBtn) opsKillSwitchBtn.addEventListener("click", () => adminEmergency("kill").catch(() => {}));

const opsRestartExecBtn = document.getElementById("opsRestartExecBtn");
if (opsRestartExecBtn) opsRestartExecBtn.addEventListener("click", () => adminEmergency("restart").catch(() => {}));

const opsDisableAutoBtn = document.getElementById("opsDisableAutoBtn");
if (opsDisableAutoBtn) opsDisableAutoBtn.addEventListener("click", () => adminEmergency("disable_auto", false).catch(() => {}));

const opsDefensiveBtn = document.getElementById("opsDefensiveBtn");
if (opsDefensiveBtn) {
	opsDefensiveBtn.addEventListener("click", () => setPropBehaviorOverride(
		"DEFENSIVE_OVERRIDE",
		0.5,
		false,
		60,
		["Manual defensive override"],
	).catch(() => {}));
}

const opsHaltBtn = document.getElementById("opsHaltBtn");
if (opsHaltBtn) {
	opsHaltBtn.addEventListener("click", () => setPropBehaviorOverride(
		"HALT_OVERRIDE",
		0.0,
		true,
		60,
		["Manual halt override"],
	).catch(() => {}));
}

const opsClearOverrideBtn = document.getElementById("opsClearOverrideBtn");
if (opsClearOverrideBtn) {
	opsClearOverrideBtn.addEventListener("click", () => clearPropBehaviorOverride().catch(() => {}));
}

const opsSimRunBtn = document.getElementById("opsSimRunBtn");
if (opsSimRunBtn) {
	opsSimRunBtn.addEventListener("click", () => runPropBehaviorScenario().catch(() => {}));
}

for (const kind of Object.keys(MICRO_PANEL_CONFIG)) {
	toggleMicroPanel(kind, false);
}
initMicroPanelDrags();
toggleGovernancePanel(false);
toggleSystemHealthPanel(false);
initGovernancePanelInteractions();
initSystemHealthPanelInteractions();
toggleOperationsConsole(false);
initOperationsConsoleDrag();
toggleJournalPanel(false);
initJournalPanelDrag();
