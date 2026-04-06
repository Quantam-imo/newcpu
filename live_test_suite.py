#!/usr/bin/env python3
"""
AstroQuant Live Test Suite
Tests all major endpoints and reports pass/fail with response details.
"""
import json
import time
import urllib.request
import urllib.error

BASE = "http://localhost:8000"
MCL  = f"{BASE}/market_causality"
STS  = f"{BASE}/status"

PASS = "\033[92m✓\033[0m"
FAIL = "\033[91m✗\033[0m"
WARN = "\033[93m!\033[0m"


def get(url, timeout=12):
    t0 = time.time()
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            data = json.loads(r.read())
            return data, time.time() - t0, None
    except urllib.error.HTTPError as e:
        return None, time.time() - t0, f"HTTP {e.code}"
    except Exception as e:
        return None, time.time() - t0, str(e)[:80]


def post(url, body, timeout=12):
    t0 = time.time()
    try:
        payload = json.dumps(body).encode()
        req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read())
            return data, time.time() - t0, None
    except urllib.error.HTTPError as e:
        try:
            body_err = e.read().decode()[:120]
        except Exception:
            body_err = ""
        return None, time.time() - t0, f"HTTP {e.code}: {body_err}"
    except Exception as e:
        return None, time.time() - t0, str(e)[:80]


def check(label, data, err, elapsed, assertions=None):
    if err:
        print(f"  {FAIL}  {label:<45}  {elapsed:.1f}s  ERROR: {err}")
        return False
    ok = True
    if assertions:
        for key, expected in assertions.items():
            val = data.get(key) if isinstance(data, dict) else None
            if expected is not None and val != expected:
                ok = False
        if not ok:
            vals = {k: data.get(k) if isinstance(data, dict) else "N/A" for k in (assertions or {})}
            print(f"  {WARN}  {label:<45}  {elapsed:.1f}s  got={vals}")
            return False
    icon = PASS if ok else FAIL
    extras = ""
    if isinstance(data, dict):
        interesting = {k: v for k, v in data.items()
                       if k in ("status","signal","confidence","price","source","regime",
                                "gann_questions_pct","gann_questions_verdict","gann_questions_score",
                                "gann_questions_total","count","records","fallback","reason","error")}
        extras = "  " + json.dumps(interesting)[:120] if interesting else ""
    print(f"  {icon}  {label:<45}  {elapsed:.1f}s{extras}")
    return True


results = []

print("\n" + "="*70)
print("  AstroQuant Live Test Suite")
print("="*70)

# ── Health ──────────────────────────────────────────────────────────────────
print("\n[1] System Health")
d, t, e = get(f"{BASE}/health")
results.append(check("/health", d, e, t))

d, t, e = get(f"{STS}/data_freshness")
results.append(check("/status/data_freshness", d, e, t, {"status": "OK"}))

# ── Live Price ───────────────────────────────────────────────────────────────
print("\n[2] Live Price")
for sym in ["XAUUSD", "NQ", "EURUSD", "US30"]:
    d, t, e = get(f"{MCL}/live_price?symbol={sym}", timeout=15)
    ok = d.get("status") == "ok" and d.get("price", 0) > 0 if d else False
    results.append(check(f"/live_price {sym}", d, e, t,
                          {"status": "ok"} if not e else None))

# ── Data Freshness Per Symbol ────────────────────────────────────────────────
print("\n[3] Data Freshness Detail")
d, t, e = get(f"{STS}/data_freshness?symbols=XAUUSD,NQ,EURUSD,US30", timeout=20)
if d and not e:
    for row in d.get("symbols", []):
        sym = row.get("symbol", "?")
        status = row.get("status", "?")
        records = row.get("records", 0)
        resolved = row.get("resolved_symbol", "")
        icon = PASS if status == "OK" else FAIL
        print(f"  {icon}  {sym:<10}  status={status:<6}  records={records:<6}  resolved={resolved}")
        results.append(status == "OK")

# ── Question Bank ────────────────────────────────────────────────────────────
print("\n[4] Question Bank (52 questions)")
d, t, e = get(f"{MCL}/question_bank?symbol=XAUUSD", timeout=10)
count = d.get("count", 0) if d else 0
results.append(check("/question_bank GET", d, e, t))
if d:
    print(f"       count={count}, live_answers_included={d.get('live_answers_included')}")
    if count != 52:
        print(f"  {WARN}  Expected 52 questions, got {count}")

# ── POST /question_bank with live payload ────────────────────────────────────
print("\n[5] POST /question_bank live answers")
# First get a live price to build a minimal payload
price_d, _, _ = get(f"{MCL}/live_price?symbol=XAUUSD", timeout=15)
price = (price_d or {}).get("price", 3100.0)
minimal_payload = {
    "symbol": "XAUUSD",
    "price": price,
    "signal": "BUY",
    "confidence": 0.7,
    "regime": "TRENDING_UP",
    "observation": {
        "price": price,
        "symbol": "XAUUSD",
        "signal": "BUY",
        "confidence": 0.7,
        "regime": "TRENDING_UP",
    }
}
d, t, e = post(f"{MCL}/question_bank", minimal_payload, timeout=10)
results.append(check("/question_bank POST", d, e, t))
if d:
    qs = d.get("gann_questions", [])
    pct = d.get("gann_questions_pct", 0)
    verdict = d.get("gann_questions_verdict", "")
    print(f"       answered={len(qs)}, pct={pct}%, verdict={verdict}")

