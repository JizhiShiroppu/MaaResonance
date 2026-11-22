from __future__ import annotations

from contextlib import contextmanager
import importlib
import json
from pathlib import Path
import re
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np

from maa_resonance.logic.regional_combat import (
    REGIONAL_LOW_CLARITY_CANCEL_POINT,
    REGIONAL_LOW_CLARITY_CONFIRM_POINT,
    find_low_clarity_popup_button,
    find_regional_fight_button_box,
    find_selected_city_card,
    find_terminal_regional_combat_go_point,
    has_first_clear_badge,
    is_regional_combat_page,
    merge_city_catalog,
    parse_enemy_level,
    parse_level_range,
    parse_regional_city_cards,
    parse_stage_title,
    rank_unfinished_regional_cities,
    resolve_effective_max_enemy_level,
    resolve_effective_max_runs,
    select_unfinished_regional_cities,
    should_skip_for_enemy_level,
)

ROOT = Path(__file__).resolve().parents[1]


@contextmanager
def _real_maa_modules():
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


class RegionalCombatLogicTest(unittest.TestCase):
    def test_terminal_card_detection_ignores_security_agency_and_handles_fallback(self) -> None:
        terminal_entries = [
            {"text": "铁安协同终端", "box": [726, 38, 158, 28]},
            {"text": "铁安局", "box": [700, 379, 93, 35]},
            {"text": ">前往", "box": [617, 461, 261, 37]},
            {"text": "区域作战中心", "box": [1000, 378, 180, 36]},
            {"text": ">前往>>", "box": [961, 461, 260, 37]},
            {"text": "完成全部作战计划可获得", "box": [1009, 577, 191, 18]},
        ]
        self.assertEqual(find_terminal_regional_combat_go_point(terminal_entries), (1091, 480))

        # Missing '前往' button still falls back below the right card, never clicking left 铁安局 card.
        fallback_entries = [e for e in terminal_entries if e["text"] != ">前往>>"]
        self.assertEqual(find_terminal_regional_combat_go_point(fallback_entries), (1090, 481))

        # Must NOT match once already inside Regional Combat or Security Agency.
        self.assertIsNone(
            find_terminal_regional_combat_go_point(
                terminal_entries + [{"text": "前往作战", "box": [1048, 575, 104, 33]}]
            )
        )
        self.assertIsNone(
            find_terminal_regional_combat_go_point(
                terminal_entries + [{"text": "威胁等级", "box": [578, 176, 76, 23]}]
            )
        )

    def test_page_detection_badges_enemy_level_and_param_resolution(self) -> None:
        # 汇流塔 uses red header '真理演绎' instead of '形态污染清理计划', still detected cleanly.
        self.assertTrue(
            is_regional_combat_page(
                [{"text": "威胁等级", "box": [578, 176, 76, 23]}],
                [{"text": "点击变更难度", "box": [1013, 448, 76, 15]}],
                [{"text": "前往作战", "box": [1046, 573, 107, 37]}],
            )
        )
        self.assertIsNone(find_regional_fight_button_box([{"text": "变更难度"}]))
        self.assertFalse(
            is_regional_combat_page(
                [],
                [],
                [{"text": "前往作战", "box": [941, 522, 125, 33]}],
            )
        )

        self.assertTrue(has_first_clear_badge([{"text": "首通", "box": [654, 562, 32, 20]}]))
        self.assertFalse(has_first_clear_badge([{"text": "9"}, {"text": "4"}]))

        self.assertEqual(parse_enemy_level([{"text": "敌方等级：31"}]), 31)
        self.assertEqual(parse_enemy_level([{"text": "敌方等级: S6"}]), 56)
        self.assertIsNone(parse_enemy_level([{"text": "奖励"}]))

        self.assertEqual(
            parse_stage_title([
                {"text": "EVICTION PROCESS", "box": [568, 451, 90, 9]},
                {"text": "压力测验·园丁1", "box": [564, 418, 180, 32]},
            ]),
            "压力测验·园丁1",
        )

        self.assertEqual(parse_level_range("LV21~LV125"), (21, 125))
        self.assertEqual(parse_level_range("ELV56~LV80"), (56, 80))
        self.assertEqual(parse_level_range("LV36"), (36, None))

        self.assertTrue(should_skip_for_enemy_level(56, 50, city_min_level=41))
        self.assertFalse(should_skip_for_enemy_level(46, 50, city_min_level=41))
        # Missing enemy level falls back to city_min_level when cap > 0.
        self.assertTrue(should_skip_for_enemy_level(None, 50, city_min_level=51))
        self.assertFalse(should_skip_for_enemy_level(None, 50, city_min_level=46))
        self.assertFalse(should_skip_for_enemy_level(99, 0, city_min_level=99))

        self.assertEqual(
            resolve_effective_max_enemy_level({"max_enemy_level": 50, "use_custom_max_enemy_level": False}),
            50,
        )
        self.assertEqual(
            resolve_effective_max_enemy_level(
                {"max_enemy_level": 50, "use_custom_max_enemy_level": True, "custom_max_enemy_level": "65"}
            ),
            65,
        )
        self.assertEqual(resolve_effective_max_runs({"run_mode": "unlimited", "run_count": 5}), 0)
        self.assertEqual(resolve_effective_max_runs({"run_mode": "fixed_count", "run_count": "3"}), 3)

    def test_city_cards_parsing_splits_locked_and_yellow_arrow_selection(self) -> None:
        # Real OCR layout from top_tiemeng (includes split '作战进度' + '9%', '度14%', 'LV36' + 'V60').
        top_entries = [
            {"text": "荒原站", "box": [45, 156, 64, 29]},
            {"text": "LV21~LV30", "box": [337, 92, 96, 15]},
            {"text": "作战进度100%", "box": [312, 162, 141, 28]},
            {"text": "铁盟哨站", "box": [44, 275, 84, 32]},
            {"text": "LV21-LV125", "box": [329, 207, 105, 23]},
            {"text": "作战进度", "box": [341, 288, 69, 19]},
            {"text": "9%", "box": [406, 281, 46, 28]},
            {"text": "淘金乐园", "box": [46, 399, 80, 24]},
            {"text": "LV26~LV41", "box": [334, 328, 100, 22]},
            {"text": "作战进度62%", "box": [326, 405, 123, 23]},
            {"text": "阿妮塔能源研究所", "box": [49, 521, 149, 22]},
            {"text": "LV36", "box": [334, 446, 52, 26]},
            {"text": "V60", "box": [396, 451, 37, 17]},
            {"text": "作战进度40%", "box": [324, 520, 128, 31]},
            {"text": "阿妮塔战备工厂", "box": [49, 640, 128, 23]},
            {"text": "LV41-LV110", "box": [328, 565, 108, 25]},
            {"text": "作战进度", "box": [328, 648, 69, 19]},
            {"text": "度14%", "box": [386, 641, 63, 27]},
        ]
        cards = parse_regional_city_cards(top_entries)
        self.assertEqual(
            [(c["city_name"], c["percent"], c["min_level"], c["max_level"], c["stage_count"]) for c in cards],
            [
                ("荒原站", 100, 21, 30, 10),
                ("铁盟哨站", 9, 21, 125, 105),
                ("淘金乐园", 62, 26, 41, 16),
                ("阿妮塔能源研究所", 40, 36, 60, 25),
                ("阿妮塔战备工厂", 14, 41, 110, 70),
            ],
        )

        # Single-sided LV fragment without upper bound yields stage_count=None rather than 1.
        single_lv_cards = parse_regional_city_cards([
            {"text": "测试站", "box": [49, 521, 90, 22]},
            {"text": "LV36", "box": [334, 446, 52, 26]},
            {"text": "作战进度40%", "box": [324, 520, 128, 31]},
        ])
        self.assertEqual(single_lv_cards[0]["min_level"], 36)
        self.assertIsNone(single_lv_cards[0]["max_level"])
        self.assertIsNone(single_lv_cards[0]["stage_count"])

        # Rank all 9 real stations by fewest stages first.
        bottom_full_entries = [
            {"text": "云岫桥基地", "box": [45, 183, 101, 31]},
            {"text": "LV41~LV50", "box": [333, 115, 103, 25]},
            {"text": "作战进度0%", "box": [338, 191, 112, 28]},
            {"text": "栖羽站", "box": [45, 305, 65, 29]},
            {"text": "LV46~LV65", "box": [333, 236, 103, 23]},
            {"text": "作战进度0%", "box": [337, 309, 115, 31]},
            {"text": "汇流塔", "box": [44, 426, 66, 29]},
            {"text": "LV51~LV70", "box": [334, 357, 102, 22]},
            {"text": "作战进度", "box": [340, 435, 72, 22]},
            {"text": "0%", "box": [405, 428, 48, 33]},
            {"text": "远星大桥", "box": [45, 546, 84, 28]},
            {"text": "ELV56~LV80", "box": [329, 476, 107, 24]},
            {"text": "作战进度0%", "box": [338, 551, 112, 28]},
            {"text": "维蒂林场", "box": [46, 669, 80, 24]},
            {"text": "LOCK", "box": [248, 620, 58, 29]},
            {"text": "前往车站后解锁", "box": [332, 672, 117, 26]},
        ]
        catalog: dict[str, dict] = {}
        merge_city_catalog(catalog, cards)
        merge_city_catalog(catalog, parse_regional_city_cards(bottom_full_entries))
        ranked = rank_unfinished_regional_cities(list(catalog.values()), city_order="fewest_stages_first")
        self.assertEqual(
            [c["city_name"] for c in ranked],
            [
                "云岫桥基地",
                "淘金乐园",
                "栖羽站",
                "汇流塔",
                "阿妮塔能源研究所",
                "远星大桥",
                "阿妮塔战备工厂",
                "铁盟哨站",
            ],
        )

        # Level cap <= 35 skips 阿妮塔能源研究所 (36) and 阿妮塔战备工厂 (41), plus excluded 铁盟哨站.
        filtered = select_unfinished_regional_cities(
            top_entries,
            excluded_cities={"铁盟哨站"},
            max_enemy_level=35,
        )
        self.assertEqual([c["city_name"] for c in filtered], ["淘金乐园"])

        # Bottom list skips clipped top card (y=87) and LOCK card (维蒂林场 has no '%').
        bottom_entries = [
            {"text": "阿妮塔战备工厂", "box": [46, 75, 123, 17]},
            {"text": "作战进度14%", "box": [326, 75, 124, 24]},
            {"text": "云岫桥基地", "box": [45, 183, 101, 31]},
            {"text": "作战进度0%", "box": [338, 191, 112, 28]},
            {"text": "汇流塔", "box": [44, 426, 66, 29]},
            {"text": "作战进度", "box": [340, 435, 72, 22]},
            {"text": "0%", "box": [405, 428, 48, 33]},
            {"text": "维蒂林场", "box": [46, 669, 80, 24]},
            {"text": "LOCK", "box": [248, 620, 58, 29]},
            {"text": "前往车站后解锁", "box": [332, 672, 117, 26]},
        ]
        bottom_cards = parse_regional_city_cards(bottom_entries)
        self.assertEqual([c["city_name"] for c in bottom_cards], ["云岫桥基地", "汇流塔"])

        # Selected card yellow '<' '>' edges beat 100% gold progress bar.
        frame = np.full((720, 1280, 3), 40, dtype=np.uint8)
        # 100% gold bar on right side of 荒原站 (only right side, < 120 pixels)
        frame[160:175, 426:430] = (50, 200, 240)
        # Yellow arrows on both sides of 阿妮塔能源研究所 (center_y=535)
        frame[478:520, 15:25] = (40, 210, 250)
        frame[478:520, 435:445] = (40, 210, 250)
        selected = find_selected_city_card(frame, cards)
        self.assertIsNotNone(selected)
        self.assertEqual(selected["city_name"], "阿妮塔能源研究所")


