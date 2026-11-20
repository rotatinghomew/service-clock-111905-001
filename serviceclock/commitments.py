"""居民承诺：候约、通知已发、居民已接受是不同事实。

承诺只按居民同意的实际时间窗口履约；责任项的停钟和转交不能延后它。
调整单（proposal）发出后只暂占到确认截止；居民确认前旧约仍有效；截止时
前台仍不知道是否接受就释放暂占；仅凭事后回报的发生时间不能复活已释放的
暂占。签收时若班表变动，只有仍能共同履行的整组确认才能替代旧约。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .intervals import intersect, measure
from .model import fmt_hhmm


@dataclass
class ApptState:
    appt: object
    state: str  # 候约/通知已发/已接受/待发出/暂占中/已确认/已替换/已释放/失效/确认无效
    detail: str
    evidence: list


def group_problems(view, appt) -> list:
    """整组资源在 [start,end) 上是否都有适用班表覆盖。"""
    problems = []
    for res in appt.resources:
        segs = view.shift_segments(res)
        if not segs:
            problems.append(f"{res} 无适用班表")
        elif measure(intersect([(appt.start, appt.end)], segs)) < appt.end - appt.start:
            problems.append(f"{res} 班表不覆盖 {fmt_hhmm(appt.start)}-{fmt_hhmm(appt.end)}")
    return problems


def appointment_states(view):
    """计算各预约在 view.now 的状态，并给出当前生效的资源占用。"""
    states: dict[str, ApptState] = {}
    reservations: list = []  # (start, end, appt_id, resources, state)

    def conflicts(appt):
        return [r for r in reservations
                if r[2] != appt.id and r[2] != appt.prior
                and r[0] < appt.end and appt.start < r[1]
                and set(r[3]) & set(appt.resources)]

    appts = sorted(view.appointments.values(), key=lambda a: (a.received, a.id))
    for appt in appts:
        rs = view.receipts_for(appt.id)
        sent = next((r for r in rs if r.kind == "sent"), None)
        accepted = next((r for r in rs if r.kind == "accepted"), None)
        ev = [r.id for r in (sent, accepted) if r]
        if appt.kind in ("original", "protected"):
            if accepted:
                st, detail = "已接受", "居民已接受该时段"
            elif sent:
                st, detail = "通知已发", "已通知居民，尚未接受"
            else:
                st, detail = "候约", "尚未通知居民"
            states[appt.id] = ApptState(appt, st, detail, ev)
            if accepted:
                reservations.append((appt.start, appt.end, appt.id, frozenset(appt.resources), st))
            continue
        # proposal：值班员收到的待比较调整单
        if not sent:
            if appt.expires is not None and view.now > appt.expires:
                st, detail = "失效", "未在确认截止前发出"
            else:
                st = "待发出"
                clash = conflicts(appt)
                detail = "调整单未发出"
                if clash:
                    detail += "；与 " + ",".join(c[2] for c in clash) + " 争同一份资源，不能发出"
            states[appt.id] = ApptState(appt, st, detail, ev)
            continue
        known_in_time = (accepted and appt.expires is not None
                         and accepted.received <= appt.expires
                         and accepted.occ_from <= appt.expires)
        if known_in_time:
            shift_view = view.ledger.view(accepted.received)
            problems = group_problems(shift_view, appt)
            clash = conflicts(appt)
            if not problems and not clash:
                states[appt.id] = ApptState(appt, "已确认", "居民在截止前接受，整组可共同履行", ev)
                reservations.append((appt.start, appt.end, appt.id, frozenset(appt.resources), "已确认"))
                if appt.prior and appt.prior in states:
                    old = states[appt.prior]
                    states[appt.prior] = ApptState(old.appt, "已替换", f"被 {appt.id} 替代", old.evidence)
                    reservations[:] = [r for r in reservations if r[2] != appt.prior]
            else:
                why = "；".join(problems + [f"与 {c[2]} 资源冲突" for c in clash])
                states[appt.id] = ApptState(
                    appt, "确认无效", f"签收时整组不可共同履行：{why}；原约继续有效", ev)
        elif appt.expires is not None and view.now > appt.expires:
            if accepted:
                states[appt.id] = ApptState(
                    appt, "已释放", "确认截止后才知道的接受不能复活已释放的暂占", ev)
            else:
                states[appt.id] = ApptState(
                    appt, "已释放", "确认截止时前台仍不知道是否接受，暂占释放，需重新协商", ev)
        else:
            states[appt.id] = ApptState(
                appt, "暂占中", f"暂占至 {fmt_hhmm(appt.expires)}，居民确认前旧约仍有效", ev)
            reservations.append((appt.start, appt.end, appt.id, frozenset(appt.resources), "暂占中"))
    return states, reservations


def valid_appointment(view, case: str, states=None):
    """当前对居民有效的承诺约：已确认的调整单优先，否则未被替换的已接受原约。"""
    if states is None:
        states, _ = appointment_states(view)
    mine = [s for s in states.values() if s.appt.case == case]
    for s in mine:
        if s.state == "已确认":
            return s.appt
    for s in mine:
        if s.state == "已接受":
            return s.appt
    return None


def effective_owner(view, duty) -> str:
    """责任交接只转移之后的工作：当前责任人取最后一条有效交接回执。"""
    owner = duty.owner
    for r in view.receipts_for(duty.id, ("transfer",)):
        if r.detail:
            owner = r.detail
    return owner


def _arrival_problem(view, duty, appt) -> str | None:
    """剩余窗口内责任人是否还可能到场；不可能时给出原因。"""
    earliest = max(view.now, appt.start)
    if earliest >= appt.end:
        return "承诺窗口已过"
    owner = effective_owner(view, duty)
    if not intersect([(earliest, appt.end)], view.shift_segments(owner)):
        return f"责任人 {owner} 班表不覆盖剩余窗口"
    return None


@dataclass
class CommitmentReport:
    case: str
    grid: str
    appointment: object
    appt_state: str | None
    status: str  # 待履约/可挽救/已履约/可能失守/已失守/需重新协商
    reasons: list
    arrivals: dict
    evidence: list
    clock: str = "居民承诺窗口(按同意的实际时间)"

    def describe(self) -> str:
        if self.appointment is None:
            win = "无有效约"
        else:
            win = f"{self.appointment.id} {fmt_hhmm(self.appointment.start)}-{fmt_hhmm(self.appointment.end)}"
        return f"{self.case} 承诺[{win}] → {self.status}（{'；'.join(self.reasons) or '无异常'}）"


def commitment_status(view, case: str, states=None) -> CommitmentReport:
    term = view.ledger.terms[case]
    if states is None:
        states, _ = appointment_states(view)
    appt = valid_appointment(view, case, states)
    visits = [d for d in view.ledger.duties.values() if d.case == case and d.stage == "visit"]
    evidence, reasons = [], []
    if appt is None:
        notes = [f"{s.appt.id}:{s.state}" for s in states.values() if s.appt.case == case]
        return CommitmentReport(
            case=case, grid=term.grid, appointment=None, appt_state=None,
            status="需重新协商" if visits else "无承诺",
            reasons=["没有居民同意的有效时段（" + ",".join(notes) + "）"] if notes else ["从未发出约"],
            arrivals={}, evidence=notes)
    evidence.append(appt.id)
    late, uncertain, missing = [], [], []
    arrivals = {}
    for d in visits:
        r = next((x for x in view.receipts_for(d.id, ("arrival",))), None)
        arrivals[d.id] = r
        if r is None:
            missing.append(d)
        else:
            evidence.append(r.id)
            if r.occ_from >= appt.start and r.occ_to <= appt.end:
                continue
            if r.occ_to <= appt.start or r.occ_from >= appt.end:
                late.append((d, r))
            else:
                uncertain.append((d, r))
    for d, r in late:
        reasons.append(f"{d.id} 到场 {fmt_hhmm(r.occ_from)}-{fmt_hhmm(r.occ_to)} 在承诺窗口之外")
    for d, r in uncertain:
        reasons.append(
            f"{d.id} 到场只有发生界限 {fmt_hhmm(r.occ_from)}-{fmt_hhmm(r.occ_to)}，"
            f"跨越窗口末 {fmt_hhmm(appt.end)}，不能按最有利解释算达标")
    declined = [d for d in missing if view.receipts_for(d.id, ("decline",))]
    blocked = [(d, _arrival_problem(view, d, appt)) for d in missing]
    hard = [(d, why) for d, why in blocked if why and d not in declined]
    for d, why in blocked:
        if why and not (why == "承诺窗口已过" and view.now >= appt.end):
            reasons.append(f"{d.id} {why}")
    for d in declined:
        reasons.append(f"{d.id} 已退单，需重派或重新联系居民")
    if late or (missing and view.now >= appt.end):
        status = "已失守"
        if missing and view.now >= appt.end:
            reasons.append("承诺窗口已过，仍有责任项无到场回执")
    elif uncertain:
        status = "可能失守"
    elif missing:
        if hard:
            status = "已失守"  # 剩余窗口内确定无法履约
        elif declined or any(why for _, why in blocked):
            status = "可能失守"
        elif view.now >= appt.start:
            status = "可挽救"
        else:
            status = "待履约"
    else:
        status = "已履约"
    return CommitmentReport(
        case=case, grid=term.grid, appointment=appt,
        appt_state=states[appt.id].state, status=status, reasons=reasons,
        arrivals=arrivals, evidence=evidence)
