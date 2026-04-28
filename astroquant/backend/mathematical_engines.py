"""
Mathematical Engines for 52-Question Trading Framework
=======================================================

Validates and calculates mathematical properties that align with:
- Gann geometry and harmonics
- Physics (momentum, gravity, acceleration)
- Fibonacci ratios and proportions
- Confluence scoring
- Probability calculations

Philosophy: "Trade with mathematics, not hope. The market is always teacher."
"""

from dataclasses import dataclass
from typing import Any
import math
import time

from astroquant.backend.prediction_tracker import PredictionTracker


@dataclass
class GannAngleResult:
    """Result of Gann angle proximity calculation"""
    angle_degrees: float
    price_at_angle: float
    current_price: float
    distance_pips: float
    proximity: str  # "EXACT", "NEAR", "NONE"
    is_support: bool
    is_resistance: bool
    next_angle: float
    next_angle_distance: float
    
    def __str__(self):
        return f"Gann {self.angle_degrees}° | Price: {self.price_at_angle} | Current: {self.current_price} | Proximity: {self.proximity}"


@dataclass
class VelocityResult:
    """Result of velocity and momentum analysis"""
    current_velocity: float  # pips per bar
    bars_fuel_remaining: int  # bars until natural exhaustion
    momentum_status: str  # "STRONG", "WEAKENING", "EXHAUSTED"
    acceleration: float  # pips_per_bar change
    time_to_reversal_bars: int
    expected_move_pips: float
    confidence: float  # 0-1
    warning_signs: list[str]
    
    def __str__(self):
        return f"Velocity: {self.current_velocity:.1f} pips/bar | Fuel: {self.bars_fuel_remaining}b | Status: {self.momentum_status}"


@dataclass
class FibonacciLevels:
    """Standard Fibonacci ratio levels"""
    level_23_6: float
    level_38_2: float
    level_50_0: float
    level_61_8: float
    level_78_6: float
    level_100: float
    level_127_2: float
    level_138_2: float
    
    def get_nearest(self, price: float) -> tuple[str, float]:
        """Find nearest Fibonacci level"""
        levels = {
            "23.6%": self.level_23_6,
            "38.2%": self.level_38_2,
            "50.0%": self.level_50_0,
            "61.8%": self.level_61_8,
            "78.6%": self.level_78_6,
            "100%": self.level_100,
            "127.2%": self.level_127_2,
            "138.2%": self.level_138_2,
        }
        nearest = min(levels.items(), key=lambda x: abs(x[1] - price))
        return nearest


@dataclass
class ConfluenceScore:
    """Comprehensive confluence scoring"""
    geometry_score: float  # 0-1
    time_score: float  # 0-1
    structure_score: float  # 0-1
    momentum_score: float  # 0-1
    gann_score: float  # 0-1
    ict_score: float  # 0-1
    
    # Composite
    overall_score: float  # 0-1
    buy_probability: float  # 0-1
    sell_probability: float  # 0-1
    wait_probability: float  # 0-1
    
    # Weakness
    weakest_component: str
    weakest_score: float
    
    def __str__(self):
        return f"Confluence Score: {self.overall_score:.1%} | BUY: {self.buy_probability:.1%} | SELL: {self.sell_probability:.1%} | WAIT: {self.wait_probability:.1%}"


