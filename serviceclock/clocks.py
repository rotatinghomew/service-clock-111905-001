"""责任项时钟：按适用班表计时，停钟以有效等待原因为限。

回执只有发生界限时，枚举同一事实的各种可能先后关系（开启不晚于配对的
关闭才可信），得到计时的上下界：下界都超限时才算"已失守"，只有上界超限
算"可能失守"，不允许用最有利的一种解释把两边都算作达标。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from itertools import product

from .intervals import intersect, measure, merge
from .model import fmt_hhmm

TERMINAL_KINDS = {"completed", "decline"}
TIMED_KINDS = TERMINAL_KINDS | {"arrival", "transfer", "pause_open", "pause_close"}


@dataclass
class ClockReport:
    duty_id: str
    case: str
    window: str
    limit: int
    elapsed_min: int
    elapsed_max: int
    closed: bool
    terminal: str | None
    status: str  # 已失守 / 可能失守 / 在限时内
    owners: dict  # 责任方 -> (计时下界, 计时上界)，交接前的等待仍归原责任方
    pauses: list
    evidence: list
    clock: str = "责任项时钟(按适用班表)"

    def describe(self) -> str:
        span = f"{self.elapsed_min}-{self.elapsed_max}" if self.elapsed_min != self.elapsed_max else f"{self.elapsed_min}"
        state = "已终结" if self.closed else "进行中"
        return (f"{self.duty_id}[{self.window}] {state} 计时 {span}/{self.limit} 分钟 "
                f"→ {self.status}（依据 {','.join(self.evidence) or '无回执'}）")


def duty_clock(view, duty_id: str) -> ClockReport:
    duty = view.ledger.duties[duty_id]
    term = view.ledger.terms[duty.case]
    rs = view.receipts_for(duty_id)
    timed = [r for r in rs if r.kind in TIMED_KINDS]
    choices = [
        (r.occ_from,) if r.occ_from == r.occ_to else (r.occ_from, r.occ_to)
        for r in timed
    ]
    totals = []
    owners_lo: dict[str, int] = {}
    owners_hi: dict[str, int] = {}
    terminal_seen = None
    pauses_worst: list = []
    for combo in product(*choices) if choices else [()]:
        t = {r.id: v for r, v in zip(timed, combo)}
        res = _evaluate(view, duty, rs, t)
        if res is None:
            continue  # 该种先后关系不可信（关闭早于任何可配对的开启）
        total, per_owner, terminal, pauses = res
        totals.append(total)
        terminal_seen = terminal
        for owner, val in per_owner.items():
            owners_lo[owner] = min(owners_lo.get(owner, val), val)
            owners_hi[owner] = max(owners_hi.get(owner, val), val)
        if total == max(totals):
            pauses_worst = pauses
    if not totals:  # 全部不可信时退化为发生界限端点近似
        t = {r.id: r.occ_from for r in timed}
        total, per_owner, terminal_seen, pauses_worst = _evaluate(view, duty, rs, t, strict=False)
        totals = [total]
        for owner, val in per_owner.items():
            owners_lo[owner] = owners_hi[owner] = val
    lo, hi = min(totals), max(totals)
    limit = term.due_minutes
    if lo > limit:
        status = "已失守"
    elif hi > limit:
        status = "可能失守"
    else:
        status = "在限时内"
    owners = {o: (owners_lo[o], owners_hi[o]) for o in owners_lo}
    pauses_desc = [
        {"reason": reason, "open": oid, "close": cid,
         "span": f"{fmt_hhmm(a)}-{fmt_hhmm(b)}"}
        for a, b, reason, oid, cid in pauses_worst
    ]
    return ClockReport(
        duty_id=duty_id, case=duty.case, window=duty.window, limit=limit,
        elapsed_min=lo, elapsed_max=hi, closed=terminal_seen is not None,
        terminal=terminal_seen, status=status, owners=owners,
        pauses=pauses_desc, evidence=[r.id for r in rs],
    )


def _evaluate(view, duty, rs, t, strict=True):
    """在一种具体先后关系 t（回执 id -> 发生时刻）下计算计时。"""
    terminals = [r for r in rs if r.kind in TERMINAL_KINDS
                 or (r.kind == "arrival" and duty.stage == "visit")]
    end = view.now
    terminal = None
    for r in terminals:
        if t[r.id] <= end:
            end = t[r.id]
            terminal = r.kind
    transfers = sorted((r for r in rs if r.kind == "transfer"),
                       key=lambda r: (t[r.id], r.id))
    points = [duty.opened] + [t[r.id] for r in transfers] + [end]
    owners = [duty.owner] + [r.detail for r in transfers]
    segments = []
    for i, owner in enumerate(owners):
        a, b = points[i], min(points[i + 1], end)
        a = min(a, b)
        if owner and b > a:
            segments.append((owner, a, b))
    # 停钟：同一理由的开启与关闭按先后配对，未配对的开启计到终结/现在
    opens: dict[str, list] = {}
    closes: dict[str, list] = {}
    for r in rs:
        if r.kind == "pause_open" and r.detail:
            opens.setdefault(r.detail, []).append(r)
        elif r.kind == "pause_close" and r.detail:
            closes.setdefault(r.detail, []).append(r)
    pauses = []
    for reason, olist in opens.items():
        olist = sorted(olist, key=lambda r: (t[r.id], r.id))
        clist = sorted(closes.get(reason, []), key=lambda r: (t[r.id], r.id))
        used = set()
        for c in clist:
            cand = [o for o in olist if o.id not in used and t[o.id] <= t[c.id]]
            if not cand:
                if strict:
                    return None
                continue
            o = cand[-1]
            used.add(o.id)
            pauses.append((t[o.id], t[c.id], reason, o.id, c.id))
        for o in olist:
            if o.id not in used:
                pauses.append((t[o.id], end, reason, o.id, None))
    pause_ivs = merge([
        (max(a, duty.opened), min(b, end))
        for a, b, *_ in pauses if min(b, end) > max(a, duty.opened)
    ])
    per_owner: dict[str, int] = {}
    total = 0
    for owner, a, b in segments:
        sched = intersect([(a, b)], view.shift_segments(owner))
        charge = measure(sched) - measure(intersect(sched, pause_ivs))
        per_owner[owner] = per_owner.get(owner, 0) + charge
        total += charge
    return total, per_owner, terminal, pauses
