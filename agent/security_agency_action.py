from __future__ import annotations

from typing import Any

from maa.agent.agent_server import AgentServer
from maa.context import Context
from maa.custom_action import CustomAction
from maa.custom_recognition import CustomRecognition

from agent.utils.action_helpers import ocr_roi, parse_action_param, swipe_points, tap_point
from agent.utils.input_guard import safe_screencap, sleep_with_stop
from agent.utils.network_guard import exit_on_network_restart
from maa_resonance.logic.security_agency import (
    SECURITY_CITY_LIST_ROI,
    SECURITY_CITY_SWIPE_DOWN,
    SECURITY_CITY_SWIPE_UP,
    SECURITY_FIGHT_BTN_ROI,
    SECURITY_PROGRESS_ROI,
    SECURITY_REMOTE_MARKER_ROI,
    SECURITY_REMOTE_REWARD_ROI,
    SECURITY_REPUTATION_ROI,
    SECURITY_TABS_ROI,
    SECURITY_TAB_SWIPE,
    SECURITY_TITLE_ROI,
    find_start_combat_box,
    find_terminal_security_agency_go_point,
    has_remote_security_hub,
    has_security_agency_title,
    parse_expulsion_progress,
    parse_remote_city_cards,
    parse_reputation_level,
    parse_reputation_progress,
    select_unfinished_remote_cities,
    select_unfinished_tab_candidates,
    should_stop_for_reputation,
)

_ALL_100_VERIFIED_TASKS: set[int] = set()
_EXCLUDED_CITIES_BY_TASK: dict[int, set[str]] = {}


def _task_key(context: Context, argv: Any) -> int:
    task_detail = getattr(argv, "task_detail", None)
    task_id = getattr(task_detail, "task_id", None)
    if len(_ALL_100_VERIFIED_TASKS) > 64:
        _ALL_100_VERIFIED_TASKS.clear()
    if len(_EXCLUDED_CITIES_BY_TASK) > 64:
        _EXCLUDED_CITIES_BY_TASK.clear()
    return int(task_id) if task_id is not None else id(context.tasker)


def _parse_param(raw: Any) -> dict[str, Any]:
    return parse_action_param(raw)


def _ocr_roi(context: Context, image: Any, node_name: str, roi: tuple[int, int, int, int]) -> list[dict[str, Any]]:
    return ocr_roi(context, image, node_name, roi)


def _tap_point(context: Context, node_name: str, point: tuple[int, int]) -> bool:
    return tap_point(context, node_name, point)


def _swipe_points(
    context: Context,
    node_name: str,
    x1: int,
    y1: int,
    x2: int,
    y2: int,
    *,
    duration: int = 420,
) -> bool:
    return swipe_points(
        context,
        node_name,
        (int(x1), int(y1)),
        (int(x2), int(y2)),
        duration=duration,
        end_hold=150,
    )


def _try_switch_unfinished_tab(context: Context, node_name: str, image: Any, *, allow_swipe: bool = True) -> bool:
    def _try_visible(cur_img: Any, prefix: str) -> bool:
        tab_entries = _ocr_roi(context, cur_img, f"{prefix}ScanTabs", SECURITY_TABS_ROI)
        excluded_x: set[int] = set()
        for idx in range(4):
            candidates = select_unfinished_tab_candidates(tab_entries, excluded_x_centers=excluded_x)
            if not candidates:
                return False
            chosen = candidates[0]
            tx, ty = chosen["tap_point"]
            print(
                f"[SecurityAgency] 当前关卡驱逐进度已满 100%，尝试切换至下排关卡 "
                f"(x={chosen['center_x']}, 原进度={chosen['percent']}% -> tap=({tx}, {ty}))。",
                flush=True,
            )
            new_img = None
            for retry in range(2):
                if not _tap_point(context, f"{prefix}Tab{idx}_{retry}", (tx, ty)):
                    return False
                if not sleep_with_stop(context, 0.65):
                    return False
                new_img = safe_screencap(context)
                if new_img is None:
                    return False
                new_prog = parse_expulsion_progress(
                    _ocr_roi(context, new_img, f"{prefix}Prog{idx}_{retry}", SECURITY_PROGRESS_ROI)
                )
                if new_prog is not None and new_prog < 100:
                    print(f"[SecurityAgency] 切换关卡成功，当前驱逐进度 {new_prog}%。", flush=True)
                    return True
            excluded_x.add(int(chosen["center_x"]))
            tab_entries = _ocr_roi(context, new_img, f"{prefix}Rescan{idx}", SECURITY_TABS_ROI)
        return False

    if _try_visible(image, node_name):
        return True
    if not allow_swipe:
        return False

    x1, y1, x2, y2 = SECURITY_TAB_SWIPE
    if not _swipe_points(context, f"{node_name}TabBar", x1, y1, x2, y2):
        return False
    if not sleep_with_stop(context, 0.55):
        return False
    swiped_img = safe_screencap(context)
    if swiped_img is None:
        return False
    return _try_visible(swiped_img, f"{node_name}Swiped")


