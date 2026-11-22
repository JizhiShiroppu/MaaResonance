"""Custom MaaFramework recognitions and actions for Regional Combat Center (区域作战中心)."""
from __future__ import annotations

from typing import Any

from maa.agent.agent_server import AgentServer
from maa.context import Context
from maa.custom_action import CustomAction
from maa.custom_recognition import CustomRecognition

from agent.utils.action_helpers import ocr_roi, parse_action_param, swipe_points, tap_point
from agent.utils.activity_hub_nav import select_activity_tab
from agent.utils.input_guard import safe_screencap, sleep_with_stop
from agent.utils.lobby_nav import is_stopping
from agent.utils.network_guard import exit_on_network_restart
from maa_resonance.logic.activity_hub import ACTIVITY_HUB_SIDEBAR_ROI, is_activity_hub_entries
from maa_resonance.logic.clarity_recovery import CLARITY_BACK_POINT
from maa_resonance.logic.regional_combat import (
    REGIONAL_BANNER_ROI,
    REGIONAL_CITY_LIST_ROI,
    REGIONAL_CITY_SWIPE_DOWN,
    REGIONAL_CITY_SWIPE_UP,
    REGIONAL_DIFF_BTN_ROI,
    REGIONAL_ENEMY_LEVEL_ROI,
    REGIONAL_FIGHT_BTN_ROI,
    REGIONAL_FIRST_CLEAR_ROI,
    REGIONAL_LOW_CLARITY_BTN_ROI,
    REGIONAL_LOW_CLARITY_CANCEL_POINT,
    REGIONAL_LOW_CLARITY_CONFIRM_POINT,
    REGIONAL_STAGE_TITLE_ROI,
    find_low_clarity_popup_button,
    find_selected_city_card,
    find_terminal_regional_combat_go_point,
    has_first_clear_badge,
    is_regional_combat_page,
    merge_city_catalog,
    parse_enemy_level,
    parse_regional_city_cards,
    parse_stage_title,
    rank_unfinished_regional_cities,
    resolve_effective_max_enemy_level,
    resolve_effective_max_runs,
    select_unfinished_regional_cities,
    should_skip_for_enemy_level,
)

REGIONAL_COMBAT_ATTACH_NODES: tuple[str, ...] = (
    "RegionalCombatOptScope",
    "RegionalCombatOptCityOrder",
    "RegionalCombatOptMaxEnemyLevel",
    "RegionalCombatOptCustomMaxEnemyLevel",
    "RegionalCombatOptRunMode",
    "RegionalCombatOptRunCount",
    "RegionalCombatOptUseMedicine",
)

_REGIONAL_STATE_BY_TASK: dict[int, dict[str, Any]] = {}


def _task_state(context: Context, argv: Any) -> dict[str, Any]:
    task_detail = getattr(argv, "task_detail", None)
    task_id = getattr(task_detail, "task_id", None)
    key = int(task_id) if task_id is not None else id(getattr(context, "tasker", context))
    if len(_REGIONAL_STATE_BY_TASK) > 32:
        _REGIONAL_STATE_BY_TASK.clear()
    return _REGIONAL_STATE_BY_TASK.setdefault(
        key,
        {
            "excluded_cities": set(),
            "completed_runs": 0,
            "done": False,
            "city_catalog": {},
            "catalog_scanned": False,
            "initial_city_selected": False,
            "active_target_city": None,
        },
    )


def _resolve_params(context: Context, argv: Any, param_attr: str = "custom_action_param") -> dict[str, Any]:
    merged = dict(parse_action_param(getattr(argv, param_attr, None)))
    get_node_data = getattr(context, "get_node_data", None)
    if callable(get_node_data):
        for node_name in REGIONAL_COMBAT_ATTACH_NODES:
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


@AgentServer.custom_recognition("regional_combat_is_done")
class RegionalCombatIsDoneRecognition(CustomRecognition):
    """Trigger clean exit when the current Regional Combat run has finished."""

    def analyze(
        self,
        context: Context,
        argv: CustomRecognition.AnalyzeArg,
    ) -> CustomRecognition.AnalyzeResult:
        if _task_state(context, argv).get("done"):
            return CustomRecognition.AnalyzeResult(box=(0, 0, 10, 10), detail={"ok": True, "done": True})
        return CustomRecognition.AnalyzeResult(box=None, detail={"ok": False, "done": False})


