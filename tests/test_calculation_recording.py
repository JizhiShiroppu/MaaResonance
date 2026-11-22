from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess
import sys
import unittest

import numpy as np

from maa_resonance.logic.calculation_recording import (
    CALC_HUB_LEFT_ENTER_FALLBACK,
    CALC_LEFT_SLOT_CENTERS_Y,
    count_lit_phase_segments,
    did_stage_advance,
    find_calc_recording_hub_enter_point,
    find_selected_left_slot,
    find_start_button_box,
    is_boss_completed_100,
    is_calculation_recording_page,
    is_left_slot_unlocked,
    parse_boss_name,
    parse_boss_number,
    parse_enemy_level,
    parse_record_progress_done,
    parse_ticket_count,
    parse_total_progress,
    rank_unfinished_bosses,
    resolve_effective_max_enemy_level,
    resolve_effective_max_runs,
    should_skip_for_enemy_level,
)

ROOT = Path(__file__).resolve().parents[1]


def _make_calc_frame(
    *,
    width: int = 1280,
    height: int = 720,
    lit_segments: int = 1,
    selected_slot: int | None = None,
    unlocked_slots: tuple[int, ...] = (0, 1, 2, 3),
    more_record: bool = False,
    pct_span_wide: bool = False,
) -> np.ndarray:
    """Create a synthetic 720p-proportioned BGR frame matching calibrated pixel signatures."""
    img = np.full((height, width, 3), 240, dtype=np.uint8)
    sx = width / 1280.0
    sy = height / 720.0

    def _rect(x1: float, y1: float, x2: float, y2: float, bgr: tuple[int, int, int]) -> None:
        ix1, ix2 = max(0, int(round(x1 * sx))), min(width, int(round(x2 * sx)))
        iy1, iy2 = max(0, int(round(y1 * sy))), min(height, int(round(y2 * sy)))
        if ix2 > ix1 and iy2 > iy1:
            img[iy1:iy2, ix1:ix2] = bgr

    # Right panel dark background + 5 phase segments.
    _rect(640, 100, 1250, 660, (30, 32, 34))
    seg_w = (882.0 - 673.0) / 5.0
    for idx in range(5):
        x1 = 673.0 + idx * seg_w + 2.0
        x2 = 673.0 + (idx + 1) * seg_w - 2.0
        bgr = (210, 200, 60) if idx < lit_segments else (85, 85, 65)
        _rect(x1, 286, x2, 294, bgr)

    # Left list slots: cyan radar glow on unlocked slots, selection bracket on active slot.
    for slot_idx in unlocked_slots:
        cy = CALC_LEFT_SLOT_CENTERS_Y[slot_idx]
        _rect(90, cy - 30, 260, cy + 30, (180, 175, 45))
    if selected_slot is not None:
        cy = CALC_LEFT_SLOT_CENTERS_Y[selected_slot]
        _rect(8, cy - 8, 24, cy + 8, (10, 10, 10))
        _rect(600, cy - 8, 616, cy + 8, (10, 10, 10))

    # Right panel percentage white pixels: 100% spans >=70px vs 80%/20% ~63px.
    if pct_span_wide:
        _rect(1042, 202, 1114, 232, (235, 235, 235))
    else:
        _rect(1048, 202, 1111, 232, (235, 235, 235))

    # Bottom-left 更多记录 dark button (only present on 100% bosses).
    if more_record:
        _rect(358, 618, 462, 692, (25, 30, 35))

    return img


