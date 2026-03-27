from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import List

import pandas as pd

from backend.core.phase1_config import get_phase1_config
from backend.core.output_contracts import output_contract_versions
from backend.memory.scanner import scan_market
from backend.utils.data_loader import load_data, load_news_data, integrate_news_features
from backend.validation.backtest import backtest
from backend.validation.trade_simulator import simulate_trades


TIMEFRAME_FILE_MAP = {
    "1h": "data/XAU_1h_data.csv",
    "30m": "data/XAU_30m_data.csv",
    "5m": "data/XAU_5m_data.csv",
    "1m": "data/XAU_1m_data.csv",
}


def _apply_high_impact_news_guard(memory: list[dict]) -> tuple[list[dict], int]:
    """Return a copy of memory where directional signals are suppressed during high-impact news windows."""
    guarded: list[dict] = []
    suppressed = 0
    directional = {"BUY", "SELL", "STRONG BUY", "STRONG SELL"}

    for rec in memory:
        rec2 = dict(rec)
        signal = rec2.get("signal", "WAIT")
        news = rec2.get("news") or {}
        if signal in directional and bool(news.get("high_impact_active", False)):
            rec2["signal"] = "WAIT"
            suppressed += 1
        guarded.append(rec2)

    return guarded, suppressed


def _slice_last_year(df: pd.DataFrame) -> pd.DataFrame:
    if "time" not in df.columns:
        raise ValueError("Input dataframe must have a 'time' column")

    df = df.sort_values("time").dropna(subset=["time"]).copy()
    end_time = df["time"].max()
    start_time = end_time - pd.Timedelta(days=365)
    return df[df["time"] >= start_time].reset_index(drop=True)