@AgentServer.custom_recognition("regional_combat_terminal_card")
class RegionalCombatTerminalCardRecognition(CustomRecognition):
    """Detect the 区域作战中心 card inside the 铁安协同终端 hub screen."""

    def analyze(
        self,
        context: Context,
        argv: CustomRecognition.AnalyzeArg,
    ) -> CustomRecognition.AnalyzeResult:
        image = getattr(argv, "image", None)
        if image is None:
            return CustomRecognition.AnalyzeResult(box=None, detail={"ok": False})

        entries = ocr_roi(context, image, f"{argv.node_name}Scan", (0, 0, 1280, 720))
        point = find_terminal_regional_combat_go_point(entries)
        if point is None:
            return CustomRecognition.AnalyzeResult(box=None, detail={"ok": False})

        px, py = point
        return CustomRecognition.AnalyzeResult(
            box=(max(0, px - 40), max(0, py - 20), 80, 40),
            detail={"ok": True, "tap_point": [px, py]},
        )


@AgentServer.custom_recognition("regional_combat_activity_hub_need_switch")
class RegionalCombatActivityHubNeedSwitchRecognition(CustomRecognition):
    """Detect when Activity Hub is open on a tab other than 铁安协同终端."""

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
        if find_terminal_regional_combat_go_point(full_entries) is not None:
            return CustomRecognition.AnalyzeResult(box=None, detail={"ok": False, "reason": "already_on_terminal"})

        return CustomRecognition.AnalyzeResult(
            box=(20, 130, 180, 40),
            detail={"ok": True},
        )


@AgentServer.custom_recognition("regional_combat_needs_advance")
class RegionalCombatNeedsAdvanceRecognition(CustomRecognition):
    """Trigger station/stage advancement when current target is cleared, over-level, excluded, or reached max_runs."""

    def analyze(
        self,
        context: Context,
        argv: CustomRecognition.AnalyzeArg,
    ) -> CustomRecognition.AnalyzeResult:
        image = getattr(argv, "image", None)
        if image is None:
            return CustomRecognition.AnalyzeResult(box=None, detail={"ok": False})

        banner_entries = ocr_roi(context, image, f"{argv.node_name}Banner", REGIONAL_BANNER_ROI)
        diff_entries = ocr_roi(context, image, f"{argv.node_name}Diff", REGIONAL_DIFF_BTN_ROI)
        fight_entries = ocr_roi(context, image, f"{argv.node_name}FightBtn", REGIONAL_FIGHT_BTN_ROI)
        if not is_regional_combat_page(banner_entries, diff_entries, fight_entries):
            return CustomRecognition.AnalyzeResult(box=None, detail={"ok": False, "reason": "not_regional_page"})

        state = _task_state(context, argv)
        params = _resolve_params(context, argv, "custom_recognition_param")
        scope = str(params.get("scope") or "all_cities")
        city_order = str(params.get("city_order") or "fewest_stages_first")
        max_runs = resolve_effective_max_runs(params)
        if max_runs > 0 and int(state.get("completed_runs", 0)) >= max_runs:
            return CustomRecognition.AnalyzeResult(
                box=(980, 565, 180, 50),
                detail={"ok": True, "reason": "max_runs_reached"},
            )

        if scope == "all_cities" and city_order == "fewest_stages_first" and not state.get("initial_city_selected"):
            return CustomRecognition.AnalyzeResult(
                box=(980, 565, 180, 50),
                detail={"ok": True, "reason": "initial_city_selection"},
            )

        city_entries = ocr_roi(context, image, f"{argv.node_name}Cities", REGIONAL_CITY_LIST_ROI)
        cards = parse_regional_city_cards(city_entries)
        selected_card = find_selected_city_card(image, cards)
        excluded_cities: set[str] = state["excluded_cities"]
        if scope == "all_cities" and selected_card is not None:
            selected_name = str(selected_card["city_name"]).strip()
            if selected_name in excluded_cities:
                return CustomRecognition.AnalyzeResult(
                    box=(980, 565, 180, 50),
                    detail={"ok": True, "reason": "city_excluded", "city": selected_card["city_name"]},
                )
            active_target = state.get("active_target_city")
            if city_order == "fewest_stages_first" and active_target and selected_name != str(active_target).strip():
                return CustomRecognition.AnalyzeResult(
                    box=(980, 565, 180, 50),
                    detail={
                        "ok": True,
                        "reason": "active_target_mismatch",
                        "selected_city": selected_name,
                        "target_city": active_target,
                    },
                )

        fc_entries = ocr_roi(context, image, f"{argv.node_name}FirstClear", REGIONAL_FIRST_CLEAR_ROI)
        if not has_first_clear_badge(fc_entries):
            return CustomRecognition.AnalyzeResult(
                box=(980, 565, 180, 50),
                detail={"ok": True, "reason": "no_first_clear_badge"},
            )

        max_enemy_level = resolve_effective_max_enemy_level(params)
        if max_enemy_level > 0:
            lv_entries = ocr_roi(context, image, f"{argv.node_name}EnemyLv", REGIONAL_ENEMY_LEVEL_ROI)
            enemy_lv = parse_enemy_level(lv_entries)
            city_min_lv = selected_card.get("min_level") if selected_card is not None else None
            if should_skip_for_enemy_level(enemy_lv, max_enemy_level, city_min_level=city_min_lv):
                return CustomRecognition.AnalyzeResult(
                    box=(980, 565, 180, 50),
                    detail={
                        "ok": True,
                        "reason": "enemy_level_exceeded",
                        "enemy_level": enemy_lv,
                        "city_min_level": city_min_lv,
                        "max_enemy_level": max_enemy_level,
                    },
                )

        return CustomRecognition.AnalyzeResult(box=None, detail={"ok": False, "reason": "ready_to_fight"})


