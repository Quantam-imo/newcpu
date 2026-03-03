import csv
import sqlite3
from collections import defaultdict
from datetime import datetime
from pathlib import Path

DB_PATH = "ai_trade_journal.db"
REPORT_PATH = Path("monthly_performance_report.csv")


def generate_monthly_report():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT timestamp, pnl, r_multiple, confidence FROM trades")
    rows = c.fetchall()
    conn.close()

    grouped = defaultdict(lambda: {"pnl_sum": 0.0, "r_values": [], "confidence_values": []})

    for timestamp, pnl, r_multiple, confidence in rows:
        try:
            dt = datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
            month_key = dt.strftime("%Y-%m")
        except Exception:
            month_key = "unknown"

        grouped[month_key]["pnl_sum"] += float(pnl or 0.0)
        grouped[month_key]["r_values"].append(float(r_multiple or 0.0))
        grouped[month_key]["confidence_values"].append(float(confidence or 0.0))

    with REPORT_PATH.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["month", "pnl", "avg_r_multiple", "avg_confidence"])

        for month in sorted(grouped.keys()):
            item = grouped[month]
            avg_r = sum(item["r_values"]) / len(item["r_values"]) if item["r_values"] else 0.0
            avg_conf = sum(item["confidence_values"]) / len(item["confidence_values"]) if item["confidence_values"] else 0.0
            writer.writerow([
                month,
                round(item["pnl_sum"], 2),
                round(avg_r, 4),
                round(avg_conf, 4),
            ])

    return str(REPORT_PATH)
