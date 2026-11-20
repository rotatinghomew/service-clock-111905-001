"""值班台查询：按事项、居民（网格）和责任窗口查承诺账，以及值班交接。"""
from __future__ import annotations

from .clocks import duty_clock
from .commitments import appointment_states, commitment_status, valid_appointment
from .expedite import compare_options
from .model import fmt_hhmm


def desk_report(view, case=None, grid=None, window=None) -> dict:
    """按事项/居民/责任窗口查到已经失守、可能失守以及现在可挽救的承诺，
    并给出每个判断采用的记录（回执号）和时钟区别。"""
    states, _ = appointment_states(view)
    cases = []
    summary = {"已失守": [], "可能失守": [], "可挽救": []}
    for term in view.ledger.terms.values():
        if case and term.id != case:
            continue
        if grid and term.grid != grid:
            continue
        rep = commitment_status(view, term.id, states)
        clocks = [duty_clock(view, d.id) for d in view.ledger.duties.values()
                  if d.case == term.id and (not window or d.window == window)]
        if window and not clocks:
            continue
        cases.append({"case": term.id, "grid": term.grid,
                      "commitment": rep, "duties": clocks})
        if rep.status in ("已失守", "可能失守"):
            summary[rep.status].append(f"{term.id} 承诺（{rep.clock}）")
        elif rep.status in ("可挽救", "待履约"):
            summary["可挽救"].append(f"{term.id} 承诺（{rep.clock}）")
        elif rep.status == "需重新协商":
            summary["可能失守"].append(f"{term.id} 承诺（{rep.clock}，需重新协商）")
        for c in clocks:
            ref = f"{c.duty_id} 责任项（{c.clock}）"
            if c.status in ("已失守", "可能失守"):
                summary[c.status].append(ref)
            elif not c.closed:
                summary["可挽救"].append(ref)
    return {"now": fmt_hhmm(view.now), "cases": cases, "summary": summary}


def handover_report(view, action_id: str) -> dict:
    """值班交接：从一条催办记录查到它处置过的风险、当前仍有效的预约，
    以及未能处理的原因。"""
    ledger = view.ledger
    action = ledger.actions[action_id]
    states, _ = appointment_states(view)
    valid = {}
    for term in ledger.terms.values():
        appt = valid_appointment(view, term.id, states)
        if appt is not None:
            valid[term.id] = {
                "appointment": appt.id,
                "window": f"{fmt_hhmm(appt.start)}-{fmt_hhmm(appt.end)}",
                "state": states[appt.id].state,
            }
    unhandled = []
    for term in ledger.terms.values():
        rep = commitment_status(view, term.id, states)
        if rep.status not in ("已失守", "可能失守", "需重新协商"):
            continue
        reasons = list(rep.reasons)
        if rep.status == "需重新协商":
            for opt in compare_options(view, term.id):
                if not opt.feasible:
                    reasons += opt.reasons
        unhandled.append({"case": term.id, "status": rep.status, "reasons": reasons})
    return {
        "action": action,
        "risks_addressed": list(action.risks),
        "valid_appointments": valid,
        "unhandled": unhandled,
    }