@AgentServer.custom_action("regional_combat_switch_to_terminal")
class RegionalCombatSwitchToTerminalAction(CustomAction):
    """Switch Activity Hub sidebar to 常规活动 -> 协同终端."""

    @exit_on_network_restart(return_value=CustomAction.RunResult(success=True))
    def run(self, context: Context, argv: CustomAction.RunArg) -> CustomAction.RunResult:
        ok, _ = select_activity_tab(context, f"{argv.node_name}_Hub", "常规活动", ("协同终端",))
        return CustomAction.RunResult(success=ok and not is_stopping(context))


@AgentServer.custom_action("regional_combat_advance")
class RegionalCombatAdvanceAction(CustomAction):
    """Advance to the next uncleared stage or station inside Regional Combat Center."""

    def _evaluate_selected_stage(
        self,
        context: Context,
        image: Any,
        prefix: str,
        *,
        max_enemy_level: int,
        city_min_level: int | None,
    ) -> tuple[bool, int | None, str, bool]:
        """Return ``(fightable, enemy_level, stage_title, has_fc)``."""
        fc_entries = ocr_roi(context, image, f"{prefix}FC", REGIONAL_FIRST_CLEAR_ROI)
        has_fc = has_first_clear_badge(fc_entries)
        lv_entries = ocr_roi(context, image, f"{prefix}Lv", REGIONAL_ENEMY_LEVEL_ROI)
        enemy_lv = parse_enemy_level(lv_entries)
        title_entries = ocr_roi(context, image, f"{prefix}Title", REGIONAL_STAGE_TITLE_ROI)
        stage_title = parse_stage_title(title_entries)
        over_level = should_skip_for_enemy_level(enemy_lv, max_enemy_level, city_min_level=city_min_level)
        return (has_fc and not over_level), enemy_lv, stage_title, has_fc

    def _scan_full_city_catalog(
        self,
        context: Context,
        prefix: str,
        image: Any,
        state: dict[str, Any],
        *,
        initial_cards: list[dict[str, Any]] | None = None,
    ) -> Any | None:
        catalog: dict[str, dict[str, Any]] = state.setdefault("city_catalog", {})
        cur_img = image
        cur_cards = (
            initial_cards
            if initial_cards is not None
            else parse_regional_city_cards(ocr_roi(context, cur_img, f"{prefix}Init", REGIONAL_CITY_LIST_ROI))
        )
        merge_city_catalog(catalog, cur_cards)
        last_sig = tuple(str(c["city_name"]) for c in cur_cards)

        ux1, uy1, ux2, uy2 = REGIONAL_CITY_SWIPE_UP
        for step in range(3):
            if not swipe_points(context, f"{prefix}Up{step}", (ux1, uy1), (ux2, uy2), duration=450, end_hold=150):
                return None
            if not sleep_with_stop(context, 0.6):
                return None
            cur_img = safe_screencap(context)
            if cur_img is None:
                return None
            cur_cards = parse_regional_city_cards(ocr_roi(context, cur_img, f"{prefix}UpScan{step}", REGIONAL_CITY_LIST_ROI))
            merge_city_catalog(catalog, cur_cards)
            cur_sig = tuple(str(c["city_name"]) for c in cur_cards)
            if cur_sig and cur_sig == last_sig:
                break
            last_sig = cur_sig

        dx1, dy1, dx2, dy2 = REGIONAL_CITY_SWIPE_DOWN
        for step in range(4):
            if not swipe_points(context, f"{prefix}Down{step}", (dx1, dy1), (dx2, dy2), duration=450, end_hold=150):
                return None
            if not sleep_with_stop(context, 0.6):
                return None
            cur_img = safe_screencap(context)
            if cur_img is None:
                return None
            cur_cards = parse_regional_city_cards(ocr_roi(context, cur_img, f"{prefix}DownScan{step}", REGIONAL_CITY_LIST_ROI))
            merge_city_catalog(catalog, cur_cards)
            cur_sig = tuple(str(c["city_name"]) for c in cur_cards)
            if cur_sig and cur_sig == last_sig:
                break
            last_sig = cur_sig

        state["catalog_scanned"] = True
        return cur_img

    def _locate_and_select_city(
        self,
        context: Context,
        prefix: str,
        image: Any,
        target_city_name: str,
        *,
        catalog: dict[str, dict[str, Any]],
        max_enemy_level: int,
    ) -> tuple[bool, Any | None, int | None, str, bool, dict[str, Any] | None]:
        """Locate target_city_name on screen (sweeping up/down if needed), select it, and evaluate."""

        def _find_on_frame(frame: Any, tag: str) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
            cards = parse_regional_city_cards(ocr_roi(context, frame, f"{tag}Cities", REGIONAL_CITY_LIST_ROI))
            merge_city_catalog(catalog, cards)
            match = next((c for c in cards if str(c["city_name"]).strip() == target_city_name), None)
            return cards, match

        cur_img = image
        cards, target_card = _find_on_frame(cur_img, f"{prefix}Cur_")
        last_sig = tuple(str(c["city_name"]) for c in cards)

        if target_card is None:
            for dir_tag, (sx1, sy1, sx2, sy2) in (("Up", REGIONAL_CITY_SWIPE_UP), ("Down", REGIONAL_CITY_SWIPE_DOWN)):
                for step in range(4):
                    if not swipe_points(context, f"{prefix}{dir_tag}{step}", (sx1, sy1), (sx2, sy2), duration=450, end_hold=150):
                        return False, None, None, "", False, None
                    if not sleep_with_stop(context, 0.6):
                        return False, None, None, "", False, None
                    cur_img = safe_screencap(context)
                    if cur_img is None:
                        return False, None, None, "", False, None
                    cards, target_card = _find_on_frame(cur_img, f"{prefix}{dir_tag}{step}_")
                    if target_card is not None:
                        break
                    cur_sig = tuple(str(c["city_name"]) for c in cards)
                    if cur_sig and cur_sig == last_sig:
                        break
                    last_sig = cur_sig
                if target_card is not None:
                    break

        if target_card is None:
            return False, cur_img, None, "", False, None

        selected = find_selected_city_card(cur_img, cards)
        already_selected = selected is not None and str(selected["city_name"]).strip() == target_city_name
        if not already_selected:
            if not tap_point(context, f"{prefix}TapTarget", target_card["tap_point"]):
                return False, None, None, "", False, target_card
            if not sleep_with_stop(context, 0.75):
                return False, None, None, "", False, target_card
            cur_img = safe_screencap(context)
            if cur_img is None:
                return False, None, None, "", False, target_card

        fightable, enemy_lv, stage_title, has_fc = self._evaluate_selected_stage(
            context,
            cur_img,
            f"{prefix}Eval_",
            max_enemy_level=max_enemy_level,
            city_min_level=target_card.get("min_level"),
        )
        if not has_fc and already_selected and int(target_card["percent"]) < 100:
            if not tap_point(context, f"{prefix}RetapTarget", target_card["tap_point"]):
                return False, None, None, "", False, target_card
            if not sleep_with_stop(context, 0.75):
                return False, None, None, "", False, target_card
            cur_img = safe_screencap(context)
            if cur_img is None:
                return False, None, None, "", False, target_card
            fightable, enemy_lv, stage_title, has_fc = self._evaluate_selected_stage(
                context,
                cur_img,
                f"{prefix}RetapEval_",
                max_enemy_level=max_enemy_level,
                city_min_level=target_card.get("min_level"),
            )

        return fightable, cur_img, enemy_lv, stage_title, has_fc, target_card

    def _select_fewest_stages_city(
        self,
        context: Context,
        prefix: str,
        image: Any,
        state: dict[str, Any],
        *,
        initial_cards: list[dict[str, Any]] | None,
        max_enemy_level: int,
    ) -> CustomAction.RunResult:
        excluded_cities: set[str] = state["excluded_cities"]
        cur_img = image
        pending_cards = initial_cards
        scanned_this_call = False

        for refresh_pass in range(2):
            if not state.get("catalog_scanned") or refresh_pass > 0:
                cur_img = self._scan_full_city_catalog(
                    context,
                    f"{prefix}Catalog{refresh_pass}_",
                    cur_img,
                    state,
                    initial_cards=pending_cards if refresh_pass == 0 else None,
                )
                if cur_img is None:
                    return CustomAction.RunResult(success=False)
                pending_cards = None
                scanned_this_call = True

            ranked = rank_unfinished_regional_cities(
                list(state.get("city_catalog", {}).values()),
                excluded_cities=excluded_cities,
                max_enemy_level=max_enemy_level,
                city_order="fewest_stages_first",
            )
            if not ranked:
                if not scanned_this_call:
                    continue
                break

            for idx, cand in enumerate(ranked):
                if is_stopping(context):
                    return CustomAction.RunResult(success=False)
                target_name = str(cand["city_name"]).strip()
                fightable, cur_img, enemy_lv, stage_title, has_fc, found_card = self._locate_and_select_city(
                    context,
                    f"{prefix}Pick{refresh_pass}_{idx}_",
                    cur_img,
                    target_name,
                    catalog=state.setdefault("city_catalog", {}),
                    max_enemy_level=max_enemy_level,
                )
                if cur_img is None or is_stopping(context):
                    return CustomAction.RunResult(success=False)
                if fightable:
                    state["initial_city_selected"] = True
                    state["active_target_city"] = target_name
                    eff_card = found_card or cand
                    sc = eff_card.get("stage_count")
                    sc_info = f"约 {sc} 关" if sc is not None else "关卡数未知"
                    print(
                        f"[RegionalCombat] 优先切换至短站点「{target_name}」（{sc_info}，进度 {eff_card.get('percent', '?')}%）"
                        f"->「{stage_title or '未通关关卡'}」（敌方等级={enemy_lv or '未知'}）。",
                        flush=True,
                    )
                    return CustomAction.RunResult(success=True)

                if found_card is None:
                    print(f"[RegionalCombat] 未在列表中找到候选车站「{target_name}」，跳过。", flush=True)
                elif not has_fc:
                    print(f"[RegionalCombat] 车站「{target_name}」当前未见「首通」标签，跳过。", flush=True)
                else:
                    print(
                        f"[RegionalCombat] 车站「{target_name}」关卡「{stage_title or '未知'}」"
                        f"（敌方等级 {enemy_lv or cand.get('min_level')}）超过上限 {max_enemy_level}，跳过。",
                        flush=True,
                    )
                excluded_cities.add(target_name)

            if scanned_this_call:
                break

        print("[RegionalCombat] 所有符合条件的已解锁车站均已推进完毕或超过敌方等级上限，任务完成！", flush=True)
        return CustomAction.RunResult(success=False)

    def _try_visible_cities(
        self,
        context: Context,
        prefix: str,
        image: Any,
        excluded_cities: set[str],
        *,
        max_enemy_level: int,
    ) -> tuple[bool, tuple[str, ...]]:
        city_entries = ocr_roi(context, image, f"{prefix}Scan", REGIONAL_CITY_LIST_ROI)
        all_cards = parse_regional_city_cards(city_entries)
        signature = tuple(str(c["city_name"]) for c in all_cards)

        candidates = select_unfinished_regional_cities(
            city_entries,
            excluded_cities=excluded_cities,
            max_enemy_level=max_enemy_level,
        )
        for idx, card in enumerate(candidates):
            if is_stopping(context):
                return False, signature
            city_name = str(card["city_name"]).strip()
            tx, ty = card["tap_point"]
            if not tap_point(context, f"{prefix}City{idx}", (tx, ty)):
                return False, signature
            if not sleep_with_stop(context, 0.75):
                return False, signature
            after_img = safe_screencap(context)
            if after_img is None:
                return False, signature

            fightable, enemy_lv, stage_title, has_fc = self._evaluate_selected_stage(
                context,
                after_img,
                f"{prefix}Pick{idx}_",
                max_enemy_level=max_enemy_level,
                city_min_level=card.get("min_level"),
            )
            if fightable:
                print(
                    f"[RegionalCombat] 切换至车站「{city_name}」（列表进度 {card['percent']}%）"
                    f"->「{stage_title or '未通关关卡'}」（敌方等级={enemy_lv or '未知'}）。",
                    flush=True,
                )
                return True, signature

            if not has_fc:
                print(f"[RegionalCombat] 车站「{city_name}」当前未见「首通」标签，跳过。", flush=True)
            else:
                print(
                    f"[RegionalCombat] 车站「{city_name}」关卡「{stage_title or '未知'}」"
                    f"（敌方等级 {enemy_lv or card.get('min_level')}）超过上限 {max_enemy_level}，跳过。",
                    flush=True,
                )
            excluded_cities.add(city_name)

        return False, signature

    @exit_on_network_restart(return_value=CustomAction.RunResult(success=True))
    def run(self, context: Context, argv: CustomAction.RunArg) -> CustomAction.RunResult:
        state = _task_state(context, argv)
        params = _resolve_params(context, argv)
        prefix = f"{argv.node_name}_Adv"

        max_runs = resolve_effective_max_runs(params)
        if max_runs > 0 and int(state.get("completed_runs", 0)) >= max_runs:
            print(f"[RegionalCombat] 已完成指定推关次数 {state['completed_runs']}/{max_runs}，任务结束。", flush=True)
            state["done"] = True
            return CustomAction.RunResult(success=True)

        scope = str(params.get("scope") or "all_cities")
        city_order = str(params.get("city_order") or "fewest_stages_first")
        max_enemy_level = resolve_effective_max_enemy_level(params)
        excluded_cities: set[str] = state["excluded_cities"]

        image = safe_screencap(context)
        if image is None:
            return CustomAction.RunResult(success=False)

        city_entries = ocr_roi(context, image, f"{prefix}Cities", REGIONAL_CITY_LIST_ROI)
        cards = parse_regional_city_cards(city_entries)
        merge_city_catalog(state.setdefault("city_catalog", {}), cards)
        selected_card = find_selected_city_card(image, cards)
        selected_min_lv = selected_card.get("min_level") if selected_card is not None else None
        selected_name = str(selected_card["city_name"]).strip() if selected_card is not None else ""

        if scope == "all_cities" and city_order == "fewest_stages_first" and not state.get("initial_city_selected"):
            return self._select_fewest_stages_city(
                context,
                f"{prefix}Init_",
                image,
                state,
                initial_cards=cards,
                max_enemy_level=max_enemy_level,
            )

        fightable, enemy_lv, stage_title, has_fc = self._evaluate_selected_stage(
            context,
            image,
            f"{prefix}Cur_",
            max_enemy_level=max_enemy_level,
            city_min_level=selected_min_lv,
        )

        if (
            not has_fc
            and selected_card is not None
            and int(selected_card["percent"]) < 100
            and selected_name not in excluded_cities
            and not (max_enemy_level > 0 and selected_min_lv is not None and int(selected_min_lv) > max_enemy_level)
            and (
                scope != "all_cities"
                or city_order != "fewest_stages_first"
                or not state.get("active_target_city")
                or selected_name == str(state.get("active_target_city")).strip()
            )
        ):
            if not tap_point(context, f"{prefix}RetapSameCity", selected_card["tap_point"]):
                return CustomAction.RunResult(success=False)
            if not sleep_with_stop(context, 0.75):
                return CustomAction.RunResult(success=False)
            retap_img = safe_screencap(context)
            if retap_img is None:
                return CustomAction.RunResult(success=False)
            fightable, enemy_lv, stage_title, has_fc = self._evaluate_selected_stage(
                context,
                retap_img,
                f"{prefix}Retap_",
                max_enemy_level=max_enemy_level,
                city_min_level=selected_min_lv,
            )
            if fightable:
                print(
                    f"[RegionalCombat] 已切至「{selected_name}」未通关关卡「{stage_title or '未知关卡'}」"
                    f"（敌方等级={enemy_lv or '未知'}）。",
                    flush=True,
                )
                return CustomAction.RunResult(success=True)
            image = retap_img

        active_target = state.get("active_target_city")
        is_target_match = (
            scope != "all_cities"
            or city_order != "fewest_stages_first"
            or not active_target
            or selected_card is None
            or selected_name == str(active_target).strip()
        )
        if fightable and is_target_match and (selected_card is None or selected_name not in excluded_cities):
            return CustomAction.RunResult(success=True)

        if selected_card is not None:
            if (
                scope != "all_cities"
                or city_order != "fewest_stages_first"
                or not fightable
                or not active_target
                or selected_name == str(active_target).strip()
            ):
                excluded_cities.add(selected_name)
        else:
            selected_name = "当前车站"

        if scope == "current_city":
            if has_fc and should_skip_for_enemy_level(enemy_lv, max_enemy_level, city_min_level=selected_min_lv):
                print(
                    f"[RegionalCombat] 当前车站「{selected_name}」关卡「{stage_title or '未知'}」"
                    f"（敌方等级 {enemy_lv or selected_min_lv}）超过上限 {max_enemy_level}，停止推关。",
                    flush=True,
                )
            else:
                pct_info = f"（进度 {selected_card['percent']}%）" if selected_card is not None else ""
                print(
                    f"[RegionalCombat] 当前车站「{selected_name}」已无未通关首通关卡{pct_info}，按仅当前车站模式结束。",
                    flush=True,
                )
            return CustomAction.RunResult(success=False)

        if city_order == "fewest_stages_first":
            return self._select_fewest_stages_city(
                context,
                f"{prefix}Fewest_",
                image,
                state,
                initial_cards=cards,
                max_enemy_level=max_enemy_level,
            )

        switched, last_sig = self._try_visible_cities(
            context,
            f"{prefix}Vis_",
            image,
            excluded_cities,
            max_enemy_level=max_enemy_level,
        )
        if switched:
            return CustomAction.RunResult(success=True)
        if is_stopping(context):
            return CustomAction.RunResult(success=False)

        dx1, dy1, dx2, dy2 = REGIONAL_CITY_SWIPE_DOWN
        for step in range(5):
            if not swipe_points(context, f"{prefix}Down{step}", (dx1, dy1), (dx2, dy2), duration=450, end_hold=150):
                return CustomAction.RunResult(success=False)
            if not sleep_with_stop(context, 0.6):
                return CustomAction.RunResult(success=False)
            cur_img = safe_screencap(context)
            if cur_img is None:
                return CustomAction.RunResult(success=False)
            switched, cur_sig = self._try_visible_cities(
                context,
                f"{prefix}Down{step}_",
                cur_img,
                excluded_cities,
                max_enemy_level=max_enemy_level,
            )
            if switched:
                return CustomAction.RunResult(success=True)
            if is_stopping(context):
                return CustomAction.RunResult(success=False)
            if cur_sig and cur_sig == last_sig:
                break
            last_sig = cur_sig

        ux1, uy1, ux2, uy2 = REGIONAL_CITY_SWIPE_UP
        for step in range(5):
            if not swipe_points(context, f"{prefix}Up{step}", (ux1, uy1), (ux2, uy2), duration=450, end_hold=150):
                return CustomAction.RunResult(success=False)
            if not sleep_with_stop(context, 0.6):
                return CustomAction.RunResult(success=False)
            cur_img = safe_screencap(context)
            if cur_img is None:
                return CustomAction.RunResult(success=False)
            switched, cur_sig = self._try_visible_cities(
                context,
                f"{prefix}Up{step}_",
                cur_img,
                excluded_cities,
                max_enemy_level=max_enemy_level,
            )
            if switched:
                return CustomAction.RunResult(success=True)
            if is_stopping(context):
                return CustomAction.RunResult(success=False)
            if cur_sig and cur_sig == last_sig:
                break
            last_sig = cur_sig

        print("[RegionalCombat] 所有符合条件的已解锁车站均已推进完毕或超过敌方等级上限，任务完成！", flush=True)
        return CustomAction.RunResult(success=False)


