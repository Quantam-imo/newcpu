#!/bin/bash
# Quick ML Training & Inference Setup
# Everything runs on physical CPU, models stored outside VS Code

set -e

WORKSPACE="/workspaces/newcpu"
MODELS_DIR="/home/codespace/xau_ml_models"

echo "═══════════════════════════════════════════════════════════"
echo "XAUUSD ML Training Setup - CPU-Based"
echo "═══════════════════════════════════════════════════════════"
echo ""
echo "Workspace:    $WORKSPACE"
echo "Models Dir:   $MODELS_DIR"
echo "Python:       $(python3 --version)"
echo ""

# Create models directory
mkdir -p "$MODELS_DIR"
echo "✓ Models directory ready: $MODELS_DIR"
echo ""

# Check dependencies
echo "Checking ML dependencies..."
python3 -c "import pandas; print('✓ pandas')" 2>/dev/null || { echo "✗ pandas missing"; exit 1; }
python3 -c "import numpy; print('✓ numpy')" 2>/dev/null || { echo "✗ numpy missing"; exit 1; }
python3 -c "import sklearn; print('✓ scikit-learn')" 2>/dev/null || { echo "✗ scikit-learn missing"; exit 1; }

echo ""
echo "Checking optional dependencies (TensorFlow, XGBoost)..."
python3 -c "import tensorflow; print('✓ tensorflow')" 2>/dev/null || echo "⚠ tensorflow not installed (LSTM will skip)"
python3 -c "import xgboost; print('✓ xgboost')" 2>/dev/null || echo "⚠ xgboost not installed (XGBoost will skip)"

echo ""
echo "═══════════════════════════════════════════════════════════"
echo "USAGE"
echo "═══════════════════════════════════════════════════════════"
echo ""
echo "1. TRAIN ALL MODELS (15-25 minutes on 4-core CPU):"
echo "   cd $WORKSPACE"
echo "   python3 ml/train_all_models.py"
echo ""
echo "2. GENERATE LIVE TRADING SIGNAL:"
echo "   python3 ml/live_inference.py"
echo ""
echo "3. CHECK TRAINING HISTORY:"
echo "   cat $MODELS_DIR/training_log.json | python3 -m json.tool"
echo ""
echo "4. VIEW RECENT PREDICTIONS:"
echo "   tail -n 5 $MODELS_DIR/live_signals.jsonl"
echo ""
echo "═══════════════════════════════════════════════════════════"
echo ""
echo "Models will be stored in: $MODELS_DIR"
echo "This keeps your VS Code workspace clean (~1GB saved)"
echo ""
