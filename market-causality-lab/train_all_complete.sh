#!/usr/bin/env bash
# ============================================================
# AstroQuant — Complete AI + Astrology Training Pipeline
# Run once to train ALL timeframes with full astro & news data
# Usage: bash train_all_complete.sh
# ============================================================
set -e
cd "$(dirname "$0")"

VENV="../.venv/bin/activate"
PYTHON="${VENV%/bin/activate}/bin/python3"

source "$VENV"

echo ""
echo "================================================================"
echo "  AstroQuant Complete Training Pipeline"
echo "  Date: $(date '+%Y-%m-%d %H:%M:%S')"
echo "================================================================"

# Default to the layered execution schema so scanner-derived geometry features
# (including gann_astro_math) are always included in model training.
FEATURE_VERSION="${FEATURE_VERSION:-v4_layered_execution}"
# Regenerating full moon-aspects can be slow; keep existing file by default.
REGENERATE_GANN_MOON="${REGENERATE_GANN_MOON:-0}"

# ── Step 1: Verify astro datasets are present and up to date ─────────────────
echo ""
echo "[1/5] Checking astro event datasets..."
ASTRO_COMBINED="data/astro_nakshatra_events_2000_2026.csv"
ASTRO_INGRESS="data/astro_planetary_ingress_2000_2026.csv"
ASTRO_NAK="data/nakshatra_transitions_2000_2026.csv"

for f in "$ASTRO_COMBINED" "$ASTRO_INGRESS" "$ASTRO_NAK"; do
    if [[ -f "$f" ]]; then
        ROWS=$(awk 'END{print NR-1}' "$f")
        LAST=$(tail -1 "$f" | cut -d',' -f1)
        echo "  ✓ $f  ($ROWS rows, last: $LAST)"
    else
        echo "  ✗ $f MISSING — regenerating..."
        cd ..
        python market-causality-lab/scripts/generate_astro_nakshatra_datasets.py
        cd market-causality-lab
        echo "  ✓ Astro datasets regenerated"
        break
    fi
done

# ── Step 1b: Generate / refresh Gann + Moon aspects dataset ──────────────────
echo ""
echo "[1b/5] Generating Gann + Moon aspects dataset..."
GANN_MOON="data/gann_moon_aspects_2000_2026.csv"

if [[ -f "$GANN_MOON" ]]; then
    ROWS=$(awk 'END{print NR-1}' "$GANN_MOON")
    LAST=$(tail -1 "$GANN_MOON" | cut -d',' -f1)
    echo "  ✓ $GANN_MOON  ($ROWS rows, last: $LAST)"
    if [[ "$REGENERATE_GANN_MOON" == "1" ]]; then
        echo "  (re-generating to ensure freshness...)"
    else
        echo "  (using existing dataset; set REGENERATE_GANN_MOON=1 to force refresh)"
    fi
fi
if [[ ! -f "$GANN_MOON" || "$REGENERATE_GANN_MOON" == "1" ]]; then
    python scripts/generate_gann_moon_aspects.py
    ROWS=$(awk 'END{print NR-1}' "$GANN_MOON")
    echo "  ✓ $GANN_MOON  ($ROWS rows)"
fi

# ── Step 1c: Generate / refresh Gann cycles + nodes + pressure points ─────────
echo ""
echo "[1c/5] Generating Gann cycles, nodes, and pressure points dataset..."
GANN_CYCLES="data/gann_cycles_nodes_2000_2026.csv"
python scripts/generate_gann_cycles_nodes.py
ROWS=$(awk 'END{print NR-1}' "$GANN_CYCLES")
echo "  ✓ $GANN_CYCLES  ($ROWS rows)"

# ── Step 2: Build/refresh the derived timeframe CSVs ────────────────────────
echo ""
echo "[2/5] Building missing/derived timeframe datasets (1w, 15m, 1month)..."
python build_missing_timeframes.py

# ── Step 2b: Build direct 25Y Gann/Astro training table ─────────────────────
echo ""
echo "[2b/5] Building direct 25Y Gann/Astro training table..."
python scripts/generate_gann_direct_training_table.py
DIRECT_TABLE="data/reports/gann_astro_25y_ai_training_table.csv"
if [[ -f "$DIRECT_TABLE" ]]; then
    ROWS=$(awk 'END{print NR-1}' "$DIRECT_TABLE")
    echo "  ✓ $DIRECT_TABLE  ($ROWS rows)"
