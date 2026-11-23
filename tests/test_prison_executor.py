from __future__ import annotations

import unittest

from maa_resonance.logic.planning import (
    PrisonActionOutcome,
    PrisonPlanOptions,
    PrisonRunReceipt,
    build_prison_execution_plan,
    build_semi_auto_guidance,
    format_mxu_plain_summary,
    format_planning_report_html,
    format_prison_plan_markdown,
    plan_prison,
    snapshot_from_account_payload,
)


class PrisonExecutorTests(unittest.TestCase):
    def test_lv7_rush_leveling_do_buy_build_and_safety_guardrails(self) -> None:
        snap = snapshot_from_account_payload(
            {
                "uid": "8820083699",
                "trade": {"available_cities": ["云岫桥基地", "海角城", "岚心城"]},
                "wallet": {"coins": 31_771_061, "huashi": 14_880},
                "prison": {
                    "level": 7,
                    "work_tickets": 7500,
                    "power_used": 5150,
                    "power_max": 13800,
                    "dorm_count": 2,
                    "production_workshop_count": 2,
                    "buildings": {
                        "power_center": 3,
                        "research_center": 3,
                        "confinement_room": 1,
                        "infirmary": 1,
                        "raw_sewing": 1,
                        "raw_synthetic": 1,
                    },
                    "active_orders": [
                        {"item_name": "牛仔布", "quantity": 180, "order_type": "daily", "stock_owned": 180},
                        {"item_name": "冲锋衣", "quantity": 60, "order_type": "daily", "stock_owned": 0},
                    ],
                    "purchase_offers": [
                        {"from_item": "棉花", "to_item": "亚麻"},
                        {"from_item": "缝纫包", "to_item": "蚕丝"},
                    ],
                },
            }
        )
        opts = PrisonPlanOptions(reserve_coins=15_000_000, player_level=71)
        report = plan_prison(snap, opts)
        plan = build_prison_execution_plan(snap, report, opts)

        self.assertEqual(plan.phase, "rush_leveling")
        self.assertEqual(plan.coins_before, 31_771_061)
        self.assertGreaterEqual(plan.simulated_coins_after, 15_000_000)

        # 做什么：直交牛仔布、免费删冲锋衣、轮换排产含已解锁效率货、含原料预存
        do_types = {(s.action_type, s.target): s for s in plan.do_actions}
        self.assertTrue(do_types[("order_deliver", "牛仔布")].allowed)
        self.assertTrue(do_types[("order_delete_free", "冲锋衣")].allowed)
        produce_targets = [s.target for s in plan.do_actions if s.action_type == "produce_good" and s.allowed]
        self.assertTrue(produce_targets)
        self.assertNotIn("冲锋衣", produce_targets)
        self.assertTrue(do_types[("raw_predeposit", "缝纫工具原料车间")].allowed)
        self.assertTrue(do_types[("raw_predeposit", "人造纤维原料车间")].allowed)

        # 买什么：仓库铁盟币扩容放行、工票 7500 放行配方与胶卷、拉普拉斯差500、采购站安全转换放行
        buy_types = {(s.action_type, s.target): s for s in plan.buy_actions}
        self.assertTrue(buy_types[("warehouse_coin_expand", "仓库铁盟币扩容")].allowed)
        self.assertTrue(buy_types[("exchange_ticket_buy", "研发配方")].allowed)
        self.assertTrue(buy_types[("exchange_ticket_buy", "自观测胶卷")].allowed)
        self.assertFalse(buy_types[("exchange_ticket_buy", "拉普拉斯协议")].allowed)
        self.assertIn("500", buy_types[("exchange_ticket_buy", "拉普拉斯协议")].blocked_reason)
        self.assertTrue(buy_types[("purchase_convert", "棉花 → 亚麻")].allowed)

        # 造什么：研发 -> 电力（缝纫/人造原料 LV1->LV2 需研发中心 LV7，植物/动物需研发LV4/LV5，均正确拦截并附前置提示）
        build_by_target = {s.target: s for s in plan.build_actions}
        self.assertTrue(build_by_target["研发中心"].allowed)
        self.assertTrue(build_by_target["电力中心"].allowed)
        self.assertFalse(build_by_target["缝纫工具原料车间"].allowed)
        self.assertIn("研发中心 LV7", build_by_target["缝纫工具原料车间"].blocked_reason)
        self.assertFalse(build_by_target["人造纤维原料车间"].allowed)
        self.assertIn("研发中心 LV7", build_by_target["人造纤维原料车间"].blocked_reason)
        self.assertFalse(build_by_target["植物纤维原料车间"].allowed)
        self.assertFalse(build_by_target["动物纤维原料车间"].allowed)

        # 模拟扣减精确核对：500k*2(原料预存) + 10k(仓库币扩仓) = 1,010,000（未扣未达前置的原料升级）
        self.assertEqual(plan.simulated_coins_after, 31_771_061 - 1_010_000)

        # 研发中心达 LV7 时，缝纫与人造原料 LV1->LV2 自动放行并精准扣减 300k*2
        snap_lv7_research = snapshot_from_account_payload(
            {
                "uid": "8820083699",
                "wallet": {"coins": 31_771_061, "huashi": 14_880},
                "prison": {
                    "level": 7,
                    "work_tickets": 7500,
                    "dorm_count": 2,
                    "production_workshop_count": 2,
                    "buildings": {
                        "power_center": 3,
                        "research_center": 7,
                        "confinement_room": 1,
                        "infirmary": 1,
                        "raw_sewing": 1,
                        "raw_synthetic": 1,
                    },
                },
            }
        )
        plan_unlocked = build_prison_execution_plan(
            snap_lv7_research, plan_prison(snap_lv7_research, opts), opts
        )
        unlocked_by_target = {s.target: s for s in plan_unlocked.build_actions}
        self.assertTrue(unlocked_by_target["缝纫工具原料车间"].allowed)
        self.assertEqual(unlocked_by_target["缝纫工具原料车间"].estimated_coins, 300_000)
        self.assertTrue(unlocked_by_target["人造纤维原料车间"].allowed)
        self.assertEqual(unlocked_by_target["人造纤维原料车间"].estimated_coins, 300_000)
        self.assertEqual(
            plan_unlocked.simulated_coins_after,
            31_771_061 - (300_000 * 2 + 500_000 * 2 + 10_000),
        )

        # 护栏拦截清单：假释室、治安挂件、电力电机、桦石扩仓、逮捕令、帮帮券、缝纫包->蚕丝、宿舍阶梯锁定
        blocked_targets = {s.target for s in plan.blocked_actions}
        for expected in (
            "假释室",
            "治安挂件房",
            "电力中心电机",
            "仓库桦石扩容",
            "逮捕令",
            "超级帮帮券",
            "超级帮帮券（10 桦石）",
            "缝纫包 → 蚕丝",
            "宿舍与生产车间阶梯",
        ):
            self.assertIn(expected, blocked_targets)

    def test_coin_reserve_floor_hard_lock(self) -> None:
        snap = snapshot_from_account_payload(
            {
                "uid": "floor_test",
                "wallet": {"coins": 15_150_000, "huashi": 14_880},
                "prison": {
                    "level": 7,
                    "work_tickets": 0,
                    "dorm_count": 2,
                    "production_workshop_count": 2,
                    "buildings": {
                        "power_center": 3,
                        "research_center": 7,
                        "confinement_room": 1,
                        "infirmary": 1,
                        "raw_sewing": 1,
                    },
                },
            }
        )
        opts = PrisonPlanOptions(reserve_coins=15_000_000, player_level=71)
        plan = build_prison_execution_plan(snap, plan_prison(snap, opts), opts)

        self.assertGreaterEqual(plan.simulated_coins_after, 15_000_000)
        self.assertEqual(plan.simulated_coins_after, 15_140_000)

        sew_step = next(s for s in plan.build_actions if s.target == "缝纫工具原料车间")
        self.assertFalse(sew_step.allowed)
        self.assertIn("保留底线", sew_step.blocked_reason)
        predep_step = next(s for s in plan.do_actions if s.action_type == "raw_predeposit")
        self.assertFalse(predep_step.allowed)
        self.assertTrue(any(s.target == "缝纫工具原料车间" and not s.allowed for s in plan.blocked_actions))

    def test_lv20_overflow_filter_and_profit_harvest_graduation(self) -> None:
        late_rush = snapshot_from_account_payload(
            {
                "uid": "late_rush",
                "wallet": {"coins": 60_000_000},
                "prison": {
                    "level": 22,
                    "dorm_count": 3,
                    "production_workshop_count": 3,
                    "buildings": {"power_center": 8, "research_center": 8, "confinement_room": 1, "infirmary": 1},
                },
            }
        )
        late_plan = build_prison_execution_plan(late_rush, plan_prison(late_rush))
        late_produce = [s.target for s in late_plan.do_actions if s.action_type == "produce_good"]
        self.assertNotIn("牛仔布", late_produce)
        self.assertNotIn("牛仔裤", late_produce)
        self.assertTrue(any(s.target == "牛仔布" and not s.allowed for s in late_plan.blocked_actions))

        graduated = snapshot_from_account_payload(
            {
                "uid": "grad_60",
                "wallet": {"coins": 120_000_000},
                "prison": {
                    "level": 60,
                    "graduated": True,
                    "sewing_machines_maxed": True,
                    "dorm_count": 6,
                    "production_workshop_count": 6,
                    "buildings": {
                        "power_center": 20,
                        "research_center": 10,
                        "raw_sewing": 10,
                        "raw_synthetic": 10,
                        "raw_plant": 10,
                        "raw_animal": 10,
                        "confinement_room": 1,
                        "infirmary": 1,
                    },
                    "active_orders": [{"item_name": "蕾丝连衣裙", "quantity": 180, "order_type": "daily", "stock_owned": 180}],
                },
            }
        )
        grad_plan = build_prison_execution_plan(graduated, plan_prison(graduated))
        self.assertEqual(grad_plan.phase, "profit_harvest")
        grad_produce = {s.target for s in grad_plan.do_actions if s.action_type == "produce_good"}
        self.assertEqual(grad_produce, {"真丝睡衣", "蕾丝连衣裙", "阿妮塔连体衣"})
        self.assertTrue(any(s.target == "蕾丝连衣裙" and not s.allowed for s in grad_plan.blocked_actions))

    def test_build_semi_auto_guidance_and_render_outputs(self) -> None:
        snap = snapshot_from_account_payload(
            {
                "uid": "8820083699<x>",
                "wallet": {"coins": 32_000_000, "huashi": 15_130},
                "prison": {
                    "level": 9,
                    "work_tickets": 2600,
                    "power_used": 13000,
                    "power_max": 14400,
                    "prisoners_current": 11,
                    "prisoners_capacity": 24,
                    "dorm_count": 2,
                    "production_workshop_count": 2,
                    "buildings": {
                        "research_center": 6,
                        "power_center": 5,
                        "confinement_room": 1,
                        "infirmary": 1,
                        "raw_sewing": 1,
                        "raw_synthetic": 1,
                    },
                    "active_orders": [
                        {"item_name": "冲锋衣", "quantity": 120, "order_type": "daily", "stock_owned": 0},
                    ],
                },
            }
        )
        opts = PrisonPlanOptions(reserve_coins=30_000_000, player_level=71)
        report = plan_prison(snap, opts)
        plan = build_prison_execution_plan(snap, report, opts)
        receipt = PrisonRunReceipt(
            mode="execute_safe_auto",
            scope="full_safe",
            coins_before=32_000_000,
            coins_after=32_000_000,
            tickets_before=2600,
            tickets_after=2600,
            huashi_before=15_130,
            huashi_after=15_130,
            skipped=[
                PrisonActionOutcome(
                    category="do",
                    action_type="produce_good",
                    target="1号生产车间:牛仔布",
                    status="skipped",
                    detail="已轮换尝试 牛仔布 均原料不足，请先在原料车间安排囚犯采集（未点确定）。",
                )
            ],
            guard_aborts=[
                PrisonActionOutcome(
                    category="guard",
                    action_type="power_center_guard",
                    target="电力中心",
                    status="guard_abort",
                    detail="右侧安装电机防误触拦截",
                )
            ],
        )

        guides = build_semi_auto_guidance(snap, report, plan, receipt)
        self.assertTrue(guides)
        ranks = [{"urgent": 0, "recommended": 1, "optional": 2}[g.priority] for g in guides]
        self.assertEqual(ranks, sorted(ranks))

        categories = {g.category for g in guides}
        # 狱内配员/LV0首建/删单/机台/财务开关/商店道具均由全自动接管，不再无故甩给人
        self.assertTrue({"prisoners", "setup", "huashi"}.issubset(categories))
        self.assertFalse({"unlock", "orders", "shop"} & categories)
        setup_steps = " ".join(s for g in guides if g.category == "setup" for s in g.steps)
        self.assertIn("转运中心", setup_steps)
        self.assertNotIn("财务中心", setup_steps)
        prisoner_steps = " ".join(s for g in guides if g.category == "prisoners" for s in g.steps)
        self.assertIn("自动接管", prisoner_steps)

        # 若实机某次自动首建或免费删单未完成（真实兜底），才生成对应的半自动接力提示
        receipt_fallback = receipt.model_copy(
            update={
                "skipped": list(receipt.skipped)
                + [
                    PrisonActionOutcome(
                        category="build",
                        action_type="building_unlock",
                        target="植物纤维原料车间",
                        status="skipped",
                        detail="总览未找到可升级入口（not_found）。",
                    ),
                    PrisonActionOutcome(
                        category="do",
                        action_type="order_delete_free",
                        target="冲锋衣",
                        status="skipped",
                        detail="点击删除后订单未变化，未确认删除成功。",
                    ),
                ]
            }
        )
        guides_fb = build_semi_auto_guidance(snap, report, plan, receipt_fallback)
        fb_cats = {g.category for g in guides_fb}
        self.assertTrue({"prisoners", "setup", "unlock", "orders", "huashi"}.issubset(fb_cats))
        unlock_titles = " ".join(g.title for g in guides_fb if g.category == "unlock")
        self.assertIn("植物纤维原料车间", unlock_titles)
        order_titles = " ".join(g.title for g in guides_fb if g.category == "orders")
        self.assertIn("冲锋衣", order_titles)

        md = format_prison_plan_markdown(report, semi_auto_guides=guides_fb)
        self.assertIn("### 半自动人工接力指引", md)
        self.assertIn("植物纤维原料车间", md)

        html_doc = format_planning_report_html(
            report,
            execution_plan=plan,
            run_receipt=receipt_fallback,
            semi_auto_guides=guides_fb,
            generated_at="2026-11-23 18:05:00",
        )
        self.assertIn("半自动人工接力指引", html_doc)
        self.assertIn("&lt;x&gt;", html_doc)
        self.assertNotIn("8820083699<x>", html_doc)

        summary_lines = format_mxu_plain_summary(
            report,
            execution_plan=plan,
            run_receipt=receipt_fallback,
            semi_auto_guides=guides_fb,
        )
        self.assertTrue(any(line.startswith("手动接力") for line in summary_lines))

        done_snap = snapshot_from_account_payload(
            {
                "uid": "done_60",
                "wallet": {"coins": 120_000_000},
                "prison": {
                    "level": 60,
                    "graduated": True,
                    "deposit_auto_refill": True,
                    "transfer_anchors": ["海角城", "岚心城"],
                    "prisoners_current": 36,
                    "prisoners_capacity": 36,
                    "work_tickets": 200,
                    "power_used": 10000,
                    "power_max": 20000,
                    "dorm_count": 6,
                    "production_workshop_count": 6,
                    "buildings": {
                        "power_center": 20,
                        "research_center": 10,
                        "raw_sewing": 10,
                        "raw_synthetic": 10,
                        "raw_plant": 10,
                        "raw_animal": 10,
                        "confinement_room": 1,
                        "infirmary": 1,
                    },
                },
            }
        )
        done_report = plan_prison(done_snap)
        done_plan = build_prison_execution_plan(done_snap, done_report)
        self.assertEqual(build_semi_auto_guidance(done_snap, done_report, done_plan), [])


if __name__ == "__main__":
    unittest.main()
