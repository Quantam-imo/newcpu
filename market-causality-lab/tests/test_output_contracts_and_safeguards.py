import unittest

import pandas as pd

from backend.core.output_contracts import (
    normalize_capital_flow_output,
    normalize_execution_output,
    normalize_failure_output,
    output_contract_versions,
)
from backend.sync.simplicity_layer import simplicity_score
from backend.validation.adaptive_timescale_engine import adaptive_timescale_analysis
from backend.validation.data_quality_engine import check_data_quality
from backend.validation.latency_engine import latency_analysis
from backend.validation.overfitting_protection import overfitting_guard


class OutputContractTests(unittest.TestCase):
    def test_execution_contract_fallbacks_and_clamps(self) -> None:
        normalized = normalize_execution_output(
            {
                "verdict": "invalid_verdict",
                "score": 120,
                "issues": None,
                "estimated_slippage": -3,
            }
        )

        self.assertEqual(normalized["contract_version"], "v1")
        self.assertEqual(normalized["verdict"], "CAUTION")
        self.assertEqual(normalized["score"], 100.0)
        self.assertEqual(normalized["issues"], ["NONE"])
        self.assertEqual(normalized["estimated_slippage"], 0.0)

    def test_failure_contract_defaults(self) -> None:
        normalized = normalize_failure_output({"status": "unknown", "severity": "weird", "issues": "x"})

        self.assertEqual(normalized["contract_version"], "v1")
        self.assertEqual(normalized["status"], "CAUTION")
        self.assertEqual(normalized["severity"], "LOW")
        self.assertEqual(normalized["issues"], ["x"])
        self.assertFalse(normalized["invalidated"])

    def test_capital_flow_contract_defaults(self) -> None:
        normalized = normalize_capital_flow_output({"regime": "x", "gold_bias": "y", "risk_on": "yes"})

        self.assertEqual(normalized["contract_version"], "v1")
        self.assertEqual(normalized["regime"], "MIXED")
        self.assertEqual(normalized["safe_haven_demand"], "MEDIUM")
        self.assertEqual(normalized["gold_bias"], "NEUTRAL")
        self.assertTrue(normalized["risk_on"])

    def test_output_contract_versions(self) -> None:
        versions = output_contract_versions()
        self.assertEqual(versions["execution"], "v1")
        self.assertEqual(versions["failure"], "v1")
        self.assertEqual(versions["capital_flow"], "v1")


class SafeguardEngineTests(unittest.TestCase):
    def _df(self) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "open": [100 + i for i in range(60)],
                "high": [101 + i for i in range(60)],
                "low": [99 + i for i in range(60)],
                "close": [100 + i for i in range(60)],
            }
        )

    def test_data_quality_detects_issues(self) -> None:
        df = self._df().copy()
        df.loc[0, "close"] = 0
        result = check_data_quality(df)
        self.assertIn("score", result)
        self.assertIn("status", result)
        self.assertTrue(isinstance(result["issues"], list))

    def test_latency_analysis_shape(self) -> None:
        result = latency_analysis({"volatility": 4.5, "spread": 2.2}, self._df())
        self.assertIn(result["timing_verdict"], {"OK", "CAUTION", "ENTRY_RISK"})
        self.assertIn("bar_latency", result)
        self.assertIn("reaction_window", result)

    def test_adaptive_timescale_shape(self) -> None:
        result = adaptive_timescale_analysis({"volatility": 1.0}, self._df())
        self.assertIn("volatility_regime", result)
        self.assertIn("time_compression", result)
        self.assertIn(result["signal_modifier"], {"NORMAL", "REDUCE_POSITION", "BREAKOUT_WATCH"})

    def test_simplicity_score_bounds(self) -> None:
        result = simplicity_score(
            filtered_signal="BUY",
            confidence=0.8,
            reliability_score=0.7,
            conflict_score=0.2,
            trap={"probability": 0.1},
        )
        self.assertGreaterEqual(result["bias_score"], -1.0)
        self.assertLessEqual(result["bias_score"], 1.0)
        self.assertGreaterEqual(result["clarity"], 0)
        self.assertLessEqual(result["clarity"], 100)

    def test_overfit_guard_insufficient_history(self) -> None:
        result = overfitting_guard({"pnl_series": [1, -1, 2]}, signal_history=["BUY", "SELL"])
        self.assertEqual(result["overfit_risk"], "LOW")
        self.assertIn("accuracy", result)
        self.assertIn("stability", result)


if __name__ == "__main__":
    unittest.main()