def run_backtest_1y(timeframe: str = "1h", news_file: str = "data/news_data_v2.csv") -> dict:
    phase1_cfg = get_phase1_config()
    if timeframe not in TIMEFRAME_FILE_MAP:
        raise ValueError(f"Unsupported timeframe: {timeframe}")

    file_path = TIMEFRAME_FILE_MAP[timeframe]
    if not Path(file_path).exists():
        raise FileNotFoundError(f"Missing required data file: {file_path}")

    df = load_data(file_path)
    news_status = "missing_optional_file"
    news_events = 0
    news_path = Path(news_file)
    if news_path.exists():
        try:
            news_df = load_news_data(news_file)
            news_events = len(news_df)
            df = integrate_news_features(df, news_df)
            news_status = "loaded"
        except Exception as exc:
            df = integrate_news_features(df, None)
            news_status = f"load_failed ({exc})"
    else:
        df = integrate_news_features(df, None)

    df_1y = _slice_last_year(df)

    if len(df_1y) < 200:
        raise ValueError(
            f"Not enough bars for a meaningful 1-year backtest in {timeframe}. "
            f"Got {len(df_1y)} bars."
        )

    memory = scan_market(df_1y)
    stats = backtest(memory)

    signal_counter = Counter()
    false_phase_counter = Counter()
    phase_signal_stats: dict = {}   # {phase: {"buy": int, "correct": int, "fwd5": int, "fwd5_n": int}}
    evaluated = 0
    correct = 0
    incorrect = 0

    # 5-bar forward accuracy: BUY → is price higher 5 bars later?
    fwd5_evaluated = 0
    fwd5_correct = 0
    fwd5_pnl: list = []   # % price changes for EV calculation

    # Filtered evaluation (Accuracy Pass v1: MANIPULATION + low-vol EXPANSION gate)
    f_evaluated = 0
    f_correct = 0
    f_false_phase_counter = Counter()
    f_fwd5_pnl: list = []

    for i in range(len(memory) - 1):
        rec = memory[i]
        nxt = memory[i + 1]

        pred = rec.get("signal", "WAIT")
        signal_counter[pred] += 1
        phase = rec.get("phase", "UNKNOWN")

        # --- unfiltered next-1-bar pass ---
        if pred in {"BUY", "SELL"}:
            evaluated += 1
            actual = "BUY" if nxt["state"]["trend"] == "UP" else "SELL"
            ps = phase_signal_stats.setdefault(phase, {"buy": 0, "correct": 0, "fwd5": 0, "fwd5_n": 0})
            ps["buy"] += 1
            if pred == actual:
                correct += 1
                ps["correct"] += 1
            else:
                incorrect += 1
                false_phase_counter[phase] += 1

        # --- 5-bar forward accuracy + EV ---
        if pred == "BUY" and i + 5 < len(memory):
            fwd5_evaluated += 1
            entry = rec["state"]["price"]
            exit_p = memory[i + 5]["state"]["price"]
            pct = (exit_p - entry) / entry * 100
            fwd5_pnl.append(pct)
            if exit_p > entry:
                fwd5_correct += 1
                phase_signal_stats.setdefault(phase, {"buy": 0, "correct": 0, "fwd5": 0, "fwd5_n": 0})
                phase_signal_stats[phase]["fwd5"] += 1
            phase_signal_stats.setdefault(phase, {"buy": 0, "correct": 0, "fwd5": 0, "fwd5_n": 0})
            phase_signal_stats[phase]["fwd5_n"] += 1

        # --- filtered pass (Accuracy Pass v1) ---
        # Gate 1: Suppress MANIPULATION signals (2.6% precision — anti-signal)
        # Gate 2: Suppress low-vol EXPANSION (low-energy noise, vol < p25 = 4.5)
        f_pred = pred
        if phase == "MANIPULATION":
            f_pred = "WAIT"
        elif phase == "EXPANSION" and rec["state"]["volatility"] < 4.5:
            f_pred = "WAIT"
        if f_pred in {"BUY", "SELL"}:
            f_evaluated += 1
            actual = "BUY" if nxt["state"]["trend"] == "UP" else "SELL"
            if f_pred == actual:
                f_correct += 1
            else:
                f_false_phase_counter[phase] += 1
            if f_pred == "BUY" and i + 5 < len(memory):
                entry = rec["state"]["price"]
                exit_p = memory[i + 5]["state"]["price"]
                f_fwd5_pnl.append((exit_p - entry) / entry * 100)

    directional_accuracy = (correct / evaluated) if evaluated else 0.0
    filtered_accuracy = (f_correct / f_evaluated) if f_evaluated else 0.0
    fwd5_accuracy = (fwd5_correct / fwd5_evaluated) if fwd5_evaluated else 0.0

    ev_raw = sum(fwd5_pnl) / len(fwd5_pnl) if fwd5_pnl else 0.0
    ev_filtered = sum(f_fwd5_pnl) / len(f_fwd5_pnl) if f_fwd5_pnl else 0.0

    # Trade simulation: optimal (SL=10, TP=20, 7-bar) and no-SL baseline
    sim_optimal = simulate_trades(memory, hold_bars=7, stop_loss_pts=10, take_profit_pts=20)
    sim_no_sl = simulate_trades(memory, hold_bars=7, stop_loss_pts=None, take_profit_pts=None)
    if phase1_cfg["enable_news_guard"]:
        memory_news_guard, suppressed_news_signals = _apply_high_impact_news_guard(memory)
    else:
        memory_news_guard, suppressed_news_signals = memory, 0
    sim_optimal_news_guard = simulate_trades(
        memory_news_guard,
        hold_bars=7,
        stop_loss_pts=10,
        take_profit_pts=20,
    )

    return {
        "report_contract_version": "v1",
        "output_contracts": output_contract_versions(),
        "timeframe": timeframe,
        "file": file_path,
        "news_file": news_file,
        "news_status": news_status,
        "news_events": news_events,
        "news_active_bars": int(df_1y.get("news_event_active", pd.Series(dtype=bool)).sum()) if "news_event_active" in df_1y.columns else 0,
        "phase1_profile": phase1_cfg["profile"],
        "phase1_news_guard_enabled": phase1_cfg["enable_news_guard"],
        "bars_1y": len(df_1y),
        "memory_records": len(memory),
        "trend_backtest": stats,
        "signal_counts": dict(signal_counter),
        "directional": {
            "evaluated": evaluated,
            "correct": correct,
            "incorrect": incorrect,
            "accuracy": round(directional_accuracy, 4),
        },
        "directional_filtered": {
            "evaluated": f_evaluated,
            "correct": f_correct,
            "incorrect": f_evaluated - f_correct,
            "accuracy": round(filtered_accuracy, 4),
            "suppressed": evaluated - f_evaluated,
        },
        "forward5_accuracy": {
            "evaluated": fwd5_evaluated,
            "correct": fwd5_correct,
            "accuracy": round(fwd5_accuracy, 4),
            "expected_value_pct": round(ev_raw, 4),
        },
        "forward5_filtered": {
            "expected_value_pct": round(ev_filtered, 4),
        },
        "phase_signal_precision": {
            p: {
                "signals": v["buy"],
                "correct": v["correct"],
                "precision": round(v["correct"] / v["buy"], 4) if v["buy"] else 0.0,
                "fwd5_acc": round(v["fwd5"] / v["fwd5_n"], 4) if v["fwd5_n"] else 0.0,
            }
            for p, v in phase_signal_stats.items()
        },
        "false_signal_phases": dict(false_phase_counter),
        "false_signal_phases_filtered": dict(f_false_phase_counter),
        "simulation_optimal": sim_optimal,
        "simulation_optimal_news_guard": sim_optimal_news_guard,
        "suppressed_news_signals": suppressed_news_signals,
        "simulation_no_sl": sim_no_sl,
        "range": {
            "start": str(df_1y["time"].min()),
            "end": str(df_1y["time"].max()),
        },
    }


