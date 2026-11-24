"""Read-only CustomAction for Reforming Center / Prison Planning (整顿中心只读扫描与执行规划)."""
from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import time
import traceback
from typing import Any, Sequence
import webbrowser

from maa.agent.agent_server import AgentServer
from maa.context import Context
from maa.custom_action import CustomAction

from agent.utils.action_helpers import ocr_roi, parse_action_param, poll_screen, swipe_points, tap_point
from agent.utils.input_guard import safe_screencap, sleep_with_stop
from agent.utils.lobby_nav import is_stopping, open_drawer, return_to_lobby
from agent.utils.mall_nav import CITY_LANDMARKS_ROI, LOBBY_VISIT_CITY_ROI, read_drawer_uid
from agent.utils.network_guard import NetworkRestartedToLobbyError, retry_on_network_restart
from maa_resonance.logic.daily_routine import (
    DRAWER_CLOSE_POINT,
    DRAWER_GRID_ROI,
    DRAWER_SCROLL_UP_SWIPE,
    find_drawer_entry_point,
)
from maa_resonance.logic.manual_trade import find_account_config
from maa_resonance.logic.paths import ROOT_PATH
from maa_resonance.logic.planning import (
    ALL_PRISON_AUTO_MODULES,
    AccountSnapshot,
    FINANCE_DISMISS_POINT,
    FINANCE_MODAL_CHECK_ROI,
    FINANCE_TOGGLE_POINT,
    ORDERS_BODY_ROI,
    ORDERS_DELETE_BTN_POINT,
    ORDERS_DELETE_BTN_ROI,
    ORDERS_DELIVER_BUTTON_ROI,
    ORDERS_DELIVER_POINT,
    ORDERS_FOYER_DAILY_POINT,
    ORDERS_HEADER_ROI,
    ORDERS_RIGHT_SLOTS_ROI,
    ORDERS_SLOT_POINTS,
    POWER_BUBBLE_BUILD_FALLBACK,
    POWER_TABS_OCR_ROI,
    PRISON_BACK_POINT,
    PRISON_BOTTOM_DOCK_ROI,
    PRISON_CHECKIN_CONFIRM_POINT,
    PRISON_CHECKIN_SELECT_ALL_POINT,
    PRISON_CHECKIN_STATUS_ROI,
    PRISON_DOCK_ORDERS_FALLBACK,
    PRISON_DOCK_SHOP_FALLBACK,
    PRISON_DOCK_WAREHOUSE_FALLBACK,
    PRISON_OVERVIEW_GRID_ROI,
    PRISON_PAN_SWIPES,
    PRISON_REWARD_DISMISS_POINT,
    PRISON_RIGHT_WING_PAN_SWIPE,
    PRISON_ROSTER_CHECKIN_BTN_POINT,
    PRISON_ROSTER_CHECKIN_BTN_ROI,
    PRISON_TODO_BTN_POINT,
    PRISON_TODO_BTN_ROI,
    PRISON_TODO_CLAIM_ROI,
    PRISON_TOP_BAR_ROI,
    PRISON_TOP_PRISONER_BAR_POINT,
    PRISON_UPPER_WING_PAN_SWIPE,
    PROD_CARDS_SCROLL_LEFT_SWIPE,
    PROD_CONFIRM_START_POINT,
    PROD_DUR_2H_POINT,
    PROD_DUR_4H_POINT,
    PROD_DUR_8H_POINT,
    PROD_READY_PANEL_ROI,
    PROD_RECIPE_CARDS_ROI,
    PROD_SELECT_ALL_ROI,
    PrisonActionOutcome,
    PrisonDiagnosticRecorder,
    PrisonExecutionPlan,
    PrisonOrder,
    PrisonPlanOptions,
    PrisonPlanReport,
    PrisonRunReceipt,
    PrisonRuntimeConfig,
    RAW_PREDEPOSIT_BAL_ROI,
    RAW_PREDEPOSIT_BTN_POINT,
    RAW_PREDEPOSIT_CANCEL_POINT,
    RAW_PREDEPOSIT_CONFIRM_POINT,
    RAW_PREDEPOSIT_MODAL_QTY_ROI,
    RAW_PREDEPOSIT_SLIDER_Y,
    RAW_PROD_ACTION_ROI,
    RAW_PROD_PICKER_COUNT_ROI,
    RAW_PROD_PICKER_CONFIRM_POINT,
    RAW_PROD_PICKER_GRID_ROI,
    RAW_PROD_SELECT_PRISONER_POINT,
    RAW_PROD_START_POINT,
    RAW_PROD_WORKERS_ROI,
    ROOM_BUBBLE_BOTTOM_FALLBACK,
    ROOM_BUBBLE_ROI,
    ROOM_BUBBLE_TOP_FALLBACK,
    ROOM_BUILD_BUTTON_ROI,
    ROOM_BUILD_CONFIRM_POINT,
    ROOM_BUILD_PANEL_ROI,
    ROOM_UNZOOM_LEFT_COL_POINT,
    ROOM_UNZOOM_RIGHT_COL_POINT,
    SHOP_BODY_ROI,
    SHOP_COINS_ROI,
    SHOP_CONFIRM_MODAL_ROI,
    SHOP_ITEMS_SCROLL_DOWN_SWIPE,
    SHOP_MODAL_CANCEL_POINT,
    SHOP_TAB_ITEMS_POINT,
    SHOP_TAB_RECIPES_POINT,
    SHOP_WORK_TICKETS_ROI,
    WAREHOUSE_BODY_ROI,
    WAREHOUSE_BUY_CARD_POINT,
    WAREHOUSE_FIN_EXPAND_POINT,
    WAREHOUSE_MODAL_CANCEL_POINT,
    WAREHOUSE_MODAL_CONFIRM_POINT,
    WAREHOUSE_MODAL_PLUS1_POINT,
    WAREHOUSE_MODAL_TABS_ROI,
    WAREHOUSE_OVERLAY_EXIT_POINT,
    WAREHOUSE_RAW_EXPAND_POINT,
    WAREHOUSE_TOP_BAR_ROI,
    WORKSHOP_1_FALLBACK,
    WORKSHOP_2_FALLBACK,
    WORKSHOP_ENTER_EDIT_POINT,
    WORKSHOP_ENTER_PROD_POINT,
    WORKSHOP_INTERIOR_CHECK_ROI,
    WS_EDIT_APPLY_POINT,
    WS_EDIT_LEADER_TOP_ROI,
    WS_EDIT_MACHINE_COST_ROI,
    WS_EDIT_MACHINE_SLOT_CENTERS,
    WS_EDIT_MACHINE_UPGRADE_POINT,
    WS_EDIT_MACHINE_UPGRADE_ROI,
    WS_EDIT_PANEL_CHECK_ROI,
    WS_EDIT_QUICK_TEAM_POINT,
    WS_EDIT_SET_LEADER_POINT,
    WS_EDIT_SET_LEADER_ROI,
    build_prison_execution_plan,
    build_semi_auto_guidance,
    compute_predeposit_slider_x,
    detect_finance_auto_refill_state,
    evaluate_black_moon_order,
    find_all_production_recipe_card_points,
    find_city_prison_npc_point,
    find_dock_button_point,
    find_idle_prisoner_card_points,
    find_modal_confirm_button_point,
    find_production_recipe_card_point,
    find_production_select_all_point,
    find_room_bubble_point,
    find_todo_claim_button_points,
    find_weekly_orders_tab_point,
    format_mxu_plain_summary,
    format_planning_report_html,
    format_prison_plan_markdown,
    has_unset_workshop_leader,
    has_warehouse_left_coin_price,
    has_workshop_leader_set,
    is_exchange_shop_entries,
    is_orders_foyer_entries,
    is_orders_screen_entries,
    is_prison_overview_entries,
    is_prison_room_zoomed_entries,
    is_warehouse_screen_entries,
    load_account_snapshot,
    merge_prison_grid_scans,
    parse_drawer_wallet,
    parse_exchange_shop_item_rows,
    parse_exchange_shop_recipe_rows,
    parse_exchange_shop_top_bar,
    parse_orders_screen,
    parse_predeposit_balance,
    parse_predeposit_modal_qty,
    parse_prison_grid_buildings,
    parse_prison_top_bar,
    parse_prisoner_checkin_counts,
    parse_production_ready_panel,
    parse_raw_workshop_prod_status,
    parse_room_build_panel,
    parse_single_order_card,
    parse_warehouse_modal_remaining,
    parse_warehouse_screen,
    parse_workshop_machine_upgrade_cost,
    plan_prison,
    plan_prisoner_worker_allocation,
    resolve_prison_runtime_config,
    save_account_snapshot_sections,
    verify_power_room_upgrade_tab_safe,
    verify_warehouse_coins_tab_safe,
)
from maa_resonance.logic.planning.prison_scanner import (
    LOCKED_HINTS,
    REQUIREMENT_LABEL_HINTS,
    _clean_text,
    _merge_horizontal_adjacent,
)

PRISON_PLAN_ATTACH_NODES: tuple[str, ...] = (
    "PrisonPlanOptExecMode",
    "PrisonPlanOptAutoScope",
    "PrisonPlanOptEnabledModules",
    "PrisonPlanOptReserveCoins",
    "PrisonPlanOptCustomReserveCoins",
    "PrisonPlanOptScanSubpages",
    "PrisonPlanOptHuashiStrategy",
    "PrisonPlanOptPlayerLevel",
    "PrisonPlanOptAutoOpenReport",
    "PrisonPlanOptProdDuration",
    "PrisonPlanOptRawWorkerMode",
    "PrisonPlanOptWarehouseBatchCap",
    "PrisonPlanOptCoreUpgradeCap",
    "PrisonPlanOptDebugExport",
)

# 慢节奏稳定操作参数（优先保证点准、等稳、闭环核实）
SWIPE_DURATION_MS: int = 500
SWIPE_END_HOLD_MS: int = 180
SWIPE_SETTLE_DELAY: float = 0.95
STEP_TAP_DELAY: float = 0.35
SLOT_SWITCH_DELAY: float = 0.85
POST_CONFIRM_DELAY: float = 1.35
PANEL_POLL_INITIAL: float = 1.2
PANEL_POLL_INTERVAL: float = 0.55
PANEL_POLL_CHECKS: int = 5
MAX_CORE_UPGRADES_PER_RUN: int = 3
MAX_WAREHOUSE_BATCHES_PER_RUN: int = 2


def _resolve_plan_params(context: Context, argv: Any) -> dict[str, Any]:
    merged = dict(parse_action_param(getattr(argv, "custom_action_param", None)))
    get_node_data = getattr(context, "get_node_data", None)
    if callable(get_node_data):
        for node_name in PRISON_PLAN_ATTACH_NODES:
            try:
                node_data = get_node_data(node_name)
            except Exception:
                node_data = None
            if isinstance(node_data, dict) and isinstance(node_data.get("attach"), dict):
                merged.update(node_data["attach"])
    return merged


def _entry_center(entry: dict[str, Any]) -> tuple[int, int] | None:
    if "center_x" in entry and "center_y" in entry:
        try:
            return int(round(float(entry["center_x"]))), int(round(float(entry["center_y"])))
        except (TypeError, ValueError):
            pass
    box = entry.get("box")
    if isinstance(box, (list, tuple)) and len(box) >= 4:
        try:
            return int(round(int(box[0]) + int(box[2]) / 2.0)), int(round(int(box[1]) + int(box[3]) / 2.0))
        except (TypeError, ValueError):
            return None
    return None


def _account_config_path_for_uid(uid: str) -> Path:
    safe_uid = "".join(ch for ch in str(uid or "").strip() if ch.isalnum() or ch in {"_", "-"})
    if not safe_uid:
        safe_uid = "unknown"
    return ROOT_PATH / "config" / "accounts" / f"{safe_uid}.json"


def _poll_prison_overview(context: Context, prefix: str, *, initial_delay: float = 1.4, max_checks: int = 5) -> tuple[bool, bool]:
    """轮询等待进入整顿中心总览，返回 (entered, aborted)。"""

    def _check_prison_open(frame: Any, idx: int) -> bool | None:
        top = ocr_roi(context, frame, f"{prefix}OpenTop{idx}", PRISON_TOP_BAR_ROI)
        dock = ocr_roi(context, frame, f"{prefix}OpenDock{idx}", PRISON_BOTTOM_DOCK_ROI)
        if is_prison_overview_entries(top, dock):
            return True
        return None

    _, entered, aborted = poll_screen(
        context,
        _check_prison_open,
        initial_delay=initial_delay,
        interval=0.5,
        max_checks=max_checks,
        screencap_fn=safe_screencap,
        sleep_fn=sleep_with_stop,
    )
    return bool(entered), bool(aborted)


def _find_drawer_prison_point_with_scroll(
    context: Context,
    prefix: str,
    drawer_entries: list[dict[str, Any]],
) -> tuple[int, int] | None:
    """在已打开的左抽屉内查找「整顿中心」入口，必要时上下轻滑抽屉网格。"""
    pt = find_drawer_entry_point(drawer_entries, ("整顿中心",))
    if pt is not None:
        return pt

    scroll_swipes = (
        ("ScrollDown", (350, 620), (350, 390)),
        ("ScrollUp", (DRAWER_SCROLL_UP_SWIPE[0], DRAWER_SCROLL_UP_SWIPE[1]), (DRAWER_SCROLL_UP_SWIPE[2], DRAWER_SCROLL_UP_SWIPE[3])),
    )
    for tag, start_pt, end_pt in scroll_swipes:
        if not swipe_points(context, f"{prefix}{tag}", start_pt, end_pt, duration=400, end_hold=100):
            return None
        if not sleep_with_stop(context, 0.7):
            return None
        img = safe_screencap(context)
        if img is None:
            return None
        entries = ocr_roi(context, img, f"{prefix}Grid{tag}", DRAWER_GRID_ROI)
        pt = find_drawer_entry_point(entries, ("整顿中心",))
        if pt is not None:
            return pt
    return None


def _overview_state(context: Context, frame: Any, prefix: str) -> tuple[bool, bool]:
    """复用顶栏与底栏 OCR 判定当前画面状态，返回 (is_overview, is_room_zoomed)。"""
    top = ocr_roi(context, frame, f"{prefix}Top", PRISON_TOP_BAR_ROI)
    dock = ocr_roi(context, frame, f"{prefix}Dock", PRISON_BOTTOM_DOCK_ROI)
    return is_prison_overview_entries(top, dock), is_prison_room_zoomed_entries(top, dock)


def _is_on_prison_overview(context: Context, frame: Any, prefix: str) -> bool:
    """复用顶栏与底栏 OCR 判定当前画面是否仍位于整顿中心总览。"""
    is_ov, _ = _overview_state(context, frame, prefix)
    return is_ov


def _unzoom_room_to_overview(
    context: Context,
    prefix: str,
    unzoom_point: tuple[int, int] = ROOM_UNZOOM_RIGHT_COL_POINT,
) -> bool:
    """从房间放大聚焦态点击空白处退回正常总览，绝不盲点左上角返回按钮。"""
    alt_pt = ROOM_UNZOOM_RIGHT_COL_POINT if unzoom_point == ROOM_UNZOOM_LEFT_COL_POINT else ROOM_UNZOOM_LEFT_COL_POINT
    for tap_name, chk_name, pt in (
        (f"{prefix}Unzoom", f"{prefix}Chk2", unzoom_point),
        (f"{prefix}UnzoomAlt", f"{prefix}Chk3", alt_pt),
    ):
        if not tap_point(context, tap_name, pt):
            return False
        if not sleep_with_stop(context, 1.05):
            return False
        frame = safe_screencap(context)
        if frame is not None and _is_on_prison_overview(context, frame, chk_name):
            return True
    return False


def _navigate_lobby_to_prison(context: Context, prefix: str) -> tuple[bool, str, dict[str, int], str]:
    """回到大厅打开左抽屉读取 UID/资产，优先点击抽屉「整顿中心」远程直达，失败再回退进城。"""
    if not return_to_lobby(context, f"{prefix}ToLobby"):
        return False, "unknown", {}, "stopped" if is_stopping(context) else "not_in_lobby"

    uid = "unknown"
    drawer_wallet: dict[str, int] = {}
    img = safe_screencap(context)
    if img is None:
        return False, uid, drawer_wallet, "stopped"

    drawer_img, drawer_entries = open_drawer(context, f"{prefix}Drawer")
    if drawer_img is not None:
        read_uid = read_drawer_uid(context, f"{prefix}Uid", drawer_img)
        if read_uid:
            uid = read_uid
        drawer_wallet = parse_drawer_wallet(drawer_entries)

        drawer_prison_pt = _find_drawer_prison_point_with_scroll(context, f"{prefix}DrawerPrison", drawer_entries)
        if drawer_prison_pt is not None:
            if not tap_point(context, f"{prefix}TapDrawerPrison", drawer_prison_pt):
                return False, uid, drawer_wallet, "stopped"
            entered, aborted = _poll_prison_overview(context, f"{prefix}DrawerEnter")
            if aborted:
                return False, uid, drawer_wallet, "stopped"
            if entered:
                return True, uid, drawer_wallet, "ok_drawer"
            return_to_lobby(context, f"{prefix}DrawerPrisonTimeoutBack")
            return False, uid, drawer_wallet, "prison_enter_timeout"

        tap_point(context, f"{prefix}CloseDrawer", DRAWER_CLOSE_POINT)
        if not sleep_with_stop(context, 0.7):
            return False, uid, drawer_wallet, "stopped"
        img = safe_screencap(context)
        if img is None:
            return False, uid, drawer_wallet, "stopped"
    else:
        _acc_path, acc_data = find_account_config()
        if isinstance(acc_data, dict) and str(acc_data.get("uid") or "").strip():
            uid = str(acc_data["uid"]).strip()

    visit_entries = ocr_roi(context, img, f"{prefix}VisitCity", LOBBY_VISIT_CITY_ROI)
    visit_pt: tuple[int, int] | None = None
    for entry in visit_entries:
        if isinstance(entry, dict) and "访问城市" in str(entry.get("text") or "").replace(" ", ""):
            visit_pt = _entry_center(entry)
            if visit_pt is not None:
                break
    if visit_pt is None:
        return False, uid, drawer_wallet, "not_at_city"

    if not tap_point(context, f"{prefix}TapVisit", visit_pt):
        return False, uid, drawer_wallet, "stopped"

    def _check_city_landmarks(frame: Any, idx: int) -> list[dict[str, Any]] | None:
        entries = ocr_roi(context, frame, f"{prefix}City{idx}", CITY_LANDMARKS_ROI)
        joined = "".join(str(e.get("text") or "") for e in entries if isinstance(e, dict))
        if any(kw in joined for kw in ("整顿中心", "黑月", "商会", "交易所", "铁安局", "市政厅")):
            return entries
        return None

    _city_img, city_entries, aborted = poll_screen(
        context,
        _check_city_landmarks,
        initial_delay=1.3,
        interval=0.5,
        max_checks=4,
        screencap_fn=safe_screencap,
        sleep_fn=sleep_with_stop,
    )
    if aborted:
        return False, uid, drawer_wallet, "stopped"
    if not city_entries:
        return_to_lobby(context, f"{prefix}CityTimeoutBack")
        return False, uid, drawer_wallet, "city_load_timeout"

    npc_pt = find_city_prison_npc_point(city_entries)
    if npc_pt is None:
        return_to_lobby(context, f"{prefix}NotYunxiuBack")
        return False, uid, drawer_wallet, "not_at_yunxiuqiao"

    if not tap_point(context, f"{prefix}TapPrisonNpc", npc_pt):
        return False, uid, drawer_wallet, "stopped"

    entered, aborted = _poll_prison_overview(context, prefix)
    if aborted:
        return False, uid, drawer_wallet, "stopped"
    if not entered:
        return_to_lobby(context, f"{prefix}PrisonTimeoutBack")
        return False, uid, drawer_wallet, "prison_enter_timeout"
    return True, uid, drawer_wallet, "ok_city"


def _back_to_prison_overview(context: Context, prefix: str) -> bool:
    """从仓库/订单等子界面点返回按钮并等待回到整顿中心总览（兼容双跳门面页与房间放大态退回）。"""
    for attempt in range(3):
        if not tap_point(context, f"{prefix}Back{attempt}", PRISON_BACK_POINT):
            return False

        def _check_overview(frame: Any, idx: int) -> str | None:
            top = ocr_roi(context, frame, f"{prefix}BackTop{attempt}_{idx}", PRISON_TOP_BAR_ROI)
            dock = ocr_roi(context, frame, f"{prefix}BackDock{attempt}_{idx}", PRISON_BOTTOM_DOCK_ROI)
            if is_prison_overview_entries(top, dock):
                return "overview"
            if is_prison_room_zoomed_entries(top, dock):
                return "zoomed"
            return None

        _, state_kind, aborted = poll_screen(
            context,
            _check_overview,
            initial_delay=1.25,
            interval=0.55,
            max_checks=4,
            screencap_fn=safe_screencap,
            sleep_fn=sleep_with_stop,
        )
        if aborted:
            return False
        if state_kind == "overview":
            return True
        if state_kind == "zoomed":
            if _unzoom_room_to_overview(context, f"{prefix}ZoomExit{attempt}", ROOM_UNZOOM_RIGHT_COL_POINT):
                return True
            if is_stopping(context):
                return False
    return False