@AgentServer.custom_recognition("security_agency_reputation_reached")
class SecurityAgencyReputationReachedRecognition(CustomRecognition):
    """Stop Security Agency farming once bottom-left city reputation reaches target_level."""

    def analyze(
        self,
        context: Context,
        argv: CustomRecognition.AnalyzeArg,
    ) -> CustomRecognition.AnalyzeResult:
        params = _parse_param(getattr(argv, "custom_recognition_param", None))
        raw_target = params.get("target_level", 1)
        try:
            target_level = int(raw_target)
        except (TypeError, ValueError):
            target_level = 1

        if target_level <= 0:
            return CustomRecognition.AnalyzeResult(box=None, detail={"ok": False, "reason": "unlimited"})

        image = getattr(argv, "image", None)
        if image is None:
            return CustomRecognition.AnalyzeResult(box=None, detail={"ok": False})

        title_entries = _ocr_roi(context, image, f"{argv.node_name}Title", SECURITY_TITLE_ROI)
        if not has_security_agency_title(title_entries):
            return CustomRecognition.AnalyzeResult(box=None, detail={"ok": False, "reason": "not_security_page"})

        fight_entries = _ocr_roi(context, image, f"{argv.node_name}FightBtn", SECURITY_FIGHT_BTN_ROI)
        if find_start_combat_box(fight_entries) is None:
            return CustomRecognition.AnalyzeResult(box=None, detail={"ok": False, "reason": "fight_btn_hidden"})

        rep_entries = _ocr_roi(context, image, f"{argv.node_name}Reputation", SECURITY_REPUTATION_ROI)
        level = parse_reputation_level(rep_entries)
        progress = parse_reputation_progress(rep_entries)
        if should_stop_for_reputation(level, target_level):
            progress_str = f"{progress[0]}/{progress[1]}" if progress else "unknown"
            print(
                f"[SecurityAgency] 城市声望已达 {level} 级（目标 {target_level} 级，进度 {progress_str}），停止刷取。",
                flush=True,
            )
            return CustomRecognition.AnalyzeResult(
                box=(94, 656, 116, 22),
                detail={
                    "ok": True,
                    "level": level,
                    "target_level": target_level,
                    "progress": list(progress) if progress else None,
                },
            )

        return CustomRecognition.AnalyzeResult(
            box=None,
            detail={
                "ok": False,
                "level": level,
                "target_level": target_level,
                "progress": list(progress) if progress else None,
            },
        )


