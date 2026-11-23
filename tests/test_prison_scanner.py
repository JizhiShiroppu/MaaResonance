from __future__ import annotations

from contextlib import contextmanager, redirect_stdout
import importlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np

from maa_resonance.logic.planning import (
    PrisonOrder,
    build_prison_execution_plan,
    evaluate_black_moon_order,
    find_city_prison_npc_point,
    find_dock_button_point,
    find_weekly_orders_tab_point,
    format_mxu_plain_summary,
    format_planning_report_html,
    is_orders_screen_entries,
    is_prison_overview_entries,
    is_warehouse_screen_entries,
    merge_prison_grid_scans,
    parse_cn_number,
    parse_drawer_clarity,
    parse_drawer_wallet,
    parse_orders_screen,
    parse_prison_grid_buildings,
    parse_prison_top_bar,
    parse_target_crews_text,
    parse_warehouse_screen,
    plan_prison,
    snapshot_from_account_payload,
)

ROOT = Path(__file__).resolve().parents[1]


@contextmanager
def _real_maa_resource():
    saved = {}
    maa_mod = sys.modules.get("maa")
    stashed = maa_mod is not None and not hasattr(maa_mod, "__path__")
    if stashed:
        for name in list(sys.modules):
            if name == "maa" or name.startswith("maa."):
                saved[name] = sys.modules.pop(name)
    try:
        try:
            resource_mod = importlib.import_module("maa.resource")
            yield resource_mod.Resource
        except ImportError:
            yield None
    finally:
        if stashed:
            for name in list(sys.modules):
                if name == "maa" or name.startswith("maa."):
                    sys.modules.pop(name, None)
            sys.modules.update(saved)