class CalculationRecordingLogicTest(unittest.TestCase):
    def test_hub_enter_picks_left_card_and_ignores_depth_and_inner_page(self) -> None:
        hub_entries = [
            {"text": "虚演刻录", "box": [28, 381, 63, 17]},
            {"text": "CALCULATION", "box": [320, 140, 153, 36]},
            {"text": "RECORDING", "box": [320, 178, 212, 50]},
            {"text": "虚演刻录", "box": [320, 228, 156, 52]},
            {"text": "虚演进度", "box": [322, 317, 90, 24]},
            {"text": "前往虚演空间", "box": [432, 427, 134, 28]},
            {"text": "DEPTH", "box": [744, 107, 78, 33]},
            {"text": "深度演算", "box": [746, 194, 154, 41]},
            {"text": "前往虚演空间", "box": [872, 330, 136, 27]},
            {"text": "兑换商店", "box": [530, 616, 94, 29]},
        ]
        self.assertEqual(find_calc_recording_hub_enter_point(hub_entries), (499, 441))

        # Fallback if OCR misses left button text while left card & hub context are visible.
        no_left_btn = [e for e in hub_entries if not (e["text"] == "前往虚演空间" and e["box"][0] < 700)]
        self.assertEqual(find_calc_recording_hub_enter_point(no_left_btn), CALC_HUB_LEFT_ENTER_FALLBACK)

        # Inner screen must never match hub enter recognition.
        self.assertIsNone(
            find_calc_recording_hub_enter_point(
                hub_entries + [{"text": "开始虚演刻录", "box": [820, 611, 174, 30]}]
            )
        )
        # Right card only must never match.
        right_only = [e for e in hub_entries if e["box"][0] > 700]
        self.assertIsNone(find_calc_recording_hub_enter_point(right_only))

    def test_page_detection_tickets_boss_info_and_param_resolution(self) -> None:
        self.assertTrue(
            is_calculation_recording_page(
                [{"text": "开始虚演刻录", "box": [820, 611, 174, 30]}],
                [{"text": "刻录进度", "box": [919, 135, 91, 24]}],
                [{"text": "21/185(11%)", "box": [620, 29, 107, 23]}],
            )
        )
        self.assertIsNone(find_start_button_box([{"text": "前往虚演空间", "box": [432, 427, 134, 28]}]))
        self.assertEqual(parse_total_progress([{"text": "21/185(11%)", "box": [620, 29, 107, 23]}]), (21, 185))
        self.assertEqual(
            parse_ticket_count([
                {"text": "1", "box": [1068, 39, 10, 5]},
                {"text": "125", "box": [1179, 25, 43, 26]},
            ]),
            125,
        )
        self.assertEqual(parse_ticket_count([{"text": "O", "box": [1180, 25, 20, 24]}]), 0)

        self.assertEqual(
            parse_boss_number([
                {"text": "VIRTUAL SIMULATION SEQUENCE", "box": [701, 270, 152, 13]},
                {"text": "08", "box": [693, 131, 160, 149]},
            ]),
            8,
        )
        self.assertIs(parse_record_progress_done([{"text": "0/1", "box": [1133, 134, 80, 45]}]), False)
        self.assertIs(parse_record_progress_done([{"text": "1/1", "box": [1134, 134, 80, 45]}]), True)
        self.assertEqual(
            parse_boss_name([
                {"text": "20%", "box": [1049, 201, 73, 37]},
                {"text": "金子小姐", "box": [1044, 238, 107, 31]},
                {"text": "敌人等级：42", "box": [1044, 292, 113, 20]},
            ]),
            "金子小姐",
        )
        self.assertEqual(parse_enemy_level([{"text": "敌人等级：37", "box": [1044, 292, 112, 20]}]), 37)
        self.assertEqual(parse_enemy_level([{"text": "敌方等级: S8"}]), 58)

        self.assertTrue(should_skip_for_enemy_level(65, 60))
        self.assertFalse(should_skip_for_enemy_level(37, 60))
        self.assertFalse(should_skip_for_enemy_level(None, 60))
        self.assertFalse(should_skip_for_enemy_level(99, 0))

        self.assertEqual(
            resolve_effective_max_enemy_level({"max_enemy_level": 50, "use_custom_max_enemy_level": False}),
            50,
        )
        self.assertEqual(
            resolve_effective_max_enemy_level(
                {"max_enemy_level": 50, "use_custom_max_enemy_level": True, "custom_max_enemy_level": "75"}
            ),
            75,
        )
        self.assertEqual(resolve_effective_max_runs({"run_mode": "unlimited", "run_count": 5}), 0)
        self.assertEqual(resolve_effective_max_runs({"run_mode": "fixed_count", "run_count": "4"}), 4)

    def test_phase_segments_and_100_vs_80_percent_and_slot_pixels(self) -> None:
        frame_80 = _make_calc_frame(
            lit_segments=5,
            selected_slot=1,
            unlocked_slots=(0, 1, 2),
            more_record=False,
            pct_span_wide=False,
        )
        self.assertEqual(count_lit_phase_segments(frame_80), 5)
        self.assertFalse(is_boss_completed_100(frame_80, [{"text": "80%"}]))
        self.assertFalse(is_boss_completed_100(frame_80, [{"text": "8%"}]))  # Common live OCR miss on Boss 02

        frame_100 = _make_calc_frame(
            width=1920,
            height=1080,
            lit_segments=5,
            selected_slot=0,
            unlocked_slots=(0, 1, 2),
            more_record=True,
            pct_span_wide=True,
        )
        self.assertEqual(count_lit_phase_segments(frame_100), 5)
        self.assertTrue(is_boss_completed_100(frame_100, [{"text": "100%"}]))
        # Even if OCR fails '100%', 更多记录 + wide % pixel span confirms 100%.
        self.assertTrue(is_boss_completed_100(frame_100, [{"text": ""}]))

        # Unlocked slots vs locked slot 3 + OCR lock label guard.
        self.assertTrue(is_left_slot_unlocked(frame_80, CALC_LEFT_SLOT_CENTERS_Y[0]))
        self.assertTrue(is_left_slot_unlocked(frame_80, CALC_LEFT_SLOT_CENTERS_Y[2]))
        self.assertFalse(is_left_slot_unlocked(frame_80, CALC_LEFT_SLOT_CENTERS_Y[3]))
        self.assertFalse(
            is_left_slot_unlocked(
                frame_80,
                CALC_LEFT_SLOT_CENTERS_Y[2],
                [{"text": "前置关卡未完成", "box": [245, CALC_LEFT_SLOT_CENTERS_Y[2] + 10, 123, 20]}],
            )
        )
        self.assertEqual(find_selected_left_slot(frame_80), 1)
        self.assertEqual(find_selected_left_slot(frame_100), 0)

    def test_stage_advance_and_boss_ranking(self) -> None:
        base = {
            "boss_no": 8,
            "lit_segments": 1,
            "record_done": False,
            "is_100": False,
            "enemy_level": 37,
            "total_cleared": 20,
        }
        # Same state after battle => non-S clear => False.
        self.assertFalse(did_stage_advance(base, dict(base)))
        # Any S-clear signal => True.
        self.assertTrue(did_stage_advance(base, {**base, "total_cleared": 21}))
        self.assertTrue(did_stage_advance(base, {**base, "lit_segments": 2}))
        self.assertTrue(did_stage_advance(base, {**base, "record_done": True}))
        self.assertTrue(did_stage_advance(base, {**base, "enemy_level": 42}))
        self.assertTrue(did_stage_advance({**base, "lit_segments": 5}, {**base, "lit_segments": 5, "is_100": True}))

        catalog = [
            {"boss_no": 1, "boss_name": "鼷鼠重机", "enemy_level": 65, "is_100": True},
            {"boss_no": 2, "boss_name": "穿击动力甲", "enemy_level": 66, "is_100": False},
            {"boss_no": 5, "boss_name": "Boss05", "enemy_level": 39, "is_100": False},
            {"boss_no": 7, "boss_name": "尘鸣游鳞", "enemy_level": 41, "is_100": False},
            {"boss_no": 8, "boss_name": "金子小姐", "enemy_level": 42, "is_100": False},
            {"boss_no": 9, "boss_name": "蝎型机械体", "enemy_level": 38, "is_100": False},
        ]
        ranked_lowest = rank_unfinished_bosses(
            catalog,
            excluded_bosses={5},
            max_enemy_level=60,
            boss_order="lowest_level_first",
        )
        self.assertEqual([b["boss_no"] for b in ranked_lowest], [9, 7, 8])

        ranked_list = rank_unfinished_bosses(catalog, excluded_bosses=set(), max_enemy_level=0, boss_order="list_order")
        self.assertEqual([b["boss_no"] for b in ranked_list], [2, 5, 7, 8, 9])


