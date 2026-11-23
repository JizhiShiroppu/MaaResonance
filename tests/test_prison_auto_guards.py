from __future__ import annotations

from contextlib import contextmanager
import importlib
import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np

from maa_resonance.logic.planning import (
    AccountSnapshot,
    PrisonActionOutcome,
    PrisonOrder,
    PrisonPlanOptions,
    PrisonRunReceipt,
    compute_predeposit_slider_x,
    find_production_recipe_card_point,
    find_production_select_all_point,
    find_room_bubble_point,
    format_mxu_plain_summary,
    format_planning_report_html,
    is_exchange_shop_entries,
    is_orders_foyer_entries,
    parse_exchange_shop_recipe_rows,
    parse_exchange_shop_top_bar,
    parse_predeposit_balance,
    parse_predeposit_modal_qty,
    parse_production_ready_panel,
    parse_room_build_panel,
    parse_single_order_card,
    parse_warehouse_modal_remaining,
    plan_prison,
    sample_roi_mean_brightness,
    snapshot_from_account_payload,
    verify_power_room_upgrade_tab_safe,
    verify_warehouse_coins_tab_safe,
)

ROOT = Path(__file__).resolve().parents[1]


@contextmanager
def _real_maa_agent_env():
    """临时移除测试桩 `maa.*` 模块，确保导入实装 CustomAction 并避免污染后续发现测试。"""
    saved: dict[str, object] = {}
    maa_mod = sys.modules.get("maa")
    stashed = maa_mod is not None and not hasattr(maa_mod, "__path__")
    if stashed:
        for name in list(sys.modules):
            if name == "maa" or name.startswith("maa."):
                saved[name] = sys.modules.pop(name)
    try:
        try:
            ca_mod = importlib.import_module("maa.custom_action")
            if not hasattr(ca_mod.CustomAction, "RunResult"):
                yield False
                return
            yield True
        except ImportError:
            yield False
    finally:
        if stashed:
            for name in list(sys.modules):
                if name == "maa" or name.startswith("maa."):
                    sys.modules.pop(name, None)
            sys.modules.update(saved)


def _make_tab_frame(
    left_roi: tuple[int, int, int, int],
    right_roi: tuple[int, int, int, int],
    *,
    left_rgb: tuple[int, int, int],
    right_rgb: tuple[int, int, int],
    height: int = 720,
    width: int = 1280,
) -> np.ndarray:
    img = np.zeros((height, width, 3), dtype=np.uint8)
    for roi, color in ((left_roi, left_rgb), (right_roi, right_rgb)):
        rx, ry, rw, rh = roi
        x1 = int(round(rx * width / 1280.0))
        y1 = int(round(ry * height / 720.0))
        x2 = int(round((rx + rw) * width / 1280.0))
        y2 = int(round((ry + rh) * height / 720.0))
        img[y1:y2, x1:x2] = np.array(color, dtype=np.uint8)
    return img


class PrisonAutoPixelGuardsTests(unittest.TestCase):
    def test_warehouse_coins_tab_guard_passes_and_fails_closed(self) -> None:
        left_roi = (372, 436, 40, 16)
        right_roi = (870, 436, 40, 16)
        ok_ocr = [{"text": "铁盟币 10000 剩余100次", "box": [380, 430, 180, 30]}]

        # 720p 与 1080p 下均识别左侧白底 + 右侧暗灰
        for h, w in ((720, 1280), (1080, 1920)):
            safe_img = _make_tab_frame(
                left_roi,
                right_roi,
                left_rgb=(253, 253, 251),
                right_rgb=(42, 42, 42),
                height=h,
                width=w,
            )
            ok, msg = verify_warehouse_coins_tab_safe(safe_img, ok_ocr)
            self.assertTrue(ok, msg=msg)

        # 页签反转（不小心切到右侧桦石页签）：右白左黑必须硬拦截
        swapped_img = _make_tab_frame(
            left_roi,
            right_roi,
            left_rgb=(42, 42, 42),
            right_rgb=(253, 253, 251),
        )
        ok_swap, reason_swap = verify_warehouse_coins_tab_safe(swapped_img, ok_ocr)
        self.assertFalse(ok_swap)
        self.assertIn("拦截", reason_swap)

        # 两边同白或同黑、缺铁盟币 OCR、空图全部 fail-closed
        both_dark = _make_tab_frame(left_roi, right_roi, left_rgb=(42, 42, 42), right_rgb=(42, 42, 42))
        self.assertFalse(verify_warehouse_coins_tab_safe(both_dark, ok_ocr)[0])
        both_white = _make_tab_frame(left_roi, right_roi, left_rgb=(250, 250, 250), right_rgb=(250, 250, 250))
        self.assertFalse(verify_warehouse_coins_tab_safe(both_white, ok_ocr)[0])
        safe_img = _make_tab_frame(left_roi, right_roi, left_rgb=(253, 253, 251), right_rgb=(42, 42, 42))
        self.assertFalse(verify_warehouse_coins_tab_safe(safe_img, [{"text": "桦石"}])[0])
        self.assertFalse(verify_warehouse_coins_tab_safe(None, ok_ocr)[0])
        self.assertIsNone(sample_roi_mean_brightness(None, left_roi))

    def test_power_room_upgrade_tab_guard_passes_and_fails_closed(self) -> None:
        left_roi = (805, 24, 40, 14)
        right_roi = (1180, 24, 40, 14)
        ok_ocr = [{"text": "房间升级", "box": [830, 22, 110, 32]}, {"text": "安装电机 0/20", "box": [1080, 22, 120, 32]}]

        safe_img = _make_tab_frame(left_roi, right_roi, left_rgb=(252, 252, 250), right_rgb=(36, 39, 46))
        self.assertTrue(verify_power_room_upgrade_tab_safe(safe_img, ok_ocr)[0])

        motor_tab_active = _make_tab_frame(left_roi, right_roi, left_rgb=(36, 39, 46), right_rgb=(252, 252, 250))
        ok, msg = verify_power_room_upgrade_tab_safe(motor_tab_active, ok_ocr)
        self.assertFalse(ok)
        self.assertIn("电力中心护栏", msg)
        self.assertFalse(verify_power_room_upgrade_tab_safe(safe_img, [])[0])
        self.assertFalse(verify_power_room_upgrade_tab_safe(None, ok_ocr)[0])


class PrisonAutoParsersTests(unittest.TestCase):
    def test_orders_foyer_and_single_card_parsers(self) -> None:
        foyer = [{"text": "黑月订单站"}, {"text": "运输订单"}, {"text": "每周订单"}, {"text": "交谈"}]
        self.assertTrue(is_orders_foyer_entries(foyer))
        self.assertFalse(is_orders_foyer_entries(foyer + [{"text": "需求物资"}]))

        body_entries = [
            {"text": "牛仔布", "box": [470, 172, 95, 28]},
            {"text": "需求物资", "box": [475, 208, 100, 24]},
            {"text": "180", "box": [735, 248, 60, 30]},
            {"text": "奖励物品", "box": [475, 450, 90, 24]},
            {"text": "73143", "box": [480, 505, 65, 22]},
        ]
        insufficient_btn = [
            {"text": "0", "box": [630, 620, 25, 22]},
            {"text": "物资不足", "box": [705, 608, 95, 26]},
        ]
        parsed_short = parse_single_order_card(body_entries, insufficient_btn)
        self.assertIsNotNone(parsed_short)
        assert parsed_short is not None
        self.assertEqual(parsed_short["item_name"], "牛仔布")
        self.assertEqual(parsed_short["quantity"], 180)
        self.assertEqual(parsed_short["stock_owned"], 0)
        self.assertFalse(parsed_short["deliverable"])

        ready_btn = [
            {"text": "210", "box": [630, 620, 35, 22]},
            {"text": "交付", "box": [720, 608, 60, 26]},
        ]
        parsed_ok = parse_single_order_card(body_entries, ready_btn)
        assert parsed_ok is not None
        self.assertTrue(parsed_ok["deliverable"])
        self.assertEqual(parsed_ok["stock_owned"], 210)

    def test_exchange_shop_top_bar_and_recipe_rows(self) -> None:
        self.assertTrue(is_exchange_shop_entries([{"text": "研发配方"}, {"text": "兑换道具"}]))
        top_vals = parse_exchange_shop_top_bar(
            ticket_entries=[
                {"text": "1", "box": [875, 20, 18, 36]},  # 高框图标噪点 & x < 920
                {"text": "7700", "box": [975, 22, 65, 24]},
            ],
            coin_entries=[
                {"text": "0", "box": [1088, 22, 20, 24]},  # x < 1125 图标误读
                {"text": "31771061", "box": [1175, 22, 95, 24]},
            ],
        )
        self.assertEqual(top_vals, {"work_tickets": 7700, "coins": 31_771_061})

        body_entries = [
            {"text": "牛仔裤缝制法", "box": [510, 202, 120, 24]},
            {"text": "31.8m/180k", "box": [715, 205, 80, 20]},
            {"text": "7.7k/1.8k", "box": [805, 205, 70, 20]},
            {"text": "剩余1次", "box": [1115, 210, 75, 20]},
            {"text": "无纺布粘制法", "box": [510, 332, 120, 24]},
            {"text": "31.8m/180k", "box": [715, 335, 80, 20]},
            {"text": "7.7k/1.8k", "box": [805, 335, 70, 20]},
            {"text": "剩余1次", "box": [1115, 340, 75, 20]},
            {"text": "纯棉布料织造法", "box": [510, 462, 130, 24]},
            {"text": "LEVEL 4", "box": [800, 442, 90, 26]},
            {"text": "31.8m/180k", "box": [715, 465, 80, 20]},
            {"text": "剩余1次", "box": [1115, 470, 75, 20]},
        ]
        rows = parse_exchange_shop_recipe_rows(body_entries)
        self.assertEqual(len(rows), 3)
        self.assertFalse(rows[0]["locked"])
        self.assertEqual(rows[0]["base_good_name"], "牛仔裤")
        self.assertEqual(rows[0]["coin_cost"], 180_000)
        self.assertEqual(rows[0]["ticket_cost"], 1800)
        self.assertEqual(rows[0]["exchange_point"][0], 1152)
        self.assertTrue(rows[2]["locked"])

    def test_room_bubble_build_panel_and_warehouse_remaining(self) -> None:
        bubble = [
            {"text": "生产", "box": [740, 305, 90, 28]},
            {"text": "建设", "box": [740, 368, 90, 28]},
        ]
        self.assertEqual(find_room_bubble_point(bubble, "建设", (792, 382)), (785, 382))
        self.assertIsNone(find_room_bubble_point(bubble, "详情", (792, 319)))

        panel_ok = [
            {"text": "40k / 31.8m", "box": [785, 520, 95, 24]},
            {"text": "400 / 7.7k", "box": [895, 520, 90, 24]},
        ]
        parsed_ok = parse_room_build_panel(panel_ok, [{"text": "建造", "box": [980, 595, 80, 30]}])
        self.assertTrue(parsed_ok["can_build"])
        self.assertEqual(parsed_ok["required_coins"], 40_000)
        self.assertEqual(parsed_ok["required_tickets"], 400)

        parsed_merged = parse_room_build_panel(
            [
                {"text": "50k / 32.0m", "box": [798, 529, 91, 17]},
                {"text": "500/2.6k", "box": [885, 529, 87, 17]},
            ],
            [{"text": "建造", "box": [978, 594, 55, 31]}],
        )
        self.assertTrue(parsed_merged["can_build"])
        self.assertEqual(parsed_merged["required_coins"], 50_000)
        self.assertEqual(parsed_merged["required_tickets"], 500)

        parsed_blocked = parse_room_build_panel(
            panel_ok + [{"text": "研发中心等级不足", "box": [860, 595, 160, 28]}],
            [{"text": "研发中心等级不足", "box": [860, 595, 160, 28]}],
        )
        self.assertFalse(parsed_blocked["can_build"])
        self.assertFalse(parse_room_build_panel(panel_ok, [{"text": "已升级", "box": [980, 595, 90, 30]}])["can_build"])

        # 只读左侧 x < 645 的剩余次数，忽略右侧桦石页签剩余 350 次
        rem = parse_warehouse_modal_remaining(
            [
                {"text": "剩余350次", "box": [740, 465, 95, 22]},
                {"text": "剩余100次", "box": [455, 465, 95, 22]},
            ]
        )
        self.assertEqual(rem, 100)
        self.assertIsNone(parse_warehouse_modal_remaining([{"text": "剩余350次", "box": [740, 465, 95, 22]}]))

    def test_predeposit_and_production_dynamic_parsers(self) -> None:
        self.assertEqual(parse_predeposit_balance([{"text": "铁盟币存量"}, {"text": "0"}]), 0)
        self.assertEqual(parse_predeposit_balance([{"text": "500,000"}]), 500_000)
        self.assertEqual(parse_predeposit_modal_qty([{"text": "1 / 2500000"}]), (1, 2_500_000))
        self.assertGreater(compute_predeposit_slider_x(500_000, 2_500_000), 506)
        self.assertEqual(compute_predeposit_slider_x(5_000_000, 2_500_000), 773)

        # 选配方前 y=559，选配方后上移至 y=496 并切换为「一键取消」
        pt_pre, mode_pre = find_production_select_all_point([{"text": "一键全选", "box": [1135, 545, 96, 28]}])
        self.assertEqual((pt_pre, mode_pre), ((1183, 559), "select_all"))
        pt_post, mode_post = find_production_select_all_point([{"text": "一键取消", "box": [1135, 482, 96, 28]}])
        self.assertEqual((pt_post, mode_post), ((1183, 496), "cancel_all"))

        cards = [
            {"text": "牛仔布织造法", "box": [35, 685, 110, 22]},
            {"text": "尼龙晴雨伞缝制法", "box": [365, 685, 130, 22]},
            {"text": "获取途径", "box": [380, 640, 90, 24]},
        ]
        pick = find_production_recipe_card_point(cards, ["尼龙晴雨伞", "牛仔布"])
        self.assertIsNotNone(pick)
        assert pick is not None
        self.assertEqual(pick[0], "牛仔布")

        # 原料不足 (1/12) vs 充足 (20/12)，同时过滤上方 6/6 人数标签
        short_panel = parse_production_ready_panel(
            [
                {"text": "6/6", "box": [1015, 520, 40, 20]},
                {"text": "1/12", "box": [800, 610, 45, 22]},
                {"text": "确定", "box": [1150, 660, 65, 28]},
            ]
        )
        self.assertTrue(short_panel["has_confirm"])
        self.assertFalse(short_panel["materials_sufficient"])

        ready_panel = parse_production_ready_panel(
            [
                {"text": "20/12", "box": [800, 610, 50, 22]},
                {"text": "确定", "box": [1150, 660, 65, 28]},
            ]
        )
        self.assertTrue(ready_panel["has_confirm"])
        self.assertTrue(ready_panel["materials_sufficient"])

    def test_html_and_mxu_summary_with_execution_receipt(self) -> None:
        snap = snapshot_from_account_payload(
            {
                "uid": "8820083699",
                "wallet": {"coins": 31_000_000, "huashi": 14_880},
                "prison": {
                    "level": 7,
                    "work_tickets": 5900,
                    "power_used": 5150,
                    "power_max": 13800,
                    "dorm_count": 2,
                    "production_workshop_count": 2,
                    "buildings": {"power_center": 4, "research_center": 4, "raw_sewing": 1},
                },
            }
        )
        report = plan_prison(snap, PrisonPlanOptions())
        receipt = PrisonRunReceipt(
            mode="execute_safe_auto",
            scope="full_safe",
            coins_before=31_771_061,
            coins_after=31_000_000,
            tickets_before=7700,
            tickets_after=5900,
            huashi_before=14_880,
            huashi_after=14_880,
            executed=[
                PrisonActionOutcome(
                    category="build",
                    action_type="building_upgrade",
                    target="研发中心<test>",
                    status="executed",
                    detail="升级 LV3→LV4",
                    coins_delta=-40_000,
                )
            ],
            guard_aborts=[
                PrisonActionOutcome(
                    category="guard",
                    action_type="warehouse_huashi_guard",
                    target="原料仓库扩容",
                    status="guard_abort",
                    detail="右侧高亮异常已拦截",
                )
            ],
        )
        html_doc = format_planning_report_html(report, run_receipt=receipt, generated_at="2026-11-23 16:15:00")
        self.assertIn("本次自动执行回执", html_doc)
        self.assertIn("研发中心&lt;test&gt;", html_doc)
        self.assertIn("31,771,061 → 31,000,000", html_doc)
        self.assertIn("14,880 → 14,880", html_doc)
        self.assertNotIn("http://", html_doc)
        self.assertNotIn("https://", html_doc)

        lines = format_mxu_plain_summary(report, run_receipt=receipt)
        self.assertTrue(any("本次执行：完成 1 项 / 跳过 0 项 / 护栏拦截 1 项" in line for line in lines))