class MathematicalEngines:
    """
    Core mathematical validation engines.
    
    These are the "laws" that prices obey. All questions validate against these laws.
    """
    
    @staticmethod
    def calculate_gann_angles(pivot_price: float, pivot_bar: int, current_bar: int) -> list[GannAngleResult]:
        """
        Calculate Gann angles (45°, 90°, 180°, 225°, 315°) from pivot point.
        
        Gann's principle: Market moves at 45° ratio of price to time.
        1 unit of time = 1 unit of price (1:1 ratio = 45° angle)
        
        Args:
            pivot_price: Price at pivot point
            pivot_bar: Bar number of pivot
            current_bar: Current bar number
        
        Returns:
            List of GannAngleResult for each major angle
        """
        time_elapsed = current_bar - pivot_bar
        
        # Cardinal angles and their price changes per bar
        angles = {
            45: 1.0,    # 1 pip per bar
            90: 0.5,    # 0.5 pip per bar (slower)
            135: 2.0,   # 2 pips per bar (faster)
            180: 0.0,   # Horizontal line
            225: -0.5,  # Downward at 90° inverse
            315: -1.0,  # Downward 45°
        }
        
        results = []
        for angle_deg, price_change_rate in angles.items():
            price_at_angle = pivot_price + (price_change_rate * time_elapsed)
            
            # Assume current price (you would pass this as parameter in real code)
            current_price = pivot_price + (price_change_rate * time_elapsed * 0.95)  # Placeholder
            distance = abs(current_price - price_at_angle)
            
            # Proximity determination
            if distance < 2:  # Within 2 pips
                proximity = "EXACT"
            elif distance < 5:  # Within 5 pips
                proximity = "NEAR"
            else:
                proximity = "NONE"
            
            # Determine if support or resistance
            is_support = current_price < price_at_angle and price_change_rate > 0
            is_resistance = current_price > price_at_angle and price_change_rate > 0
            
            result = GannAngleResult(
                angle_degrees=angle_deg,
                price_at_angle=price_at_angle,
                current_price=current_price,
                distance_pips=distance,
                proximity=proximity,
                is_support=is_support,
                is_resistance=is_resistance,
                next_angle=price_at_angle + (price_change_rate * 5),  # Next 5 bars
                next_angle_distance=(price_at_angle + (price_change_rate * 5)) - current_price,
            )
            results.append(result)
        
        return results
    
    @staticmethod
    def calculate_velocity(prices: list[float], bars_analyzed: int = 5) -> VelocityResult:
        """
        Calculate market velocity (rate of price change) and momentum lifespan.
        
        Principle: Momentum is finite. Velocity exhausts naturally.
        
        Args:
            prices: List of recent price closes
            bars_analyzed: Number of bars to analyze
        
        Returns:
            VelocityResult with momentum analysis
        """
        if len(prices) < bars_analyzed:
            return VelocityResult(
                current_velocity=0,
                bars_fuel_remaining=0,
                momentum_status="INSUFFICIENT_DATA",
                acceleration=0,
                time_to_reversal_bars=0,
                expected_move_pips=0,
                confidence=0,
                warning_signs=["Not enough price data"],
            )
        
        # Calculate recent pips per bar
        recent_prices = prices[-bars_analyzed:]
        pips_last_n_bars = recent_prices[-1] - recent_prices[0]
        current_velocity = pips_last_n_bars / bars_analyzed
        
        # Calculate acceleration (is velocity increasing or decreasing?)
        if len(prices) >= bars_analyzed * 2:
            older_velocity = (prices[-bars_analyzed] - prices[-bars_analyzed*2]) / bars_analyzed
            acceleration = current_velocity - older_velocity
        else:
            acceleration = 0
        
        # Determine momentum status
        if abs(current_velocity) < 1:
            momentum_status = "WEAK"
            bars_fuel = 2
        elif abs(current_velocity) < 5:
            momentum_status = "NORMAL"
            bars_fuel = 5
        elif abs(current_velocity) < 10:
            momentum_status = "STRONG"
            bars_fuel = 8
        else:
            momentum_status = "VERY_STRONG"
            bars_fuel = 6  # Strong moves often exhaust faster
        
        # Check for deceleration (exhaustion warning)
        warning_signs = []
        if acceleration < -0.5:
            warning_signs.append("Momentum decelerating (exhaustion warning)")
            bars_fuel = max(2, bars_fuel - 2)
        
        # Time to reversal (based on oscillation frequency)
        time_to_reversal = bars_fuel + 3  # Add some buffer bars
        
        # Expected move before exhaustion
        expected_move = current_velocity * bars_fuel
        
        # Confidence in velocity estimate
        confidence = min(1.0, (abs(current_velocity) / 20.0))  # Scales with velocity
        
        return VelocityResult(
            current_velocity=current_velocity,
            bars_fuel_remaining=bars_fuel,
            momentum_status=momentum_status,
            acceleration=acceleration,
            time_to_reversal_bars=time_to_reversal,
            expected_move_pips=expected_move,
            confidence=confidence,
            warning_signs=warning_signs,
        )
    
    @staticmethod
    def calculate_fibonacci_levels(swing_low: float, swing_high: float) -> FibonacciLevels:
        """
        Calculate Fibonacci retracement and extension levels.
        
        Used for: identifying reversal zones, profit targets, support/resistance
        
        Args:
            swing_low: Low point of swing
            swing_high: High point of swing
        
        Returns:
            FibonacciLevels with all standard levels
        """
        swing_range = swing_high - swing_low
        
        return FibonacciLevels(
            level_23_6=swing_high - (swing_range * 0.236),
            level_38_2=swing_high - (swing_range * 0.382),
            level_50_0=swing_high - (swing_range * 0.500),
            level_61_8=swing_high - (swing_range * 0.618),
            level_78_6=swing_high - (swing_range * 0.786),
            level_100=swing_low,
            level_127_2=swing_low - (swing_range * 0.272),  # Extension
            level_138_2=swing_low - (swing_range * 0.382),  # Extension
        )
    
    @staticmethod
    def calculate_square_of_9_levels(base_price: float, num_levels: int = 5) -> list[float]:
        """
        Calculate Gann Square of 9 levels.
        
        Square of 9 is based on spiral geometry. Prices at certain positions
        on the square correspond to mathematical harmonies with high reversal potential.
        
        Args:
            base_price: Starting price
            num_levels: Number of levels to calculate
        
        Returns:
            List of Square of 9 price levels
        """
        # Simplified Square of 9: Each level is square root based
        levels = []
        base_sqrt = math.sqrt(base_price)
        
        for i in range(1, num_levels + 1):
            # Each step represents a 90° movement on the square
            new_sqrt = base_sqrt + i
            new_price = new_sqrt ** 2
            levels.append(new_price)
        
        return levels
    
    @staticmethod
    def calculate_gravity_wells(support_level: float, resistance_level: float, 
                               current_price: float, recent_touches: int = 0) -> dict[str, Any]:
        """
        Identify and measure "gravity wells" - support/resistance zones that 
        repeatedly attract price like gravitational forces.
        
        Args:
            support_level: Major support level
            resistance_level: Major resistance level
            current_price: Current price
            recent_touches: Number of times price recently tested this level
        
        Returns:
            Dict with gravity analysis
        """
        distance_to_support = current_price - support_level
        distance_to_resistance = resistance_level - current_price
        
        # Gravity strength increases with recent touches
        support_gravity = min(1.0, recent_touches / 5.0)
        resistance_gravity = min(1.0, recent_touches / 5.0)
        
        # Determine which gravity well is stronger
        if distance_to_support < distance_to_resistance:
            primary_gravity = "support"
            primary_distance = distance_to_support
        else:
            primary_gravity = "resistance"
            primary_distance = distance_to_resistance
        
        return {
            "primary_gravity_well": primary_gravity,
            "primary_distance_pips": primary_distance,
            "support_level": support_level,
            "resistance_level": resistance_level,
            "support_gravity_strength": support_gravity,
            "resistance_gravity_strength": resistance_gravity,
            "bars_to_gravity_well": max(1, int(primary_distance / 1.5)),  # Estimate bars at 1.5 pip/bar
        }
    
    @staticmethod
    def calculate_confluence_score(
        geometry_valid: bool,
        time_valid: bool,
        structure_valid: bool,
        momentum_strong: bool,
        gann_aligned: bool,
        ict_signal: bool,
        geometry_strength: float = 0.9,
        time_strength: float = 0.9,
        structure_strength: float = 0.95,
        momentum_strength: float = 0.85,
        gann_strength: float = 0.88,
        ict_strength: float = 0.80,
    ) -> ConfluenceScore:
        """
        Calculate comprehensive confluence score based on multiple factors.
        
        The more factors that align, the higher the confidence in the setup.
        
        Args:
            geometry_valid: Is geometric formation valid?
            time_valid: Is time window active?
            structure_valid: Is structure confirmed (BOS/CHOCH)?
            momentum_strong: Is momentum present?
            gann_aligned: Are Gann factors aligned?
            ict_signal: Is ICT signal present?
            [strength params]: Individual weight for each factor (0-1)
        
        Returns:
            ConfluenceScore with probabilities
        """
        # Calculate individual scores
        geometry_score = geometry_strength if geometry_valid else 0
        time_score = time_strength if time_valid else 0
        structure_score = structure_strength if structure_valid else 0
        momentum_score = momentum_strength if momentum_strong else 0
        gann_score = gann_strength if gann_aligned else 0
        ict_score = ict_strength if ict_signal else 0
        
        # Overall confluence (average of confirmed factors)
        confirmed_count = sum([geometry_valid, time_valid, structure_valid, 
                              momentum_strong, gann_aligned, ict_signal])
        max_count = 6
        
        overall_score = (geometry_score + time_score + structure_score + 
                        momentum_score + gann_score + ict_score) / max_count
        
        # Probability calculations based on confluence strength
        # More confirmations = higher confidence
        if confirmed_count >= 5:
            buy_prob = 0.72
            sell_prob = 0.18
            wait_prob = 0.10
        elif confirmed_count == 4:
            buy_prob = 0.65
            sell_prob = 0.25
            wait_prob = 0.10
        elif confirmed_count == 3:
            buy_prob = 0.55
            sell_prob = 0.35
            wait_prob = 0.10
        elif confirmed_count == 2:
            buy_prob = 0.48
            sell_prob = 0.48
            wait_prob = 0.04
        else:
            buy_prob = 0.50
            sell_prob = 0.50
            wait_prob = 0.00
        
        # Find weakest component
        scores = {
            "geometry": geometry_score,
            "time": time_score,
            "structure": structure_score,
            "momentum": momentum_score,
            "gann": gann_score,
            "ict": ict_score,
        }
        weakest = min(scores.items(), key=lambda x: x[1])
        
        return ConfluenceScore(
            geometry_score=geometry_score,
            time_score=time_score,
            structure_score=structure_score,
            momentum_score=momentum_score,
            gann_score=gann_score,
            ict_score=ict_score,
            overall_score=overall_score,
            buy_probability=buy_prob,
            sell_probability=sell_prob,
            wait_probability=wait_prob,
            weakest_component=weakest[0],
            weakest_score=weakest[1],
        )