# ---------------------------------------------------------------------------
# Walk-forward quarterly validation (Accuracy Pass v1)
# ---------------------------------------------------------------------------

def run_walkforward(timeframe: str = "1h", news_file: str = "data/news_data_v2.csv") -> List[dict]:
    """Split the last year into 4 equal quarters; report per-quarter accuracy."""
    if timeframe not in TIMEFRAME_FILE_MAP:
        raise ValueError(f"Unsupported timeframe: {timeframe}")

    df = load_data(TIMEFRAME_FILE_MAP[timeframe])
    news_path = Path(news_file)
    if news_path.exists():
        try:
            news_df = load_news_data(news_file)
            df = integrate_news_features(df, news_df)
        except Exception:
            df = integrate_news_features(df, None)
    else:
        df = integrate_news_features(df, None)
    df_1y = _slice_last_year(df)

    total_bars = len(df_1y)
    quarter_size = total_bars // 4
    quarters = []

    for q in range(4):
        q_start = q * quarter_size
        q_end = (q + 1) * quarter_size if q < 3 else total_bars
        q_df = df_1y.iloc[q_start:q_end].reset_index(drop=True)

        if len(q_df) < 60:
            quarters.append({"quarter": q + 1, "bars": len(q_df), "error": "insufficient data"})
            continue

        memory = scan_market(q_df)

        evaluated = 0
        correct = 0
        f_evaluated = 0
        f_correct = 0
        false_phases = Counter()

        for i in range(len(memory) - 1):
            rec = memory[i]
            nxt = memory[i + 1]
            pred = rec.get("signal", "WAIT")

            if pred in {"BUY", "SELL"}:
                evaluated += 1
                actual = "BUY" if nxt["state"]["trend"] == "UP" else "SELL"
                if pred == actual:
                    correct += 1
                else:
                    false_phases[rec.get("phase", "UNKNOWN")] += 1

            # filtered: suppress MANIPULATION and low-vol EXPANSION
            f_pred = pred
            if rec.get("phase") == "MANIPULATION":
                f_pred = "WAIT"
            elif rec.get("phase") == "EXPANSION" and rec["state"]["volatility"] < 4.5:
                f_pred = "WAIT"
            if f_pred in {"BUY", "SELL"}:
                f_evaluated += 1
                actual = "BUY" if nxt["state"]["trend"] == "UP" else "SELL"
                if f_pred == actual:
                    f_correct += 1

        quarters.append({
            "quarter": q + 1,
            "start": str(q_df["time"].min()),
            "end": str(q_df["time"].max()),
            "bars": len(q_df),
            "raw_accuracy": round(correct / evaluated, 4) if evaluated else 0.0,
            "filtered_accuracy": round(f_correct / f_evaluated, 4) if f_evaluated else 0.0,
            "raw_evaluated": evaluated,
            "filtered_evaluated": f_evaluated,
            "false_phases": dict(false_phases),
        })

    return quarters


