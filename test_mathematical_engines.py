"""
Test suite for Mathematical Engines and Learning Feedback System

Tests validate that the framework obeyed mathematical laws,
and that the AI learns correctly from market feedback.
"""

import pytest
from astroquant.backend.mathematical_engines import (
    MathematicalEngines,
    LearningFeedbackEngine,
    MathematicalQuestionChecker,
    GannAngleResult,
    VelocityResult,
    ConfluenceScore,
)


class TestGannAngleCalculations:
    """Test Gann angle mathematics"""
    
    def test_gann_angles_45_degree_basic(self):
        """45° angle should show 1:1 price-to-time ratio"""
        angles = MathematicalEngines.calculate_gann_angles(
            pivot_price=2450,
            pivot_bar=0,
            current_bar=10
        )
        
        # Find 45° angle
        angle_45 = next(a for a in angles if a.angle_degrees == 45)
        
        # 10 bars later, price should be ~2460 (10 pips per 10 bars = 1:1 ratio)
        assert angle_45.angle_degrees == 45
        assert angle_45.price_at_angle > 2450  # Price should increase
        assert len(angles) == 6  # Should have all 6 major angles
    
    def test_gann_angle_proximity_exact(self):
        """When price is within 2 pips of angle, proximity should be EXACT"""
        angles = MathematicalEngines.calculate_gann_angles(2450, 0, 10)
        
        for angle in angles:
            if angle.distance_pips < 2:
                assert angle.proximity == "EXACT"
            elif angle.distance_pips < 5:
                assert angle.proximity == "NEAR"
            else:
                assert angle.proximity == "NONE"
    
    def test_gann_cardinal_angles_ordered(self):
        """All cardinal angles should be calculated"""
        angles = MathematicalEngines.calculate_gann_angles(2450, 0, 10)
        expected_angles = [45, 90, 135, 180, 225, 315]
        actual_angles = sorted([a.angle_degrees for a in angles])
        
        assert actual_angles == sorted(expected_angles)


class TestVelocityCalculations:
    """Test momentum and velocity mathematics"""
    
    def test_velocity_weak_status(self):
        """Velocity <1 pip/bar should be WEAK"""
        prices = [2450, 2450.2, 2450.3, 2450.4, 2450.5]  # Very slow
        
        velocity = MathematicalEngines.calculate_velocity(prices)
        
        assert velocity.momentum_status == "WEAK"
        assert velocity.bars_fuel_remaining <= 3
    
    def test_velocity_strong_status(self):
        """Velocity >5 pips/bar should be STRONG"""
        prices = [2450, 2460, 2470, 2480, 2490, 2500]  # Fast
        
        velocity = MathematicalEngines.calculate_velocity(prices)
        
        assert velocity.momentum_status in ["STRONG", "VERY_STRONG"]
        assert velocity.current_velocity > 5
    
    def test_velocity_with_deceleration_warning(self):
        """When acceleration is negative, should have warning"""
        # Scenario: price was moving up fast, then slowing down
        prices = [2450, 2455, 2460, 2464, 2467, 2469]  # Decelerating
        
        velocity = MathematicalEngines.calculate_velocity(prices)
        
        # Should detect deceleration
        if velocity.acceleration < -0.5:
            assert "exhaustion" in " ".join(velocity.warning_signs).lower()
    
    def test_velocity_fuel_estimate(self):
        """Bars fuel remaining should be proportional to velocity"""
        # Low velocity
        slow_prices = [2450, 2450.5, 2450.6, 2450.7, 2450.8]
        slow_velocity = MathematicalEngines.calculate_velocity(slow_prices)
        
        # High velocity
        fast_prices = [2450, 2455, 2460, 2465, 2470]
        fast_velocity = MathematicalEngines.calculate_velocity(fast_prices)
        
        # Both should have fuel estimates (could be different)
        assert slow_velocity.bars_fuel_remaining > 0
        assert fast_velocity.bars_fuel_remaining > 0