class LearningFeedbackEngine:
    """
    The "Market is the Teacher" learning system.
    
    This AI learns by comparing predictions against realized outcomes.
    Updates confidence weights based on feedback.
    
    Philosophy: "The market is always teacher. Listen."
    """
    
    def __init__(self, tracker: PredictionTracker | None = None):
        """Initialize learning system with baseline weights.

        Args:
            tracker: Optional :class:`PredictionTracker` for file-backed
                persistence.  When provided, weights are loaded from the
                tracker on startup and saved automatically after every update.
                When ``None`` (default), everything stays in-memory only.
        """
        self._tracker = tracker

        # Baseline weights may be overridden by persisted values.
        _baseline = {
            "geometry": 0.88,
            "time": 0.82,
            "structure": 0.92,
            "momentum": 0.85,
            "gann": 0.80,
            "ict": 0.78,
            "confluence": 0.90,
        }

        if tracker is not None:
            persisted = tracker.load_weights()
            self.weights = {k: persisted.get(k, v) for k, v in _baseline.items()}
            self.predictions = tracker.load_predictions()
            self.realized_outcomes = tracker.load_outcomes()
        else:
            self.weights = dict(_baseline)
            # Track predictions for learning
            self.predictions = []
            self.realized_outcomes = []

        # Track which outcome IDs have already been reflected in weights for
        # THIS engine instance.
        self._weighted_outcome_ids: set[str] = set()

        # ── Replay: apply any existing outcomes that have not yet updated weights ──
        # This ensures a freshly-started engine restores learned weights from the
        # persisted outcomes file rather than starting at baseline every time.
        if self.realized_outcomes:
            _pred_by_id = {p["id"]: p for p in self.predictions}
            for _outcome in self.realized_outcomes:
                _pid = _outcome.get("prediction_id")
                if _pid and _pid not in self._weighted_outcome_ids:
                    _pred = _pred_by_id.get(_pid)
                    if _pred is not None:
                        self._update_weights(_pred, _outcome)
                        self._weighted_outcome_ids.add(_pid)
        
    def record_prediction(self,
                         prediction_id: str,
                         direction: str,  # "BUY", "SELL", "WAIT"
                         confluence_score: float,
                         geometry_signal: bool,
                         time_signal: bool,
                         structure_signal: bool,
                         momentum_signal: bool,
                         gann_signal: bool,
                         ict_signal: bool,
                         entry_price: float,
                         stop_price: float,
                         target_price: float,
                         forecast_horizon_days: int,
                         confluence_signal: bool = False,
                         features: dict[str, Any] | None = None) -> dict[str, Any]:
        """
        Record a prediction to learn from later.
        
        Args:
            prediction_id: Unique ID for this prediction
            direction: "BUY", "SELL", or "WAIT"
            confluence_score: Overall confluence strength (0-1)
            [signal fields]: Boolean for each signal type
            entry_price: Entry price
            stop_price: Stop loss price
            target_price: Profit target
            forecast_horizon_days: How far into future is this?
        
        Returns:
            Confirmation dict
        """
        prediction = {
            "id": prediction_id,
            "direction": direction,
            "confluence_score": confluence_score,
            "signals": {
                "geometry":    geometry_signal,
                "time":        time_signal,
                "structure":   structure_signal,
                "momentum":    momentum_signal,
                "gann":        gann_signal,
                "ict":         ict_signal,
                "confluence":  confluence_signal,
            },
            "entry_price": entry_price,
            "stop_price": stop_price,
            "target_price": target_price,
            "forecast_horizon_days": forecast_horizon_days,
            "prediction_timestamp": int(time.time()),
            "accuracy": None,  # Will be filled in when outcome recorded
            "features": dict(features or {}),
        }
        
        # Upsert: if a prediction with this ID already exists (e.g. re-run batch),
        # replace it in-place so record_outcome() always uses the latest signals.
        existing_idx = next(
            (i for i, p in enumerate(self.predictions) if p["id"] == prediction_id),
            None,
        )
        if existing_idx is not None:
            self.predictions[existing_idx] = prediction
        else:
            self.predictions.append(prediction)

        if self._tracker is not None:
            self._tracker.save_prediction(prediction)

        return {
            "status": "prediction_recorded",
            "prediction_id": prediction_id,
            "direction": direction,
            "confluence_score": confluence_score,
            "signals_aligned": sum([v for v in prediction["signals"].values()]),
        }
    
    def record_outcome(self, 
                      prediction_id: str,
                      realized_price: float,
                      outcome_direction: str,  # "UP", "DOWN", "SIDEWAYS"
                      actual_move_pips: float,
                      timeframe_reached: int) -> dict[str, Any]:
        """
        Record what actually happened - this is how the market teaches.
        
        Args:
            prediction_id: Matches a previous prediction
            realized_price: Where price actually went
            outcome_direction: "UP", "DOWN", or "SIDEWAYS"
            actual_move_pips: Actual pips moved
            timeframe_reached: How many bars until this outcome
        
        Returns:
            Learning update dict
        """
        # Find the matching prediction
        prediction = next((p for p in self.predictions if p["id"] == prediction_id), None)
        
        if not prediction:
            return {"status": "error", "message": f"Prediction {prediction_id} not found"}
        
        # Calculate accuracy
        predicted_direction = prediction["direction"]
        was_correct = False
        accuracy_score = 0
        
        if predicted_direction == "BUY" and outcome_direction == "UP":
            was_correct = True
            accuracy_score = 1.0
        elif predicted_direction == "SELL" and outcome_direction == "DOWN":
            was_correct = True
            accuracy_score = 1.0
        elif predicted_direction == "WAIT" and outcome_direction == "SIDEWAYS":
            was_correct = True
            accuracy_score = 1.0
        elif outcome_direction == "SIDEWAYS" and predicted_direction == "WAIT":
            # WAIT predicted on a sideways market — partial credit
            accuracy_score = 0.5
        else:
            # Directional prediction wrong (includes SIDEWAYS when we called BUY/SELL)
            accuracy_score = 0.0
        
        # Record the outcome
        outcome = {
            "prediction_id": prediction_id,
            "realized_price": realized_price,
            "outcome_direction": outcome_direction,
            "actual_move_pips": actual_move_pips,
            "timeframe_reached": timeframe_reached,
            "predicted_direction": predicted_direction,
            "was_correct": was_correct,
            "accuracy_score": accuracy_score,
        }

        # Upsert in-memory: if an outcome for this prediction already exists, update
        # it in-place.  Only skip _update_weights() when this engine instance has
        # ALREADY reflected that outcome ID in its weights (guards against
        # double-learning from the same live trade re-submission).
        existing_idx = next(
            (i for i, o in enumerate(self.realized_outcomes) if o.get("prediction_id") == prediction_id),
            None,
        )
        already_weighted = prediction_id in self._weighted_outcome_ids

        if existing_idx is not None:
            self.realized_outcomes[existing_idx] = outcome
        else:
            self.realized_outcomes.append(outcome)

        prediction["accuracy"] = accuracy_score

        if self._tracker is not None:
            self._tracker.save_outcome(outcome)
            self._tracker.save_prediction(prediction)  # persist accuracy field

        if already_weighted:
            # Same live trade submitted again — don't re-learn
            return {
                "status": "outcome_updated",
                "prediction_id": prediction_id,
                "accuracy_score": accuracy_score,
                "was_correct": was_correct,
                "learning_update": {},
            }

        # Learn from this outcome (first time this engine sees it)
        learning = self._update_weights(prediction, outcome)
        self._weighted_outcome_ids.add(prediction_id)

        return {
            "status": "outcome_recorded",
            "prediction_id": prediction_id,
            "accuracy_score": accuracy_score,
            "was_correct": was_correct,
            "learning_update": learning,
        }
    
    def _update_weights(self, prediction: dict, outcome: dict) -> dict[str, Any]:
        """
        Update confidence weights based on outcome.
        
        This is where the AI learns. If a signal was correct, increase its weight.
        If incorrect, decrease it.
        
        Returns:
            Learning summary
        """
        accuracy = outcome["accuracy_score"]
        signals = prediction["signals"]
        
        # Adjust weights based on this outcome
        weight_changes = {}
        
        for signal_type, signal_present in signals.items():
            if signal_present:
                # This signal was present in the prediction
                w = self.weights[signal_type]
                if outcome["was_correct"]:
                    # Prediction was right, increase this signal's weight
                    # Symmetric rate: 0.015 of remaining headroom to grow
                    boost = 0.015 * (1.0 - w)
                    self.weights[signal_type] = min(0.99, w + boost)
                    weight_changes[signal_type] = f"+{boost:.4f}"
                else:
                    # Prediction was wrong, decrease this signal's weight
                    # Symmetric rate: 0.015 of current weight; floor lowered to 0.20
                    # so weights can naturally fall to their statistical equilibrium
                    penalty = 0.015 * w
                    self.weights[signal_type] = max(0.20, w - penalty)
                    weight_changes[signal_type] = f"-{penalty:.4f}"
        
        if self._tracker is not None:
            self._tracker.save_weights(self.weights)

        return {
            "confidence_weights_updated": weight_changes,
            "new_weights": self.weights.copy(),
            "learning_message": f"Market taught us: accuracy={accuracy:.1%} | signals_to_trust={[k for k,v in signals.items() if v]}",
        }

    def save_weights(self) -> None:
        """Explicitly persist current weights to the tracker (no-op if no tracker)."""
        if self._tracker is not None:
            self._tracker.save_weights(self.weights)
    
    def get_model_calibration(self) -> dict[str, Any]:
        """
        Get current model calibration - how much we trust each factor.
        
        This is self-aware model tuning: the AI knows its own strengths/weaknesses.
        """
        total_accuracy = sum([o["accuracy_score"] for o in self.realized_outcomes]) / max(1, len(self.realized_outcomes))
        
        # Per-signal binary accuracy: fraction of outcomes where that signal was active AND correct.
        # Uses p["signals"].get(signal_type, False) so only predictions where the signal
        # was truly active (value=True) are counted, preventing flat accuracy when all
        # signals fire simultaneously.
        signal_accuracy = {}
        # Build a lookup from prediction_id → prediction dict for O(1) joins
        pred_by_id: dict = {p["id"]: p for p in self.predictions}
        for signal_type in self.weights.keys():
            correct = 0
            total = 0
            for o in self.realized_outcomes:
                pred = pred_by_id.get(o.get("prediction_id"))
                if pred is None:
                    continue
                if pred.get("signals", {}).get(signal_type, False):
                    total += 1
                    if o.get("was_correct", False):
                        correct += 1
            # Always include every signal key; None means signal never fired (no data yet)
            signal_accuracy[signal_type] = (correct / total) if total > 0 else None

        # Per-direction (BUY / SELL / WAIT) accuracy
        direction_accuracy: dict[str, float] = {}
        for direction in ("BUY", "SELL", "WAIT"):
            dir_correct = 0
            dir_total = 0
            for o in self.realized_outcomes:
                pred = pred_by_id.get(o.get("prediction_id"))
                if pred is None:
                    continue
                if pred.get("direction", "") == direction:
                    dir_total += 1
                    if o.get("was_correct", False):
                        dir_correct += 1
            if dir_total > 0:
                direction_accuracy[direction] = round(dir_correct / dir_total, 4)

        return {
            "overall_accuracy": total_accuracy,
            "total_predictions": len(self.predictions),
            "total_outcomes": len(self.realized_outcomes),
            "current_weights": self.weights.copy(),
            "signal_accuracy": signal_accuracy,
            "model_confidence": (
                "LEARNING"    if len(self.realized_outcomes) < 20  else
                "CALIBRATING" if len(self.realized_outcomes) < 100 else
                "HIGH"        if total_accuracy > 0.65             else
                "MEDIUM"      if total_accuracy > 0.55             else
                "LOW"
            ),
            "learning_message": f"Market has taught us {len(self.realized_outcomes)} lessons. Model is {total_accuracy:.1%} accurate. Trust weights have been calibrated.",
            "accuracy_trend": [round(o["accuracy_score"], 4) for o in self.realized_outcomes[-20:]],
            "direction_accuracy": direction_accuracy,
        }