@AgentServer.custom_recognition("security_agency_progress_complete")
class SecurityAgencyProgressCompleteRecognition(CustomRecognition):
    """Detect when local Security Agency top-right expulsion progress reaches 100%."""

    def analyze(
        self,
        context: Context,
        argv: CustomRecognition.AnalyzeArg,
    ) -> CustomRecognition.AnalyzeResult:
        params = _parse_param(getattr(argv, "custom_recognition_param", None))
        stop_when_all_complete = bool(params.get("stop_when_all_complete", False))
        image = getattr(argv, "image", None)
        if image is None:
            return CustomRecognition.AnalyzeResult(box=None, detail={"ok": False})

        title_entries = _ocr_roi(context, image, f"{argv.node_name}Title", SECURITY_TITLE_ROI)
        if not has_security_agency_title(title_entries):
            return CustomRecognition.AnalyzeResult(box=None, detail={"ok": False, "reason": "not_local_security_page"})

        fight_entries = _ocr_roi(context, image, f"{argv.node_name}FightBtn", SECURITY_FIGHT_BTN_ROI)
        if find_start_combat_box(fight_entries) is None:
            return CustomRecognition.AnalyzeResult(box=None, detail={"ok": False, "reason": "fight_btn_hidden"})

        prog_entries = _ocr_roi(context, image, f"{argv.node_name}Progress", SECURITY_PROGRESS_ROI)
        progress_pct = parse_expulsion_progress(prog_entries)
        if progress_pct is None or progress_pct < 100:
            return CustomRecognition.AnalyzeResult(
                box=None,
                detail={"ok": False, "progress_pct": progress_pct},
            )

        tab_entries = _ocr_roi(context, image, f"{argv.node_name}Tabs", SECURITY_TABS_ROI)
        unfinished = select_unfinished_tab_candidates(tab_entries)
        tkey = _task_key(context, argv)
        if unfinished:
            _ALL_100_VERIFIED_TASKS.discard(tkey)
            return CustomRecognition.AnalyzeResult(
                box=(1128, 189, 109, 59),
                detail={
                    "ok": True,
                    "progress_pct": progress_pct,
                    "unfinished_count": len(unfinished),
                },
            )

        if not stop_when_all_complete and tkey in _ALL_100_VERIFIED_TASKS:
            return CustomRecognition.AnalyzeResult(
                box=None,
                detail={"ok": False, "reason": "all_100_already_verified"},
            )

        return CustomRecognition.AnalyzeResult(
            box=(1128, 189, 109, 59),
            detail={
                "ok": True,
                "progress_pct": progress_pct,
                "unfinished_count": 0,
            },
        )


@AgentServer.custom_action("security_agency_switch_tab")
class SecurityAgencySwitchTabAction(CustomAction):
    """Switch to a bottom mission tab with <100% expulsion progress on the local Security Agency page."""

    @exit_on_network_restart(return_value=True)
    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        params = _parse_param(getattr(argv, "custom_action_param", None))
        stop_when_all_complete = bool(params.get("stop_when_all_complete", False))
        tkey = _task_key(context, argv)

        image = safe_screencap(context)
        if image is None:
            return False
        if _try_switch_unfinished_tab(context, argv.node_name, image, allow_swipe=True):
            _ALL_100_VERIFIED_TASKS.discard(tkey)
            return True
        if context.tasker.stopping:
            return False

        _ALL_100_VERIFIED_TASKS.add(tkey)
        if stop_when_all_complete:
            print("[SecurityAgency] 所有可切换关卡驱逐进度均已达 100%，按配置停止刷取。", flush=True)
            return False

        print(
            "[SecurityAgency] 所有关卡驱逐进度均已达 100%，继续刷取当前关卡以累计城市声望。",
            flush=True,
        )
        fight_img = safe_screencap(context)
        if fight_img is None:
            return False
        fight_entries = _ocr_roi(context, fight_img, f"{argv.node_name}FightBtn", SECURITY_FIGHT_BTN_ROI)
        fight_box = find_start_combat_box(fight_entries)
        if fight_box is not None:
            fx = int(round(fight_box[0] + fight_box[2] / 2.0))
            fy = int(round(fight_box[1] + fight_box[3] / 2.0))
            if not _tap_point(context, f"{argv.node_name}FallbackFight", (fx, fy)):
                return False
            if not sleep_with_stop(context, 0.8):
                return False
        return True


