from __future__ import annotations

from contextlib import redirect_stdout
import io
import json
import unittest

from maa_resonance.logic.planning import (
    AccountSnapshot,
    CrewGoal,
    CrewProgressionEntry,
    GrowthPlanOptions,
    MaterialInventoryEntry,
    PrisonSnapshot,
    WalletSnapshot,
    format_growth_plan_markdown,
    plan_growth,
)
from maa_resonance.logic.planning.cli import main as planning_cli_main


class GrowthPlannerTests(unittest.TestCase):
    def _sample_snapshot(self) -> AccountSnapshot:
        return AccountSnapshot(
            uid="8820083699",
            trade_role_resonance={"真咲": 4, "苍叶": 2},
            wallet=WalletSnapshot(coins=31_641_061, huashi=14_880),
            crew_progression={
                "真咲": CrewProgressionEntry(
                    level=70,
                    target_goal=CrewGoal(
                        target_level=80,
                        target_resonance=5,
                        required_coins=2_000_000,
                        required_materials={"桦树核仁": 6, "深眠木": 4},
                        priority=1,
                    ),
                ),
                "苍叶": CrewProgressionEntry(
                    level=60,
                    target_goal=CrewGoal(
                        target_level=70,
                        target_resonance=4,
                        required_coins=16_000_000,
                        required_materials={"桦树核仁": 4},
                        priority=2,
                    ),
                ),
            },
            materials_inventory={
                "桦树核仁": MaterialInventoryEntry(owned=3),
                "深眠木": MaterialInventoryEntry(owned=5),
            },
            prison=PrisonSnapshot(
                level=7,
                work_tickets=7500,
                prisoners_current=11,
                prisoners_capacity=24,
            ),
        )

    def test_crew_shortfall_aggregation_and_coin_reserve(self) -> None:
        snapshot = self._sample_snapshot()
        report = plan_growth(snapshot, GrowthPlanOptions(weekday=1, reserve_coins=15_000_000))
        self.assertEqual(report.spendable_coins, 16_641_061)
        self.assertEqual(report.total_required_coins, 18_000_000)
        self.assertEqual(report.coin_shortfall, 1_358_939)
        self.assertEqual(report.crew_plans[0].role_name, "真咲")
        self.assertEqual(report.crew_plans[0].current_resonance, 4)

        by_mat = {item.name: item for item in report.aggregated_material_shortfalls}
        self.assertEqual(by_mat["桦树核仁"].required, 10)
        self.assertEqual(by_mat["桦树核仁"].owned, 3)
        self.assertEqual(by_mat["桦树核仁"].shortfall, 7)
        self.assertEqual(by_mat["深眠木"].shortfall, 0)

        tickets = {item.item_name: item for item in report.ticket_reward_checks}
        self.assertEqual(tickets["自观测胶卷"].affordable_count, 1)
        self.assertEqual(tickets["拉普拉斯协议"].affordable_count, 0)
        self.assertEqual(tickets["拉普拉斯协议"].tickets_short_for_one, 500)

    def test_weekday_scheduling_and_prisoner_synergy(self) -> None:
        snapshot = self._sample_snapshot()

        mon_sweep = plan_growth(
            snapshot,
            GrowthPlanOptions(daily_clarity_budget=240, weekday=0, prefer_sweepable_event=True),
        )
        mon_ids = [s.stage_id for s in mon_sweep.stage_allocations]
        self.assertIn("equip_zhishi", mon_ids)
        self.assertIn("material_liren", mon_ids)
        self.assertIn("material_tiaodeng", mon_ids)
        self.assertIn("event_leyuan_shallow1", mon_ids)
        self.assertEqual(mon_sweep.clarity_remaining, 0)
        self.assertGreater(mon_sweep.expected_total_prisoners, 40)

        wed_haidao = plan_growth(
            snapshot,
            GrowthPlanOptions(daily_clarity_budget=240, weekday=2, prefer_sweepable_event=False),
        )
        wed_ids = [s.stage_id for s in wed_haidao.stage_allocations]
        self.assertIn("equip_yazhi", wed_ids)
        self.assertIn("event_haidao_sp4", wed_ids)

        tue_no_prisoner = plan_growth(
            snapshot,
            GrowthPlanOptions(daily_clarity_budget=240, weekday=1, need_prisoners=False),
        )
        tue_ids = [s.stage_id for s in tue_no_prisoner.stage_allocations]
        self.assertFalse(tue_no_prisoner.need_prisoners)
        self.assertIn("material_liren", tue_ids)
        self.assertIn("material_tiaodeng", tue_ids)
        self.assertNotIn("event_leyuan_shallow1", tue_ids)
        self.assertNotIn("event_haidao_sp4", tue_ids)

        md = format_growth_plan_markdown(mon_sweep)
        self.assertIn("特供·制式", md)
        self.assertIn("桦树核仁", md)

    def test_cli_dry_run_returns_valid_json(self) -> None:
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = planning_cli_main(
                [
                    "--prison-level",
                    "7",
                    "--coins",
                    "31641061",
                    "--huashi",
                    "14880",
                    "--tickets",
                    "7500",
                    "--weekday",
                    "0",
                    "--json",
                ]
            )
        self.assertEqual(rc, 0)
        parsed = json.loads(buf.getvalue())
        self.assertEqual(parsed["prison"]["prison_level"], 7)
        self.assertEqual(parsed["growth"]["weekday"], 0)


if __name__ == "__main__":
    unittest.main()