@dataclass
class MathQuestionResult:
    """Result of a single mathematical check question"""
    question_id: str       # e.g. "MATH_01"
    question: str          # Human readable question
    answer: bool           # True = condition met, False = not met
    detail: str            # Numeric detail (e.g. "distance: 1.2 pips")
    confidence: float      # 0-1 confidence in the answer


class MathematicalQuestionChecker:
    """
    Answers the core mathematical validation questions for the 52-question framework.

    These questions verify that a trade setup respects mathematical laws:
    - Gann geometry (price:time harmony)
    - Fibonacci ratios (golden ratio proportions)
    - Physics laws (momentum, acceleration, gravity)
    - R:R viability (position sizing logic)

    Philosophy: "Every valid setup obeys mathematical law. No exceptions."
    """

    # Tolerance constants
    GANN_EXACT_PIPS = 2.0       # Within 2 pips = "on" a Gann angle
    FIB_TOLERANCE_PIPS = 3.0    # Within 3 pips = "at" a Fibonacci level
    SQ9_TOLERANCE_PIPS = 5.0    # Within 5 pips = near a Square-of-9 level
    MIN_RR = 1.5                # Minimum acceptable risk:reward ratio

    @staticmethod
    def check_all(
        pivot_price: float,
        pivot_bar: int,
        current_bar: int,
        current_price: float,
        recent_prices: list[float],
        swing_low: float,
        swing_high: float,
        entry_price: float,
        stop_price: float,
        target_price: float,
    ) -> list[MathQuestionResult]:
        """
        Run all mathematical check questions and return results.

        Args:
            pivot_price: Price at most recent swing pivot
            pivot_bar: Bar index of the pivot
            current_bar: Current bar index
            current_price: Latest close price
            recent_prices: List of recent close prices (5-20 bars)
            swing_low: Prior swing low
            swing_high: Prior swing high
            entry_price: Proposed trade entry
            stop_price: Proposed stop loss
            target_price: Proposed profit target

        Returns:
            List of MathQuestionResult, one per question
        """
        checker = MathematicalQuestionChecker
        results = []

        # ── GANN questions ────────────────────────────────────────────────────
        results.append(checker._q_gann_45_angle(pivot_price, pivot_bar, current_bar, current_price))
        results.append(checker._q_gann_cardinal_angle(pivot_price, pivot_bar, current_bar, current_price))
        results.append(checker._q_gann_price_time_aligned(pivot_price, pivot_bar, current_bar, current_price))
        results.append(checker._q_gann_square_of_9(current_price))

        # ── FIBONACCI questions ───────────────────────────────────────────────
        results.append(checker._q_fib_golden_ratio(swing_low, swing_high, current_price))
        results.append(checker._q_fib_38_2_level(swing_low, swing_high, current_price))
        results.append(checker._q_fib_confluence(swing_low, swing_high, current_price))
        results.append(checker._q_fib_extension_target(swing_low, swing_high, target_price))

        # ── PHYSICS / MOMENTUM questions ─────────────────────────────────────
        results.append(checker._q_momentum_positive(recent_prices))
        results.append(checker._q_velocity_sustainable(recent_prices))
        results.append(checker._q_acceleration_healthy(recent_prices))
        results.append(checker._q_gravity_well_proximity(swing_low, swing_high, current_price))

        # ── RISK / REWARD questions ───────────────────────────────────────────
        results.append(checker._q_rr_valid(entry_price, stop_price, target_price))
        results.append(checker._q_stop_structural(entry_price, stop_price, swing_low, swing_high))
        results.append(checker._q_move_proportional(swing_low, swing_high, entry_price, target_price))

        return results

    # ── GANN helpers ─────────────────────────────────────────────────────────

    @staticmethod
    def _q_gann_45_angle(pivot_price: float, pivot_bar: int, current_bar: int, current_price: float) -> MathQuestionResult:
        """MATH_01 — Is price within 2 pips of the Gann 45° (1:1) angle?"""
        bars = current_bar - pivot_bar
        price_at_45 = pivot_price + bars * 1.0  # 1 pip per bar upward
        distance = abs(current_price - price_at_45)
        answer = distance <= MathematicalQuestionChecker.GANN_EXACT_PIPS
        return MathQuestionResult(
            question_id="MATH_01",
            question="Is price on the Gann 45° angle (1:1 price:time ratio)?",
            answer=answer,
            detail=f"45° price={price_at_45:.2f} | actual={current_price:.2f} | gap={distance:.2f} pips",
            confidence=max(0.0, 1.0 - distance / 10.0),
        )

    @staticmethod
    def _q_gann_cardinal_angle(pivot_price: float, pivot_bar: int, current_bar: int, current_price: float) -> MathQuestionResult:
        """MATH_02 — Is price aligned with ANY Gann cardinal angle (45/90/135/180)?"""
        bars = current_bar - pivot_bar
        cardinal_prices = [
            pivot_price + bars * 0.5,   # 90°
            pivot_price + bars * 1.0,   # 45°
            pivot_price + bars * 2.0,   # 135°
        ]
        distances = [abs(current_price - p) for p in cardinal_prices]
        min_dist = min(distances)
        answer = min_dist <= MathematicalQuestionChecker.GANN_EXACT_PIPS
        return MathQuestionResult(
            question_id="MATH_02",
            question="Is price aligned with any Gann cardinal angle?",
            answer=answer,
            detail=f"Nearest cardinal distance={min_dist:.2f} pips",
            confidence=max(0.0, 1.0 - min_dist / 10.0),
        )

    @staticmethod
    def _q_gann_price_time_aligned(pivot_price: float, pivot_bar: int, current_bar: int, current_price: float) -> MathQuestionResult:
        """MATH_03 — Is price move proportional to time elapsed (Price=Time law)?"""
        bars = current_bar - pivot_bar
        price_move = abs(current_price - pivot_price)
        if bars == 0:
            return MathQuestionResult("MATH_03", "Is Price=Time law satisfied?", False, "bars_elapsed=0", 0.0)
        ratio = price_move / bars  # pips per bar
        # Good ratio: 0.5 to 3.0 pips per bar (within natural Gann range)
        answer = 0.5 <= ratio <= 3.0
        return MathQuestionResult(
            question_id="MATH_03",
            question="Is Price=Time relationship satisfied (move proportional to time)?",
            answer=answer,
            detail=f"pips_per_bar={ratio:.2f} (valid range: 0.5–3.0)",
            confidence=1.0 if answer else max(0.0, 1.0 - abs(ratio - 1.5) / 3.0),
        )

    @staticmethod
    def _q_gann_square_of_9(current_price: float) -> MathQuestionResult:
        """MATH_04 — Is current price near a Gann Square of 9 harmonic level?"""
        levels = MathematicalEngines.calculate_square_of_9_levels(current_price - 50, num_levels=10)
        distances = [abs(current_price - lvl) for lvl in levels]
        min_dist = min(distances)
        nearest = levels[distances.index(min_dist)]
        answer = min_dist <= MathematicalQuestionChecker.SQ9_TOLERANCE_PIPS
        return MathQuestionResult(
            question_id="MATH_04",
            question="Is price near a Gann Square of 9 harmonic level?",
            answer=answer,
            detail=f"nearest Sq9={nearest:.2f} | gap={min_dist:.2f} pips",
            confidence=max(0.0, 1.0 - min_dist / 20.0),
        )

    # ── FIBONACCI helpers ────────────────────────────────────────────────────

    @staticmethod
    def _q_fib_golden_ratio(swing_low: float, swing_high: float, current_price: float) -> MathQuestionResult:
        """MATH_05 — Is price at the 61.8% (golden ratio) retracement level?"""
        fibs = MathematicalEngines.calculate_fibonacci_levels(swing_low, swing_high)
        distance = abs(current_price - fibs.level_61_8)
        answer = distance <= MathematicalQuestionChecker.FIB_TOLERANCE_PIPS
        return MathQuestionResult(
            question_id="MATH_05",
            question="Is price at the 61.8% golden ratio retracement?",
            answer=answer,
            detail=f"61.8% level={fibs.level_61_8:.2f} | actual={current_price:.2f} | gap={distance:.2f} pips",
            confidence=max(0.0, 1.0 - distance / 15.0),
        )

    @staticmethod
    def _q_fib_38_2_level(swing_low: float, swing_high: float, current_price: float) -> MathQuestionResult:
        """MATH_06 — Is price at the 38.2% retracement level?"""
        fibs = MathematicalEngines.calculate_fibonacci_levels(swing_low, swing_high)
        distance = abs(current_price - fibs.level_38_2)
        answer = distance <= MathematicalQuestionChecker.FIB_TOLERANCE_PIPS
        return MathQuestionResult(
            question_id="MATH_06",
            question="Is price at the 38.2% retracement level?",
            answer=answer,
            detail=f"38.2% level={fibs.level_38_2:.2f} | actual={current_price:.2f} | gap={distance:.2f} pips",
            confidence=max(0.0, 1.0 - distance / 15.0),
        )

    @staticmethod
    def _q_fib_confluence(swing_low: float, swing_high: float, current_price: float) -> MathQuestionResult:
        """MATH_07 — Do multiple Fibonacci levels converge within 3 pips of current price?"""
        fibs = MathematicalEngines.calculate_fibonacci_levels(swing_low, swing_high)
        all_levels = [
            fibs.level_23_6, fibs.level_38_2, fibs.level_50_0,
            fibs.level_61_8, fibs.level_78_6, fibs.level_100,
        ]
        nearby = [lvl for lvl in all_levels if abs(current_price - lvl) <= MathematicalQuestionChecker.FIB_TOLERANCE_PIPS]
        answer = len(nearby) >= 2
        return MathQuestionResult(
            question_id="MATH_07",
            question="Do multiple Fibonacci levels converge near current price (confluence)?",
            answer=answer,
            detail=f"{len(nearby)} Fibonacci level(s) within {MathematicalQuestionChecker.FIB_TOLERANCE_PIPS} pips",
            confidence=min(1.0, len(nearby) / 3.0),
        )

    @staticmethod
    def _q_fib_extension_target(swing_low: float, swing_high: float, target_price: float) -> MathQuestionResult:
        """MATH_08 — Is the profit target at a Fibonacci extension (127.2% or 138.2%)?"""
        fibs = MathematicalEngines.calculate_fibonacci_levels(swing_low, swing_high)
        ext_levels = [fibs.level_127_2, fibs.level_138_2]
        distances = [abs(target_price - lvl) for lvl in ext_levels]
        min_dist = min(distances)
        nearest = ext_levels[distances.index(min_dist)]
        answer = min_dist <= MathematicalQuestionChecker.FIB_TOLERANCE_PIPS * 2
        return MathQuestionResult(
            question_id="MATH_08",
            question="Is target at a Fibonacci extension level (127.2% or 138.2%)?",
            answer=answer,
            detail=f"nearest extension={nearest:.2f} | target={target_price:.2f} | gap={min_dist:.2f} pips",
            confidence=max(0.0, 1.0 - min_dist / 20.0),
        )

    # ── PHYSICS helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _q_momentum_positive(recent_prices: list[float]) -> MathQuestionResult:
        """MATH_09 — Is momentum (net direction) positive and sustained?"""
        if len(recent_prices) < 3:
            return MathQuestionResult("MATH_09", "Is momentum positive?", False, "insufficient data", 0.0)
        velocity = MathematicalEngines.calculate_velocity(recent_prices)
        answer = velocity.current_velocity > 0.5 and velocity.momentum_status not in ("WEAK",)
        return MathQuestionResult(
            question_id="MATH_09",
            question="Is momentum positive and above minimum threshold?",
            answer=answer,
            detail=f"velocity={velocity.current_velocity:.2f} pips/bar | status={velocity.momentum_status}",
            confidence=min(1.0, abs(velocity.current_velocity) / 10.0),
        )

    @staticmethod
    def _q_velocity_sustainable(recent_prices: list[float]) -> MathQuestionResult:
        """MATH_10 — Does velocity have enough fuel remaining (≥3 bars)?"""
        if len(recent_prices) < 3:
            return MathQuestionResult("MATH_10", "Is velocity sustainable?", False, "insufficient data", 0.0)
        velocity = MathematicalEngines.calculate_velocity(recent_prices)
        answer = velocity.bars_fuel_remaining >= 3
        return MathQuestionResult(
            question_id="MATH_10",
            question="Is velocity sustainable (≥3 bars of fuel remaining)?",
            answer=answer,
            detail=f"fuel_remaining={velocity.bars_fuel_remaining} bars | warnings={velocity.warning_signs}",
            confidence=min(1.0, velocity.bars_fuel_remaining / 8.0),
        )

    @staticmethod
    def _q_acceleration_healthy(recent_prices: list[float]) -> MathQuestionResult:
        """MATH_11 — Is acceleration non-negative (not decelerating into exhaustion)?"""
        if len(recent_prices) < 6:
            return MathQuestionResult("MATH_11", "Is acceleration healthy?", False, "insufficient data", 0.0)
        velocity = MathematicalEngines.calculate_velocity(recent_prices)
        answer = velocity.acceleration >= -0.3  # Allow slight slowdown
        return MathQuestionResult(
            question_id="MATH_11",
            question="Is acceleration healthy (not entering exhaustion zone)?",
            answer=answer,
            detail=f"acceleration={velocity.acceleration:.2f} pips/bar² (threshold: ≥-0.3)",
            confidence=max(0.0, (velocity.acceleration + 1.0) / 2.0),
        )

    @staticmethod
    def _q_gravity_well_proximity(swing_low: float, swing_high: float, current_price: float) -> MathQuestionResult:
        """MATH_12 — Is price within 10 pips of a strong gravity well (S/R)?"""
        gravity = MathematicalEngines.calculate_gravity_wells(swing_low, swing_high, current_price, recent_touches=3)
        distance = gravity["primary_distance_pips"]
        answer = distance <= 10.0
        return MathQuestionResult(
            question_id="MATH_12",
            question="Is price near a gravity well (S/R zone acting as magnet)?",
            answer=answer,
            detail=f"primary_well={gravity['primary_gravity_well']} | distance={distance:.2f} pips",
            confidence=max(0.0, 1.0 - distance / 20.0),
        )

    # ── RISK / REWARD helpers ────────────────────────────────────────────────

    @staticmethod
    def _q_rr_valid(entry_price: float, stop_price: float, target_price: float) -> MathQuestionResult:
        """MATH_13 — Is risk:reward ≥ 1.5:1?"""
        risk = abs(entry_price - stop_price)
        reward = abs(target_price - entry_price)
        if risk == 0:
            return MathQuestionResult("MATH_13", "Is R:R ≥ 1.5?", False, "risk=0 (invalid stop)", 0.0)
        rr = reward / risk
        answer = rr >= MathematicalQuestionChecker.MIN_RR
        return MathQuestionResult(
            question_id="MATH_13",
            question="Is risk:reward ratio ≥ 1.5:1?",
            answer=answer,
            detail=f"R:R={rr:.2f} | risk={risk:.1f} pips | reward={reward:.1f} pips",
            confidence=min(1.0, rr / 3.0),
        )

    @staticmethod
    def _q_stop_structural(entry_price: float, stop_price: float,
                            swing_low: float, swing_high: float) -> MathQuestionResult:
        """MATH_14 — Is the stop loss placed beyond a structural swing point (not arbitrary)?"""
        risk_pips = abs(entry_price - stop_price)
        # Stop is structural if it's placed near swing_low (for longs) or swing_high (for shorts)
        near_swing_low = abs(stop_price - swing_low) <= 5.0
        near_swing_high = abs(stop_price - swing_high) <= 5.0
        answer = (near_swing_low or near_swing_high) and risk_pips >= 3.0
        return MathQuestionResult(
            question_id="MATH_14",
            question="Is stop placed at a structural level (beyond swing low/high)?",
            answer=answer,
            detail=f"stop={stop_price:.2f} | swing_low={swing_low:.2f} | swing_high={swing_high:.2f} | risk={risk_pips:.1f} pips",
            confidence=0.9 if answer else 0.3,
        )

    @staticmethod
    def _q_move_proportional(swing_low: float, swing_high: float,
                              entry_price: float, target_price: float) -> MathQuestionResult:
        """MATH_15 — Is the projected move proportional to prior swing range (not overextended)?"""
        prior_range = abs(swing_high - swing_low)
        projected_move = abs(target_price - entry_price)
        if prior_range == 0:
            return MathQuestionResult("MATH_15", "Is projected move proportional?", False, "prior_range=0", 0.0)
        ratio = projected_move / prior_range
        # Acceptable: 0.38 (38.2% of prior range) to 1.618 (golden ratio extension)
        answer = 0.38 <= ratio <= 1.618
        return MathQuestionResult(
            question_id="MATH_15",
            question="Is projected move proportional to prior swing (0.38–1.618× range)?",
            answer=answer,
            detail=f"projected={projected_move:.1f} pips | prior_range={prior_range:.1f} pips | ratio={ratio:.2f}",
            confidence=1.0 if answer else max(0.0, 1.0 - abs(ratio - 1.0)),
        )

    @classmethod
    def score_setup(cls, results: list[MathQuestionResult]) -> dict:
        """
        Summarise the 15-question mathematical check into a score and verdict.

        Returns:
            Dict with score (0-15), pct_pass, verdict, and failed question IDs.
        """
        passed = [r for r in results if r.answer]
        failed = [r for r in results if not r.answer]
        score = len(passed)
        pct = score / len(results) if results else 0

        if pct >= 0.80:
            verdict = "STRONG_MATH"
        elif pct >= 0.60:
            verdict = "ACCEPTABLE_MATH"
        elif pct >= 0.40:
            verdict = "WEAK_MATH"
        else:
            verdict = "FAIL_MATH"

        return {
            "score": score,
            "total": len(results),
            "pct_pass": round(pct, 3),
            "verdict": verdict,
            "passed_ids": [r.question_id for r in passed],
            "failed_ids": [r.question_id for r in failed],
        }