def _ensure_on_prison_overview(context: Context, prefix: str) -> bool:
    """确保当前已停在整顿中心总览：已在总览直接放行，处于房间放大态先点空白解除，否则尝试返回总览。"""
    frame = safe_screencap(context)
    if frame is None:
        return False
    is_ov, is_zoomed = _overview_state(context, frame, f"{prefix}OvChk")
    if is_ov:
        return True
    if is_zoomed and _unzoom_room_to_overview(context, f"{prefix}OvUnzoom", ROOM_UNZOOM_RIGHT_COL_POINT):
        return True
    return _back_to_prison_overview(context, f"{prefix}OvBack")


def _merge_scanned_prison_and_wallet(
    previous: AccountSnapshot,
    *,
    uid: str,
    top_data: dict[str, Any],
    grid_data: dict[str, Any],
    warehouse_data: dict[str, Any],
    orders_scanned: bool,
    scanned_orders: list[PrisonOrder],
    drawer_wallet: dict[str, int] | None = None,
    drawer_clarity: int | None = None,
    shop_data: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    wallet_dict = previous.wallet.model_dump(mode="python")
    merged_drawer = dict(drawer_wallet or {})
    if drawer_clarity is not None and merged_drawer.get("clarity_estimate") is None:
        merged_drawer["clarity_estimate"] = int(drawer_clarity)
    if merged_drawer.get("clarity_estimate") is not None:
        wallet_dict["clarity_estimate"] = int(merged_drawer["clarity_estimate"])
    for source in (merged_drawer, top_data, warehouse_data, shop_data or {}):
        if source.get("coins") is not None:
            wallet_dict["coins"] = int(source["coins"])
        if source.get("huashi") is not None:
            wallet_dict["huashi"] = int(source["huashi"])

    prison_dict = previous.prison.model_dump(mode="python")
    scalar_fields = (
        "level",
        "exp",
        "exp_next",
        "work_tickets",
        "power_used",
        "power_max",
        "prisoners_current",
        "prisoners_capacity",
        "raw_warehouse_used",
        "raw_warehouse_cap",
        "finished_warehouse_used",
        "finished_warehouse_cap",
        "dorm_count",
        "production_workshop_count",
    )
    for source in (top_data, grid_data, warehouse_data, shop_data or {}):
        for field_name in scalar_fields:
            if source.get(field_name) is not None:
                prison_dict[field_name] = int(source[field_name])

    merged_buildings = dict(prison_dict.get("buildings") or {})
    fresh_buildings = grid_data.get("buildings") or {}
    for locked_bid in grid_data.get("locked_buildings") or ():
        key = str(locked_bid)
        if key not in fresh_buildings:
            merged_buildings.pop(key, None)
    for bid, lv in fresh_buildings.items():
        merged_buildings[str(bid)] = int(lv)
    prison_dict["buildings"] = merged_buildings

    if orders_scanned:
        prison_dict["active_orders"] = [o.model_dump(mode="python") for o in scanned_orders]

    return wallet_dict, prison_dict


def _scan_exchange_shop_overview(
    context: Context,
    dock_entries: list[dict[str, Any]],
    prefix: str,
) -> tuple[dict[str, int], list[dict[str, Any]]]:
    """只读进入「兑换商店」同时采集精确工票/铁盟币与当前页研发配方状态，避免重复进店。"""
    shop_pt = find_dock_button_point(dock_entries, ("兑换",), PRISON_DOCK_SHOP_FALLBACK)
    if not tap_point(context, f"{prefix}TapShop", shop_pt):
        return {}, []

    def _check_shop(frame: Any, idx: int) -> bool | None:
        entries = ocr_roi(context, frame, f"{prefix}ShopChk{idx}", (100, 75, 1160, 590))
        return True if is_exchange_shop_entries(entries) else None

    shop_img, shop_ok, aborted = poll_screen(
        context,
        _check_shop,
        initial_delay=0.9,
        interval=0.45,
        max_checks=4,
        screencap_fn=safe_screencap,
        sleep_fn=sleep_with_stop,
    )
    if aborted:
        return {}, []

    shop_data: dict[str, int] = {}
    shop_rows: list[dict[str, Any]] = []
    if shop_ok and shop_img is not None:
        t_entries = ocr_roi(context, shop_img, f"{prefix}ShopTickets", SHOP_WORK_TICKETS_ROI)
        c_entries = ocr_roi(context, shop_img, f"{prefix}ShopCoins", SHOP_COINS_ROI)
        shop_data = parse_exchange_shop_top_bar(t_entries, c_entries)
        body_entries = ocr_roi(context, shop_img, f"{prefix}ShopScanBody", SHOP_BODY_ROI)
        shop_rows = parse_exchange_shop_recipe_rows(body_entries)
        _back_to_prison_overview(context, f"{prefix}ShopBack")
    elif shop_img is not None and not _is_on_prison_overview(context, shop_img, f"{prefix}ShopMiss"):
        _back_to_prison_overview(context, f"{prefix}ShopBack")
    return shop_data, shop_rows


def _scan_exchange_shop_balances(
    context: Context,
    dock_entries: list[dict[str, Any]],
    prefix: str,
) -> dict[str, int]:
    """只读进入「兑换商店」读取精确工票与铁盟币，再安全返回整顿中心总览。"""
    shop_data, _rows = _scan_exchange_shop_overview(context, dock_entries, prefix)
    return shop_data


def _unlocked_order_slot_points(slot_entries: list[dict[str, Any]]) -> list[tuple[int, tuple[int, int]]]:
    """根据右侧订单槽列表识别当前未解锁分界线，仅返回可用槽位索引与坐标。"""
    merged = _merge_horizontal_adjacent(slot_entries, max_gap_x=16, max_row_diff=12.0)
    min_locked_y: int | None = None
    for entry in merged:
        text = _clean_text(entry.get("text"))
        if "解锁" in text:
            box = entry.get("box")
            cy = int(round(float(box[1]) + float(box[3]) / 2.0)) if isinstance(box, (list, tuple)) and len(box) >= 4 else 999
            if min_locked_y is None or cy < min_locked_y:
                min_locked_y = cy
    if min_locked_y is not None:
        pts = [(idx, pt) for idx, pt in enumerate(ORDERS_SLOT_POINTS) if pt[1] + 15 < min_locked_y]
        return pts or [(0, ORDERS_SLOT_POINTS[0])]
    return list(enumerate(ORDERS_SLOT_POINTS[:3]))


def _enter_daily_orders_screen(
    context: Context,
    dock_entries: list[dict[str, Any]],
    prefix: str,
) -> tuple[Any | None, bool, bool, bool]:
    """从总览进入黑月日常订单卡片页（兼容门面页两跳与单跳测试桩）。"""
    ord_pt = find_dock_button_point(dock_entries, ("订单",), PRISON_DOCK_ORDERS_FALLBACK)
    if not tap_point(context, f"{prefix}TapOrders", ord_pt):
        return None, False, False, True

    def _check_ord(frame: Any, idx: int) -> str | None:
        hdr = ocr_roi(context, frame, f"{prefix}OrdChk{idx}", ORDERS_HEADER_ROI)
        foyer_body = ocr_roi(context, frame, f"{prefix}OrdFoyerChk{idx}", ORDERS_BODY_ROI)
        combined = list(hdr) + list(foyer_body)
        if is_orders_foyer_entries(combined):
            return "foyer"
        if is_orders_screen_entries(hdr):
            return "daily"
        joined = "".join(_clean_text(e.get("text")) for e in combined if isinstance(e, dict))
        if any(kw in joined for kw in ("需求物资", "奖励物品", "ITEMPURCHASEORDER", "删除订单", "物资不足", "交付")):
            return "daily"
        return None

    ord_img, kind, aborted = poll_screen(
        context,
        _check_ord,
        initial_delay=0.9,
        interval=0.45,
        max_checks=4,
        screencap_fn=safe_screencap,
        sleep_fn=sleep_with_stop,
    )
    if aborted:
        return None, False, False, True
    if not kind or ord_img is None:
        return ord_img, False, False, False

    if kind == "foyer":
        if not tap_point(context, f"{prefix}TapOrdersDaily", ORDERS_FOYER_DAILY_POINT):
            return None, False, False, True

        def _check_daily_card(frame: Any, idx: int) -> bool | None:
            body = ocr_roi(context, frame, f"{prefix}OrdDailyCard{idx}", ORDERS_BODY_ROI)
            joined = "".join(_clean_text(e.get("text")) for e in body if isinstance(e, dict))
            if any(kw in joined for kw in ("需求物资", "奖励物品", "ITEMPURCHASEORDER", "删除订单", "物资不足", "交付")):
                return True
            return None

        daily_img, daily_ok, aborted2 = poll_screen(
            context,
            _check_daily_card,
            initial_delay=0.9,
            interval=0.45,
            max_checks=4,
            screencap_fn=safe_screencap,
            sleep_fn=sleep_with_stop,
        )
        if aborted2:
            return None, False, False, True
        if daily_ok and daily_img is not None:
            return daily_img, True, False, False
        return daily_img, False, False, False

    return ord_img, True, True, False


def _scan_daily_orders_slots(
    context: Context,
    initial_img: Any,
    prefix: str,
) -> list[tuple[int, tuple[int, int], dict[str, Any]]]:
    """逐槽位读取黑月运输订单页右侧激活订单卡片详情。"""
    slot_entries = ocr_roi(context, initial_img, f"{prefix}OrdSlots", ORDERS_RIGHT_SLOTS_ROI)
    slot_points = _unlocked_order_slot_points(slot_entries)
    results: list[tuple[int, tuple[int, int], dict[str, Any]]] = []

    for idx, slot_pt in slot_points:
        if is_stopping(context):
            break
        cur_img = initial_img
        if idx > 0:
            if not tap_point(context, f"{prefix}OrdSlot{idx}", slot_pt):
                break
            if not sleep_with_stop(context, SLOT_SWITCH_DELAY):
                break
            cur_img = safe_screencap(context)
            if cur_img is None:
                break
        body = ocr_roi(context, cur_img, f"{prefix}OrdCardBody{idx}", ORDERS_BODY_ROI)
        btn = ocr_roi(context, cur_img, f"{prefix}OrdCardBtn{idx}", ORDERS_DELIVER_BUTTON_ROI)
        parsed = parse_single_order_card(body, btn, order_type="daily")
        if parsed is None:
            if not sleep_with_stop(context, 0.6):
                break
            retry_img = safe_screencap(context)
            if retry_img is None:
                break
            body = ocr_roi(context, retry_img, f"{prefix}OrdCardBodyRetry{idx}", ORDERS_BODY_ROI)
            btn = ocr_roi(context, retry_img, f"{prefix}OrdCardBtnRetry{idx}", ORDERS_DELIVER_BUTTON_ROI)
            parsed = parse_single_order_card(body, btn, order_type="daily")
        if parsed is not None:
            results.append((idx, slot_pt, parsed))
    return results


@dataclass
class _ExecState:
    live_coins: int
    live_tickets: int
    huashi_baseline: int
    reserve_coins: int
    executed: list[PrisonActionOutcome] = field(default_factory=list)
    skipped: list[PrisonActionOutcome] = field(default_factory=list)
    guard_aborts: list[PrisonActionOutcome] = field(default_factory=list)
    upgraded_buildings: dict[str, int] = field(default_factory=dict)
    deposit_auto_refill: bool | None = None
    tickets_gained: int = 0
    prisoners_checked_in: int = 0
    enabled_modules: frozenset[str] = field(default_factory=lambda: frozenset(ALL_PRISON_AUTO_MODULES))
    prod_duration_pref: str = "8h"
    raw_worker_mode: str = "balanced"
    warehouse_batch_cap: int = MAX_WAREHOUSE_BATCHES_PER_RUN
    core_upgrade_cap: int = MAX_CORE_UPGRADES_PER_RUN
    diag: PrisonDiagnosticRecorder | None = None

    def is_enabled(self, module_key: str) -> bool:
        return str(module_key) in self.enabled_modules

    def prod_duration_sequence(self) -> tuple[tuple[int, tuple[int, int]], ...]:
        if self.prod_duration_pref == "2h":
            return ((2, PROD_DUR_2H_POINT),)
        if self.prod_duration_pref == "4h":
            return ((4, PROD_DUR_4H_POINT), (2, PROD_DUR_2H_POINT))
        return ((8, PROD_DUR_8H_POINT), (4, PROD_DUR_4H_POINT), (2, PROD_DUR_2H_POINT))

    def can_afford_coins(self, cost: int) -> bool:
        spend = max(0, int(cost))
        return spend == 0 or (self.live_coins - spend) >= self.reserve_coins

    def spend_coins(self, cost: int) -> None:
        self.live_coins = max(0, self.live_coins - max(0, int(cost)))

    def spend_tickets(self, cost: int) -> None:
        self.live_tickets = max(0, self.live_tickets - max(0, int(cost)))

    def add_tickets(self, amount: int) -> None:
        gain = max(0, int(amount))
        if gain > 0:
            self.live_tickets += gain
            self.tickets_gained += gain

    def add_executed(
        self,
        category: str,
        action_type: str,
        target: str,
        detail: str,
        *,
        coins_delta: int = 0,
        tickets_delta: int = 0,
    ) -> None:
        self.executed.append(
            PrisonActionOutcome(
                category=category,  # type: ignore[arg-type]
                action_type=action_type,
                target=target,
                status="executed",
                detail=detail,
                coins_delta=coins_delta,
                tickets_delta=tickets_delta,
            )
        )
        if self.diag is not None:
            self.diag.record(
                "exec",
                f"executed.{action_type}",
                f"{target}: {detail}",
                data={"coins_delta": coins_delta, "tickets_delta": tickets_delta},
            )

    def add_skipped(self, category: str, action_type: str, target: str, detail: str) -> None:
        self.skipped.append(
            PrisonActionOutcome(
                category=category,  # type: ignore[arg-type]
                action_type=action_type,
                target=target,
                status="skipped",
                detail=detail,
            )
        )
        if self.diag is not None:
            self.diag.record("exec", f"skipped.{action_type}", f"{target}: {detail}")

    def add_guard_abort(
        self,
        category: str,
        action_type: str,
        target: str,
        detail: str,
        *,
        frame: Any = None,
    ) -> None:
        self.guard_aborts.append(
            PrisonActionOutcome(
                category=category,  # type: ignore[arg-type]
                action_type=action_type,
                target=target,
                status="guard_abort",
                detail=detail,
            )
        )
        if self.diag is not None:
            self.diag.record("guard", action_type, f"{target}: {detail}", level="WARNING")
            if frame is not None:
                self.diag.capture_frame(f"guard_{action_type}", frame)

    def add_failed(
        self,
        category: str,
        action_type: str,
        target: str,
        detail: str,
        *,
        frame: Any = None,
    ) -> None:
        self.skipped.append(
            PrisonActionOutcome(
                category=category,  # type: ignore[arg-type]
                action_type=action_type,
                target=target,
                status="failed",
                detail=detail,
            )
        )
        if self.diag is not None:
            self.diag.record("exec", f"failed.{action_type}", f"{target}: {detail}", level="ERROR")
            if frame is not None:
                self.diag.capture_frame(f"failed_{action_type}", frame)


def _find_room_in_overview_grid(
    entries: list[dict[str, Any]],
    aliases: tuple[str, ...],
    *,
    allow_unlockable: bool = False,
) -> tuple[tuple[int, int] | None, str]:
    """在网格 OCR 中查找目标建筑中心点（自动排除锁定/前置提示条；allow_unlockable=True 时放行「可解锁」LV0房间）。"""
    active_locked_hints = (
        tuple(hint for hint in LOCKED_HINTS if hint != "可解锁")
        if allow_unlockable
        else LOCKED_HINTS
    )
    merged = _merge_horizontal_adjacent(entries, max_gap_x=24, max_row_diff=14.0)
    normalized: list[tuple[str, tuple[int, int]]] = []
    for entry in merged:
        text = _clean_text(entry.get("text"))
        center = _entry_center(entry)
        if text and center is not None:
            normalized.append((text, center))

    for text, (cx, cy) in normalized:
        if any(hint in text for hint in REQUIREMENT_LABEL_HINTS):
            continue
        if not any(alias in text for alias in aliases):
            continue
        if any(hint in text for hint in active_locked_hints):
            return None, "locked"
        locked_nearby = any(
            abs(ny - cy) <= 60
            and ny - cy >= -18
            and abs(nx - cx) <= 165
            and any(hint in nb_text for hint in active_locked_hints)
            for nb_text, (nx, ny) in normalized
        )
        if locked_nearby:
            return None, "locked"
        # 严禁点击贴边被裁切的标题（如 17:15:48 研发中心 cy=619 导致点偏后误点进 1 号整顿宿舍）
        if cy > 545:
            return None, "edge_clipped_bottom"
        if cy < 85:
            return None, "edge_clipped_top"
        if cx > 1175:
            return None, "edge_clipped_right"
        if cx < 90:
            return None, "edge_clipped_left"
        return (min(1190, cx + 15), min(585, cy + 32)), "ok"
    return None, "not_found"


def _has_upgradable_badge_near(
    entries: list[dict[str, Any]],
    aliases: tuple[str, ...],
) -> bool:
    """检查总览网格里目标房间卡片下方是否仍挂有蓝底「可升级」徽标。"""
    merged = _merge_horizontal_adjacent(entries, max_gap_x=24, max_row_diff=14.0)
    normalized: list[tuple[str, tuple[int, int]]] = []
    for entry in merged:
        text = _clean_text(entry.get("text"))
        center = _entry_center(entry)
        if text and center is not None:
            normalized.append((text, center))
    for text, (cx, cy) in normalized:
        if any(hint in text for hint in REQUIREMENT_LABEL_HINTS):
            continue
        if not any(alias in text for alias in aliases):
            continue
        if "可升级" in text:
            return True
        if any(
            abs(nx - cx) <= 185 and -10 <= (ny - cy) <= 75 and "可升级" in nb_text
            for nb_text, (nx, ny) in normalized
        ):
            return True
    return False


def _overview_grid_signature(entries: Sequence[dict[str, Any]]) -> tuple[tuple[str, int, int], ...]:
    """提取网格 OCR 归一化位置签名，用于检测拖拽是否完全卡滞（排除单字噪点）。"""
    sig: set[tuple[str, int, int]] = set()
    for entry in _merge_horizontal_adjacent(entries, max_gap_x=24, max_row_diff=14.0):
        text = _clean_text(entry.get("text"))
        if len(text) < 2:
            continue
        center = _entry_center(entry)
        if center is None:
            continue
        sig.add((text, round(center[0] / 24), round(center[1] / 24)))
    return tuple(sorted(sig))


def _has_zoomed_bubble_hint(entries: Sequence[dict[str, Any]]) -> bool:
    """检查网格 OCR 是否出现房间放大态右侧浮出的「建设/生产/详情」气泡词。"""
    merged = _merge_horizontal_adjacent(entries, max_gap_x=14, max_row_diff=12.0)
    for entry in list(entries) + merged:
        if not isinstance(entry, dict):
            continue
        text = _clean_text(entry.get("text"))
        if text not in ("建设", "生产", "详情"):
            continue
        center = _entry_center(entry)
        if center is not None and 680 <= center[0] <= 910 and 190 <= center[1] <= 445:
            return True
    return False


def _pan_and_find_room(
    context: Context,
    prefix: str,
    swipe_pair: tuple[tuple[int, int], tuple[int, int]],
    aliases: tuple[str, ...],
    *,
    allow_unlockable: bool = False,
) -> tuple[tuple[int, int] | None, str]:
    cur_img = safe_screencap(context)
    if cur_img is None:
        return None, "stopped"
    cur_entries = ocr_roi(context, cur_img, f"{prefix}GridCur", PRISON_OVERVIEW_GRID_ROI)
    pt, status = _find_room_in_overview_grid(cur_entries, aliases, allow_unlockable=allow_unlockable)
    if pt is not None or status == "locked":
        return pt, status

    if _has_zoomed_bubble_hint(cur_entries):
        _is_ov, is_zoomed = _overview_state(context, cur_img, f"{prefix}ZoomHint")
        if is_stopping(context):
            return None, "stopped"
        if is_zoomed and _unzoom_room_to_overview(context, f"{prefix}HintUnzoom", ROOM_UNZOOM_RIGHT_COL_POINT):
            unzoom_img = safe_screencap(context)
            if unzoom_img is None:
                return None, "stopped"
            cur_img = unzoom_img
            cur_entries = ocr_roi(context, cur_img, f"{prefix}GridUnzoom", PRISON_OVERVIEW_GRID_ROI)
            pt, status = _find_room_in_overview_grid(cur_entries, aliases, allow_unlockable=allow_unlockable)
            if pt is not None or status == "locked":
                return pt, status

    edge_nudges: dict[str, tuple[tuple[int, int], tuple[int, int]]] = {
        "edge_clipped_bottom": PRISON_RIGHT_WING_PAN_SWIPE,
        "edge_clipped_right": ((980, 360), (340, 360)),
        "edge_clipped_top": ((640, 200), (640, 520)),
        "edge_clipped_left": ((300, 360), (960, 360)),
    }
    candidates: list[tuple[tuple[int, int], tuple[int, int]]] = []
    if status in edge_nudges:
        candidates.append(edge_nudges[status])
    candidates.append(swipe_pair)
    if swipe_pair == PRISON_RIGHT_WING_PAN_SWIPE:
        candidates.extend((((640, 200), (640, 520)), ((980, 360), (340, 360))))
    elif swipe_pair == PRISON_UPPER_WING_PAN_SWIPE:
        candidates.extend((((640, 220), (640, 560)), ((980, 360), (340, 360))))

    swipes: list[tuple[tuple[int, int], tuple[int, int]]] = []
    for pair in candidates:
        if pair not in swipes:
            swipes.append(pair)

    last_status = status
    prev_sig = _overview_grid_signature(cur_entries)
    unzoom_recovered = False
    stalled_swipes = 0

    for swipe_idx, (start_pt, end_pt) in enumerate(swipes):
        pan_name = f"{prefix}Pan" if swipe_idx == 0 else f"{prefix}PanRec{swipe_idx}"
        grid_name = f"{prefix}Grid" if swipe_idx == 0 else f"{prefix}GridRec{swipe_idx}"
        if not swipe_points(
            context,
            pan_name,
            start_pt,
            end_pt,
            duration=SWIPE_DURATION_MS,
            end_hold=SWIPE_END_HOLD_MS,
        ):
            return None, "stopped"
        if not sleep_with_stop(context, SWIPE_SETTLE_DELAY):
            return None, "stopped"
        img = safe_screencap(context)
        if img is None:
            return None, "stopped"
        entries = ocr_roi(context, img, grid_name, PRISON_OVERVIEW_GRID_ROI)
        pt, last_status = _find_room_in_overview_grid(entries, aliases, allow_unlockable=allow_unlockable)
        if pt is not None or last_status == "locked":
            return pt, last_status

        next_sig = _overview_grid_signature(entries)
        if prev_sig and next_sig and next_sig == prev_sig:
            if not unzoom_recovered:
                unzoom_recovered = True
                _ov, is_zoomed = _overview_state(context, img, f"{prefix}StallChk{swipe_idx}")
                if is_stopping(context):
                    return None, "stopped"
                if is_zoomed and _unzoom_room_to_overview(
                    context,
                    f"{prefix}StallUnzoom{swipe_idx}",
                    ROOM_UNZOOM_RIGHT_COL_POINT,
                ):
                    rec_img = safe_screencap(context)
                    if rec_img is None:
                        return None, "stopped"
                    rec_entries = ocr_roi(context, rec_img, f"{prefix}GridStallRec{swipe_idx}", PRISON_OVERVIEW_GRID_ROI)
                    rec_pt, rec_status = _find_room_in_overview_grid(
                        rec_entries,
                        aliases,
                        allow_unlockable=allow_unlockable,
                    )
                    if rec_pt is not None or rec_status == "locked":
                        return rec_pt, rec_status
                    last_status = rec_status
                    prev_sig = _overview_grid_signature(rec_entries)
                    stalled_swipes = 0
                    continue
            stalled_swipes += 1
            if stalled_swipes >= 2:
                return None, "pan_stalled"
        elif next_sig:
            stalled_swipes = 0
            prev_sig = next_sig
    return None, last_status


def _exit_zoomed_panel_to_overview(
    context: Context,
    prefix: str,
    unzoom_point: tuple[int, int],
) -> bool:
    """退出子面板并解除房间放大态，确保回到可滑动的整顿中心总览。"""
    if not tap_point(context, f"{prefix}ExitPanel", PRISON_BACK_POINT):
        return False
    if not sleep_with_stop(context, 1.2):
        return False
    frame = safe_screencap(context)
    if frame is None:
        return False
    if _is_on_prison_overview(context, frame, f"{prefix}Chk1"):
        return True

    if _unzoom_room_to_overview(context, prefix, unzoom_point):
        return True
    if is_stopping(context):
        return False
    return _back_to_prison_overview(context, f"{prefix}FallbackBack")


def _exec_claim_todo_tasks(
    context: Context,
    state: _ExecState,
    prefix: str,
) -> None:
    """打开右上「事项一览」领取全部已完成任务工票/徽章奖励。"""
    fresh = safe_screencap(context)
    if fresh is None:
        return
    btn_entries = ocr_roi(context, fresh, f"{prefix}TodoBtn", PRISON_TODO_BTN_ROI)
    todo_pt: tuple[int, int] | None = None
    for entry in _merge_horizontal_adjacent(btn_entries, max_gap_x=14, max_row_diff=12.0):
        text = _clean_text(entry.get("text"))
        if "事项" in text or "一览" in text:
            todo_pt = _entry_center(entry) or PRISON_TODO_BTN_POINT
            break
    if todo_pt is None:
        return

    if not tap_point(context, f"{prefix}TapTodo", todo_pt):
        return

    def _check_todo_open(frame: Any, poll_idx: int) -> bool | None:
        left_entries = ocr_roi(context, frame, f"{prefix}TodoTitle_{poll_idx}", (60, 420, 400, 260))
        right_entries = ocr_roi(context, frame, f"{prefix}TodoClaimChk_{poll_idx}", PRISON_TODO_CLAIM_ROI)
        joined = "".join(
            _clean_text(e.get("text"))
            for e in (list(left_entries) + list(right_entries))
            if isinstance(e, dict)
        )
        if any(kw in joined for kw in ("整顿中心任务", "领取", "前往")):
            return True
        return None

    todo_img, opened, aborted = poll_screen(
        context,
        _check_todo_open,
        initial_delay=1.0,
        interval=0.5,
        max_checks=4,
        screencap_fn=safe_screencap,
        sleep_fn=sleep_with_stop,
    )
    if aborted:
        return
    if not opened or todo_img is None:
        if todo_img is not None and not _is_on_prison_overview(context, todo_img, f"{prefix}TodoMiss"):
            _back_to_prison_overview(context, f"{prefix}TodoBack")
        return

    claimed = 0
    cur_img = todo_img
    for step_idx in range(8):
        if is_stopping(context):
            break
        claim_entries = ocr_roi(context, cur_img, f"{prefix}TodoClaimList_{step_idx}", PRISON_TODO_CLAIM_ROI)
        pts = find_todo_claim_button_points(claim_entries)
        if not pts:
            break
        claim_pt = (pts[0][0], max(60, pts[0][1] - 26))
        if not tap_point(context, f"{prefix}TapTodoClaim_{step_idx}", claim_pt):
            break
        if not sleep_with_stop(context, 1.0):
            break
        after_img = safe_screencap(context)
        if after_img is None:
            break
        pop_entries = ocr_roi(context, after_img, f"{prefix}TodoReward_{step_idx}", (340, 140, 600, 560))
        pop_text = "".join(_clean_text(e.get("text")) for e in pop_entries if isinstance(e, dict))
        got_reward = any(kw in pop_text for kw in ("获得", "恭喜", "触碰空白"))
        if got_reward:
            if not tap_point(context, f"{prefix}TodoRewardDismiss_{step_idx}", PRISON_REWARD_DISMISS_POINT):
                break
            if not sleep_with_stop(context, 0.9):
                break
            refreshed = safe_screencap(context)
            if refreshed is not None:
                after_img = refreshed
        else:
            next_entries = ocr_roi(context, after_img, f"{prefix}TodoClaimAfter_{step_idx}", PRISON_TODO_CLAIM_ROI)
            next_pts = find_todo_claim_button_points(next_entries)
            if len(next_pts) >= len(pts):
                break
        claimed += 1
        state.add_tickets(200)
        cur_img = after_img

    if claimed > 0:
        state.add_executed(
            "do",
            "todo_claim",
            "事项一览",
            f"自动领取「事项一览」任务奖励 ×{claimed} 项（估算 +{claimed * 200:,} 工票）",
            tickets_delta=claimed * 200,
        )
    _back_to_prison_overview(context, f"{prefix}TodoDone")


def _exec_checkin_prisoners(
    context: Context,
    state: _ExecState,
    snapshot: AccountSnapshot,
    prefix: str,
) -> None:
    """进入顶栏囚犯名册检查是否有待入住囚犯并全选办理入住。"""
    cap = int(snapshot.prison.prisoners_capacity or 0)
    cur = int(snapshot.prison.prisoners_current or 0)
    if cap > 0 and cur >= cap:
        return

    if not tap_point(context, f"{prefix}TapPrisonerBar", PRISON_TOP_PRISONER_BAR_POINT):
        return

    def _check_roster(frame: Any, poll_idx: int) -> tuple[int, int] | None:
        entries = ocr_roi(context, frame, f"{prefix}RosterBtn_{poll_idx}", PRISON_ROSTER_CHECKIN_BTN_ROI)
        for entry in _merge_horizontal_adjacent(entries, max_gap_x=12, max_row_diff=12.0):
            if "办理" in _clean_text(entry.get("text")) or "入住" in _clean_text(entry.get("text")):
                return _entry_center(entry) or PRISON_ROSTER_CHECKIN_BTN_POINT
        return None

    roster_img, checkin_pt, aborted = poll_screen(
        context,
        _check_roster,
        initial_delay=1.0,
        interval=0.5,
        max_checks=4,
        screencap_fn=safe_screencap,
        sleep_fn=sleep_with_stop,
    )
    if aborted:
        return
    if checkin_pt is None or roster_img is None:
        if roster_img is not None and not _is_on_prison_overview(context, roster_img, f"{prefix}RosterMiss"):
            _back_to_prison_overview(context, f"{prefix}RosterBack")
        return

    if not tap_point(context, f"{prefix}TapCheckinBtn", checkin_pt):
        return

    def _check_checkin_screen(frame: Any, poll_idx: int) -> list[dict[str, Any]] | None:
        entries = ocr_roi(context, frame, f"{prefix}CheckinStatus_{poll_idx}", PRISON_CHECKIN_STATUS_ROI)
        joined = "".join(_clean_text(e.get("text")) for e in entries if isinstance(e, dict))
        if any(kw in joined for kw in ("未整顿", "整顿中", "确认办理", "一键全选")):
            return entries
        empty_entries = ocr_roi(context, frame, f"{prefix}CheckinEmpty_{poll_idx}", (420, 260, 440, 220))
        empty_joined = "".join(_clean_text(e.get("text")) for e in empty_entries if isinstance(e, dict))
        if "暂无囚犯" in empty_joined:
            return list(entries) + list(empty_entries)
        return None

    checkin_img, polled_status, aborted2 = poll_screen(
        context,
        _check_checkin_screen,
        initial_delay=1.0,
        interval=0.5,
        max_checks=4,
        screencap_fn=safe_screencap,
        sleep_fn=sleep_with_stop,
    )
    if aborted2:
        return
    if checkin_img is None or polled_status is None:
        _back_to_prison_overview(context, f"{prefix}CheckinMiss")
        return

    waiting, active_cur, active_cap = parse_prisoner_checkin_counts(polled_status)
    if (
        waiting is not None
        and waiting > 0
        and (active_cap is None or active_cur is None or active_cur < active_cap)
    ):
        if tap_point(context, f"{prefix}CheckinSelAll", PRISON_CHECKIN_SELECT_ALL_POINT) and sleep_with_stop(context, 0.85):
            if tap_point(context, f"{prefix}CheckinConfirm", PRISON_CHECKIN_CONFIRM_POINT) and sleep_with_stop(context, POST_CONFIRM_DELAY):
                post_img = safe_screencap(context)
                if post_img is not None:
                    post_status = ocr_roi(context, post_img, f"{prefix}CheckinPostStatus", PRISON_CHECKIN_STATUS_ROI)
                    w_after, a_after, _cap_after = parse_prisoner_checkin_counts(post_status)
                    gained = (
                        (a_after - active_cur)
                        if (a_after is not None and active_cur is not None and a_after > active_cur)
                        else (waiting - (w_after or 0) if w_after is not None and w_after < waiting else waiting)
                    )
                    if gained > 0 or (w_after is not None and w_after < waiting):
                        state.prisoners_checked_in += max(1, gained)
                        state.add_executed(
                            "do",
                            "prisoner_checkin",
                            "囚犯入住",
                            f"自动办理 {max(1, gained)} 名未整顿囚犯入住",
                        )

    _back_to_prison_overview(context, f"{prefix}CheckinDone")


def _exec_ensure_finance_auto_refill(
    context: Context,
    state: _ExecState,
    snapshot: AccountSnapshot,
    prefix: str,
) -> None:
    """自动进右翼「财务中心」核对并开启「保证金低于80%自动补满」。"""
    if snapshot.prison.deposit_auto_refill is True:
        state.deposit_auto_refill = True
        return

    fin_pt, _status = _pan_and_find_room(context, f"{prefix}Fin", PRISON_RIGHT_WING_PAN_SWIPE, ("财务中心",))
    if fin_pt is None:
        return
    if not tap_point(context, f"{prefix}TapFinance", fin_pt):
        return

    def _check_fin_modal(frame: Any, poll_idx: int) -> bool | None:
        entries = ocr_roi(context, frame, f"{prefix}FinModal_{poll_idx}", FINANCE_MODAL_CHECK_ROI)
        joined = "".join(_clean_text(e.get("text")) for e in entries if isinstance(e, dict))
        if any(kw in joined for kw in ("财务中心", "保证金", "自动补满", "生活运营")):
            return True
        return None

    fin_img, fin_ok, aborted = poll_screen(
        context,
        _check_fin_modal,
        initial_delay=1.0,
        interval=0.5,
        max_checks=4,
        screencap_fn=safe_screencap,
        sleep_fn=sleep_with_stop,
    )
    if aborted:
        return
    if not fin_ok or fin_img is None:
        _ensure_on_prison_overview(context, f"{prefix}FinMiss")
        return

    cur_on = detect_finance_auto_refill_state(fin_img)
    if cur_on is True:
        state.deposit_auto_refill = True
    elif cur_on is False:
        if tap_point(context, f"{prefix}ToggleFinanceAutoRefill", FINANCE_TOGGLE_POINT) and sleep_with_stop(context, 0.9):
            after_img = safe_screencap(context)
            if after_img is not None and detect_finance_auto_refill_state(after_img) is True:
                state.deposit_auto_refill = True
                state.add_executed(
                    "do",
                    "finance_auto_refill",
                    "财务中心",
                    "已自动开启「保证金低于80%自动补满」",
                )
            else:
                state.add_skipped("do", "finance_auto_refill", "财务中心", "点击开关后未确认变成开启状态，待下次复检。")

    tap_point(context, f"{prefix}DismissFinance", FINANCE_DISMISS_POINT)
    sleep_with_stop(context, 0.85)
    _ensure_on_prison_overview(context, f"{prefix}FinDone")


def _exec_deliver_orders(
    context: Context,
    state: _ExecState,
    snapshot: AccountSnapshot,
    phase: str,
    prefix: str,
) -> None:
    if phase != "rush_leveling":
        state.add_skipped("do", "order_deliver", "黑月订单", "毕业阶段按攻略停交黑月订单。")
        return
    allow_deliver = state.is_enabled("order_deliver")
    allow_delete = state.is_enabled("order_delete_free")
    if not allow_deliver and not allow_delete:
        return

    fresh = safe_screencap(context)
    if fresh is None:
        return
    dock_entries = ocr_roi(context, fresh, f"{prefix}OrdDock", PRISON_BOTTOM_DOCK_ROI)
    ord_img, entered, _legacy, aborted = _enter_daily_orders_screen(context, dock_entries, f"{prefix}ExecOrd")
    if aborted:
        return
    if not entered or ord_img is None:
        if ord_img is not None and not _is_on_prison_overview(context, ord_img, f"{prefix}ExecOrdMiss"):
            _back_to_prison_overview(context, f"{prefix}ExecOrdBack")
        state.add_skipped("do", "order_deliver", "黑月订单", "未能进入黑月运输订单页，跳过交付。")
        return

    slot_entries = ocr_roi(context, ord_img, f"{prefix}ExecOrdSlots", ORDERS_RIGHT_SLOTS_ROI)
    slot_points = _unlocked_order_slot_points(slot_entries)
    acted_any = False
    slot_cursor = 0
    tried_sigs: set[tuple[str, int, int]] = set()

    for round_no in range(len(slot_points) + 2):
        if is_stopping(context) or slot_cursor >= len(slot_points):
            break
        idx, slot_pt = slot_points[slot_cursor]
        cur_img = ord_img if (round_no == 0 and idx == 0) else safe_screencap(context)
        if round_no > 0 or idx > 0:
            if not tap_point(context, f"{prefix}ExecOrdSlot{idx}_{round_no}", slot_pt):
                break
            if not sleep_with_stop(context, SLOT_SWITCH_DELAY):
                break
            cur_img = safe_screencap(context)
        if cur_img is None:
            break

        body = ocr_roi(context, cur_img, f"{prefix}ExecOrdBody{idx}_{round_no}", ORDERS_BODY_ROI)
        btn = ocr_roi(context, cur_img, f"{prefix}ExecOrdBtn{idx}_{round_no}", ORDERS_DELIVER_BUTTON_ROI)
        card = parse_single_order_card(body, btn, order_type="daily")
        if card is None:
            if not sleep_with_stop(context, 0.6):
                break
            retry_img = safe_screencap(context)
            if retry_img is None:
                break
            cur_img = retry_img
            body = ocr_roi(context, cur_img, f"{prefix}ExecOrdBodyRetry{idx}_{round_no}", ORDERS_BODY_ROI)
            btn = ocr_roi(context, cur_img, f"{prefix}ExecOrdBtnRetry{idx}_{round_no}", ORDERS_DELIVER_BUTTON_ROI)
            card = parse_single_order_card(body, btn, order_type="daily")
        if card is None:
            slot_cursor += 1
            continue

        sig = (card["item_name"], int(card["quantity"]), int(card["stock_owned"]))
        if sig in tried_sigs:
            slot_cursor += 1
            continue
        tried_sigs.add(sig)

        decision = evaluate_black_moon_order(
            PrisonOrder(
                item_name=card["item_name"],
                quantity=card["quantity"],
                order_type="daily",
                stock_owned=card["stock_owned"],
            ),
            snapshot.prison,
            phase,  # type: ignore[arg-type]
        )
        if decision.action == "deliver" and card["deliverable"]:
            if not allow_deliver:
                state.add_skipped(
                    "do",
                    "order_deliver",
                    card["item_name"],
                    f"槽位#{idx + 1}（{card['item_name']}×{card['quantity']}）可交但已关闭「黑月订单自动交付」。",
                )
                slot_cursor += 1
                continue
            if not tap_point(context, f"{prefix}ExecOrdDeliver{idx}_{round_no}", ORDERS_DELIVER_POINT):
                break
            if not sleep_with_stop(context, POST_CONFIRM_DELAY):
                break
            after_img = safe_screencap(context)
            confirmed = after_img is not None
            if after_img is not None:
                after_body = ocr_roi(context, after_img, f"{prefix}ExecOrdAfterBody{idx}_{round_no}", ORDERS_BODY_ROI)
                after_btn = ocr_roi(context, after_img, f"{prefix}ExecOrdAfterBtn{idx}_{round_no}", ORDERS_DELIVER_BUTTON_ROI)
                after_card = parse_single_order_card(after_body, after_btn, order_type="daily")
                if (
                    after_card is not None
                    and after_card["deliverable"]
                    and after_card["item_name"] == card["item_name"]
                    and after_card["quantity"] == card["quantity"]
                    and after_card["stock_owned"] >= card["stock_owned"]
                ):
                    confirmed = False
            if confirmed:
                acted_any = True
                state.add_executed(
                    "do",
                    "order_deliver",
                    card["item_name"],
                    f"交付槽位#{idx + 1}：{card['item_name']}×{card['quantity']}",
                )
                continue
            state.add_skipped(
                "do",
                "order_deliver",
                card["item_name"],
                f"点击交付槽位#{idx + 1} 后状态未变化，未确认交付成功。",
            )
            slot_cursor += 1
        elif decision.action == "delete_free":
            if not allow_delete:
                state.add_skipped(
                    "do",
                    "order_delete_free",
                    card["item_name"],
                    f"槽位#{idx + 1}（{card['item_name']}×{card['quantity']}）可免费删除但已关闭「低效订单免费删除」。",
                )
                slot_cursor += 1
                continue
            del_entries = ocr_roi(context, cur_img, f"{prefix}ExecOrdDelBtn{idx}_{round_no}", ORDERS_DELETE_BTN_ROI)
            del_pt = ORDERS_DELETE_BTN_POINT
            for entry in _merge_horizontal_adjacent(del_entries, max_gap_x=12, max_row_diff=12.0):
                if "删除" in _clean_text(entry.get("text")):
                    del_pt = _entry_center(entry) or ORDERS_DELETE_BTN_POINT
                    break
            if not tap_point(context, f"{prefix}ExecOrdDelete{idx}_{round_no}", del_pt):
                break
            if not sleep_with_stop(context, POST_CONFIRM_DELAY):
                break
            after_del = safe_screencap(context)
            if after_del is None:
                break
            pop_entries = ocr_roi(context, after_del, f"{prefix}ExecOrdDelPop{idx}_{round_no}", SHOP_CONFIRM_MODAL_ROI)
            pop_txt = "".join(_clean_text(e.get("text")) for e in pop_entries if isinstance(e, dict))
            if "桦石" in pop_txt:
                tap_point(context, f"{prefix}ExecOrdDelCancelHuashi{idx}", SHOP_MODAL_CANCEL_POINT)
                sleep_with_stop(context, 0.8)
                state.add_guard_abort("guard", "order_delete_huashi", card["item_name"], "删除订单弹窗出现桦石字样，已取消。", frame=after_del)
                break
            if find_modal_confirm_button_point(pop_entries) is not None or any(kw in pop_txt for kw in ("消耗", "确认", "确定", "取消")):
                tap_point(context, f"{prefix}ExecOrdDelCancelPay{idx}", SHOP_MODAL_CANCEL_POINT)
                sleep_with_stop(context, 0.8)
                state.add_skipped(
                    "do",
                    "order_delete_free",
                    card["item_name"],
                    f"删除槽位#{idx + 1} 出现二次确认弹窗，按安全规则取消保留。",
                )
                slot_cursor += 1
                continue

            after_slots = ocr_roi(context, after_del, f"{prefix}ExecOrdDelSlots{idx}_{round_no}", ORDERS_RIGHT_SLOTS_ROI)
            after_slots_txt = "".join(_clean_text(e.get("text")) for e in after_slots if isinstance(e, dict))
            after_body = ocr_roi(context, after_del, f"{prefix}ExecOrdDelAfterBody{idx}_{round_no}", ORDERS_BODY_ROI)
            after_btn = ocr_roi(context, after_del, f"{prefix}ExecOrdDelAfterBtn{idx}_{round_no}", ORDERS_DELIVER_BUTTON_ROI)
            after_card = parse_single_order_card(after_body, after_btn, order_type="daily")
            changed = (
                "订单调度" in after_slots_txt
                or "调度中" in after_slots_txt
                or after_card is None
                or after_card["item_name"] != card["item_name"]
                or int(after_card["quantity"]) != int(card["quantity"])
            )
            if changed:
                acted_any = True
                state.add_executed(
                    "do",
                    "order_delete_free",
                    card["item_name"],
                    f"免费删除黑月订单：{card['item_name']}×{card['quantity']}",
                )
                continue
            state.add_skipped(
                "do",
                "order_delete_free",
                card["item_name"],
                f"点击删除槽位#{idx + 1} 后订单未变化，未确认删除成功。",
            )
            slot_cursor += 1
        else:
            state.add_skipped(
                "do",
                "order_deliver",
                card["item_name"],
                f"槽位#{idx + 1}（{card['item_name']}×{card['quantity']}，库存{card['stock_owned']}）暂不交付：{decision.action}",
            )
            slot_cursor += 1

    if not acted_any and not any(o.action_type in ("order_deliver", "order_delete_free") for o in state.skipped):
        state.add_skipped("do", "order_deliver", "黑月订单", "未识别到可直接交付或免费删单的运输订单。")
    _back_to_prison_overview(context, f"{prefix}ExecOrdDone")


def _exec_upgrade_core_buildings(
    context: Context,
    state: _ExecState,
    execution_plan: PrisonExecutionPlan,
    prefix: str,
    snapshot: AccountSnapshot | None = None,
) -> None:
    if execution_plan.phase != "rush_leveling":
        return

    raw_allowed = {
        s.target
        for s in execution_plan.build_actions
        if s.allowed and s.action_type in ("building_upgrade", "building_unlock")
    }
    raw_research_blocked = {
        s.target
        for s in execution_plan.build_actions
        if (not s.allowed)
        and s.action_type in ("building_upgrade", "building_unlock")
        and ("研发中心" in s.blocked_reason)
    }
    unlock_targets = {
        s.target
        for s in execution_plan.build_actions
        if s.action_type == "building_unlock"
    }
    if snapshot is not None:
        for bid, label in (
            ("raw_sewing", "缝纫工具原料车间"),
            ("raw_synthetic", "人造纤维原料车间"),
            ("raw_plant", "植物纤维原料车间"),
            ("raw_animal", "动物纤维原料车间"),
        ):
            if int(snapshot.prison.buildings.get(bid, 0)) < 1:
                unlock_targets.add(label)

    core_candidates: list[tuple[str, str, tuple[str, ...], tuple[int, int]]] = [
        ("research_center", "研发中心", ("研发中心",), ROOM_UNZOOM_LEFT_COL_POINT),
        ("power_center", "电力中心", ("电力中心",), ROOM_UNZOOM_RIGHT_COL_POINT),
    ]
    raw_specs = (
        ("raw_sewing", "缝纫工具原料车间", ("缝纫工具原料车间", "缝纫工具车间"), ROOM_UNZOOM_LEFT_COL_POINT),
        ("raw_synthetic", "人造纤维原料车间", ("人造纤维原料车间", "人造纤维车间"), ROOM_UNZOOM_RIGHT_COL_POINT),
        ("raw_plant", "植物纤维原料车间", ("植物纤维原料车间", "植物纤维车间"), ROOM_UNZOOM_LEFT_COL_POINT),
        ("raw_animal", "动物纤维原料车间", ("动物纤维原料车间", "动物纤维车间"), ROOM_UNZOOM_RIGHT_COL_POINT),
    )

    def _run_building(bid: str, label: str, aliases: tuple[str, ...], unzoom_pt: tuple[int, int]) -> None:
        is_unlock = label in unlock_targets
        action_kind = "building_unlock" if is_unlock else "building_upgrade"
        room_pt, locate_status = _pan_and_find_room(
            context,
            f"{prefix}Bld_{bid}",
            PRISON_RIGHT_WING_PAN_SWIPE,
            aliases,
            allow_unlockable=is_unlock,
        )
        if room_pt is None:
            state.add_skipped("build", action_kind, label, f"总览未找到可升级入口（{locate_status}）。")
            return

        if not tap_point(context, f"{prefix}TapRoom_{bid}", room_pt):
            return

        need_exit_zoom = True
        entered_build_panel = False
        latest_after_img: Any = None
        max_rounds = max(1, int(state.core_upgrade_cap))

        for round_idx in range(max_rounds):
            if is_stopping(context):
                break
            round_suffix = "" if round_idx == 0 else f"_r{round_idx}"
            fallback_bubble = POWER_BUBBLE_BUILD_FALLBACK if bid == "power_center" else ROOM_BUBBLE_BOTTOM_FALLBACK

            if round_idx == 0:
                def _check_bubble(frame: Any, poll_idx: int) -> list[dict[str, Any]] | None:
                    entries = ocr_roi(context, frame, f"{prefix}Bubble_{bid}_{poll_idx}", ROOM_BUBBLE_ROI)
                    joined = "".join(_clean_text(e.get("text")) for e in entries if isinstance(e, dict))
                    if any(kw in joined for kw in ("建设", "详情")):
                        return entries
                    return None

                bubble_img, bubble_polled, aborted_b = poll_screen(
                    context,
                    _check_bubble,
                    initial_delay=PANEL_POLL_INITIAL,
                    interval=PANEL_POLL_INTERVAL,
                    max_checks=4,
                    screencap_fn=safe_screencap,
                    sleep_fn=sleep_with_stop,
                )
                if aborted_b or bubble_img is None:
                    need_exit_zoom = False
                    break
                bubble_entries = bubble_polled if isinstance(bubble_polled, list) else []
                build_bubble_pt = find_room_bubble_point(bubble_entries, "建设", fallback_bubble)
                if build_bubble_pt is None:
                    state.add_skipped("build", action_kind, label, "房间聚焦后未检测到「建设」按钮。")
                    if _is_on_prison_overview(context, bubble_img, f"{prefix}UnzoomChk_{bid}"):
                        need_exit_zoom = False
                    break
            else:
                cur_bubble_img = latest_after_img if latest_after_img is not None else safe_screencap(context)
                if cur_bubble_img is None:
                    break
                if _is_on_prison_overview(context, cur_bubble_img, f"{prefix}AfterOv_{bid}{round_suffix}"):
                    ov_grid = ocr_roi(context, cur_bubble_img, f"{prefix}OvRechk_{bid}{round_suffix}", PRISON_OVERVIEW_GRID_ROI)
                    re_pt, _re_st = _find_room_in_overview_grid(ov_grid, aliases, allow_unlockable=False)
                    if re_pt is not None and _has_upgradable_badge_near(ov_grid, aliases):
                        if not tap_point(context, f"{prefix}TapRoom_{bid}{round_suffix}", re_pt):
                            need_exit_zoom = False
                            break
                        def _check_re_bubble(frame: Any, idx: int) -> list[dict[str, Any]] | None:
                            entries = ocr_roi(context, frame, f"{prefix}Bubble_{bid}{round_suffix}_{idx}", ROOM_BUBBLE_ROI)
                            joined = "".join(_clean_text(e.get("text")) for e in entries if isinstance(e, dict))
                            return entries if any(kw in joined for kw in ("建设", "详情")) else None

                        re_img, re_polled, re_aborted = poll_screen(
                            context,
                            _check_re_bubble,
                            initial_delay=PANEL_POLL_INITIAL,
                            interval=PANEL_POLL_INTERVAL,
                            max_checks=4,
                            screencap_fn=safe_screencap,
                            sleep_fn=sleep_with_stop,
                        )
                        if re_aborted or re_img is None:
                            need_exit_zoom = False
                            break
                        bubble_entries = re_polled if isinstance(re_polled, list) else []
                        build_bubble_pt = find_room_bubble_point(bubble_entries, "建设", fallback_bubble)
                        if build_bubble_pt is None:
                            need_exit_zoom = False
                            break
                    else:
                        need_exit_zoom = False
                        break
                else:
                    bubble_entries = ocr_roi(context, cur_bubble_img, f"{prefix}Bubble_{bid}{round_suffix}", ROOM_BUBBLE_ROI)
                    build_bubble_pt = find_room_bubble_point(bubble_entries, "建设", fallback_bubble)
                    if build_bubble_pt is None:
                        break

            if not tap_point(context, f"{prefix}TapBuildBubble_{bid}{round_suffix}", build_bubble_pt):
                break
            entered_build_panel = True

            def _check_build_panel(frame: Any, poll_idx: int) -> bool | None:
                entries = ocr_roi(context, frame, f"{prefix}BuildPanel_{bid}{round_suffix}_{poll_idx}", ROOM_BUILD_PANEL_ROI)
                joined = "".join(_clean_text(e.get("text")) for e in entries if isinstance(e, dict))
                if any(kw in joined for kw in ("升级", "建造", "等级", "条件", "满级")) or "/" in joined:
                    return True
                if bid == "power_center":
                    t_entries = ocr_roi(context, frame, f"{prefix}PowerTabsPoll{round_suffix}_{poll_idx}", POWER_TABS_OCR_ROI)
                    t_joined = "".join(_clean_text(e.get("text")) for e in t_entries if isinstance(e, dict))
                    if any(kw in t_joined for kw in ("房间", "电机")):
                        return True
                return None

            build_img, _panel_ok, aborted_p = poll_screen(
                context,
                _check_build_panel,
                initial_delay=PANEL_POLL_INITIAL,
                interval=PANEL_POLL_INTERVAL,
                max_checks=4,
                screencap_fn=safe_screencap,
                sleep_fn=sleep_with_stop,
            )
            if aborted_p or build_img is None:
                break

            if bid == "power_center":
                tab_entries = ocr_roi(context, build_img, f"{prefix}PowerTabs{round_suffix}", POWER_TABS_OCR_ROI)
                safe, guard_msg = verify_power_room_upgrade_tab_safe(build_img, tab_entries)
                if not safe:
                    state.add_guard_abort("guard", "power_center_guard", label, guard_msg, frame=build_img)
                    break

            panel_entries = ocr_roi(context, build_img, f"{prefix}BuildPanel_{bid}{round_suffix}", ROOM_BUILD_PANEL_ROI)
            btn_entries = ocr_roi(context, build_img, f"{prefix}BuildBtn_{bid}{round_suffix}", ROOM_BUILD_BUTTON_ROI)
            info = parse_room_build_panel(panel_entries, btn_entries)
            if not info["can_build"]:
                if round_idx == 0:
                    state.add_skipped("build", action_kind, label, f"条件未满足或已升级：{info['status_text'] or '不可建造'}")
                break

            req_coins = info["required_coins"]
            req_tickets = int(info["required_tickets"] or 0)
            if req_coins is None:
                state.add_guard_abort("guard", "building_cost_guard", label, "未能从建造面板解析所需铁盟币，按 fail-closed 拦截。", frame=build_img)
                break
            if not state.can_afford_coins(int(req_coins)):
                if round_idx == 0:
                    state.add_skipped(
                        "build",
                        action_kind,
                        label,
                        f"升级需 {int(req_coins):,} 币，触发保留底线（{state.reserve_coins:,}）暂缓。",
                    )
                break
            if state.live_tickets < req_tickets:
                if round_idx == 0:
                    state.add_skipped("build", action_kind, label, f"工票不足（需 {req_tickets:,}，现 {state.live_tickets:,}）。")
                break

            if bid == "power_center":
                re_tabs = ocr_roi(context, build_img, f"{prefix}PowerTabsConfirm{round_suffix}", POWER_TABS_OCR_ROI)
                safe2, guard_msg2 = verify_power_room_upgrade_tab_safe(build_img, re_tabs)
                if not safe2:
                    state.add_guard_abort("guard", "power_center_guard", label, guard_msg2, frame=build_img)
                    break

            if not tap_point(context, f"{prefix}ConfirmBuild_{bid}{round_suffix}", ROOM_BUILD_CONFIRM_POINT):
                break
            if not sleep_with_stop(context, POST_CONFIRM_DELAY):
                break
            after_img = safe_screencap(context)
            latest_after_img = after_img
            if after_img is not None:
                pop_entries = ocr_roi(context, after_img, f"{prefix}BuildPop_{bid}{round_suffix}", SHOP_CONFIRM_MODAL_ROI)
                pop_text = "".join(_clean_text(e.get("text")) for e in pop_entries if isinstance(e, dict))
                if "桦石" in pop_text:
                    tap_point(context, f"{prefix}BuildCancelHuashi_{bid}{round_suffix}", SHOP_MODAL_CANCEL_POINT)
                    sleep_with_stop(context, 0.7)
                    state.add_guard_abort("guard", "building_huashi_guard", label, "二级弹窗出现桦石字样，已强制取消。", frame=after_img)
                    break

                after_btn = ocr_roi(context, after_img, f"{prefix}BuildAfterBtn_{bid}{round_suffix}", ROOM_BUILD_BUTTON_ROI)
                still_open = bool(parse_room_build_panel([], after_btn)["can_build"])
                if still_open:
                    sleep_with_stop(context, 0.8)
                    after_img2 = safe_screencap(context)
                    if after_img2 is not None:
                        latest_after_img = after_img2
                        after_btn2 = ocr_roi(context, after_img2, f"{prefix}BuildAfterBtn2_{bid}{round_suffix}", ROOM_BUILD_BUTTON_ROI)
                        still_open = bool(parse_room_build_panel([], after_btn2)["can_build"])
                if still_open:
                    if round_idx == 0:
                        state.add_skipped("build", action_kind, label, "点击建造后建造面板仍未关闭，未确认升级成功。")
                    break

            state.spend_coins(int(req_coins))
            state.spend_tickets(req_tickets)
            state.upgraded_buildings[bid] = state.upgraded_buildings.get(bid, 0) + 1
            unlock_targets.discard(label)
            action_verb = "首建" if (is_unlock and round_idx == 0) else "升级"
            state.add_executed(
                "build",
                "building_unlock" if (is_unlock and round_idx == 0) else "building_upgrade",
                label,
                f"点击「建造」{action_verb}「{label}」（-{int(req_coins):,}币" + (f"、-{req_tickets:,}工票" if req_tickets else "") + "）",
                coins_delta=-int(req_coins),
                tickets_delta=-req_tickets,
            )
            if not state.can_afford_coins(10_000):
                break

        if need_exit_zoom and not is_stopping(context):
            if entered_build_panel:
                _exit_zoomed_panel_to_overview(context, f"{prefix}Done_{bid}", unzoom_pt)
            else:
                _unzoom_room_to_overview(context, f"{prefix}Done_{bid}", unzoom_pt)

    for bid, label, aliases, unzoom_pt in core_candidates:
        if is_stopping(context):
            break
        _run_building(bid, label, aliases, unzoom_pt)

    research_upgraded = state.upgraded_buildings.get("research_center", 0) > 0
    for bid, label, aliases, unzoom_pt in raw_specs:
        if is_stopping(context):
            break
        if (label in raw_allowed) or (research_upgraded and label in raw_research_blocked):
            _run_building(bid, label, aliases, unzoom_pt)


def _exec_expand_warehouses_coins_only(
    context: Context,
    state: _ExecState,
    prefix: str,
) -> None:
    if not state.can_afford_coins(10_000):
        state.add_skipped("buy", "warehouse_coin_expand", "双仓扩容", f"余额触及保留底线（{state.reserve_coins:,}），跳过扩仓。")
        return

    fresh = safe_screencap(context)
    if fresh is None:
        return
    dock_entries = ocr_roi(context, fresh, f"{prefix}WhExecDock", PRISON_BOTTOM_DOCK_ROI)
    wh_pt = find_dock_button_point(dock_entries, ("仓库",), PRISON_DOCK_WAREHOUSE_FALLBACK)
    if not tap_point(context, f"{prefix}ExecTapWh", wh_pt):
        return

    def _check_wh(frame: Any, idx: int) -> bool | None:
        entries = ocr_roi(context, frame, f"{prefix}ExecWhChk{idx}", WAREHOUSE_BODY_ROI)
        return True if is_warehouse_screen_entries(entries) else None

    wh_img, wh_ok, aborted = poll_screen(
        context,
        _check_wh,
        initial_delay=0.9,
        interval=0.45,
        max_checks=4,
        screencap_fn=safe_screencap,
        sleep_fn=sleep_with_stop,
    )
    if aborted:
        return
    if not wh_ok or wh_img is None:
        if wh_img is not None and not _is_on_prison_overview(context, wh_img, f"{prefix}ExecWhMiss"):
            _back_to_prison_overview(context, f"{prefix}ExecWhMissBack")
        state.add_skipped("buy", "warehouse_coin_expand", "双仓扩容", "未能进入仓库页面，跳过。")
        return

    max_batches = max(1, int(state.warehouse_batch_cap))
    for wh_label, expand_pt in (
        ("原料仓库扩容", WAREHOUSE_RAW_EXPAND_POINT),
        ("成品仓库扩容", WAREHOUSE_FIN_EXPAND_POINT),
    ):
        for batch_idx in range(max_batches):
            if is_stopping(context):
                break
            batch_suffix = "" if batch_idx == 0 else f"_b{batch_idx}"
            max_by_budget = max(0, (state.live_coins - state.reserve_coins) // 10_000)
            if max_by_budget <= 0:
                if batch_idx == 0:
                    state.add_skipped("buy", "warehouse_coin_expand", wh_label, f"预算触及底线（{state.reserve_coins:,}），跳过。")
                break

            if not tap_point(context, f"{prefix}TapExpand_{wh_label}{batch_suffix}", expand_pt):
                break
            if not sleep_with_stop(context, 1.1):
                break
            if not tap_point(context, f"{prefix}TapBuyCard_{wh_label}{batch_suffix}", WAREHOUSE_BUY_CARD_POINT):
                break

            def _check_modal_tabs(frame: Any, poll_idx: int) -> list[dict[str, Any]] | None:
                entries = ocr_roi(context, frame, f"{prefix}WhModalTabs_{wh_label}{batch_suffix}_{poll_idx}", WAREHOUSE_MODAL_TABS_ROI)
                joined = "".join(_clean_text(e.get("text")) for e in entries if isinstance(e, dict))
                if any(kw in joined for kw in ("铁盟币", "桦石", "剩余")) or has_warehouse_left_coin_price(entries):
                    return entries
                return None

            modal_img, polled_tabs, aborted_wh = poll_screen(
                context,
                _check_modal_tabs,
                initial_delay=1.1,
                interval=0.5,
                max_checks=4,
                screencap_fn=safe_screencap,
                sleep_fn=sleep_with_stop,
            )
            if aborted_wh or modal_img is None:
                break
            tab_entries = (
                polled_tabs
                if isinstance(polled_tabs, list)
                else ocr_roi(context, modal_img, f"{prefix}WhModalTabs_{wh_label}{batch_suffix}", WAREHOUSE_MODAL_TABS_ROI)
            )
            safe, guard_msg = verify_warehouse_coins_tab_safe(modal_img, tab_entries)
            if not safe:
                tap_point(context, f"{prefix}WhCancelGuard{batch_suffix}", WAREHOUSE_MODAL_CANCEL_POINT)
                sleep_with_stop(context, 0.7)
                tap_point(context, f"{prefix}WhExitOverlayGuard{batch_suffix}", WAREHOUSE_OVERLAY_EXIT_POINT)
                sleep_with_stop(context, 0.7)
                state.add_guard_abort("guard", "warehouse_huashi_guard", wh_label, guard_msg, frame=modal_img)
                break

            remaining = parse_warehouse_modal_remaining(tab_entries)
            if remaining is None and has_warehouse_left_coin_price(tab_entries):
                remaining = 1
            if remaining is None or remaining <= 0:
                tap_point(context, f"{prefix}WhCancelEmpty{batch_suffix}", WAREHOUSE_MODAL_CANCEL_POINT)
                sleep_with_stop(context, 0.7)
                tap_point(context, f"{prefix}WhExitOverlayEmpty{batch_suffix}", WAREHOUSE_OVERLAY_EXIT_POINT)
                sleep_with_stop(context, 0.7)
                if batch_idx == 0:
                    state.add_skipped("buy", "warehouse_coin_expand", wh_label, "铁盟币扩容剩余次数为 0 或未读到。")
                break

            clicks = min(10, remaining, max_by_budget)
            if clicks <= 0:
                tap_point(context, f"{prefix}WhCancelZero{batch_suffix}", WAREHOUSE_MODAL_CANCEL_POINT)
                sleep_with_stop(context, 0.7)
                tap_point(context, f"{prefix}WhExitOverlayZero{batch_suffix}", WAREHOUSE_OVERLAY_EXIT_POINT)
                sleep_with_stop(context, 0.7)
                break

            for plus_idx in range(clicks - 1):
                if is_stopping(context):
                    break
                tap_point(context, f"{prefix}WhPlus_{wh_label}{batch_suffix}_{plus_idx}", WAREHOUSE_MODAL_PLUS1_POINT)
                sleep_with_stop(context, STEP_TAP_DELAY)

            if not sleep_with_stop(context, 0.55):
                break
            pre_ok_img = safe_screencap(context)
            if pre_ok_img is None:
                tap_point(context, f"{prefix}WhCancelNoFrame{batch_suffix}", WAREHOUSE_MODAL_CANCEL_POINT)
                sleep_with_stop(context, 0.6)
                tap_point(context, f"{prefix}WhExitNoFrame{batch_suffix}", WAREHOUSE_OVERLAY_EXIT_POINT)
                break
            pre_tabs = ocr_roi(context, pre_ok_img, f"{prefix}WhReChk_{wh_label}{batch_suffix}", WAREHOUSE_MODAL_TABS_ROI)
            safe2, guard_msg2 = verify_warehouse_coins_tab_safe(pre_ok_img, pre_tabs)
            if not safe2:
                tap_point(context, f"{prefix}WhCancelGuard2{batch_suffix}", WAREHOUSE_MODAL_CANCEL_POINT)
                sleep_with_stop(context, 0.7)
                tap_point(context, f"{prefix}WhExitOverlayGuard2{batch_suffix}", WAREHOUSE_OVERLAY_EXIT_POINT)
                sleep_with_stop(context, 0.7)
                state.add_guard_abort("guard", "warehouse_huashi_guard", wh_label, guard_msg2, frame=pre_ok_img)
                break

            if not tap_point(context, f"{prefix}WhConfirm_{wh_label}{batch_suffix}", WAREHOUSE_MODAL_CONFIRM_POINT):
                break
            sleep_with_stop(context, POST_CONFIRM_DELAY)
            tap_point(context, f"{prefix}WhExitOverlayDone_{wh_label}{batch_suffix}", WAREHOUSE_OVERLAY_EXIT_POINT)

            def _check_back_wh_main(frame: Any, poll_idx: int) -> bool | None:
                entries = ocr_roi(context, frame, f"{prefix}WhExitWhChk_{wh_label}{batch_suffix}_{poll_idx}", WAREHOUSE_BODY_ROI)
                return True if is_warehouse_screen_entries(entries) else None

            _wh_back_img, wh_main_ok, _aborted_exit = poll_screen(
                context,
                _check_back_wh_main,
                initial_delay=0.75,
                interval=0.45,
                max_checks=3,
                screencap_fn=safe_screencap,
                sleep_fn=sleep_with_stop,
            )
            if not wh_main_ok and not is_stopping(context):
                tap_point(context, f"{prefix}WhExitOverlayRetry_{wh_label}{batch_suffix}", WAREHOUSE_OVERLAY_EXIT_POINT)
                sleep_with_stop(context, 0.8)
            spent = clicks * 10_000
            state.spend_coins(spent)
            state.add_executed(
                "buy",
                "warehouse_coin_expand",
                wh_label,
                f"左侧铁盟币扩容 ×{clicks} 次（-{spent:,}币）",
                coins_delta=-spent,
            )
            if remaining <= clicks or clicks < 10:
                break
            if batch_idx + 1 < max_batches:
                sleep_with_stop(context, 0.65)

    _back_to_prison_overview(context, f"{prefix}ExecWhDone")


def _exec_exchange_rush_recipes(
    context: Context,
    state: _ExecState,
    phase: str,
    prefix: str,
) -> None:
    if phase != "rush_leveling":
        return
    allow_recipes = state.is_enabled("shop_recipes")
    allow_items = state.is_enabled("shop_items")
    if not allow_recipes and not allow_items:
        return

    fresh = safe_screencap(context)
    if fresh is None:
        return
    dock_entries = ocr_roi(context, fresh, f"{prefix}ShopExecDock", PRISON_BOTTOM_DOCK_ROI)
    shop_pt = find_dock_button_point(dock_entries, ("兑换",), PRISON_DOCK_SHOP_FALLBACK)
    if not tap_point(context, f"{prefix}ExecTapShop", shop_pt):
        return

    def _check_shop(frame: Any, idx: int) -> bool | None:
        entries = ocr_roi(context, frame, f"{prefix}ExecShopChk{idx}", (100, 75, 1160, 590))
        return True if is_exchange_shop_entries(entries) else None

    shop_img, shop_ok, aborted = poll_screen(
        context,
        _check_shop,
        initial_delay=PANEL_POLL_INITIAL,
        interval=PANEL_POLL_INTERVAL,
        max_checks=4,
        screencap_fn=safe_screencap,
        sleep_fn=sleep_with_stop,
    )
    if aborted:
        return
    if not shop_ok or shop_img is None:
        if shop_img is not None and not _is_on_prison_overview(context, shop_img, f"{prefix}ExecShopMiss"):
            _back_to_prison_overview(context, f"{prefix}ExecShopBack")
        return

    tap_point(context, f"{prefix}ShopRecipesTab", SHOP_TAB_RECIPES_POINT)
    if not sleep_with_stop(context, 1.0):
        _back_to_prison_overview(context, f"{prefix}ExecShopStopBack")
        return
    fresh_shop_img = safe_screencap(context)
    cur_img = fresh_shop_img if fresh_shop_img is not None else shop_img
    top_vals = parse_exchange_shop_top_bar(
        ocr_roi(context, cur_img, f"{prefix}ExecShopTix", SHOP_WORK_TICKETS_ROI),
        ocr_roi(context, cur_img, f"{prefix}ExecShopCoins", SHOP_COINS_ROI),
    )
    if top_vals.get("work_tickets") is not None:
        state.live_tickets = int(top_vals["work_tickets"])
    if top_vals.get("coins") is not None:
        state.live_coins = int(top_vals["coins"])

    prev_tickets: int | None = top_vals.get("work_tickets")
    prev_coins: int | None = top_vals.get("coins")
    attempted_recipes: set[str] = set()
    bought = 0
    failed_modal = False

    def _confirm_and_verify_exchange(
        item_label: str,
        row_idx: int,
        exchange_pt: tuple[int, int],
        c_cost: int,
        t_cost: int,
        *,
        is_item: bool,
        buy_seq: int,
    ) -> tuple[bool, Any]:
        nonlocal prev_tickets, prev_coins
        tap_name = f"{prefix}TapExItem_{row_idx}" if is_item else f"{prefix}TapExchange_{row_idx}"
        if not tap_point(context, tap_name, exchange_pt):
            return False, None

        pop_tag = f"{prefix}ItemPop_{row_idx}" if is_item else f"{prefix}ShopPop_{row_idx}"

        def _check_shop_pop(frame: Any, poll_idx: int) -> list[dict[str, Any]] | None:
            entries = ocr_roi(context, frame, f"{pop_tag}_{poll_idx}", SHOP_CONFIRM_MODAL_ROI)
            joined = "".join(_clean_text(e.get("text")) for e in entries if isinstance(e, dict))
            if any(kw in joined for kw in ("确认消耗", "确定", "确认", "取消", "桦石")):
                return entries
            return None

        pop_img, polled_pop, aborted_pop = poll_screen(
            context,
            _check_shop_pop,
            initial_delay=1.1,
            interval=0.5,
            max_checks=4,
            screencap_fn=safe_screencap,
            sleep_fn=sleep_with_stop,
        )
        if aborted_pop or pop_img is None:
            return False, None
        pop_entries = polled_pop if isinstance(polled_pop, list) else []
        pop_text = "".join(_clean_text(e.get("text")) for e in pop_entries if isinstance(e, dict))
        if "桦石" in pop_text:
            tap_point(context, f"{prefix}ShopCancelHuashi", SHOP_MODAL_CANCEL_POINT)
            sleep_with_stop(context, 0.8)
            state.add_guard_abort("guard", "shop_huashi_guard", item_label, "兑换确认框检测到桦石字样，已取消。", frame=pop_img)
            return False, None

        confirm_pt = find_modal_confirm_button_point(pop_entries)
        if confirm_pt is None:
            tap_point(context, f"{prefix}ShopCancelNoConfirm_{row_idx}", SHOP_MODAL_CANCEL_POINT)
            sleep_with_stop(context, 0.8)
            state.add_skipped(
                "buy",
                "exchange_ticket_buy",
                item_label,
                "兑换确认弹窗未识别到底部「确定」按钮，已取消保护。",
            )
            return False, None

        ok_tag = f"{prefix}ItemPopOk_{row_idx}" if is_item else f"{prefix}ShopPopOk_{row_idx}"
        if not tap_point(context, ok_tag, confirm_pt):
            return False, None
        if not sleep_with_stop(context, POST_CONFIRM_DELAY):
            return False, None

        after_pop_img = safe_screencap(context)
        if after_pop_img is None:
            return False, None

        reward_entries = ocr_roi(
            context,
            after_pop_img,
            f"{prefix}ShopReward_{row_idx}",
            (220, 140, 840, 520),
        )
        reward_text = "".join(_clean_text(e.get("text")) for e in reward_entries if isinstance(e, dict))
        if any(kw in reward_text for kw in ("获得", "恭喜", "点击空白")):
            tap_point(context, f"{prefix}ShopRewardDismiss_{row_idx}", (640, 660))
            sleep_with_stop(context, 0.9)
            refreshed = safe_screencap(context)
            if refreshed is not None:
                after_pop_img = refreshed

        tix_tag = f"{prefix}ItemPostTix_{buy_seq}" if is_item else f"{prefix}ShopPostTix_{buy_seq}"
        coins_tag = f"{prefix}ItemPostCoins_{buy_seq}" if is_item else f"{prefix}ShopPostCoins_{buy_seq}"
        post_vals = parse_exchange_shop_top_bar(
            ocr_roi(context, after_pop_img, tix_tag, SHOP_WORK_TICKETS_ROI),
            ocr_roi(context, after_pop_img, coins_tag, SHOP_COINS_ROI),
        )
        post_tix = post_vals.get("work_tickets")
        post_coins = post_vals.get("coins")
        has_post_reading = (post_tix is not None) or (post_coins is not None)

        confirmed_purchase = False
        if has_post_reading:
            tix_dropped = (post_tix is not None) and (prev_tickets is not None) and (post_tix < prev_tickets)
            coins_dropped = (post_coins is not None) and (prev_coins is not None) and (post_coins < prev_coins)
            if tix_dropped or coins_dropped:
                confirmed_purchase = True
            else:
                still_pop = ocr_roi(
                    context,
                    after_pop_img,
                    f"{prefix}ShopStuckChk_{row_idx}",
                    SHOP_CONFIRM_MODAL_ROI,
                )
                still_txt = "".join(_clean_text(e.get("text")) for e in still_pop if isinstance(e, dict))
                if find_modal_confirm_button_point(still_pop) is not None or any(kw in still_txt for kw in ("确认消耗", "取消")):
                    tap_point(context, f"{prefix}ShopCancelStuck_{row_idx}", SHOP_MODAL_CANCEL_POINT)
                    sleep_with_stop(context, 0.8)
                state.add_skipped(
                    "buy",
                    "exchange_ticket_buy",
                    item_label,
                    "点击确定后余额与工票未变化，未确认兑换成功。",
                )
                return False, None
        else:
            stuck_entries = ocr_roi(
                context,
                after_pop_img,
                f"{prefix}ShopStuckChk_{row_idx}",
                SHOP_CONFIRM_MODAL_ROI,
            )
            if find_modal_confirm_button_point(stuck_entries) is not None:
                tap_point(context, f"{prefix}ShopCancelNoTop_{row_idx}", SHOP_MODAL_CANCEL_POINT)
                sleep_with_stop(context, 0.8)
                state.add_skipped(
                    "buy",
                    "exchange_ticket_buy",
                    item_label,
                    "点击确定后弹窗仍未关闭，未确认兑换成功。",
                )
                return False, None
            confirmed_purchase = True

        if not confirmed_purchase:
            return False, after_pop_img

        if post_coins is not None:
            state.live_coins = int(post_coins)
            prev_coins = int(post_coins)
        else:
            state.spend_coins(c_cost)
            if prev_coins is not None:
                prev_coins = max(0, prev_coins - c_cost)
        if post_tix is not None:
            state.live_tickets = int(post_tix)
            prev_tickets = int(post_tix)
        else:
            state.spend_tickets(t_cost)
            if prev_tickets is not None:
                prev_tickets = max(0, prev_tickets - t_cost)
        detail = (
            f"兑换商店道具「{item_label}」（-{t_cost:,}工票）"
            if is_item
            else f"兑换冲级研发配方「{item_label}」（-{c_cost:,}币、-{t_cost:,}工票）"
        )
        state.add_executed(
            "buy",
            "exchange_ticket_buy",
            item_label,
            detail,
            coins_delta=-c_cost,
            tickets_delta=-t_cost,
        )
        return True, after_pop_img

    while allow_recipes and bought < 3 and not is_stopping(context):
        body_entries = ocr_roi(context, cur_img, f"{prefix}ExecShopBody_{bought}", SHOP_BODY_ROI)
        rows = parse_exchange_shop_recipe_rows(body_entries)
        picked_row: dict[str, Any] | None = None
        for row in rows:
            recipe_name = str(row["recipe_name"])
            if recipe_name in attempted_recipes:
                continue
            if row["locked"] or row["remaining"] <= 0 or not row["base_good_name"]:
                continue
            c_cost = int(row["coin_cost"])
            t_cost = int(row["ticket_cost"])
            if not state.can_afford_coins(c_cost) or state.live_tickets < t_cost:
                attempted_recipes.add(recipe_name)
                state.add_skipped(
                    "buy",
                    "exchange_ticket_buy",
                    recipe_name,
                    f"预算或工票不足（需 {c_cost:,}币 + {t_cost:,}工票）。",
                )
                continue
            picked_row = row
            break

        if picked_row is None:
            break

        recipe_name = str(picked_row["recipe_name"])
        attempted_recipes.add(recipe_name)
        ok_buy, _after = _confirm_and_verify_exchange(
            recipe_name,
            int(picked_row["row_index"]),
            picked_row["exchange_point"],
            int(picked_row["coin_cost"]),
            int(picked_row["ticket_cost"]),
            is_item=False,
            buy_seq=bought,
        )
        if not ok_buy:
            failed_modal = True
            break
        bought += 1

        if not sleep_with_stop(context, 0.65):
            break
        next_img = safe_screencap(context)
        if next_img is None:
            break
        cur_img = next_img

    # 余票充足（>= 4,000）且「兑换道具」页签可见时，自动切页换一次性「拉普拉斯协议」与「自观测胶卷」
    if allow_items and not failed_modal and state.live_tickets >= 4_000 and not is_stopping(context):
        tab_entries = ocr_roi(context, cur_img, f"{prefix}ShopItemsTabChk", (980, 80, 260, 58))
        tab_txt = "".join(_clean_text(e.get("text")) for e in tab_entries if isinstance(e, dict))
        if "兑换道具" in tab_txt and tap_point(context, f"{prefix}ShopItemsTab", SHOP_TAB_ITEMS_POINT) and sleep_with_stop(context, 1.0):
            items_img = safe_screencap(context)
            bought_items = 0
            attempted_items: set[str] = set()
            for scroll_round in range(2):
                if items_img is None or bought_items >= 2 or state.live_tickets < 4_000 or is_stopping(context):
                    break
                item_entries = ocr_roi(context, items_img, f"{prefix}ShopItemsBody_{scroll_round}", SHOP_BODY_ROI)
                item_rows = parse_exchange_shop_item_rows(item_entries)
                picked_item = next(
                    (
                        r
                        for r in item_rows
                        if r["item_name"] not in attempted_items and state.live_tickets >= int(r["ticket_cost"])
                    ),
                    None,
                )
                if picked_item is not None:
                    attempted_items.add(str(picked_item["item_name"]))
                    ok_item, post_item_img = _confirm_and_verify_exchange(
                        str(picked_item["item_name"]),
                        int(picked_item["row_index"]),
                        picked_item["exchange_point"],
                        0,
                        int(picked_item["ticket_cost"]),
                        is_item=True,
                        buy_seq=bought_items,
                    )
                    if not ok_item:
                        break
                    bought_items += 1
                    items_img = post_item_img if post_item_img is not None else safe_screencap(context)
                    continue
                if scroll_round == 0:
                    if not swipe_points(
                        context,
                        f"{prefix}ShopItemsScroll",
                        SHOP_ITEMS_SCROLL_DOWN_SWIPE[0],
                        SHOP_ITEMS_SCROLL_DOWN_SWIPE[1],
                        duration=SWIPE_DURATION_MS,
                        end_hold=SWIPE_END_HOLD_MS,
                    ) or not sleep_with_stop(context, 0.9):
                        break
                    items_img = safe_screencap(context)

    _back_to_prison_overview(context, f"{prefix}ExecShopDone")


def _exec_predeposit_raw_workshops(
    context: Context,
    state: _ExecState,
    snapshot: AccountSnapshot,
    predeposit_target: int,
    prefix: str,
) -> None:
    allow_predeposit = state.is_enabled("raw_predeposit")
    allow_raw_start = state.is_enabled("raw_start") and state.raw_worker_mode != "predeposit_only"
    if not allow_predeposit and not allow_raw_start:
        return

    raw_specs = (
        ("raw_sewing", "缝纫工具原料车间", ("缝纫工具原料车间", "缝纫工具车间"), ROOM_UNZOOM_LEFT_COL_POINT),
        ("raw_synthetic", "人造纤维原料车间", ("人造纤维原料车间", "人造纤维车间"), ROOM_UNZOOM_RIGHT_COL_POINT),
        ("raw_plant", "植物纤维原料车间", ("植物纤维原料车间", "植物纤维车间"), ROOM_UNZOOM_LEFT_COL_POINT),
        ("raw_animal", "动物纤维原料车间", ("动物纤维原料车间", "动物纤维车间"), ROOM_UNZOOM_RIGHT_COL_POINT),
    )
    built_raw_ids = [
        bid
        for bid, _label, _aliases, _pt in raw_specs
        if max(int(snapshot.prison.buildings.get(bid, 0)), int(state.upgraded_buildings.get(bid, 0))) >= 1
    ]
    if not built_raw_ids:
        return

    alloc = plan_prisoner_worker_allocation(
        total_prisoners=int(snapshot.prison.prisoners_current) + int(state.prisoners_checked_in),
        built_raw_count=len(built_raw_ids),
        raw_warehouse_used=int(snapshot.prison.raw_warehouse_used),
        prod_ws_count=int(snapshot.prison.production_workshop_count),
        mode=state.raw_worker_mode,
    )
    raw_per_room = int(alloc["raw_per_room"]) if allow_raw_start else 0

    for bid, label, aliases, unzoom_pt in raw_specs:
        if is_stopping(context):
            break
        if bid not in built_raw_ids:
            continue

        room_pt, locate_status = _pan_and_find_room(context, f"{prefix}Pre_{bid}", PRISON_RIGHT_WING_PAN_SWIPE, aliases)
        if room_pt is None:
            if locate_status == "pan_stalled" and not _ensure_on_prison_overview(context, f"{prefix}PreStall_{bid}"):
                state.add_skipped("do", "raw_predeposit", label, "整顿中心画面拖拽无响应，已中止后续车间搜索。")
                break
            continue
        if not tap_point(context, f"{prefix}TapPreRoom_{bid}", room_pt):
            break

        def _check_pre_bubble(frame: Any, poll_idx: int) -> list[dict[str, Any]] | None:
            entries = ocr_roi(context, frame, f"{prefix}PreBubble_{bid}_{poll_idx}", ROOM_BUBBLE_ROI)
            joined = "".join(_clean_text(e.get("text")) for e in entries if isinstance(e, dict))
            if "生产" in joined or "详情" in joined:
                return entries
            return None

        bubble_img, polled_pre_b, aborted_pb = poll_screen(
            context,
            _check_pre_bubble,
            initial_delay=PANEL_POLL_INITIAL,
            interval=PANEL_POLL_INTERVAL,
            max_checks=4,
            screencap_fn=safe_screencap,
            sleep_fn=sleep_with_stop,
        )
        if aborted_pb or bubble_img is None:
            break
        bubble_entries = polled_pre_b if isinstance(polled_pre_b, list) else []
        prod_pt = find_room_bubble_point(bubble_entries, "生产", ROOM_BUBBLE_TOP_FALLBACK)
        if prod_pt is None:
            if not _is_on_prison_overview(context, bubble_img, f"{prefix}PreUnzoomChk_{bid}"):
                _unzoom_room_to_overview(context, f"{prefix}PreUnzoom_{bid}", unzoom_pt)
            continue

        if not tap_point(context, f"{prefix}TapPreProd_{bid}", prod_pt):
            break

        def _check_pre_bal(frame: Any, poll_idx: int) -> tuple[int] | None:
            bal = parse_predeposit_balance(
                ocr_roi(context, frame, f"{prefix}PreBal_{bid}_{poll_idx}", RAW_PREDEPOSIT_BAL_ROI)
            )
            return (bal,) if bal is not None else None

        panel_img, polled_bal, aborted_bal = poll_screen(
            context,
            _check_pre_bal,
            initial_delay=PANEL_POLL_INITIAL,
            interval=PANEL_POLL_INTERVAL,
            max_checks=4,
            screencap_fn=safe_screencap,
            sleep_fn=sleep_with_stop,
        )
        if aborted_bal or panel_img is None:
            break
        cur_bal = (
            polled_bal[0]
            if isinstance(polled_bal, tuple)
            else parse_predeposit_balance(ocr_roi(context, panel_img, f"{prefix}PreBal_{bid}", RAW_PREDEPOSIT_BAL_ROI))
        )

        effective_bal = cur_bal if cur_bal is not None else 0
        if (
            allow_predeposit
            and predeposit_target > 1
            and cur_bal is not None
            and cur_bal < predeposit_target
        ):
            if not state.can_afford_coins(predeposit_target):
                state.add_skipped(
                    "do",
                    "raw_predeposit",
                    label,
                    f"可用余额不足 {predeposit_target:,}（保底线 {state.reserve_coins:,}），跳过预存。",
                )
            elif tap_point(context, f"{prefix}TapPreBtn_{bid}", RAW_PREDEPOSIT_BTN_POINT):
                def _check_pre_modal(frame: Any, poll_idx: int) -> tuple[int, int] | None:
                    return parse_predeposit_modal_qty(
                        ocr_roi(context, frame, f"{prefix}PreModalQty_{bid}_{poll_idx}", RAW_PREDEPOSIT_MODAL_QTY_ROI)
                    )

                modal_img, qty_pair, aborted_pm = poll_screen(
                    context,
                    _check_pre_modal,
                    initial_delay=1.0,
                    interval=0.5,
                    max_checks=4,
                    screencap_fn=safe_screencap,
                    sleep_fn=sleep_with_stop,
                )
                if aborted_pm or modal_img is None:
                    break
                if qty_pair is None:
                    tap_point(context, f"{prefix}PreCancelMissing_{bid}", RAW_PREDEPOSIT_CANCEL_POINT)
                    sleep_with_stop(context, 0.7)
                    state.add_skipped("do", "raw_predeposit", label, "未读取到预存数量上限，已取消。")
                else:
                    _cur_qty, max_qty = qty_pair
                    target_x = compute_predeposit_slider_x(predeposit_target, max_qty)
                    if swipe_points(
                        context,
                        f"{prefix}PreSlide_{bid}",
                        (506, RAW_PREDEPOSIT_SLIDER_Y),
                        (target_x, RAW_PREDEPOSIT_SLIDER_Y),
                        duration=SWIPE_DURATION_MS,
                        end_hold=SWIPE_END_HOLD_MS,
                    ) and sleep_with_stop(context, 0.9):
                        slid_img = safe_screencap(context)
                        after_pair = (
                            parse_predeposit_modal_qty(ocr_roi(context, slid_img, f"{prefix}PreSlidQty_{bid}", RAW_PREDEPOSIT_MODAL_QTY_ROI))
                            if slid_img is not None
                            else None
                        )
                        if (
                            after_pair is None
                            or after_pair[0] <= 0
                            or after_pair[0] > int(predeposit_target * 1.35)
                            or not state.can_afford_coins(after_pair[0])
                        ):
                            tap_point(context, f"{prefix}PreCancelSlid_{bid}", RAW_PREDEPOSIT_CANCEL_POINT)
                            sleep_with_stop(context, 0.7)
                            state.add_skipped("do", "raw_predeposit", label, f"滑块校准结果异常（{after_pair}），已安全取消。")
                        else:
                            deposit_coins = int(after_pair[0])
                            if tap_point(context, f"{prefix}PreConfirm_{bid}", RAW_PREDEPOSIT_CONFIRM_POINT):
                                sleep_with_stop(context, POST_CONFIRM_DELAY)
                                post_img = safe_screencap(context)
                                new_bal = (
                                    parse_predeposit_balance(
                                        ocr_roi(context, post_img, f"{prefix}PreAfterBal_{bid}", RAW_PREDEPOSIT_BAL_ROI)
                                    )
                                    if post_img is not None
                                    else None
                                )
                                if post_img is not None and (new_bal is None or new_bal > cur_bal):
                                    panel_img = post_img
                                    effective_bal = new_bal if new_bal is not None else (cur_bal + deposit_coins)
                                    state.spend_coins(deposit_coins)
                                    state.add_executed(
                                        "do",
                                        "raw_predeposit",
                                        label,
                                        f"为「{label}」预存 {deposit_coins:,} 铁盟币",
                                        coins_delta=-deposit_coins,
                                    )
                                else:
                                    state.add_skipped("do", "raw_predeposit", label, "点击确定后存量未增加，未确认预存成功。")

        # 自动配员并启动原料车间采集（若已经在生产中，绝不打断）
        if allow_raw_start and panel_img is not None and not is_stopping(context):
            prod_status = parse_raw_workshop_prod_status(
                ocr_roi(context, panel_img, f"{prefix}RawAct_{bid}", RAW_PROD_ACTION_ROI),
                ocr_roi(context, panel_img, f"{prefix}RawWorkers_{bid}", RAW_PROD_WORKERS_ROI),
            )
            if (not prod_status["running"]) and raw_per_room > 0 and effective_bal > 0:
                picked_count = int(prod_status["assigned"])
                if picked_count == 0 and tap_point(context, f"{prefix}RawSelPrisoner_{bid}", RAW_PROD_SELECT_PRISONER_POINT):
                    def _check_picker(frame: Any, poll_idx: int) -> list[dict[str, Any]] | None:
                        entries = ocr_roi(context, frame, f"{prefix}RawPickGrid_{bid}_{poll_idx}", RAW_PROD_PICKER_GRID_ROI)
                        if entries:
                            return entries
                        cnt = ocr_roi(context, frame, f"{prefix}RawPickCnt_{bid}_{poll_idx}", RAW_PROD_PICKER_COUNT_ROI)
                        if cnt:
                            return []
                        return None

                    picker_img, polled_grid, aborted_pk = poll_screen(
                        context,
                        _check_picker,
                        initial_delay=0.9,
                        interval=0.5,
                        max_checks=3,
                        screencap_fn=safe_screencap,
                        sleep_fn=sleep_with_stop,
                    )
                    if not aborted_pk and picker_img is not None:
                        grid_entries = (
                            polled_grid
                            if isinstance(polled_grid, list)
                            else ocr_roi(context, picker_img, f"{prefix}RawPickGrid_{bid}", RAW_PROD_PICKER_GRID_ROI)
                        )
                        idle_pts = find_idle_prisoner_card_points(grid_entries, max_pick=raw_per_room)
                        if idle_pts:
                            for idx_p, card_pt in enumerate(idle_pts):
                                if not tap_point(context, f"{prefix}RawPickCard_{bid}_{idx_p}", card_pt):
                                    break
                                sleep_with_stop(context, 0.45)
                            if tap_point(context, f"{prefix}RawPickOk_{bid}", RAW_PROD_PICKER_CONFIRM_POINT):
                                sleep_with_stop(context, 1.0)
                                refreshed = safe_screencap(context)
                                if refreshed is not None:
                                    panel_img = refreshed
                                picked_count = len(idle_pts)
                        else:
                            tap_point(context, f"{prefix}RawPickCancel_{bid}", PRISON_BACK_POINT)
                            sleep_with_stop(context, 0.9)
                            state.add_skipped(
                                "do",
                                "raw_start_production",
                                label,
                                "当前无空闲可用囚犯，暂缓启动原料车间采集。",
                            )

                if panel_img is not None and picked_count > 0 and not is_stopping(context):
                    post_status = parse_raw_workshop_prod_status(
                        ocr_roi(context, panel_img, f"{prefix}RawActRe_{bid}", RAW_PROD_ACTION_ROI),
                        ocr_roi(context, panel_img, f"{prefix}RawWorkersRe_{bid}", RAW_PROD_WORKERS_ROI),
                    )
                    if post_status["can_start"] and tap_point(context, f"{prefix}RawStart_{bid}", RAW_PROD_START_POINT):
                        sleep_with_stop(context, POST_CONFIRM_DELAY)
                        started_img = safe_screencap(context)
                        verified_run = True
                        if started_img is not None:
                            chk_status = parse_raw_workshop_prod_status(
                                ocr_roi(context, started_img, f"{prefix}RawAfterAct_{bid}", RAW_PROD_ACTION_ROI),
                                ocr_roi(context, started_img, f"{prefix}RawAfterWorkers_{bid}", RAW_PROD_WORKERS_ROI),
                            )
                            banner_txt = "".join(
                                _clean_text(e.get("text"))
                                for e in ocr_roi(context, started_img, f"{prefix}RawBanner_{bid}", (420, 310, 440, 100))
                                if isinstance(e, dict)
                            )
                            if not chk_status["running"] and "生产开始" not in banner_txt and chk_status["can_start"]:
                                verified_run = False
                        if verified_run:
                            state.add_executed(
                                "do",
                                "raw_start_production",
                                label,
                                f"为「{label}」分配 {picked_count} 名囚犯并启动采集",
                            )
                        else:
                            state.add_skipped("do", "raw_start_production", label, "点击开始生产后未确认进入运行态。")

        _exit_zoomed_panel_to_overview(context, f"{prefix}PreDone_{bid}", unzoom_pt)


def _exec_start_workshop_production(
    context: Context,
    state: _ExecState,
    snapshot: AccountSnapshot,
    execution_plan: PrisonExecutionPlan,
    prefix: str,
    auto_scope: str = "full_safe",
) -> None:
    allow_edit_team = state.is_enabled("ws_edit_team")
    allow_start_prod = state.is_enabled("ws_start_prod")
    live_research_lv = int(snapshot.prison.buildings.get("research_center", 0)) + int(
        state.upgraded_buildings.get("research_center", 0)
    )
    allow_machine_up = (
        state.is_enabled("ws_machine_upgrade")
        and auto_scope != "orders_and_prod"
        and live_research_lv >= 6
        and state.can_afford_coins(10_000)
        and state.live_tickets >= 100
    )
    if not allow_edit_team and not allow_machine_up and not allow_start_prod:
        return

    preferred_targets = [
        s.target for s in execution_plan.do_actions if s.allowed and s.action_type == "produce_good"
    ]
    if allow_start_prod and not preferred_targets and not allow_edit_team and not allow_machine_up:
        state.add_skipped("do", "produce_good", "生产车间", "暂无推荐的排产目标。")
        return

    total_prisoners = int(snapshot.prison.prisoners_current) + int(state.prisoners_checked_in)

    ws_specs: list[tuple[str, tuple[str, ...]]] = [("1号生产车间", ("1号生产车间",))]
    if snapshot.prison.production_workshop_count >= 2:
        ws_specs.append(("2号生产车间", ("2号生产车间",)))

    started_goods: set[str] = set()

    for ws_label, aliases in ws_specs:
        if is_stopping(context):
            break
        ws_pt, status = _pan_and_find_room(context, f"{prefix}Ws_{ws_label}", PRISON_UPPER_WING_PAN_SWIPE, aliases)
        if ws_pt is None:
            if status == "pan_stalled" and not _ensure_on_prison_overview(context, f"{prefix}WsStall_{ws_label}"):
                state.add_skipped("do", "produce_good", ws_label, "整顿中心画面拖拽无响应，已中止后续车间搜索。")
                break
            if ws_label == "1号生产车间":
                state.add_skipped("do", "produce_good", ws_label, f"上翼未检测到可用「{ws_label}」（{status}）。")
            continue

        if not tap_point(context, f"{prefix}TapWs_{ws_label}", ws_pt):
            break

        detected_edit_pt: list[tuple[int, int]] = []

        def _check_ws_interior(frame: Any, poll_idx: int) -> tuple[int, int] | None:
            entries = ocr_roi(context, frame, f"{prefix}WsInterior_{ws_label}_{poll_idx}", WORKSHOP_INTERIOR_CHECK_ROI)
            for entry in entries:
                if "车间编辑" in _clean_text(entry.get("text")):
                    ept = _entry_center(entry) or WORKSHOP_ENTER_EDIT_POINT
                    if ept[1] >= 650:
                        ept = (ept[0], max(615, ept[1] - 48))
                    if not detected_edit_pt:
                        detected_edit_pt.append(ept)
            for entry in entries:
                if "生产" in _clean_text(entry.get("text")):
                    pt = _entry_center(entry) or WORKSHOP_ENTER_PROD_POINT
                    if pt[1] >= 650:
                        pt = (pt[0], max(615, pt[1] - 48))
                    return pt
            joined = "".join(_clean_text(e.get("text")) for e in entries if isinstance(e, dict))
            if "车间编辑" in joined:
                return WORKSHOP_ENTER_PROD_POINT
            bubble_entries = ocr_roi(context, frame, f"{prefix}WsBubble_{ws_label}_{poll_idx}", ROOM_BUBBLE_ROI)
            return find_room_bubble_point(bubble_entries, "生产", WORKSHOP_ENTER_PROD_POINT)

        room_img, prod_enter_pt, aborted_ws = poll_screen(
            context,
            _check_ws_interior,
            initial_delay=1.4,
            interval=PANEL_POLL_INTERVAL,
            max_checks=PANEL_POLL_CHECKS,
            screencap_fn=safe_screencap,
            sleep_fn=sleep_with_stop,
        )
        if aborted_ws or room_img is None:
            break
        if prod_enter_pt is None:
            state.add_skipped("do", "produce_good", ws_label, "未能确认「生产」按钮。")
            _ensure_on_prison_overview(context, f"{prefix}WsMiss_{ws_label}")
            continue

        leader_top_entries = ocr_roi(context, room_img, f"{prefix}WsLeaderTop_{ws_label}", WS_EDIT_LEADER_TOP_ROI)
        leader_unset = has_unset_workshop_leader(leader_top_entries)
        leader_set = has_workshop_leader_set(leader_top_entries)
        need_team_edit = allow_edit_team and (
            leader_unset
            or state.prisoners_checked_in > 0
            or (not leader_set and total_prisoners > 0)
        )
        if allow_edit_team and leader_set and not need_team_edit and not allow_machine_up:
            if state.diag is not None:
                state.diag.record("exec", "ws_edit_skipped", f"{ws_label}: 已有工位且组长已设，跳过车间编辑")
        if detected_edit_pt and (need_team_edit or allow_machine_up):
            if tap_point(context, f"{prefix}TapWsEdit_{ws_label}", detected_edit_pt[0]):
                def _check_ws_edit(frame: Any, poll_idx: int) -> bool | None:
                    e_entries = ocr_roi(context, frame, f"{prefix}WsEditChk_{ws_label}_{poll_idx}", WS_EDIT_PANEL_CHECK_ROI)
                    e_txt = "".join(_clean_text(e.get("text")) for e in e_entries if isinstance(e, dict))
                    if any(kw in e_txt for kw in ("快速编队", "切换机器")):
                        return True
                    return None

                edit_img, edit_ok, aborted_ed = poll_screen(
                    context,
                    _check_ws_edit,
                    initial_delay=1.0,
                    interval=0.5,
                    max_checks=4,
                    screencap_fn=safe_screencap,
                    sleep_fn=sleep_with_stop,
                )
                if aborted_ed:
                    break
                if edit_ok and edit_img is not None:
                    edited_anything = False
                    if need_team_edit and total_prisoners > 0 and tap_point(context, f"{prefix}TapQuickTeam_{ws_label}", WS_EDIT_QUICK_TEAM_POINT):
                        def _check_qt(frame: Any, poll_idx: int) -> list[dict[str, Any]] | None:
                            c_entries = ocr_roi(context, frame, f"{prefix}QtCnt_{ws_label}_{poll_idx}", RAW_PROD_PICKER_COUNT_ROI)
                            if any(kw in "".join(_clean_text(e.get("text")) for e in c_entries if isinstance(e, dict)) for kw in ("囚犯", "/")):
                                return c_entries
                            return None

                        qt_img, qt_cnt_entries, aborted_qt = poll_screen(
                            context,
                            _check_qt,
                            initial_delay=0.9,
                            interval=0.5,
                            max_checks=3,
                            screencap_fn=safe_screencap,
                            sleep_fn=sleep_with_stop,
                        )
                        if aborted_qt:
                            break
                        if qt_img is not None and qt_cnt_entries is not None:
                            cnt_txt = "".join(_clean_text(e.get("text")) for e in qt_cnt_entries if isinstance(e, dict))
                            cnt_status = parse_raw_workshop_prod_status([], [{"text": cnt_txt}])
                            ws_assigned = int(cnt_status["assigned"])
                            ws_cap = int(cnt_status["capacity"])
                            did_pick_qt = False
                            if ws_assigned < ws_cap:
                                qt_grid = ocr_roi(context, qt_img, f"{prefix}QtGrid_{ws_label}", RAW_PROD_PICKER_GRID_ROI)
                                idle_pts = find_idle_prisoner_card_points(qt_grid, max_pick=ws_cap - ws_assigned)
                                if idle_pts:
                                    for idx_q, q_pt in enumerate(idle_pts):
                                        if not tap_point(context, f"{prefix}QtCard_{ws_label}_{idx_q}", q_pt):
                                            break
                                        sleep_with_stop(context, 0.45)
                                    if tap_point(context, f"{prefix}QtConfirm_{ws_label}", RAW_PROD_PICKER_CONFIRM_POINT):
                                        sleep_with_stop(context, 1.0)
                                        edited_anything = True
                                        did_pick_qt = True
                                        state.add_executed(
                                            "do",
                                            "ws_assign_workers",
                                            ws_label,
                                            f"为「{ws_label}」编入 {len(idle_pts)} 名空闲囚犯",
                                        )
                            if not did_pick_qt:
                                tap_point(context, f"{prefix}QtBack_{ws_label}", PRISON_BACK_POINT)
                                sleep_with_stop(context, 0.9)
                            ref_ed = safe_screencap(context)
                            if ref_ed is not None:
                                edit_img = ref_ed

                    if allow_edit_team and edit_img is not None and has_unset_workshop_leader(
                        ocr_roi(context, edit_img, f"{prefix}WsEditLeaderChk_{ws_label}", WS_EDIT_LEADER_TOP_ROI)
                    ):
                        for slot_idx, slot_pt in enumerate(WS_EDIT_MACHINE_SLOT_CENTERS):
                            if is_stopping(context):
                                break
                            if not tap_point(context, f"{prefix}WsSlot{slot_idx}Leader_{ws_label}", slot_pt):
                                break
                            if not sleep_with_stop(context, 0.55):
                                break
                            slot_img = safe_screencap(context)
                            if slot_img is None:
                                continue
                            sl_entries = ocr_roi(context, slot_img, f"{prefix}WsSetLeaderBtn_{ws_label}_{slot_idx}", WS_EDIT_SET_LEADER_ROI)
                            sl_pt: tuple[int, int] | None = None
                            for entry in _merge_horizontal_adjacent(sl_entries, max_gap_x=12, max_row_diff=12.0):
                                if "设为组长" in _clean_text(entry.get("text")):
                                    sl_pt = _entry_center(entry) or WS_EDIT_SET_LEADER_POINT
                                    break
                            if sl_pt is not None and tap_point(context, f"{prefix}WsSetLeader_{ws_label}", sl_pt):
                                sleep_with_stop(context, 0.85)
                                edited_anything = True
                                state.add_executed("do", "ws_set_leader", ws_label, f"为「{ws_label}」指派车间组长")
                                break

                    if allow_machine_up and not is_stopping(context):
                        machine_ups = 0
                        for slot_idx, slot_pt in enumerate(WS_EDIT_MACHINE_SLOT_CENTERS):
                            if (
                                machine_ups >= 3
                                or not state.can_afford_coins(10_000)
                                or state.live_tickets < 100
                                or is_stopping(context)
                            ):
                                break
                            if not tap_point(context, f"{prefix}WsMachSlot_{ws_label}_{slot_idx}", slot_pt):
                                break
                            if not sleep_with_stop(context, 0.55):
                                break
                            slot_img = safe_screencap(context)
                            if slot_img is None:
                                break
                            cost_entries = ocr_roi(context, slot_img, f"{prefix}MachCost_{ws_label}_{slot_idx}", WS_EDIT_MACHINE_COST_ROI)
                            btn_entries = ocr_roi(context, slot_img, f"{prefix}MachBtn_{ws_label}_{slot_idx}", WS_EDIT_MACHINE_UPGRADE_ROI)
                            m_info = parse_workshop_machine_upgrade_cost(cost_entries, btn_entries)
                            if m_info["huashi_blocked"]:
                                state.add_guard_abort("guard", "ws_machine_huashi_guard", f"{ws_label}#槽{slot_idx + 1}", "机台升级检测到桦石消耗，已拦截。", frame=slot_img)
                                break
                            if not m_info["can_upgrade"]:
                                continue
                            req_c = m_info["required_coins"]
                            req_t = int(m_info["required_tickets"] or 0)
                            if req_c is None:
                                continue
                            if not state.can_afford_coins(int(req_c)) or state.live_tickets < req_t:
                                break
                            if not tap_point(context, f"{prefix}MachUpgrade_{ws_label}_{slot_idx}", WS_EDIT_MACHINE_UPGRADE_POINT):
                                break
                            if not sleep_with_stop(context, POST_CONFIRM_DELAY):
                                break
                            after_m = safe_screencap(context)
                            if after_m is not None:
                                pop_entries = ocr_roi(context, after_m, f"{prefix}MachPop_{ws_label}_{slot_idx}", SHOP_CONFIRM_MODAL_ROI)
                                pop_txt = "".join(_clean_text(e.get("text")) for e in pop_entries if isinstance(e, dict))
                                if "桦石" in pop_txt:
                                    tap_point(context, f"{prefix}MachCancelHuashi_{ws_label}_{slot_idx}", SHOP_MODAL_CANCEL_POINT)
                                    sleep_with_stop(context, 0.7)
                                    state.add_guard_abort("guard", "ws_machine_huashi_guard", f"{ws_label}#槽{slot_idx + 1}", "机台升级弹窗检测到桦石字样，已强制取消。", frame=after_m)
                                    break
                                c_pt = find_modal_confirm_button_point(pop_entries)
                                if c_pt is not None:
                                    tap_point(context, f"{prefix}MachPopOk_{ws_label}_{slot_idx}", c_pt)
                                    sleep_with_stop(context, POST_CONFIRM_DELAY)
                            state.spend_coins(int(req_c))
                            state.spend_tickets(req_t)
                            machine_ups += 1
                            edited_anything = True
                            state.add_executed(
                                "build",
                                "ws_machine_upgrade",
                                f"{ws_label}#机台{slot_idx + 1}",
                                f"升级「{ws_label}」#{slot_idx + 1} 缝纫机（-{int(req_c):,}币" + (f"、-{req_t:,}工票" if req_t else "") + "）",
                                coins_delta=-int(req_c),
                                tickets_delta=-req_t,
                            )

                    if edited_anything:
                        tap_point(context, f"{prefix}WsEditApply_{ws_label}", WS_EDIT_APPLY_POINT)
                        sleep_with_stop(context, 0.95)
                    tap_point(context, f"{prefix}WsEditBack_{ws_label}", PRISON_BACK_POINT)
                    sleep_with_stop(context, 1.1)

        if not allow_start_prod or not preferred_targets:
            _back_to_prison_overview(context, f"{prefix}WsEditDone_{ws_label}")
            continue

        if not tap_point(context, f"{prefix}TapProd_{ws_label}", prod_enter_pt):
            break

        def _check_prod_drawer(frame: Any, poll_idx: int) -> list[dict[str, Any]] | None:
            entries = ocr_roi(context, frame, f"{prefix}ProdSel_{ws_label}_{poll_idx}", PROD_SELECT_ALL_ROI)
            _spt, smode = find_production_select_all_point(entries)
            if smode in ("select_all", "cancel_all"):
                return entries
            return None

        prod_img, polled_sel, aborted_pd = poll_screen(
            context,
            _check_prod_drawer,
            initial_delay=PANEL_POLL_INITIAL,
            interval=PANEL_POLL_INTERVAL,
            max_checks=4,
            screencap_fn=safe_screencap,
            sleep_fn=sleep_with_stop,
        )
        if aborted_pd or prod_img is None:
            break
        sel_entries = (
            polled_sel
            if isinstance(polled_sel, list)
            else ocr_roi(context, prod_img, f"{prefix}ProdSel_{ws_label}", PROD_SELECT_ALL_ROI)
        )
        sel_pt, sel_mode = find_production_select_all_point(sel_entries)
        if sel_mode == "select_all" and sel_pt is not None:
            if not tap_point(context, f"{prefix}TapSelAll_{ws_label}", sel_pt):
                break

            def _check_cancel_all(frame: Any, poll_idx: int) -> bool | None:
                entries = ocr_roi(context, frame, f"{prefix}ProdSelRe_{ws_label}_{poll_idx}", PROD_SELECT_ALL_ROI)
                _p, mode = find_production_select_all_point(entries)
                return True if mode == "cancel_all" else None

            after_sel, sel_all_ok, aborted_sa = poll_screen(
                context,
                _check_cancel_all,
                initial_delay=0.9,
                interval=0.5,
                max_checks=3,
                screencap_fn=safe_screencap,
                sleep_fn=sleep_with_stop,
            )
            if aborted_sa or after_sel is None:
                break
            if not sel_all_ok:
                state.add_skipped("do", "produce_good", ws_label, "点击一键全选后未选中空闲工位。")
                _back_to_prison_overview(context, f"{prefix}WsNoIdle_{ws_label}")
                continue
            prod_img = after_sel
        elif sel_mode == "none":
            state.add_skipped("do", "produce_good", ws_label, "未检测到一键全选按钮。")
            _back_to_prison_overview(context, f"{prefix}WsNoSel_{ws_label}")
            continue

        attempted_goods: list[str] = []
        started_this_ws = False
        no_workers_this_ws = False
        retried_worker_toggle = False
        aborted_loop = False
        attempt_num = 0

        def _try_candidate(good_name: str, card_pt: tuple[int, int]) -> str:
            """尝试点击单张配方卡并视原料状态启动排产，返回 started/no_workers/no_materials/aborted。"""
            nonlocal attempt_num, retried_worker_toggle
            attempt_suffix = "" if attempt_num == 0 else f"_a{attempt_num}"
            attempt_num += 1
            if not tap_point(context, f"{prefix}TapCard_{ws_label}{attempt_suffix}", card_pt):
                return "aborted"

            def _check_ready_panel(frame: Any, poll_idx: int) -> list[dict[str, Any]] | None:
                entries = ocr_roi(context, frame, f"{prefix}ReadyPanel_{ws_label}{attempt_suffix}_{poll_idx}", PROD_READY_PANEL_ROI)
                joined = "".join(_clean_text(e.get("text")) for e in entries if isinstance(e, dict))
                if any(kw in joined for kw in ("确定", "不足", "所需材料", "请先选择生产人员")):
                    return entries
                return None

            ready_img, polled_ready, aborted_rp = poll_screen(
                context,
                _check_ready_panel,
                initial_delay=0.9,
                interval=0.5,
                max_checks=3,
                screencap_fn=safe_screencap,
                sleep_fn=sleep_with_stop,
            )
            if aborted_rp or ready_img is None:
                return "aborted"
            ready_entries = (
                polled_ready
                if isinstance(polled_ready, list)
                else ocr_roi(context, ready_img, f"{prefix}ReadyPanel_{ws_label}{attempt_suffix}", PROD_READY_PANEL_ROI)
            )
            ready_joined = "".join(_clean_text(e.get("text")) for e in ready_entries if isinstance(e, dict))

            if "请先选择生产人员" in ready_joined:
                if sel_mode == "cancel_all" and not retried_worker_toggle and sel_pt is not None:
                    retried_worker_toggle = True
                    if not tap_point(context, f"{prefix}ToggleCancelAll_{ws_label}", sel_pt):
                        return "aborted"
                    if not sleep_with_stop(context, 0.75):
                        return "aborted"
                    tog_img = safe_screencap(context)
                    if tog_img is not None:
                        re_sel_pt, re_mode = find_production_select_all_point(
                            ocr_roi(context, tog_img, f"{prefix}ReSelChk_{ws_label}", PROD_SELECT_ALL_ROI)
                        )
                        if re_mode == "select_all" and re_sel_pt is not None:
                            if not tap_point(context, f"{prefix}ReSelAll_{ws_label}", re_sel_pt):
                                return "aborted"
                            if not sleep_with_stop(context, 0.75):
                                return "aborted"
                    if not tap_point(context, f"{prefix}TapCardRetry_{ws_label}{attempt_suffix}", card_pt):
                        return "aborted"
                    ready_img2, polled_ready2, aborted_rp2 = poll_screen(
                        context,
                        _check_ready_panel,
                        initial_delay=0.9,
                        interval=0.5,
                        max_checks=2,
                        screencap_fn=safe_screencap,
                        sleep_fn=sleep_with_stop,
                    )
                    if aborted_rp2 or ready_img2 is None:
                        return "aborted"
                    ready_entries = polled_ready2 if isinstance(polled_ready2, list) else []
                    ready_joined = "".join(_clean_text(e.get("text")) for e in ready_entries if isinstance(e, dict))
                if "请先选择生产人员" in ready_joined:
                    return "no_workers"

            ready = parse_production_ready_panel(ready_entries)
            if not ready["has_confirm"] or not ready["materials_sufficient"]:
                return "no_materials"

            dur_seq = state.prod_duration_sequence()
            chosen_hours = dur_seq[-1][0]
            final_ready = ready
            for hours, dur_pt in dur_seq:
                if not tap_point(context, f"{prefix}Dur_{hours}h_{ws_label}{attempt_suffix}", dur_pt):
                    return "aborted"
                if not sleep_with_stop(context, 0.75):
                    return "aborted"
                dur_img = safe_screencap(context)
                if dur_img is None:
                    return "aborted"
                probe = parse_production_ready_panel(
                    ocr_roi(context, dur_img, f"{prefix}DurChk_{hours}_{ws_label}{attempt_suffix}", PROD_READY_PANEL_ROI)
                )
                if probe["has_confirm"] and probe["materials_sufficient"]:
                    chosen_hours = hours
                    final_ready = probe
                    break
                final_ready = probe

            if not final_ready["has_confirm"] or not final_ready["materials_sufficient"]:
                return "no_materials"

            if not tap_point(context, f"{prefix}ConfirmProd_{ws_label}{attempt_suffix}", PROD_CONFIRM_START_POINT):
                return "aborted"
            if not sleep_with_stop(context, POST_CONFIRM_DELAY):
                return "aborted"
            after_prod_img = safe_screencap(context)
            confirmed_prod = after_prod_img is not None
            if after_prod_img is not None:
                post_ready = parse_production_ready_panel(
                    ocr_roi(context, after_prod_img, f"{prefix}ProdAfterChk_{ws_label}{attempt_suffix}", PROD_READY_PANEL_ROI)
                )
                if post_ready["has_confirm"] and post_ready["materials_sufficient"]:
                    sleep_with_stop(context, 0.8)
                    after_prod_img2 = safe_screencap(context)
                    if after_prod_img2 is not None:
                        post_ready2 = parse_production_ready_panel(
                            ocr_roi(context, after_prod_img2, f"{prefix}ProdAfterChk2_{ws_label}{attempt_suffix}", PROD_READY_PANEL_ROI)
                        )
                        if post_ready2["has_confirm"] and post_ready2["materials_sufficient"]:
                            confirmed_prod = False
            if not confirmed_prod:
                state.add_skipped("do", "produce_good", f"{ws_label}:{good_name}", "点击确定排产后就绪面板未关闭，未确认启动成功。")
                return "unconfirmed"

            started_goods.add(good_name)
            state.add_executed(
                "do",
                "produce_good",
                good_name,
                f"{ws_label}启动「{good_name}」排产（{chosen_hours}小时）",
            )
            return "started"

        cards = ocr_roi(context, prod_img, f"{prefix}ProdCards_{ws_label}", PROD_RECIPE_CARDS_ROI)
        candidates_p0 = find_all_production_recipe_card_points(cards, preferred_targets, exclude_targets=started_goods)
        for cand_good, cand_pt in candidates_p0[:4]:
            if cand_good not in attempted_goods:
                attempted_goods.append(cand_good)
            outcome = _try_candidate(cand_good, cand_pt)
            if outcome == "started":
                started_this_ws = True
                break
            if outcome in ("no_workers", "unconfirmed", "aborted"):
                if outcome == "no_workers":
                    no_workers_this_ws = True
                    state.add_skipped(
                        "do",
                        "produce_good",
                        f"{ws_label}:{cand_good}",
                        "车间暂无空闲可用囚犯（请先选择生产人员），无法启动排产。",
                    )
                aborted_loop = outcome == "aborted"
                break

        if not started_this_ws and not no_workers_this_ws and not aborted_loop and not is_stopping(context):
            if candidates_p0 and candidates_p0[0][0] in attempted_goods:
                pass
            if swipe_points(
                context,
                f"{prefix}ProdScrollLeft_{ws_label}",
                PROD_CARDS_SCROLL_LEFT_SWIPE[0],
                PROD_CARDS_SCROLL_LEFT_SWIPE[1],
                duration=SWIPE_DURATION_MS,
                end_hold=SWIPE_END_HOLD_MS,
            ) and sleep_with_stop(context, 0.85):
                scroll_img = safe_screencap(context)
                if scroll_img is not None:
                    cards2 = ocr_roi(context, scroll_img, f"{prefix}ProdCardsScroll_{ws_label}", PROD_RECIPE_CARDS_ROI)
                    candidates_p1 = find_all_production_recipe_card_points(
                        cards2,
                        preferred_targets,
                        exclude_targets=list(started_goods) + attempted_goods,
                    )
                    for cand_good, cand_pt in candidates_p1[:2]:
                        if cand_good not in attempted_goods:
                            attempted_goods.append(cand_good)
                        outcome2 = _try_candidate(cand_good, cand_pt)
                        if outcome2 == "started":
                            started_this_ws = True
                            break
                        if outcome2 in ("no_workers", "unconfirmed", "aborted"):
                            if outcome2 == "no_workers":
                                no_workers_this_ws = True
                                state.add_skipped(
                                    "do",
                                    "produce_good",
                                    f"{ws_label}:{cand_good}",
                                    "车间暂无空闲可用囚犯（请先选择生产人员），无法启动排产。",
                                )
                            aborted_loop = outcome2 == "aborted"
                            break

        if not started_this_ws and not no_workers_this_ws and not aborted_loop:
            has_unconfirmed = any(o.action_type == "produce_good" and o.target.startswith(f"{ws_label}:") for o in state.skipped)
            if not has_unconfirmed:
                if attempted_goods:
                    state.add_skipped(
                        "do",
                        "produce_good",
                        f"{ws_label}:{attempted_goods[0]}",
                        f"已轮换尝试 {' / '.join(attempted_goods)} 均原料不足，请先在原料车间安排囚犯采集（未点确定）。",
                    )
                else:
                    state.add_skipped("do", "produce_good", ws_label, "当前页及翻页后均未发现已解锁的白名单配方卡。")

        _back_to_prison_overview(context, f"{prefix}WsDone_{ws_label}")


def _execute_safe_auto_actions(
    context: Context,
    *,
    snapshot: AccountSnapshot,
    prison_report: PrisonPlanReport,
    execution_plan: PrisonExecutionPlan,
    auto_scope: str,
    prefix: str,
    orders_scanned: bool = False,
    scanned_orders: Sequence[PrisonOrder] = (),
    scanned_shop_rows: Sequence[dict[str, Any]] = (),
    runtime_config: PrisonRuntimeConfig | None = None,
    diag: PrisonDiagnosticRecorder | None = None,
) -> PrisonRunReceipt:
    """按选定范围安全执行已通过护栏审核的「做什么 / 买什么 / 造什么」动作（去重进子页）。"""
    cfg = runtime_config or resolve_prison_runtime_config({"auto_scope": auto_scope})
    state = _ExecState(
        live_coins=int(snapshot.wallet.coins),
        live_tickets=int(snapshot.prison.work_tickets),
        huashi_baseline=int(snapshot.wallet.huashi),
        reserve_coins=int(execution_plan.reserve_coins),
        enabled_modules=cfg.enabled_modules,
        prod_duration_pref=cfg.prod_duration_pref,
        raw_worker_mode=cfg.raw_worker_mode,
        warehouse_batch_cap=cfg.warehouse_batch_cap,
        core_upgrade_cap=cfg.core_upgrade_cap,
        diag=diag,
    )

    def _can_skip_orders_stage() -> bool:
        if not (orders_scanned and scanned_orders):
            return False
        wanted_actions: set[str] = set()
        if state.is_enabled("order_deliver"):
            wanted_actions.add("deliver")
        if state.is_enabled("order_delete_free"):
            wanted_actions.add("delete_free")
        if not wanted_actions:
            return True
        return not any(
            evaluate_black_moon_order(o, snapshot.prison, prison_report.phase).action in wanted_actions
            for o in scanned_orders
        )

    def _run_orders_stage() -> None:
        if _can_skip_orders_stage():
            for idx, o in enumerate(scanned_orders):
                dec = evaluate_black_moon_order(o, snapshot.prison, prison_report.phase)
                state.add_skipped(
                    "do",
                    "order_deliver",
                    o.item_name,
                    f"槽位#{idx + 1}（{o.item_name}×{o.quantity}，库存{o.stock_owned}）暂不交付：{dec.action}",
                )
            return
        _exec_deliver_orders(context, state, snapshot, prison_report.phase, prefix)

    def _can_skip_shop_stage() -> bool:
        allow_recipes = state.is_enabled("shop_recipes")
        allow_items = state.is_enabled("shop_items")
        need_items = allow_items and (state.tickets_gained > 0 or state.live_tickets >= 4_000)
        if not allow_recipes:
            return not need_items
        if prison_report.phase != "rush_leveling":
            return False
        if not scanned_shop_rows:
            return False
        if state.upgraded_buildings.get("research_center", 0) > 0:
            return False
        if need_items:
            return False
        return not any(
            (not row.get("locked"))
            and int(row.get("remaining") or 0) > 0
            and bool(row.get("base_good_name"))
            and state.can_afford_coins(int(row.get("coin_cost") or 0))
            and state.live_tickets >= int(row.get("ticket_cost") or 0)
            for row in scanned_shop_rows
        )

    def _run_shop_stage() -> None:
        if _can_skip_shop_stage():
            skip_msg = (
                "首轮扫店无可兑冲级配方，跳过二次进店。"
                if state.is_enabled("shop_recipes")
                else "已关闭配方兑换且当前余票未达道具兑换门槛，跳过二次进店。"
            )
            state.add_skipped("buy", "exchange_ticket_buy", "研发配方", skip_msg)
            return
        _exec_exchange_rush_recipes(context, state, prison_report.phase, prefix)

    stages: list[tuple[bool, str, str, str, Any]] = [
        (state.is_enabled("todo_claim"), "do", "todo_claim", "事项一览领奖", lambda: _exec_claim_todo_tasks(context, state, prefix)),
        (state.is_enabled("prisoner_checkin"), "do", "prisoner_checkin", "囚犯自动入住", lambda: _exec_checkin_prisoners(context, state, snapshot, prefix)),
        (state.is_enabled("finance_auto_refill"), "do", "finance_auto_refill", "财务中心自动补满", lambda: _exec_ensure_finance_auto_refill(context, state, snapshot, prefix)),
        (state.is_enabled("order_deliver") or state.is_enabled("order_delete_free"), "do", "order_deliver", "黑月订单", _run_orders_stage),
        (state.is_enabled("building_upgrade"), "build", "building_upgrade", "核心建筑升级", lambda: _exec_upgrade_core_buildings(context, state, execution_plan, prefix, snapshot)),
        (state.is_enabled("warehouse_coin_expand"), "buy", "warehouse_coin_expand", "仓库铁盟币扩容", lambda: _exec_expand_warehouses_coins_only(context, state, prefix)),
        (state.is_enabled("shop_recipes") or state.is_enabled("shop_items"), "buy", "exchange_recipe", "研发配方兑换", _run_shop_stage),
        (state.is_enabled("raw_predeposit") or (state.is_enabled("raw_start") and cfg.raw_worker_mode != "predeposit_only"), "do", "raw_predeposit", "原料车间预存与开工", lambda: _exec_predeposit_raw_workshops(context, state, snapshot, prison_report.recommended_raw_predeposit, prefix)),
        (state.is_enabled("ws_edit_team") or state.is_enabled("ws_machine_upgrade") or state.is_enabled("ws_start_prod"), "do", "workshop_production", "生产车间编队与排产", lambda: _exec_start_workshop_production(context, state, snapshot, execution_plan, prefix, auto_scope)),
    ]
    for enabled, category, action_type, target, runner in stages:
        if not enabled:
            if diag is not None:
                diag.record("exec", "stage_disabled", f"{target} ({action_type}) 未勾选或当前范围不启用，跳过。")
            continue
        if is_stopping(context):
            break
        if action_type == "order_deliver" and _can_skip_orders_stage():
            runner()
            continue
        if action_type == "exchange_recipe" and _can_skip_shop_stage():
            runner()
            continue
        stage_t0 = time.monotonic()
        if diag is not None:
            diag.record(
                "exec",
                "stage_start",
                f"开始阶段：{target} ({action_type})",
                data={"coins": state.live_coins, "tickets": state.live_tickets},
            )
        try:
            _ensure_on_prison_overview(context, f"{prefix}PreStage_{action_type}")
            runner()
            if diag is not None:
                elapsed = max(0, int(round((time.monotonic() - stage_t0) * 1000)))
                diag.record(
                    "exec",
                    "stage_end",
                    f"完成阶段：{target} ({action_type})",
                    data={"elapsed_ms": elapsed, "coins": state.live_coins, "tickets": state.live_tickets},
                )
        except NetworkRestartedToLobbyError:
            raise
        except Exception as exc:
            err_frame = safe_screencap(context)
            if diag is not None:
                diag.record_exception(f"stage.{action_type}", exc, traceback.format_exc())
            state.add_failed(
                category,
                action_type,
                target,
                f"{target}执行异常：{type(exc).__name__}: {exc}",
                frame=err_frame,
            )
            if not is_stopping(context):
                _ensure_on_prison_overview(context, f"{prefix}ErrBack_{action_type}")

    return PrisonRunReceipt(
        mode="execute_safe_auto",
        scope=auto_scope,
        coins_before=int(snapshot.wallet.coins),
        coins_after=state.live_coins,
        tickets_before=int(snapshot.prison.work_tickets),
        tickets_after=state.live_tickets,
        huashi_before=int(snapshot.wallet.huashi),
        huashi_after=state.huashi_baseline,
        executed=state.executed,
        skipped=state.skipped,
        guard_aborts=state.guard_aborts,
        upgraded_buildings=dict(state.upgraded_buildings),
        deposit_auto_refill_verified=state.deposit_auto_refill,
    )


def _push_complete_focus(context: Context, message: str) -> None:
    """把摘要或报错写入 PrisonPlanComplete.focus，确保 MXU 前台面板直接显示。"""
    override_fn = getattr(context, "override_pipeline", None)
    if callable(override_fn):
        try:
            override_fn({"PrisonPlanComplete": {"focus": {"Node.Action.Succeeded": message}}})
        except Exception:
            pass


def _open_report_in_browser(report_path: Path) -> bool:
    """尽量用默认浏览器打开离线 HTML 报告，失败时不抛出异常。"""
    try:
        resolved = report_path.resolve()
        startfile = getattr(os, "startfile", None)
        if callable(startfile):
            startfile(str(resolved))
            return True
        return bool(webbrowser.open(resolved.as_uri()))
    except Exception:
        return False


@AgentServer.custom_action("prison_plan_scan_run")
class PrisonPlanScanAction(CustomAction):
    """只读扫描整顿中心实况，非破坏式保存账号快照并生成规划报告。"""

    @retry_on_network_restart(max_restarts=1)
    def run(
        self,
        context: Context,
        argv: CustomAction.RunArg,
    ) -> CustomAction.RunResult:
        diag_holder: list[PrisonDiagnosticRecorder] = []
        try:
            return self._run_scan(context, argv, _diag_holder=diag_holder)
        except NetworkRestartedToLobbyError:
            raise
        except Exception as exc:
            tb_text = traceback.format_exc()
            traceback.print_exc()
            bundle_hint = ""
            try:
                err_diag = (
                    diag_holder[0]
                    if diag_holder
                    else PrisonDiagnosticRecorder(export_mode="bundle", root_path=ROOT_PATH)
                )
                if err_diag.export_mode == "off":
                    err_diag.export_mode = "log_only"
                err_diag.record_exception("run", exc, tb_text)
                try:
                    err_diag.capture_frame("unhandled_exception", safe_screencap(context))
                except Exception:
                    pass
                exported = err_diag.export(ROOT_PATH / "config" / "planning" / "logs")
                err_artifact = exported.get("bundle_path") or exported.get("log_path")
                if err_artifact is not None:
                    bundle_hint = f"（排错日志已导出：config/planning/logs/{err_artifact.name}）"
            except Exception:
                pass
            err_msg = f"[PrisonPlan] 扫描过程中发生异常：{type(exc).__name__}: {exc}{bundle_hint}"
            print(err_msg, flush=True)
            _push_complete_focus(context, err_msg)
            return CustomAction.RunResult(success=False)

    def _run_scan(
        self,
        context: Context,
        argv: CustomAction.RunArg,
        *,
        _diag_holder: list[PrisonDiagnosticRecorder] | None = None,
    ) -> CustomAction.RunResult:
        prefix = "PrisonPlan"
        params = _resolve_plan_params(context, argv)
        runtime_cfg = resolve_prison_runtime_config(params)
        exec_mode = runtime_cfg.exec_mode
        auto_scope = runtime_cfg.auto_scope
        reserve_coins = runtime_cfg.reserve_coins
        scan_subpages = runtime_cfg.scan_subpages
        allow_huashi_motors = runtime_cfg.allow_huashi_motors
        allow_huashi_warehouse = runtime_cfg.allow_huashi_warehouse
        player_level = runtime_cfg.player_level
        auto_open_report = runtime_cfg.auto_open_report

        diag = PrisonDiagnosticRecorder(
            export_mode=runtime_cfg.diag_export_mode,
            root_path=ROOT_PATH,
            options_summary=runtime_cfg.to_summary_dict(),
        )
        if _diag_holder is not None:
            _diag_holder.append(diag)
        diag.record(
            "init",
            "options_resolved",
            f"mode={exec_mode}, scope={auto_scope}, reserve={reserve_coins}, diag={runtime_cfg.diag_export_mode}",
            data=runtime_cfg.to_summary_dict(),
        )

        first_img = safe_screencap(context)
        if first_img is None:
            diag.record("init", "screencap_failed", "首帧截图失败，终止运行。", level="ERROR")
            try:
                diag.export(ROOT_PATH / "config" / "planning" / "logs")
            except Exception:
                pass
            return CustomAction.RunResult(success=False)

        top_entries = ocr_roi(context, first_img, f"{prefix}InitTop", PRISON_TOP_BAR_ROI)
        dock_entries = ocr_roi(context, first_img, f"{prefix}InitDock", PRISON_BOTTOM_DOCK_ROI)
        in_prison = is_prison_overview_entries(top_entries, dock_entries)
        entered_from_lobby = False
        uid = "unknown"
        drawer_wallet: dict[str, int] = {}

        if not in_prison and is_prison_room_zoomed_entries(top_entries, dock_entries):
            if _unzoom_room_to_overview(context, f"{prefix}InitUnzoom", ROOM_UNZOOM_RIGHT_COL_POINT):
                in_prison = True
                diag.record("entry", "unzoomed_from_room", "启动时处于房间放大聚焦态，已自动点击空白处退回总览")

        if in_prison:
            _acc_path, acc_data = find_account_config()
            if isinstance(acc_data, dict) and str(acc_data.get("uid") or "").strip():
                uid = str(acc_data["uid"]).strip()
            diag.set_uid(uid)
            diag.record("entry", "already_in_prison", "当前画面已位于整顿中心总览")
            print(f"[PrisonPlan] 检测到已在整顿中心界面，开始扫描（UID={uid}）...", flush=True)
        else:
            entered, nav_uid, drawer_wallet, reason = _navigate_lobby_to_prison(context, prefix)
            if nav_uid and nav_uid != "unknown":
                uid = nav_uid
                diag.set_uid(uid)
            if reason == "stopped" or is_stopping(context):
                diag.record("entry", "stopped", f"导航过程中收到停止信号（reason={reason}）", level="WARNING")
                try:
                    diag.export(ROOT_PATH / "config" / "planning" / "logs")
                except Exception:
                    pass
                return CustomAction.RunResult(success=False)
            if entered:
                in_prison = True
                entered_from_lobby = True
                entry_desc = "左侧抽屉「整顿中心」" if reason == "ok_drawer" else "云岫桥基地"
                diag.record("entry", f"entered_{reason}", f"已从{entry_desc}进入整顿中心", data=drawer_wallet)
                print(f"[PrisonPlan] 已从{entry_desc}进入整顿中心，开始扫描（UID={uid}）...", flush=True)
            else:
                reason_hint = {
                    "not_at_city": "当前列车未停靠站点",
                    "not_at_yunxiuqiao": "当前停靠站点不是云岫桥基地",
                }.get(reason, f"未能进入整顿中心（{reason}）")
                diag.record("entry", "entry_fallback", reason_hint, level="WARNING")
                diag.capture_frame("entry_fallback", safe_screencap(context))
                print(f"[PrisonPlan] {reason_hint}，改用本地已有账号档案生成规划报告（UID={uid}）。", flush=True)

        top_data: dict[str, Any] = {}
        grid_data: dict[str, Any] = {}
        warehouse_data: dict[str, Any] = {}
        shop_data: dict[str, int] = {}
        scanned_shop_rows: list[dict[str, Any]] = []
        scanned_orders: list[PrisonOrder] = []
        orders_scanned = False

        account_path = _account_config_path_for_uid(uid)
        previous_snapshot = load_account_snapshot(account_path)

        if in_prison:
            overview_img = safe_screencap(context)
            if overview_img is None:
                return CustomAction.RunResult(success=False)
            top_entries = ocr_roi(context, overview_img, f"{prefix}TopBar", PRISON_TOP_BAR_ROI)
            dock_entries = ocr_roi(context, overview_img, f"{prefix}Dock", PRISON_BOTTOM_DOCK_ROI)
            top_data = parse_prison_top_bar(top_entries)

            grid_scans = [
                parse_prison_grid_buildings(ocr_roi(context, overview_img, f"{prefix}GridCenter", PRISON_OVERVIEW_GRID_ROI))
            ]
            for pan_name, start_pt, end_pt in PRISON_PAN_SWIPES:
                if is_stopping(context):
                    return CustomAction.RunResult(success=False)
                if not swipe_points(
                    context,
                    f"{prefix}Pan{pan_name}",
                    start_pt,
                    end_pt,
                    duration=420,
                    end_hold=120,
                ):
                    return CustomAction.RunResult(success=False)
                if not sleep_with_stop(context, 0.55):
                    return CustomAction.RunResult(success=False)
                pan_img = safe_screencap(context)
                if pan_img is None:
                    return CustomAction.RunResult(success=False)
                pan_entries = ocr_roi(context, pan_img, f"{prefix}Grid{pan_name}", PRISON_OVERVIEW_GRID_ROI)
                grid_scans.append(parse_prison_grid_buildings(pan_entries))
            grid_data = merge_prison_grid_scans(grid_scans)
            diag.record(
                "scan",
                "overview_grid",
                "完成总览四向扫描",
                data={
                    "top_level": top_data.get("level"),
                    "buildings": grid_data.get("buildings"),
                    "locked_buildings": grid_data.get("locked_buildings"),
                },
            )

            if scan_subpages and not is_stopping(context):
                # 1. 只读进「仓库」查看铁盟币/桦石/工票与双仓容量
                wh_pt = find_dock_button_point(dock_entries, ("仓库",), PRISON_DOCK_WAREHOUSE_FALLBACK)
                if tap_point(context, f"{prefix}TapWarehouse", wh_pt):
                    def _check_wh(frame: Any, idx: int) -> bool | None:
                        entries = ocr_roi(context, frame, f"{prefix}WhChk{idx}", WAREHOUSE_BODY_ROI)
                        return True if is_warehouse_screen_entries(entries) else None

                    wh_img, wh_ok, aborted = poll_screen(
                        context,
                        _check_wh,
                        initial_delay=0.9,
                        interval=0.45,
                        max_checks=4,
                        screencap_fn=safe_screencap,
                        sleep_fn=sleep_with_stop,
                    )
                    if aborted:
                        return CustomAction.RunResult(success=False)
                    if wh_ok and wh_img is not None:
                        wh_top = ocr_roi(context, wh_img, f"{prefix}WhTop", WAREHOUSE_TOP_BAR_ROI)
                        wh_body = ocr_roi(context, wh_img, f"{prefix}WhBody", WAREHOUSE_BODY_ROI)
                        warehouse_data = parse_warehouse_screen(wh_top, wh_body)
                        if not _back_to_prison_overview(context, f"{prefix}WhBack"):
                            if is_stopping(context):
                                return CustomAction.RunResult(success=False)
                    elif wh_img is not None and not _is_on_prison_overview(context, wh_img, f"{prefix}WhMiss"):
                        if not _back_to_prison_overview(context, f"{prefix}WhBack"):
                            if is_stopping(context):
                                return CustomAction.RunResult(success=False)

                # 2. 只读进「兑换商店」采集精确工票/铁盟币与研发配方列表
                if not is_stopping(context):
                    shop_pre = safe_screencap(context)
                    if shop_pre is not None and _is_on_prison_overview(context, shop_pre, f"{prefix}ShopPre"):
                        shop_dock = ocr_roi(context, shop_pre, f"{prefix}DockBeforeShop", PRISON_BOTTOM_DOCK_ROI)
                        shop_data, scanned_shop_rows = _scan_exchange_shop_overview(context, shop_dock, prefix)
                        if is_stopping(context):
                            return CustomAction.RunResult(success=False)

                # 3. 刷新底部 Dock 并只读扫描黑月订单（支持两跳门面页与多槽位切卡）
                if not is_stopping(context):
                    fresh_overview = safe_screencap(context)
                    still_overview = (
                        _is_on_prison_overview(context, fresh_overview, f"{prefix}OrdPre")
                        if fresh_overview is not None
                        else False
                    )
                    if fresh_overview is not None:
                        dock_entries = ocr_roi(context, fresh_overview, f"{prefix}DockBeforeOrd", PRISON_BOTTOM_DOCK_ROI)

                    if not still_overview:
                        print("[PrisonPlan] 未确认处于整顿中心总览界面，跳过黑月订单只读扫描。", flush=True)
                    else:
                        ord_img, ord_ok, legacy_direct, aborted = _enter_daily_orders_screen(context, dock_entries, prefix)
                        if aborted:
                            return CustomAction.RunResult(success=False)
                        if ord_ok and ord_img is not None:
                            slot_cards = [] if legacy_direct else _scan_daily_orders_slots(context, ord_img, prefix)
                            if slot_cards:
                                for _idx, _pt, card in slot_cards:
                                    scanned_orders.append(
                                        PrisonOrder(
                                            item_name=card["item_name"],
                                            quantity=card["quantity"],
                                            order_type="daily",
                                            stock_owned=card["stock_owned"],
                                        )
                                    )
                            else:
                                ord_hdr = ocr_roi(context, ord_img, f"{prefix}OrdHdr", ORDERS_HEADER_ROI)
                                ord_body = ocr_roi(context, ord_img, f"{prefix}OrdBody", ORDERS_BODY_ROI)
                                scanned_orders.extend(parse_orders_screen(ord_hdr, ord_body, order_type="daily"))

                                cur_level = int(top_data.get("level") or previous_snapshot.prison.level or 0)
                                weekly_pt = find_weekly_orders_tab_point(ord_hdr) if cur_level >= 20 else None
                                if weekly_pt is not None and tap_point(context, f"{prefix}TapWeeklyTab", weekly_pt):
                                    if sleep_with_stop(context, 0.7):
                                        w_img = safe_screencap(context)
                                        if w_img is not None:
                                            w_hdr = ocr_roi(context, w_img, f"{prefix}OrdWkHdr", ORDERS_HEADER_ROI)
                                            w_body = ocr_roi(context, w_img, f"{prefix}OrdWkBody", ORDERS_BODY_ROI)
                                            scanned_orders.extend(
                                                parse_orders_screen(w_hdr, w_body, order_type="weekly")
                                            )
                            orders_scanned = True
                            _back_to_prison_overview(context, f"{prefix}OrdBack")
                        elif ord_img is not None and not _is_on_prison_overview(context, ord_img, f"{prefix}OrdMiss"):
                            _back_to_prison_overview(context, f"{prefix}OrdBack")

                diag.record(
                    "scan",
                    "subpages_done",
                    "完成子页面只读扫描",
                    data={
                        "warehouse_raw_used": warehouse_data.get("raw_warehouse_used"),
                        "warehouse_fin_used": warehouse_data.get("finished_warehouse_used"),
                        "shop_tickets": shop_data.get("work_tickets"),
                        "shop_row_count": len(scanned_shop_rows),
                        "orders_scanned": orders_scanned,
                        "order_count": len(scanned_orders),
                    },
                )

        if in_prison:
            merged_wallet, merged_prison = _merge_scanned_prison_and_wallet(
                previous_snapshot,
                uid=uid,
                top_data=top_data,
                grid_data=grid_data,
                warehouse_data=warehouse_data,
                orders_scanned=orders_scanned,
                scanned_orders=scanned_orders,
                drawer_wallet=drawer_wallet,
                shop_data=shop_data,
            )
            save_account_snapshot_sections(
                account_path,
                uid=uid,
                wallet=merged_wallet,
                prison=merged_prison,
            )
            snapshot = load_account_snapshot(account_path)
        else:
            snapshot = previous_snapshot
            if uid != "unknown" and snapshot.uid == "unknown":
                snapshot = snapshot.model_copy(update={"uid": uid})
            wallet_updates = {
                key: int(drawer_wallet[key])
                for key in ("coins", "huashi", "clarity_estimate")
                if drawer_wallet.get(key) is not None
            }
            if wallet_updates:
                snapshot = snapshot.model_copy(
                    update={"wallet": snapshot.wallet.model_copy(update=wallet_updates)}
                )

        diag.set_uid(snapshot.uid)
        prison_options = PrisonPlanOptions(
            reserve_coins=reserve_coins,
            allow_huashi_motors=allow_huashi_motors,
            allow_huashi_warehouse=allow_huashi_warehouse,
            player_level=player_level,
        )
        prison_report = plan_prison(snapshot, prison_options)
        execution_plan = build_prison_execution_plan(snapshot, prison_report, prison_options)
        diag.record(
            "plan",
            "plan_built",
            f"phase={prison_report.phase}, level={prison_report.prison_level}",
            data={
                "do_count": len(execution_plan.do_actions),
                "buy_count": len(execution_plan.buy_actions),
                "build_count": len(execution_plan.build_actions),
                "blocked_count": len(execution_plan.blocked_actions),
            },
        )

        run_receipt = PrisonRunReceipt(
            mode="plan_only",
            scope=auto_scope,
            coins_before=int(snapshot.wallet.coins),
            coins_after=int(snapshot.wallet.coins),
            tickets_before=int(snapshot.prison.work_tickets),
            tickets_after=int(snapshot.prison.work_tickets),
            huashi_before=int(snapshot.wallet.huashi),
            huashi_after=int(snapshot.wallet.huashi),
        )
        if exec_mode == "execute_safe_auto" and in_prison and not is_stopping(context):
            run_receipt = _execute_safe_auto_actions(
                context,
                snapshot=snapshot,
                prison_report=prison_report,
                execution_plan=execution_plan,
                auto_scope=auto_scope,
                prefix=f"{prefix}Exec",
                orders_scanned=orders_scanned,
                scanned_orders=scanned_orders,
                scanned_shop_rows=scanned_shop_rows,
                runtime_config=runtime_cfg,
                diag=diag,
            )
            diag.record(
                "exec",
                "exec_complete",
                f"executed={len(run_receipt.executed)}, skipped={len(run_receipt.skipped)}, aborts={len(run_receipt.guard_aborts)}",
                data={
                    "coins_before": run_receipt.coins_before,
                    "coins_after": run_receipt.coins_after,
                    "tickets_before": run_receipt.tickets_before,
                    "tickets_after": run_receipt.tickets_after,
                    "huashi_before": run_receipt.huashi_before,
                    "huashi_after": run_receipt.huashi_after,
                },
            )
            if (
                run_receipt.coins_after != int(snapshot.wallet.coins)
                or run_receipt.tickets_after != int(snapshot.prison.work_tickets)
                or run_receipt.upgraded_buildings
                or run_receipt.deposit_auto_refill_verified is True
            ):
                post_wallet = snapshot.wallet.model_dump(mode="python")
                post_wallet["coins"] = int(run_receipt.coins_after)
                post_prison = snapshot.prison.model_dump(mode="python")
                post_prison["work_tickets"] = int(run_receipt.tickets_after)
                if run_receipt.deposit_auto_refill_verified is True:
                    post_prison["deposit_auto_refill"] = True
                if run_receipt.upgraded_buildings:
                    buildings_map = dict(post_prison.get("buildings") or {})
                    for bid, delta in run_receipt.upgraded_buildings.items():
                        buildings_map[bid] = int(buildings_map.get(bid, 0)) + int(delta)
                    post_prison["buildings"] = buildings_map
                save_account_snapshot_sections(
                    account_path,
                    uid=uid,
                    wallet=post_wallet,
                    prison=post_prison,
                )
                snapshot = load_account_snapshot(account_path)
                prison_report = plan_prison(snapshot, prison_options)
                execution_plan = build_prison_execution_plan(snapshot, prison_report, prison_options)

        semi_auto_guides = build_semi_auto_guidance(
            snapshot,
            prison_report,
            execution_plan,
            run_receipt,
        )
        run_receipt = run_receipt.model_copy(update={"semi_auto_guides": semi_auto_guides})

        safe_report_uid = "".join(ch for ch in str(snapshot.uid or "unknown") if ch.isalnum() or ch in {"_", "-"}) or "unknown"
        report_dir = ROOT_PATH / "config" / "planning"
        report_dir.mkdir(parents=True, exist_ok=True)
        md_path = report_dir / f"latest_report_{safe_report_uid}.md"
        json_path = report_dir / f"latest_report_{safe_report_uid}.json"
        html_path = report_dir / f"latest_report_{safe_report_uid}.html"

        diag_log_path: Path | None = None
        issue_bundle_path: Path | None = None
        try:
            diag_files = diag.export(
                report_dir / "logs",
                snapshot=snapshot,
                prison_report=prison_report,
                execution_plan=execution_plan,
                run_receipt=run_receipt,
                semi_auto_guides=semi_auto_guides,
            )
            diag_log_path = diag_files.get("log_path")
            issue_bundle_path = diag_files.get("bundle_path")
        except Exception as diag_exc:
            print(f"[PrisonPlan] 诊断日志导出失败（不影响主流程）：{diag_exc}", flush=True)

        md_path.write_text(
            format_prison_plan_markdown(prison_report, semi_auto_guides=semi_auto_guides),
            encoding="utf-8",
        )
        json_path.write_text(
            json.dumps(
                {
                    "prison": prison_report.model_dump(mode="json"),
                    "execution_plan": execution_plan.model_dump(mode="json"),
                    "run_receipt": run_receipt.model_dump(mode="json"),
                    "semi_auto_guides": [g.model_dump(mode="json") for g in semi_auto_guides],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        html_path.write_text(
            format_planning_report_html(
                prison_report,
                growth_report=None,
                execution_plan=execution_plan,
                run_receipt=run_receipt,
                semi_auto_guides=semi_auto_guides,
                issue_bundle_path=issue_bundle_path,
                diag_log_path=diag_log_path,
            ),
            encoding="utf-8",
        )

        summary_lines = format_mxu_plain_summary(
            prison_report,
            report_path=html_path,
            execution_plan=execution_plan,
            run_receipt=run_receipt,
            semi_auto_guides=semi_auto_guides,
            issue_bundle_path=issue_bundle_path or diag_log_path,
        )
        for line in summary_lines:
            print(line, flush=True)
        _push_complete_focus(context, "\n".join(summary_lines))

        if entered_from_lobby and not is_stopping(context):
            return_to_lobby(context, f"{prefix}FinishLobby")

        if auto_open_report and not is_stopping(context):
            _open_report_in_browser(html_path)

        return CustomAction.RunResult(success=not is_stopping(context))
