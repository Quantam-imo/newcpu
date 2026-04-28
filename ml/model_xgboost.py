"""
XGBoost Model for XAUUSD
Gradient boosting with superior performance and regularization
Best for: Accuracy, handling complex patterns, production reliability
"""

import numpy as np
import pandas as pd
from pathlib import Path
from xgboost import XGBClassifier
from sklearn.model_selection import train_test_split
import pickle
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class XGBoostModel:
    """XGBoost for price direction prediction."""
    
    def __init__(self, max_depth=8, learning_rate=0.05, model_path="/tmp/xau_xgb_model.pkl"):
        """
        Args:
            max_depth: Tree depth (8-12 recommended)
            learning_rate: Shrinkage parameter (lower = more regularization)
            model_path: Where to save trained model (outside workspace)
        """
        self.max_depth = max_depth
        self.learning_rate = learning_rate
        self.model_path = Path(model_path)
        self.model = None
        self.feature_columns = None
        self.feature_importance = None
        
    def train(self, features_df, test_size=0.2, n_rounds=500, random_state=42):
        """
        Train XGBoost on engineered features.
        
        Args:
            features_df: DataFrame from feature_engineering.py
            test_size: Fraction for test set
            n_rounds: Boosting rounds
            random_state: For reproducibility
        """
        logger.info(f"Training XGBoost with {len(features_df)} samples, max_depth={self.max_depth}")
        
        # Select numeric features
        exclude_cols = ['Date', 'Open', 'High', 'Low', 'Close', 'Volume', 'Target_Return_5']
        feature_cols = [c for c in features_df.columns if c not in exclude_cols and not c.startswith('Target_')]
        self.feature_columns = feature_cols
        
        X = features_df[feature_cols].values
        y = features_df['Target_Direction'].values
        
        # Train/test split
        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=test_size, random_state=random_state, stratify=y
        )
        
        logger.info(f"Train: {len(X_train)}, Test: {len(X_test)}")
        
        # Train XGBoost
        self.model = XGBClassifier(
            max_depth=self.max_depth,
            learning_rate=self.learning_rate,
            n_estimators=n_rounds,
            subsample=0.8,
            colsample_bytree=0.8,
            gamma=1,
            reg_alpha=0.5,
            reg_lambda=1,
            random_state=random_state,
            n_jobs=-1,
            eval_metric='logloss'
        )
        
        self.model.fit(
            X_train, y_train,
            eval_set=[(X_test, y_test)],
            verbose=10
        )
        
        # Evaluate
        train_acc = self.model.score(X_train, y_train)
        test_acc = self.model.score(X_test, y_test)
        
        logger.info(f"Train Accuracy: {train_acc:.4f}, Test Accuracy: {test_acc:.4f}")
        
        # Feature importance
        self.feature_importance = pd.DataFrame({
            'Feature': feature_cols,
            'Importance': self.model.feature_importances_
        }).sort_values('Importance', ascending=False)
        
        logger.info(f"\nTop 10 Most Important Features:")
        print(self.feature_importance.head(10))
        
        # Save model
        with open(str(self.model_path), 'wb') as f:
            pickle.dump(self.model, f)
        logger.info(f"Model saved to {self.model_path}")
        
        return train_acc, test_acc
    
    def predict(self, features_df, return_probabilities=False):
        """
        Predict next 5 bars direction.
        
        Args:
            features_df: DataFrame with features
            return_probabilities: If True, return confidence scores [0, 1]
            
        Returns:
            Array of predictions (0=down, 1=up) or probabilities
        """
        if self.model is None:
            with open(str(self.model_path), 'rb') as f:
                self.model = pickle.load(f)
            logger.info(f"Loaded model from {self.model_path}")
        
        exclude_cols = ['Date', 'Open', 'High', 'Low', 'Close', 'Volume', 'Target_Return_5']
        feature_cols = [c for c in features_df.columns if c not in exclude_cols and not c.startswith('Target_')]
        
        X = features_df[feature_cols].values
        
        if return_probabilities:
            return self.model.predict_proba(X)[:, 1]  # Probability of class 1 (up)
        else:
            return self.model.predict(X)
    
    def get_feature_importance(self, top_n=15):
        """Get top N most important features."""
        if self.feature_importance is None:
            logger.warning("No feature importance data. Train model first.")
            return None
        return self.feature_importance.head(top_n)


if __name__ == "__main__":
    from ml.feature_engineering import load_and_engineer_features
    
    # Load features
    canonical_path = Path("market-causality-lab/data/XAU_5m_data.csv")
    features_df = load_and_engineer_features(str(canonical_path))
    
    # Train XGBoost
    xgb = XGBoostModel(max_depth=8, learning_rate=0.05)
    xgb.train(features_df)