class PrisonSafeAutoExecutionUnitTests(unittest.TestCase):
    def test_merge_shop_data_overrides_noisy_drawer_and_warehouse(self) -> None:
        with _real_maa_agent_env() as ok_maa:
            if not ok_maa:
                self.skipTest("maafw is not installed")
            if str(ROOT) not in sys.path:
                sys.path.insert(0, str(ROOT))
            import agent.prison_plan_action as ppa

            prev = AccountSnapshot(uid="8820083699")
            wallet, prison = ppa._merge_scanned_prison_and_wallet(
                prev,
                uid="8820083699",
                top_data={"level": 7},
                grid_data={"buildings": {"research_center": 3, "power_center": 3}},
                warehouse_data={"coins": 317_710_611, "huashi": 14_880},
                orders_scanned=False,
                scanned_orders=[],
                shop_data={"coins": 31_771_061, "work_tickets": 7700},
            )
            self.assertEqual(wallet["coins"], 31_771_061)
            self.assertEqual(wallet["huashi"], 14_880)
            self.assertEqual(prison["work_tickets"], 7700)

    def test_huashi_tab_swap_aborts_warehouse_and_power_never_clicks_confirm(self) -> None:
        with _real_maa_agent_env() as ok_maa:
            if not ok_maa:
                self.skipTest("maafw is not installed")
            if str(ROOT) not in sys.path:
                sys.path.insert(0, str(ROOT))
            import agent.prison_plan_action as ppa
            from maa_resonance.logic.planning import build_prison_execution_plan

            snap = snapshot_from_account_payload(
                {
                    "uid": "guard_test",
                    "wallet": {"coins": 31_771_061, "huashi": 14_880},
                    "prison": {
                        "level": 7,
                        "work_tickets": 7700,
                        "power_used": 5150,
                        "power_max": 13800,
                        "dorm_count": 2,
                        "production_workshop_count": 2,
                        "buildings": {"power_center": 3, "research_center": 3, "confinement_room": 1, "infirmary": 1},
                    },
                }
            )
            report = plan_prison(snap, PrisonPlanOptions(reserve_coins=15_000_000))
            plan = build_prison_execution_plan(snap, report, PrisonPlanOptions(reserve_coins=15_000_000))

            # 构造一张电力中心和仓库都误停在「安装电机 / 右侧桦石页签」的危险画面
            danger_img = np.zeros((720, 1280, 3), dtype=np.uint8)
            danger_img[24:38, 1180:1220] = 252  # 右侧 安装电机 白底
            danger_img[436:452, 870:910] = 253  # 右侧 桦石页签 白底

            taps: list[tuple[str, tuple[int, int]]] = []

            def fake_tap(_ctx, name: str, pt):
                taps.append((name, (int(pt[0]), int(pt[1]))))
                return True

            def fake_ocr(_ctx, _img, node_name: str, _roi):
                if "Grid" in node_name:
                    return [{"text": "电力中心 LV3", "box": [760, 410, 120, 24]}]
                if "Bubble" in node_name:
                    return [{"text": "建设", "box": [740, 336, 90, 28]}]
                if "PowerTabs" in node_name:
                    return [{"text": "安装电机", "box": [1080, 22, 120, 32]}]
                if "WhExecDock" in node_name or "ShopExecDock" in node_name or "BackDock" in node_name:
                    return [{"text": "仓库", "box": [55, 600, 40, 24]}, {"text": "订单", "box": [140, 600, 40, 24]}]
                if "WhChk" in node_name:
                    return [
                        {"text": "原料仓库 0/250", "box": [220, 130, 160, 28]},
                        {"text": "成品仓库 0/250", "box": [640, 130, 160, 28]},
                    ]
                if "WhModalTabs" in node_name:
                    return [{"text": "桦石", "box": [740, 430, 60, 24]}]
                if "BackTop" in node_name or "Top" in node_name:
                    return [{"text": "整顿中心 LV7", "box": [370, 20, 120, 28]}]
                if "Dock" in node_name:
                    return [{"text": "仓库", "box": [55, 600, 40, 24]}, {"text": "订单", "box": [140, 600, 40, 24]}]
                return []

            ctx = SimpleNamespace(tasker=SimpleNamespace(stopping=False))
            with (
                patch.object(ppa, "safe_screencap", return_value=danger_img),
                patch.object(ppa, "ocr_roi", side_effect=fake_ocr),
                patch.object(ppa, "tap_point", side_effect=fake_tap),
                patch.object(ppa, "swipe_points", return_value=True),
                patch.object(ppa, "sleep_with_stop", return_value=True),
            ):
                receipt = ppa._execute_safe_auto_actions(
                    ctx,
                    snapshot=snap,
                    prison_report=report,
                    execution_plan=plan,
                    auto_scope="build_and_buy",
                    prefix="GuardTest",
                )

            self.assertEqual(receipt.coins_before, 31_771_061)
            self.assertEqual(receipt.coins_after, 31_771_061)
            self.assertEqual(receipt.huashi_after, 14_880)
            self.assertEqual(len(receipt.executed), 0)
            abort_types = {o.action_type for o in receipt.guard_aborts}
            self.assertIn("power_center_guard", abort_types)
            self.assertIn("warehouse_huashi_guard", abort_types)
            tap_names = [n for n, _pt in taps]
            self.assertFalse(any("ConfirmBuild_power_center" in n for n in tap_names))
            self.assertFalse(any("WhConfirm" in n for n in tap_names))
            self.assertTrue(any("WhCancelGuard" in n for n in tap_names))

    def test_reserve_coins_floor_blocks_spending_in_auto_mode(self) -> None:
        with _real_maa_agent_env() as ok_maa:
            if not ok_maa:
                self.skipTest("maafw is not installed")
            if str(ROOT) not in sys.path:
                sys.path.insert(0, str(ROOT))
            import agent.prison_plan_action as ppa
            from maa_resonance.logic.planning import build_prison_execution_plan

            snap = snapshot_from_account_payload(
                {
                    "uid": "floor_auto_test",
                    "wallet": {"coins": 15_020_000, "huashi": 14_880},
                    "prison": {
                        "level": 7,
                        "work_tickets": 500,
                        "power_used": 5150,
                        "power_max": 13800,
                        "dorm_count": 2,
                        "production_workshop_count": 2,
                        "buildings": {"power_center": 3, "research_center": 3, "confinement_room": 1, "infirmary": 1},
                    },
                }
            )
            opts = PrisonPlanOptions(reserve_coins=15_000_000)
            report = plan_prison(snap, opts)
            plan = build_prison_execution_plan(snap, report, opts)

            # 仅剩 20,000 可花：研发中心升级 40,000 必须跳过，不能突破 15,000,000 底线
            safe_img = np.zeros((720, 1280, 3), dtype=np.uint8)
            safe_img[436:452, 372:412] = 253
            safe_img[436:452, 870:910] = 42
            taps: list[tuple[str, tuple[int, int]]] = []

            def fake_ocr(_ctx, _img, node_name: str, _roi):
                if "Grid" in node_name:
                    return [
                        {"text": "研发中心 LV3", "box": [320, 385, 120, 24]},
                        {"text": "电力中心 LV3", "box": [760, 410, 120, 24]},
                    ]
                if "Bubble" in node_name:
                    return [{"text": "建设", "box": [740, 356, 90, 28]}]
                if "BuildPanel_research_center" in node_name:
                    return [
                        {"text": "40k / 15.0m", "box": [785, 520, 95, 24]},
                        {"text": "400 / 500", "box": [895, 520, 90, 24]},
                    ]
                if "BuildPanel_power_center" in node_name:
                    return [{"text": "50k / 15.0m", "box": [785, 520, 95, 24]}]
                if "BuildBtn" in node_name:
                    return [{"text": "建造", "box": [980, 595, 80, 30]}]
                if "PowerTabs" in node_name:
                    return [{"text": "房间升级", "box": [830, 22, 110, 32]}]
                if "WhChk" in node_name:
                    return [{"text": "原料仓库 0/250", "box": [220, 130, 160, 28]}, {"text": "成品仓库 0/250", "box": [640, 130, 160, 28]}]
                if "WhModalTabs" in node_name or "WhReChk" in node_name:
                    return [{"text": "铁盟币 剩余100次", "box": [410, 430, 140, 24]}]
                if "Top" in node_name:
                    return [{"text": "整顿中心 LV7", "box": [370, 20, 120, 28]}]
                if "Dock" in node_name:
                    return [{"text": "仓库", "box": [55, 600, 40, 24]}, {"text": "订单", "box": [140, 600, 40, 24]}]
                return []

            ctx = SimpleNamespace(tasker=SimpleNamespace(stopping=False))
            safe_img[24:38, 805:845] = 252
            safe_img[24:38, 1180:1220] = 40
            with (
                patch.object(ppa, "safe_screencap", return_value=safe_img),
                patch.object(ppa, "ocr_roi", side_effect=fake_ocr),
                patch.object(ppa, "tap_point", side_effect=lambda _c, n, p: taps.append((n, (int(p[0]), int(p[1])))) or True),
                patch.object(ppa, "swipe_points", return_value=True),
                patch.object(ppa, "sleep_with_stop", return_value=True),
            ):
                receipt = ppa._execute_safe_auto_actions(
                    ctx,
                    snapshot=snap,
                    prison_report=report,
                    execution_plan=plan,
                    auto_scope="build_and_buy",
                    prefix="FloorTest",
                )

            # 研发/电力 40k/50k 被保底线拦截，仓库左侧仅余 20k 预算 → 原料仓买2次花完 20k，成品仓触发底线跳过
            self.assertGreaterEqual(receipt.coins_after, 15_000_000)
            self.assertEqual(receipt.coins_after, 15_000_000)
            self.assertFalse(any("ConfirmBuild" in n for n, _ in taps))
            self.assertTrue(any(o.target == "研发中心" and "底线" in o.detail for o in receipt.skipped))


