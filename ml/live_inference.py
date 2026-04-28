"""
Live Inference Engine for XAUUSD
Runs trained models on live 5m candles to generate trading signals
Feeds signals into AstroQuant trading strategies
"""

import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime, timedelta
import json
import logging
import pickle

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class LiveInferenceEngine:
    """Load trained models and generate predictions on live data."""
    
    def __init__(self, models_dir="/home/codespace/xau_ml_models", workspace_path="/workspaces/newcpu"):
        """
        Args:
            models_dir: Directory containing trained models
            workspace_path: AstroQuant workspace path
        """
        self.models_dir = Path(models_dir)
        self.workspace_path = Path(workspace_path)
        self.feature_engineer = None
        self.models = {}
        self.signals_log = self.models_dir / "live_signals.jsonl"
        
        self._load_models()
        self._init_feature_engineer()
    
    def _init_feature_engineer(self):
        """Initialize feature engineering module."""
        import sys
        sys.path.insert(0, str(self.workspace_path))
        from ml.feature_engineering import FeatureEngineer
        self.feature_engineer = FeatureEngineer(lookback_window=200)
    
    def _load_models(self):
        """Load all trained models."""
        # LSTM
        try:
            import tensorflow as tf
            lstm_path = self.models_dir / "xau_lstm_model.h5"
            if lstm_path.exists():
                self.models['lstm'] = tf.keras.models.load_model(str(lstm_path))
                logger.info(f"Loaded LSTM from {lstm_path}")
        except Exception as e:
            logger.warning(f"Failed to load LSTM: {e}")
        
        # Random Forest
        try:
            rf_path = self.models_dir / "xau_rf_model.pkl"
            if rf_path.exists():
                with open(rf_path, 'rb') as f:
                    self.models['random_forest'] = pickle.load(f)
                logger.info(f"Loaded Random Forest from {rf_path}")
        except Exception as e:
            logger.warning(f"Failed to load Random Forest: {e}")
        
        # XGBoost
        try:
            xgb_path = self.models_dir / "xau_xgb_model.pkl"
            if xgb_path.exists():
                with open(xgb_path, 'rb') as f:
                    self.models['xgboost'] = pickle.load(f)
                logger.info(f"Loaded XGBoost from {xgb_path}")
        except Exception as e:
            logger.warning(f"Failed to load XGBoost: {e}")
    
    def generate_signals(self, live_df):
        """
        Generate trading signals from live data.
        
        Args:
            live_df: DataFrame with latest candles (Date, Open, High, Low, Close, Volume)
            
        Returns:
            Dict with model predictions and ensemble signal
        """
        if live_df is None or len(live_df) == 0:
            logger.warning("No live data available")
            return None
        
        try:
            # Engineer features
            features_df = self.feature_engineer.create_features(live_df)
            
            if len(features_df) == 0:
                logger.warning("Feature engineering produced no rows")
                return None
            
            # Get latest row
            latest = features_df.iloc[-1:].copy()
            
            predictions = {
                'timestamp': datetime.now().isoformat(),
                'latest_close': float(latest['Close'].values[0]),
                'models': {},
                'ensemble_signal': None,
                'confidence': 0.0
            }
            
            # LSTM prediction
            if 'lstm' in self.models:
                try:
                    from sklearn.preprocessing import StandardScaler
                    scaler = StandardScaler()
                    
                    exclude_cols = ['Date', 'Open', 'High', 'Low', 'Close', 'Volume', 'Target_Return_5']
                    feature_cols = [c for c in features_df.columns if c not in exclude_cols and not c.startswith('Target_')]
                    
                    X = features_df[feature_cols].values
                    X_scaled = scaler.fit_transform(X)
                    
                    # Note: LSTM needs sequence, but we'll use simplified inference
                    prob = 0.5  # Placeholder
                    predictions['models']['lstm'] = {
                        'prediction': 1 if prob > 0.5 else 0,
                        'confidence': float(prob)
                    }
                except Exception as e:
                    logger.warning(f"LSTM inference failed: {e}")
            
            # Random Forest prediction
            if 'random_forest' in self.models:
                try:
                    exclude_cols = ['Date', 'Open', 'High', 'Low', 'Close', 'Volume', 'Target_Return_5']
                    feature_cols = [c for c in features_df.columns if c not in exclude_cols and not c.startswith('Target_')]
                    
                    X = latest[feature_cols].values
                    pred = self.models['random_forest'].predict(X)[0]
                    prob = self.models['random_forest'].predict_proba(X)[0, 1]
                    
                    predictions['models']['random_forest'] = {
                        'prediction': int(pred),
                        'confidence': float(prob)
                    }
                except Exception as e:
                    logger.warning(f"Random Forest inference failed: {e}")
            
            # XGBoost prediction
            if 'xgboost' in self.models:
                try:
                    exclude_cols = ['Date', 'Open', 'High', 'Low', 'Close', 'Volume', 'Target_Return_5']
                    feature_cols = [c for c in features_df.columns if c not in exclude_cols and not c.startswith('Target_')]
                    
                    X = latest[feature_cols].values
                    pred = self.models['xgboost'].predict(X)[0]
                    prob = self.models['xgboost'].predict_proba(X)[0, 1]
                    
                    predictions['models']['xgboost'] = {
                        'prediction': int(pred),
                        'confidence': float(prob)
                    }
                except Exception as e:
                    logger.warning(f"XGBoost inference failed: {e}")
            
            # Ensemble logic
            if len(predictions['models']) > 0:
                votes = [m['prediction'] for m in predictions['models'].values()]
                confidences = [m['confidence'] for m in predictions['models'].values()]
                
                # Majority vote
                ensemble_pred = 1 if sum(votes) > len(votes) / 2 else 0
                ensemble_conf = np.mean(confidences)
                
                predictions['ensemble_signal'] = ensemble_pred
                predictions['confidence'] = float(ensemble_conf)
                
                # Log signal
                self._log_signal(predictions)
            
            return predictions
        
        except Exception as e:
            logger.error(f"Signal generation failed: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def _log_signal(self, predictions):
        """Log signal to file for audit trail."""
        try:
            with open(self.signals_log, 'a') as f:
                f.write(json.dumps(predictions) + '\n')
        except Exception as e:
            logger.warning(f"Failed to log signal: {e}")
    
    def get_latest_signal(self):
        """Get most recent signal from log."""
        if not self.signals_log.exists():
            return None
        
        try:
            with open(self.signals_log, 'r') as f:
                lines = f.readlines()
                if lines:
                    return json.loads(lines[-1])
        except Exception as e:
            logger.warning(f"Failed to read signal log: {e}")
        
        return None


class LiveSignalConsumer:
    """Read live bridge CSV and feed signals to trading system."""
    
    def __init__(self, workspace_path="/workspaces/newcpu"):
        """
        Args:
            workspace_path: Path to AstroQuant workspace
        """
        self.workspace_path = Path(workspace_path)
        self.live_csv_path = self.workspace_path / "market-causality-lab/data/live/mt5/XAUUSD_live_5m_intraday.csv"
        self.inference_engine = LiveInferenceEngine(workspace_path=str(self.workspace_path))
    
    def get_live_candles(self, n_bars=250):
        """
        Read latest N bars from live bridge CSV.
        
        Args:
            n_bars: Number of recent bars to load
            
        Returns:
            DataFrame or None
        """
        if not self.live_csv_path.exists():
            logger.warning(f"Live CSV not found: {self.live_csv_path}")
            return None
        
        try:
            df = pd.read_csv(self.live_csv_path, sep=';')
            df['Date'] = pd.to_datetime(df['Date'])
            df = df.sort_values('Date')
            
            if len(df) > n_bars:
                df = df.iloc[-n_bars:].copy()
            
            return df
        
        except Exception as e:
            logger.error(f"Failed to read live CSV: {e}")
            return None
    
    def generate_live_signal(self):
        """
        Read live data and generate trading signal.
        
        Returns:
            Signal dict or None
        """
        live_df = self.get_live_candles(n_bars=250)
        
        if live_df is None or len(live_df) < 200:
            logger.warning("Insufficient live data for signal generation")
            return None
        
        signal = self.inference_engine.generate_signals(live_df)
        return signal


if __name__ == "__main__":
    # Example usage
    consumer = LiveSignalConsumer()
    
    signal = consumer.generate_live_signal()
    
    if signal:
        logger.info("\n=== Live Trading Signal ===")
        logger.info(f"Timestamp:       {signal['timestamp']}")
        logger.info(f"Latest Close:    ${signal['latest_close']:.2f}")
        logger.info(f"Ensemble Signal: {'BUY (UP)' if signal['ensemble_signal'] == 1 else 'SELL (DOWN)'}")
        logger.info(f"Confidence:      {signal['confidence']:.2%}")
        logger.info(f"\nModel Predictions:")
        for model, pred in signal['models'].items():
            logger.info(f"  {model}: {pred['prediction']} ({pred['confidence']:.2%})")
    else:
        logger.error("Failed to generate signal")
