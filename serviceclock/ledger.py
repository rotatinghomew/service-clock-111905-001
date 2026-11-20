"""源记录的装载与按到件时点的可见视图。

记录按 received 的到件时点分批读入；同一时刻全批可用。
没有 supersedes 表示追加而非覆盖；void 回执撤销其 supersedes 指向的回执。
"""
from __future__ import annotations

import csv
from pathlib import Path

from .intervals import merge
from .model import Appointment, Duty, Receipt, Shift, Term, parse_hhmm


def _opt(value: str | None) -> str | None:
    return value if value else None


class Ledger:
    """全部源记录，以及值班台自己发出的本地业务回执与催办记录。"""

    def __init__(self, terms, duties, shifts, appointments, receipts):
        self.terms = {row.id: row for row in terms}
        self.duties = {row.id: row for row in duties}
        self.shifts = list(shifts)
        self.appointments = {row.id: row for row in appointments}
        self.receipts = list(receipts)
        self.outbox: list[Receipt] = []       # 值班台发出的本地业务回执
        self.issued: list[Appointment] = []   # 值班台发出的新约（proposal）
        self.actions: dict[str, object] = {}  # 催办记录，供值班交接追查

    @classmethod
    def load(cls, folder) -> "Ledger":
        folder = Path(folder)

        def rows(name):
            with (folder / name).open(encoding="utf-8", newline="") as src:
                return list(csv.DictReader(src))

        terms = [
            Term(r["id"], r["grid"], parse_hhmm(r["intake"]), int(r["due_minutes"]), int(r["duration"]))
            for r in rows("terms.csv")
        ]
        duties = [
            Duty(r["id"], r["case"], r["window"], r["owner"], r["skill"],
                 parse_hhmm(r["opened"]), _opt(r["prerequisite"]), r["stage"])
            for r in rows("duties.csv")
        ]
        shifts = [
            Shift(r["id"], r["resource"], _opt(r["window"]),
                  frozenset(x for x in r["skills"].split(";") if x),
                  parse_hhmm(r["start"]), parse_hhmm(r["end"]),
                  parse_hhmm(r["received"]), _opt(r["supersedes"]))
            for r in rows("shifts.csv")
        ]
        appointments = [
            Appointment(r["id"], r["case"], parse_hhmm(r["start"]), parse_hhmm(r["end"]),
                        tuple(x for x in r["resources"].split(";") if x),
                        r["kind"], _opt(r["prior"]),
                        parse_hhmm(r["expires"]) if r["expires"] else None,
                        parse_hhmm(r["received"]))
            for r in rows("appointments.csv")
        ]
        receipts = [
            Receipt(r["id"], r["target"], r["kind"],
                    parse_hhmm(r["occurred_from"]), parse_hhmm(r["occurred_to"]),
                    parse_hhmm(r["received"]), _opt(r["detail"]), _opt(r["supersedes"]))
            for r in rows("receipts.csv")
        ]
        return cls(terms, duties, shifts, appointments, receipts)

    def view(self, now) -> "View":
        if isinstance(now, str):
            now = parse_hhmm(now)
        return View(self, now)


class View:
    """某一到件时点下值班台可见的事实（已过知的修订与撤销在此生效）。"""

    def __init__(self, ledger: Ledger, now: int):
        self.ledger = ledger
        self.now = now
        known_shifts = [s for s in ledger.shifts if s.received <= now]
        superseded = {s.supersedes for s in known_shifts if s.supersedes}
        self.shifts = [s for s in known_shifts if s.id not in superseded]
        known_receipts = [r for r in ledger.receipts + ledger.outbox if r.received <= now]
        self.voids = [r for r in known_receipts if r.kind == "void"]
        voided = {r.supersedes for r in self.voids if r.supersedes}
        self.receipts = [r for r in known_receipts if r.kind != "void" and r.id not in voided]
        self.appointments = {}
        for appt in list(ledger.appointments.values()) + ledger.issued:
            if appt.received <= now:
                self.appointments[appt.id] = appt

    def shift_segments(self, resource: str):
        segs = [(s.start, s.end) for s in self.shifts if s.resource == resource]
        return merge(segs)

    def receipts_for(self, target: str, kinds=None):
        out = [r for r in self.receipts if r.target == target]
        if kinds is not None:
            out = [r for r in out if r.kind in kinds]
        return sorted(out, key=lambda r: (r.occ_from, r.occ_to, r.id))