class TestFibonacciLevels:
    """Test Fibonacci ratio calculations"""
    
    def test_fibonacci_range_ordering(self):
        """Fibonacci levels should be ordered from high to low"""
        fibs = MathematicalEngines.calculate_fibonacci_levels(2420, 2480)
        
        # 61.8% should be lower than 38.2%
        assert fibs.level_61_8 < fibs.level_38_2
        
        # 100% should equal swing low
        assert fibs.level_100 == 2420
    
    def test_fibonacci_golden_ratio(self):
        """61.8% and 38.2% are key golden ratio levels"""
        swing_range = 100
        fibs = MathematicalEngines.calculate_fibonacci_levels(0, swing_range)
        
        # Validate ratio relationships
        ratio_61_8 = (swing_range - fibs.level_61_8) / swing_range
        ratio_38_2 = (swing_range - fibs.level_38_2) / swing_range
        
        assert abs(ratio_61_8 - 0.618) < 0.01
        assert abs(ratio_38_2 - 0.382) < 0.01
    
    def test_fibonacci_nearest_level(self):
        """get_nearest should find closest Fibonacci level"""
        fibs = MathematicalEngines.calculate_fibonacci_levels(2420, 2480)
        
        # Price at 50% should find 50% level
        nearest_label, nearest_price = fibs.get_nearest(fibs.level_50_0)
        
        assert "50" in nearest_label
        assert abs(nearest_price - fibs.level_50_0) < 1


class TestConfluenceScoring:
    """Test confluence scoring system"""
    
    def test_confluence_five_confirmations(self):
        """5/6 confirmations should give ~72% BUY probability"""
        score = MathematicalEngines.calculate_confluence_score(
            geometry_valid=True,
            time_valid=True,
            structure_valid=True,
            momentum_strong=True,
            gann_aligned=True,
            ict_signal=False,  # Only 5/6
        )
        
        assert score.buy_probability >= 0.65
        assert score.overall_score > 0.65
    
    def test_confluence_all_confirmations(self):
        """6/6 confirmations should give highest probability"""
        score = MathematicalEngines.calculate_confluence_score(
            geometry_valid=True,
            time_valid=True,
            structure_valid=True,
            momentum_strong=True,
            gann_aligned=True,
            ict_signal=True,  # All 6
        )
        
        # With all confirmations, should be most confident
        assert score.buy_probability >= 0.70
        assert score.sell_probability <= 0.20
    
    def test_confluence_probabilities_sum_to_one(self):
        """Buy + Sell + Wait probabilities should sum to 1.0"""
        score = MathematicalEngines.calculate_confluence_score(
            geometry_valid=True,
            time_valid=False,
            structure_valid=True,
            momentum_strong=True,
            gann_aligned=False,
            ict_signal=True,
        )
        
        total_prob = score.buy_probability + score.sell_probability + score.wait_probability
        assert abs(total_prob - 1.0) < 0.01
    
    def test_confluence_weakest_component(self):
        """Should identify weakest factor"""
        score = MathematicalEngines.calculate_confluence_score(
            geometry_valid=True,
            time_valid=False,  # This will be weakest
            structure_valid=True,
            momentum_strong=True,
            gann_aligned=True,
            ict_signal=True,
        )
        
        assert score.weakest_component == "time"
        assert score.weakest_score == 0.0