class PrisonScannerLogicTests(unittest.TestCase):
    def test_parse_cn_number_formats(self) -> None:
        self.assertEqual(parse_cn_number("31,641,061"), 31_641_061)
        self.assertEqual(parse_cn_number("14880"), 14_880)
        self.assertEqual(parse_cn_number("31.6M"), 31_600_000)
        self.assertEqual(parse_cn_number("7.5K"), 7_500)
        self.assertEqual(parse_cn_number("250万"), 2_500_000)
        self.assertEqual(parse_cn_number("1.2亿"), 120_000_000)
        self.assertIsNone(parse_cn_number("未解锁"))

    def test_parse_prison_top_bar_merged_and_split(self) -> None:
        merged_entries = [
            {"text": "整顿中心 LV7", "box": [370, 20, 120, 28]},
            {"text": "0/80", "box": [410, 46, 70, 22]},
            {"text": "囚犯 11/24", "box": [840, 25, 110, 28]},
            {"text": "电力 5150/13800", "box": [1010, 25, 150, 28]},
        ]
        parsed = parse_prison_top_bar(merged_entries)
        self.assertEqual(parsed["level"], 7)
        self.assertEqual(parsed["exp"], 0)
        self.assertEqual(parsed["exp_next"], 80)
        self.assertEqual(parsed["prisoners_current"], 11)
        self.assertEqual(parsed["prisoners_capacity"], 24)
        self.assertEqual(parsed["power_used"], 5150)
        self.assertEqual(parsed["power_max"], 13800)

        split_entries = [
            {"text": "LV", "box": [400, 25, 28, 26]},
            {"text": "7", "box": [434, 25, 18, 26]},
            {"text": "0/80", "box": [415, 52, 60, 20]},
            {"text": "11/24", "box": [870, 26, 65, 24]},
            {"text": "5150", "box": [1030, 26, 52, 24]},
            {"text": "/13800", "box": [1086, 26, 74, 24]},
        ]
        split_parsed = parse_prison_top_bar(split_entries)
        self.assertEqual(split_parsed["level"], 7)
        self.assertEqual(split_parsed["power_used"], 5150)
        self.assertEqual(split_parsed["power_max"], 13800)
        self.assertEqual(split_parsed["prisoners_current"], 11)
        self.assertEqual(split_parsed["prisoners_capacity"], 24)

    def test_parse_and_merge_grid_buildings_ignores_locked(self) -> None:
        left_scan = parse_prison_grid_buildings(
            [
                {"text": "2号整顿宿舍", "box": [430, 140, 130, 28]},
                {"text": "1号整顿宿舍", "box": [430, 250, 130, 28]},
                {"text": "禁闭室", "box": [140, 250, 90, 28]},
                {"text": "LV1", "box": [155, 282, 50, 22]},
                {"text": "医务室 LV1", "box": [430, 360, 110, 28]},
                {"text": "假释室 LV1", "box": [430, 440, 110, 28]},
                {"text": "安保中心", "box": [140, 450, 100, 28]},
                {"text": "未解锁", "box": [150, 482, 70, 22]},
            ]
        )
        right_scan = parse_prison_grid_buildings(
            [
                {"text": "2号生产车间", "box": [660, 140, 130, 28]},
                {"text": "1号生产车间", "box": [660, 240, 130, 28]},
                {"text": "植物纤维原料车间", "box": [650, 320, 160, 28]},
                {"text": "未解锁", "box": [680, 352, 80, 22]},
                {"text": "研发中心", "box": [660, 410, 110, 28]},
                {"text": "LV3", "box": [680, 442, 50, 22]},
                {"text": "电力中心", "box": [950, 410, 110, 28]},
                {"text": "LV3", "box": [970, 442, 50, 22]},
                {"text": "转运中心 未解锁", "box": [950, 495, 160, 28]},
            ]
        )
        merged = merge_prison_grid_scans([left_scan, right_scan])
        self.assertEqual(merged["dorm_count"], 2)
        self.assertEqual(merged["production_workshop_count"], 2)
        self.assertEqual(merged["buildings"]["research_center"], 3)
        self.assertEqual(merged["buildings"]["power_center"], 3)
        self.assertEqual(merged["buildings"]["confinement_room"], 1)
        self.assertNotIn("raw_plant", merged["buildings"])
        self.assertNotIn("transfer_center", merged["buildings"])
        self.assertIn("raw_plant", merged["locked_buildings"])
        self.assertIn("security_center", merged["locked_buildings"])

    def test_parse_warehouse_screen_labeled_and_icon_only(self) -> None:
        labeled = parse_warehouse_screen(
            [
                {"text": "铁盟币 31,641,061", "box": [520, 22, 180, 28]},
                {"text": "桦石 14,880", "box": [780, 22, 120, 28]},
                {"text": "工票 7,500", "box": [980, 22, 120, 28]},
            ],
            [
                {"text": "原料仓库", "box": [220, 130, 110, 28]},
                {"text": "0/250", "box": [350, 130, 80, 28]},
                {"text": "成品仓库", "box": [640, 130, 110, 28]},
                {"text": "18/250", "box": [770, 130, 90, 28]},
            ],
        )
        self.assertEqual(labeled["coins"], 31_641_061)
        self.assertEqual(labeled["huashi"], 14_880)
        self.assertEqual(labeled["work_tickets"], 7500)
        self.assertEqual(labeled["raw_warehouse_used"], 0)
        self.assertEqual(labeled["raw_warehouse_cap"], 250)
        self.assertEqual(labeled["finished_warehouse_used"], 18)
        self.assertEqual(labeled["finished_warehouse_cap"], 250)

        icon_only = parse_warehouse_screen(
            [
                {"text": "31.6M", "box": [560, 24, 80, 26]},
                {"text": "14,880", "box": [790, 24, 80, 26]},
                {"text": "7.5K", "box": [990, 24, 70, 26]},
            ],
            [{"text": "原料仓库 5/250", "box": [220, 130, 150, 28]}],
        )
        self.assertEqual(icon_only["coins"], 31_600_000)
        self.assertEqual(icon_only["huashi"], 14_880)
        self.assertEqual(icon_only["work_tickets"], 7500)
        self.assertEqual(icon_only["raw_warehouse_used"], 5)

    def test_parse_warehouse_screen_live_1518_ignores_icon_noise(self) -> None:
        live_1518 = parse_warehouse_screen(
            [
                {"box": [251, 18, 31, 35], "text": "?"},
                {"box": [281, 24, 39, 25], "text": "帮助"},
                {"box": [963, 25, 91, 21], "text": "31771061"},
                {"box": [1075, 11, 47, 44], "text": "1"},
                {"box": [1181, 24, 80, 21], "text": "14880十"},
            ],
            [
                {"box": [1121, 205, 85, 27], "text": "原料仓库"},
                {"box": [1198, 266, 55, 23], "text": "0/250"},
                {"box": [1121, 539, 85, 27], "text": "成品仓库"},
                {"box": [1198, 598, 55, 24], "text": "0/250"},
            ],
        )
        self.assertEqual(live_1518["coins"], 31_771_061)
        self.assertEqual(live_1518["huashi"], 14_880)
        self.assertNotIn("work_tickets", live_1518)
        self.assertEqual(live_1518["raw_warehouse_cap"], 250)
        self.assertEqual(live_1518["finished_warehouse_cap"], 250)

    def test_is_orders_screen_entries_accepts_columba_header(self) -> None:
        self.assertTrue(
            is_orders_screen_entries(
                [
                    {"box": [249, 10, 36, 41], "text": "Q"},
                    {"box": [278, 24, 42, 22], "text": "帮助"},
                    {"box": [909, 83, 107, 31], "text": "COLUMBA"},
                ]
            )
        )
        self.assertFalse(is_orders_screen_entries([{"box": [278, 24, 42, 22], "text": "帮助"}]))

    def test_parse_orders_screen_and_planner_chain(self) -> None:
        daily = parse_orders_screen(
            [{"text": "黑月服装订单站", "box": [120, 25, 220, 32]}, {"text": "运输订单", "box": [240, 80, 120, 28]}],
            [
                {"text": "牛仔布", "box": [220, 220, 100, 28]},
                {"text": "180/180", "box": [220, 260, 110, 24]},
                {"text": "冲锋衣", "box": [540, 220, 100, 28]},
                {"text": "0/60", "box": [540, 260, 80, 24]},
                {"text": "普通布袋", "box": [860, 220, 110, 28]},
                {"text": "60/120", "box": [860, 260, 90, 24]},
            ],
            order_type="daily",
        )
        self.assertEqual(len(daily), 3)
        by_name = {o.item_name: o for o in daily}
        self.assertEqual(by_name["牛仔布"].stock_owned, 180)
        self.assertEqual(by_name["牛仔布"].quantity, 180)
        self.assertEqual(by_name["冲锋衣"].quantity, 60)

        weekly = parse_orders_screen(
            [{"text": "每周订单", "box": [440, 80, 120, 28]}],
            [{"text": "冲锋衣", "box": [260, 240, 100, 28]}, {"text": "400/1200", "box": [260, 280, 110, 24]}],
            order_type="weekly",
        )
        self.assertEqual(len(weekly), 1)
        self.assertEqual(weekly[0].order_type, "weekly")
        self.assertEqual(weekly[0].quantity, 1200)

        early_prison = snapshot_from_account_payload({"uid": "1", "prison": {"level": 7}}).prison
        self.assertEqual(evaluate_black_moon_order(by_name["牛仔布"], early_prison, "rush_leveling").action, "deliver")
        self.assertEqual(evaluate_black_moon_order(by_name["冲锋衣"], early_prison, "rush_leveling").action, "delete_free")
        self.assertEqual(evaluate_black_moon_order(weekly[0], early_prison, "rush_leveling").action, "produce_then_deliver")

    def test_nav_helpers_and_plain_summary(self) -> None:
        self.assertTrue(
            is_prison_overview_entries(
                [{"text": "LV7"}],
                [{"text": "仓库", "box": [40, 595, 60, 30]}, {"text": "订单", "box": [130, 595, 60, 30]}],
            )
        )
        self.assertEqual(
            find_dock_button_point([{"text": "订单", "box": [130, 595, 60, 30]}], ("订单",), (163, 610)),
            (160, 610),
        )
        self.assertEqual(
            find_city_prison_npc_point(
                [
                    {"text": "黑月服装订单站", "box": [300, 150, 140, 30]},
                    {"text": "整顿中心", "box": [890, 160, 100, 30]},
                ]
            ),
            (940, 175),
        )
        self.assertTrue(is_warehouse_screen_entries([{"text": "原料仓库"}, {"text": "成品仓库"}]))
        self.assertTrue(is_orders_screen_entries([{"text": "黑月服装订单站"}]))
        self.assertEqual(find_weekly_orders_tab_point([{"text": "每周订单", "box": [400, 80, 100, 30]}]), (450, 95))
        self.assertEqual(parse_target_crews_text("真咲, 苍叶、真咲\n瑞秋"), ["真咲", "苍叶", "瑞秋"])

        snap = snapshot_from_account_payload(
            {
                "uid": "8820083699",
                "wallet": {"coins": 31_641_061, "huashi": 14_880},
                "prison": {
                    "level": 7,
                    "work_tickets": 7500,
                    "dorm_count": 2,
                    "production_workshop_count": 2,
                    "active_orders": [{"item_name": "冲锋衣", "quantity": 60, "order_type": "daily"}],
                },
            }
        )
        report = plan_prison(snap)
        exec_plan = build_prison_execution_plan(snap, report)
        summary = format_mxu_plain_summary(
            report,
            report_path=Path(r"E:\Program Files\MaaResonance\config\planning\latest_report_8820083699.html"),
            execution_plan=exec_plan,
        )
        joined = "\n".join(summary)
        self.assertIn("整顿中心（实验型）", joined)
        self.assertIn("8820083699", joined)
        self.assertIn("造什么：", joined)
        self.assertIn("做什么：", joined)
        self.assertIn("买什么：", joined)
        self.assertIn("免费删", joined)
        self.assertIn("latest_report_8820083699.html", joined)
        self.assertLessEqual(len(summary), 6)
        self.assertNotIn("================", joined)
        self.assertNotIn("体力：", joined)

    def test_parse_drawer_clarity(self) -> None:
        self.assertEqual(
            parse_drawer_clarity(
                [
                    {"box": [181, 256, 79, 23], "text": "57/292+"},
                    {"box": [576, 648, 66, 18], "text": "整顿中心"},
                    {"box": [100, 420, 60, 20], "text": "1/10"},
                ]
            ),
            57,
        )
        self.assertIsNone(parse_drawer_clarity([{"box": [200, 500, 60, 20], "text": "57/292+"}]))

    def test_parse_drawer_wallet_from_live_1457_ocr(self) -> None:
        raw_1457 = [
            {"box": [118, 203, 41, 25], "text": "资产"},
            {"box": [181, 256, 79, 23], "text": "57/292+"},
            {"box": [194, 207, 75, 18], "text": "31771061"},
            {"box": [365, 259, 86, 17], "text": "466/824+"},
            {"box": [413, 206, 50, 19], "text": "14880"},
            {"box": [610, 258, 48, 19], "text": "1/975"},
        ]
        parsed = parse_drawer_wallet(raw_1457)
        self.assertEqual(parsed, {"clarity_estimate": 57, "coins": 31_771_061, "huashi": 14_880})
        # 即使 OCR 框把右侧疲劳/货舱排到澄明度前面，仍按 X 坐标取最左侧澄明度
        shuffled = [raw_1457[3], raw_1457[5], raw_1457[1], raw_1457[4], raw_1457[2], raw_1457[0]]
        self.assertEqual(parse_drawer_wallet(shuffled)["clarity_estimate"], 57)

    def test_parse_grid_live_1457_locked_requirements_and_bottom_row(self) -> None:
        center = parse_prison_grid_buildings(
            [
                {"box": [201, 111, 99, 20], "text": "2号整顿宿舍"},
                {"box": [202, 225, 98, 20], "text": "1号整顿宿舍"},
                {"box": [204, 451, 38, 21], "text": "餐厅"},
                {"box": [237, 449, 41, 20], "text": "LV1"},
                {"box": [850, 110, 102, 19], "text": "2号生产车间"},
                {"box": [852, 225, 97, 20], "text": "1号生产车间"},
                {"box": [933, 477, 137, 18], "text": "植物纤维原料车间"},
                {"box": [934, 498, 103, 20], "text": "研发中心等级"},
                {"box": [1036, 502, 33, 13], "text": "LV4"},
            ]
        )
        top_left = parse_prison_grid_buildings(
            [
                {"box": [718, 363, 96, 21], "text": "2号整顿宿舍"},
                {"box": [721, 481, 95, 16], "text": "1号整顿宿舍"},
                {"box": [800, 193, 100, 16], "text": "整顿中心等级"},
                {"box": [820, 165, 97, 27], "text": "3号整顿宿舍"},
                {"box": [901, 193, 40, 16], "text": "LV11"},
            ]
        )
        top_right = parse_prison_grid_buildings(
            [
                {"box": [205, 330, 97, 19], "text": "2号整顿宿舍"},
                {"box": [205, 445, 97, 20], "text": "1号整顿宿舍"},
                {"box": [285, 156, 101, 19], "text": "整顿中心等级"},
                {"box": [304, 131, 101, 26], "text": "3号整顿宿舍"},
                {"box": [384, 158, 42, 16], "text": "LV11"},
                {"box": [853, 330, 101, 19], "text": "2号生产车间"},
                {"box": [853, 442, 105, 24], "text": "1号生产车间"},
                {"box": [933, 156, 143, 19], "text": "整顿中心等级LV11"},
                {"box": [954, 135, 99, 19], "text": "3号生产车间"},
            ]
        )
        bottom_right = parse_prison_grid_buildings(
            [
                {"box": [332, 504, 180, 21], "text": "缝纫工具原料车间LV1"},
                {"box": [336, 161, 97, 20], "text": "1号生产车间"},
                {"box": [416, 413, 137, 20], "text": "植物纤维原料车间"},
                {"box": [418, 434, 104, 20], "text": "研发中心等级"},
                {"box": [516, 437, 36, 15], "text": "LV4"},
                {"box": [689, 504, 179, 19], "text": "人造纤维原料车间LV1"},
                {"box": [686, 620, 114, 25], "text": "电力中心LV3"},
                {"box": [485, 620, 96, 24], "text": "研发中心LV3"},
                {"box": [806, 413, 138, 20], "text": "动物纤维原料车间"},
                {"box": [808, 434, 134, 20], "text": "研发中心等级LV5"},
            ]
        )
        merged = merge_prison_grid_scans([center, top_left, top_right, bottom_right])
        self.assertEqual(merged["dorm_count"], 2)
        self.assertEqual(merged["production_workshop_count"], 2)
        self.assertEqual(merged["buildings"]["dormitory"], 1)
        self.assertEqual(merged["buildings"]["production_workshop"], 1)
        self.assertEqual(merged["buildings"]["power_center"], 3)
        self.assertEqual(merged["buildings"]["research_center"], 3)
        self.assertEqual(merged["buildings"]["raw_sewing"], 1)
        self.assertEqual(merged["buildings"]["raw_synthetic"], 1)
        self.assertNotIn("raw_plant", merged["buildings"])
        self.assertNotIn("raw_animal", merged["buildings"])
        self.assertIn("raw_plant", merged["locked_buildings"])
        self.assertIn("raw_animal", merged["locked_buildings"])

    def test_dock_button_icon_offset_and_merged_label_and_drawer_rejection(self) -> None:
        live_dock = [
            {"box": [56, 663, 38, 22], "text": "仓库"},
            {"box": [137, 663, 136, 23], "text": "订单站RCA-F02-B采购"},
            {"box": [309, 664, 71, 20], "text": "生活技能"},
            {"box": [394, 664, 72, 20], "text": "兑换商店"},
            {"box": [495, 662, 54, 23], "text": "拼单单"},
        ]
        wh_pt = find_dock_button_point(live_dock, ("仓库",), (73, 610))
        self.assertLessEqual(wh_pt[1], 620)
        self.assertEqual(wh_pt, (75, 616))
        ord_pt = find_dock_button_point(live_dock, ("订单",), (163, 610))
        self.assertEqual(ord_pt, (163, 610))

        live_left_drawer_dock = [
            {"box": [139, 649, 35, 18], "text": "仓库"},
            {"box": [249, 647, 39, 22], "text": "列车"},
            {"box": [348, 648, 68, 20], "text": "制造加工"},
            {"box": [469, 647, 53, 21], "text": "拼单单"},
            {"box": [575, 648, 68, 20], "text": "整顿中心"},
        ]
        self.assertFalse(is_prison_overview_entries([], live_left_drawer_dock))

    def test_format_planning_report_html_offline_and_escaped(self) -> None:
        snap = snapshot_from_account_payload(
            {
                "uid": "88<script>alert(1)</script>",
                "wallet": {"coins": 31_771_061, "huashi": 14_880, "clarity_estimate": 57},
                "prison": {
                    "level": 7,
                    "power_used": 5150,
                    "power_max": 13800,
                    "dorm_count": 2,
                    "production_workshop_count": 2,
                    "buildings": {"power_center": 3, "research_center": 3, "raw_sewing": 1},
                    "active_orders": [{"item_name": "冲锋衣", "quantity": 60, "order_type": "daily"}],
                },
            }
        )
        report = plan_prison(snap)
        exec_plan = build_prison_execution_plan(snap, report)
        html_doc = format_planning_report_html(
            report,
            growth_report=None,
            execution_plan=exec_plan,
            generated_at="2026-11-23 15:10:00",
        )
        self.assertIn("<!DOCTYPE html>", html_doc)
        self.assertIn("88&lt;script&gt;alert(1)&lt;/script&gt;", html_doc)
        self.assertNotIn("<script>alert(1)</script>", html_doc)
        self.assertNotIn("http://", html_doc)
        self.assertNotIn("https://", html_doc)
        self.assertIn("整顿中心（监狱）自动规划与执行清单", html_doc)
        self.assertIn("做什么（订单与排产）", html_doc)
        self.assertIn("买什么（扩仓/工票/采购）", html_doc)
        self.assertIn("造什么（升级顺序与设置）", html_doc)
        self.assertIn("护栏拦截清单", html_doc)
        self.assertNotIn("乘员养成缺口", html_doc)
        self.assertNotIn("养成规划报告", html_doc)
        self.assertIn("冲锋衣", html_doc)
        self.assertIn("14,880", html_doc)


