"""
Feature Engineering Pipeline for XAUUSD 5m Candles
Extracts 50+ features from raw OHLCV data for ML model training
Designed for LSTM (sequential), Random Forest (tree-based), and XGBoost
"""

import pandas as pd
import numpy as np
from pathlib import Path
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class FeatureEngineer:
    """Transform raw OHLCV into ML-ready features without look-ahead bias."""
    
    def __init__(self, lookback_window=200):
        """
        Args:
            lookback_window: Bars to use for rolling calculations (default 200 = ~1 trading day of 5m)
        """
        self.lookback_window = lookback_window
        
    def create_features(self, df):
        """
        Main feature creation pipeline.
        
        Args:
            df: DataFrame with columns [Date, Open, High, Low, Close, Volume]
            
        Returns:
            DataFrame with original OHLCV + 50+ engineered features
        """
        df = df.copy()
        df['Date'] = pd.to_datetime(df['Date'])
        df = df.sort_values('Date').reset_index(drop=True)
        
        # === PRICE & RETURN FEATURES ===
        df['Close_lag1'] = df['Close'].shift(1)
        df['Close_lag5'] = df['Close'].shift(5)
        df['Close_lag20'] = df['Close'].shift(20)
        
        df['Return_1'] = (df['Close'] - df['Close_lag1']) / df['Close_lag1']  # Current bar return
        df['Return_5'] = (df['Close'] - df['Close_lag5']) / df['Close_lag5']  # 5 bars return
        df['Return_20'] = (df['Close'] - df['Close_lag20']) / df['Close_lag20']  # 20 bars return
        
        # === VOLATILITY FEATURES ===
        df['HL_Range'] = (df['High'] - df['Low']) / df['Open']  # Intrabar volatility
        df['OC_Range'] = abs(df['Close'] - df['Open']) / df['Open']  # Close vs Open
        df['Volatility_20'] = df['Return_1'].rolling(self.lookback_window).std()  # 200-bar volatility
        df['Volatility_Ratio'] = df['HL_Range'] / (df['Volatility_20'] + 1e-8)  # Normalized vol
        
        # === MOMENTUM FEATURES ===
        df['SMA_20'] = df['Close'].rolling(20).mean()
        df['SMA_50'] = df['Close'].rolling(50).mean()
        df['SMA_200'] = df['Close'].rolling(200).mean()
        
        df['Price_vs_SMA20'] = (df['Close'] - df['SMA_20']) / df['SMA_20']
        df['Price_vs_SMA50'] = (df['Close'] - df['SMA_50']) / df['SMA_50']
        df['Price_vs_SMA200'] = (df['Close'] - df['SMA_200']) / df['SMA_200']
        
        df['SMA_Slope_20'] = df['SMA_20'].diff(5) / df['SMA_20'].shift(5)  # Trend direction
        df['SMA_Slope_50'] = df['SMA_50'].diff(5) / df['SMA_50'].shift(5)
        
        # === RSI (Relative Strength Index) ===
        df['RSI_14'] = self._calculate_rsi(df['Close'], 14)
        df['RSI_28'] = self._calculate_rsi(df['Close'], 28)
        
        # === MACD (Moving Average Convergence Divergence) ===
        df['MACD_12_26'], df['MACD_Signal_9'] = self._calculate_macd(df['Close'])
        df['MACD_Histogram'] = df['MACD_12_26'] - df['MACD_Signal_9']
        
        # === ATR (Average True Range) - Volatility ===
        df['ATR_14'] = self._calculate_atr(df, 14)
        
        # === VOLUME FEATURES ===
        df['Volume_SMA_20'] = df['Volume'].rolling(20).mean()
        df['Volume_Ratio'] = df['Volume'] / (df['Volume_SMA_20'] + 1e-8)  # Relative volume
        df['Volume_Trend'] = df['Volume'].diff(5) / df['Volume'].shift(5)  # Volume momentum
        
        # === CANDLESTICK PATTERNS ===
        df['Is_Bullish'] = (df['Close'] > df['Open']).astype(int)
        df['Body_Size'] = abs(df['Close'] - df['Open']) / (df['High'] - df['Low'] + 1e-8)  # Body-to-range ratio
        df['Upper_Wick'] = (df['High'] - np.maximum(df['Open'], df['Close'])) / (df['High'] - df['Low'] + 1e-8)
        df['Lower_Wick'] = (np.minimum(df['Open'], df['Close']) - df['Low']) / (df['High'] - df['Low'] + 1e-8)
        
        # === TIME-OF-DAY FEATURES (cyclical encoding) ===
        df['Hour'] = df['Date'].dt.hour
        df['Minute'] = df['Date'].dt.minute
        df['DayOfWeek'] = df['Date'].dt.dayofweek
        
        # Cyclical encoding: sin/cos transforms for time-of-day patterns
        df['Hour_sin'] = np.sin(2 * np.pi * df['Hour'] / 24)
        df['Hour_cos'] = np.cos(2 * np.pi * df['Hour'] / 24)
        df['DOW_sin'] = np.sin(2 * np.pi * df['DayOfWeek'] / 7)
        df['DOW_cos'] = np.cos(2 * np.pi * df['DayOfWeek'] / 7)
        
        # === SESSION FEATURES ===
        df['Is_US_Session'] = ((df['Hour'] >= 13) & (df['Hour'] < 22)).astype(int)  # 1pm-10pm UTC
        df['Is_Asia_Session'] = ((df['Hour'] >= 0) & (df['Hour'] < 8)).astype(int)  # Midnight-8am UTC
        df['Is_EU_Session'] = ((df['Hour'] >= 8) & (df['Hour'] < 17)).astype(int)  # 8am-5pm UTC
        
        # === PRICE ACTION FEATURES (last N bars) ===
        for lag in [1, 5, 10]:
            df[f'Consecutive_Up_{lag}'] = (df['Is_Bullish'].rolling(lag).sum() == lag).astype(int)
            df[f'Consecutive_Down_{lag}'] = ((1 - df['Is_Bullish']).rolling(lag).sum() == lag).astype(int)
        
        # === SUPPORT/RESISTANCE (20-bar high/low) ===
        df['HighestHigh_20'] = df['High'].rolling(20).max()
        df['LowestLow_20'] = df['Low'].rolling(20).min()
        df['Price_From_High'] = (df['HighestHigh_20'] - df['Close']) / df['HighestHigh_20']
        df['Price_From_Low'] = (df['Close'] - df['LowestLow_20']) / df['LowestLow_20']
        
        # === TARGET VARIABLE (what we want to predict) ===
        # Next bar return (5 bars ahead for better signal)
        df['Target_Return_5'] = df['Return_5'].shift(-1)  # Look-ahead: next 5 bars
        df['Target_Direction'] = (df['Target_Return_5'] > 0).astype(int)  # Binary: up/down
        
        # Drop rows with NaN (lookback warming period)
        df = df.dropna()
        
        logger.info(f"Created {df.shape[1]} features from {len(df)} bars")
        return df
    
    @staticmethod
    def _calculate_rsi(prices, period=14):
        """Calculate Relative Strength Index."""
        delta = prices.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        rs = gain / (loss + 1e-8)
        rsi = 100 - (100 / (1 + rs))
        return rsi
    
    @staticmethod
    def _calculate_macd(prices, fast=12, slow=26, signal=9):
        """Calculate MACD and Signal line."""
        ema_fast = prices.ewm(span=fast).mean()
        ema_slow = prices.ewm(span=slow).mean()
        macd_line = ema_fast - ema_slow
        signal_line = macd_line.ewm(span=signal).mean()
        return macd_line, signal_line
    
    @staticmethod
    def _calculate_atr(df, period=14):
        """Calculate Average True Range."""
        high_low = df['High'] - df['Low']
        high_close = abs(df['High'] - df['Close'].shift())
        low_close = abs(df['Low'] - df['Close'].shift())
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        atr = tr.rolling(period).mean()
        return atr


