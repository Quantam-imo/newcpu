"""
LSTM (Long Short-Term Memory) Model for XAUUSD
Captures sequential price patterns and dependencies across time
Best for: Temporal sequences, autoregressive relationships
"""

import numpy as np
import pandas as pd
from pathlib import Path
import tensorflow as tf
from tensorflow.keras.models import Sequential
from tensorflow.keras.layers import LSTM, Dense, Dropout
from tensorflow.keras.callbacks import EarlyStopping
from sklearn.preprocessing import StandardScaler
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class LSTMModel:
    """LSTM for price direction prediction (next 5 bars: up/down)."""
    
    def __init__(self, sequence_length=50, model_path="/tmp/xau_lstm_model.h5"):
        """
        Args:
            sequence_length: Number of lookback bars (50 * 5m = ~4 hours)
            model_path: Where to save trained model (outside workspace)
        """
        self.sequence_length = sequence_length
        self.model_path = Path(model_path)
        self.model = None
        self.scaler = StandardScaler()
        self.feature_columns = None
        
    def _create_sequences(self, X, y=None):
        """Create sliding windows for LSTM input."""
        sequences_X = []
        sequences_y = [] if y is not None else None
        
        for i in range(len(X) - self.sequence_length):
            sequences_X.append(X[i:i + self.sequence_length])
            if y is not None:
                sequences_y.append(y[i + self.sequence_length])
        
        return np.array(sequences_X), (np.array(sequences_y) if y is not None else None)
    
    def _build_model(self, input_shape):
        """Build LSTM architecture."""
        model = Sequential([
            LSTM(128, activation='relu', input_shape=input_shape, return_sequences=True),
            Dropout(0.2),
            LSTM(64, activation='relu', return_sequences=False),
            Dropout(0.2),
            Dense(32, activation='relu'),
            Dense(16, activation='relu'),
            Dense(1, activation='sigmoid')  # Binary classification: up/down
        ])
        model.compile(optimizer='adam', loss='binary_crossentropy', metrics=['accuracy'])
        return model
    
    def train(self, features_df, test_size=0.2, epochs=50, batch_size=32):
        """
        Train LSTM on engineered features.
        
        Args:
            features_df: DataFrame from feature_engineering.py
            test_size: Fraction for test set
            epochs: Training epochs
            batch_size: Batch size for training
        """
        logger.info(f"Training LSTM with {len(features_df)} samples, sequence_length={self.sequence_length}")
        
        # Select only numeric features (exclude Date, OHLCV raw)
        exclude_cols = ['Date', 'Open', 'High', 'Low', 'Close', 'Volume', 'Target_Return_5']
        feature_cols = [c for c in features_df.columns if c not in exclude_cols and not c.startswith('Target_')]
        self.feature_columns = feature_cols
        
        X = features_df[feature_cols].values
        y = features_df['Target_Direction'].values
        
        # Normalize features
        X = self.scaler.fit_transform(X)
        
        # Create sequences
        X_seq, y_seq = self._create_sequences(X, y)
        logger.info(f"Created {len(X_seq)} sequences")
        
        # Train/test split
        split_idx = int(len(X_seq) * (1 - test_size))
        X_train, X_test = X_seq[:split_idx], X_seq[split_idx:]
        y_train, y_test = y_seq[:split_idx], y_seq[split_idx:]
        
        logger.info(f"Train: {len(X_train)}, Test: {len(X_test)}")
        
        # Build and train model
        self.model = self._build_model((self.sequence_length, len(feature_cols)))
        
        early_stop = EarlyStopping(monitor='val_loss', patience=5, restore_best_weights=True)
        
        history = self.model.fit(
            X_train, y_train,
            validation_data=(X_test, y_test),
            epochs=epochs,
            batch_size=batch_size,
            callbacks=[early_stop],
            verbose=1
        )
        
        # Evaluate
        train_acc = self.model.evaluate(X_train, y_train, verbose=0)[1]
        test_acc = self.model.evaluate(X_test, y_test, verbose=0)[1]
        
        logger.info(f"Train Accuracy: {train_acc:.4f}, Test Accuracy: {test_acc:.4f}")
        
        # Save model
        self.model.save(str(self.model_path))
        logger.info(f"Model saved to {self.model_path}")
        
        return history, train_acc, test_acc
    
    def predict(self, features_df, return_probabilities=False):
        """
        Predict next 5 bars direction for latest samples.
        
        Args:
            features_df: DataFrame with features
            return_probabilities: If True, return confidence scores [0, 1]
            
        Returns:
            Array of predictions (0=down, 1=up) or probabilities
        """
        if self.model is None:
            self.model = tf.keras.models.load_model(str(self.model_path))
            logger.info(f"Loaded model from {self.model_path}")
        
        exclude_cols = ['Date', 'Open', 'High', 'Low', 'Close', 'Volume', 'Target_Return_5']
        feature_cols = [c for c in features_df.columns if c not in exclude_cols and not c.startswith('Target_')]
        
        X = features_df[feature_cols].values
        X = self.scaler.transform(X)
        X_seq, _ = self._create_sequences(X)
        
        predictions = self.model.predict(X_seq, verbose=0)
        
        if return_probabilities:
            return predictions.flatten()
        else:
            return (predictions.flatten() > 0.5).astype(int)


if __name__ == "__main__":
    from ml.feature_engineering import load_and_engineer_features
    
    # Load features
    canonical_path = Path("market-causality-lab/data/XAU_5m_data.csv")
    features_df = load_and_engineer_features(str(canonical_path))
    
    # Train LSTM
    lstm = LSTMModel(sequence_length=50)
    lstm.train(features_df, epochs=30)
