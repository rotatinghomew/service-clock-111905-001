import csv
from pathlib import Path
import unittest


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
HEADERS = {'appointment_slots': ['id', 'owner', 'skill', 'start', 'end', 'capacity'], 'appointments': ['id', 'work', 'slots', 'start', 'end', 'sent', 'resident_confirmed', 'canceled_confirmed'], 'calendar': ['day', 'open', 'close'], 'cases': ['id', 'kind', 'received', 'grid', 'commitment'], 'commitments': ['id', 'start', 'clock', 'limit_min', 'notice_min', 'pause_reason'], 'events': ['id', 'case_id', 'work_id', 'kind', 'occurred', 'recorded', 'owner', 'detail', 'supersedes'], 'notices': ['id', 'work_id', 'owner', 'action', 'status', 'as_of', 'due'], 'slot_requirements': ['work', 'skill', 'role', 'duration_min'], 'work': ['id', 'case_id', 'commitment', 'prerequisite', 'action']}
LINKS = [('work', 'case_id', 'cases', 'id'), ('events', 'case_id', 'cases', 'id'), ('notices', 'work_id', 'work', 'id'), ('slot_requirements', 'work', 'work', 'id'), ('appointments', 'work', 'work', 'id')]


def read(name):
    with (FIXTURES / (name + ".csv")).open(encoding="utf-8", newline="") as source:
        reader = csv.DictReader(source)
        return reader.fieldnames, list(reader)


class SourceRecords(unittest.TestCase):
    def test_records_match_source_columns(self):
        for name, expected in HEADERS.items():
            with self.subTest(table=name):
                header, rows = read(name)
                self.assertEqual(header, expected)
                self.assertTrue(rows)
                self.assertTrue(all(None not in row and None not in row.values() for row in rows))
                if "id" in header:
                    ids = [row["id"] for row in rows]
                    self.assertTrue(all(ids))
                    self.assertEqual(len(ids), len(set(ids)))

    def test_record_references_exist(self):
        for source, field, target, key in LINKS:
            with self.subTest(table=source, column=field):
                _, source_rows = read(source)
                _, target_rows = read(target)
                keys = {row[key] for row in target_rows}
                self.assertTrue(all(row[field] in keys for row in source_rows))
