function getActiveSymbol() {
    return (window.chartState && window.chartState.symbol) ? window.chartState.symbol : "GC.FUT";
}

function fmtTime(value) {
    if (typeof window.formatTableTime === "function") {
        return window.formatTableTime(value);
    }
    return value ?? "--";
}

function renderRows(tableSelector, rowsHtml) {
    const body = document.querySelector(`${tableSelector} tbody`);
    if (!body) return;
    body.innerHTML = rowsHtml || "";
}

async function loadIcebergTable() {
    try {
        const symbol = getActiveSymbol();
        const rows = await window.apiFetchJson(`/orderflow/iceberg/${symbol}`);
        const sorted = [...rows].sort((first, second) => (second.price || 0) - (first.price || 0));
        renderRows(
            "#icebergTable",
            sorted.map((row, index) => `
                <tr${index % 2 === 0 ? ' class="even"' : ''}>
                    <td>${fmtTime(row.time)}</td>
                    <td>${row.price ?? "--"}</td>
                    <td>${row.buy_volume ?? "--"}</td>
                    <td>${row.sell_volume ?? "--"}</td>
                    <td>${row.bias ?? "--"}</td>
                </tr>
            `).join("")
        );
    } catch (error) {
        console.error("Iceberg table load failed:", error.message);
    }
}

async function loadOrderflowTable() {
    try {
        const symbol = getActiveSymbol();
        const rows = await window.apiFetchJson(`/orderflow/table/${symbol}`);
        const sorted = [...rows].sort((first, second) => String(second.time || "").localeCompare(String(first.time || "")));
        renderRows(
            "#orderflowTable",
            sorted.map((row, index) => `
                <tr${index % 2 === 0 ? ' class="even"' : ''}>
                    <td>${fmtTime(row.time)}</td>
                    <td>${row.delta ?? "--"}</td>
                    <td>${row.volume ?? "--"}</td>
                    <td>${row.imbalance ?? "--"}</td>
                </tr>
            `).join("")
        );
    } catch (error) {
        console.error("Order flow table load failed:", error.message);
    }
}

async function loadLadderTable() {
    try {
        const symbol = getActiveSymbol();
        const rows = await window.apiFetchJson(`/orderflow/ladder/${symbol}`);
        const sorted = [...rows].sort((first, second) => (second.price || 0) - (first.price || 0));
        renderRows(
            "#ladderTable",
            sorted.map((row, index) => `
                <tr${index % 2 === 0 ? ' class="even"' : ''}>
                    <td>${fmtTime(row.time)}</td>
                    <td>${row.bid_size ?? "--"}</td>
                    <td>${row.price ?? "--"}</td>
                    <td>${row.ask_size ?? "--"}</td>
                </tr>
            `).join("")
        );
    } catch (error) {
        console.error("Ladder table load failed:", error.message);
    }
}

async function loadTimeSalesTable() {
    try {
        const symbol = getActiveSymbol();
        const rows = await window.apiFetchJson(`/orderflow/time-sales/${symbol}`);
        const sorted = [...rows].sort((first, second) => String(second.time || "").localeCompare(String(first.time || "")));
        renderRows(
            "#timeSalesTable",
            sorted.map((row, index) => `
                <tr${index % 2 === 0 ? ' class="even"' : ''}>
                    <td>${fmtTime(row.time)}</td>
                    <td>${row.price ?? "--"}</td>
                    <td>${row.size ?? "--"}</td>
                    <td>${row.side ?? "--"}</td>
                </tr>
            `).join("")
        );
    } catch (error) {
        console.error("Time & Sales table load failed:", error.message);
    }
}

async function loadCycleTable() {
    try {
        const symbol = getActiveSymbol();
        const cycle = await window.apiFetchJson(`/cycle/${symbol}`);
        const activeCycles = Array.isArray(cycle.active_cycles) && cycle.active_cycles.length
            ? cycle.active_cycles.join(", ")
            : "--";

        renderRows(
            "#cycleTable",
            `<tr>
                <td>${fmtTime(cycle.time)}</td>
                <td>${cycle.bar_count ?? "--"}</td>
                <td>${cycle.phase ?? "--"}</td>
                <td>${cycle.is_cycle ?? "--"}</td>
                <td>${activeCycles}</td>
                <td>${cycle.next_cycle ?? "--"}</td>
            </tr>`
        );
    } catch (error) {
        console.error("Cycle table load failed:", error.message);
    }
}

async function loadLiquidityTable() {
    try {
        const symbol = getActiveSymbol();
        const liquidity = await window.apiFetchJson(`/liquidity/${symbol}`);

        renderRows(
            "#liquidityTable",
            `<tr>
                <td>${fmtTime(liquidity.time)}</td>
                <td>${liquidity.zone ?? "--"}</td>
                <td>${liquidity.bias ?? "--"}</td>
                <td>${liquidity.range_low ?? "--"}</td>
                <td>${liquidity.range_high ?? "--"}</td>
                <td>${liquidity.equilibrium ?? "--"}</td>
            </tr>`
        );
    } catch (error) {
        console.error("Liquidity table load failed:", error.message);
    }
}

async function refreshOrderflowWindows() {
    await Promise.all([
        loadIcebergTable(),
        loadOrderflowTable(),
        loadLadderTable(),
        loadTimeSalesTable(),
        loadCycleTable(),
        loadLiquidityTable()
    ]);
}

setInterval(refreshOrderflowWindows, 4000);
refreshOrderflowWindows();
