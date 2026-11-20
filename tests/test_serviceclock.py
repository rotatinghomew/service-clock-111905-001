import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from serviceclock.clocks import duty_clock
from serviceclock.commitments import appointment_states, commitment_status, valid_appointment
from serviceclock.expedite import compare_options, decline_impact, issue_option
from serviceclock.ledger import Ledger
from serviceclock.reports import desk_report, handover_report

FIXTURES = ROOT / "fixtures"


class ServiceClockTest(unittest.TestCase):
    def setUp(self):
        self.ledger = Ledger.load(FIXTURES)

    # ---- 班表：修订以 received 起可知，业务区间仍用 start/end ----
    def test_shift_revision_known_by_received(self):
        self.assertEqual(self.ledger.view("10:02").shift_segments("U2"), [(480, 720)])
        self.assertEqual(self.ledger.view("10:03").shift_segments("U2"), [(480, 645)])

    # ---- 责任项时钟：停钟理由重叠不重复扣时间；撤销改变有效区间 ----
    def test_pause_overlap_not_double_counted(self):
        clk = duty_clock(self.ledger.view("09:00"), "D11")
        # 资料 08:20-08:25→08:35 与 联络 08:30→08:48-08:55 重叠段只扣一次
        self.assertEqual((clk.elapsed_min, clk.elapsed_max), (25, 37))
        self.assertFalse(clk.closed)

    def test_void_receipt_changes_pause_intervals(self):
        before = duty_clock(self.ledger.view("10:11"), "D11")
        self.assertEqual((before.elapsed_min, before.elapsed_max), (33, 45))
        after = duty_clock(self.ledger.view("10:40"), "D11")
        # E17 撤销 E08 后，资料停钟失去关闭点，计到完结
        self.assertEqual((after.elapsed_min, after.elapsed_max), (20, 25))
        self.assertTrue(after.closed)
        self.assertEqual(after.status, "在限时内")

    def test_clock_counts_only_within_applicable_shift(self):
        clk = duty_clock(self.ledger.view("09:30"), "D31")
        # D31 08:40 开立，但 U3 班表 09:00 才开始
        self.assertEqual((clk.elapsed_min, clk.elapsed_max), (30, 30))

    def test_transfer_keeps_prior_wait_on_original_owner(self):
        clk = duty_clock(self.ledger.view("10:40"), "D13")
        self.assertEqual(clk.status, "已失守")
        self.assertEqual(clk.owners["U2"], (65, 80))
        self.assertEqual(clk.owners["U3"], (41, 64))
        self.assertEqual((clk.elapsed_min, clk.elapsed_max), (121, 129))

    # ---- 承诺生命周期：候约/通知已发/已接受是不同事实 ----
    def test_appointment_facts_are_distinct(self):
        states, _ = appointment_states(self.ledger.view("08:21"))
        self.assertEqual(states["B1"].state, "候约")
        states, _ = appointment_states(self.ledger.view("08:22"))
        self.assertEqual(states["B1"].state, "通知已发")
        states, _ = appointment_states(self.ledger.view("08:24"))
        self.assertEqual(states["B1"].state, "已接受")

    def test_old_appointment_stands_while_proposal_pending(self):
        states, _ = appointment_states(self.ledger.view("09:50"))
        self.assertEqual(states["B6"].state, "暂占中")
        self.assertEqual(states["B1"].state, "已接受")  # 居民确认前旧约仍有效

    def test_expired_hold_released_and_not_revived_by_late_report(self):
        states, reservations = appointment_states(self.ledger.view("10:05"))
        self.assertEqual(states["B8"].state, "已释放")
        self.assertIn("不能复活", states["B8"].detail)
        # 已释放的暂占不能因事后回报的发生时间再占一次
        self.assertFalse(any(r[2] == "B8" for r in reservations))
        states, _ = appointment_states(self.ledger.view("10:00"))
        self.assertEqual(states["B5"].state, "失效")

    def test_confirmation_rejected_when_shifts_changed(self):
        states, _ = appointment_states(self.ledger.view("10:40"))
        # B6 签收时 U2 班表已缩短，整组不可共同履行，不能替代旧约
        self.assertEqual(states["B6"].state, "确认无效")
        self.assertIn("U2", states["B6"].detail)
        self.assertEqual(states["B1"].state, "已接受")
        self.assertEqual(valid_appointment(self.ledger.view("10:40"), "C1").id, "B1")

    # ---- 承诺分类：已失守 / 可能失守 / 可挽救 ----
    def test_commitment_categories(self):
        rep = commitment_status(self.ledger.view("10:40"), "C1")
        self.assertEqual(rep.status, "可能失守")  # D12 到场区间跨越窗口末
        self.assertIn("E20", rep.evidence)
        rep = commitment_status(self.ledger.view("10:25"), "C1")
        self.assertEqual(rep.status, "可能失守")  # D12 已退单待重派
        self.assertEqual(commitment_status(self.ledger.view("10:40"), "C2").status, "可挽救")
        self.assertEqual(commitment_status(self.ledger.view("10:46"), "C2").status, "已失守")
        self.assertEqual(commitment_status(self.ledger.view("10:40"), "C3").status, "待履约")
        self.assertEqual(commitment_status(self.ledger.view("10:40"), "C4").status, "已失守")
        self.assertEqual(commitment_status(self.ledger.view("10:40"), "C5").status, "需重新协商")

    # ---- 退单影响 ----
    def test_decline_impact(self):
        imp = decline_impact(self.ledger.view("09:55"), "D12")
        self.assertTrue(any("B1" in line for line in imp.recontact))
        self.assertIn(("D13", "其到场仍计入当前承诺窗口"), imp.worth_continuing)
        breached = {clk.duty_id: clk.status for clk in imp.breach_ledger}
        self.assertEqual(breached.get("D12"), "已失守")
        self.assertEqual(breached.get("D13"), "已失守")
        self.assertNotIn("D11", breached)  # 停钟有效，仍在限时内

    # ---- 催办方案：资源不重复承诺、联合上门需预审且同时段可用 ----
    def test_no_feasible_joint_window_for_c5(self):
        opts = {o.kind: o for o in compare_options(self.ledger.view("10:40"), "C5")}
        opt = opts["new_joint_window"]
        self.assertFalse(opt.feasible)
        joined = "；".join(opt.reasons)
        self.assertIn("ROOM", joined)
        self.assertIn("U3", joined)
        self.assertFalse(any(o.feasible for o in opts.values()))

    def test_handoff_option_for_c2(self):
        opts = compare_options(self.ledger.view("10:46"), "C2")
        handoffs = [o for o in opts if o.kind == "handoff" and o.feasible]
        self.assertEqual(len(handoffs), 1)
        self.assertEqual(handoffs[0].assignments, {"D22": "U3"})
        self.assertTrue(any("C2" in line for line in handoffs[0].avoids))
        # 受保护的既有预约不能被挪给新单
        self.assertFalse(any(o.kind == "new_joint_window" for o in opts))

    def test_infeasible_option_cannot_be_issued(self):
        view = self.ledger.view("10:40")
        opt = [o for o in compare_options(view, "C5") if o.kind == "new_joint_window"][0]
        with self.assertRaises(ValueError):
            issue_option(self.ledger, view, opt)

    # ---- 发出与交接：本地业务回执、处置风险、未处理原因 ----
    def test_issue_handoff_and_handover(self):
        view = self.ledger.view("10:46")
        opt = [o for o in compare_options(view, "C2")
               if o.kind == "handoff" and o.feasible][0]
        action = issue_option(self.ledger, view, opt)
        # 所有收发用本地业务回执
        self.assertEqual(len(action.receipts), 1)
        rc = self.ledger.outbox[0]
        self.assertEqual((rc.target, rc.kind, rc.detail), ("D22", "transfer", "U3"))
        # 代班后承诺回到可挽救
        later = self.ledger.view("10:47")
        self.assertEqual(commitment_status(later, "C2").status, "可挽救")
        rep = handover_report(later, action.id)
        self.assertTrue(any("C2" in line for line in rep["risks_addressed"]))
        self.assertEqual(set(rep["valid_appointments"]), {"C1", "C2", "C3", "C4"})
        unhandled = {e["case"]: e for e in rep["unhandled"]}
        self.assertIn("C5", unhandled)
        self.assertEqual(unhandled["C5"]["status"], "需重新协商")
        self.assertTrue(any("ROOM" in r or "U3" in r for r in unhandled["C5"]["reasons"]))
        self.assertNotIn("C2", unhandled)

    # ---- 值班台查询：按窗口查，带记录与时钟区别 ----
    def test_desk_report_by_window(self):
        report = desk_report(self.ledger.view("10:40"), window="W2")
        duties = {c.duty_id: c for e in report["cases"] for c in e["duties"]}
        self.assertEqual(set(duties), {"D13", "D22", "D31", "D53"})
        self.assertEqual(duties["D31"].status, "已失守")
        self.assertTrue(duties["D31"].evidence is not None)
        self.assertTrue(any("D31" in x for x in report["summary"]["已失守"]))
        self.assertTrue(any("承诺" in x for x in report["summary"]["可挽救"]))

    def test_desk_report_shows_clock_distinction(self):
        report = desk_report(self.ledger.view("10:40"), case="C1")
        entry = report["cases"][0]
        self.assertIn("居民承诺窗口", entry["commitment"].clock)
        self.assertTrue(all("责任项时钟" in c.clock for c in entry["duties"]))


if __name__ == "__main__":
    unittest.main()
