async function fetchPanelJson(path) {
    const response = await fetch(path, { method: 'GET' });
    if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
    }
    return response.json();
}

export async function createPropChallengePanel() {
    let panel = document.getElementById('propChallengePanel');
    if (panel) {
        panel.classList.add('open');
        return;
    }
    panel = document.createElement('div');
    panel.id = 'propChallengePanel';
    panel.className = 'panel prop-challenge-float';
    panel.innerHTML = `
        <div class="prop-challenge-head">
            <h3>Prop Firm Challenge Dashboard</h3>
            <button class="panel-close-btn" onclick="document.getElementById('propChallengePanel').remove()">✕ Close</button>
        </div>
        <div id="propChallengeContent">Loading...</div>
    `;
    document.body.appendChild(panel);
    try {
        const data = await fetchPanelJson('/prop_status');
        renderPropChallengeContent(data);
    } catch (err) {
        document.getElementById('propChallengeContent').innerText = 'Failed to load challenge data.';
    }
}

function renderPropChallengeContent(data) {
    const el = document.getElementById('propChallengeContent');
    if (!data) {
        el.innerText = 'No challenge data available.';
        return;
    }
    el.innerHTML = `
        <table class="aq-table">
            <tr><th>Phase</th><td>${data.phase || '--'}</td></tr>
            <tr><th>Static Floor</th><td>${data.static_floor != null ? data.static_floor.toFixed(2) : '--'}</td></tr>
            <tr><th>Profitable Days</th><td>${data.profitable_days ?? '--'}</td></tr>
            <tr><th>Trading</th><td>${data.trading_enabled ? 'ACTIVE' : 'DISABLED'}</td></tr>
            <tr><th>Completion</th><td>${data.phase_completion_status || '--'}</td></tr>
            <tr><th>Daily Max Loss</th><td>${data.daily_max_loss != null ? data.daily_max_loss.toFixed(2) : '--'}</td></tr>
            <tr><th>Total Max Loss</th><td>${data.total_max_loss != null ? data.total_max_loss.toFixed(2) : '--'}</td></tr>
            <tr><th>Phase 1 Target</th><td>${data.phase1_target != null ? data.phase1_target.toFixed(2) : '--'}</td></tr>
            <tr><th>Phase 2 Target</th><td>${data.phase2_target != null ? data.phase2_target.toFixed(2) : '--'}</td></tr>
            <tr><th>Risk / Trade</th><td>${data.risk_per_trade_pct != null ? (data.risk_per_trade_pct * 100).toFixed(2) + '%' : '--'}</td></tr>
            <tr><th>Active Accounts</th><td>${Array.isArray(data.active_accounts) ? data.active_accounts.join(', ') : '--'}</td></tr>
            <tr><th>Primary Account</th><td>${data.primary_account || '--'}</td></tr>
            <tr><th>Profile Mode</th><td>${data.profile_mode || '--'}</td></tr>
        </table>
    `;
}

export function addPropChallengeButton() {
    let btn = document.getElementById('openPropChallengeBtn');
    if (btn) return;
    btn = document.createElement('button');
    btn.id = 'openPropChallengeBtn';
    btn.textContent = 'Open Prop Challenge Dashboard';
    btn.onclick = () => createPropChallengePanel();
    document.body.appendChild(btn);
}