class CalculationRecordingActionFlowTest(unittest.TestCase):
    def test_action_flow_catalog_probe_non_s_skip_and_settlement_in_isolated_subprocess(self) -> None:
        # Execute AgentServer action/recognition tests in an isolated subprocess so importing
        # maa.agent.agent_server never alters Library._is_agent_server in the main test runner.
        script = f"""
import sys
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, {str(ROOT)!r})
sys.path.insert(0, {str(ROOT / 'agent')!r})

import numpy as np
import agent.calculation_recording_action as cra
from maa_resonance.logic.calculation_recording import CALC_RECORD_MODAL_DISMISS_POINT

try:
    from agent.utils.network_guard import NetworkRestartedToLobbyError
except ImportError:
    NetworkRestartedToLobbyError = Exception

def make_frame(lit=1, selected=0, unlocked=(0, 1, 2, 3), is_100=False):
    img = np.full((720, 1280, 3), 240, dtype=np.uint8)
    img[100:660, 640:1250] = (30, 32, 34)
    seg_w = (882.0 - 673.0) / 5.0
    for i in range(5):
        x1 = int(round(673.0 + i * seg_w + 2))
        x2 = int(round(673.0 + (i + 1) * seg_w - 2))
        img[286:294, x1:x2] = (210, 200, 60) if i < lit else (85, 85, 65)
    for slot in unlocked:
        cy = (162, 287, 412, 537)[slot]
        img[cy-30:cy+30, 90:260] = (180, 175, 45)
    if selected is not None:
        cy = (162, 287, 412, 537)[selected]
        img[cy-8:cy+8, 8:24] = (10, 10, 10)
        img[cy-8:cy+8, 600:616] = (10, 10, 10)
    if is_100:
        img[202:232, 1042:1114] = (235, 235, 235)
        img[618:692, 358:462] = (25, 30, 35)
    else:
        img[202:232, 1048:1111] = (235, 235, 235)
    return img

def snap_ocr(no, rec, pct, name, lv, total, more=False):
    seq = [
        [{{"text": f"{{no:02d}}", "box": [693, 131, 160, 149]}}],
        [{{"text": rec}}],
        [{{"text": pct}}],
    ]
    img_lit5 = False
    if pct == "100%" or pct == "80%":
        seq.append([{{"text": "更多记录"}}] if more else [])
    seq.extend([
        [{{"text": name}}],
        [{{"text": f"敌人等级：{{lv}}"}}],
        [{{"text": f"{{total}}/185(11%)"}}],
    ])
    return seq

cra._CALC_STATE_BY_TASK.clear()
node_cfg = {{
    "CalculationRecordingOptScope": {{"attach": {{"scope": "all_bosses"}}}},
    "CalculationRecordingOptBossOrder": {{"attach": {{"boss_order": "lowest_level_first"}}}},
    "CalculationRecordingOptMaxEnemyLevel": {{"attach": {{"max_enemy_level": 60, "use_custom_max_enemy_level": False}}}},
    "CalculationRecordingOptRunMode": {{"attach": {{"run_mode": "unlimited"}}}},
}}
ctx = SimpleNamespace(
    tasker=SimpleNamespace(stopping=False),
    get_node_data=lambda n: node_cfg.get(n),
)
argv = SimpleNamespace(
    node_name="CalculationRecordingNeedsAdvance",
    task_detail=SimpleNamespace(task_id=3001),
    custom_action_param={{}},
    custom_recognition_param={{}},
)

# 1. NeedsAdvance triggers initial_boss_selection on Boss 08.
reco = cra.CalculationRecordingNeedsAdvanceRecognition()
f_08 = make_frame(lit=1, selected=2, unlocked=(0, 1, 2))
with patch.object(
    cra,
    "ocr_roi",
    side_effect=[
        [{{"text": "开始虚演刻录", "box": [820, 611, 174, 30]}}],
        [{{"text": "刻录进度"}}],
        [{{"text": "20/185(11%)"}}],
        [{{"text": "126", "box": [1178, 23, 46, 28]}}],
    ],
):
    hit = reco.analyze(ctx, SimpleNamespace(node_name="Check", task_detail=argv.task_detail, image=f_08, custom_recognition_param={{}}))
assert hit.box is not None and hit.detail["reason"] == "initial_boss_selection"

# 2. AdvanceAction scans top (01=100%/Lv65, 03=Lv57, 05=Lv39, 07=Lv41; then Page1: 07, 08=0%/Lv37) and picks Boss 08 (lowest Lv37).
f_top_s0 = make_frame(lit=5, selected=0, unlocked=(0, 1, 2, 3), is_100=True)
f_top_s1 = make_frame(lit=4, selected=1, unlocked=(0, 1, 2, 3))
f_top_s2 = make_frame(lit=3, selected=2, unlocked=(0, 1, 2, 3))
f_top_s3 = make_frame(lit=2, selected=3, unlocked=(0, 1, 2, 3))
# Page 1 overlaps 07(slot0), 08(slot1) and slot2 locked.
f_p1_s0 = make_frame(lit=2, selected=0, unlocked=(0, 1))
f_p1_s1 = make_frame(lit=1, selected=1, unlocked=(0, 1))

ocr_seq = []
ocr_seq.append([{{"text": "126", "box": [1178, 23, 46, 28]}}])              # Ticket
ocr_seq.extend(snap_ocr(8, "0/1", "0%", "金子小姐", 37, 20))               # Cur
ocr_seq.extend(snap_ocr(8, "0/1", "0%", "金子小姐", 37, 20))               # TopCheck (not at top)
ocr_seq.extend(snap_ocr(1, "1/1", "100%", "鼷鼠重机", 65, 20, more=True))  # TopRead0 -> boss_no=1!
ocr_seq.append([])                                                          # LeftP0
ocr_seq.extend(snap_ocr(3, "1/1", "60%", "鸣爆虫母", 57, 20))              # P0S1
ocr_seq.extend(snap_ocr(5, "1/1", "40%", "Boss05", 39, 20))                # P0S2
ocr_seq.extend(snap_ocr(7, "1/1", "20%", "尘鸣游鳞", 41, 20))              # P0S3
ocr_seq.append([])                                                          # LeftP1
ocr_seq.extend(snap_ocr(7, "1/1", "20%", "尘鸣游鳞", 41, 20))              # P1S0 (overlaps P0S3)
ocr_seq.extend(snap_ocr(8, "0/1", "0%", "金子小姐", 37, 20))               # P1S1 (slot 2 locked -> stop scan)
ocr_seq.extend(snap_ocr(8, "0/1", "0%", "金子小姐", 37, 20))               # _locate Init (already on Boss 08)

adv = cra.CalculationRecordingAdvanceAction()
with (
    patch.object(
        cra,
        "safe_screencap",
        side_effect=[
            f_08, f_top_s0, f_top_s0, f_top_s1, f_top_s2, f_top_s3,
            f_p1_s0, f_p1_s0, f_p1_s1,
        ],
    ),
    patch.object(cra, "sleep_with_stop", return_value=True),
    patch.object(cra, "ocr_roi", side_effect=lambda *_a, **_kw: ocr_seq.pop(0)),
    patch.object(cra, "tap_point", return_value=True),
    patch.object(cra, "swipe_points", return_value=True),
):
    res1 = adv.run(ctx, argv)

assert res1.success and ocr_seq == [], f"leftover={{ocr_seq}}"
state = cra._task_state(ctx, argv)
assert state["initial_boss_selected"] is True
assert state["active_target_boss"] == 8
assert state["boss_catalog"][1]["is_100"] is True  # 100% Boss 01 filtered out from ranking

# 3. Enter battle snapshots Boss 08 (battle_settled=False). If swallowed click, NeedsAdvance returns None (no false skip).
enter_act = cra.CalculationRecordingEnterBattleAction()
enter_ocr = [
    [{{"text": "126", "box": [1178, 23, 46, 28]}}],
    *snap_ocr(8, "0/1", "0%", "金子小姐", 37, 20),
    [{{"text": "开始虚演刻录", "box": [820, 611, 174, 30]}}],
]
with (
    patch.object(cra, "safe_screencap", return_value=f_p1_s1),
    patch.object(cra, "ocr_roi", side_effect=lambda *_a, **_kw: enter_ocr.pop(0)),
    patch.object(cra, "run_guarded_click", return_value=True),
):
    enter_res = enter_act.run(ctx, argv)
assert enter_res.success and state["battle_settled"] is False

# Swallowed click check: NeedsAdvance still sees ready_to_fight (None box).
with patch.object(
    cra,
    "ocr_roi",
    side_effect=[
        [{{"text": "开始虚演刻录", "box": [820, 611, 174, 30]}}],
        [{{"text": "刻录进度"}}],
        [{{"text": "20/185(11%)"}}],
        [{{"text": "126", "box": [1178, 23, 46, 28]}}],
        [{{"text": "08", "box": [693, 131, 160, 149]}}],
        [{{"text": "0%"}}],
        [{{"text": "敌人等级：37"}}],
    ],
):
    no_skip = reco.analyze(ctx, SimpleNamespace(node_name="Check", task_detail=argv.task_detail, image=f_p1_s1, custom_recognition_param={{}}))
assert no_skip.box is None

# 4. Dismiss 通关记录 modal + SettleNext marks battle_settled=True and increments completed_runs.
taps_modal = []
with patch.object(cra, "run_guarded_click", side_effect=lambda _c, _n, x, y: taps_modal.append((x, y)) or True):
    cra.CalculationRecordingDismissRecordAction().run(ctx, argv)
assert taps_modal == [CALC_RECORD_MODAL_DISMISS_POINT]
assert state["battle_settled"] is True

taps_next = []
next_argv = SimpleNamespace(
    node_name="SettleNext",
    task_detail=argv.task_detail,
    box=[1180, 655, 24, 17],
    custom_action_param={{}},
)
with patch.object(cra, "run_guarded_click", side_effect=lambda _c, _n, x, y: taps_next.append((x, y)) or True):
    cra.CalculationRecordingSettleNextAction().run(ctx, next_argv)
assert taps_next == [(1176, 610)]  # Adjusted into the circular > button instead of low text label
assert state["completed_runs"] == 1

# 5. Post-battle S-clear (08 becomes 1/1, Lv42, total 21) -> probes unlocked 09 (Lv38) -> selects 09!
f_08_after = make_frame(lit=2, selected=1, unlocked=(0, 1, 2))
f_09 = make_frame(lit=1, selected=2, unlocked=(0, 1, 2))
ocr_post_s = [
    [{{"text": "125", "box": [1178, 23, 46, 28]}}],          # Ticket
    *snap_ocr(8, "1/1", "20%", "金子小姐", 42, 21),           # Post (0/1 -> 1/1!)
    *snap_ocr(8, "1/1", "20%", "金子小姐", 42, 21),           # ProbeNew Init (sel=1 -> 1-click slot 2 = 09)
    *snap_ocr(9, "0/1", "0%", "蝎型机械体", 38, 21),          # ProbeNew DirectRead (09!)
    *snap_ocr(9, "0/1", "0%", "蝎型机械体", 38, 21),          # Cur (already on 09)
    *snap_ocr(9, "0/1", "0%", "蝎型机械体", 38, 21),          # _locate Init (already on 09!)
]
with (
    patch.object(cra, "safe_screencap", side_effect=[f_08_after, f_09]),
    patch.object(cra, "sleep_with_stop", return_value=True),
    patch.object(cra, "ocr_roi", side_effect=lambda *_a, **_kw: ocr_post_s.pop(0)),
    patch.object(cra, "tap_point", return_value=True),
):
    res2 = adv.run(ctx, argv)
assert res2.success and ocr_post_s == [], f"leftover={{ocr_post_s}}"
assert state["active_target_boss"] == 9
assert 9 not in state["excluded_bosses"]

# 6. Simulate non-S clear on Boss 09 (progress unchanged after battle_settled=True) -> excludes 09 and switches to 05 (Lv39)!
state["pending_battle"] = {{
    "boss_no": 9, "boss_name": "蝎型机械体", "enemy_level": 38,
    "lit_segments": 1, "record_done": False, "is_100": False, "total_cleared": 21,
}}
state["battle_settled"] = True
ocr_non_s = [
    [{{"text": "124", "box": [1178, 23, 46, 28]}}],          # Ticket
    *snap_ocr(9, "0/1", "0%", "蝎型机械体", 38, 21),          # Post (no progress -> excludes 09!)
    *snap_ocr(9, "0/1", "0%", "蝎型机械体", 38, 21),          # Cur
    *snap_ocr(9, "0/1", "0%", "蝎型机械体", 38, 21),          # _locate Init (target=05 < 09 -> swipes up)
    *snap_ocr(5, "1/1", "40%", "Boss05", 39, 21),             # _locate ProbeRead -> lands on 05!
]
with (
    patch.object(cra, "safe_screencap", side_effect=[f_09, f_top_s1, f_top_s1]),
    patch.object(cra, "sleep_with_stop", return_value=True),
    patch.object(cra, "ocr_roi", side_effect=lambda *_a, **_kw: ocr_non_s.pop(0)),
    patch.object(cra, "tap_point", return_value=True),
    patch.object(cra, "swipe_points", return_value=True),
):
    res3 = adv.run(ctx, argv)
assert res3.success and ocr_non_s == [], f"leftover={{ocr_non_s}}"
assert 9 in state["excluded_bosses"]
assert state["active_target_boss"] == 5

# 7. Tickets == 0 marks done=True cleanly.
with (
    patch.object(cra, "safe_screencap", return_value=f_top_s1),
    patch.object(cra, "ocr_roi", return_value=[{{"text": "0", "box": [1185, 25, 20, 24]}}]),
):
    res4 = adv.run(ctx, argv)
assert res4.success and state["done"] is True
print("SUBPROCESS_OK")
"""
        proc = subprocess.run(
            [sys.executable, "-c", script],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, msg=proc.stderr or proc.stdout)
        self.assertIn("SUBPROCESS_OK", proc.stdout)


