import sqlite3
from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse
from typing import Any
from datetime import datetime

router = APIRouter()

@router.get("/export/broker_ticks")
def export_broker_ticks(
    symbol: str = Query(..., description="Symbol, e.g. XAUUSD, NQ, EURUSD, BTC, US30"),
    lookback_minutes: int = Query(1440, description="Lookback window in minutes (default 1440, max 4320)"),
) -> Any:
    """
    Export broker/spot tick history as CSV for a given symbol and lookback window.
    """
    db_path = "data/broker_ticks.db"
    cutoff = int(datetime.utcnow().timestamp()) - (max(60, min(int(lookback_minutes or 1440), 4320)) * 60)
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS broker_ticks (
            id INTEGER PRIMARY KEY,
            symbol TEXT,
            time INTEGER,
            price REAL,
            source TEXT
        )
        """
    )
    c.execute(
        "SELECT time, price, source FROM broker_ticks WHERE symbol=? AND time>=? ORDER BY time ASC",
        (str(symbol).upper(), cutoff)
    )
    rows = c.fetchall()
    conn.close()

    def iter_csv():
        yield "time,price,source\n"
        for t, p, s in rows:
            dt = datetime.utcfromtimestamp(t).isoformat()
            yield f"{dt},{p},{s}\n"

    filename = f"broker_ticks_{symbol}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.csv"
    return StreamingResponse(iter_csv(), media_type="text/csv", headers={
        "Content-Disposition": f"attachment; filename={filename}"
    })
