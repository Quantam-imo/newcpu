-- USERS TABLE
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    role TEXT NOT NULL, -- admin, trader
    phase TEXT NOT NULL DEFAULT 'phase1', -- phase1, phase2, funded
    risk_multiplier REAL DEFAULT 1.0,
    auto_trading_enabled INTEGER DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- PROP RULES TABLE
CREATE TABLE IF NOT EXISTS prop_rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    phase TEXT UNIQUE NOT NULL,
    profit_target_percent REAL,
    daily_drawdown_percent REAL,
    overall_drawdown_percent REAL,
    lock_level REAL,
    min_profitable_days INTEGER,
    leverage INTEGER,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

INSERT OR IGNORE INTO prop_rules 
(phase, profit_target_percent, daily_drawdown_percent, overall_drawdown_percent, lock_level, min_profitable_days, leverage)
VALUES
('phase1', 8, 4, 8, 52000, 3, 75),
('phase2', 5, 4, 8, 52000, 3, 75),
('funded', 0, 4, 8, 52000, 3, 75);

-- ENGINE STATUS TABLE
CREATE TABLE IF NOT EXISTS engine_status (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    ict_enabled INTEGER DEFAULT 1,
    iceberg_enabled INTEGER DEFAULT 1,
    astro_enabled INTEGER DEFAULT 1,
    gann_enabled INTEGER DEFAULT 1,
    confluence_threshold REAL DEFAULT 0.7,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- BEHAVIOR OVERRIDE TABLE
CREATE TABLE IF NOT EXISTS behavior_overrides (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    mode TEXT NOT NULL, -- CLEAR, DEFENSIVE, HALT
    expires_at DATETIME,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- TRADE LOG TABLE
CREATE TABLE IF NOT EXISTS trade_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    direction TEXT,
    entry_price REAL,
    sl REAL,
    tp REAL,
    lot_size REAL,
    confidence REAL,
    phase TEXT,
    result REAL,
    status TEXT, -- open, closed, rejected
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- RISK VIOLATION TABLE
CREATE TABLE IF NOT EXISTS risk_violations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT,
    violation_type TEXT,
    description TEXT,
    equity REAL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- EXECUTION STATUS TABLE
CREATE TABLE IF NOT EXISTS execution_status (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    playwright_connected INTEGER DEFAULT 0,
    last_heartbeat DATETIME,
    last_execution DATETIME,
    error_message TEXT
);

-- TIME & SALES TABLE
CREATE TABLE IF NOT EXISTS time_and_sales (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    price REAL NOT NULL,
    size REAL NOT NULL,
    side TEXT, -- buy or sell aggressor
    trade_time DATETIME NOT NULL
);

-- ORDER FLOW AGGREGATE TABLE
CREATE TABLE IF NOT EXISTS orderflow_summary (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    total_buy_volume REAL,
    total_sell_volume REAL,
    delta REAL,
    delta_percent REAL,
    window_start DATETIME,
    window_end DATETIME
);

-- ICEBERG EVENTS TABLE
CREATE TABLE IF NOT EXISTS iceberg_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    price_level REAL,
    buy_absorption REAL,
    sell_absorption REAL,
    repetition_count INTEGER,
    duration_seconds INTEGER,
    dominant_side TEXT,
    confidence REAL,
    detected_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- DOM LADDER TABLE (limited for MBP-1)
CREATE TABLE IF NOT EXISTS dom_ladder (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    price REAL,
    bid_size REAL,
    ask_size REAL,
    imbalance REAL,
    snapshot_time DATETIME
);

-- DELTA TABLE (Per Candle Delta)
CREATE TABLE IF NOT EXISTS candle_delta (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    timeframe TEXT,
    open REAL,
    high REAL,
    low REAL,
    close REAL,
    buy_volume REAL,
    sell_volume REAL,
    delta REAL,
    created_at DATETIME
);

-- LADDER IMBALANCE SUMMARY TABLE
CREATE TABLE IF NOT EXISTS ladder_imbalance_summary (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT,
    strongest_bid_level REAL,
    strongest_ask_level REAL,
    imbalance_ratio REAL,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