@AgentServer.custom_recognition("security_agency_remote_needs_advance")
class SecurityAgencyRemoteNeedsAdvanceRecognition(CustomRecognition):
    """On the remote Security Agency hub, trigger tab/city switching whenever current target is 100% or locked."""

    def analyze(
        self,
        context: Context,
        argv: CustomRecognition.AnalyzeArg,
    ) -> CustomRecognition.AnalyzeResult:
        image = getattr(argv, "image", None)
        if image is None:
            return CustomRecognition.AnalyzeResult(box=None, detail={"ok": False})

        marker_entries = _ocr_roi(context, image, f"{argv.node_name}Marker", SECURITY_REMOTE_MARKER_ROI)
        reward_entries = _ocr_roi(context, image, f"{argv.node_name}Reward", SECURITY_REMOTE_REWARD_ROI)
        if not has_remote_security_hub(marker_entries, reward_entries):
            return CustomRecognition.AnalyzeResult(box=None, detail={"ok": False, "reason": "not_remote_hub"})

        fight_entries = _ocr_roi(context, image, f"{argv.node_name}FightBtn", SECURITY_FIGHT_BTN_ROI)
        fight_box = find_start_combat_box(fight_entries)
        prog_entries = _ocr_roi(context, image, f"{argv.node_name}Progress", SECURITY_PROGRESS_ROI)
        progress_pct = parse_expulsion_progress(prog_entries)

        if fight_box is not None and progress_pct is not None and progress_pct < 100:
            return CustomRecognition.AnalyzeResult(
                box=None,
                detail={"ok": False, "reason": "ready_to_fight", "progress_pct": progress_pct},
            )

        return CustomRecognition.AnalyzeResult(
            box=(116, 659, 76, 23),
            detail={
                "ok": True,
                "has_fight_btn": fight_box is not None,
                "progress_pct": progress_pct,
            },
        )