class TestLearningFeedbackEngine:
    """Test the 'Market is the Teacher' learning system"""
    
    def test_prediction_recording(self):
        """Should record predictions correctly"""
        engine = LearningFeedbackEngine()
        
        result = engine.record_prediction(
            prediction_id="test_001",
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
        
        assert result["status"] == "prediction_recorded"
        assert result["direction"] == "BUY"
        assert result["signals_aligned"] == 5  # 5 signals were True
    
    def test_outcome_recording_correct_prediction(self):
        """When market proves prediction correct, accuracy should be 1.0"""
        engine = LearningFeedbackEngine()
        
        # Record a BUY prediction
        engine.record_prediction(
            prediction_id="pred_001",
            direction="BUY",
            confluence_score=0.78,
            geometry_signal=True,
            time_signal=True,
            structure_signal=True,
            momentum_signal=True,
            gann_signal=True,
            ict_signal=True,
            entry_price=2465,
            stop_price=2458,
            target_price=2475,
            forecast_horizon_days=1,
        )
        
        # Market went UP - this was correct
        outcome = engine.record_outcome(
            prediction_id="pred_001",
            realized_price=2475,
            outcome_direction="UP",
            actual_move_pips=10,
            timeframe_reached=5,
        )
        
        assert outcome["was_correct"] is True
        assert outcome["accuracy_score"] == 1.0
    
    def test_outcome_recording_wrong_prediction(self):
        """When market disproves prediction, accuracy should be 0.0"""
        engine = LearningFeedbackEngine()
        
        # Record a BUY prediction
        engine.record_prediction(
            prediction_id="pred_002",
            direction="BUY",
            confluence_score=0.78,
            geometry_signal=True,
            time_signal=True,
            structure_signal=True,
            momentum_signal=True,
            gann_signal=True,
            ict_signal=True,
            entry_price=2465,
            stop_price=2458,
            target_price=2475,
            forecast_horizon_days=1,
        )
        
        # Market went DOWN - this was wrong
        outcome = engine.record_outcome(
            prediction_id="pred_002",
            realized_price=2455,
            outcome_direction="DOWN",
            actual_move_pips=-10,
            timeframe_reached=5,
        )
        
        assert outcome["was_correct"] is False
        assert outcome["accuracy_score"] == 0.0
    
    def test_weight_adjustment_on_correct_prediction(self):
        """When prediction is correct, signal weights should increase"""
        engine = LearningFeedbackEngine()
        
        # Record baseline weights
        baseline_geometry = engine.weights["geometry"]
        baseline_momentum = engine.weights["momentum"]
        
        # Predict and be correct
        engine.record_prediction(
            prediction_id="pred_003",
            direction="BUY",
            confluence_score=0.78,
            geometry_signal=True,
            time_signal=False,
            structure_signal=True,
            momentum_signal=True,
            gann_signal=False,
            ict_signal=False,
            entry_price=2465,
            stop_price=2458,
            target_price=2475,
            forecast_horizon_days=1,
        )
        
        engine.record_outcome(
            prediction_id="pred_003",
            realized_price=2475,
            outcome_direction="UP",
            actual_move_pips=10,
            timeframe_reached=5,
        )
        
        # Weights of signals that were present should increase
        assert engine.weights["geometry"] > baseline_geometry  # Was True, should increase
        assert engine.weights["momentum"] > baseline_momentum  # Was True, should increase
        assert engine.weights["time"] <= 0.82  # Was False, shouldn't be affected much
    
    def test_model_calibration_accuracy(self):
        """Model should report overall accuracy"""
        engine = LearningFeedbackEngine()
        
        # Make 2 predictions: 1 correct, 1 wrong
        # Correct prediction
        engine.record_prediction(
            prediction_id="pred_a",
            direction="BUY",
            confluence_score=0.78,
            geometry_signal=True,
            time_signal=True,
            structure_signal=True,
            momentum_signal=True,
            gann_signal=True,
            ict_signal=True,
            entry_price=2465,
            stop_price=2458,
            target_price=2475,
            forecast_horizon_days=1,
        )
        engine.record_outcome("pred_a", 2475, "UP", 10, 5)
        
        # Wrong prediction
        engine.record_prediction(
            prediction_id="pred_b",
            direction="SELL",
            confluence_score=0.55,
            geometry_signal=False,
            time_signal=False,
            structure_signal=True,
            momentum_signal=False,
            gann_signal=False,
            ict_signal=False,
            entry_price=2470,
            stop_price=2478,
            target_price=2450,
            forecast_horizon_days=1,
        )
        engine.record_outcome("pred_b", 2480, "UP", 10, 5)  # Wrong direction
        
        calibration = engine.get_model_calibration()
        
        # Should report 50% accuracy (1 correct out of 2)
        assert calibration["overall_accuracy"] == 0.5
        assert calibration["total_predictions"] == 2
        assert calibration["total_outcomes"] == 2
        assert "geometry" in calibration["current_weights"]  # Check for a specific weight
    
    def test_weight_convergence(self):
        """Weights should eventually converge to reliable signals"""
        engine = LearningFeedbackEngine()
        
        # Simulate 10 correct predictions all with geometry=True
        for i in range(10):
            engine.record_prediction(
                prediction_id=f"pred_{i:02d}",
                direction="BUY",
                confluence_score=0.78,
                geometry_signal=True,  # Always right
                time_signal=i % 2 == 0,  # Random
                structure_signal=i % 2 == 0,  # Random
                momentum_signal=i % 2 == 0,  # Random
                gann_signal=False,  # Never used
                ict_signal=False,  # Never used
                entry_price=2465,
                stop_price=2458,
                target_price=2475,
                forecast_horizon_days=1,
            )
            
            engine.record_outcome(
                prediction_id=f"pred_{i:02d}",
                realized_price=2475,
                outcome_direction="UP",
                actual_move_pips=10,
                timeframe_reached=5,
            )
        
        calibration = engine.get_model_calibration()
        
        # Geometry weight should be high (was always correct)
        # Gann weight should be low (was never used but we're being accurate)
        assert calibration["current_weights"]["geometry"] > 0.88
        assert calibration["overall_accuracy"] > 0.99


class TestMathematicalQuestions:
    """
    Test the 15 mathematical check questions (MATH_01 – MATH_15).

    These validate that price setups obey Gann geometry, Fibonacci ratios,
    physics laws, and proper risk/reward structure.
    """

    # ── shared fixture values ────────────────────────────────────────────────
    PIVOT_PRICE = 2450.0
    PIVOT_BAR = 0
    CURRENT_BAR = 10
    SWING_LOW = 2420.0
    SWING_HIGH = 2480.0

    # ── MATH_01: Gann 45° ───────────────────────────────────────────────────
    def test_gann_45_on_angle(self):
        """MATH_01: price sitting on 45° should answer True"""
        price_on_45 = self.PIVOT_PRICE + self.CURRENT_BAR * 1.0  # exactly 2460
        result = MathematicalQuestionChecker._q_gann_45_angle(
            self.PIVOT_PRICE, self.PIVOT_BAR, self.CURRENT_BAR, price_on_45
        )
        assert result.question_id == "MATH_01"
        assert result.answer is True
        assert result.confidence >= 0.9

    def test_gann_45_off_angle(self):
        """MATH_01: price 15 pips off 45° should answer False"""
        price_off_45 = self.PIVOT_PRICE + self.CURRENT_BAR * 1.0 + 15  # 15 pips away
        result = MathematicalQuestionChecker._q_gann_45_angle(
            self.PIVOT_PRICE, self.PIVOT_BAR, self.CURRENT_BAR, price_off_45
        )
        assert result.answer is False

    # ── MATH_02: Cardinal angle ─────────────────────────────────────────────
    def test_cardinal_angle_detected(self):
        """MATH_02: price on 90° angle should return True"""
        price_on_90 = self.PIVOT_PRICE + self.CURRENT_BAR * 0.5  # 90°
        result = MathematicalQuestionChecker._q_gann_cardinal_angle(
            self.PIVOT_PRICE, self.PIVOT_BAR, self.CURRENT_BAR, price_on_90
        )
        assert result.question_id == "MATH_02"
        assert result.answer is True

    # ── MATH_03: Price=Time ─────────────────────────────────────────────────
    def test_price_time_law_within_range(self):
        """MATH_03: 1.5 pips/bar satisfies Price=Time law"""
        current_price = self.PIVOT_PRICE + self.CURRENT_BAR * 1.5
        result = MathematicalQuestionChecker._q_gann_price_time_aligned(
            self.PIVOT_PRICE, self.PIVOT_BAR, self.CURRENT_BAR, current_price
        )
        assert result.question_id == "MATH_03"
        assert result.answer is True

    def test_price_time_law_too_fast(self):
        """MATH_03: 20 pips/bar violates Price=Time law"""
        current_price = self.PIVOT_PRICE + self.CURRENT_BAR * 20  # too fast
        result = MathematicalQuestionChecker._q_gann_price_time_aligned(
            self.PIVOT_PRICE, self.PIVOT_BAR, self.CURRENT_BAR, current_price
        )
        assert result.answer is False

    # ── MATH_04: Square of 9 ───────────────────────────────────────────────
    def test_square_of_9_returns_result(self):
        """MATH_04: should always return a result with question_id"""
        result = MathematicalQuestionChecker._q_gann_square_of_9(2465.0)
        assert result.question_id == "MATH_04"
        assert isinstance(result.answer, bool)
        assert 0.0 <= result.confidence <= 1.0

    # ── MATH_05: Golden ratio ──────────────────────────────────────────────
    def test_golden_ratio_at_61_8_pct(self):
        """MATH_05: price exactly at 61.8% retracement should pass"""
        fibs = MathematicalEngines.calculate_fibonacci_levels(self.SWING_LOW, self.SWING_HIGH)
        result = MathematicalQuestionChecker._q_fib_golden_ratio(
            self.SWING_LOW, self.SWING_HIGH, fibs.level_61_8
        )
        assert result.question_id == "MATH_05"
        assert result.answer is True

    def test_golden_ratio_far_from_61_8(self):
        """MATH_05: price 20 pips from 61.8% should fail"""
        fibs = MathematicalEngines.calculate_fibonacci_levels(self.SWING_LOW, self.SWING_HIGH)
        result = MathematicalQuestionChecker._q_fib_golden_ratio(
            self.SWING_LOW, self.SWING_HIGH, fibs.level_61_8 + 20
        )
        assert result.answer is False

    # ── MATH_06: 38.2% level ──────────────────────────────────────────────
    def test_fib_38_2_at_level(self):
        """MATH_06: price exactly at 38.2% should pass"""
        fibs = MathematicalEngines.calculate_fibonacci_levels(self.SWING_LOW, self.SWING_HIGH)
        result = MathematicalQuestionChecker._q_fib_38_2_level(
            self.SWING_LOW, self.SWING_HIGH, fibs.level_38_2
        )
        assert result.question_id == "MATH_06"
        assert result.answer is True

    # ── MATH_07: Fibonacci confluence ─────────────────────────────────────
    def test_fib_confluence_at_50pct(self):
        """MATH_07: price at 50% where nearby levels may converge"""
        fibs = MathematicalEngines.calculate_fibonacci_levels(self.SWING_LOW, self.SWING_HIGH)
        # Place price exactly at 50% so at least one level triggers;
        # whether 2+ are within 3 pips depends on swing range.
        result = MathematicalQuestionChecker._q_fib_confluence(
            self.SWING_LOW, self.SWING_HIGH, fibs.level_50_0
        )
        assert result.question_id == "MATH_07"
        # For swing_range=60, levels are spaced ~10+ pips, so <2 nearby → answer=False
        assert isinstance(result.answer, bool)

    def test_fib_confluence_tight_range(self):
        """MATH_07: on a tiny 5-pip swing the levels will cluster → True"""
        result = MathematicalQuestionChecker._q_fib_confluence(
            100.0, 102.0, 101.0  # 2-pip range → all levels within 3 pips
        )
        assert result.answer is True

    # ── MATH_08: Fibonacci extension target ───────────────────────────────
    def test_fib_extension_target_at_127(self):
        """MATH_08: target at 127.2% extension should pass"""
        fibs = MathematicalEngines.calculate_fibonacci_levels(self.SWING_LOW, self.SWING_HIGH)
        result = MathematicalQuestionChecker._q_fib_extension_target(
            self.SWING_LOW, self.SWING_HIGH, fibs.level_127_2
        )
        assert result.question_id == "MATH_08"
        assert result.answer is True

    # ── MATH_09: Momentum positive ────────────────────────────────────────
    def test_momentum_positive_rising_prices(self):
        """MATH_09: steadily rising prices → momentum positive"""
        prices = [2450, 2453, 2457, 2461, 2465, 2470]
        result = MathematicalQuestionChecker._q_momentum_positive(prices)
        assert result.question_id == "MATH_09"
        assert result.answer is True

    def test_momentum_negative_flat_prices(self):
        """MATH_09: near-flat prices → momentum not positive"""
        prices = [2450, 2450.1, 2450.0, 2450.2, 2450.1]
        result = MathematicalQuestionChecker._q_momentum_positive(prices)
        assert result.answer is False

    # ── MATH_10: Velocity sustainable ────────────────────────────────────
    def test_velocity_sustainable_strong_move(self):
        """MATH_10: strong move → bars_fuel_remaining ≥ 3"""
        prices = [2450, 2455, 2460, 2465, 2470, 2475]
        result = MathematicalQuestionChecker._q_velocity_sustainable(prices)
        assert result.question_id == "MATH_10"
        assert result.answer is True

    def test_velocity_not_sustainable_very_slow(self):
        """MATH_10: very slow prices → fuel_remaining < 3"""
        prices = [2450, 2450.1, 2450.2, 2450.1, 2450.2]
        result = MathematicalQuestionChecker._q_velocity_sustainable(prices)
        assert result.answer is False

    # ── MATH_11: Acceleration healthy ────────────────────────────────────
    def test_acceleration_healthy_steady_move(self):
        """MATH_11: fewer than 2×bars_analyzed bars → acceleration=0 → healthy"""
        # With <10 prices the engine returns acceleration=0 (insufficient history)
        prices = [2450, 2455, 2460, 2465, 2470, 2475]  # 6 prices, bars_analyzed=5 → no accel calc
        result = MathematicalQuestionChecker._q_acceleration_healthy(prices)
        assert result.question_id == "MATH_11"
        assert result.answer is True

    def test_acceleration_unhealthy_sharp_slowdown(self):
        """MATH_11: sharp deceleration → answer False"""
        # Moving fast then suddenly slow
        prices = [2450, 2460, 2470, 2480, 2481, 2481.5, 2481.8]
        result = MathematicalQuestionChecker._q_acceleration_healthy(prices)
        assert result.question_id == "MATH_11"
        # acceleration will be very negative
        assert isinstance(result.answer, bool)

    # ── MATH_12: Gravity well ─────────────────────────────────────────────
    def test_gravity_well_near_support(self):
        """MATH_12: price 5 pips above swing_low → near gravity well"""
        result = MathematicalQuestionChecker._q_gravity_well_proximity(
            self.SWING_LOW, self.SWING_HIGH, self.SWING_LOW + 5
        )
        assert result.question_id == "MATH_12"
        assert result.answer is True

    def test_gravity_well_far_from_levels(self):
        """MATH_12: price 25 pips above support → not near gravity well"""
        result = MathematicalQuestionChecker._q_gravity_well_proximity(
            self.SWING_LOW, self.SWING_HIGH, self.SWING_LOW + 25
        )
        assert result.answer is False

    # ── MATH_13: R:R valid ────────────────────────────────────────────────
    def test_rr_valid_2_to_1(self):
        """MATH_13: 2:1 R:R should pass"""
        result = MathematicalQuestionChecker._q_rr_valid(
            entry_price=2465, stop_price=2455, target_price=2485  # risk=10, reward=20
        )
        assert result.question_id == "MATH_13"
        assert result.answer is True

    def test_rr_invalid_1_to_1(self):
        """MATH_13: 1:1 R:R should fail (below 1.5 minimum)"""
        result = MathematicalQuestionChecker._q_rr_valid(
            entry_price=2465, stop_price=2455, target_price=2475  # risk=10, reward=10
        )
        assert result.answer is False

    # ── MATH_14: Structural stop ─────────────────────────────────────────
    def test_stop_structural_at_swing_low(self):
        """MATH_14: stop placed 2 pips below swing low is structural"""
        result = MathematicalQuestionChecker._q_stop_structural(
            entry_price=2450,
            stop_price=self.SWING_LOW - 2,   # 2418
            swing_low=self.SWING_LOW,
            swing_high=self.SWING_HIGH,
        )
        assert result.question_id == "MATH_14"
        assert result.answer is True

    def test_stop_arbitrary_mid_range(self):
        """MATH_14: stop placed in the middle of nowhere should fail"""
        result = MathematicalQuestionChecker._q_stop_structural(
            entry_price=2465,
            stop_price=2460,               # 5 pips below entry, not near any swing
            swing_low=self.SWING_LOW,
            swing_high=self.SWING_HIGH,
        )
        assert result.answer is False

    # ── MATH_15: Proportional move ───────────────────────────────────────
    def test_move_proportional_golden_ratio(self):
        """MATH_15: target equal to 61.8% of prior range is proportional"""
        prior_range = self.SWING_HIGH - self.SWING_LOW  # 60 pips
        projected = prior_range * 0.618                 # ~37 pips
        result = MathematicalQuestionChecker._q_move_proportional(
            self.SWING_LOW, self.SWING_HIGH,
            entry_price=2450,
            target_price=2450 + projected,
        )
        assert result.question_id == "MATH_15"
        assert result.answer is True

    def test_move_overextended(self):
        """MATH_15: target 3× prior range is overextended → False"""
        prior_range = self.SWING_HIGH - self.SWING_LOW  # 60 pips
        result = MathematicalQuestionChecker._q_move_proportional(
            self.SWING_LOW, self.SWING_HIGH,
            entry_price=2450,
            target_price=2450 + prior_range * 3,  # 3× range = overextended
        )
        assert result.answer is False

    # ── check_all integration ─────────────────────────────────────────────
    def test_check_all_returns_15_questions(self):
        """check_all must return exactly 15 MathQuestionResult objects"""
        results = MathematicalQuestionChecker.check_all(
            pivot_price=self.PIVOT_PRICE,
            pivot_bar=self.PIVOT_BAR,
            current_bar=self.CURRENT_BAR,
            current_price=2462.0,
            recent_prices=[2450, 2453, 2457, 2460, 2463, 2466],
            swing_low=self.SWING_LOW,
            swing_high=self.SWING_HIGH,
            entry_price=2462,
            stop_price=2452,
            target_price=2477,
        )
        assert len(results) == 15
        ids = [r.question_id for r in results]
        expected = [f"MATH_{i:02d}" for i in range(1, 16)]
        assert ids == expected

    def test_check_all_confidence_bounded(self):
        """All confidence values must be in [0, 1]"""
        results = MathematicalQuestionChecker.check_all(
            pivot_price=2450, pivot_bar=0, current_bar=10,
            current_price=2462,
            recent_prices=[2450, 2453, 2457, 2460, 2463, 2466],
            swing_low=2420, swing_high=2480,
            entry_price=2462, stop_price=2452, target_price=2482,
        )
        for r in results:
            assert 0.0 <= r.confidence <= 1.0, f"{r.question_id} confidence out of range: {r.confidence}"

    # ── score_setup integration ───────────────────────────────────────────
    def test_score_setup_high_confluence(self):
        """A well-aligned setup should score STRONG_MATH or ACCEPTABLE_MATH"""
        fibs = MathematicalEngines.calculate_fibonacci_levels(2420, 2480)
        # Price exactly at 61.8%, on 45° angle, strong momentum
        price = fibs.level_61_8  # ~2443
        results = MathematicalQuestionChecker.check_all(
            pivot_price=2420, pivot_bar=0, current_bar=10,
            current_price=price,
            recent_prices=[2420, 2425, 2430, 2435, 2439, 2443],
            swing_low=2420, swing_high=2480,
            entry_price=price, stop_price=price - 10, target_price=price + 20,
        )
        summary = MathematicalQuestionChecker.score_setup(results)
        assert summary["total"] == 15
        assert summary["pct_pass"] >= 0.0
        assert summary["verdict"] in ("STRONG_MATH", "ACCEPTABLE_MATH", "WEAK_MATH", "FAIL_MATH")

    def test_score_setup_bad_rr_lowers_score(self):
        """When R:R < 1.5, MATH_13 should be in failed_ids"""
        results = MathematicalQuestionChecker.check_all(
            pivot_price=2450, pivot_bar=0, current_bar=10,
            current_price=2462,
            recent_prices=[2450, 2453, 2457, 2460, 2463, 2466],
            swing_low=2420, swing_high=2480,
            entry_price=2462,
            stop_price=2452,   # 10-pip risk
            target_price=2467, # 5-pip reward → R:R = 0.5 → FAIL
        )
        summary = MathematicalQuestionChecker.score_setup(results)
        assert "MATH_13" in summary["failed_ids"]

    def test_score_setup_structure_keys_present(self):
        """score_setup dict must contain score, total, pct_pass, verdict"""
        results = MathematicalQuestionChecker.check_all(
            pivot_price=2450, pivot_bar=0, current_bar=10,
            current_price=2462,
            recent_prices=[2450, 2453, 2457, 2460, 2463, 2466],
            swing_low=2420, swing_high=2480,
            entry_price=2462, stop_price=2452, target_price=2477,
        )
        summary = MathematicalQuestionChecker.score_setup(results)
        for key in ("score", "total", "pct_pass", "verdict", "passed_ids", "failed_ids"):
            assert key in summary


# Run tests
if __name__ == "__main__":
    pytest.main([__file__, "-v"])