# ── POST /gann_questions ─────────────────────────────────────────────────────
print("\n[6] POST /gann_questions")
d, t, e = post(f"{MCL}/gann_questions", minimal_payload, timeout=10)
results.append(check("/gann_questions POST", d, e, t))
if d:
    qs = d.get("gann_questions", [])
    pct = d.get("gann_questions_pct", 0)
    verdict = d.get("gann_questions_verdict", "")
    score = d.get("gann_questions_score", 0)
    total = d.get("gann_questions_total", 0)
    print(f"       answered={len(qs)}, score={score}/{total}, pct={pct:.1f}%, verdict={verdict}")
    if qs:
        print("       First 8 answers:")
        for q in qs[:8]:
            icon = PASS if q.get("passed") else FAIL
            print(f"         {icon} {q.get('question_id','?'):12}  {str(q.get('answer',''))[:65]}")

# ── GET /gann_qa ─────────────────────────────────────────────────────────────
print("\n[7] GET /gann_qa")
d, t, e = get(f"{MCL}/gann_qa?symbol=XAUUSD", timeout=12)
results.append(check("/gann_qa GET", d, e, t))
if d:
    qs = d.get("gann_questions", [])
    print(f"       answered={len(qs)}, pct={d.get('gann_questions_pct',0)}, verdict={d.get('gann_questions_verdict','?')}")

# ── POST /math_check ─────────────────────────────────────────────────────────
print("\n[8] POST /math_check")
d, t, e = post(f"{MCL}/math_check", minimal_payload, timeout=10)
results.append(check("/math_check POST", d, e, t))
if d:
    score = d.get("math_score", 0)
    total = d.get("math_total", 0)
    verdict = d.get("math_verdict", "")
    print(f"       score={score}/{total}, verdict={verdict}")

# ── Weights ──────────────────────────────────────────────────────────────────
print("\n[9] Weights & History")
d, t, e = get(f"{MCL}/weights", timeout=8)
results.append(check("/weights GET", d, e, t))
if d:
    w = d.get("weights", {})
    print(f"       weight_count={len(w)}, sample={list(w.items())[:3] if isinstance(w,dict) else str(w)[:80]}")

d, t, e = get(f"{MCL}/history?symbol=XAUUSD&limit=5", timeout=8)
results.append(check("/history GET", d, e, t))
if d:
    recs = d.get("history", d.get("records", []))
    print(f"       records={len(recs) if isinstance(recs,list) else '?'}")

# ── timeframe_matrix ─────────────────────────────────────────────────────────
print("\n[10] Timeframe Matrix")
d, t, e = get(f"{MCL}/timeframe_matrix?symbol=XAUUSD", timeout=12)
results.append(check("/timeframe_matrix GET", d, e, t))
if d:
    tfs = d.get("timeframes", d.get("matrix", {}))
    print(f"       timeframe_count={len(tfs) if isinstance(tfs,(dict,list)) else '?'}")

# ── Record Outcome (dry-run) ─────────────────────────────────────────────────
print("\n[11] Record Outcome (dry-run)")
outcome_payload = {
    "symbol": "XAUUSD",
    "signal": "BUY",
    "confidence": 0.72,
    "outcome": "WIN",
    "entry_price": price,
    "exit_price": price * 1.005,
    "pnl": 150.0,
}
d, t, e = post(f"{MCL}/record_outcome", outcome_payload, timeout=8)
results.append(check("/record_outcome POST", d, e, t))
if d:
    print(f"       status={d.get('status')}, updated={d.get('weights_updated')}")

# ── Summary ──────────────────────────────────────────────────────────────────
print("\n[12] /summary (heavy — may timeout)")
d, t, e = get(f"{MCL}/summary?symbol=XAUUSD&timeframe=1d&lookback_years=1", timeout=45)
results.append(check("/summary GET (lookback_years=1)", d, e, t))
if d:
    print(f"       signal={d.get('signal')}, confidence={d.get('confidence')}, regime={d.get('regime')}")
    print(f"       gann={d.get('gann_questions_score')}/{d.get('gann_questions_total')} {d.get('gann_questions_verdict')}")
    if d.get("error"):
        print(f"       inner_error={d['error'][:120]}")

# ── Summary ─────────────────────────────────────────────────────────────────
print("\n" + "="*70)
passed = sum(1 for r in results if r)
total  = len(results)
pct    = 100.0 * passed / total if total else 0
icon   = PASS if pct >= 85 else (WARN if pct >= 60 else FAIL)
print(f"  {icon}  RESULT: {passed}/{total} passed ({pct:.0f}%)")
print("="*70 + "\n")
