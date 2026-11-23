from __future__ import annotations

from pathlib import Path
import sys
import unittest

from maa_resonance.logic.planning import (
    AccountSnapshot,
    PrisonOrder,
    PrisonPlanOptions,
    PrisonSnapshot,
    PurchaseOffer,
    WalletSnapshot,
    detect_prison_phase,
    evaluate_black_moon_order,
    evaluate_exchange_shop_item,
    evaluate_purchase_offer,
    format_prison_plan_markdown,
    load_prison_strategy_catalog,
    plan_prison,
    raw_workshop_remaining_cost,
    recommended_dorm_and_workshop_count,
    remaining_power_motor_cost,
    sewing_machine_remaining_cost,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "tools"))

import sync_planning_catalogs as sync_tool


class PrisonPlannerTests(unittest.TestCase):
    def test_static_catalog_totals_match_bwiki_and_guide(self) -> None:
        catalog = load_prison_strategy_catalog()
        self.assertEqual(len(catalog["rush_leveling_goods"]), 21)
        self.assertEqual(len(catalog["profit_harvest_goods"]), 3)
        self.assertEqual(len(catalog["power_motors"]), 20)

        motor_total = remaining_power_motor_cost(0, catalog)
        self.assertEqual(motor_total["remaining_slots"], 20)
        self.assertEqual(motor_total["total_remaining_huashi"], 3500)
        self.assertEqual(motor_total["total_remaining_coins"], 28_700_000)

        sewing_total = sewing_machine_remaining_cost(1, catalog)
        self.assertEqual(sewing_total["remaining_levels"], 9)
        self.assertEqual(sewing_total["coins"], 1_650_000)
        self.assertEqual(sewing_total["work_tickets"], 16_500)

        self.assertEqual(raw_workshop_remaining_cost(0, catalog), 22_000_000)
        self.assertEqual(raw_workshop_remaining_cost(1, catalog), 21_900_000)

    def test_stepwise_ladder_ending_in_6(self) -> None:
        expected = [
            (1, 1, 6),
            (5, 1, 6),
            (6, 2, 16),
            (7, 2, 16),
            (15, 2, 16),
            (16, 3, 26),
            (26, 4, 36),
            (36, 5, 46),
            (46, 6, None),
            (60, 6, None),
        ]
        for level, exp_cap, exp_next in expected:
            with self.subTest(level=level):
                self.assertEqual(recommended_dorm_and_workshop_count(level), (exp_cap, exp_next))

    def test_plan_lv2_flags_confinement_blocker(self) -> None:
        snapshot = AccountSnapshot(
            uid="8820083699",
            available_cities=["云岫桥基地", "海角城", "岚心城"],
            wallet=WalletSnapshot(coins=37_615_061, huashi=14_880),
            prison=PrisonSnapshot(
                level=2,
                work_tickets=800,
                power_used=1350,
                power_max=12000,
                prisoners_current=6,
                prisoners_capacity=12,
                dorm_count=1,
                production_workshop_count=1,
                buildings={"power_center": 2, "research_center": 2, "infirmary": 1},
            ),
        )
        report = plan_prison(snapshot)
        self.assertEqual(report.phase, "rush_leveling")
        blockers = [r for r in report.building_recommendations if r.priority == "blocker"]
        self.assertTrue(any(r.building_id == "confinement_room" and "LV3" in r.action for r in blockers))

    def test_plan_lv7_matches_live_state_and_guardrails(self) -> None:
        snapshot = AccountSnapshot(
            uid="8820083699",
            available_cities=["云岫桥基地", "海角城", "岚心城"],
            wallet=WalletSnapshot(coins=31_641_061, huashi=14_880),
            prison=PrisonSnapshot(
                level=7,
                work_tickets=7500,
                power_used=5150,
                power_max=13800,
                prisoners_current=11,
                prisoners_capacity=24,
                raw_warehouse_used=0,
                raw_warehouse_cap=250,
                finished_warehouse_used=0,
                finished_warehouse_cap=250,
                dorm_count=2,
                production_workshop_count=2,
                buildings={
                    "power_center": 3,
                    "research_center": 3,
                    "raw_sewing": 1,
                    "raw_synthetic": 1,
                    "infirmary": 1,
                    "confinement_room": 1,
                },
            ),
        )
        report = plan_prison(snapshot, PrisonPlanOptions(reserve_coins=15_000_000, player_level=71))
        self.assertEqual(report.spendable_coins, 16_641_061)
        self.assertEqual(report.recommended_dorm_and_workshop_cap, 2)
        self.assertEqual(report.next_ladder_unlock_level, 16)
        self.assertEqual(report.recommended_raw_predeposit, 500_000)

        by_id = {r.building_id: r for r in report.building_recommendations}
        self.assertIn("LV4", by_id["research_center"].action)
        self.assertIn("LV6", by_id["research_center"].action)
        self.assertEqual(by_id["raw_sewing"].priority, "defer")
        self.assertIn("研发中心 LV7", by_id["raw_sewing"].action)
        self.assertEqual(by_id["dormitory"].priority, "defer")
        self.assertIn("LV16", by_id["dormitory"].action)
        self.assertEqual(by_id["parole_room"].priority, "ignore")
        self.assertEqual(by_id["incident_rooms_bundle"].priority, "ignore")

        guarded = {g.action_id: g for g in report.guarded_huashi_actions}
        self.assertEqual(guarded["power_center_motors"].status, "blocked_by_guardrail")
        self.assertEqual(guarded["power_center_motors"].remaining_total_huashi, 3500)
        self.assertEqual(guarded["warehouse_huashi_expansion"].status, "blocked_by_guardrail")

        md = format_prison_plan_markdown(report)
        self.assertIn("LV 7", md)
        self.assertIn("3,500", md)

    def test_missing_lanxin_warning_and_lv9_anchors_and_overbuild_warning(self) -> None:
        snapshot = AccountSnapshot(
            uid="10001",
            available_cities=["云岫桥基地", "7号自由港", "修格里城"],
            wallet=WalletSnapshot(coins=20_000_000, huashi=2000),
            prison=PrisonSnapshot(
                level=9,
                dorm_count=3,
                production_workshop_count=2,
                transfer_anchors=["海角城"],
                buildings={"power_center": 5, "research_center": 6, "confinement_room": 1, "infirmary": 1},
            ),
        )
        report = plan_prison(
            snapshot,
            PrisonPlanOptions(allow_huashi_motors=True, allow_huashi_warehouse=True, player_level=80),
        )
        self.assertTrue(any("岚心城" in w for w in report.prerequisite_warnings))
        self.assertEqual(report.recommended_raw_predeposit, 2_500_000)
        by_id = {r.building_id: r for r in report.building_recommendations}
        self.assertEqual(by_id["dormitory"].priority, "warning")
        self.assertEqual(by_id["transfer_center"].priority, "high")
        self.assertIn("岚心城", by_id["transfer_center"].action)
        for g in report.guarded_huashi_actions:
            self.assertEqual(g.status, "opt_in_enabled")

    def test_profit_harvest_transition_and_order_decisions(self) -> None:
        early_prison = PrisonSnapshot(level=5, finished_warehouse_used=50, finished_warehouse_cap=250)
        self.assertEqual(
            evaluate_black_moon_order(
                PrisonOrder(item_name="冲锋衣", quantity=60, order_type="daily"),
                early_prison,
                "rush_leveling",
            ).action,
            "delete_free",
        )
        self.assertEqual(
            evaluate_black_moon_order(
                PrisonOrder(item_name="冲锋衣", quantity=1200, order_type="weekly", stock_owned=1200),
                early_prison,
                "rush_leveling",
            ).action,
            "deliver",
        )
        cowboy_early = evaluate_black_moon_order(
            PrisonOrder(item_name="牛仔布", quantity=180, order_type="daily"),
            early_prison,
            "rush_leveling",
        )
        self.assertEqual(cowboy_early.action, "produce_then_deliver")
        self.assertTrue(cowboy_early.overflow_warning)

        late_prison = PrisonSnapshot(level=24, finished_warehouse_used=50, finished_warehouse_cap=250)
        cowboy_late = evaluate_black_moon_order(
            PrisonOrder(item_name="牛仔布", quantity=180, order_type="daily"),
            late_prison,
            "rush_leveling",
        )
        self.assertEqual(cowboy_late.action, "delete_free")
        self.assertTrue(cowboy_late.overflow_warning)

        self.assertEqual(
            evaluate_black_moon_order(
                PrisonOrder(item_name="普通布袋", quantity=1200, order_type="weekly"),
                late_prison,
                "rush_leveling",
            ).action,
            "skip_weekly",
        )
        self.assertEqual(
            evaluate_black_moon_order(
                PrisonOrder(item_name="普通布袋", quantity=60, order_type="daily"),
                late_prison,
                "rush_leveling",
            ).action,
            "delete_free",
        )
        silk_pajama = evaluate_black_moon_order(
            PrisonOrder(item_name="真丝睡衣", quantity=60, order_type="daily"),
            late_prison,
            "rush_leveling",
        )
        self.assertEqual(silk_pajama.action, "produce_then_deliver")
        self.assertTrue(silk_pajama.defer_until_surplus)

        graduated_snapshot = AccountSnapshot(
            uid="999",
            available_cities=["云岫桥基地", "海角城", "岚心城"],
            wallet=WalletSnapshot(coins=120_000_000, huashi=5000),
            prison=PrisonSnapshot(
                level=60,
                sewing_machines_maxed=True,
                buildings={
                    "raw_sewing": 10,
                    "raw_synthetic": 10,
                    "raw_plant": 10,
                    "raw_animal": 10,
                    "confinement_room": 1,
                    "infirmary": 1,
                },
                active_orders=[PrisonOrder(item_name="蕾丝连衣裙", quantity=180, order_type="daily")],
            ),
        )
        self.assertEqual(detect_prison_phase(graduated_snapshot.prison, PrisonPlanOptions()), "profit_harvest")
        grad_report = plan_prison(graduated_snapshot)
        self.assertEqual(grad_report.phase, "profit_harvest")
        self.assertEqual(grad_report.order_decisions[0].action, "skip_profit_phase")
        md = format_prison_plan_markdown(grad_report)
        self.assertIn("真丝睡衣", md)
        self.assertIn("10 小时", md)
        self.assertIn("云岫桥基地", md)

    def test_purchase_station_and_exchange_shop_filters(self) -> None:
        lv36 = PrisonSnapshot(level=36)
        self.assertEqual(
            evaluate_purchase_offer(PurchaseOffer(from_item="缝纫工具包", to_item="蚕丝"), lv36).action,
            "block",
        )
        alias_blocked = evaluate_purchase_offer(PurchaseOffer(from_item="缝纫包", to_item="蚕丝"), lv36)
        self.assertEqual(alias_blocked.action, "block")
        self.assertEqual(alias_blocked.normalized_from_item, "缝纫工具包")
        self.assertEqual(
            evaluate_purchase_offer(PurchaseOffer(from_item="棉花", to_item="纯棉布料"), lv36).action,
            "accept",
        )

        self.assertEqual(evaluate_exchange_shop_item("超级帮帮券", "huashi").action, "block_huashi")
        self.assertEqual(evaluate_exchange_shop_item("超级帮帮券", "work_tickets").action, "skip_renewable")
        self.assertEqual(evaluate_exchange_shop_item("逮捕令", "work_tickets").action, "skip_renewable")
        self.assertEqual(evaluate_exchange_shop_item("拉普拉斯协议", "work_tickets").action, "buy_one_time")
        self.assertEqual(evaluate_exchange_shop_item("自观测胶卷", "work_tickets").action, "buy_one_time")
        self.assertEqual(evaluate_exchange_shop_item("蕾丝连衣裙缝制法", "work_tickets").action, "buy_one_time")

    def test_bwiki_wikitext_parsers_offline_and_delay_guard(self) -> None:
        motors_wt = """
{{#invoke: 数据| 生成列表
| 表格列数 = 2
| 标题1 = 模块安装次数 #style="width:7%;"
| 标题2 = 所需材料
| 模块安装次数1 = 1*
| 所需材料1 = 桦石：100、铁盟币：10000
| 模块安装次数20 = 20*
| 所需材料20 = 桦石：250、铁盟币：4000000
}}
{{#invoke: 数据| 生成列表
| 表格列数 = 3
| 标题1 = 可兑换物
| 标题2 = 可兑换次数
| 标题3 = 所需材料
| 可兑换物16 = 拉普拉斯协议：1
| 可兑换次数16 = *2
| 所需材料16 = 整顿中心工票：8000
| 可兑换物21 = 蕾丝连衣裙缝制法：1
| 可兑换次数21 = *1
| 所需材料21 = 铁盟币：980000、整顿中心工票：9800
}}
"""
        motors = sync_tool.parse_power_motors_wikitext(motors_wt)
        self.assertEqual(motors, [{"slot": 1, "huashi": 100, "coins": 10000}, {"slot": 20, "huashi": 250, "coins": 4000000}])

        shop = sync_tool.parse_exchange_shop_wikitext(motors_wt)
        self.assertEqual(len(shop), 2)
        self.assertFalse(shop[0]["is_recipe"])
        self.assertTrue(shop[1]["is_recipe"])
        self.assertEqual(shop[1]["coins"], 980000)

        sewing_wt = """
{{#invoke: 数据| 生成列表
| 表格列数 = 3
| 标题1 = 等级
| 标题2 = 额外产出
| 标题3 = 升级所需材料
| 等级1 = *1
| 额外产出1 = *1.0%
| 升级所需材料1 = 铁盟币：10000、整顿中心工票：100
| 等级10 = *10
| 额外产出10 = *10.0%
| 升级所需材料10 = 无
}}
"""
        sewing = sync_tool.parse_sewing_machine_upgrades_wikitext(sewing_wt)
        self.assertEqual(len(sewing), 1)
        self.assertEqual(sewing[0]["from_level"], 1)
        self.assertEqual(sewing[0]["to_level"], 2)
        self.assertEqual(sewing[0]["work_tickets"], 100)

        raw_wt = """
{{#invoke: 数据| 生成列表
| 表格列数 = 6
| 标题1 = 等级
| 标题2 = 电力需求
| 标题3 = 囚犯数量
| 标题4 = 额外产出
| 标题5 = 升级所需时间
| 标题6 = 升级所需材料
| 等级2 = *2
| 电力需求2 = *700
| 囚犯数量2 = *7
| 额外产出2 = *2.0%
| 升级所需时间2 = *15min
| 升级所需材料2 = 铁盟币：300000
}}
"""
        raw_upgrades = sync_tool.parse_raw_workshop_upgrades_wikitext(raw_wt)
        self.assertEqual(
            raw_upgrades,
            [
                {
                    "from_level": 1,
                    "to_level": 2,
                    "coins": 300000,
                    "power_cost": 700,
                    "prisoner_slots": 7,
                    "extra_output_percent": 2.0,
                    "build_minutes": 15,
                }
            ],
        )

        orders_wt = """
{{#invoke: 数据| 生成列表
| 表格列数 = 4
| 标题1 = 解锁所需等级
| 标题2 = 需求物资
| 标题3 = 权重
| 标题4 = 奖励
| 解锁所需等级1 = *1
| 需求物资1 = 牛仔布：180
| 权重1 = *10
| 奖励1 = 铁盟币：73143、整顿中心经验：15、整顿中心工票：750
}}
"""
        orders = sync_tool.parse_black_moon_orders_wikitext(orders_wt)
        self.assertEqual(
            orders,
            [
                {
                    "unlock_prison_level": 1,
                    "item_name": "牛仔布",
                    "quantity": 180,
                    "weight": 10,
                    "reward_coins": 73143,
                    "reward_exp": 15,
                    "reward_work_tickets": 750,
                }
            ],
        )

        with self.assertRaises(ValueError):
            sync_tool.sync_bwiki_prison_catalog(delay_seconds=0.5)


if __name__ == "__main__":
    unittest.main()
