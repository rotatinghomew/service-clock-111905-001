"""左闭右开时段的集合运算。时段用 (start, end) 分钟元组表示。"""
from __future__ import annotations


def merge(ivs):
    """合并重叠或相接的时段；重叠的等待理由在此去重，不重复扣时间。"""
    pts = sorted((s, e) for s, e in ivs if e > s)
    out = []
    for s, e in pts:
        if out and s <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], e))
        else:
            out.append((s, e))
    return out


def measure(ivs) -> int:
    return sum(e - s for s, e in ivs)


def intersect(a, b):
    out = []
    for s1, e1 in a:
        for s2, e2 in b:
            s, e = max(s1, s2), min(e1, e2)
            if e > s:
                out.append((s, e))
    return merge(out)


def subtract(ivs, blocks):
    blocks = merge(blocks)
    out = []
    for s, e in ivs:
        cur = [(s, e)]
        for bs, be in blocks:
            nxt = []
            for cs, ce in cur:
                if be <= cs or bs >= ce:
                    nxt.append((cs, ce))
                    continue
                if cs < bs:
                    nxt.append((cs, bs))
                if be < ce:
                    nxt.append((be, ce))
            cur = nxt
        out.extend(cur)
    return [(s, e) for s, e in out if e > s]
