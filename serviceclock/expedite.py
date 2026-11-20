"""催办：退单影响、可兑现方案的比较与发出。

方案不能只按剩余分钟排队：同一人和同一间核验室不能被重复承诺，联合上门
需要材料预审已结束且双方在同一时段真正可用；受保护的既有预约不能被挪给
新单。新安排只暂占到确认截止，旧约在居民确认前仍然有效。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .clocks import duty_clock
from .commitments import (appointment_states, commitment_status, effective_owner,
                          group_problems, valid_appointment)
from .intervals import intersect, merge, subtract
from .model import Appointment, Receipt, fmt_hhmm


@dataclass
class Impact:
    duty_id: str
    case: str
    recontact: list            # 现在只能重新联系居民的承诺
    worth_continuing: list     # (责任项, 原因)：仍值得办的并行任务
    breach_ledger: list        # 进入原时限违约账的时钟


@dataclass
class Option:
    kind: str                  # prep_first / handoff / new_joint_window
    case: str
    feasible: bool
    description: str
    slot: tuple | None = None
    assignments: dict = field(default_factory=dict)
    resources: tuple = ()
    avoids: list = field(default_factory=list)   # 能减少的确定失约
    costs: list = field(default_factory=list)    # 会失去后续可行时间的事项
    reasons: list = field(default_factory=list)


@dataclass
class Action:
    """催办记录：值班交接从它查到处置过的风险与发出的本地回执。"""

    id: str
    time: int
    kind: str
    case: str
    summary: str
    risks: list
    receipts: list
    appointment_id: str | None = None


def _pending_duties(view, case, stage=None):
    """尚未完成也未到场（退单仍待重派）的责任项。"""
    out = []
    for d in view.ledger.duties.values():
        if d.case != case or (stage and d.stage != stage):
            continue
        rs = view.receipts_for(d.id)
        if any(r.kind in ("completed", "arrival") for r in rs):
            continue
        out.append(d)
    return out


def _prep_finished(view, case) -> bool:
    preps = [d for d in view.ledger.duties.values() if d.case == case and d.stage == "prep"]
    return all(any(r.kind == "completed" for r in view.receipts_for(d.id)) for d in preps)


def _needed_resources(view, case, visits):
    resources = sorted({effective_owner(view, d) for d in visits})
    windows = {d.window for d in view.ledger.duties.values()
               if d.case == case and d.stage == "visit"}
    if len(windows) > 1:
        resources.append("ROOM")  # 联合上门需要共同房间
    return resources


def free_intervals(view, resource, reservations, earliest, extra=()):
    segs = view.shift_segments(resource)
    blocks = [(s, e) for (s, e, _aid, res, _st) in reservations if resource in res]
    blocks += [(s, e) for (s, e, r) in extra if r == resource]
    return [(max(s, earliest), e) for s, e in subtract(segs, merge(blocks))
            if e > max(s, earliest)]


def find_joint_slot(view, resources, duration, earliest, reservations, extra=()):
    """整组资源同一时段真正可用的最早窗口；找不到时给出每个资源的原因。"""
    common = None
    for r in resources:
        fi = free_intervals(view, r, reservations, earliest, extra)
        common = fi if common is None else intersect(common, fi)
    slot = None
    for s, e in common or []:
        if e - s >= duration:
            slot = (s, s + duration)
            break
    reasons = []
    if slot is None:
        for r in resources:
            segs = view.shift_segments(r)
            if not segs:
                reasons.append(f"{r} 无适用班表")
                continue
            busy = [(s, e, aid) for (s, e, aid, res, _st) in reservations
                    if r in res and e > earliest]
            msg = f"{r} 班表至 {fmt_hhmm(max(e for _, e in segs))}"
            if busy:
                msg += "，" + "；".join(
                    f"{fmt_hhmm(s)}-{fmt_hhmm(e)} 被 {aid} 占用" for s, e, aid in sorted(busy))
            reasons.append(msg)
    return slot, reasons


def decline_impact(view, duty_id: str) -> Impact:
    """窗口退回自己的一项：查仍值得办的并行任务、只能重新联系的承诺、
    以及将进入原时限违约账的等待。"""
    duty = view.ledger.duties[duty_id]
    case = duty.case
    rep = commitment_status(view, case)
    recontact = []
    if rep.appointment is not None and rep.status in ("可挽救", "可能失守", "已失守"):
        win = f"{rep.appointment.id} {fmt_hhmm(rep.appointment.start)}-{fmt_hhmm(rep.appointment.end)}"
        recontact.append(f"{case} 对居民的承诺 {win}：{duty_id} 退单后只能重新联系或重派")
    worth = []
    for d in _pending_duties(view, case):
        if d.id == duty_id:
            continue
        if d.stage == "visit" and rep.appointment is not None and view.now < rep.appointment.end:
            worth.append((d.id, "其到场仍计入当前承诺窗口"))
        elif d.stage == "prep":
            worth.append((d.id, "前置完成可保留后续重约的可行时间"))
        else:
            worth.append((d.id, "进度保留，供重新协商后的联合上门使用"))
    breach = []
    for d in view.ledger.duties.values():
        if d.case != case:
            continue
        clk = duty_clock(view, d.id)
        if clk.status != "在限时内":
            breach.append(clk)
    return Impact(duty_id=duty_id, case=case, recontact=recontact,
                  worth_continuing=worth, breach_ledger=breach)


def _alternatives(view, duty):
    """同技能且同窗口（或未限定窗口）的其他可接手人员。"""
    alts = []
    for s in view.shifts:
        if s.resource == effective_owner(view, duty):
            continue
        if duty.skill not in s.skills:
            continue
        if s.window not in (None, duty.window):
            continue
        if s.resource not in alts:
            alts.append(s.resource)
    return sorted(alts)


def compare_options(view, case: str) -> list:
    """比较三类安排分别减少哪些确定失约、又让哪些事项失去后续可行时间。"""
    term = view.ledger.terms[case]
    states, reservations = appointment_states(view)
    rep = commitment_status(view, case, states)
    visits = _pending_duties(view, case, "visit")
    preps_open = _pending_duties(view, case, "prep")
    current = valid_appointment(view, case, states)
    at_risk = rep.status in ("已失守", "可能失守", "需重新协商")
    risk_desc = f"{case} 对居民的承诺（当前{rep.status}）"
    options = []

    # 选项一：能独做的前置事项提前
    if preps_open:
        resources = _needed_resources(view, case, visits)
        slot, reasons = (None, ["没有待上门的责任项"]) if not visits else find_joint_slot(
            view, resources, term.duration, view.now, reservations)
        opt = Option("prep_first", case, slot is not None,
                     description="前置事项可独做，立即完成后联合上门的最早已知窗口",
                     slot=slot, reasons=reasons)
        if slot and at_risk:
            opt.avoids.append(risk_desc)
        options.append(opt)

    # 选项二：同技能人员接手
    for d in visits + preps_open:
        declined = bool(view.receipts_for(d.id, ("decline",)))
        stuck = declined or current is None
        if not stuck and current is not None:
            from .commitments import _arrival_problem
            stuck = _arrival_problem(view, d, current) is not None
        if not stuck:
            continue
        for alt in _alternatives(view, d):
            if current is not None:
                earliest = max(view.now, current.start)
                ok = any(intersect([(s, e)], [(earliest, current.end)])
                         for s, e in free_intervals(view, alt, reservations, earliest))
                slot, reasons = None, [] if ok else [f"{alt} 在承诺窗口内不可用"]
            else:
                resources = [alt if r == effective_owner(view, d) else r
                             for r in _needed_resources(view, case, visits)]
                slot, reasons = find_joint_slot(view, resources, term.duration,
                                                view.now, reservations)
                ok = slot is not None
            opt = Option("handoff", case, ok,
                         description=f"{d.id} 由 {effective_owner(view, d)} 改派 {alt}（同技能 {d.skill}）",
                         slot=slot, assignments={d.id: alt}, reasons=reasons)
            if ok and at_risk:
                opt.avoids.append(risk_desc)
            options.append(opt)

    # 选项三：用新的联合窗口继续履约（受保护的既有预约不能被挪）
    if visits and (current is None or current.kind != "protected"):
        if not _prep_finished(view, case):
            options.append(Option("new_joint_window", case, False,
                                  description="新的联合窗口",
                                  reasons=["材料预审未结束，联合上门不能排"]))
        else:
            resources = _needed_resources(view, case, visits)
            slot, reasons = find_joint_slot(view, resources, term.duration,
                                            view.now, reservations)
            opt = Option("new_joint_window", case, slot is not None,
                         description="新的联合窗口继续履约",
                         slot=slot, resources=tuple(resources), reasons=reasons)
            if slot:
                if at_risk:
                    opt.avoids.append(risk_desc)
                extra = [(slot[0], slot[1], r) for r in resources]
                for other in view.ledger.terms.values():
                    if other.id == case or valid_appointment(view, other.id, states):
                        continue
                    ovisits = _pending_duties(view, other.id, "visit")
                    if not ovisits or not _prep_finished(view, other.id):
                        continue
                    ores = _needed_resources(view, other.id, ovisits)
                    before, _ = find_joint_slot(view, ores, other.duration, view.now, reservations)
                    after, _ = find_joint_slot(view, ores, other.duration, view.now,
                                               reservations, extra)
                    if before and not after:
                        opt.costs.append(f"{other.id} 失去后续可行时间")
            options.append(opt)
    return options


def issue_option(ledger, view, option: Option, expires=None) -> Action:
    """发出可兑现的安排；所有收发都用本地业务回执。不可兑现的安排不能发出。"""
    if not option.feasible:
        raise ValueError("不可兑现的安排不能发出：" + "；".join(option.reasons))
    now = view.now
    receipts = []
    if option.kind == "handoff":
        for duty_id, alt in option.assignments.items():
            rid = f"R{len(ledger.outbox) + 1:03d}"
            ledger.outbox.append(Receipt(rid, duty_id, "transfer", now, now, now, alt, None))
            receipts.append(rid)
        action = Action(f"A{len(ledger.actions) + 1}", now, "handoff", option.case,
                        option.description, list(option.avoids), receipts)
    elif option.kind == "new_joint_window":
        current = valid_appointment(view, option.case)
        if current is not None and current.kind == "protected":
            raise ValueError("受保护的既有预约不能被挪给新单")
        aid = f"P{len(ledger.issued) + 1:02d}"
        appt = Appointment(aid, option.case, option.slot[0], option.slot[1],
                           tuple(option.resources), "proposal",
                           current.id if current else None, expires, now)
        states, reservations = appointment_states(view)
        problems = group_problems(view, appt)
        clash = [r for r in reservations
                 if r[2] != appt.prior and r[0] < appt.end and appt.start < r[1]
                 and set(r[3]) & set(appt.resources)]
        if problems or clash:
            raise ValueError("不能发出无法接受的新约：" + "；".join(
                problems + [f"与 {c[2]} 资源冲突" for c in clash]))
        ledger.issued.append(appt)
        rid = f"R{len(ledger.outbox) + 1:03d}"
        ledger.outbox.append(Receipt(rid, aid, "sent", now, now, now, None, None))
        receipts.append(rid)
        action = Action(f"A{len(ledger.actions) + 1}", now, "new_joint_window",
                        option.case, option.description, list(option.avoids),
                        receipts, appointment_id=aid)
    else:
        raise ValueError("该选项不需要发出通知")
    ledger.actions[action.id] = action
    return action