class RegionalCombatActionFlowTest(unittest.TestCase):
    def _make_frame_with_selected(self, center_y: int = 295) -> np.ndarray:
        frame = np.full((720, 1280, 3), 30, dtype=np.uint8)
        y1 = max(65, center_y - 55)
        y2 = max(y1 + 25, center_y - 15)
        frame[y1:y2, 14:24] = (40, 210, 250)
        frame[y1:y2, 434:444] = (40, 210, 250)
        return frame

    def test_advance_retap_same_city_overlevel_and_scroll_flow(self) -> None:
        with _real_maa_modules() as Resource:
            if Resource is None:
                self.skipTest("maafw is not installed")
            import agent.regional_combat_action as rca

            rca._REGIONAL_STATE_BY_TASK.clear()
            img_top = self._make_frame_with_selected(295)
            img_bottom = self._make_frame_with_selected(195)

            city_top = [
                {"text": "荒原站", "box": [45, 156, 64, 29]},
                {"text": "作战进度100%", "box": [312, 162, 141, 28]},
                {"text": "铁盟哨站", "box": [44, 275, 84, 32]},
                {"text": "LV21~LV125", "box": [329, 207, 105, 23]},
                {"text": "作战进度9%", "box": [337, 280, 115, 31]},
            ]
            city_bottom = [
                {"text": "淘金乐园", "box": [46, 180, 80, 24]},
                {"text": "LV26~LV41", "box": [334, 120, 100, 22]},
                {"text": "作战进度62%", "box": [326, 183, 123, 23]},
            ]

            # 1) Same-city re-tap in list_order switches cleared stage back to uncleared '首通' stage.
            taps: list[tuple[int, int]] = []
            ctx = SimpleNamespace(
                tasker=SimpleNamespace(stopping=False),
                get_node_data=lambda _n: {
                    "attach": {"scope": "all_cities", "city_order": "list_order", "max_enemy_level": 50}
                },
            )
            argv = SimpleNamespace(
                node_name="RegionalCombatNeedsAdvance",
                task_detail=SimpleNamespace(task_id=1001),
                custom_action_param={},
            )

            ocr_seq_retap = [
                city_top,                               # Cur Cities
                [],                                     # Cur FC (no '首通')
                [{"text": "敌方等级：31"}],              # Cur Lv
                [{"text": "旧关"}],                      # Cur Title
                [{"text": "首通"}],                      # Retap FC (now has '首通')
                [{"text": "敌方等级：35"}],              # Retap Lv
                [{"text": "暴力鼹鼠帮"}],                # Retap Title
            ]

            action = rca.RegionalCombatAdvanceAction()
            with (
                patch.object(rca, "safe_screencap", return_value=img_top),
                patch.object(rca, "sleep_with_stop", return_value=True),
                patch.object(rca, "ocr_roi", side_effect=lambda *_a, **_kw: ocr_seq_retap.pop(0)),
                patch.object(rca, "tap_point", side_effect=lambda _c, _n, pt: taps.append(pt) or True),
            ):
                res = action.run(ctx, argv)
            self.assertTrue(res.success)
            self.assertEqual(len(taps), 1)
            self.assertEqual(ocr_seq_retap, [])

            # 2) Current city over-level in current_city scope returns failure (stops cleanly).
            rca._REGIONAL_STATE_BY_TASK.clear()
            ctx_cur = SimpleNamespace(
                tasker=SimpleNamespace(stopping=False),
                get_node_data=lambda _n: {"attach": {"scope": "current_city", "max_enemy_level": 40}},
            )
            ocr_seq_cur_over = [
                city_top,
                [{"text": "首通"}],
                [{"text": "敌方等级：55"}],
                [{"text": "高难关"}],
            ]
            with (
                patch.object(rca, "safe_screencap", return_value=img_top),
                patch.object(rca, "sleep_with_stop", return_value=True),
                patch.object(rca, "ocr_roi", side_effect=lambda *_a, **_kw: ocr_seq_cur_over.pop(0)),
            ):
                res_cur = action.run(ctx_cur, argv)
            self.assertFalse(res_cur.success)

            # 3) Over-level in all_cities scrolls down and selects eligible city 淘金乐园.
            rca._REGIONAL_STATE_BY_TASK.clear()
            swipes: list[tuple[int, int]] = []
            taps2: list[tuple[int, int]] = []
            ocr_seq_scroll = [
                city_top,
                [{"text": "首通"}],
                [{"text": "敌方等级：65"}],  # 铁盟哨站 over cap 50
                [{"text": "高难关"}],
                city_top,                    # Vis scan -> 铁盟哨站 excluded, none left
                city_bottom,                 # Down0 scan -> 淘金乐园 candidate
                [{"text": "首通"}],
                [{"text": "敌方等级：36"}],
                [{"text": "齿轮润滑·金子1"}],
            ]
            with (
                patch.object(rca, "safe_screencap", side_effect=[img_top, img_bottom, img_bottom]),
                patch.object(rca, "sleep_with_stop", return_value=True),
                patch.object(rca, "ocr_roi", side_effect=lambda *_a, **_kw: ocr_seq_scroll.pop(0)),
                patch.object(rca, "tap_point", side_effect=lambda _c, _n, pt: taps2.append(pt) or True),
                patch.object(rca, "swipe_points", side_effect=lambda _c, _n, p1, p2, **_kw: swipes.append(p1) or True),
            ):
                res_scroll = action.run(ctx, argv)
            self.assertTrue(res_scroll.success)
            self.assertEqual(len(swipes), 1)
            self.assertEqual(len(taps2), 1)

            # 4) max_runs reached sets state['done'] = True.
            rca._REGIONAL_STATE_BY_TASK.clear()
            rca._task_state(ctx, argv)["completed_runs"] = 3
            ctx_cap = SimpleNamespace(
                tasker=SimpleNamespace(stopping=False),
                get_node_data=lambda _n: {"attach": {"run_mode": "fixed_count", "run_count": 3}},
            )
            res_done = action.run(ctx_cap, argv)
            self.assertTrue(res_done.success)
            self.assertTrue(rca._task_state(ctx_cap, argv)["done"])

    def test_fewest_stages_first_initial_scan_preserves_default_city_and_prioritizes_short_stations(self) -> None:
        with _real_maa_modules() as Resource:
            if Resource is None:
                self.skipTest("maafw is not installed")
            import agent.regional_combat_action as rca

            rca._REGIONAL_STATE_BY_TASK.clear()
            img_top = self._make_frame_with_selected(295)     # 铁盟哨站 selected initially
            img_bottom_1 = self._make_frame_with_selected(535)
            img_bottom_2 = self._make_frame_with_selected(195)  # 云岫桥基地 selected after tap

            city_top = [
                {"text": "荒原站", "box": [45, 156, 64, 29]},
                {"text": "LV21~LV30", "box": [337, 92, 96, 15]},
                {"text": "作战进度100%", "box": [312, 162, 141, 28]},
                {"text": "铁盟哨站", "box": [44, 275, 84, 32]},
                {"text": "LV21~LV125", "box": [329, 207, 105, 23]},
                {"text": "作战进度9%", "box": [337, 280, 115, 31]},
            ]
            city_bottom = [
                {"text": "云岫桥基地", "box": [45, 183, 101, 31]},
                {"text": "LV41~LV50", "box": [333, 115, 103, 25]},
                {"text": "作战进度0%", "box": [338, 191, 112, 28]},
                {"text": "汇流塔", "box": [44, 426, 66, 29]},
                {"text": "LV51~LV70", "box": [334, 357, 102, 22]},
                {"text": "作战进度0%", "box": [338, 430, 112, 28]},
            ]

            ctx_fewest = SimpleNamespace(
                tasker=SimpleNamespace(stopping=False),
                get_node_data=lambda _n: {
                    "attach": {"scope": "all_cities", "city_order": "fewest_stages_first", "max_enemy_level": 0}
                },
            )
            ctx_list = SimpleNamespace(
                tasker=SimpleNamespace(stopping=False),
                get_node_data=lambda _n: {
                    "attach": {"scope": "all_cities", "city_order": "list_order", "max_enemy_level": 0}
                },
            )
            argv = SimpleNamespace(
                node_name="RegionalCombatNeedsAdvance",
                task_detail=SimpleNamespace(task_id=3003),
                custom_action_param={},
            )

            # list_order keeps fighting initial 铁盟哨站 immediately without triggering initial scan.
            reco = rca.RegionalCombatNeedsAdvanceRecognition()
            with patch.object(
                rca,
                "ocr_roi",
                side_effect=[
                    [{"text": "威胁等级", "box": [578, 176, 76, 23]}],
                    [{"text": "点击变更难度", "box": [1013, 448, 76, 15]}],
                    [{"text": "前往作战", "box": [1048, 575, 104, 33]}],
                    city_top,
                    [{"text": "首通", "box": [654, 562, 32, 20]}],
                ],
            ):
                list_miss = reco.analyze(ctx_list, SimpleNamespace(node_name="Check", image=img_top))
            self.assertIsNone(list_miss.box)

            # fewest_stages_first triggers initial scan even though 铁盟哨站 has '首通'.
            with patch.object(
                rca,
                "ocr_roi",
                side_effect=[
                    [{"text": "威胁等级", "box": [578, 176, 76, 23]}],
                    [{"text": "点击变更难度", "box": [1013, 448, 76, 15]}],
                    [{"text": "前往作战", "box": [1048, 575, 104, 33]}],
                ],
            ):
                init_hit = reco.analyze(ctx_fewest, SimpleNamespace(node_name="Check", image=img_top))
            self.assertIsNotNone(init_hit.box)
            self.assertEqual(init_hit.detail["reason"], "initial_city_selection")

            # Advance scans top & bottom, selects 云岫桥基地 (10 stages), and does NOT exclude 铁盟哨站!
            taps: list[tuple[int, int]] = []
            ocr_seq = [
                city_top,           # initial screen
                city_top,           # Up0 (same signature -> stops up sweep)
                city_bottom,        # Down0
                city_bottom,        # Down1 (same signature -> stops down sweep)
                city_bottom,        # _locate_and_select_city Cur_Cities (云岫桥基地 visible at bottom)
                [{"text": "首通"}],  # Eval_FC
                [{"text": "敌方等级：41"}],
                [{"text": "新关1"}],
            ]
            action = rca.RegionalCombatAdvanceAction()
            with (
                patch.object(
                    rca,
                    "safe_screencap",
                    side_effect=[img_top, img_top, img_bottom_1, img_bottom_1, img_bottom_2],
                ),
                patch.object(rca, "sleep_with_stop", return_value=True),
                patch.object(rca, "ocr_roi", side_effect=lambda *_a, **_kw: ocr_seq.pop(0)),
                patch.object(rca, "tap_point", side_effect=lambda _c, _n, pt: taps.append(pt) or True),
                patch.object(rca, "swipe_points", return_value=True),
            ):
                adv_res = action.run(ctx_fewest, argv)

            self.assertTrue(adv_res.success)
            self.assertEqual(ocr_seq, [])
            self.assertEqual(len(taps), 1)
            state = rca._task_state(ctx_fewest, argv)
            self.assertTrue(state["initial_city_selected"])
            self.assertEqual(state["active_target_city"], "云岫桥基地")
            self.assertNotIn("铁盟哨站", state["excluded_cities"])

            # Once 云岫桥基地 finishes (e.g. 100%, no 首通), next candidate picked is 汇流塔 (20) before 铁盟哨站 (105).
            img_bottom_cloud_done = self._make_frame_with_selected(195)
            img_bottom_hui_sel = self._make_frame_with_selected(440)
            taps_next: list[tuple[int, int]] = []
            ocr_seq_next = [
                city_bottom,                # Cur Cities (云岫桥基地 selected)
                [],                         # Cur FC (no 首通 -> tries retap)
                [],                         # Cur Lv
                [],                         # Cur Title
                [],                         # Retap FC (still no 首通 -> finishes 云岫桥基地)
                [],                         # Retap Lv
                [],                         # Retap Title
                city_bottom,                # _locate_and_select_city Cur_Cities (汇流塔 visible)
                [{"text": "首通"}],          # Eval_FC
                [],                         # Eval_Lv (汇流塔 stage 1 missing enemy level)
                [{"text": "入梦·上"}],       # Eval_Title
            ]
            with (
                patch.object(
                    rca,
                    "safe_screencap",
                    side_effect=[img_bottom_cloud_done, img_bottom_cloud_done, img_bottom_hui_sel],
                ),
                patch.object(rca, "sleep_with_stop", return_value=True),
                patch.object(rca, "ocr_roi", side_effect=lambda *_a, **_kw: ocr_seq_next.pop(0)),
                patch.object(rca, "tap_point", side_effect=lambda _c, _n, pt: taps_next.append(pt) or True),
                patch.object(rca, "swipe_points", return_value=True),
            ):
                adv_next = action.run(ctx_fewest, argv)

            self.assertTrue(adv_next.success)
            self.assertEqual(state["active_target_city"], "汇流塔")
            self.assertIn("云岫桥基地", state["excluded_cities"])
            self.assertNotIn("铁盟哨站", state["excluded_cities"])

    def test_low_clarity_activity_switch_and_network_restart_exit(self) -> None:
        with _real_maa_modules() as Resource:
            if Resource is None:
                self.skipTest("maafw is not installed")
            import agent.regional_combat_action as rca
            from agent.utils.network_guard import NetworkRestartedToLobbyError

            rca._REGIONAL_STATE_BY_TASK.clear()
            img = np.full((720, 1280, 3), 25, dtype=np.uint8)
            argv = SimpleNamespace(
                node_name="RegionalCombatLowClarityPrompt",
                task_detail=SimpleNamespace(task_id=2002),
                custom_action_param={},
            )

            # Low clarity with use_medicine=False clicks cancel and marks done=True.
            taps: list[tuple[int, int]] = []
            ctx_no_med = SimpleNamespace(
                tasker=SimpleNamespace(stopping=False),
                get_node_data=lambda _n: {"attach": {"use_medicine": False}},
            )
            with (
                patch.object(rca, "safe_screencap", return_value=img),
                patch.object(rca, "sleep_with_stop", return_value=True),
                patch.object(rca, "ocr_roi", return_value=[{"text": "取消", "box": [300, 480, 90, 45]}]),
                patch.object(rca, "tap_point", side_effect=lambda _c, _n, pt: taps.append(pt) or True),
            ):
                res_no_med = rca.RegionalCombatHandleLowClarityAction().run(ctx_no_med, argv)
            self.assertTrue(res_no_med.success)
            self.assertEqual(taps, [(345, 502)])
            self.assertTrue(rca._task_state(ctx_no_med, argv)["done"])

            # Low clarity with use_medicine=True clicks confirm and keeps done=False.
            rca._REGIONAL_STATE_BY_TASK.clear()
            taps_med: list[tuple[int, int]] = []
            ctx_med = SimpleNamespace(
                tasker=SimpleNamespace(stopping=False),
                get_node_data=lambda _n: {"attach": {"use_medicine": True}},
            )
            with (
                patch.object(rca, "safe_screencap", return_value=img),
                patch.object(rca, "sleep_with_stop", return_value=True),
                patch.object(rca, "ocr_roi", return_value=[]),
                patch.object(rca, "tap_point", side_effect=lambda _c, _n, pt: taps_med.append(pt) or True),
            ):
                res_med = rca.RegionalCombatHandleLowClarityAction().run(ctx_med, argv)
            self.assertTrue(res_med.success)
            self.assertEqual(taps_med, [REGIONAL_LOW_CLARITY_CONFIRM_POINT])
            self.assertFalse(rca._task_state(ctx_med, argv)["done"])

            # Activity Hub detection triggers only when on hub AND not already showing 区域作战中心.
            hub_reco = rca.RegionalCombatActivityHubNeedSwitchRecognition()
            hub_sidebar = [
                {"text": "限时活动", "box": [83, 141, 91, 28]},
                {"text": "常规活动", "box": [113, 136, 119, 28]},
            ]
            with patch.object(rca, "ocr_roi", side_effect=[hub_sidebar, [{"text": "虚演刻录"}]]):
                hit = hub_reco.analyze(ctx_med, SimpleNamespace(node_name="HubSwitch", image=img))
            self.assertIsNotNone(hit.box)

            with patch.object(
                rca,
                "ocr_roi",
                side_effect=[
                    hub_sidebar,
                    [
                        {"text": "铁安协同终端", "box": [726, 38, 158, 28]},
                        {"text": "区域作战中心", "box": [1000, 378, 180, 36]},
                        {"text": ">前往>>", "box": [961, 461, 260, 37]},
                    ],
                ],
            ):
                miss = hub_reco.analyze(ctx_med, SimpleNamespace(node_name="HubSwitch", image=img))
            self.assertIsNone(miss.box)

            # Network restart exception exits cleanly with success=True.
            with patch.object(rca, "select_activity_tab", side_effect=NetworkRestartedToLobbyError("restarted")):
                net_res = rca.RegionalCombatSwitchToTerminalAction().run(ctx_med, argv)
            self.assertTrue(net_res.success)