@AgentServer.custom_action("regional_combat_settle_next")
class RegionalCombatSettleNextAction(CustomAction):
    """Click settlement '下一步' via guarded_click and increment completed_runs."""

    @exit_on_network_restart(return_value=CustomAction.RunResult(success=True))
    def run(self, context: Context, argv: CustomAction.RunArg) -> CustomAction.RunResult:
        from agent.utils.input_guard import run_guarded_click

        state = _task_state(context, argv)
        cx, cy = _box_center(getattr(argv, "box", None), (1170, 610))
        ok = run_guarded_click(context, f"{argv.node_name}Guarded", cx, cy)
        if ok:
            state["completed_runs"] = int(state["completed_runs"]) + 1
            print(f"[RegionalCombat] 本轮已完成第 {state['completed_runs']} 场结算。", flush=True)
        return CustomAction.RunResult(success=ok)


@AgentServer.custom_action("regional_combat_handle_low_clarity")
class RegionalCombatHandleLowClarityAction(CustomAction):
    """Confirm into Clarity Recovery when medicine is enabled, or cancel and finish cleanly."""

    @exit_on_network_restart(return_value=CustomAction.RunResult(success=True))
    def run(self, context: Context, argv: CustomAction.RunArg) -> CustomAction.RunResult:
        params = _resolve_params(context, argv)
        use_medicine = bool(params.get("use_medicine", False))
        img = safe_screencap(context)
        btn_entries = (
            ocr_roi(context, img, f"{argv.node_name}Btns", REGIONAL_LOW_CLARITY_BTN_ROI)
            if img is not None
            else []
        )

        if use_medicine:
            confirm_pt = find_low_clarity_popup_button(btn_entries, kind="confirm") or REGIONAL_LOW_CLARITY_CONFIRM_POINT
            if not tap_point(context, f"{argv.node_name}Confirm", confirm_pt):
                return CustomAction.RunResult(success=False)
            sleep_with_stop(context, 0.8)
            return CustomAction.RunResult(success=not is_stopping(context))

        cancel_pt = find_low_clarity_popup_button(btn_entries, kind="cancel") or REGIONAL_LOW_CLARITY_CANCEL_POINT
        if not tap_point(context, f"{argv.node_name}Cancel", cancel_pt):
            return CustomAction.RunResult(success=False)
        sleep_with_stop(context, 0.6)
        _task_state(context, argv)["done"] = True
        print("[RegionalCombat] 澄明度不足且未开启体力恢复，已取消弹窗并结束任务。", flush=True)
        return CustomAction.RunResult(success=not is_stopping(context))


@AgentServer.custom_action("regional_combat_clarity_abort")
class RegionalCombatClarityAbortAction(CustomAction):
    """Close the Clarity Recovery screen if open and mark the current run as finished."""

    @exit_on_network_restart(return_value=CustomAction.RunResult(success=True))
    def run(self, context: Context, argv: CustomAction.RunArg) -> CustomAction.RunResult:
        img = safe_screencap(context)
        if img is not None:
            entries = ocr_roi(context, img, f"{argv.node_name}Check", (260, 200, 400, 220))
            if any("请选择恢复方式" in str(e.get("text") or "") for e in entries):
                tap_point(context, f"{argv.node_name}Back", CLARITY_BACK_POINT)
                sleep_with_stop(context, 0.6)
        _task_state(context, argv)["done"] = True
        print("[RegionalCombat] 澄明度恢复未开启或可用配额已耗尽，结束区域作战任务。", flush=True)
        return CustomAction.RunResult(success=not is_stopping(context))