class PrisonLiveLogRegressionTests(unittest.TestCase):
    """基于 2026-11-23 16:57-16:58 实机 MXU 日志（maafw.log）沉淀的回归测试。"""

    def test_warehouse_coins_tab_accepts_live_price_ocr_and_rejects_huashi_swap(self) -> None:
        import numpy as np
        from maa_resonance.logic.planning import (
            WAREHOUSE_MODAL_COIN_PATCH_ROI,
            WAREHOUSE_MODAL_HUASHI_PATCH_ROI,
            has_warehouse_left_coin_price,
            verify_warehouse_coins_tab_safe,
        )

        img = np.full((720, 1280, 3), 40, dtype=np.uint8)
        cx, cy, cw, ch = WAREHOUSE_MODAL_COIN_PATCH_ROI
        img[cy : cy + ch, cx : cx + cw] = 245

        live_entries = [
            {"text": "中", "box": [462, 432, 18, 28]},
            {"text": "10000", "box": [484, 432, 67, 30]},
            {"text": "福", "box": [554, 432, 18, 28]},
        ]
        self.assertTrue(has_warehouse_left_coin_price(live_entries))
        self.assertTrue(has_warehouse_left_coin_price([{"text": "100k", "box": [484, 432, 60, 28]}]))
        self.assertFalse(has_warehouse_left_coin_price([{"text": "剩余100次", "box": [484, 495, 80, 24]}]))
        ok, msg = verify_warehouse_coins_tab_safe(img, live_entries)
        self.assertTrue(ok, msg)

        huashi_only_entries = [{"text": "100", "box": [780, 432, 42, 30]}]
        self.assertFalse(has_warehouse_left_coin_price(huashi_only_entries))
        ok_huashi, _ = verify_warehouse_coins_tab_safe(img, huashi_only_entries)
        self.assertFalse(ok_huashi)

        left_huashi_kw = [{"text": "桦石", "box": [490, 432, 44, 28]}]
        ok_kw, _ = verify_warehouse_coins_tab_safe(img, left_huashi_kw)
        self.assertFalse(ok_kw)

        swapped_img = np.full((720, 1280, 3), 40, dtype=np.uint8)
        hx, hy, hw, hh = WAREHOUSE_MODAL_HUASHI_PATCH_ROI
        swapped_img[hy : hy + hh, hx : hx + hw] = 245
        ok_swapped, _ = verify_warehouse_coins_tab_safe(swapped_img, live_entries)
        self.assertFalse(ok_swapped)

    def test_single_order_card_parses_live_03b_coords(self) -> None:
        from maa_resonance.logic.planning import parse_single_order_card

        body_entries = [
            {"text": "需求物资", "box": [460, 210, 90, 24]},
            {"text": "牛仔布", "box": [760, 271, 64, 28]},
            {"text": "180", "box": [938, 272, 48, 28]},
        ]
        btn_insufficient = [
            {"text": "0", "box": [841, 641, 20, 22]},
            {"text": "物资不足", "box": [922, 609, 96, 28]},
        ]
        parsed = parse_single_order_card(body_entries, btn_insufficient, order_type="daily")
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed["item_name"], "牛仔布")
        self.assertEqual(parsed["quantity"], 180)
        self.assertEqual(parsed["stock_owned"], 0)
        self.assertFalse(parsed["deliverable"])

        btn_ready = [
            {"text": "220", "box": [841, 641, 36, 22]},
            {"text": "交付", "box": [935, 609, 60, 28]},
        ]
        parsed_ready = parse_single_order_card(body_entries, btn_ready, order_type="daily")
        self.assertIsNotNone(parsed_ready)
        assert parsed_ready is not None
        self.assertEqual(parsed_ready["stock_owned"], 220)
        self.assertTrue(parsed_ready["deliverable"])

    def test_exchange_shop_recipe_rows_parse_live_y_bands(self) -> None:
        from maa_resonance.logic.planning import parse_exchange_shop_recipe_rows

        entries = [
            {"text": "EXCHANGE", "box": [1100, 181, 88, 24]},
            {"text": "牛皮粘制法", "box": [510, 232, 110, 24]},
            {"text": "31.8m/180k", "box": [690, 232, 75, 22]},
            {"text": "7.7k/1.8k", "box": [805, 232, 68, 22]},
            {"text": "剩余1次", "box": [940, 232, 70, 22]},
            {"text": "EXCHANGE", "box": [1100, 312, 88, 24]},
            {"text": "毛毡缝制法", "box": [510, 361, 110, 24]},
            {"text": "31.8m/300k", "box": [690, 361, 75, 22]},
            {"text": "7.7k/3.0k", "box": [805, 361, 68, 22]},
            {"text": "剩余1次", "box": [940, 361, 70, 22]},
            {"text": "EXCHANGE", "box": [1100, 445, 88, 24]},
            {"text": "蕾丝织造法", "box": [510, 490, 110, 24]},
            {"text": "31.8m/500k", "box": [690, 490, 75, 22]},
            {"text": "7.7k/5.0k", "box": [805, 490, 68, 22]},
            {"text": "剩余1次", "box": [940, 490, 70, 22]},
            {"text": "EXCHANGE", "box": [1100, 565, 88, 24]},
            {"text": "海草布剪裁法", "box": [510, 623, 120, 24]},
            {"text": "31.8m/800k", "box": [690, 623, 75, 22]},
            {"text": "7.7k/8.0k", "box": [805, 623, 68, 22]},
            {"text": "等级不足", "box": [940, 623, 80, 22]},
        ]
        rows = parse_exchange_shop_recipe_rows(entries)
        self.assertEqual([r["recipe_name"] for r in rows], ["牛皮粘制法", "毛毡缝制法", "蕾丝织造法", "海草布剪裁法"])
        self.assertEqual([(r["coin_cost"], r["ticket_cost"]) for r in rows], [
            (180_000, 1800),
            (300_000, 3000),
            (500_000, 5000),
            (800_000, 8000),
        ])
        self.assertFalse(rows[0]["locked"])
        self.assertTrue(rows[3]["locked"])
        self.assertEqual([r["exchange_point"][1] for r in rows], [193, 324, 457, 577])

    def test_columba_foyer_routes_through_two_hop_entry(self) -> None:
        from unittest import mock
        import numpy as np
        from maa_resonance.logic.planning import ORDERS_FOYER_DAILY_POINT

        with _real_maa_agent_env():
            import agent.prison_plan_action as ppa

            frame = np.zeros((720, 1280, 3), dtype=np.uint8)
            taps: list[tuple[int, int]] = []

            class _FakeCtx:
                def run_recognition(self, name, img, param=None):
                    return None

                def run_action(self, name, param=None):
                    return None

            def fake_ocr(_ctx, _img, name, _roi):
                if "OrdChk" in name:
                    return [{"text": "COLUMBA", "box": [120, 30, 140, 30]}, {"text": "帮助", "box": [400, 30, 40, 26]}]
                if "OrdFoyerChk" in name:
                    return [
                        {"text": "运输订单", "box": [880, 310, 110, 28]},
                        {"text": "每周订单", "box": [880, 390, 110, 28]},
                        {"text": "交谈", "box": [880, 470, 70, 28]},
                    ]
                if "OrdDailyCard" in name:
                    return [{"text": "需求物资", "box": [460, 210, 90, 24]}, {"text": "牛仔布", "box": [760, 271, 64, 28]}]
                return []

            def fake_tap(_ctx, _name, pt):
                taps.append(tuple(pt))
                return True

            with (
                mock.patch.object(ppa, "safe_screencap", return_value=frame),
                mock.patch.object(ppa, "sleep_with_stop", return_value=True),
                mock.patch.object(ppa, "ocr_roi", side_effect=fake_ocr),
                mock.patch.object(ppa, "tap_point", side_effect=fake_tap),
            ):
                img, entered, legacy, aborted = ppa._enter_daily_orders_screen(
                    _FakeCtx(),
                    [{"text": "黑月订单", "box": [880, 650, 90, 30]}],
                    "RegTest_",
                )
            self.assertIsNotNone(img)
            self.assertTrue(entered)
            self.assertFalse(legacy)
            self.assertFalse(aborted)
            self.assertIn(ORDERS_FOYER_DAILY_POINT, taps)

    def test_exchange_shop_ndarray_screencap_and_stage_isolation(self) -> None:
        from unittest import mock
        import numpy as np
        from maa_resonance.logic.planning import (
            AccountSnapshot,
            PrisonPlanOptions,
            PrisonSnapshot,
            WalletSnapshot,
            build_prison_execution_plan,
            plan_prison,
        )

        with _real_maa_agent_env():
            import agent.prison_plan_action as ppa

            frame = np.zeros((720, 1280, 3), dtype=np.uint8)
            state = ppa._ExecState(
                live_coins=31_731_061,
                live_tickets=7_300,
                huashi_baseline=14_880,
                reserve_coins=30_000_000,
            )

            class _FakeCtx:
                pass

            def fake_ocr(_ctx, _img, name, _roi):
                if "ShopChk" in name:
                    return [{"text": "研发配方", "box": [220, 80, 120, 30]}]
                if "ExecShopTix" in name:
                    return [{"text": "7.3k", "box": [960, 22, 60, 24]}]
                if "ExecShopCoins" in name:
                    return [{"text": "31.7m", "box": [1145, 22, 70, 24]}]
                return []

            with (
                mock.patch.object(ppa, "safe_screencap", return_value=frame),
                mock.patch.object(ppa, "sleep_with_stop", return_value=True),
                mock.patch.object(ppa, "ocr_roi", side_effect=fake_ocr),
                mock.patch.object(ppa, "tap_point", return_value=True),
            ):
                ppa._exec_exchange_rush_recipes(
                    _FakeCtx(),
                    state,
                    "rush_leveling",
                    "RegShop_",
                )

            snapshot = AccountSnapshot(
                uid="8820083699",
                wallet=WalletSnapshot(coins=31_731_061, huashi=14_880),
                prison=PrisonSnapshot(prison_level=7, work_tickets=7_300),
            )
            opts = PrisonPlanOptions(reserve_coins=30_000_000)
            report = plan_prison(snapshot, opts)
            plan = build_prison_execution_plan(snapshot, report, opts)
            ran: list[str] = []

            def boom(*_args, **_kwargs):
                raise RuntimeError("mock crash")

            with (
                mock.patch.object(ppa, "is_stopping", return_value=False),
                mock.patch.object(ppa, "_ensure_on_prison_overview", return_value=True),
                mock.patch.object(ppa, "_back_to_prison_overview", return_value=True),
                mock.patch.object(ppa, "_exec_claim_todo_tasks"),
                mock.patch.object(ppa, "_exec_checkin_prisoners"),
                mock.patch.object(ppa, "_exec_ensure_finance_auto_refill"),
                mock.patch.object(ppa, "_exec_deliver_orders", side_effect=boom),
                mock.patch.object(ppa, "_exec_upgrade_core_buildings", side_effect=lambda *a: ran.append("bld")),
                mock.patch.object(ppa, "_exec_expand_warehouses_coins_only", side_effect=lambda *a: ran.append("wh")),
                mock.patch.object(ppa, "_exec_exchange_rush_recipes", side_effect=lambda *a: ran.append("shop")),
                mock.patch.object(ppa, "_exec_predeposit_raw_workshops", side_effect=lambda *a: ran.append("raw")),
                mock.patch.object(ppa, "_exec_start_workshop_production", side_effect=lambda *a: ran.append("prod")),
            ):
                receipt = ppa._execute_safe_auto_actions(
                    _FakeCtx(),
                    snapshot=snapshot,
                    prison_report=report,
                    execution_plan=plan,
                    auto_scope="full_safe",
                    prefix="RegIso_",
                )
            self.assertEqual(ran, ["bld", "wh", "shop", "raw", "prod"])
            self.assertTrue(any(o.status == "failed" and o.action_type == "order_deliver" for o in receipt.skipped))

    def test_pan_and_find_room_checks_current_screen_before_swiping(self) -> None:
        from unittest import mock
        import numpy as np
        from maa_resonance.logic.planning import PRISON_RIGHT_WING_PAN_SWIPE

        with _real_maa_agent_env():
            import agent.prison_plan_action as ppa

            frame = np.zeros((720, 1280, 3), dtype=np.uint8)
            swipes: list[str] = []

            class _FakeCtx:
                pass

            def fake_ocr(_ctx, _img, name, _roi):
                if name.endswith("GridCur"):
                    return [{"text": "电力中心", "box": [780, 310, 90, 26]}]
                return []

            with (
                mock.patch.object(ppa, "safe_screencap", return_value=frame),
                mock.patch.object(ppa, "ocr_roi", side_effect=fake_ocr),
                mock.patch.object(ppa, "swipe_points", side_effect=lambda *a, **kw: swipes.append(a[1]) or True),
            ):
                pt, status = ppa._pan_and_find_room(
                    _FakeCtx(),
                    "RegCur_",
                    PRISON_RIGHT_WING_PAN_SWIPE,
                    ("电力中心",),
                )
            self.assertEqual(status, "ok")
            self.assertIsNotNone(pt)
            self.assertEqual(swipes, [])

    def test_prison_overview_rejects_dormitory_3d_interior(self) -> None:
        from maa_resonance.logic.planning import is_prison_overview_entries

        dorm_top = [
            {"text": "帮助", "box": [281, 25, 39, 23]},
            {"text": "LV7", "box": [434, 39, 44, 33]},
            {"text": "整顿中心", "box": [436, 15, 89, 31]},
            {"text": "1号整顿宿舍", "box": [656, 21, 104, 21]},
            {"text": "已解锁床位：", "box": [658, 45, 96, 21]},
            {"text": "12/36", "box": [760, 45, 52, 21]},
        ]
        dorm_dock = [
            {"text": "宿舍导航", "box": [126, 658, 69, 19]},
            {"text": "已解锁生活区域：2/6", "box": [402, 676, 174, 19]},
            {"text": "下一区场", "box": [596, 678, 61, 16]},
        ]
        self.assertFalse(is_prison_overview_entries(dorm_top, dorm_dock))

        overview_top = [{"text": "整顿中心"}, {"text": "LV7"}]
        overview_dock = [{"text": "仓库"}, {"text": "订单站"}, {"text": "兑换商店"}]
        self.assertTrue(is_prison_overview_entries(overview_top, overview_dock))
        self.assertTrue(is_prison_overview_entries([{"text": "整顿中心 LV7"}], []))
        self.assertFalse(is_prison_overview_entries([{"text": "整顿中心 LV7"}], [{"text": "未知底栏"}]))

    def test_find_room_rejects_edge_clipped_and_clicks_room_interior(self) -> None:
        with _real_maa_agent_env() as ok_maa:
            if not ok_maa:
                self.skipTest("maafw is not installed")
            import agent.prison_plan_action as ppa

            pt_bottom, st_bottom = ppa._find_room_in_overview_grid(
                [{"text": "研发中心LV4", "box": [976, 608, 113, 23]}],
                ("研发中心",),
            )
            self.assertIsNone(pt_bottom)
            self.assertEqual(st_bottom, "edge_clipped_bottom")

            pt_right, st_right = ppa._find_room_in_overview_grid(
                [{"text": "电力中心", "box": [1196, 230, 77, 19]}],
                ("电力中心",),
            )
            self.assertIsNone(pt_right)
            self.assertEqual(st_right, "edge_clipped_right")

            pt_ok, st_ok = ppa._find_room_in_overview_grid(
                [{"text": "研发中心LV3", "box": [840, 230, 110, 19]}],
                ("研发中心",),
            )
            self.assertEqual(st_ok, "ok")
            self.assertIsNotNone(pt_ok)
            assert pt_ok is not None
            self.assertEqual(pt_ok[0], 910)
            self.assertGreaterEqual(pt_ok[1], 270)
            self.assertLessEqual(pt_ok[1], 274)

    def test_pan_and_find_room_nudges_left_on_right_edge_clip(self) -> None:
        from unittest import mock
        import numpy as np
        from maa_resonance.logic.planning import PRISON_RIGHT_WING_PAN_SWIPE

        with _real_maa_agent_env() as ok_maa:
            if not ok_maa:
                self.skipTest("maafw is not installed")
            import agent.prison_plan_action as ppa

            frame = np.zeros((720, 1280, 3), dtype=np.uint8)
            swipes: list[tuple[tuple[int, int], tuple[int, int]]] = []

            class _FakeCtx:
                pass

            def fake_ocr(_ctx, _img, name, _roi):
                if name.endswith("GridCur"):
                    return [{"text": "电力中心", "box": [1196, 230, 77, 19]}]
                if name.endswith("Grid"):
                    return [{"text": "电力中心", "box": [820, 230, 90, 22]}]
                return []

            def fake_swipe(_ctx, _name, start_pt, end_pt, **_kwargs):
                swipes.append((tuple(start_pt), tuple(end_pt)))
                return True

            with (
                mock.patch.object(ppa, "safe_screencap", return_value=frame),
                mock.patch.object(ppa, "sleep_with_stop", return_value=True),
                mock.patch.object(ppa, "ocr_roi", side_effect=fake_ocr),
                mock.patch.object(ppa, "swipe_points", side_effect=fake_swipe),
            ):
                pt, status = ppa._pan_and_find_room(
                    _FakeCtx(),
                    "RegRight_",
                    PRISON_RIGHT_WING_PAN_SWIPE,
                    ("电力中心",),
                )
            self.assertEqual(status, "ok")
            self.assertIsNotNone(pt)
            self.assertEqual(swipes, [((980, 360), (340, 360))])

    def test_missing_build_bubble_on_overview_never_taps_unzoom_room(self) -> None:
        from unittest import mock
        import numpy as np
        from maa_resonance.logic.planning import (
            ROOM_UNZOOM_LEFT_COL_POINT,
            AccountSnapshot,
            PrisonPlanOptions,
            PrisonSnapshot,
            WalletSnapshot,
            build_prison_execution_plan,
            plan_prison,
        )

        with _real_maa_agent_env() as ok_maa:
            if not ok_maa:
                self.skipTest("maafw is not installed")
            import agent.prison_plan_action as ppa

            frame = np.zeros((720, 1280, 3), dtype=np.uint8)
            taps: list[tuple[str, tuple[int, int]]] = []
            snap = AccountSnapshot(
                uid="8820083699",
                wallet=WalletSnapshot(coins=31_731_061, huashi=14_880),
                prison=PrisonSnapshot(
                    prison_level=7,
                    work_tickets=7_300,
                    buildings={"research_center": 4, "power_center": 3},
                ),
            )
            opts = PrisonPlanOptions(reserve_coins=30_000_000)
            report = plan_prison(snap, opts)
            plan = build_prison_execution_plan(snap, report, opts)
            state = ppa._ExecState(
                live_coins=31_731_061,
                live_tickets=7_300,
                huashi_baseline=14_880,
                reserve_coins=30_000_000,
            )

            class _FakeCtx:
                pass

            def fake_ocr(_ctx, _img, name, _roi):
                if "research_center" in name and "GridCur" in name:
                    return [{"text": "研发中心LV4", "box": [840, 230, 110, 19]}]
                if "Bubble" in name:
                    return []
                if "Top" in name:
                    return [{"text": "整顿中心"}, {"text": "LV7"}]
                if "Dock" in name:
                    return [{"text": "仓库"}, {"text": "订单站"}]
                return []

            def fake_tap(_ctx, name, pt):
                taps.append((name, (int(pt[0]), int(pt[1]))))
                return True

            with (
                mock.patch.object(ppa, "is_stopping", return_value=False),
                mock.patch.object(ppa, "safe_screencap", return_value=frame),
                mock.patch.object(ppa, "sleep_with_stop", return_value=True),
                mock.patch.object(ppa, "ocr_roi", side_effect=fake_ocr),
                mock.patch.object(ppa, "tap_point", side_effect=fake_tap),
                mock.patch.object(ppa, "swipe_points", return_value=True),
            ):
                ppa._exec_upgrade_core_buildings(_FakeCtx(), state, plan, "NoBlind_")

            self.assertFalse(any("UnzoomMissing" in n for n, _ in taps))
            self.assertFalse(any(pt == ROOM_UNZOOM_LEFT_COL_POINT for _, pt in taps))

    def test_unlockable_raw_workshop_treated_as_locked_not_lv1(self) -> None:
        from maa_resonance.logic.planning import parse_prison_grid_buildings

        entries = [
            {"text": "植物纤维原料车间", "box": [932, 475, 140, 23]},
            {"text": "可解锁", "box": [974, 498, 52, 19]},
        ]
        parsed = parse_prison_grid_buildings(entries)
        self.assertNotIn("raw_plant", parsed["buildings"])
        self.assertIn("raw_plant", parsed["locked_buildings"])

        with _real_maa_agent_env() as ok_maa:
            if not ok_maa:
                self.skipTest("maafw is not installed")
            import agent.prison_plan_action as ppa

            pt, status = ppa._find_room_in_overview_grid(
                entries,
                ("植物纤维原料车间", "植物纤维车间"),
            )
            self.assertIsNone(pt)
            self.assertEqual(status, "locked")

    def test_find_modal_confirm_ignores_prompt_sentence_and_hits_bottom_button(self) -> None:
        from maa_resonance.logic.planning import find_modal_confirm_button_point

        prompt_only = [
            {"text": "确认消耗以上素材兑换牛仔裤缝制法×1吗？", "box": [442, 432, 383, 23]},
            {"text": "取消", "box": [295, 522, 54, 28]},
        ]
        self.assertIsNone(find_modal_confirm_button_point(prompt_only))

        with_confirm = prompt_only + [{"text": "确定", "box": [930, 522, 54, 28]}]
        self.assertEqual(find_modal_confirm_button_point(with_confirm), (957, 536))

    def test_exchange_shop_requires_confirm_and_balance_change(self) -> None:
        from unittest import mock
        import numpy as np
        from maa_resonance.logic.planning import SHOP_MODAL_CANCEL_POINT

        with _real_maa_agent_env() as ok_maa:
            if not ok_maa:
                self.skipTest("maafw is not installed")
            import agent.prison_plan_action as ppa

            frame = np.zeros((720, 1280, 3), dtype=np.uint8)
            shop_row_entries = [
                {"text": "EXCHANGE", "box": [1095, 185, 90, 29]},
                {"text": "牛仔裤缝制法", "box": [521, 240, 102, 24]},
                {"text": "33.7m/180k", "box": [697, 242, 82, 17]},
                {"text": "6.8k/1.8k", "box": [792, 242, 64, 17]},
                {"text": "剩余1次", "box": [1116, 241, 68, 22]},
            ]

            class _FakeCtx:
                pass

            def _run_case(mode: str):
                taps: list[tuple[str, tuple[int, int]]] = []
                state = ppa._ExecState(
                    live_coins=33_733_271,
                    live_tickets=6_800,
                    huashi_baseline=15_130,
                    reserve_coins=30_000_000,
                )

                def fake_ocr(_ctx, _img, name, _roi):
                    if "ShopChk" in name:
                        return [{"text": "研发配方", "box": [903, 92, 73, 26]}]
                    if "ExecShopTix" in name:
                        return [{"text": "6800", "box": [999, 25, 51, 21]}]
                    if "ExecShopCoins" in name:
                        return [{"text": "33733271", "box": [1165, 23, 95, 23]}]
                    if "ExecShopBody_0" in name:
                        return shop_row_entries
                    if "ExecShopBody_1" in name:
                        return []
                    if "ShopPop_0" in name:
                        entries = [{"text": "确认消耗以上素材兑换牛仔裤缝制法×1吗？", "box": [442, 432, 383, 23]}]
                        if mode != "missing_confirm":
                            entries.append({"text": "确定", "box": [930, 522, 54, 28]})
                        return entries
                    if "ShopPostTix_0" in name:
                        return [{"text": "5000" if mode == "ok" else "6800", "box": [999, 25, 51, 21]}]
                    if "ShopPostCoins_0" in name:
                        return [{"text": "33553271" if mode == "ok" else "33733271", "box": [1165, 23, 95, 23]}]
                    if "ShopStuckChk" in name and mode == "unchanged":
                        return [{"text": "确认消耗以上素材", "box": [442, 432, 200, 23]}]
                    if "BackTop" in name:
                        return [{"text": "整顿中心 LV7", "box": [370, 20, 120, 28]}]
                    if "BackDock" in name:
                        return [{"text": "仓库", "box": [55, 600, 40, 24]}, {"text": "订单站", "box": [140, 600, 40, 24]}]
                    return []

                with (
                    mock.patch.object(ppa, "is_stopping", return_value=False),
                    mock.patch.object(ppa, "safe_screencap", return_value=frame),
                    mock.patch.object(ppa, "sleep_with_stop", return_value=True),
                    mock.patch.object(ppa, "ocr_roi", side_effect=fake_ocr),
                    mock.patch.object(ppa, "tap_point", side_effect=lambda _c, n, p: taps.append((n, (int(p[0]), int(p[1])))) or True),
                ):
                    ppa._exec_exchange_rush_recipes(_FakeCtx(), state, "rush_leveling", "ShopCase_")
                return state, taps

            st_a, taps_a = _run_case("missing_confirm")
            self.assertEqual(len(st_a.executed), 0)
            self.assertTrue(any(pt == SHOP_MODAL_CANCEL_POINT for _, pt in taps_a))
            self.assertEqual(len(st_a.skipped), 1)

            st_b, taps_b = _run_case("unchanged")
            self.assertEqual(len(st_b.executed), 0)
            self.assertTrue(any(pt == SHOP_MODAL_CANCEL_POINT for _, pt in taps_b))
            self.assertTrue(any("未变化" in s.detail for s in st_b.skipped))

            st_c, _taps_c = _run_case("ok")
            self.assertEqual(len(st_c.executed), 1)
            self.assertEqual(st_c.live_tickets, 5000)
            self.assertEqual(st_c.live_coins, 33_553_271)

    def test_workshop_prod_button_shifts_text_label_up_to_icon_and_polls_drawer(self) -> None:
        from unittest import mock
        import numpy as np
        from maa_resonance.logic.planning import (
            AccountSnapshot,
            PrisonPlanOptions,
            PrisonSnapshot,
            WalletSnapshot,
            build_prison_execution_plan,
            plan_prison,
        )

        with _real_maa_agent_env() as ok_maa:
            if not ok_maa:
                self.skipTest("maafw is not installed")
            import agent.prison_plan_action as ppa

            frame = np.zeros((720, 1280, 3), dtype=np.uint8)
            taps: list[tuple[str, tuple[int, int]]] = []
            drawer_checks = {"n": 0}
            snap = AccountSnapshot(
                uid="8820083699",
                wallet=WalletSnapshot(coins=33_000_000, huashi=15_130),
                prison=PrisonSnapshot(prison_level=7, production_workshop_count=1, work_tickets=6_800),
            )
            opts = PrisonPlanOptions(reserve_coins=30_000_000)
            report = plan_prison(snap, opts)
            plan = build_prison_execution_plan(snap, report, opts)
            state = ppa._ExecState(
                live_coins=33_000_000,
                live_tickets=6_800,
                huashi_baseline=15_130,
                reserve_coins=30_000_000,
            )

            class _FakeCtx:
                pass

            def fake_ocr(_ctx, _img, name, _roi):
                if "Ws_1号生产车间GridCur" in name:
                    return [{"text": "1号生产车间", "box": [849, 223, 101, 23]}]
                if "WsInterior_1号生产车间" in name:
                    return [
                        {"text": "车间编辑", "box": [1092, 670, 81, 25]},
                        {"text": "生产", "box": [1202, 665, 50, 34]},
                    ]
                if "ProdSel_1号生产车间" in name:
                    drawer_checks["n"] += 1
                    if drawer_checks["n"] == 1:
                        return []
                    return [{"text": "一键全选", "box": [1135, 545, 96, 28]}]
                if "ProdSelRe_1号生产车间" in name:
                    return [{"text": "一键取消", "box": [1135, 482, 96, 28]}]
                if "ProdCards_1号生产车间" in name:
                    return [{"text": "牛仔布", "box": [120, 620, 80, 30]}]
                if "ReadyPanel_1号生产车间" in name:
                    return [{"text": "确定", "box": [1150, 660, 64, 28]}, {"text": "100/20", "box": [900, 580, 60, 22]}]
                if "DurChk_8_1号生产车间" in name:
                    return [{"text": "确定", "box": [1150, 660, 64, 28]}, {"text": "100/80", "box": [900, 580, 60, 22]}]
                if "ProdAfterChk" in name:
                    return []
                if "BackTop" in name:
                    return [{"text": "整顿中心 LV7", "box": [370, 20, 120, 28]}]
                if "BackDock" in name:
                    return [{"text": "仓库", "box": [55, 600, 40, 24]}, {"text": "订单站", "box": [140, 600, 40, 24]}]
                return []

            def fake_tap(_ctx, name, pt):
                taps.append((name, (int(pt[0]), int(pt[1]))))
                return True

            with (
                mock.patch.object(ppa, "is_stopping", return_value=False),
                mock.patch.object(ppa, "safe_screencap", return_value=frame),
                mock.patch.object(ppa, "sleep_with_stop", return_value=True),
                mock.patch.object(ppa, "ocr_roi", side_effect=fake_ocr),
                mock.patch.object(ppa, "tap_point", side_effect=fake_tap),
            ):
                ppa._exec_start_workshop_production(_FakeCtx(), state, snap, plan, "WsCase_")

            prod_taps = [pt for n, pt in taps if n == "WsCase_TapProd_1号生产车间"]
            self.assertEqual(prod_taps, [(1227, 634)])
            self.assertEqual(len(state.executed), 1)
            self.assertEqual(state.executed[0].target, "牛仔布")

    def test_find_all_production_recipe_cards_orders_and_excludes_started(self) -> None:
        from maa_resonance.logic.planning import (
            find_all_production_recipe_card_points,
            find_production_recipe_card_point,
        )

        cards = [
            {"text": "牛仔裤缝制法", "box": [14, 665, 99, 19]},
            {"text": "牛仔布织造法", "box": [193, 665, 99, 19]},
            {"text": "无纺布粘制法", "box": [370, 663, 101, 22]},
            {"text": "真丝睡衣缝制法", "box": [550, 665, 110, 19]},
            {"text": "获取途径", "box": [570, 630, 60, 18]},
        ]
        self.assertIsNone(find_production_recipe_card_point(cards, ["岚心锦"]))
        all_pts = find_all_production_recipe_card_points(
            cards,
            ["无纺布", "牛仔布"],
            exclude_targets=["无纺布"],
        )
        names = [name for name, _pt in all_pts]
        self.assertNotIn("无纺布", names)
        self.assertNotIn("真丝睡衣", names)
        self.assertGreaterEqual(len(names), 1)
        self.assertEqual(names[0], "牛仔布")

    def test_workshop_rotates_to_second_recipe_when_first_lacks_materials_and_avoids_duplicate(self) -> None:
        from unittest import mock
        import numpy as np
        from maa_resonance.logic.planning import (
            AccountSnapshot,
            PrisonPlanOptions,
            PrisonSnapshot,
            WalletSnapshot,
            build_prison_execution_plan,
            plan_prison,
        )

        with _real_maa_agent_env() as ok_maa:
            if not ok_maa:
                self.skipTest("maafw is not installed")
            import agent.prison_plan_action as ppa

            frame = np.zeros((720, 1280, 3), dtype=np.uint8)
            snap = AccountSnapshot(
                uid="8820083699",
                wallet=WalletSnapshot(coins=33_000_000, huashi=15_130),
                prison=PrisonSnapshot(prison_level=7, production_workshop_count=2, work_tickets=2_600),
            )
            opts = PrisonPlanOptions(reserve_coins=30_000_000)
            report = plan_prison(snap, opts)
            plan = build_prison_execution_plan(snap, report, opts)

            class _FakeCtx:
                pass

            # 子用例 1：1号车间的首张「牛仔布」缺料后自动切到第二张「无纺布」启动；2号车间自动排除已开「无纺布」改为启动「牛仔布」
            state = ppa._ExecState(33_000_000, 2_600, 15_130, 30_000_000)

            def fake_ocr(_ctx, _img, name, _roi):
                if "GridCur" in name:
                    return [
                        {"text": "1号生产车间", "box": [849, 223, 101, 23]},
                        {"text": "2号生产车间", "box": [848, 105, 105, 26]},
                    ]
                if "WsInterior" in name:
                    return [{"text": "生产", "box": [1202, 665, 50, 34]}]
                if "ProdSel_" in name:
                    return [{"text": "一键取消", "box": [1137, 482, 94, 24]}]
                if "ProdCards_" in name:
                    return [
                        {"text": "牛仔布织造法", "box": [193, 665, 99, 19]},
                        {"text": "无纺布粘制法", "box": [370, 663, 101, 22]},
                    ]
                if "ReadyPanel_1号生产车间_a1_" in name:
                    return [{"text": "确定", "box": [1150, 660, 64, 28]}, {"text": "100/20", "box": [900, 580, 60, 22]}]
                if "ReadyPanel_1号生产车间_" in name:
                    return [{"text": "确定", "box": [1150, 660, 64, 28]}, {"text": "1/12", "box": [900, 580, 60, 22]}]
                if "DurChk_8_1号生产车间_a1" in name:
                    return [{"text": "确定", "box": [1150, 660, 64, 28]}, {"text": "100/80", "box": [900, 580, 60, 22]}]
                if "ReadyPanel_2号生产车间_" in name:
                    return [{"text": "确定", "box": [1150, 660, 64, 28]}, {"text": "100/20", "box": [900, 580, 60, 22]}]
                if "DurChk_8_2号生产车间" in name:
                    return [{"text": "确定", "box": [1150, 660, 64, 28]}, {"text": "100/80", "box": [900, 580, 60, 22]}]
                if "ProdAfterChk" in name:
                    return []
                if "BackTop" in name:
                    return [{"text": "整顿中心 LV7"}]
                if "BackDock" in name:
                    return [{"text": "仓库"}, {"text": "订单站"}]
                return []

            with (
                mock.patch.object(ppa, "is_stopping", return_value=False),
                mock.patch.object(ppa, "safe_screencap", return_value=frame),
                mock.patch.object(ppa, "sleep_with_stop", return_value=True),
                mock.patch.object(ppa, "ocr_roi", side_effect=fake_ocr),
                mock.patch.object(ppa, "tap_point", return_value=True),
            ):
                ppa._exec_start_workshop_production(_FakeCtx(), state, snap, plan, "RotCase_")

            self.assertEqual(len(state.executed), 2)
            self.assertEqual(state.executed[0].target, "无纺布")
            self.assertEqual(state.executed[1].target, "牛仔布")

            # 子用例 2：车间「请先选择生产人员和配方」时先切换一次全选，仍无人员则输出明确空闲囚犯跳过文案
            snap1 = snap.model_copy(update={"prison": snap.prison.model_copy(update={"production_workshop_count": 1})})
            state_nw = ppa._ExecState(33_000_000, 2_600, 15_130, 30_000_000)
            taps_nw: list[str] = []

            def fake_ocr_nw(_ctx, _img, name, _roi):
                if "GridCur" in name:
                    return [{"text": "1号生产车间", "box": [849, 223, 101, 23]}]
                if "WsInterior" in name:
                    return [{"text": "生产", "box": [1202, 665, 50, 34]}]
                if "ProdSel_" in name:
                    return [{"text": "一键取消", "box": [1137, 482, 94, 24]}]
                if "ReSelChk" in name:
                    return [{"text": "一键全选", "box": [1136, 545, 97, 26]}]
                if "ProdCards_" in name:
                    return [{"text": "牛仔布织造法", "box": [193, 665, 99, 19]}]
                if "ReadyPanel" in name:
                    return [{"text": "请先选择生产人员和配方", "box": [930, 624, 180, 21]}]
                if "BackTop" in name:
                    return [{"text": "整顿中心 LV7"}]
                if "BackDock" in name:
                    return [{"text": "仓库"}, {"text": "订单站"}]
                return []

            with (
                mock.patch.object(ppa, "is_stopping", return_value=False),
                mock.patch.object(ppa, "safe_screencap", return_value=frame),
                mock.patch.object(ppa, "sleep_with_stop", return_value=True),
                mock.patch.object(ppa, "ocr_roi", side_effect=fake_ocr_nw),
                mock.patch.object(ppa, "tap_point", side_effect=lambda _c, nm, _p: taps_nw.append(nm) or True),
            ):
                ppa._exec_start_workshop_production(_FakeCtx(), state_nw, snap1, plan, "NoWrk_")

            self.assertEqual(len(state_nw.executed), 0)
            self.assertTrue(any("ToggleCancelAll" in t for t in taps_nw))
            self.assertTrue(any("ReSelAll" in t for t in taps_nw))
            self.assertTrue(any("暂无空闲可用囚犯" in s.detail for s in state_nw.skipped))

    def test_single_pass_skips_redundant_orders_and_shop_reentry(self) -> None:
        from unittest import mock
        from maa_resonance.logic.planning import (
            AccountSnapshot,
            PrisonOrder,
            PrisonPlanOptions,
            PrisonSnapshot,
            WalletSnapshot,
            build_prison_execution_plan,
            plan_prison,
        )

        with _real_maa_agent_env() as ok_maa:
            if not ok_maa:
                self.skipTest("maafw is not installed")
            import agent.prison_plan_action as ppa

            snapshot = AccountSnapshot(
                uid="8820083699",
                wallet=WalletSnapshot(coins=32_000_000, huashi=15_130),
                prison=PrisonSnapshot(prison_level=7, work_tickets=2_600),
            )
            opts = PrisonPlanOptions(reserve_coins=30_000_000)
            report = plan_prison(snapshot, opts)
            plan = build_prison_execution_plan(snapshot, report, opts)
            scanned_orders = [PrisonOrder(item_name="牛仔布", quantity=180, order_type="daily", stock_owned=0)]
            scanned_shop_rows = [
                {
                    "row_index": 0,
                    "recipe_name": "海草布剪裁法",
                    "base_good_name": "海草布",
                    "locked": True,
                    "remaining": 1,
                    "coin_cost": 800_000,
                    "ticket_cost": 8_000,
                    "exchange_point": (1140, 200),
                }
            ]

            class _FakeCtx:
                pass

            calls_a: list[str] = []
            with (
                mock.patch.object(ppa, "is_stopping", return_value=False),
                mock.patch.object(ppa, "_ensure_on_prison_overview", return_value=True),
                mock.patch.object(ppa, "_exec_claim_todo_tasks"),
                mock.patch.object(ppa, "_exec_checkin_prisoners"),
                mock.patch.object(ppa, "_exec_ensure_finance_auto_refill"),
                mock.patch.object(ppa, "_exec_deliver_orders", side_effect=lambda *a: calls_a.append("ord")),
                mock.patch.object(ppa, "_exec_upgrade_core_buildings", side_effect=lambda *a: calls_a.append("bld")),
                mock.patch.object(ppa, "_exec_expand_warehouses_coins_only", side_effect=lambda *a: calls_a.append("wh")),
                mock.patch.object(ppa, "_exec_exchange_rush_recipes", side_effect=lambda *a: calls_a.append("shop")),
                mock.patch.object(ppa, "_exec_predeposit_raw_workshops", side_effect=lambda *a: calls_a.append("raw")),
                mock.patch.object(ppa, "_exec_start_workshop_production", side_effect=lambda *a: calls_a.append("prod")),
            ):
                receipt_a = ppa._execute_safe_auto_actions(
                    _FakeCtx(),
                    snapshot=snapshot,
                    prison_report=report,
                    execution_plan=plan,
                    auto_scope="full_safe",
                    prefix="DedupA_",
                    orders_scanned=True,
                    scanned_orders=scanned_orders,
                    scanned_shop_rows=scanned_shop_rows,
                )
            self.assertNotIn("ord", calls_a)
            self.assertNotIn("shop", calls_a)
            self.assertTrue(any(o.action_type == "order_deliver" for o in receipt_a.skipped))
            self.assertTrue(any(o.action_type == "exchange_ticket_buy" and "跳过二次进店" in o.detail for o in receipt_a.skipped))

            # 若研发中心刚在本趟升过级，即使首轮扫店无可买项仍应进店重查新解锁配方
            calls_b: list[str] = []

            def fake_bld(_ctx, st, *_args):
                calls_b.append("bld")
                st.upgraded_buildings["research_center"] = 1

            with (
                mock.patch.object(ppa, "is_stopping", return_value=False),
                mock.patch.object(ppa, "_ensure_on_prison_overview", return_value=True),
                mock.patch.object(ppa, "_exec_claim_todo_tasks"),
                mock.patch.object(ppa, "_exec_checkin_prisoners"),
                mock.patch.object(ppa, "_exec_ensure_finance_auto_refill"),
                mock.patch.object(ppa, "_exec_deliver_orders", side_effect=lambda *a: calls_b.append("ord")),
                mock.patch.object(ppa, "_exec_upgrade_core_buildings", side_effect=fake_bld),
                mock.patch.object(ppa, "_exec_expand_warehouses_coins_only", side_effect=lambda *a: calls_b.append("wh")),
                mock.patch.object(ppa, "_exec_exchange_rush_recipes", side_effect=lambda *a: calls_b.append("shop")),
                mock.patch.object(ppa, "_exec_predeposit_raw_workshops", side_effect=lambda *a: calls_b.append("raw")),
                mock.patch.object(ppa, "_exec_start_workshop_production", side_effect=lambda *a: calls_b.append("prod")),
            ):
                receipt_b = ppa._execute_safe_auto_actions(
                    _FakeCtx(),
                    snapshot=snapshot,
                    prison_report=report,
                    execution_plan=plan,
                    auto_scope="full_safe",
                    prefix="DedupB_",
                    orders_scanned=True,
                    scanned_orders=scanned_orders,
                    scanned_shop_rows=scanned_shop_rows,
                )
            self.assertNotIn("ord", calls_b)
            self.assertIn("shop", calls_b)
            self.assertEqual(receipt_b.upgraded_buildings, {"research_center": 1})

    def test_core_building_upgrades_multiple_rounds_and_tracks_deltas(self) -> None:
        from unittest import mock
        import numpy as np
        from maa_resonance.logic.planning import (
            AccountSnapshot,
            PrisonPlanOptions,
            PrisonSnapshot,
            WalletSnapshot,
            build_prison_execution_plan,
            plan_prison,
        )

        with _real_maa_agent_env() as ok_maa:
            if not ok_maa:
                self.skipTest("maafw is not installed")
            import agent.prison_plan_action as ppa

            frame = np.zeros((720, 1280, 3), dtype=np.uint8)
            snap = AccountSnapshot(
                uid="8820083699",
                wallet=WalletSnapshot(coins=32_000_000, huashi=15_130),
                prison=PrisonSnapshot(prison_level=7, work_tickets=2_600, buildings={"research_center": 3, "power_center": 3}),
            )
            opts = PrisonPlanOptions(reserve_coins=30_000_000)
            report = plan_prison(snap, opts)
            plan = build_prison_execution_plan(snap, report, opts)
            state = ppa._ExecState(32_000_000, 2_600, 15_130, 30_000_000)

            class _FakeCtx:
                pass

            def fake_ocr(_ctx, _img, name, _roi):
                if "Bld_research_centerGridCur" in name:
                    return [{"text": "研发中心LV3", "box": [840, 230, 110, 19]}]
                if "Bubble_research_center_r2" in name:
                    return []
                if "Bubble_research_center" in name:
                    return [{"text": "建设", "box": [788, 368, 48, 27]}]
                if "BuildPanel_research_center_r1" in name:
                    return [{"text": "50k / 32.0m", "box": [798, 529, 85, 17]}, {"text": "500/2.6k", "box": [898, 529, 87, 17]}]
                if "BuildPanel_research_center" in name:
                    return [{"text": "40k / 32.0m", "box": [798, 529, 85, 17]}, {"text": "400/2.6k", "box": [898, 529, 87, 17]}]
                if "BuildBtn_research_center" in name:
                    return [{"text": "建造", "box": [978, 594, 55, 31]}]
                if "Top" in name and "AfterOv_" not in name:
                    return [{"text": "整顿中心 LV7"}]
                if "Dock" in name and "AfterOv_" not in name:
                    return [{"text": "仓库"}, {"text": "订单站"}]
                return []

            with (
                mock.patch.object(ppa, "is_stopping", return_value=False),
                mock.patch.object(ppa, "safe_screencap", return_value=frame),
                mock.patch.object(ppa, "sleep_with_stop", return_value=True),
                mock.patch.object(ppa, "ocr_roi", side_effect=fake_ocr),
                mock.patch.object(ppa, "tap_point", return_value=True),
                mock.patch.object(ppa, "swipe_points", return_value=True),
            ):
                ppa._exec_upgrade_core_buildings(_FakeCtx(), state, plan, "Multi_")

            self.assertEqual(len(state.executed), 2)
            self.assertEqual(state.upgraded_buildings, {"research_center": 2})
            self.assertEqual(state.live_coins, 32_000_000 - 90_000)
            self.assertEqual(state.live_tickets, 2_600 - 900)

    def test_full_auto_new_parsers_planners_and_finance_toggle_pixel(self) -> None:
        import numpy as np
        from maa_resonance.logic.planning import (
            detect_finance_auto_refill_state,
            find_idle_prisoner_card_points,
            find_todo_claim_button_points,
            has_unset_workshop_leader,
            has_workshop_leader_set,
            parse_exchange_shop_item_rows,
            parse_prisoner_checkin_counts,
            parse_raw_workshop_prod_status,
            parse_workshop_machine_upgrade_cost,
            plan_prisoner_worker_allocation,
        )

        # 1. 事项一览领取坐标按 Y 升序且排除「已领取」
        pts = find_todo_claim_button_points(
            [
                {"text": "领取", "box": [1160, 380, 60, 30]},
                {"text": "已领取", "box": [1160, 240, 70, 30]},
                {"text": "领取", "box": [1160, 95, 60, 30]},
            ]
        )
        self.assertEqual(pts, [(1190, 110), (1190, 395)])

        # 2. 办理入住计数解析
        self.assertEqual(
            parse_prisoner_checkin_counts(
                [{"text": "未整顿囚犯数量 4/32"}, {"text": "整顿中囚犯数量 11/24"}]
            ),
            (4, 11, 24),
        )
        self.assertEqual(parse_prisoner_checkin_counts([{"text": "暂无囚犯"}]), (0, None, None))

        # 3. 财务中心自动补满像素开关（10a OFF: left~140, mid~39; 11a ON: left~145, mid~145）
        off_img = np.full((720, 1280, 3), 39, dtype=np.uint8)
        off_img[415:426, 1026:1038] = (180, 140, 90)
        self.assertIs(detect_finance_auto_refill_state(off_img), False)

        on_img = np.full((720, 1280, 3), 39, dtype=np.uint8)
        on_img[415:426, 1026:1058] = (190, 150, 95)
        self.assertIs(detect_finance_auto_refill_state(on_img), True)
        self.assertIsNone(detect_finance_auto_refill_state(None))

        # 4. 兑换道具严格白名单（拦截逮捕令/超级帮帮券/桦石/锁定，仅留协议与胶卷）
        items = parse_exchange_shop_item_rows(
            [
                {"text": "逮捕令", "box": [480, 200, 80, 22]},
                {"text": "100/200", "box": [680, 210, 80, 20]},
                {"text": "EXCHANGE", "box": [1110, 185, 80, 32]},
                {"text": "超级帮帮券", "box": [480, 330, 110, 22]},
                {"text": "15.1k/10 桦石", "box": [680, 340, 120, 20]},
                {"text": "拉普拉斯协议", "box": [480, 455, 110, 24]},
                {"text": "8k/8k", "box": [680, 460, 80, 20]},
                {"text": "剩余2次", "box": [1115, 495, 70, 20]},
                {"text": "EXCHANGE", "box": [1110, 450, 80, 32]},
                {"text": "自观测胶卷", "box": [480, 585, 110, 24]},
                {"text": "LEVEL 15", "box": [720, 585, 90, 22]},
                {"text": "100/4k", "box": [680, 610, 80, 20]},
            ]
        )
        self.assertEqual([r["item_name"] for r in items], ["拉普拉斯协议"])
        self.assertEqual(items[0]["ticket_cost"], 8000)

        # 5. 原料车间运行态、囚犯动态配比、空闲卡片筛选、机台升级与组长判断
        self.assertTrue(parse_raw_workshop_prod_status([{"text": "终止"}, {"text": "加速"}], [{"text": "工作名单 2/6"}])["running"])
        st_idle = parse_raw_workshop_prod_status([{"text": "开始生产"}], [{"text": "工作名单 0/6"}])
        self.assertFalse(st_idle["running"])
        self.assertTrue(st_idle["can_start"])

        self.assertEqual(plan_prisoner_worker_allocation(11, 4, 0, 2), {"raw_per_room": 2, "prod_reserve": 3})
        self.assertEqual(plan_prisoner_worker_allocation(11, 4, 100, 2), {"raw_per_room": 1, "prod_reserve": 7})
        self.assertEqual(plan_prisoner_worker_allocation(30, 4, 0, 2), {"raw_per_room": 6, "prod_reserve": 6})

        picked = find_idle_prisoner_card_points(
            [
                {"text": "10% 刑期 13天", "box": [80, 120, 100, 30]},
                {"text": "3% 选中", "box": [290, 250, 90, 28]},
                {"text": "12% 生产中", "box": [80, 400, 100, 30]},
                {"text": "6% 刑期 7天 剪裁", "box": [300, 400, 110, 30]},
            ],
            max_pick=3,
        )
        self.assertEqual(picked, [(118, 190), (326, 420)])

        mach_ok = parse_workshop_machine_upgrade_cost(
            [{"text": "31M/10K", "box": [965, 675, 65, 20]}, {"text": "100/100", "box": [1050, 675, 65, 20]}],
            [{"text": "机器升级", "box": [1145, 645, 90, 28]}],
        )
        self.assertTrue(mach_ok["can_upgrade"])
        self.assertEqual(mach_ok["required_coins"], 10_000)
        self.assertEqual(mach_ok["required_tickets"], 100)
        mach_hs = parse_workshop_machine_upgrade_cost(
            [{"text": "桦石", "box": [975, 675, 50, 20]}],
            [{"text": "机器升级", "box": [1145, 645, 90, 28]}],
        )
        self.assertTrue(mach_hs["huashi_blocked"])
        self.assertFalse(mach_hs["can_upgrade"])

        self.assertTrue(has_unset_workshop_leader([{"text": "车间组长 未设置"}]))
        self.assertFalse(has_unset_workshop_leader([{"text": "车间组长 鼹鼠"}]))
        self.assertTrue(has_workshop_leader_set([{"text": "车间组长"}, {"text": "鼹鼠"}]))
        self.assertFalse(has_workshop_leader_set([{"text": "车间组长"}, {"text": "未设置"}]))
        self.assertFalse(has_workshop_leader_set([{"text": "车间组长"}]))
        self.assertFalse(has_workshop_leader_set([]))

        # 实机日志回归：截断的「产中」、合1/金1/合2/金2/仓1 角标以及右下角误识单字 '8' 均不得误选
        picked_cross_ws = find_idle_prisoner_card_points(
            [
                # (0,0) 本车间已有工位
                {"text": "4号工位", "box": [85, 226, 70, 22]},
                {"text": "000011", "box": [170, 262, 42, 14]},
                # (0,1) 已被 2 号车间占用 合2
                {"text": "合2", "box": [170 + 208, 228, 30, 22]},
                {"text": "刑期 7天 000008", "box": [240, 100, 120, 24]},
                # (0,2) 已被 1 号车间占用 金1
                {"text": "金1", "box": [170 + 416, 228, 30, 22]},
                {"text": "刑期 6天 000004", "box": [450, 100, 120, 24]},
                # (0,3) 真正空闲囚犯
                {"text": "10% 刑期 6天", "box": [660, 110, 110, 24]},
                {"text": "000001", "box": [800, 262, 42, 14]},
                # (1,0) 实机右下角角标被误识成单字符 '8'
                {"text": "消防斧暴徒", "box": [30, 476, 81, 26]},
                {"text": "刑期", "box": [134, 317, 39, 20]},
                {"text": "000011", "box": [170, 484, 42, 14]},
                {"text": "8", "box": [172, 456, 14, 13]},
                # (1,1) 原料车间被截断成「产中」
                {"text": "12% 000009", "box": [240, 320, 90, 24]},
                {"text": "产中", "box": [333, 417, 39, 15]},
                # (1,2) 真正空闲囚犯
                {"text": "6% 刑期 7天 剪裁", "box": [470, 400, 110, 30]},
                # (1,3) 已被 1 号仓库占用 仓1
                {"text": "刑期 5天", "box": [660, 320, 80, 24]},
                {"text": "仓1", "box": [680, 445, 34, 20]},
            ],
            max_pick=6,
        )
        self.assertEqual(picked_cross_ws, [(742, 190), (534, 420)])

    def test_exec_upgrade_dynamically_unlocks_raw_and_orders_free_delete(self) -> None:
        from unittest import mock
        import numpy as np
        from maa_resonance.logic.planning import (
            ORDERS_DELETE_BTN_POINT,
            AccountSnapshot,
            PrisonPlanOptions,
            PrisonSnapshot,
            WalletSnapshot,
            build_prison_execution_plan,
            plan_prison,
        )

        with _real_maa_agent_env() as ok_maa:
            if not ok_maa:
                self.skipTest("maafw is not installed")
            import agent.prison_plan_action as ppa

            frame = np.zeros((720, 1280, 3), dtype=np.uint8)
            snap = AccountSnapshot(
                uid="8820083699",
                wallet=WalletSnapshot(coins=32_000_000, huashi=15_130),
                prison=PrisonSnapshot(
                    prison_level=7,
                    work_tickets=2_600,
                    buildings={"research_center": 6, "power_center": 7, "raw_sewing": 1},
                ),
            )
            opts = PrisonPlanOptions(reserve_coins=30_000_000)
            report = plan_prison(snap, opts)
            plan = build_prison_execution_plan(snap, report, opts)
            state = ppa._ExecState(32_000_000, 2_600, 15_130, 30_000_000)

            class _FakeCtx:
                pass

            def fake_bld_ocr(_ctx, _img, name, _roi):
                if "Top" in name and "AfterOv_" not in name:
                    return [{"text": "整顿中心 LV7"}]
                if "Dock" in name and "AfterOv_" not in name:
                    return [{"text": "仓库"}, {"text": "订单站"}]
                if "Bld_research_centerGridCur" in name:
                    return [{"text": "研发中心LV6", "box": [840, 230, 110, 19]}]
                if "Bld_raw_sewingGridCur" in name:
                    return [{"text": "缝纫工具原料车间LV1", "box": [840, 230, 145, 19]}]
                if "Bubble_research_center_r1" in name or "Bubble_raw_sewing_r1" in name:
                    return []
                if "Bubble_research_center" in name or "Bubble_raw_sewing" in name:
                    return [{"text": "建设", "box": [788, 368, 48, 27]}]
                if "BuildPanel_research_center_r1" in name or "BuildPanel_research_center_r2" in name:
                    return []
                if "BuildPanel_research_center" in name:
                    return [{"text": "70k / 32.0m", "box": [798, 529, 85, 17]}, {"text": "700/2.6k", "box": [898, 529, 87, 17]}]
                if "BuildBtn_research_center" in name and "_r1" not in name and "_r2" not in name:
                    return [{"text": "建造", "box": [978, 594, 55, 31]}]
                if "BuildPanel_raw_sewing_r1" in name or "BuildPanel_raw_sewing_r2" in name:
                    return []
                if "BuildPanel_raw_sewing" in name:
                    return [{"text": "100k / 32.0m", "box": [798, 529, 85, 17]}]
                if "BuildBtn_raw_sewing" in name and "_r1" not in name and "_r2" not in name:
                    return [{"text": "建造", "box": [978, 594, 55, 31]}]
                return []

            with (
                mock.patch.object(ppa, "is_stopping", return_value=False),
                mock.patch.object(ppa, "safe_screencap", return_value=frame),
                mock.patch.object(ppa, "sleep_with_stop", return_value=True),
                mock.patch.object(ppa, "ocr_roi", side_effect=fake_bld_ocr),
                mock.patch.object(ppa, "tap_point", return_value=True),
                mock.patch.object(ppa, "swipe_points", return_value=True),
            ):
                ppa._exec_upgrade_core_buildings(_FakeCtx(), state, plan, "DynRaw_", snap)

            self.assertEqual(state.upgraded_buildings.get("research_center"), 1)
            self.assertEqual(state.upgraded_buildings.get("raw_sewing"), 1)
            self.assertEqual(state.live_coins, 32_000_000 - 170_000)

            # 免费删单闭环（无二次确认直接进入订单调度中）
            ord_state = ppa._ExecState(32_000_000, 2_600, 15_130, 30_000_000)
            ord_taps: list[tuple[str, tuple[int, int]]] = []
            deleted_flag = {"done": False}

            def fake_ord_ocr(_ctx, _img, name, _roi):
                if "Top" in name:
                    return [{"text": "整顿中心 LV7"}]
                if "Dock" in name:
                    return [{"text": "仓库"}, {"text": "订单站"}]
                if "OrdChk" in name or "OrdHdr" in name:
                    return [{"text": "运输订单", "box": [900, 310, 100, 24]}]
                if "OrdDailyCard" in name:
                    return [{"text": "需求物资", "box": [550, 200, 90, 24]}]
                if "ExecOrdSlots" in name:
                    return [{"text": "整顿中心Lv10解锁", "box": [1100, 330, 120, 20]}]
                if "ExecOrdBody" in name:
                    if not deleted_flag["done"]:
                        return [{"text": "冲锋衣", "box": [550, 180, 80, 24]}, {"text": "120", "box": [780, 250, 50, 24]}]
                    return []
                if "ExecOrdBtn" in name:
                    return [{"text": "物资不足", "box": [850, 610, 90, 26]}]
                if "ExecOrdDelBtn" in name:
                    return [{"text": "删除订单", "box": [620, 618, 56, 20]}]
                if "ExecOrdDelSlots" in name:
                    return [{"text": "订单调度中 00:04:59", "box": [1100, 250, 130, 24]}]
                return []

            def fake_ord_tap(_ctx, name, pt):
                ord_taps.append((name, (int(pt[0]), int(pt[1]))))
                if "ExecOrdDelete" in name:
                    deleted_flag["done"] = True
                return True

            with (
                mock.patch.object(ppa, "is_stopping", return_value=False),
                mock.patch.object(ppa, "safe_screencap", return_value=frame),
                mock.patch.object(ppa, "sleep_with_stop", return_value=True),
                mock.patch.object(ppa, "ocr_roi", side_effect=fake_ord_ocr),
                mock.patch.object(ppa, "tap_point", side_effect=fake_ord_tap),
            ):
                ppa._exec_deliver_orders(_FakeCtx(), ord_state, snap, "rush_leveling", "DelOrd_")

            self.assertEqual(len(ord_state.executed), 1)
            self.assertEqual(ord_state.executed[0].action_type, "order_delete_free")
            self.assertEqual(ord_state.executed[0].target, "冲锋衣")
            self.assertTrue(any(n.startswith("DelOrd_ExecOrdDelete") for n, _ in ord_taps))

            # 事项一览领取坐标上移至按钮主体 + 无奖励/数量未降时防假连刷
            for with_reward in (True, False):
                td_state = ppa._ExecState(32_000_000, 0, 15_130, 30_000_000)
                td_taps: list[tuple[str, tuple[int, int]]] = []
                phase_box = {"claimed_once": False}

                def fake_td_ocr(_ctx, _img, name, _roi):
                    if "TodoBtn" in name:
                        return [{"text": "事项一览", "box": [1145, 122, 70, 30]}]
                    if "TodoTitle" in name:
                        return [{"text": "整顿中心任务"}]
                    if "TodoClaimList_0" in name:
                        return [{"text": "领取", "box": [1176, 123, 53, 32]}]
                    if "TodoClaimList_" in name:
                        return [] if (with_reward and phase_box["claimed_once"]) else [{"text": "领取", "box": [1176, 123, 53, 32]}]
                    if "TodoReward_0" in name and with_reward:
                        return [{"text": "获得物品"}, {"text": "触碰空白区域退出"}]
                    if "TodoClaimAfter_0" in name and not with_reward:
                        return [{"text": "领取", "box": [1176, 123, 53, 32]}]
                    if "Top" in name:
                        return [{"text": "整顿中心 LV7"}]
                    if "Dock" in name:
                        return [{"text": "仓库"}, {"text": "订单站"}]
                    return []

                def fake_td_tap(_ctx, name, pt):
                    td_taps.append((name, (int(pt[0]), int(pt[1]))))
                    if "TapTodoClaim_0" in name and with_reward:
                        phase_box["claimed_once"] = True
                    return True

                with (
                    mock.patch.object(ppa, "is_stopping", return_value=False),
                    mock.patch.object(ppa, "safe_screencap", return_value=frame),
                    mock.patch.object(ppa, "sleep_with_stop", return_value=True),
                    mock.patch.object(ppa, "ocr_roi", side_effect=fake_td_ocr),
                    mock.patch.object(ppa, "tap_point", side_effect=fake_td_tap),
                ):
                    ppa._exec_claim_todo_tasks(_FakeCtx(), td_state, "TdChk_")

                claim_pts = [pt for n, pt in td_taps if n == "TdChk_TapTodoClaim_0"]
                self.assertEqual(claim_pts, [(1202, 113)])
                if with_reward:
                    self.assertEqual(len(td_state.executed), 1)
                    self.assertEqual(td_state.live_tickets, 200)
                    self.assertTrue(any(n == "TdChk_TodoRewardDismiss_0" for n, _ in td_taps))
                else:
                    self.assertEqual(len(td_state.executed), 0)
                    self.assertEqual(td_state.live_tickets, 0)

    def test_custom_modules_tuning_options_and_action_issue_bundle_export(self) -> None:
        from contextlib import redirect_stderr, redirect_stdout
        import io
        from unittest import mock
        import zipfile
        from maa_resonance.logic.planning import (
            PROD_DUR_2H_POINT,
            AccountSnapshot,
            PrisonDiagnosticRecorder,
            PrisonOrder,
            PrisonPlanOptions,
            PrisonSnapshot,
            WalletSnapshot,
            build_prison_execution_plan,
            plan_prison,
            resolve_prison_runtime_config,
        )

        with _real_maa_agent_env() as ok_maa:
            if not ok_maa:
                self.skipTest("maafw is not installed")
            if str(ROOT) not in sys.path:
                sys.path.insert(0, str(ROOT))
            import agent.prison_plan_action as ppa

            frame = np.zeros((720, 1280, 3), dtype=np.uint8)
            snap = AccountSnapshot(
                uid="8820083699",
                wallet=WalletSnapshot(coins=32_000_000, huashi=15_130),
                prison=PrisonSnapshot(
                    prison_level=7,
                    work_tickets=2_600,
                    production_workshop_count=1,
                    buildings={"research_center": 6, "power_center": 6},
                    active_orders=[PrisonOrder(item_name="冲锋衣", quantity=120, order_type="daily", stock_owned=0)],
                ),
            )
            opts = PrisonPlanOptions(reserve_coins=30_000_000)
            report = plan_prison(snap, opts)
            plan = build_prison_execution_plan(snap, report, opts)

            # 1. custom 范围只启用 order_deliver（禁用 order_delete_free）和 ws_start_prod + 2h 偏好 + cap=1
            cfg_custom = resolve_prison_runtime_config(
                {
                    "exec_mode": "execute_safe_auto",
                    "auto_scope": "custom",
                    "modules_ui_configured": True,
                    "mod_pick_order_deliver": True,
                    "mod_pick_order_delete_free": False,
                    "mod_pick_ws_start_prod": True,
                    "prod_duration_pref": "2h",
                    "warehouse_batch_cap": 1,
                    "core_upgrade_cap": 1,
                    "diag_export_mode": "bundle",
                }
            )
            diag_custom = PrisonDiagnosticRecorder(export_mode="bundle", root_path=ROOT, raw_uid="8820083699")

            calls_custom: list[str] = []
            taps_custom: list[tuple[str, tuple[int, int]]] = []

            class _FakeCtx:
                pass

            def fake_prod_ocr(_ctx, _img, name, _roi):
                if "GridCur" in name:
                    return [{"text": "1号生产车间", "box": [849, 223, 101, 23]}]
                if "WsInterior" in name:
                    return [
                        {"text": "车间编辑", "box": [1100, 665, 80, 34]},
                        {"text": "生产", "box": [1202, 665, 50, 34]},
                    ]
                if "ProdSel_" in name:
                    return [{"text": "一键取消", "box": [1137, 482, 94, 24]}]
                if "ProdCards_" in name:
                    return [{"text": "牛仔布织造法", "box": [193, 665, 99, 19]}]
                if "ReadyPanel_" in name or "DurChk_2_" in name:
                    return [{"text": "确定", "box": [1150, 660, 64, 28]}, {"text": "100/20", "box": [900, 580, 60, 22]}]
                if "ProdAfterChk" in name:
                    return []
                if "Top" in name or "BackTop" in name:
                    return [{"text": "整顿中心 LV7"}]
                if "Dock" in name or "BackDock" in name:
                    return [{"text": "仓库"}, {"text": "订单站"}]
                return []

            with (
                mock.patch.object(ppa, "is_stopping", return_value=False),
                mock.patch.object(ppa, "_ensure_on_prison_overview", return_value=True),
                mock.patch.object(ppa, "_exec_claim_todo_tasks", side_effect=lambda *a: calls_custom.append("todo")),
                mock.patch.object(ppa, "_exec_checkin_prisoners", side_effect=lambda *a: calls_custom.append("checkin")),
                mock.patch.object(ppa, "_exec_ensure_finance_auto_refill", side_effect=lambda *a: calls_custom.append("fin")),
                mock.patch.object(ppa, "_exec_upgrade_core_buildings", side_effect=lambda *a: calls_custom.append("bld")),
                mock.patch.object(ppa, "_exec_expand_warehouses_coins_only", side_effect=lambda *a: calls_custom.append("wh")),
                mock.patch.object(ppa, "_exec_exchange_rush_recipes", side_effect=lambda *a: calls_custom.append("shop")),
                mock.patch.object(ppa, "_exec_predeposit_raw_workshops", side_effect=lambda *a: calls_custom.append("raw")),
                mock.patch.object(ppa, "safe_screencap", return_value=frame),
                mock.patch.object(ppa, "sleep_with_stop", return_value=True),
                mock.patch.object(ppa, "ocr_roi", side_effect=fake_prod_ocr),
                mock.patch.object(ppa, "tap_point", side_effect=lambda _c, n, p: taps_custom.append((n, (int(p[0]), int(p[1])))) or True),
            ):
                receipt_c = ppa._execute_safe_auto_actions(
                    _FakeCtx(),
                    snapshot=snap,
                    prison_report=report,
                    execution_plan=plan,
                    auto_scope="custom",
                    prefix="Cust_",
                    orders_scanned=True,
                    scanned_orders=snap.prison.active_orders,
                    runtime_config=cfg_custom,
                    diag=diag_custom,
                )

            # 只运行了车间排产；未勾选阶段与未勾选 order_delete_free 均不触碰
            self.assertEqual(calls_custom, [])
            tap_names = [n for n, _ in taps_custom]
            self.assertFalse(any("TapWsEdit" in n for n in tap_names))
            self.assertFalse(any("Dur_8h" in n or "Dur_4h" in n for n in tap_names))
            self.assertIn(("Cust_Dur_2h_1号生产车间", PROD_DUR_2H_POINT), taps_custom)
            self.assertEqual(len(receipt_c.executed), 1)
            self.assertIn("2小时", receipt_c.executed[0].detail)

            # 2. PrisonPlanScanAction 正常退出导出 zip，且异常崩溃时导出带 traceback 的紧急排错包
            with tempfile.TemporaryDirectory() as tmp_dir:
                tmp_root = Path(tmp_dir)
                acc_dir = tmp_root / "config" / "accounts"
                acc_dir.mkdir(parents=True, exist_ok=True)
                acc_file = acc_dir / "8820083699.json"
                acc_file.write_text(json.dumps({"uid": "8820083699"}), encoding="utf-8")

                ctx_ok = SimpleNamespace(
                    tasker=SimpleNamespace(stopping=False),
                    get_node_data=lambda name: {
                        "PrisonPlanOptExecMode": {"attach": {"exec_mode": "plan_only"}},
                        "PrisonPlanOptAutoOpenReport": {"attach": {"auto_open_report": False}},
                        "PrisonPlanOptDebugExport": {"attach": {"diag_export_mode": "bundle_screenshots"}},
                    }.get(name),
                )
                buf = io.StringIO()
                with (
                    patch.object(ppa, "ROOT_PATH", tmp_root),
                    patch.object(ppa, "find_account_config", return_value=(acc_file, {"uid": "8820083699"})),
                    patch.object(ppa, "_navigate_lobby_to_prison", return_value=(False, "8820083699", {}, "not_at_city")),
                    patch.object(ppa, "safe_screencap", return_value=frame),
                    patch.object(ppa, "ocr_roi", return_value=[]),
                    patch.object(ppa, "sleep_with_stop", return_value=True),
                    redirect_stdout(buf),
                ):
                    res_ok = ppa.PrisonPlanScanAction().run(ctx_ok, SimpleNamespace(custom_action_param="{}"))

                self.assertTrue(res_ok.success)
                logs_dir = tmp_root / "config" / "planning" / "logs"
                zips = list(logs_dir.glob("prison_issue_*.zip"))
                self.assertEqual(len(zips), 1)
                self.assertIn(zips[0].name, buf.getvalue())
                html_saved = (tmp_root / "config" / "planning" / "latest_report_8820083699.html").read_text(encoding="utf-8")
                self.assertIn(zips[0].name, html_saved)
                self.assertNotIn("http://", html_saved)
                self.assertNotIn("https://", html_saved)

                with zipfile.ZipFile(zips[0], "r") as zf:
                    self.assertTrue(any(n.startswith("screenshots/") for n in zf.namelist()))

                # 模拟未捕获异常 -> 自动生成带堆栈的紧急排错包并在日志中输出包名
                buf_err = io.StringIO()
                buf_stderr = io.StringIO()
                with (
                    patch.object(ppa, "ROOT_PATH", tmp_root),
                    patch.object(ppa, "safe_screencap", return_value=frame),
                    patch.object(ppa, "ocr_roi", side_effect=RuntimeError("mock_ocr_crash")),
                    redirect_stdout(buf_err),
                    redirect_stderr(buf_stderr),
                ):
                    res_err = ppa.PrisonPlanScanAction().run(ctx_ok, SimpleNamespace(custom_action_param="{}"))

                self.assertFalse(res_err.success)
                zips_after = sorted(logs_dir.glob("prison_issue_*.zip"))
                self.assertEqual(len(zips_after), 2)
                self.assertIn("mock_ocr_crash", buf_err.getvalue())
                self.assertIn("prison_issue_", buf_err.getvalue())

    def test_workshop_skips_edit_when_leader_set_and_scans_slots_for_leader(self) -> None:
        from unittest import mock
        from maa_resonance.logic.planning import (
            AccountSnapshot,
            PrisonDiagnosticRecorder,
            PrisonPlanOptions,
            PrisonSnapshot,
            WS_EDIT_MACHINE_SLOT_CENTERS,
            WalletSnapshot,
            build_prison_execution_plan,
            plan_prison,
        )

        with _real_maa_agent_env() as ok_maa:
            if not ok_maa:
                self.skipTest("maafw is not installed")
            import agent.prison_plan_action as ppa

            frame = np.zeros((720, 1280, 3), dtype=np.uint8)
            snap = AccountSnapshot(
                uid="8820083699",
                wallet=WalletSnapshot(coins=33_000_000, huashi=15_130),
                prison=PrisonSnapshot(
                    prison_level=7,
                    work_tickets=2_600,
                    prisoners_current=5,
                    production_workshop_count=1,
                    buildings={"research_center": 4, "power_center": 6},
                ),
            )
            opts = PrisonPlanOptions(reserve_coins=30_000_000)
            report = plan_prison(snap, opts)
            plan = build_prison_execution_plan(snap, report, opts)

            class _FakeCtx:
                pass

            # 1. 车间组长已设、本次未新入住、机台升级不触发 -> 跳过车间编辑，直接点「生产」
            diag_skip = PrisonDiagnosticRecorder(export_mode="log_only", root_path=ROOT, raw_uid="8820083699")
            state_skip = ppa._ExecState(
                33_000_000,
                2_600,
                15_130,
                30_000_000,
                prisoners_checked_in=0,
                diag=diag_skip,
            )
            taps_skip: list[str] = []

            def fake_ocr_skip(_ctx, _img, name, _roi):
                if "GridCur" in name:
                    return [{"text": "1号生产车间", "box": [849, 223, 101, 23]}]
                if "WsInterior" in name:
                    return [
                        {"text": "车间编辑", "box": [1100, 665, 80, 34]},
                        {"text": "生产", "box": [1202, 665, 50, 34]},
                    ]
                if "WsLeaderTop" in name:
                    return [{"text": "车间组长"}, {"text": "鼹鼠"}]
                if "ProdSel_" in name:
                    return [{"text": "一键取消", "box": [1137, 482, 94, 24]}]
                if "ProdCards_" in name:
                    return [{"text": "牛仔布织造法", "box": [193, 665, 99, 19]}]
                if "ReadyPanel_" in name or "DurChk_8_" in name:
                    return [{"text": "确定", "box": [1150, 660, 64, 28]}, {"text": "100/80", "box": [900, 580, 60, 22]}]
                if "ProdAfterChk" in name:
                    return []
                if "BackTop" in name:
                    return [{"text": "整顿中心 LV7"}]
                if "BackDock" in name:
                    return [{"text": "仓库"}, {"text": "订单站"}]
                return []

            with (
                mock.patch.object(ppa, "is_stopping", return_value=False),
                mock.patch.object(ppa, "safe_screencap", return_value=frame),
                mock.patch.object(ppa, "sleep_with_stop", return_value=True),
                mock.patch.object(ppa, "ocr_roi", side_effect=fake_ocr_skip),
                mock.patch.object(ppa, "tap_point", side_effect=lambda _c, nm, _p: taps_skip.append(nm) or True),
            ):
                ppa._exec_start_workshop_production(_FakeCtx(), state_skip, snap, plan, "SkipEd_")

            self.assertFalse(any("TapWsEdit" in t for t in taps_skip))
            self.assertIn("SkipEd_TapProd_1号生产车间", taps_skip)
            self.assertTrue(any(e["event"] == "ws_edit_skipped" for e in diag_skip.events))
            self.assertEqual([e.target for e in state_skip.executed], ["牛仔布"])

            # 2. 虽然组长已设，但本次有新入住囚犯 -> 仍需进入车间编辑并打开快速编队
            state_ci = ppa._ExecState(33_000_000, 2_600, 15_130, 30_000_000, prisoners_checked_in=1)
            taps_ci: list[str] = []

            def fake_ocr_ci(_ctx, _img, name, _roi):
                if "WsEditChk" in name:
                    return [{"text": "快速编队", "box": [80, 480, 80, 28]}]
                if "QtCnt" in name:
                    return [{"text": "囚犯 5/6", "box": [40, 660, 80, 26]}]
                if "QtGrid" in name:
                    return []
                if "WsEditLeaderChk" in name:
                    return [{"text": "车间组长"}, {"text": "鼹鼠"}]
                return fake_ocr_skip(_ctx, _img, name, _roi)

            with (
                mock.patch.object(ppa, "is_stopping", return_value=False),
                mock.patch.object(ppa, "safe_screencap", return_value=frame),
                mock.patch.object(ppa, "sleep_with_stop", return_value=True),
                mock.patch.object(ppa, "ocr_roi", side_effect=fake_ocr_ci),
                mock.patch.object(ppa, "tap_point", side_effect=lambda _c, nm, _p: taps_ci.append(nm) or True),
            ):
                ppa._exec_start_workshop_production(_FakeCtx(), state_ci, snap, plan, "NewCi_")

            self.assertIn("NewCi_TapWsEdit_1号生产车间", taps_ci)
            self.assertIn("NewCi_TapQuickTeam_1号生产车间", taps_ci)

            # 3. 组长未设置且 1~3 号槽无组员，仅 4 号槽有组员 -> 顺序探测到槽 3 并点击「设为组长」+ 应用
            state_ld = ppa._ExecState(33_000_000, 2_600, 15_130, 30_000_000, prisoners_checked_in=0)
            taps_ld: list[tuple[str, tuple[int, int]]] = []

            def fake_ocr_ld(_ctx, _img, name, _roi):
                if "WsLeaderTop" in name or "WsEditLeaderChk" in name:
                    return [{"text": "车间组长"}, {"text": "未设置"}]
                if "WsEditChk" in name:
                    return [{"text": "快速编队", "box": [80, 480, 80, 28]}]
                if "QtCnt" in name:
                    return [{"text": "囚犯 1/6", "box": [40, 660, 80, 26]}]
                if "QtGrid" in name:
                    return []
                if "WsSetLeaderBtn_1号生产车间_3" in name:
                    return [{"text": "设为组长", "box": [635, 642, 80, 28]}]
                if "WsSetLeaderBtn_" in name:
                    return []
                return fake_ocr_skip(_ctx, _img, name, _roi)

            with (
                mock.patch.object(ppa, "is_stopping", return_value=False),
                mock.patch.object(ppa, "safe_screencap", return_value=frame),
                mock.patch.object(ppa, "sleep_with_stop", return_value=True),
                mock.patch.object(ppa, "ocr_roi", side_effect=fake_ocr_ld),
                mock.patch.object(ppa, "tap_point", side_effect=lambda _c, nm, pt: taps_ld.append((nm, (int(pt[0]), int(pt[1])))) or True),
            ):
                ppa._exec_start_workshop_production(_FakeCtx(), state_ld, snap, plan, "LdScan_")

            slot_taps = [n for n, _ in taps_ld if "Leader_" in n and "WsSlot" in n]
            self.assertEqual(
                slot_taps,
                [
                    "LdScan_WsSlot0Leader_1号生产车间",
                    "LdScan_WsSlot1Leader_1号生产车间",
                    "LdScan_WsSlot2Leader_1号生产车间",
                    "LdScan_WsSlot3Leader_1号生产车间",
                ],
            )
            self.assertIn(("LdScan_WsSlot3Leader_1号生产车间", WS_EDIT_MACHINE_SLOT_CENTERS[3]), taps_ld)
            self.assertTrue(any(n == "LdScan_WsSetLeader_1号生产车间" for n, _ in taps_ld))
            self.assertTrue(any(n == "LdScan_WsEditApply_1号生产车间" for n, _ in taps_ld))
            self.assertTrue(any(e.action_type == "ws_set_leader" for e in state_ld.executed))


if __name__ == "__main__":
    unittest.main()