class RegionalCombatPipelineIntegrityTest(unittest.TestCase):
    def test_regional_combat_pipeline_task_and_preset_integrity(self) -> None:
        pipe_path = ROOT / "assets/resource/base/pipeline/combat/regional_combat.json"
        task_path = ROOT / "assets/resource/tasks/RegionalCombat.json"
        iface_path = ROOT / "assets/interface.json"
        common_guard_path = ROOT / "assets/resource/base/pipeline/common/network_guard.json"

        pipeline = json.loads(pipe_path.read_text(encoding="utf-8"))
        common_guard = json.loads(common_guard_path.read_text(encoding="utf-8"))
        known_nodes = set(pipeline) | set(common_guard)
        task_cfg = json.loads(task_path.read_text(encoding="utf-8"))
        iface_cfg = json.loads(iface_path.read_text(encoding="utf-8"))

        # All next / on_error references resolve cleanly.
        missing_refs: list[tuple[str, str]] = []
        for node_name, node_def in pipeline.items():
            for field in ("next", "on_error"):
                for ref in node_def.get(field) or []:
                    raw_name = ref["name"] if isinstance(ref, dict) else str(ref)
                    ref_name = re.sub(r"^(\[(?:JumpBack|Anchor)\])+", "", raw_name)
                    if ref_name not in known_nodes:
                        missing_refs.append((node_name, ref_name))
        self.assertEqual(missing_refs, [])

        # Zero raw Click / Swipe nodes.
        for node_name, node_def in pipeline.items():
            act = node_def.get("action")
            act_type = act.get("type") if isinstance(act, dict) else act
            self.assertNotIn(act_type, ("Click", "Swipe"), msg=f"{node_name} uses raw {act_type}")

        # Critical ordering inside RegionalCombatLoop.
        loop_next = pipeline["RegionalCombatLoop"]["next"]
        self.assertEqual(loop_next[0], "[JumpBack]CommonNetworkPoorGuard")
        expected_order = [
            "RegionalCombatIsDone",
            "RegionalCombatDifficultyWarnPrompt",
            "RegionalCombatDefeatStop",
            "RegionalCombatSettleNextTemplate",
            "RegionalCombatNeedsAdvance",
            "RegionalCombatEnterCombat",
            "RegionalCombatTerminalEnter",
            "RegionalCombatActivityHubSwitch",
            "RegionalCombatLobbyEnterTerminal",
        ]
        for a, b in zip(expected_order, expected_order[1:]):
            self.assertLess(loop_next.index(a), loop_next.index(b), msg=f"Expected {a} before {b}")

        # Safe normal completions use DoNothing so daily-all-in-one continues; defeat uses StopTask.
        self.assertEqual(pipeline["RegionalCombatComplete"]["action"], "DoNothing")
        self.assertEqual(pipeline["RegionalCombatAllCompleteFinish"]["action"], "DoNothing")
        self.assertEqual(pipeline["RegionalCombatDefeatStop"]["action"], "StopTask")
        self.assertGreaterEqual(pipeline["RegionalCombatEnterCombat"]["roi"][1], 555)
        self.assertGreaterEqual(pipeline["RegionalCombatDifficultyWarnConfirm"]["roi"][0], 600)

        # Task & interface presets check.
        task_entry = task_cfg["task"][0]
        self.assertEqual(task_entry["name"], "RegionalCombat")
        self.assertEqual(task_entry["group"], ["combat"])
        self.assertIn(task_entry["entry"], pipeline)
        self.assertIn("resource/tasks/RegionalCombat.json", iface_cfg["import"])
        preset_names = {p["name"] for p in iface_cfg["preset"]}
        self.assertIn("regional-combat", preset_names)

        # Validate option overrides & attach node consistency.
        for opt_name, opt_def in task_cfg["option"].items():
            for target_node in (opt_def.get("pipeline_override") or {}):
                self.assertIn(target_node, pipeline, msg=f"{opt_name} -> {target_node}")
            for case in opt_def.get("cases") or ():
                for target_node in (case.get("pipeline_override") or {}):
                    self.assertIn(target_node, pipeline, msg=f"{opt_name}.{case['name']} -> {target_node}")


if __name__ == "__main__":
    unittest.main()