def main() -> None:
    print("=" * 60)
    print("  ACCURACY PASS v1 — 1-YEAR BACKTEST REPORT")
    print("=" * 60)

    report = run_backtest_1y("1h")

    print(f"Timeframe  : {report['timeframe']}")
    print(f"File       : {report['file']}")
    print(f"News file  : {report['news_file']}  [{report['news_status']}]")
    print(f"News events: {report['news_events']}  Active bars: {report['news_active_bars']}")
    print(f"Phase1     : profile={report['phase1_profile']}  news_guard={report['phase1_news_guard_enabled']}")
    print(f"Bars (1Y)  : {report['bars_1y']}")
    print(f"Records    : {report['memory_records']}")
    print(f"Date range : {report['range']['start']}  ->  {report['range']['end']}")
    print()
    print("[ Trend Prediction (10-bar lookback) ]")
    print(f"  Winrate : {report['trend_backtest']['winrate']:.4f}  ({report['trend_backtest']['winrate']*100:.2f}%)")
    print(f"  Wins    : {report['trend_backtest']['wins']}   Losses: {report['trend_backtest']['losses']}")
    print()
    print("[ Signal Counts ]")
    for sig, cnt in sorted(report["signal_counts"].items()):
        print(f"  {sig:<12}: {cnt}")
    print()
    print("[ Next-1-Bar Directional Accuracy ]")
    d = report["directional"]
    print(f"  Evaluated : {d['evaluated']}")
    print(f"  Correct   : {d['correct']}   Incorrect: {d['incorrect']}")
    print(f"  Accuracy  : {d['accuracy']:.4f}  ({d['accuracy']*100:.2f}%)")
    print(f"  False-signal phases: {report['false_signal_phases']}")
    print()
    print("[ 5-Bar Forward Price Accuracy + Expected Value ]")
    f5 = report["forward5_accuracy"]
    print(f"  Evaluated : {f5['evaluated']}")
    print(f"  Correct   : {f5['correct']}  (price higher 5 bars later)")
    print(f"  Accuracy  : {f5['accuracy']:.4f}  ({f5['accuracy']*100:.2f}%)")
    print(f"  Avg EV    : {f5['expected_value_pct']:+.4f}%  per trade (raw signals)")
    print(f"  Avg EV    : {report['forward5_filtered']['expected_value_pct']:+.4f}%  per trade (v1-filtered)")
    print()
    print("[ Per-Phase Signal Precision ]")
    for phase, ps in sorted(report["phase_signal_precision"].items()):
        print(f"  {phase:<15}: signals={ps['signals']:4d}  1bar={ps['precision']:.4f}  5bar={ps['fwd5_acc']:.4f}")
    print()
    print("[ Accuracy Pass v1 Filter (MANIPULATION + low-vol EXPANSION suppressed) ]")
    df_ = report["directional_filtered"]
    print(f"  Suppressed: {df_['suppressed']} signals")
    print(f"  Evaluated : {df_['evaluated']}")
    print(f"  Accuracy  : {df_['accuracy']:.4f}  ({df_['accuracy']*100:.2f}%)")
    delta_v1 = df_["accuracy"] - d["accuracy"]
    print(f"  Delta     : {delta_v1:+.4f}  ({delta_v1*100:+.2f}%)")
    print()
    print("[ Walk-Forward Quarterly Validation ]")
    quarters = run_walkforward("1h")
    for q in quarters:
        if "error" in q:
            print(f"  Q{q['quarter']}: {q['error']}")
        else:
            print(
                f"  Q{q['quarter']}  {q['start'][:10]} -> {q['end'][:10]}  "
                f"bars={q['bars']}  "
                f"1bar={q['raw_accuracy']:.4f}  "
                f"v1_filtered={q['filtered_accuracy']:.4f}  "
                f"(n={q['raw_evaluated']})"
            )
    print("=" * 60)

    def _print_sim(label: str, s: dict) -> None:
        sl_str = f"SL={s['stop_loss_pts']}pts" if s['stop_loss_pts'] else "no SL"
        tp_str = f"TP={s['take_profit_pts']}pts" if s['take_profit_pts'] else "no TP"
        print(f"  Config     : hold={s['hold_bars']}bars  {sl_str}  {tp_str}")
        print(f"  Trades     : {s['total_trades']}  (wins={s['wins']}, losses={s['losses']})")
        eb = s.get("exit_breakdown", {})
        if eb:
            print(f"  Exit split : SL={eb.get('stop_loss',0)}  TP={eb.get('take_profit',0)}  Hold={eb.get('hold_expiry',0)}")
        print(f"  Winrate    : {s['winrate']:.4f}  ({s['winrate']*100:.2f}%)")
        print(f"  Net return : {s['net_return_pct']:+.2f}%  (${s['initial_capital']:,.0f} → ${s['final_equity']:,.2f})")
        print(f"  Max DD     : -{s['max_drawdown_pct']:.2f}%")
        print(f"  Sharpe     : {s['sharpe']:.3f}")
        print(f"  Avg W/L    : +{s['avg_win']:.2f} / -{s['avg_loss']:.2f}  R={s['r_ratio']:.2f}x")
        print(f"  Max streak : {s['max_consec_wins']} wins / {s['max_consec_losses']} losses")
        print(f"  Kelly f*   : {s['kelly_fraction']:.4f}  →  ½ Kelly = {s['half_kelly']:.4f}  (~{s['half_kelly']*100:.1f}% per trade)")

    print()
    print("[ Trade Simulation — No SL/TP (baseline) ]")
    _print_sim("no_sl", report["simulation_no_sl"])
    print()
    print("[ Trade Simulation — Optimal: SL=10pts  TP=20pts  hold=7bars ]")
    _print_sim("optimal", report["simulation_optimal"])
    print()
    print("[ Trade Simulation — Optimal + High-Impact News Guard ]")
    _print_sim("optimal_news_guard", report["simulation_optimal_news_guard"])
    print(f"  Suppressed during high-impact windows: {report['suppressed_news_signals']}")
    print("=" * 60)


if __name__ == "__main__":
    main()