@AgentServer.custom_action("security_agency_remote_advance")
class SecurityAgencyRemoteAdvanceAction(CustomAction):
    """Switch tabs and scroll/switch cities on the remote Security Agency hub until all cities reach 100%."""

    def _try_switch_visible_cities(
        self,
        context: Context,
        node_name: str,
        image: Any,
        excluded_cities: set[str],
    ) -> tuple[bool, tuple[str, ...]]:
        city_entries = _ocr_roi(context, image, f"{node_name}Cities", SECURITY_CITY_LIST_ROI)
        all_cards = parse_remote_city_cards(city_entries)
        signature = tuple(str(c["city_name"]) for c in all_cards)

        candidates = select_unfinished_remote_cities(city_entries, excluded_cities=excluded_cities)
        for idx, card in enumerate(candidates):
            if context.tasker.stopping:
                return False, signature
            city_name = str(card["city_name"])
            tx, ty = card["tap_point"]
            print(
                f"[SecurityAgency] 切换远程城市「{city_name}」（列表进度 {card['percent']}% -> tap=({tx}, {ty})）。",
                flush=True,
            )
            if not _tap_point(context, f"{node_name}City{idx}", (tx, ty)):
                return False, signature
            if not sleep_with_stop(context, 0.65):
                return False, signature
            cur_img = safe_screencap(context)
            if cur_img is None:
                return False, signature

            fight_box = find_start_combat_box(
                _ocr_roi(context, cur_img, f"{node_name}Fight{idx}", SECURITY_FIGHT_BTN_ROI)
            )
            if fight_box is None:
                print(
                    f"[SecurityAgency] 城市「{city_name}」未显示「前往作战」（可能尚未解锁远程刷取），跳过。",
                    flush=True,
                )
                excluded_cities.add(city_name)
                continue

            cur_prog = parse_expulsion_progress(
                _ocr_roi(context, cur_img, f"{node_name}CityProg{idx}", SECURITY_PROGRESS_ROI)
            )
            if cur_prog is not None and cur_prog < 100:
                print(f"[SecurityAgency] 已切至「{city_name}」，当前关卡驱逐进度 {cur_prog}%。", flush=True)
                return True, signature

            if _try_switch_unfinished_tab(context, f"{node_name}CityTab{idx}", cur_img, allow_swipe=True):
                return True, signature
            if context.tasker.stopping:
                return False, signature

            excluded_cities.add(city_name)

        return False, signature

    @exit_on_network_restart(return_value=True)
    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        tkey = _task_key(context, argv)
        excluded_cities = _EXCLUDED_CITIES_BY_TASK.setdefault(tkey, set())

        image = safe_screencap(context)
        if image is None:
            return False

        # Ensure the 驱逐任务 tab is active if 前往作战 was hidden because 悬赏任务 was selected.
        fight_box = find_start_combat_box(_ocr_roi(context, image, f"{argv.node_name}Fight0", SECURITY_FIGHT_BTN_ROI))
        if fight_box is None:
            if not _tap_point(context, f"{argv.node_name}ExpulsionTab", (154, 670)):
                return False
            if not sleep_with_stop(context, 0.55):
                return False
            image = safe_screencap(context)
            if image is None:
                return False
            fight_box = find_start_combat_box(
                _ocr_roi(context, image, f"{argv.node_name}Fight1", SECURITY_FIGHT_BTN_ROI)
            )

        if fight_box is not None:
            cur_prog = parse_expulsion_progress(
                _ocr_roi(context, image, f"{argv.node_name}Prog0", SECURITY_PROGRESS_ROI)
            )
            if cur_prog is not None and cur_prog < 100:
                return True
            if _try_switch_unfinished_tab(context, f"{argv.node_name}Tab", image, allow_swipe=True):
                return True
            if context.tasker.stopping:
                return False

        # Current city has all tabs at 100% (or is locked); scan current window and scroll down.
        switched, last_sig = self._try_switch_visible_cities(context, f"{argv.node_name}Cur", image, excluded_cities)
        if switched:
            return True
        if context.tasker.stopping:
            return False

        x1, y1, x2, y2 = SECURITY_CITY_SWIPE_DOWN
        for step in range(6):
            if not _swipe_points(context, f"{argv.node_name}Down{step}", x1, y1, x2, y2, duration=450):
                return False
            if not sleep_with_stop(context, 0.55):
                return False
            cur_img = safe_screencap(context)
            if cur_img is None:
                return False
            switched, cur_sig = self._try_switch_visible_cities(
                context, f"{argv.node_name}Down{step}", cur_img, excluded_cities
            )
            if switched:
                return True
            if context.tasker.stopping:
                return False
            if cur_sig and cur_sig == last_sig:
                break
            last_sig = cur_sig

        # Also sweep back up once in case the list started partway down.
        ux1, uy1, ux2, uy2 = SECURITY_CITY_SWIPE_UP
        for step in range(5):
            if not _swipe_points(context, f"{argv.node_name}Up{step}", ux1, uy1, ux2, uy2, duration=450):
                return False
            if not sleep_with_stop(context, 0.55):
                return False
            cur_img = safe_screencap(context)
            if cur_img is None:
                return False
            switched, cur_sig = self._try_switch_visible_cities(
                context, f"{argv.node_name}Up{step}", cur_img, excluded_cities
            )
            if switched:
                return True
            if context.tasker.stopping:
                return False
            if cur_sig and cur_sig == last_sig:
                break
            last_sig = cur_sig

        print("[SecurityAgency] 所有已解锁城市的驱逐进度均已达到 100%，全自动铁安局任务完成！", flush=True)
        return False


@AgentServer.custom_recognition("security_agency_terminal_card")
class SecurityAgencyTerminalCardRecognition(CustomRecognition):
    """Detect the 铁安局 card inside the 作战终端 hub screen."""

    def analyze(
        self,
        context: Context,
        argv: CustomRecognition.AnalyzeArg,
    ) -> CustomRecognition.AnalyzeResult:
        image = getattr(argv, "image", None)
        if image is None:
            return CustomRecognition.AnalyzeResult(box=None, detail={"ok": False})

        entries = _ocr_roi(context, image, f"{argv.node_name}Scan", (0, 0, 1280, 720))
        point = find_terminal_security_agency_go_point(entries)
        if point is None:
            return CustomRecognition.AnalyzeResult(box=None, detail={"ok": False})

        px, py = point
        return CustomRecognition.AnalyzeResult(
            box=(max(0, px - 40), max(0, py - 20), 80, 40),
            detail={"ok": True, "tap_point": [px, py]},
        )