else
    echo "  ✗ $DIRECT_TABLE missing; continuing without direct-table injection"
fi

# ── Step 2c: Build master 25Y ordered cycle ledger (moon/nakshatra/planet/gann) ──
echo ""
echo "[2c/5] Building master 25Y ordered cycle ledger..."
python scripts/generate_master_cycles.py
MASTER_CYCLES="data/reports/master_cycles_25y.csv"
if [[ -f "$MASTER_CYCLES" ]]; then
    ROWS=$(awk 'END{print NR-1}' "$MASTER_CYCLES")
    echo "  ✓ $MASTER_CYCLES  ($ROWS cycle events)"
else
    echo "  ✗ $MASTER_CYCLES missing; continuing without master-cycle injection"
fi

# ── Step 3: Train all AI models with news + astro + gann/moon features ───────
echo ""
echo "  Training: news + nakshatra + Gann + Moon aspects + cycle nodes + pressure points"
echo ""

ASTRO_ARG="--astro-file $ASTRO_COMBINED $GANN_MOON $GANN_CYCLES"
NEWS_ARG="--news-file data/news_data_v2.csv"
DIRECT_ARG="--direct-table data/reports/gann_astro_25y_ai_training_table.csv"
MASTER_CYCLES_ARG="--master-cycles data/reports/master_cycles_25y.csv"
HORIZON="--horizon 1"

run_training() {
    local label="$1"
    local tf="$2"
    local years="$3"
    echo "────────────────────────────────────────"
    echo "  Training: $label  (lookback: ${years}yr)"
    echo "────────────────────────────────────────"
    python train_ai_models.py \
        --timeframe "$tf" \
        --lookback-years "$years" \
        --feature-version "$FEATURE_VERSION" \
        $NEWS_ARG \
        $ASTRO_ARG \
        $DIRECT_ARG \
        $MASTER_CYCLES_ARG \
        $HORIZON
}

# Long timeframes — full 25-year history
run_training "Monthly (1month)"  1month  25
run_training "Weekly (1w)"       1w      25
run_training "Daily (1d)"        1d      25
run_training "4-Hour (4h)"       4h       5
run_training "1-Hour (1h)"       1h       5
run_training "30-Minute (30m)"   30m      2
run_training "15-Minute (15m)"   15m      2
run_training "5-Minute (5m)"     5m       1
run_training "1-Minute (1m)"     1m       1

# ── Step 4: Auto-generate feature impact report ──────────────────────────────
echo ""
echo "[4/7] Generating feature impact report artifact..."
python scripts/generate_feature_impact_report.py

# ── Step 5: Enforce best global fallback pointer ─────────────────────────────
echo ""
echo "[5/7] Updating global fallback pointer (best brier across first-touch scopes)..."
python scripts/update_global_fallback.py

# ── Step 6: Summary ──────────────────────────────────────────────────────────
echo ""
echo "[6/7] Listing trained model registry..."
ls -lh data/ai_models/*.json 2>/dev/null | awk '{print "  " $5, $9}' || echo "  (no models yet)"

echo ""
echo "[7/7] Feature dataset summary..."
for f in data/news_data_v2.csv "$ASTRO_COMBINED" "$GANN_MOON" "$DIRECT_TABLE" "$MASTER_CYCLES"; do
    if [[ -f "$f" ]]; then
        ROWS=$(awk 'END{print NR-1}' "$f")
        echo "  ✓ $f  ($ROWS rows)"
    fi
done

echo ""
echo "================================================================"
echo "  ALL TRAINING COMPLETE"
echo "  Features: news + nakshatra/ingress + Gann + Moon aspects"
echo "           + 25Y direct training table + master cycle ledger"
echo "  Cycle data: moon / nakshatra / planetary / gann (2000-2026)"
echo "  Models saved to: data/ai_models/"
echo "  To retrain any single TF:"
echo "    python train_ai_models.py --timeframe 4h --lookback-years 5"
echo "================================================================"
echo ""