class PrisonPlanActionTests(unittest.TestCase):
    def test_action_in_prison_scans_readonly_and_preserves_existing_snapshot(self) -> None:
        with _real_maa_resource() as Resource:
            if Resource is None:
                self.skipTest("maafw is not installed")
            import agent.prison_plan_action as ppa

            with tempfile.TemporaryDirectory() as tmp_dir:
                tmp_root = Path(tmp_dir)
                acc_dir = tmp_root / "config" / "accounts"
                acc_dir.mkdir(parents=True, exist_ok=True)
                acc_file = acc_dir / "8820083699.json"
                acc_file.write_text(
                    json.dumps(
                        {
                            "version": 1,
                            "uid": "8820083699",
                            "trade": {"cargo_capacity": 975, "available_cities": ["云岫桥基地", "海角城", "岚心城"]},
                            "prison": {"level": 6, "motors_installed": 5},
                        },
                        ensure_ascii=False,
                        indent=2,
                    ),
                    encoding="utf-8",
                )

                fake_img = np.zeros((720, 1280, 3), dtype=np.uint8)
                tapped_points: list[tuple[str, tuple[int, int]]] = []

                def fake_ocr(_ctx, _img, node_name: str, _roi):
                    if node_name.endswith(("InitTop", "TopBar")) or "BackTop" in node_name:
                        return [
                            {"text": "整顿中心 LV7", "box": [370, 20, 120, 28]},
                            {"text": "0/80", "box": [410, 46, 70, 22]},
                            {"text": "11/24", "box": [870, 25, 80, 26]},
                            {"text": "5150/13800", "box": [1020, 25, 130, 26]},
                        ]
                    if "Dock" in node_name:
                        return [
                            {"text": "仓库", "box": [43, 595, 60, 30]},
                            {"text": "订单", "box": [133, 595, 60, 30]},
                        ]
                    if "Gridtop_left" in node_name:
                        return [
                            {"text": "2号整顿宿舍", "box": [430, 140, 130, 28]},
                            {"text": "1号整顿宿舍", "box": [430, 250, 130, 28]},
                        ]
                    if "Gridbottom_right" in node_name:
                        return [
                            {"text": "研发中心 LV3", "box": [660, 410, 130, 28]},
                            {"text": "电力中心 LV3", "box": [950, 410, 130, 28]},
                        ]
                    if "Grid" in node_name:
                        return [
                            {"text": "1号生产车间", "box": [660, 240, 130, 28]},
                            {"text": "2号生产车间", "box": [660, 140, 130, 28]},
                        ]
                    if "WhChk" in node_name or "WhBody" in node_name:
                        return [
                            {"text": "原料仓库 0/250", "box": [220, 130, 160, 28]},
                            {"text": "成品仓库 0/250", "box": [640, 130, 160, 28]},
                        ]
                    if "WhTop" in node_name:
                        return [
                            {"text": "铁盟币 31,641,061", "box": [520, 22, 180, 28]},
                            {"text": "桦石 14,880", "box": [780, 22, 120, 28]},
                            {"text": "工票 7,500", "box": [980, 22, 120, 28]},
                        ]
                    if "OrdChk" in node_name or "OrdHdr" in node_name:
                        return [{"text": "黑月服装订单站", "box": [120, 25, 220, 32]}]
                    if "OrdBody" in node_name:
                        return [
                            {"text": "纯棉布料", "box": [220, 220, 110, 28]},
                            {"text": "60/180", "box": [220, 260, 90, 24]},
                        ]
                    return []

                def fake_tap(_ctx, name: str, pt):
                    tapped_points.append((name, (int(pt[0]), int(pt[1]))))
                    return True

                node_map = {
                    "PrisonPlanOptReserveCoins": {"attach": {"reserve_coins": 15_000_000}},
                    "PrisonPlanOptScanSubpages": {"attach": {"scan_subpages": True}},
                    "PrisonPlanOptHuashiStrategy": {"attach": {"allow_huashi_motors": False, "allow_huashi_warehouse": False}},
                    "PrisonPlanOptPlayerLevel": {"attach": {"player_level": 71}},
                    "PrisonPlanOptAutoOpenReport": {"attach": {"auto_open_report": True}},
                }
                ctx = SimpleNamespace(
                    tasker=SimpleNamespace(stopping=False),
                    get_node_data=lambda name: node_map.get(name),
                )
                argv = SimpleNamespace(custom_action_param="{}")

                opened_paths: list[Path] = []
                buf = io.StringIO()
                with (
                    patch.object(ppa, "ROOT_PATH", tmp_root),
                    patch.object(ppa, "find_account_config", return_value=(acc_file, {"uid": "8820083699"})),
                    patch.object(ppa, "safe_screencap", return_value=fake_img),
                    patch.object(ppa, "ocr_roi", side_effect=fake_ocr),
                    patch.object(ppa, "tap_point", side_effect=fake_tap),
                    patch.object(ppa, "swipe_points", return_value=True),
                    patch.object(ppa, "sleep_with_stop", return_value=True),
                    patch.object(ppa, "_open_report_in_browser", side_effect=lambda p: opened_paths.append(p) or True),
                    redirect_stdout(buf),
                ):
                    result = ppa.PrisonPlanScanAction().run(ctx, argv)

                self.assertTrue(result.success)
                # 确认只点过 仓库 / 订单 / 返回，绝无升级/消费动作
                tap_names = [name for name, _pt in tapped_points]
                self.assertTrue(any("TapWarehouse" in n for n in tap_names))
                self.assertTrue(any("TapOrders" in n for n in tap_names))
                self.assertTrue(any("Back" in n for n in tap_names))

                updated = json.loads(acc_file.read_text(encoding="utf-8"))
                self.assertEqual(updated["trade"]["cargo_capacity"], 975)
                self.assertEqual(updated["prison"]["level"], 7)
                self.assertEqual(updated["prison"]["motors_installed"], 5)
                self.assertEqual(updated["wallet"]["coins"], 31_641_061)
                self.assertEqual(updated["prison"]["active_orders"][0]["item_name"], "纯棉布料")

                md_path = tmp_root / "config" / "planning" / "latest_report_8820083699.md"
                json_path = tmp_root / "config" / "planning" / "latest_report_8820083699.json"
                html_path = tmp_root / "config" / "planning" / "latest_report_8820083699.html"
                self.assertTrue(md_path.is_file())
                self.assertTrue(json_path.is_file())
                self.assertTrue(html_path.is_file())
                self.assertEqual(opened_paths, [html_path])
                report_json = json.loads(json_path.read_text(encoding="utf-8"))
                self.assertIn("prison", report_json)
                self.assertIn("execution_plan", report_json)
                self.assertNotIn("growth", report_json)
                html_text = html_path.read_text(encoding="utf-8")
                self.assertIn("做什么（订单与排产）", html_text)
                self.assertNotIn("乘员养成缺口", html_text)
                self.assertIn("纯棉布料", buf.getvalue())

    def test_action_fallback_when_not_at_yunxiuqiao(self) -> None:
        with _real_maa_resource() as Resource:
            if Resource is None:
                self.skipTest("maafw is not installed")
            import agent.prison_plan_action as ppa

            with tempfile.TemporaryDirectory() as tmp_dir:
                tmp_root = Path(tmp_dir)
                acc_dir = tmp_root / "config" / "accounts"
                acc_dir.mkdir(parents=True, exist_ok=True)
                (acc_dir / "8820083699.json").write_text(
                    json.dumps(
                        {
                            "version": 1,
                            "uid": "8820083699",
                            "wallet": {"coins": 31_641_061, "huashi": 14_880},
                            "prison": {"level": 7, "work_tickets": 7500},
                        },
                        ensure_ascii=False,
                    ),
                    encoding="utf-8",
                )
                ctx = SimpleNamespace(tasker=SimpleNamespace(stopping=False), get_node_data=lambda _n: None)
                buf = io.StringIO()
                with (
                    patch.object(ppa, "ROOT_PATH", tmp_root),
                    patch.object(ppa, "safe_screencap", return_value=np.zeros((720, 1280, 3), dtype=np.uint8)),
                    patch.object(ppa, "ocr_roi", return_value=[]),
                    patch.object(
                        ppa,
                        "_navigate_lobby_to_prison",
                        return_value=(False, "8820083699", {"clarity_estimate": 57, "coins": 31_771_061, "huashi": 14_880}, "not_at_yunxiuqiao"),
                    ),
                    patch.object(ppa, "_open_report_in_browser", return_value=True),
                    redirect_stdout(buf),
                ):
                    result = ppa.PrisonPlanScanAction().run(ctx, SimpleNamespace(custom_action_param="{}"))

                self.assertTrue(result.success)
                self.assertIn("云岫桥基地", buf.getvalue())
                self.assertTrue((tmp_root / "config" / "planning" / "latest_report_8820083699.md").is_file())
                self.assertTrue((tmp_root / "config" / "planning" / "latest_report_8820083699.html").is_file())

    def test_action_enters_prison_via_drawer_tile_with_numpy_image_and_pushes_focus(self) -> None:
        with _real_maa_resource() as Resource:
            if Resource is None:
                self.skipTest("maafw is not installed")
            import agent.prison_plan_action as ppa

            with tempfile.TemporaryDirectory() as tmp_dir:
                tmp_root = Path(tmp_dir)
                acc_dir = tmp_root / "config" / "accounts"
                acc_dir.mkdir(parents=True, exist_ok=True)
                acc_file = acc_dir / "8820083699.json"
                acc_file.write_text(
                    json.dumps(
                        {
                            "version": 1,
                            "uid": "8820083699",
                            "trade": {"available_cities": ["云岫桥基地", "海角城", "岚心城"]},
                        },
                        ensure_ascii=False,
                    ),
                    encoding="utf-8",
                )

                fake_img = np.zeros((720, 1280, 3), dtype=np.uint8)
                drawer_entries = [
                    {"box": [118, 203, 41, 25], "text": "资产"},
                    {"box": [194, 207, 75, 18], "text": "31771061"},
                    {"box": [413, 206, 50, 19], "text": "14880"},
                    {"box": [181, 256, 79, 23], "text": "57/292+"},
                    {"box": [576, 648, 66, 18], "text": "整顿中心"},
                ]
                taps: list[tuple[str, tuple[int, int]]] = []
                overrides: list[dict] = []
                entered_prison = {"value": False}

                def fake_tap(_ctx, name: str, pt):
                    taps.append((name, (int(pt[0]), int(pt[1]))))
                    if "TapDrawerPrison" in name:
                        entered_prison["value"] = True
                    return True

                def fake_ocr(_ctx, _img, node_name: str, _roi):
                    if node_name.endswith("InitTop") or node_name.endswith("InitDock"):
                        return [{"text": "桥梁管理中心"}]
                    if not entered_prison["value"]:
                        return []
                    if "Top" in node_name:
                        return [
                            {"text": "整顿中心 LV7", "box": [370, 20, 120, 28]},
                            {"text": "0/80", "box": [410, 46, 70, 22]},
                            {"text": "11/24", "box": [870, 25, 80, 26]},
                            {"text": "5150/13800", "box": [1020, 25, 130, 26]},
                        ]
                    if "Dock" in node_name:
                        return [{"text": "仓库", "box": [43, 595, 60, 30]}, {"text": "订单", "box": [133, 595, 60, 30]}]
                    if "Grid" in node_name:
                        return [
                            {"text": "1号整顿宿舍", "box": [430, 250, 130, 28]},
                            {"text": "研发中心 LV3", "box": [660, 410, 130, 28]},
                            {"text": "电力中心 LV3", "box": [950, 410, 130, 28]},
                        ]
                    return []

                node_map = {
                    "PrisonPlanOptReserveCoins": {"attach": {"reserve_coins": 15_000_000}},
                    "PrisonPlanOptScanSubpages": {"attach": {"scan_subpages": False}},
                    "PrisonPlanOptAutoOpenReport": {"attach": {"auto_open_report": False}},
                }
                ctx = SimpleNamespace(
                    tasker=SimpleNamespace(stopping=False),
                    get_node_data=lambda name: node_map.get(name),
                    override_pipeline=lambda payload: overrides.append(payload) or True,
                )
                buf = io.StringIO()
                with (
                    patch.object(ppa, "ROOT_PATH", tmp_root),
                    patch.object(ppa, "safe_screencap", return_value=fake_img),
                    patch.object(ppa, "return_to_lobby", return_value=True),
                    patch.object(ppa, "open_drawer", return_value=(fake_img, drawer_entries)),
                    patch.object(ppa, "read_drawer_uid", return_value="8820083699"),
                    patch.object(ppa, "ocr_roi", side_effect=fake_ocr),
                    patch.object(ppa, "tap_point", side_effect=fake_tap),
                    patch.object(ppa, "swipe_points", return_value=True),
                    patch.object(ppa, "sleep_with_stop", return_value=True),
                    patch.object(ppa, "_open_report_in_browser", side_effect=AssertionError("auto_open_report=False 时不应打开浏览器")),
                    redirect_stdout(buf),
                ):
                    result = ppa.PrisonPlanScanAction().run(ctx, SimpleNamespace(custom_action_param="{}"))

                self.assertTrue(result.success)
                self.assertTrue(any("TapDrawerPrison" in name and pt == (609, 657) for name, pt in taps))
                self.assertFalse(any("TapVisit" in name for name, _pt in taps))

                saved = json.loads(acc_file.read_text(encoding="utf-8"))
                self.assertEqual(saved["wallet"]["coins"], 31_771_061)
                self.assertEqual(saved["wallet"]["huashi"], 14_880)
                self.assertEqual(saved["wallet"]["clarity_estimate"], 57)
                self.assertEqual(saved["prison"]["level"], 7)

                self.assertTrue(overrides)
                focus_text = overrides[-1]["PrisonPlanComplete"]["focus"]["Node.Action.Succeeded"]
                self.assertIn("UID 8820083699", focus_text)
                self.assertIn("LV7", focus_text)
                self.assertTrue((tmp_root / "config" / "planning" / "latest_report_8820083699.html").is_file())

    def test_warehouse_miss_still_on_overview_does_not_tap_back_and_cleans_stale_levels(self) -> None:
        with _real_maa_resource() as Resource:
            if Resource is None:
                self.skipTest("maafw is not installed")
            import agent.prison_plan_action as ppa

            with tempfile.TemporaryDirectory() as tmp_dir:
                tmp_root = Path(tmp_dir)
                acc_dir = tmp_root / "config" / "accounts"
                acc_dir.mkdir(parents=True, exist_ok=True)
                acc_file = acc_dir / "8820083699.json"
                acc_file.write_text(
                    json.dumps(
                        {
                            "version": 1,
                            "uid": "8820083699",
                            "wallet": {"coins": 31_771_061, "huashi": 14_880, "clarity_estimate": 57},
                            "prison": {
                                "level": 7,
                                "dorm_count": 3,
                                "production_workshop_count": 3,
                                "buildings": {
                                    "dormitory": 11,
                                    "production_workshop": 11,
                                    "raw_plant": 4,
                                    "raw_animal": 5,
                                    "research_center": 5,
                                },
                            },
                        },
                        ensure_ascii=False,
                    ),
                    encoding="utf-8",
                )

                fake_img = np.zeros((720, 1280, 3), dtype=np.uint8)
                tapped_points: list[tuple[str, tuple[int, int]]] = []
                in_orders_screen = {"value": False}

                def fake_tap(_ctx, name: str, pt):
                    tapped_points.append((name, (int(pt[0]), int(pt[1]))))
                    if "TapOrders" in name:
                        in_orders_screen["value"] = True
                    elif "OrdBack" in name:
                        in_orders_screen["value"] = False
                    return True

                def fake_ocr(_ctx, _img, node_name: str, _roi):
                    if node_name.endswith(("InitTop", "TopBar")) or "Top" in node_name:
                        return [
                            {"text": "LV7", "box": [432, 13, 42, 30]},
                            {"text": "10/80", "box": [554, 21, 42, 21]},
                            {"text": "11/24", "box": [940, 22, 52, 27]},
                            {"text": "5150/13800", "box": [1122, 25, 92, 21]},
                        ]
                    if "Dock" in node_name:
                        return [
                            {"box": [56, 663, 38, 22], "text": "仓库"},
                            {"box": [137, 663, 136, 23], "text": "订单站RCA-F02-B采购"},
                            {"box": [309, 664, 71, 20], "text": "生活技能"},
                            {"box": [394, 664, 72, 20], "text": "兑换商店"},
                            {"box": [495, 662, 54, 23], "text": "拼单单"},
                        ]
                    if "GridCenter" in node_name:
                        return [
                            {"box": [201, 111, 99, 20], "text": "2号整顿宿舍"},
                            {"box": [202, 225, 98, 20], "text": "1号整顿宿舍"},
                            {"box": [850, 110, 102, 19], "text": "2号生产车间"},
                            {"box": [852, 225, 97, 20], "text": "1号生产车间"},
                        ]
                    if "Gridtop_right" in node_name:
                        return [
                            {"box": [304, 131, 101, 26], "text": "3号整顿宿舍"},
                            {"box": [285, 156, 101, 19], "text": "整顿中心等级"},
                            {"box": [384, 158, 42, 16], "text": "LV11"},
                            {"box": [954, 135, 99, 19], "text": "3号生产车间"},
                            {"box": [933, 156, 143, 19], "text": "整顿中心等级LV11"},
                        ]
                    if "Gridbottom_right" in node_name:
                        return [
                            {"box": [332, 504, 180, 21], "text": "缝纫工具原料车间LV1"},
                            {"box": [689, 504, 179, 19], "text": "人造纤维原料车间LV1"},
                            {"box": [686, 620, 114, 25], "text": "电力中心LV3"},
                            {"box": [485, 620, 96, 24], "text": "研发中心LV3"},
                            {"box": [416, 413, 137, 20], "text": "植物纤维原料车间"},
                            {"box": [418, 434, 104, 20], "text": "研发中心等级"},
                            {"box": [516, 437, 36, 15], "text": "LV4"},
                            {"box": [806, 413, 138, 20], "text": "动物纤维原料车间"},
                            {"box": [808, 434, 134, 20], "text": "研发中心等级LV5"},
                        ]
                    # 模拟 TapWarehouse 点漏，仍停留在整顿中心总览（WhChk 返回空）
                    if "WhChk" in node_name:
                        return []
                    if in_orders_screen["value"] and ("OrdChk" in node_name or "OrdHdr" in node_name):
                        return [{"text": "黑月服装订单站", "box": [120, 25, 220, 32]}]
                    if in_orders_screen["value"] and "OrdBody" in node_name:
                        return [
                            {"text": "纯棉布料", "box": [220, 220, 110, 28]},
                            {"text": "30/180", "box": [220, 260, 90, 24]},
                        ]
                    return []

                node_map = {
                    "PrisonPlanOptScanSubpages": {"attach": {"scan_subpages": True}},
                    "PrisonPlanOptAutoOpenReport": {"attach": {"auto_open_report": False}},
                }
                ctx = SimpleNamespace(tasker=SimpleNamespace(stopping=False), get_node_data=lambda name: node_map.get(name))
                buf = io.StringIO()
                with (
                    patch.object(ppa, "ROOT_PATH", tmp_root),
                    patch.object(ppa, "find_account_config", return_value=(acc_file, {"uid": "8820083699"})),
                    patch.object(ppa, "safe_screencap", return_value=fake_img),
                    patch.object(ppa, "ocr_roi", side_effect=fake_ocr),
                    patch.object(ppa, "tap_point", side_effect=fake_tap),
                    patch.object(ppa, "swipe_points", return_value=True),
                    patch.object(ppa, "sleep_with_stop", return_value=True),
                    patch.object(ppa, "_open_report_in_browser", return_value=True),
                    redirect_stdout(buf),
                ):
                    result = ppa.PrisonPlanScanAction().run(ctx, SimpleNamespace(custom_action_param="{}"))

                self.assertTrue(result.success)
                tap_names = [name for name, _ in tapped_points]
                self.assertFalse(any("WhBack" in name for name in tap_names))
                self.assertTrue(any("TapOrders" in name for name in tap_names))

                cleaned = json.loads(acc_file.read_text(encoding="utf-8"))
                self.assertEqual(cleaned["prison"]["dorm_count"], 2)
                self.assertEqual(cleaned["prison"]["production_workshop_count"], 2)
                self.assertEqual(cleaned["prison"]["buildings"]["dormitory"], 1)
                self.assertEqual(cleaned["prison"]["buildings"]["production_workshop"], 1)
                self.assertEqual(cleaned["prison"]["buildings"]["research_center"], 3)
                self.assertEqual(cleaned["prison"]["buildings"]["power_center"], 3)
                self.assertNotIn("raw_plant", cleaned["prison"]["buildings"])
                self.assertNotIn("raw_animal", cleaned["prison"]["buildings"])
                self.assertEqual(cleaned["prison"]["active_orders"][0]["item_name"], "纯棉布料")


