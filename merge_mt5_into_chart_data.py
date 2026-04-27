#!/usr/bin/env python3
"""
Merge MT5 bridge data into chart CSVs, keeping yfinance as fallback.
Monitors for fresh MT5 data and updates all timeframes.
MT5 rows always override yfinance rows at same timestamp.
"""

import pandas as pd
from pathlib import Path
from datetime import datetime, timezone
import sys
import time

MT5_INCOMING = Path("/workspaces/newcpu/market-causality-lab/data/live/mt5/incoming/XAUUSD_feed_latest.csv")
MT5_OUT_DIR = Path("/workspaces/newcpu/market-causality-lab/data/live/mt5")
fmt_chart = "%Y.%m.%d %H:%M"     # Output format for chart CSVs
fmt_mt5_in = "%Y-%m-%d %H:%M:%S" # Input format from MT5

TF_RULES = {
    "5m":  ("5min",  "5m"),
    "15m": ("15min", "15m"),
    "30m": ("30min", "30m"),
    "1h":  ("1h",    "1h"),
    "4h":  ("4h",    "4h"),
    "1d":  ("1D",    "1d"),
}

def load_csv(path, is_mt5_native=False):
    """Load chart CSV, handle both ; and , separators and MT5 native format."""
    if not path.exists():
        return None
    
    # Try tab-separated first (MT5 native), then other formats
    for sep in ("\t", ";", ","):
        try:
            df = pd.read_csv(path, sep=sep, skipinitialspace=True)
            if len(df.columns) >= 4:
                break
        except Exception:
            continue
    
    # Normalize column names: strip angle brackets and convert to lowercase
    df.columns = [c.strip().strip("<>").lower() for c in df.columns]
    
    # Map to standard names
    col_map = {
        "date": "date_col", "time": "time_col",
        "open": "open", "high": "high", "low": "low", "close": "close",
        "tickvol": "volume", "volume": "volume", "source": "source"
    }
    df = df.rename(columns=col_map, errors="ignore")
    
    # Combine date and time columns if separate
    if "date_col" in df.columns and "time_col" in df.columns:
        df["datetime_str"] = df["date_col"].astype(str).str.strip() + " " + df["time_col"].astype(str).str.strip().str.split().str[0]
    elif "date_col" in df.columns:
        df["datetime_str"] = df["date_col"].astype(str).str.strip()
    else:
        df["datetime_str"] = ""
    
    # Convert time: MT5 uses YYYY-MM-DD HH:MM:SS, chart CSVs use YYYY.MM.DD HH:MM
    fmt_for_parse = fmt_mt5_in if is_mt5_native else fmt_chart
    df["time"] = pd.to_datetime(df["datetime_str"], format=fmt_for_parse, utc=True, errors="coerce")
    
    # Convert numeric columns
    for c in ("open","high","low","close","volume"):
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    
    df = df.dropna(subset=["time","close"]).sort_values("time")
    return df[["time","open","high","low","close","volume"]].set_index("time")

def save_csv(df, path):
    """Save chart CSV with standard format."""
    out = df.reset_index().rename(columns={"time":"_time"})
    out["Date"] = out["_time"].dt.strftime(fmt_chart)
    out["Open"]   = out["open"].round(4)
    out["High"]   = out["high"].round(4)
    out["Low"]    = out["low"].round(4)
    out["Close"]  = out["close"].round(4)
    out["Volume"] = out["volume"].fillna(0).astype(int)
    out["Source"] = out.get("source", pd.Series("unknown", index=out.index)).fillna("unknown")
    out[["Date","Open","High","Low","Close","Volume","Source"]].to_csv(
        path, sep=";", index=False)

def merge_mt5_into_charts():
    """Load MT5 data, resample to all TFs, merge into existing CSVs."""
    if not MT5_INCOMING.exists():
        print(f"[{datetime.now(timezone.utc).strftime('%H:%M:%S')}] MT5 incoming file not found: {MT5_INCOMING}")
        return 0
    
    # Load MT5 (native format)
    mt5_df = load_csv(MT5_INCOMING, is_mt5_native=True)
    if mt5_df is None or mt5_df.empty:
        print(f"[{datetime.now(timezone.utc).strftime('%H:%M:%S')}] MT5 file empty or unparseable")
        return 0
    
    mt5_rows_before = len(mt5_df)
    
    updated_count = 0
    
    for tf_key, (rule, suffix) in TF_RULES.items():
        csv_path = MT5_OUT_DIR / f"XAUUSD_live_{tf_key}_intraday.csv"
        
        # Resample MT5 to target TF
        if tf_key == "5m":
            mt5_resampled = mt5_df[["open","high","low","close","volume"]].copy()
            mt5_resampled["source"] = "mt5-bridge"
        else:
            mt5_resampled = (
                mt5_df.resample(rule, closed="left", label="left")
                .agg(open=("open","first"), high=("high","max"),
                     low=("low","min"), close=("close","last"), volume=("volume","sum"))
                .dropna(subset=["open","close"])
            )
            mt5_resampled["source"] = "mt5-bridge"
        
        # Load existing chart CSV
        existing = load_csv(csv_path, is_mt5_native=False)
        if existing is None or existing.empty:
            combined = mt5_resampled.reset_index()
            combined["Date"] = combined["time"].dt.strftime(fmt_chart)
            combined["Source"] = "mt5-bridge"
        else:
            # Merge: MT5 overrides yfinance at same timestamp
            mt5_resampled_reset = mt5_resampled.reset_index()
            existing_reset = existing.reset_index()
            
            combined = pd.concat([existing_reset[["time","open","high","low","close","volume"]], 
                                 mt5_resampled_reset[["time","open","high","low","close","volume"]]])
            combined = combined.drop_duplicates(subset=["time"], keep="first").sort_values("time")
            combined["Date"] = combined["time"].dt.strftime(fmt_chart)
            combined["Source"] = "mt5-bridge"
        
        rows_before = len(existing) if existing is not None else 0
        rows_after = len(combined)
        
        save_csv(combined, csv_path)
        export_path = MT5_OUT_DIR / f"XAUUSD_{tf_key}.csv"
        save_csv(combined, export_path)
        
        if rows_after > rows_before:
            updated_count += 1
            print(f"  {tf_key}: {rows_before} → {rows_after} rows (MT5 merged)")
    
    print(f"[{datetime.now(timezone.utc).strftime('%H:%M:%S')}] MT5 merge: {mt5_rows_before} 5m rows, {updated_count}/6 TFs updated")
    return updated_count

if __name__ == "__main__":
    # Run once or continuous
    if "--watch" in sys.argv:
        last_mtime = 0
        print(f"[{datetime.now(timezone.utc).strftime('%H:%M:%S')}] Watching for MT5 updates... (Ctrl+C to stop)")
        while True:
            try:
                if MT5_INCOMING.exists():
                    mtime = MT5_INCOMING.stat().st_mtime
                    if mtime > last_mtime:
                        last_mtime = mtime
                        merge_mt5_into_charts()
                time.sleep(5)
            except KeyboardInterrupt:
                print(f"\n[{datetime.now(timezone.utc).strftime('%H:%M:%S')}] Watch stopped")
                break
            except Exception as e:
                print(f"[{datetime.now(timezone.utc).strftime('%H:%M:%S')}] Error: {e}")
                time.sleep(5)
    else:
        merge_mt5_into_charts()
