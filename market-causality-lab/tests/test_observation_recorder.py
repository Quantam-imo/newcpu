import tempfile
import unittest
from pathlib import Path

import pandas as pd

from backend.utils.observation_recorder import record_observation


class ObservationRecorderTests(unittest.TestCase):
    def _price_df(self) -> pd.DataFrame:
        times = pd.date_range("2026-01-01 00:00:00", periods=6, freq="h")
        closes = [100.0, 101.0, 102.0, 103.0, 102.0, 101.0]
        return pd.DataFrame(
            {
                "time": times,
                "open": closes,
                "high": [c + 0.5 for c in closes],
                "low": [c - 0.5 for c in closes],
                "close": closes,
            }
        )

    def _events_df(self) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "time": ["2026-01-01 03:30:00", "2026-01-01 05:30:00"],
                "event": ["Fed Statement", "Nakshatra Shift"],
                "impact": ["high", "medium"],
            }
        )

    def _result_payload(self) -> dict:
        return {
            "filtered_signal": "SELL",
            "final": {"trend": "DOWN"},
            "universal": {
                "price_degree": 181.2,
                "gann": {
                    "degrees": 182.0,
                    "cycle": {"cycle_degree": 270.0, "quadrant": 4, "description": "MARKDOWN"},
                    "nearest_angles": ["1x1", "2x1"],
                    "price_time_equality": {"status": "PRICE_LEADS", "ratio": 1.15},
                },
                "nakshatra": {"nakshatra": "Revati", "pada": 3},
            },
        }

    def test_record_observation_persists_expected_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            df = self._price_df()
            events = self._events_df()
            result = self._result_payload()

            meta = record_observation(
                df=df,
                result=result,
                events_df=events,
                symbol="XAUUSD",
                requested_timeframe="5m",
                applied_timeframe="5m",
                lookback_years=25,
                source_mode="historical_first",
                output_dir=tmpdir,
            )

            self.assertIn("observation_id", meta)
            self.assertIn("observation_log_path", meta)

            csv_path = Path(meta["observation_log_path"])
            self.assertTrue(csv_path.exists())

            written = pd.read_csv(csv_path)
            self.assertEqual(len(written), 1)
            self.assertEqual(written.loc[0, "trend_label"], "DOWN")
            self.assertEqual(written.loc[0, "gann_degree"], 182.0)
            self.assertEqual(written.loc[0, "news_previous_event"], "Fed Statement")
            self.assertEqual(written.loc[0, "news_next_event"], "Nakshatra Shift")
            self.assertEqual(written.loc[0, "trend_start_time"], "2026-01-01T04:00:00")
            self.assertEqual(written.loc[0, "signal_start_time"], "2026-01-01T04:00:00")
            self.assertIsNotNone(written.loc[0, "signal_end_time"])
            self.assertGreater(float(written.loc[0, "signal_window_hours"]), 0.0)
            self.assertAlmostEqual(float(written.loc[0, "signal_start_price"]), 102.0)
            self.assertIn(written.loc[0, "confirmation_geometry"], ["YES", "NO"])
            self.assertIn(written.loc[0, "confirmation_time"], ["YES", "NO"])
            self.assertIn(written.loc[0, "confirmation_structure"], ["YES", "NO"])
            self.assertIn(written.loc[0, "confirmation_tape_action"], ["YES", "NO"])
            self.assertTrue(str(written.loc[0, "gann_mindset_narration"]).strip())

    def test_record_observation_appends_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            df = self._price_df()
            events = self._events_df()
            result = self._result_payload()

            meta1 = record_observation(
                df=df,
                result=result,
                events_df=events,
                symbol="XAUUSD",
                requested_timeframe="1h",
                applied_timeframe="1h",
                lookback_years=25,
                source_mode="historical_first",
                output_dir=tmpdir,
            )
            meta2 = record_observation(
                df=df,
                result=result,
                events_df=events,
                symbol="XAUUSD",
                requested_timeframe="1h",
                applied_timeframe="1h",
                lookback_years=25,
                source_mode="historical_first",
                output_dir=tmpdir,
            )

            self.assertNotEqual(meta1["observation_id"], meta2["observation_id"])
            written = pd.read_csv(meta1["observation_log_path"])
            self.assertEqual(len(written), 2)


if __name__ == "__main__":
    unittest.main()
