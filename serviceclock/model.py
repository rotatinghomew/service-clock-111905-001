"""源记录与值班台本地回执的数据模型。时间均为同一服务日的分钟数。"""
from __future__ import annotations

from dataclasses import dataclass


def parse_hhmm(text: str) -> int:
    hh, mm = text.strip().split(":")
    return int(hh) * 60 + int(mm)


def fmt_hhmm(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


@dataclass(frozen=True)
class Term:
    """居民受理单：due_minutes 是每个责任项各自的上限，duration 是联合约占用分钟。"""

    id: str
    grid: str
    intake: int
    due_minutes: int
    duration: int


@dataclass(frozen=True)
class Duty:
    """责任项：初始归属、窗口、技能与上门前置关系。"""

    id: str
    case: str
    window: str
    owner: str
    skill: str
    opened: int
    prerequisite: str | None
    stage: str  # prep=准备环节，visit=实地岗位


@dataclass(frozen=True)
class Shift:
    """班表：received 起对值班台可知，业务有效区间仍用 start/end。"""

    id: str
    resource: str
    window: str | None
    skills: frozenset[str]
    start: int
    end: int
    received: int
    supersedes: str | None


@dataclass(frozen=True)
class Appointment:
    """预约：original/protected 为既有通知，proposal 为待比较调整单（有确认截止）。"""

    id: str
    case: str
    start: int
    end: int
    resources: tuple[str, ...]
    kind: str
    prior: str | None
    expires: int | None
    received: int


@dataclass(frozen=True)
class Receipt:
    """业务回执：发生时刻不明时给发生界限 [occ_from, occ_to]。"""

    id: str
    target: str
    kind: str
    occ_from: int
    occ_to: int
    received: int
    detail: str | None
    supersedes: str | None
