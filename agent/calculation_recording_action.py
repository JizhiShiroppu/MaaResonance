"""Custom MaaFramework recognitions and actions for Calculation Recording (虚演刻录)."""
from __future__ import annotations

from typing import Any

from maa.agent.agent_server import AgentServer
from maa.context import Context
from maa.custom_action import CustomAction
from maa.custom_recognition import CustomRecognition

from agent.utils.action_helpers import ocr_roi, parse_action_param, swipe_points, tap_point
from agent.utils.activity_hub_nav import open_activity_hub, select_activity_tab
from agent.utils.input_guard import run_guarded_click, safe_screencap, sleep_with_stop
from agent.utils.lobby_nav import is_stopping
from agent.utils.network_guard import exit_on_network_restart
from maa_resonance.logic.activity_hub import ACTIVITY_HUB_SIDEBAR_ROI, is_activity_hub_entries
from maa_resonance.logic.calculation_recording import (
    CALC_BOSS_NAME_ROI,
    CALC_BOSS_NO_ROI,
    CALC_ENEMY_LEVEL_ROI,
    CALC_LEFT_LIST_ROI,
    CALC_LEFT_SLOT_CENTERS_Y,
    CALC_LEFT_SLOT_TAP_X,
    CALC_LIST_NUDGE_UP,
    CALC_LIST_SWIPE_DOWN,
    CALC_LIST_SWIPE_UP,
    CALC_MORE_RECORD_ROI,
    CALC_RECORD_MODAL_DISMISS_POINT,
    CALC_RECORD_PROGRESS_ROI,
    CALC_RIGHT_PCT_ROI,
    CALC_SETTLE_NEXT_POINT,
    CALC_SHORTAGE_BTN_ROI,
    CALC_START_BTN_FALLBACK,
    CALC_START_BTN_ROI,
    CALC_TICKET_ROI,
    CALC_TOP_PROGRESS_ROI,
    count_lit_phase_segments,
    did_stage_advance,
    find_calc_recording_hub_enter_point,
    find_popup_cancel_or_confirm_point,
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

CALC_RECORDING_ATTACH_NODES: tuple[str, ...] = (
    "CalculationRecordingOptScope",
    "CalculationRecordingOptBossOrder",
    "CalculationRecordingOptMaxEnemyLevel",
    "CalculationRecordingOptCustomMaxEnemyLevel",
    "CalculationRecordingOptRunMode",
    "CalculationRecordingOptRunCount",
)

_CALC_STATE_BY_TASK: dict[int, dict[str, Any]] = {}


def _task_state(context: Context, argv: Any) -> dict[str, Any]:
    task_detail = getattr(argv, "task_detail", None)
    task_id = getattr(task_detail, "task_id", None)
    key = int(task_id) if task_id is not None else id(getattr(context, "tasker", context))
    if len(_CALC_STATE_BY_TASK) > 32:
        _CALC_STATE_BY_TASK.clear()
    return _CALC_STATE_BY_TASK.setdefault(
        key,
        {
            "excluded_bosses": set(),
            "completed_runs": 0,
            "done": False,
            "boss_catalog": {},
            "catalog_scanned": False,
            "initial_boss_selected": False,
            "active_target_boss": None,
            "pending_battle": None,
            "battle_settled": False,
        },
    )


def _resolve_params(context: Context, argv: Any, param_attr: str = "custom_action_param") -> dict[str, Any]:
    merged = dict(parse_action_param(getattr(argv, param_attr, None)))
    get_node_data = getattr(context, "get_node_data", None)
    if callable(get_node_data):
        for node_name in CALC_RECORDING_ATTACH_NODES:
            try:
                node_data = get_node_data(node_name)
            except Exception:
                node_data = None
            if isinstance(node_data, dict) and isinstance(node_data.get("attach"), dict):
                merged.update(node_data["attach"])
    return merged


def _box_center(box: Any, fallback: tuple[int, int]) -> tuple[int, int]:
    if isinstance(box, (list, tuple)) and len(box) >= 4:
        x, y, w, h = int(box[0]), int(box[1]), int(box[2]), int(box[3])
        if w > 0 and h > 0:
            return int(round(x + w / 2.0)), int(round(y + h / 2.0))
    elif box is not None and all(hasattr(box, attr) for attr in ("x", "y", "w", "h")):
        w, h = int(box.w), int(box.h)
        if w > 0 and h > 0:
            return int(round(int(box.x) + w / 2.0)), int(round(int(box.y) + h / 2.0))
    return fallback


def _read_current_boss_snapshot(context: Context, image: Any, prefix: str) -> dict[str, Any]:
    boss_no = parse_boss_number(ocr_roi(context, image, f"{prefix}BossNo", CALC_BOSS_NO_ROI))
    rec_done = parse_record_progress_done(ocr_roi(context, image, f"{prefix}Rec", CALC_RECORD_PROGRESS_ROI))
    pct_entries = ocr_roi(context, image, f"{prefix}Pct", CALC_RIGHT_PCT_ROI)
    lit_segments = count_lit_phase_segments(image)
    more_entries = ocr_roi(context, image, f"{prefix}More", CALC_MORE_RECORD_ROI) if lit_segments >= 5 or image is None else []
    is_100 = is_boss_completed_100(image, pct_entries, more_entries)
    boss_name = parse_boss_name(ocr_roi(context, image, f"{prefix}Name", CALC_BOSS_NAME_ROI))
    enemy_lv = parse_enemy_level(ocr_roi(context, image, f"{prefix}Lv", CALC_ENEMY_LEVEL_ROI))
    total_pair = parse_total_progress(ocr_roi(context, image, f"{prefix}Total", CALC_TOP_PROGRESS_ROI))
    total_cleared = total_pair[0] if total_pair is not None else None
    return {
        "boss_no": boss_no,
        "boss_name": boss_name,
        "enemy_level": enemy_lv,
        "lit_segments": lit_segments,
        "record_done": rec_done,
        "is_100": is_100,
        "total_cleared": total_cleared,
    }


def _update_catalog(catalog: dict[int, dict[str, Any]], snapshot: dict[str, Any]) -> None:
    boss_no = snapshot.get("boss_no")
    if boss_no is None:
        return
    catalog[int(boss_no)] = dict(snapshot)


@AgentServer.custom_recognition("calculation_recording_is_done")
class CalculationRecordingIsDoneRecognition(CustomRecognition):
    """Trigger clean exit when the current Calculation Recording run has finished."""

    def analyze(
        self,
        context: Context,
        argv: CustomRecognition.AnalyzeArg,
    ) -> CustomRecognition.AnalyzeResult:
        if _task_state(context, argv).get("done"):
            return CustomRecognition.AnalyzeResult(box=(0, 0, 10, 10), detail={"ok": True, "done": True})
        return CustomRecognition.AnalyzeResult(box=None, detail={"ok": False, "done": False})


@AgentServer.custom_recognition("calculation_recording_hub_enter")
class CalculationRecordingHubEnterRecognition(CustomRecognition):
    """Detect the left '前往虚演空间' button on Activity Hub -> 常规活动 -> 虚演刻录."""

    def analyze(
        self,
        context: Context,
        argv: CustomRecognition.AnalyzeArg,
    ) -> CustomRecognition.AnalyzeResult:
        image = getattr(argv, "image", None)
        if image is None:
            return CustomRecognition.AnalyzeResult(box=None, detail={"ok": False})

        entries = ocr_roi(context, image, f"{argv.node_name}Scan", (0, 0, 1280, 720))
        point = find_calc_recording_hub_enter_point(entries)
        if point is None:
            return CustomRecognition.AnalyzeResult(box=None, detail={"ok": False})

        px, py = point
        return CustomRecognition.AnalyzeResult(
            box=(max(0, px - 55), max(0, py - 18), 110, 36),
            detail={"ok": True, "tap_point": [px, py]},
        )


@AgentServer.custom_recognition("calculation_recording_activity_hub_need_switch")
class CalculationRecordingActivityHubNeedSwitchRecognition(CustomRecognition):
    """Detect when Activity Hub is open on a tab other than 虚演刻录."""

    def analyze(
        self,
        context: Context,
        argv: CustomRecognition.AnalyzeArg,
    ) -> CustomRecognition.AnalyzeResult:
        image = getattr(argv, "image", None)
        if image is None:
            return CustomRecognition.AnalyzeResult(box=None, detail={"ok": False})

        sidebar_entries = ocr_roi(context, image, f"{argv.node_name}Sidebar", ACTIVITY_HUB_SIDEBAR_ROI)
        if not is_activity_hub_entries(sidebar_entries):
            return CustomRecognition.AnalyzeResult(box=None, detail={"ok": False, "reason": "not_activity_hub"})

        full_entries = ocr_roi(context, image, f"{argv.node_name}Full", (0, 0, 1280, 720))
        if find_calc_recording_hub_enter_point(full_entries) is not None:
            return CustomRecognition.AnalyzeResult(box=None, detail={"ok": False, "reason": "already_on_calc_tab"})

        return CustomRecognition.AnalyzeResult(
            box=(20, 130, 180, 40),
            detail={"ok": True},
        )


@AgentServer.custom_recognition("calculation_recording_needs_advance")
class CalculationRecordingNeedsAdvanceRecognition(CustomRecognition):
    """Trigger catalog scan, boss switch, post-battle S-rank check, or exit on the 虚演刻录 screen."""

    def analyze(
        self,
        context: Context,
        argv: CustomRecognition.AnalyzeArg,
    ) -> CustomRecognition.AnalyzeResult:
        image = getattr(argv, "image", None)
        if image is None:
            return CustomRecognition.AnalyzeResult(box=None, detail={"ok": False})

        start_entries = ocr_roi(context, image, f"{argv.node_name}Start", CALC_START_BTN_ROI)
        rec_entries = ocr_roi(context, image, f"{argv.node_name}Rec", CALC_RECORD_PROGRESS_ROI)
        top_entries = ocr_roi(context, image, f"{argv.node_name}Top", CALC_TOP_PROGRESS_ROI)
        if not is_calculation_recording_page(start_entries, rec_entries, top_entries):
            return CustomRecognition.AnalyzeResult(box=None, detail={"ok": False, "reason": "not_calc_page"})

        state = _task_state(context, argv)
        params = _resolve_params(context, argv, "custom_recognition_param")
        scope = str(params.get("scope") or "all_bosses")
        boss_order = str(params.get("boss_order") or "lowest_level_first")

        max_runs = resolve_effective_max_runs(params)
        if max_runs > 0 and int(state.get("completed_runs", 0)) >= max_runs:
            return CustomRecognition.AnalyzeResult(
                box=(780, 595, 220, 50),
                detail={"ok": True, "reason": "max_runs_reached"},
            )

        tickets = parse_ticket_count(ocr_roi(context, image, f"{argv.node_name}Ticket", CALC_TICKET_ROI))
        if tickets is not None and tickets == 0:
            return CustomRecognition.AnalyzeResult(
                box=(1100, 15, 130, 40),
                detail={"ok": True, "reason": "tickets_exhausted"},
            )

        if state.get("pending_battle") is not None and state.get("battle_settled"):
            return CustomRecognition.AnalyzeResult(
                box=(780, 595, 220, 50),
                detail={"ok": True, "reason": "post_battle_check"},
            )

        if scope == "all_bosses" and boss_order == "lowest_level_first" and not state.get("initial_boss_selected"):
            return CustomRecognition.AnalyzeResult(
                box=(780, 595, 220, 50),
                detail={"ok": True, "reason": "initial_boss_selection"},
            )

        boss_no = parse_boss_number(ocr_roi(context, image, f"{argv.node_name}BossNo", CALC_BOSS_NO_ROI))
        excluded_bosses: set[int] = state["excluded_bosses"]
        if boss_no is not None and int(boss_no) in excluded_bosses:
            return CustomRecognition.AnalyzeResult(
                box=(780, 595, 220, 50),
                detail={"ok": True, "reason": "boss_excluded", "boss_no": boss_no},
            )

        pct_entries = ocr_roi(context, image, f"{argv.node_name}Pct", CALC_RIGHT_PCT_ROI)
        lit_segments = count_lit_phase_segments(image)
        more_entries = (
            ocr_roi(context, image, f"{argv.node_name}More", CALC_MORE_RECORD_ROI)
            if lit_segments >= 5
            else []
        )
        if is_boss_completed_100(image, pct_entries, more_entries):
            return CustomRecognition.AnalyzeResult(
                box=(780, 595, 220, 50),
                detail={"ok": True, "reason": "boss_100_percent", "boss_no": boss_no},
            )

        active_target = state.get("active_target_boss")
        if (
            scope == "all_bosses"
            and boss_order == "lowest_level_first"
            and active_target is not None
            and boss_no is not None
            and int(boss_no) != int(active_target)
        ):
            return CustomRecognition.AnalyzeResult(
                box=(780, 595, 220, 50),
                detail={
                    "ok": True,
                    "reason": "active_target_mismatch",
                    "boss_no": boss_no,
                    "target_boss": active_target,
                },
            )

        max_enemy_level = resolve_effective_max_enemy_level(params)
        if max_enemy_level > 0:
            enemy_lv = parse_enemy_level(ocr_roi(context, image, f"{argv.node_name}Lv", CALC_ENEMY_LEVEL_ROI))
            if should_skip_for_enemy_level(enemy_lv, max_enemy_level):
                return CustomRecognition.AnalyzeResult(
                    box=(780, 595, 220, 50),
                    detail={
                        "ok": True,
                        "reason": "enemy_level_exceeded",
                        "enemy_level": enemy_lv,
                        "max_enemy_level": max_enemy_level,
                    },
                )

        return CustomRecognition.AnalyzeResult(box=None, detail={"ok": False, "reason": "ready_to_fight"})


@AgentServer.custom_action("calculation_recording_open_activity_hub")
class CalculationRecordingOpenActivityHubAction(CustomAction):
    """Navigate from Lobby to Activity Hub."""

    @exit_on_network_restart(return_value=CustomAction.RunResult(success=True))
    def run(self, context: Context, argv: CustomAction.RunArg) -> CustomAction.RunResult:
        ok = open_activity_hub(context, f"{argv.node_name}_Hub")
        return CustomAction.RunResult(success=ok and not is_stopping(context))


@AgentServer.custom_action("calculation_recording_switch_to_tab")
class CalculationRecordingSwitchToTabAction(CustomAction):
    """Switch Activity Hub sidebar to 常规活动 -> 虚演刻录."""

    @exit_on_network_restart(return_value=CustomAction.RunResult(success=True))
    def run(self, context: Context, argv: CustomAction.RunArg) -> CustomAction.RunResult:
        ok, _ = select_activity_tab(context, f"{argv.node_name}_Tab", "常规活动", ("虚演刻录",))
        return CustomAction.RunResult(success=ok and not is_stopping(context))


@AgentServer.custom_action("calculation_recording_enter_battle")
class CalculationRecordingEnterBattleAction(CustomAction):
    """Snapshot current Boss progress and click '开始虚演刻录'."""

    @exit_on_network_restart(return_value=CustomAction.RunResult(success=True))
    def run(self, context: Context, argv: CustomAction.RunArg) -> CustomAction.RunResult:
        img = safe_screencap(context)
        if img is None:
            return CustomAction.RunResult(success=False)

        state = _task_state(context, argv)
        tickets = parse_ticket_count(ocr_roi(context, img, f"{argv.node_name}Ticket", CALC_TICKET_ROI))
        if tickets is not None and tickets == 0:
            state["done"] = True
            print("[CalculationRecording] 虚演刻录门票数量为 0，任务结束。", flush=True)
            return CustomAction.RunResult(success=True)

        snapshot = _read_current_boss_snapshot(context, img, f"{argv.node_name}Pre_")
        _update_catalog(state.setdefault("boss_catalog", {}), snapshot)
        state["pending_battle"] = snapshot
        state["battle_settled"] = False

        box = find_start_button_box(ocr_roi(context, img, f"{argv.node_name}Start", CALC_START_BTN_ROI))
        tx, ty = _box_center(box or getattr(argv, "box", None), CALC_START_BTN_FALLBACK)
        ok = run_guarded_click(context, f"{argv.node_name}Guarded", tx, ty)
        if ok:
            no_str = f"{int(snapshot['boss_no']):02d}" if snapshot.get("boss_no") is not None else "?"
            print(
                f"[CalculationRecording] 进入 Boss {no_str}「{snapshot.get('boss_name') or '未知'}」"
                f"（敌人等级 {snapshot.get('enemy_level') or '未知'}，已点亮阶段 {snapshot.get('lit_segments', 0)}/5）。",
                flush=True,
            )
        return CustomAction.RunResult(success=ok and not is_stopping(context))


@AgentServer.custom_action("calculation_recording_dismiss_record")
class CalculationRecordingDismissRecordAction(CustomAction):
    """Dismiss the centered '通关记录' modal overlay by clicking safely outside on the left."""

    @exit_on_network_restart(return_value=CustomAction.RunResult(success=True))
    def run(self, context: Context, argv: CustomAction.RunArg) -> CustomAction.RunResult:
        ok = run_guarded_click(
            context,
            f"{argv.node_name}Guarded",
            CALC_RECORD_MODAL_DISMISS_POINT[0],
            CALC_RECORD_MODAL_DISMISS_POINT[1],
        )
        if ok:
            _task_state(context, argv)["battle_settled"] = True
        return CustomAction.RunResult(success=ok and not is_stopping(context))


@AgentServer.custom_action("calculation_recording_settle_next")
class CalculationRecordingSettleNextAction(CustomAction):
    """Click the circular '下一步' settlement button and mark battle settled."""

    @exit_on_network_restart(return_value=CustomAction.RunResult(success=True))
    def run(self, context: Context, argv: CustomAction.RunArg) -> CustomAction.RunResult:
        state = _task_state(context, argv)
        cx, cy = _box_center(getattr(argv, "box", None), CALC_SETTLE_NEXT_POINT)
        if cy > 640:
            tx, ty = (CALC_SETTLE_NEXT_POINT[0], 610) if abs(cx - CALC_SETTLE_NEXT_POINT[0]) <= 60 else (cx, 610)
        else:
            tx, ty = cx, cy
        ok = run_guarded_click(context, f"{argv.node_name}Guarded", tx, ty)
        if ok:
            state["completed_runs"] = int(state["completed_runs"]) + 1
            state["battle_settled"] = True
            print(f"[CalculationRecording] 本轮已完成第 {state['completed_runs']} 场结算。", flush=True)
        return CustomAction.RunResult(success=ok and not is_stopping(context))


@AgentServer.custom_action("calculation_recording_ticket_abort")
class CalculationRecordingTicketAbortAction(CustomAction):
    """Dismiss ticket-shortage prompt (if visible) and mark the run done cleanly."""

    @exit_on_network_restart(return_value=CustomAction.RunResult(success=True))
    def run(self, context: Context, argv: CustomAction.RunArg) -> CustomAction.RunResult:
        img = safe_screencap(context)
        if img is not None:
            btn_entries = ocr_roi(context, img, f"{argv.node_name}Btns", CALC_SHORTAGE_BTN_ROI)
            btn_pt = find_popup_cancel_or_confirm_point(btn_entries)
            if btn_pt is not None:
                tap_point(context, f"{argv.node_name}Close", btn_pt)
                sleep_with_stop(context, 0.5)
        _task_state(context, argv)["done"] = True
        print("[CalculationRecording] 虚演刻录门票/次数不足，任务正常结束。", flush=True)
        return CustomAction.RunResult(success=not is_stopping(context))


@AgentServer.custom_action("calculation_recording_advance")
class CalculationRecordingAdvanceAction(CustomAction):
    """Scan unlocked Bosses, handle post-battle S-rank progression, and select lowest-level target."""

    def _scroll_to_top(self, context: Context, prefix: str, image: Any) -> tuple[Any | None, dict[str, Any] | None]:
        cur_img = image
        sel_slot = find_selected_left_slot(cur_img)
        snap = _read_current_boss_snapshot(context, cur_img, f"{prefix}TopCheck_")
        if sel_slot == 0 and snap.get("boss_no") == 1:
            return cur_img, snap

        prev_top_no: int | None = None
        ux1, uy1, ux2, uy2 = CALC_LIST_SWIPE_UP
        for step in range(8):
            if not swipe_points(context, f"{prefix}Up{step}", (ux1, uy1), (ux2, uy2), duration=450, end_hold=250):
                return None, None
            if not sleep_with_stop(context, 0.6):
                return None, None
            cur_img = safe_screencap(context)
            if cur_img is None:
                return None, None
            if not tap_point(context, f"{prefix}TopTap{step}", (CALC_LEFT_SLOT_TAP_X, CALC_LEFT_SLOT_CENTERS_Y[0])):
                return None, None
            if not sleep_with_stop(context, 0.55):
                return None, None
            cur_img = safe_screencap(context)
            if cur_img is None:
                return None, None
            snap = _read_current_boss_snapshot(context, cur_img, f"{prefix}TopRead{step}_")
            top_no = snap.get("boss_no")
            if top_no == 1:
                return cur_img, snap
            if top_no is not None and prev_top_no is not None and top_no == prev_top_no:
                return cur_img, snap
            if top_no is not None:
                prev_top_no = top_no

        return cur_img, snap

    def _scan_all_unlocked_bosses(
        self,
        context: Context,
        prefix: str,
        image: Any,
        state: dict[str, Any],
    ) -> Any | None:
        catalog: dict[int, dict[str, Any]] = state.setdefault("boss_catalog", {})
        cur_img, first_top_snap = self._scroll_to_top(context, f"{prefix}ScrollTop_", image)
        if cur_img is None:
            return None

        prev_page_nos: list[int] = []
        nudge_done_for_page = False

        for page in range(15):
            if is_stopping(context):
                return None
            left_entries = ocr_roi(context, cur_img, f"{prefix}LeftP{page}", CALC_LEFT_LIST_ROI)
            page_nos: list[int] = []
            saw_locked = False

            slot0_unlocked = is_left_slot_unlocked(cur_img, CALC_LEFT_SLOT_CENTERS_Y[0], left_entries)
            if not slot0_unlocked:
                break

            # Read slot 0 first so we can detect bottom stall or skipped boss gap.
            if page == 0 and first_top_snap is not None and first_top_snap.get("boss_no") is not None:
                snap0 = first_top_snap
            else:
                if not tap_point(context, f"{prefix}P{page}Tap0", (CALC_LEFT_SLOT_TAP_X, CALC_LEFT_SLOT_CENTERS_Y[0])):
                    return None
                if not sleep_with_stop(context, 0.55):
                    return None
                cur_img = safe_screencap(context)
                if cur_img is None:
                    return None
                snap0 = _read_current_boss_snapshot(context, cur_img, f"{prefix}P{page}S0_")

            no0 = snap0.get("boss_no")
            if (
                no0 is not None
                and prev_page_nos
                and int(no0) > int(prev_page_nos[-1]) + 1
                and not nudge_done_for_page
            ):
                nx1, ny1, nx2, ny2 = CALC_LIST_NUDGE_UP
                if not swipe_points(context, f"{prefix}P{page}NudgeUp", (nx1, ny1), (nx2, ny2), duration=380, end_hold=250):
                    return None
                if not sleep_with_stop(context, 0.6):
                    return None
                cur_img = safe_screencap(context)
                if cur_img is None:
                    return None
                nudge_done_for_page = True
                continue

            nudge_done_for_page = False
            if no0 is not None:
                _update_catalog(catalog, snap0)
                page_nos.append(int(no0))

            overlap_base_idx: int | None = None
            if no0 is not None and prev_page_nos and int(no0) in prev_page_nos:
                overlap_base_idx = prev_page_nos.index(int(no0))

            # Inspect slots 1..3.
            for slot_idx in range(1, 4):
                cy = CALC_LEFT_SLOT_CENTERS_Y[slot_idx]
                if not is_left_slot_unlocked(cur_img, cy, left_entries):
                    saw_locked = True
                    break

                if overlap_base_idx is not None:
                    mapped_idx = overlap_base_idx + slot_idx
                    if mapped_idx < len(prev_page_nos):
                        known_no = int(prev_page_nos[mapped_idx])
                        if known_no in catalog:
                            page_nos.append(known_no)
                            continue

                if not tap_point(context, f"{prefix}P{page}Tap{slot_idx}", (CALC_LEFT_SLOT_TAP_X, cy)):
                    return None
                if not sleep_with_stop(context, 0.55):
                    return None
                cur_img = safe_screencap(context)
                if cur_img is None:
                    return None
                snap = _read_current_boss_snapshot(context, cur_img, f"{prefix}P{page}S{slot_idx}_")
                b_no = snap.get("boss_no")
                if b_no is not None:
                    _update_catalog(catalog, snap)
                    page_nos.append(int(b_no))

            if saw_locked:
                break
            if prev_page_nos and page_nos and tuple(page_nos) == tuple(prev_page_nos):
                break
            if page_nos:
                prev_page_nos = page_nos

            dx1, dy1, dx2, dy2 = CALC_LIST_SWIPE_DOWN
            if not swipe_points(context, f"{prefix}Down{page}", (dx1, dy1), (dx2, dy2), duration=450, end_hold=250):
                return None
            if not sleep_with_stop(context, 0.6):
                return None
            cur_img = safe_screencap(context)
            if cur_img is None:
                return None

        state["catalog_scanned"] = True
        return cur_img

    def _locate_and_select_boss(
        self,
        context: Context,
        prefix: str,
        image: Any,
        target_boss_no: int,
    ) -> tuple[Any | None, dict[str, Any] | None]:
        cur_img = image
        cur_snap = _read_current_boss_snapshot(context, cur_img, f"{prefix}Init_")
        cur_no = cur_snap.get("boss_no")
        if cur_no is not None and int(cur_no) == int(target_boss_no):
            return cur_img, cur_snap

        last_anchor_no: int | None = None
        same_anchor_count = 0

        for step in range(14):
            if is_stopping(context):
                return None, None
            sel_slot = find_selected_left_slot(cur_img)
            if cur_no is None:
                if not tap_point(context, f"{prefix}AnchorTap{step}", (CALC_LEFT_SLOT_TAP_X, CALC_LEFT_SLOT_CENTERS_Y[0])):
                    return None, None
                if not sleep_with_stop(context, 0.55):
                    return None, None
                cur_img = safe_screencap(context)
                if cur_img is None:
                    return None, None
                cur_snap = _read_current_boss_snapshot(context, cur_img, f"{prefix}AnchorRead{step}_")
                cur_no = cur_snap.get("boss_no")
                sel_slot = 0
                if cur_no is None:
                    break

            if int(cur_no) == int(target_boss_no):
                return cur_img, cur_snap

            diff = int(target_boss_no) - int(cur_no)
            if sel_slot is not None:
                est_slot = sel_slot + diff
                if 0 <= est_slot <= 3 and is_left_slot_unlocked(cur_img, CALC_LEFT_SLOT_CENTERS_Y[est_slot]):
                    if not tap_point(
                        context,
                        f"{prefix}DirectTap{step}",
                        (CALC_LEFT_SLOT_TAP_X, CALC_LEFT_SLOT_CENTERS_Y[est_slot]),
                    ):
                        return None, None
                    if not sleep_with_stop(context, 0.55):
                        return None, None
                    cur_img = safe_screencap(context)
                    if cur_img is None:
                        return None, None
                    cur_snap = _read_current_boss_snapshot(context, cur_img, f"{prefix}DirectRead{step}_")
                    cur_no = cur_snap.get("boss_no")
                    if cur_no is not None and int(cur_no) == int(target_boss_no):
                        return cur_img, cur_snap
                    if cur_no is not None and abs(int(target_boss_no) - int(cur_no)) < abs(diff):
                        continue

            if cur_no == last_anchor_no:
                same_anchor_count += 1
            else:
                last_anchor_no = int(cur_no)
                same_anchor_count = 0

            # Too far up or down: swipe toward target.
            use_small_up = diff < 0 and abs(diff) <= 2 and same_anchor_count == 0
            if diff > 0:
                sx1, sy1, sx2, sy2 = CALC_LIST_SWIPE_DOWN
                dur = 450
            elif use_small_up:
                sx1, sy1, sx2, sy2 = CALC_LIST_NUDGE_UP
                dur = 380
            else:
                sx1, sy1, sx2, sy2 = CALC_LIST_SWIPE_UP
                dur = 450

            if same_anchor_count >= 2:
                return cur_img, None

            if not swipe_points(context, f"{prefix}Swipe{step}", (sx1, sy1), (sx2, sy2), duration=dur, end_hold=250):
                return None, None
            if not sleep_with_stop(context, 0.6):
                return None, None
            cur_img = safe_screencap(context)
            if cur_img is None:
                return None, None

            probe_slot = 3 if diff > 0 and is_left_slot_unlocked(cur_img, CALC_LEFT_SLOT_CENTERS_Y[3]) else 0
            if not tap_point(
                context,
                f"{prefix}ProbeTap{step}",
                (CALC_LEFT_SLOT_TAP_X, CALC_LEFT_SLOT_CENTERS_Y[probe_slot]),
            ):
                return None, None
            if not sleep_with_stop(context, 0.55):
                return None, None
            cur_img = safe_screencap(context)
            if cur_img is None:
                return None, None
            cur_snap = _read_current_boss_snapshot(context, cur_img, f"{prefix}ProbeRead{step}_")
            cur_no = cur_snap.get("boss_no")
            if cur_no is not None and int(cur_no) == int(target_boss_no):
                return cur_img, cur_snap

        return cur_img, None

    def _handle_post_battle(
        self,
        context: Context,
        prefix: str,
        image: Any,
        state: dict[str, Any],
    ) -> Any | None:
        pending = state.get("pending_battle")
        if pending is None or not state.get("battle_settled"):
            return image

        cur_img = image
        cur_snap = _read_current_boss_snapshot(context, cur_img, f"{prefix}Post_")
        state["pending_battle"] = None
        state["battle_settled"] = False

        catalog: dict[int, dict[str, Any]] = state.setdefault("boss_catalog", {})
        excluded_bosses: set[int] = state["excluded_bosses"]
        _update_catalog(catalog, cur_snap)

        if cur_snap.get("is_100") and cur_snap.get("boss_no") is not None:
            excluded_bosses.add(int(cur_snap["boss_no"]))

        pending_no = pending.get("boss_no")
        if not did_stage_advance(pending, cur_snap):
            if pending_no is not None:
                excluded_bosses.add(int(pending_no))
                print(
                    f"[CalculationRecording] Boss {int(pending_no):02d}「{pending.get('boss_name') or '未知'}」"
                    f"未达成 S 级评级（进度未推进），跳过该 Boss！",
                    flush=True,
                )
            return cur_img

        # Check whether Stage-I S-clear unlocked the next Boss right below it.
        unlocked_next = pending_no is not None and (
            (pending.get("record_done") is False and cur_snap.get("record_done") is True)
            or (int(pending.get("lit_segments", 0)) <= 1 and int(cur_snap.get("lit_segments", 0)) >= 2)
        )
        if unlocked_next and pending_no is not None:
            next_no = int(pending_no) + 1
            cur_img, next_snap = self._locate_and_select_boss(context, f"{prefix}ProbeNew_", cur_img, next_no)
            if cur_img is None:
                return None
            if next_snap is not None and next_snap.get("boss_no") == next_no:
                _update_catalog(catalog, next_snap)
                print(
                    f"[CalculationRecording] 检测到新解锁 Boss {next_no:02d}「{next_snap.get('boss_name') or '未知'}」"
                    f"（敌人等级 {next_snap.get('enemy_level') or '未知'}），已纳入排序。",
                    flush=True,
                )

        return cur_img

    @exit_on_network_restart(return_value=CustomAction.RunResult(success=True))
    def run(self, context: Context, argv: CustomAction.RunArg) -> CustomAction.RunResult:
        state = _task_state(context, argv)
        params = _resolve_params(context, argv)
        prefix = f"{argv.node_name}_Adv"

        max_runs = resolve_effective_max_runs(params)
        if max_runs > 0 and int(state.get("completed_runs", 0)) >= max_runs:
            print(f"[CalculationRecording] 已完成指定推关次数 {state['completed_runs']}/{max_runs}，任务结束。", flush=True)
            state["done"] = True
            return CustomAction.RunResult(success=True)

        image = safe_screencap(context)
        if image is None:
            return CustomAction.RunResult(success=False)

        tickets = parse_ticket_count(ocr_roi(context, image, f"{prefix}Ticket", CALC_TICKET_ROI))
        if tickets is not None and tickets == 0:
            print("[CalculationRecording] 虚演刻录门票数量为 0，任务结束。", flush=True)
            state["done"] = True
            return CustomAction.RunResult(success=True)

        image = self._handle_post_battle(context, f"{prefix}Post_", image, state)
        if image is None or is_stopping(context):
            return CustomAction.RunResult(success=False)

        scope = str(params.get("scope") or "all_bosses")
        boss_order = str(params.get("boss_order") or "lowest_level_first")
        max_enemy_level = resolve_effective_max_enemy_level(params)
        excluded_bosses: set[int] = state["excluded_bosses"]
        catalog: dict[int, dict[str, Any]] = state.setdefault("boss_catalog", {})

        cur_snap = _read_current_boss_snapshot(context, image, f"{prefix}Cur_")
        _update_catalog(catalog, cur_snap)
        cur_no = cur_snap.get("boss_no")
        if cur_snap.get("is_100") and cur_no is not None:
            excluded_bosses.add(int(cur_no))

        cur_fightable = (
            not cur_snap.get("is_100")
            and (cur_no is None or int(cur_no) not in excluded_bosses)
            and not should_skip_for_enemy_level(cur_snap.get("enemy_level"), max_enemy_level)
        )

        if scope == "current_boss":
            if cur_fightable:
                return CustomAction.RunResult(success=True)
            if cur_snap.get("is_100"):
                print(f"[CalculationRecording] 当前 Boss {cur_no or '?'} 已达 100%，按仅当前 Boss 模式结束。", flush=True)
            elif should_skip_for_enemy_level(cur_snap.get("enemy_level"), max_enemy_level):
                print(
                    f"[CalculationRecording] 当前 Boss {cur_no or '?'} 敌人等级 {cur_snap.get('enemy_level')} "
                    f"超过上限 {max_enemy_level}，停止推关。",
                    flush=True,
                )
            else:
                print(f"[CalculationRecording] 当前 Boss {cur_no or '?'} 已跳过，按仅当前 Boss 模式结束。", flush=True)
            return CustomAction.RunResult(success=False)

        if boss_order == "list_order" and cur_fightable:
            state["initial_boss_selected"] = True
            return CustomAction.RunResult(success=True)

        cur_img = image
        if not state.get("catalog_scanned"):
            cur_img = self._scan_all_unlocked_bosses(context, f"{prefix}Scan_", cur_img, state)
            if cur_img is None or is_stopping(context):
                return CustomAction.RunResult(success=False)

        for _attempt in range(2):
            ranked = rank_unfinished_bosses(
                list(catalog.values()),
                excluded_bosses=excluded_bosses,
                max_enemy_level=max_enemy_level,
                boss_order=boss_order,
            )
            if not ranked:
                break

            for idx, cand in enumerate(ranked):
                if is_stopping(context):
                    return CustomAction.RunResult(success=False)
                target_no = int(cand["boss_no"])
                cur_img, selected_snap = self._locate_and_select_boss(
                    context,
                    f"{prefix}Pick{idx}_",
                    cur_img,
                    target_no,
                )
                if cur_img is None or is_stopping(context):
                    return CustomAction.RunResult(success=False)
                if selected_snap is None:
                    excluded_bosses.add(target_no)
                    print(f"[CalculationRecording] 未能在列表中定位 Boss {target_no:02d}，跳过。", flush=True)
                    continue

                _update_catalog(catalog, selected_snap)
                if selected_snap.get("is_100"):
                    excluded_bosses.add(target_no)
                    print(f"[CalculationRecording] Boss {target_no:02d} 已达 100%，跳过。", flush=True)
                    continue
                if should_skip_for_enemy_level(selected_snap.get("enemy_level"), max_enemy_level):
                    excluded_bosses.add(target_no)
                    print(
                        f"[CalculationRecording] Boss {target_no:02d}「{selected_snap.get('boss_name') or '未知'}」"
                        f"（敌人等级 {selected_snap.get('enemy_level')}）超过上限 {max_enemy_level}，跳过。",
                        flush=True,
                    )
                    continue

                state["initial_boss_selected"] = True
                state["active_target_boss"] = target_no
                mode_label = "低等级优先" if boss_order == "lowest_level_first" else "列表顺序"
                print(
                    f"[CalculationRecording] ({mode_label}) 切换至 Boss {target_no:02d}"
                    f"「{selected_snap.get('boss_name') or '未知'}」"
                    f"（敌人等级 {selected_snap.get('enemy_level') or '未知'}，"
                    f"阶段 {selected_snap.get('lit_segments', 0)}/5）。",
                    flush=True,
                )
                return CustomAction.RunResult(success=True)

            # Re-scan once in case catalog changed externally and retry.
            cur_img = self._scan_all_unlocked_bosses(context, f"{prefix}Rescan_", cur_img, state)
            if cur_img is None:
                return CustomAction.RunResult(success=False)

        print("[CalculationRecording] 所有符合条件的已解锁 Boss 均已推完或跳过，任务完成！", flush=True)
        return CustomAction.RunResult(success=False)
