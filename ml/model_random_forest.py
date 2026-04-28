"""
Random Forest Model for XAUUSD
Fast, interpretable tree-based ensemble learning
Best for: Feature importance, non-linear relationships, fast inference
"""

import numpy as np
import pandas as pd
from pathlib import Path
from sklearn.ensemble import RandomForestClassifier
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import train_test_split
import joblib
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class RandomForestModel:
    """Random Forest for price direction prediction."""
    
    def __init__(self, n_estimators=200, model_path="/tmp/xau_rf_model.pkl"):
        """
        Args:
            n_estimators: Number of trees in forest
            model_path: Where to save trained model (outside workspace)
        """
        self.n_estimators = n_estimators
        self.model_path = Path(model_path)
        self.model = None
        self.feature_columns = None
        self.feature_importance = None
        
    def train(self, features_df, test_size=0.2, random_state=42):
        """
        Train Random Forest on engineered features.
        
        Args:
            features_df: DataFrame from feature_engineering.py
            test_size: Fraction for test set
            random_state: For reproducibility
        """
        logger.info(f"Training Random Forest with {len(features_df)} samples, {self.n_estimators} trees")
        
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
        
        # Train Random Forest
        self.model = RandomForestClassifier(
            n_estimators=self.n_estimators,
            max_depth=15,
            min_samples_split=10,
            min_samples_leaf=5,
            random_state=random_state,
            n_jobs=-1,  # Use all CPU cores
            class_weight='balanced'  # Handle class imbalance
        )
        
        self.model.fit(X_train, y_train)
        
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
        joblib.dump(self.model, str(self.model_path))
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
            self.model = joblib.load(str(self.model_path))
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
    
    # Train Random Forest
    rf = RandomForestModel(n_estimators=200)
    rf.train(features_df)