# Example usage and testing
if __name__ == "__main__":
    print("=== Mathematical Engines for Trading Framework ===\n")
    
    # Test 1: Gann Angles
    print("1. GANN ANGLE CALCULATION")
    angles = MathematicalEngines.calculate_gann_angles(2450, pivot_bar=0, current_bar=10)
    for angle in angles[:2]:
        print(f"  {angle}")
    
    # Test 2: Velocity Analysis
    print("\n2. VELOCITY & MOMENTUM ANALYSIS")
    prices = [2450, 2452, 2455, 2458, 2460, 2461, 2461, 2460]  # Simulated price movement
    velocity = MathematicalEngines.calculate_velocity(prices)
    print(f"  {velocity}")
    
    # Test 3: Fibonacci Levels
    print("\n3. FIBONACCI RETRACEMENT LEVELS")
    fibs = MathematicalEngines.calculate_fibonacci_levels(2420, 2480)
    print(f"  38.2% level: {fibs.level_38_2:.2f}")
    print(f"  61.8% level: {fibs.level_61_8:.2f}")
    
    # Test 4: Confluence Score
    print("\n4. CONFLUENCE SCORING")
    score = MathematicalEngines.calculate_confluence_score(
        geometry_valid=True,
        time_valid=True,
        structure_valid=True,
        momentum_strong=True,
        gann_aligned=True,
        ict_signal=False,
    )
    print(f"  {score}")
    
    # Test 5: Learning Feedback Engine
    print("\n5. LEARNING FEEDBACK (Market Teaching AI)")
    learner = LearningFeedbackEngine()
    
    # Record a prediction
    learner.record_prediction(
        prediction_id="pred_001",
        direction="BUY",
        confluence_score=0.78,
        geometry_signal=True,
        time_signal=True,
        structure_signal=True,
        momentum_signal=True,
        gann_signal=False,
        ict_signal=True,
        entry_price=2465,
        stop_price=2458,
        target_price=2475,
        forecast_horizon_days=1,
    )
    print("  Prediction recorded: BUY at 2465")
    
    # Record what actually happened
    outcome = learner.record_outcome(
        prediction_id="pred_001",
        realized_price=2475,
        outcome_direction="UP",
        actual_move_pips=10,
        timeframe_reached=5,
    )
    print(f"  Outcome recorded: Market went UP (+10 pips)")
    print(f"  Learning: {outcome['learning_update']['learning_message']}")
    
    # Check calibration
    calibration = learner.get_model_calibration()
    print(f"\n  Model Calibration:")
    print(f"    Accuracy: {calibration['overall_accuracy']:.1%}")
    print(f"    Confidence: {calibration['model_confidence']}")
    print(f"    Updated weights: {calibration['current_weights']}")

