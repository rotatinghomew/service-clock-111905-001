"""命令行：python3 -m serviceclock --now HH:MM <status|impact|options|handover>"""
from __future__ import annotations

import argparse

from .commitments import appointment_states
from .expedite import compare_options, decline_impact, issue_option
from .ledger import Ledger
from .model import fmt_hhmm, parse_hhmm
from .reports import desk_report, handover_report


def _print_status(view, args):
    report = desk_report(view, case=args.case, grid=args.grid, window=args.window)
    print(f"== 值班台履约账 @ {report['now']} ==")
    for label, items in report["summary"].items():
        print(f"[{label}]")
        for it in items:
            print(f"  - {it}")
    for entry in report["cases"]:
        rep = entry["commitment"]
        print(f"\n事项 {entry['case']}（{entry['grid']}）承诺：{rep.describe()}")
        print(f"  采用记录：{','.join(rep.evidence) or '无'}；时钟：{rep.clock}")
        for clk in entry["duties"]:
            print(f"  {clk.describe()}")


def _print_impact(view, args):
    imp = decline_impact(view, args.duty)
    print(f"== 退单影响 {imp.duty_id}（事项 {imp.case}）@ {fmt_hhmm(view.now)} ==")
    print("[只能重新联系的承诺]")
    for line in imp.recontact:
        print(f"  - {line}")
    print("[仍值得办的并行任务]")
    for duty_id, why in imp.worth_continuing:
        print(f"  - {duty_id}：{why}")
    print("[进入原时限违约账的等待]")
    for clk in imp.breach_ledger:
        owners = "，".join(f"{o} {lo}-{hi} 分钟" for o, (lo, hi) in clk.owners.items())
        print(f"  - {clk.describe()}；责任方：{owners}")


def _print_options(view, args):
    print(f"== 催办方案比较 {args.case} @ {fmt_hhmm(view.now)} ==")
    opts = compare_options(view, args.case)
    if not opts:
        print("  无可比较的方案")
    for opt in opts:
        mark = "可兑现" if opt.feasible else "不可兑现"
        print(f"[{mark}] {opt.kind}: {opt.description}")
        if opt.slot:
            print(f"    窗口 {fmt_hhmm(opt.slot[0])}-{fmt_hhmm(opt.slot[1])} 资源 {','.join(opt.resources)}")
        for line in opt.avoids:
            print(f"    减少确定失约：{line}")
        for line in opt.costs:
            print(f"    代价：{line}")
        for line in opt.reasons:
            print(f"    原因：{line}")


def _print_handover(ledger, view, args):
    opts = [o for o in compare_options(view, args.case) if o.feasible]
    if not opts:
        print(f"事项 {args.case} 当前没有可兑现的安排")
        return
    expires = parse_hhmm(args.expires) if args.expires else view.now + 20
    action = issue_option(ledger, view, opts[0], expires=expires)
    print(f"== 已发出催办 {action.id}（{action.summary}）==")
    print(f"  本地业务回执：{','.join(action.receipts)}")
    rep = handover_report(ledger.view(view.now), action.id)
    print("[该催办处置过的风险]")
    for line in rep["risks_addressed"]:
        print(f"  - {line}")
    print("[当前仍有效的预约]")
    for case, info in rep["valid_appointments"].items():
        print(f"  - {case}: {info['appointment']} {info['window']}（{info['state']}）")
    print("[未能处理的原因]")
    for entry in rep["unhandled"]:
        print(f"  - {entry['case']} {entry['status']}：{'；'.join(entry['reasons'])}")


def main(argv=None):
    parser = argparse.ArgumentParser(prog="serviceclock", description="联办履约与催办值班台")
    parser.add_argument("--fixtures", default="fixtures", help="源记录目录")
    parser.add_argument("--now", required=True, help="查询时点 HH:MM")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_status = sub.add_parser("status", help="按事项/居民/窗口查承诺账")
    p_status.add_argument("--case")
    p_status.add_argument("--grid")
    p_status.add_argument("--window")
    p_impact = sub.add_parser("impact", help="退单影响")
    p_impact.add_argument("--duty", required=True)
    p_options = sub.add_parser("options", help="催办方案比较")
    p_options.add_argument("--case", required=True)
    p_handover = sub.add_parser("handover", help="发出最优方案并生成交接班")
    p_handover.add_argument("--case", required=True)
    p_handover.add_argument("--expires", help="新约确认截止 HH:MM")
    args = parser.parse_args(argv)
    ledger = Ledger.load(args.fixtures)
    view = ledger.view(args.now)
    if args.cmd == "status":
        _print_status(view, args)
    elif args.cmd == "impact":
        _print_impact(view, args)
    elif args.cmd == "options":
        _print_options(view, args)
    elif args.cmd == "handover":
        _print_handover(ledger, view, args)


if __name__ == "__main__":
    main()
