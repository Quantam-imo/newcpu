import tempfile
import unittest
from pathlib import Path

import pandas as pd

from scripts.prune_observation_logs import prune_observation_csv, prune_observation_frame


class PruneObservationLogsTests(unittest.TestCase):
    def test_prune_observation_frame_by_days(self) -> None:
        now = pd.Timestamp.now("UTC")
        df = pd.DataFrame(
            {
                "recorded_at_utc": [
                    (now - pd.Timedelta(days=400)).isoformat(),
                    (now - pd.Timedelta(days=20)).isoformat(),
                    (now - pd.Timedelta(days=2)).isoformat(),
                ],
                "observation_id": ["old", "mid", "new"],
            }
        )

        pruned = prune_observation_frame(df, keep_days=30, max_rows=100)
        self.assertEqual(list(pruned["observation_id"]), ["mid", "new"])

    def test_prune_observation_frame_by_max_rows(self) -> None:
        now = pd.Timestamp.now("UTC")
        rows = []
        for i in range(10):
            rows.append(
                {
                    "recorded_at_utc": (now - pd.Timedelta(minutes=10 - i)).isoformat(),
                    "observation_id": f"obs-{i}",
                }
            )
        df = pd.DataFrame(rows)

        pruned = prune_observation_frame(df, keep_days=365, max_rows=3)
        self.assertEqual(len(pruned), 3)
        self.assertEqual(list(pruned["observation_id"]), ["obs-7", "obs-8", "obs-9"])

    def test_prune_observation_csv_roundtrip(self) -> None:
        now = pd.Timestamp.now("UTC")
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = Path(tmpdir) / "market_observations.csv"
            df = pd.DataFrame(
                {
                    "recorded_at_utc": [
                        (now - pd.Timedelta(days=200)).isoformat(),
                        (now - pd.Timedelta(days=1)).isoformat(),
                    ],
                    "observation_id": ["older", "newer"],
                }
            )
            df.to_csv(csv_path, index=False)

            before, after = prune_observation_csv(csv_path, keep_days=30, max_rows=10, dry_run=False)
            self.assertEqual(before, 2)
            self.assertEqual(after, 1)

            out = pd.read_csv(csv_path)
            self.assertEqual(len(out), 1)
            self.assertEqual(out.loc[0, "observation_id"], "newer")


if __name__ == "__main__":
    unittest.main()
