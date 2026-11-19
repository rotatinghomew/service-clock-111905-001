import csv
import unittest
from pathlib import Path


class FixtureTests(unittest.TestCase):
    def test_event_rows_have_unique_ids_and_known_case_references(self):
        path = Path(__file__).parents[1] / "fixtures" / "events.csv"
        with path.open(encoding="utf-8", newline="") as source:
            rows = list(csv.DictReader(source))
        self.assertGreaterEqual(len(rows), 10)
        event_ids = [row["event_id"] for row in rows]
        self.assertEqual(len(event_ids), len(set(event_ids)))
        self.assertTrue(all(row["case_id"] and row["event_type"] for row in rows))


if __name__ == "__main__":
    unittest.main()