class PrisonPlanIntegrationTests(unittest.TestCase):
    def test_pipeline_task_and_subprocess_registration(self) -> None:
        pipe_path = ROOT / "assets/resource/base/pipeline/daily/prison_plan.json"
        task_path = ROOT / "assets/resource/tasks/PrisonPlanScan.json"
        iface_path = ROOT / "assets/interface.json"

        pipeline = json.loads(pipe_path.read_text(encoding="utf-8"))
        task_cfg = json.loads(task_path.read_text(encoding="utf-8"))
        iface_cfg = json.loads(iface_path.read_text(encoding="utf-8"))

        for node_name, node_def in pipeline.items():
            act = node_def.get("action")
            act_type = act.get("type") if isinstance(act, dict) else act
            self.assertNotIn(act_type, ("Click", "Swipe"), msg=node_name)
            for field in ("next", "on_error"):
                for ref in node_def.get(field) or []:
                    self.assertIn(ref, pipeline, msg=f"{node_name}.{field} -> {ref}")

        override_targets: set[str] = set()
        for opt_name, opt in task_cfg["option"].items():
            cases = opt.get("cases") or ([opt] if "pipeline_override" in opt else [])
            for case in cases:
                for child_opt in case.get("option") or []:
                    self.assertIn(child_opt, task_cfg["option"], msg=f"{opt_name} -> {child_opt}")
                for target_node in (case.get("pipeline_override") or {}).keys():
                    self.assertIn(target_node, pipeline)
                    override_targets.add(target_node)

        from agent.prison_plan_action import PRISON_PLAN_ATTACH_NODES

        self.assertEqual(override_targets, set(PRISON_PLAN_ATTACH_NODES))

        self.assertIn("resource/tasks/PrisonPlanScan.json", iface_cfg["import"])
        preset_map = {p["name"]: p for p in iface_cfg["preset"]}
        self.assertIn("prison-plan-scan", preset_map)
        self.assertEqual(preset_map["prison-plan-scan"]["label"], "整顿中心（监狱）自动（实验型）")
        self.assertEqual(task_cfg["task"][0]["label"], "整顿中心（监狱）自动（实验型）")
        daily_tasks = {t["name"]: t for t in preset_map["daily-all-in-one"]["task"]}
        self.assertIn("PrisonPlanScan", daily_tasks)
        self.assertFalse(bool(daily_tasks["PrisonPlanScan"]["enabled"]))

        with _real_maa_resource() as Resource:
            if Resource is None:
                self.skipTest("maafw is not installed")

        res_script = (
            "import sys; "
            f"sys.path.insert(0, {str(ROOT)!r}); "
            "from maa.resource import Resource; "
            "res = Resource(); "
            f"assert res.post_bundle({str(ROOT / 'assets/resource/base')!r}).wait().succeeded; "
            f"assert res.post_bundle({str(ROOT / 'assets/resource/pc')!r}).wait().succeeded; "
            "assert res.get_node_data('PrisonPlanStart') is not None; "
            "assert res.get_node_data('PrisonPlanOptEnabledModules') is not None; "
            "assert res.get_node_data('PrisonPlanOptCustomReserveCoins') is not None; "
            "assert res.get_node_data('PrisonPlanOptReserveCoins') is not None; "
            "assert res.get_node_data('PrisonPlanOptPlayerLevel') is not None; "
            "assert res.get_node_data('PrisonPlanOptProdDuration') is not None; "
            "assert res.get_node_data('PrisonPlanOptRawWorkerMode') is not None; "
            "assert res.get_node_data('PrisonPlanOptWarehouseBatchCap') is not None; "
            "assert res.get_node_data('PrisonPlanOptCoreUpgradeCap') is not None; "
            "assert res.get_node_data('PrisonPlanOptAutoOpenReport') is not None; "
            "assert res.get_node_data('PrisonPlanOptDebugExport') is not None; "
            "assert res.get_node_data('PrisonPlanComplete') is not None; "
        )
        res_proc = subprocess.run(
            [sys.executable, "-c", res_script],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(res_proc.returncode, 0, msg=res_proc.stderr or res_proc.stdout)

        agent_script = (
            "import sys; "
            f"sys.path.insert(0, {str(ROOT / 'agent')!r}); "
            f"sys.path.insert(0, {str(ROOT)!r}); "
            "from maa.agent.agent_server import AgentServer; "
            "import main; "
            "assert 'prison_plan_scan_run' in AgentServer._custom_action_holder; "
        )
        agent_proc = subprocess.run(
            [sys.executable, "-c", agent_script],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(agent_proc.returncode, 0, msg=agent_proc.stderr or agent_proc.stdout)


if __name__ == "__main__":
    unittest.main()
