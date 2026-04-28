#!/usr/bin/env python3
"""
ML Training Orchestrator for XAUUSD
Trains all 3 models in sequence, stores models outside VS Code workspace, tracks performance
Models stored in /tmp and /home for persistence without VS Code clutter
"""

import os
import sys
from pathlib import Path
from datetime import datetime
import json
import logging

# Add workspace to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from ml.feature_engineering import load_and_engineer_features
from ml.model_lstm import LSTMModel
from ml.model_random_forest import RandomForestModel
from ml.model_xgboost import XGBoostModel

logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] [%(name)s] %(levelname)s: %(message)s'
)
logger = logging.getLogger(__name__)


class MLTrainingOrchestrator:
    """Coordinate training of all 3 models."""
    
    def __init__(self, workspace_path="/workspaces/newcpu", models_dir="/home/codespace/xau_ml_models"):
        """
        Args:
            workspace_path: Path to AstroQuant workspace
            models_dir: Where to store trained models (outside VS Code)
        """
        self.workspace_path = Path(workspace_path)
        self.models_dir = Path(models_dir)
        self.models_dir.mkdir(parents=True, exist_ok=True)
        
        self.training_log = self.models_dir / "training_log.json"
        self.results = {}
        
    def load_features(self):
        """Load and engineer features from canonical data."""
        canonical_path = self.workspace_path / "market-causality-lab/data/XAU_5m_data.csv"
        
        if not canonical_path.exists():
            raise FileNotFoundError(f"Canonical data not found: {canonical_path}")
        
        logger.info(f"Loading features from {canonical_path}")
        features_df = load_and_engineer_features(str(canonical_path))
        
        logger.info(f"Loaded {len(features_df)} samples with {len(features_df.columns)} features")
        return features_df
    
    def train_lstm(self, features_df):
        """Train LSTM model."""
        logger.info("=" * 60)
        logger.info("TRAINING LSTM MODEL")
        logger.info("=" * 60)
        
        model_path = self.models_dir / "xau_lstm_model.h5"
        lstm = LSTMModel(sequence_length=50, model_path=str(model_path))
        
        try:
            history, train_acc, test_acc = lstm.train(features_df, epochs=30, batch_size=32)
            
            self.results['lstm'] = {
                'status': 'success',
                'train_accuracy': float(train_acc),
                'test_accuracy': float(test_acc),
                'model_path': str(model_path),
                'model_size_mb': model_path.stat().st_size / 1024 / 1024 if model_path.exists() else 0
            }
            logger.info(f"✅ LSTM complete: Train={train_acc:.4f}, Test={test_acc:.4f}")
            
        except Exception as e:
            logger.error(f"❌ LSTM training failed: {e}")
            self.results['lstm'] = {'status': 'failed', 'error': str(e)}
    
    def train_random_forest(self, features_df):
        """Train Random Forest model."""
        logger.info("=" * 60)
        logger.info("TRAINING RANDOM FOREST MODEL")
        logger.info("=" * 60)
        
        model_path = self.models_dir / "xau_rf_model.pkl"
        rf = RandomForestModel(n_estimators=200, model_path=str(model_path))
        
        try:
            train_acc, test_acc = rf.train(features_df)
            
            self.results['random_forest'] = {
                'status': 'success',
                'train_accuracy': float(train_acc),
                'test_accuracy': float(test_acc),
                'model_path': str(model_path),
                'model_size_mb': model_path.stat().st_size / 1024 / 1024 if model_path.exists() else 0
            }
            logger.info(f"✅ Random Forest complete: Train={train_acc:.4f}, Test={test_acc:.4f}")
            
        except Exception as e:
            logger.error(f"❌ Random Forest training failed: {e}")
            self.results['random_forest'] = {'status': 'failed', 'error': str(e)}
    
    def train_xgboost(self, features_df):
        """Train XGBoost model."""
        logger.info("=" * 60)
        logger.info("TRAINING XGBOOST MODEL")
        logger.info("=" * 60)
        
        model_path = self.models_dir / "xau_xgb_model.pkl"
        xgb = XGBoostModel(max_depth=8, learning_rate=0.05, model_path=str(model_path))
        
        try:
            train_acc, test_acc = xgb.train(features_df, n_rounds=500)
            
            self.results['xgboost'] = {
                'status': 'success',
                'train_accuracy': float(train_acc),
                'test_accuracy': float(test_acc),
                'model_path': str(model_path),
                'model_size_mb': model_path.stat().st_size / 1024 / 1024 if model_path.exists() else 0
            }
            logger.info(f"✅ XGBoost complete: Train={train_acc:.4f}, Test={test_acc:.4f}")
            
        except Exception as e:
            logger.error(f"❌ XGBoost training failed: {e}")
            self.results['xgboost'] = {'status': 'failed', 'error': str(e)}
    
    def save_training_log(self):
        """Save training results to JSON log."""
        log_entry = {
            'timestamp': datetime.now().isoformat(),
            'models_directory': str(self.models_dir),
            'results': self.results,
            'total_models_trained': sum(1 for r in self.results.values() if r.get('status') == 'success'),
            'workspace_path': str(self.workspace_path)
        }
        
        # Load existing log or create new
        existing_log = []
        if self.training_log.exists():
            with open(self.training_log) as f:
                existing_log = json.load(f)
        
        existing_log.append(log_entry)
        
        with open(self.training_log, 'w') as f:
            json.dump(existing_log, f, indent=2)
        
        logger.info(f"Training log saved to {self.training_log}")
    
    def print_summary(self):
        """Print training summary."""
        logger.info("\n" + "=" * 60)
        logger.info("TRAINING SUMMARY")
        logger.info("=" * 60)
        
        for model_name, result in self.results.items():
            if result.get('status') == 'success':
                logger.info(f"\n{model_name.upper()}")
                logger.info(f"  Train Accuracy: {result['train_accuracy']:.4f}")
                logger.info(f"  Test Accuracy:  {result['test_accuracy']:.4f}")
                logger.info(f"  Model Size:     {result['model_size_mb']:.2f} MB")
                logger.info(f"  Location:       {result['model_path']}")
            else:
                logger.error(f"\n{model_name.upper()} - FAILED: {result.get('error')}")
        
        logger.info(f"\nModels saved to: {self.models_dir}")
        logger.info(f"Training log:    {self.training_log}")
        logger.info("=" * 60 + "\n")
    
    def run(self):
        """Execute complete training pipeline."""
        logger.info(f"Starting ML Training Pipeline")
        logger.info(f"Workspace: {self.workspace_path}")
        logger.info(f"Models dir: {self.models_dir}")
        
        try:
            # Load features once
            features_df = self.load_features()
            
            # Train all models
            self.train_lstm(features_df)
            self.train_random_forest(features_df)
            self.train_xgboost(features_df)
            
            # Save results
            self.save_training_log()
            self.print_summary()
            
            logger.info("✅ Training pipeline complete!")
            return 0
            
        except Exception as e:
            logger.error(f"Pipeline failed: {e}")
            import traceback
            traceback.print_exc()
            return 1


if __name__ == "__main__":
    orchestrator = MLTrainingOrchestrator()
    exit_code = orchestrator.run()
    sys.exit(exit_code)