class CalculationRecordingPipelineIntegrityTest(unittest.TestCase):
    def test_calculation_recording_pipeline_task_and_preset_integrity(self) -> None:
        pipe_path = ROOT / "assets/resource/base/pipeline/combat/calculation_recording.json"
        task_path = ROOT / "assets/resource/tasks/CalculationRecording.json"
        iface_path = ROOT / "assets/interface.json"
        common_guard_path = ROOT / "assets/resource/base/pipeline/common/network_guard.json"

        pipeline = json.loads(pipe_path.read_text(encoding="utf-8"))
        common_guard = json.loads(common_guard_path.read_text(encoding="utf-8"))
        known_nodes = set(pipeline) | set(common_guard)
        task_cfg = json.loads(task_path.read_text(encoding="utf-8"))
        iface_cfg = json.loads(iface_path.read_text(encoding="utf-8"))

        missing_refs: list[tuple[str, str]] = []
        for node_name, node_def in pipeline.items():
            for field in ("next", "on_error"):
                for ref in node_def.get(field) or []:
                    raw_name = ref["name"] if isinstance(ref, dict) else str(ref)
                    ref_name = re.sub(r"^(\[(?:JumpBack|Anchor)\])+", "", raw_name)
                    if ref_name not in known_nodes:
                        missing_refs.append((node_name, ref_name))
        self.assertEqual(missing_refs, [])

        for node_name, node_def in pipeline.items():
            act = node_def.get("action")
            act_type = act.get("type") if isinstance(act, dict) else act
            self.assertNotIn(act_type, ("Click", "Swipe"), msg=f"{node_name} uses raw {act_type}")

        loop_next = pipeline["CalculationRecordingLoop"]["next"]
        self.assertEqual(loop_next[0], "[JumpBack]CommonNetworkPoorGuard")
        expected_order = [
            "CalculationRecordingIsDone",
            "CalculationRecordingBattleAuto",
            "CalculationRecordingDefeatStop",
            "CalculationRecordingSettleRecordModal",
            "CalculationRecordingSettleNextTemplate",
            "CalculationRecordingSettleNextOcr",
            "CalculationRecordingSettleRewardPopup",
            "CalculationRecordingSettleVictoryTap",
            "CalculationRecordingTicketShortagePrompt",
            "CalculationRecordingDifficultyWarnPrompt",
            "CalculationRecordingNeedsAdvance",
            "CalculationRecordingEnterBattle",
            "CalculationRecordingHubEnter",
            "CalculationRecordingActivityHubSwitch",
            "CalculationRecordingLobbyEnterActivity",
        ]
        for a, b in zip(expected_order, expected_order[1:]):
            self.assertLess(loop_next.index(a), loop_next.index(b), msg=f"Expected {a} before {b}")

        # Normal completions use DoNothing so daily-all-in-one continues; defeat uses StopTask.
        self.assertEqual(pipeline["CalculationRecordingComplete"]["action"], "DoNothing")
        self.assertEqual(pipeline["CalculationRecordingAllCompleteFinish"]["action"], "DoNothing")
        self.assertEqual(pipeline["CalculationRecordingDefeatStop"]["action"], "StopTask")
        self.assertNotIn("通关记录", pipeline["CalculationRecordingSettleRewardPopup"]["expected"])
        self.assertEqual(pipeline["CalculationRecordingSettleRewardPopup"]["custom_action_param"]["target"], [120, 360])

        task_entry = task_cfg["task"][0]
        self.assertEqual(task_entry["name"], "CalculationRecording")
        self.assertEqual(task_entry["group"], ["combat"])
        self.assertIn(task_entry["entry"], pipeline)
        self.assertIn("resource/tasks/CalculationRecording.json", iface_cfg["import"])
        preset_names = {p["name"] for p in iface_cfg["preset"]}
        self.assertIn("calculation-recording", preset_names)

        for opt_name, opt_def in task_cfg["option"].items():
            for target_node in (opt_def.get("pipeline_override") or {}):
                self.assertIn(target_node, pipeline, msg=f"{opt_name} -> {target_node}")
            for case in opt_def.get("cases") or ():
                for target_node in (case.get("pipeline_override") or {}):
                    self.assertIn(target_node, pipeline, msg=f"{opt_name}.{case['name']} -> {target_node}")


if __name__ == "__main__":
    unittest.main()