def load_and_engineer_features(canonical_csv_path, output_path=None):
    """
    Load canonical OHLCV CSV and engineer all features.
    
    Args:
        canonical_csv_path: Path to canonical CSV (e.g., XAU_5m_data.csv)
        output_path: Where to save engineered features (if None, return df only)
        
    Returns:
        DataFrame with all features
    """
    logger.info(f"Loading {canonical_csv_path}")
    df = pd.read_csv(canonical_csv_path, sep=';')
    
    engineer = FeatureEngineer(lookback_window=200)
    df_features = engineer.create_features(df)
    
    if output_path:
        df_features.to_csv(output_path, index=False, sep=';')
        logger.info(f"Saved engineered features to {output_path}")
    
    return df_features


if __name__ == "__main__":
    # Example usage
    canonical_path = Path("market-causality-lab/data/XAU_5m_data.csv")
    
    if canonical_path.exists():
        features_df = load_and_engineer_features(
            str(canonical_path),
            output_path="/tmp/xau_5m_features.csv"
        )
        print(f"\nFeatures shape: {features_df.shape}")
        print(f"\nFeature columns ({len(features_df.columns)}):")
        print(features_df.columns.tolist())
        print(f"\nFirst row:\n{features_df.iloc[0]}")
    else:
        print(f"File not found: {canonical_path}")
