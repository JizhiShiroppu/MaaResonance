"""CustomAction for Island (蜃息岛) read-only scan, stage planning, and safe daily execution."""
from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
from types import SimpleNamespace
import traceback
from typing import Any
import webbrowser

from maa.agent.agent_server import AgentServer
from maa.context import Context
from maa.custom_action import CustomAction

from agent.battle_autoplay_action import BattleAutoplayLoopAction
from agent.utils.action_helpers import ocr_roi, parse_action_param, poll_screen, swipe_points, tap_point
from agent.utils.activity_hub_nav import open_activity_hub, select_activity_tab
from agent.utils.input_guard import safe_screencap, sleep_with_stop
from agent.utils.lobby_nav import dismiss_reward_popup_if_present, is_stopping, open_drawer, return_to_lobby
from agent.utils.mall_nav import read_drawer_uid
from agent.utils.network_guard import NetworkRestartedToLobbyError, retry_on_network_restart
from maa_resonance.logic.daily_routine import (
    DRAWER_CLOSE_POINT,
    REWARD_POPUP_HINT_ROI,
    REWARD_POPUP_TITLE_ROI,
    has_reward_popup_entries,
)
from maa_resonance.logic.manual_trade import find_account_config
from maa_resonance.logic.paths import ROOT_PATH
from maa_resonance.logic.planning import (
    FRIEND_ISLAND_BOTTOM_ROI,
    FRIEND_ISLAND_CLEAN_POINT,
    FRIEND_ISLAND_COUNTS_ROI,
    FRIEND_ISLAND_DASHBOARD_ROI,
    FRIEND_ISLAND_INFO_ROI,
    FRIEND_ISLAND_LIKE_POINT,
    FRIEND_ISLAND_NEXT_POINT,
    FRIEND_ISLAND_RACCOON_POINT,
    ISLAND_BACK_POINT,
    ISLAND_BANNER_ENTRY_POINT,
    ISLAND_BANNER_ENTRY_ROI,
    ISLAND_BOTTOM_DOCK_ROI,
    ISLAND_BROOM_BTN_POINT,
    ISLAND_CARD_PACK_PROMPT_ROI,
    ISLAND_CARD_PACK_SWIPE_END,
    ISLAND_CARD_PACK_SWIPE_START,
    ISLAND_COUNTS_HUD_ROI,
    ISLAND_EXCHANGE_BTN_POINT,
    ISLAND_EXCHANGE_CURRENCIES_ROI,
    ISLAND_EXCHANGE_HEADER_ROI,
    ISLAND_EXCHANGE_LIST_ROI,
    ISLAND_EXPAND_BTN_POINT,
    ISLAND_EXPAND_BUTTONS_ROI,
    ISLAND_EXPAND_MODAL_ROI,
    ISLAND_FORMATION_BTN_ROI,
    ISLAND_FORMATION_COST_ROI,
    ISLAND_FORMATION_START_POINT,
    ISLAND_FRIENDS_BTN_POINT,
    ISLAND_FRIENDS_CLEAN_TAB_POINT,
    ISLAND_FRIENDS_CLOSE_POINT,
    ISLAND_FRIENDS_HEADER_ROI,
    ISLAND_FRIENDS_LIST_ROI,
    ISLAND_FRIENDS_SECURITY_TAB_POINT,
    ISLAND_INVEST_CARDS_ROI,
    ISLAND_INVEST_CONFIRM_MODAL_ROI,
    ISLAND_INVEST_REMAINING_ROI,
    ISLAND_INVEST_SUMMARY_ROI,
    ISLAND_LEFT_HUD_ROI,
    ISLAND_OPS_COINS_ROI,
    ISLAND_OPS_COLLECT_POINT,
    ISLAND_OPS_FOOTER_ROI,
    ISLAND_OPS_INVEST_TAB_POINT,
    ISLAND_OPS_METRICS_ROI,
    ISLAND_OPS_STAY_DAYS_ROI,
    ISLAND_OPS_TABS_ROI,
    ISLAND_RACCOON_BTN_POINT,
    ISLAND_REPORT_BASIC_ROI,
    ISLAND_REPORT_BTN_POINT,
    ISLAND_REPORT_CLOSE_POINT,
    ISLAND_REPORT_MODAL_ROI,
    ISLAND_REPORT_LEFT_ROI,
    ISLAND_REPORT_SCORES_ROI,
    ISLAND_REVENUE_BUBBLE_POINT,
    ISLAND_SHELLS_ROI,
    ISLAND_SKY_DISMISS_POINT,
    ISLAND_TICKETS_ROI,
    ISLAND_TODO_BTN_POINT,
    ISLAND_TODO_BUTTONS_ROI,
    ISLAND_TODO_HEADER_ROI,
    ISLAND_TODO_LEVEL_ROI,
    ISLAND_TODO_TITLES_ROI,
    ISLAND_TOP_BAR_ROI,
    ISLAND_TRASH_ACTIONS_ROI,
    ISLAND_TRASH_HEADER_ROI,
    ISLAND_TRASH_MACHINE_ROI,
    ISLAND_TRASH_PENDING_ROI,
    ISLAND_TRASH_STORAGE_ROI,
    IslandActionOutcome,
    IslandDiagnosticRecorder,
    IslandPlanOptions,
    IslandRunReceipt,
    IslandRuntimeConfig,
    choose_best_island_invest_card,
    detect_island_monster_tap_points,
    evaluate_island_expand_safe,
    find_friend_list_visit_points,
    find_island_todo_claim_points,
    find_island_trash_collect_point,
    format_island_mxu_summary,
    format_island_plan_markdown,
    format_island_report_html,
    is_free_island_formation_entries,
    is_friend_island_entries,
    is_island_banner_entries,
    is_island_card_pack_entries,
    is_island_exchange_shop_entries,
    is_island_expand_modal_entries,
    is_island_friends_drawer_entries,
    is_island_main_entries,
    is_island_ops_invest_entries,
    is_island_ops_overview_entries,
    is_island_report_entries,
    is_island_todo_entries,
    is_island_trash_screen_entries,
    island_todo_claim_circle_point,
    load_account_snapshot,
    parse_drawer_wallet,
    parse_friend_island_status,
    parse_island_exchange_shop,
    parse_island_expand_modal,
    parse_island_invest_cards,
    parse_island_main_hud,
    parse_island_ops_coins,
    parse_island_ops_invest,
    parse_island_ops_overview,
    parse_island_report_overview,
    parse_island_trash_screen,
    plan_island,
    resolve_island_runtime_config,
    save_account_snapshot_sections,
)

ISLAND_PLAN_ATTACH_NODES: tuple[str, ...] = (
    "IslandPlanOptExecMode",
    "IslandPlanOptAutoScope",
    "IslandPlanOptEnabledModules",
    "IslandPlanOptReserveCoins",
    "IslandPlanOptCustomReserveCoins",
    "IslandPlanOptOwnMonsterCap",
    "IslandPlanOptFriendCleanCap",
    "IslandPlanOptFriendHelpCap",
    "IslandPlanOptAutoOpenReport",
    "IslandPlanOptDebugExport",
)


@dataclass
class _IslandExecState:
    revenue_claimed_coins: int = 0
    trash_blocks_collected: int = 0
    own_monsters_cleared: int = 0
    todo_rewards_claimed: int = 0
    friend_visits: int = 0
    friend_trash_cleaned: int = 0
    friend_likes_sent: int = 0
    friend_monsters_helped: int = 0
    invest_executed_count: int = 0
    invest_spent_coins: int = 0
    islands_expanded: int = 0
    expand_spent_coins: int = 0
    expand_spent_tickets: int = 0
    executed: list[IslandActionOutcome] = field(default_factory=list)
    skipped: list[IslandActionOutcome] = field(default_factory=list)
    guard_aborts: list[IslandActionOutcome] = field(default_factory=list)


def _resolve_plan_params(context: Context, argv: Any) -> dict[str, Any]:
    merged = dict(parse_action_param(getattr(argv, "custom_action_param", None)))
    get_node_data = getattr(context, "get_node_data", None)
    if callable(get_node_data):
        for node_name in ISLAND_PLAN_ATTACH_NODES:
            try:
                node_data = get_node_data(node_name)
            except Exception:
                node_data = None
            if isinstance(node_data, dict) and isinstance(node_data.get("attach"), dict):
                merged.update(node_data["attach"])
    return merged


def _account_config_path_for_uid(uid: str) -> Path:
    safe_uid = "".join(ch for ch in str(uid or "").strip() if ch.isalnum() or ch in {"_", "-"})
    return ROOT_PATH / "config" / "accounts" / f"{safe_uid or 'unknown'}.json"


def _push_complete_focus(context: Context, message: str) -> None:
    override_fn = getattr(context, "override_pipeline", None)
    if callable(override_fn):
        try:
            override_fn({"IslandPlanComplete": {"focus": {"Node.Action.Succeeded": message}}})
        except Exception:
            pass


def _open_report_in_browser(report_path: Path) -> bool:
    try:
        resolved = report_path.resolve()
        startfile = getattr(os, "startfile", None)
        if callable(startfile):
            startfile(str(resolved))
            return True
        return bool(webbrowser.open(resolved.as_uri()))
    except Exception:
        return False


def _is_on_island_main(context: Context, frame: Any, prefix: str) -> bool:
    top = ocr_roi(context, frame, f"{prefix}Top", ISLAND_TOP_BAR_ROI)
    dock = ocr_roi(context, frame, f"{prefix}Dock", ISLAND_BOTTOM_DOCK_ROI)
    return is_island_main_entries(top, dock)


def _handle_island_card_pack_if_present(
    context: Context,
    prefix: str,
    image: Any = None,
    *,
    diag: IslandDiagnosticRecorder | None = None,
) -> tuple[bool, bool]:
    """若处于「请用手指滑动屏幕」卡包界面则右划拆包并关闭展示与结算弹窗，返回 (handled, ok)。"""
    cur = image if image is not None else safe_screencap(context)
    if cur is None:
        return False, not is_stopping(context)
    prompt_e = ocr_roi(context, cur, f"{prefix}PackPrompt", ISLAND_CARD_PACK_PROMPT_ROI)
    if not is_island_card_pack_entries(prompt_e):
        return False, True

    if not swipe_points(
        context,
        f"{prefix}TearPack",
        ISLAND_CARD_PACK_SWIPE_START,
        ISLAND_CARD_PACK_SWIPE_END,
        duration=450,
        end_hold=80,
    ):
        return True, False
    if not sleep_with_stop(context, 2.2):
        return True, False

    for step in range(10):
        step_img = safe_screencap(context)
        if step_img is None:
            return True, not is_stopping(context)
        if _is_on_island_main(context, step_img, f"{prefix}PackMainChk{step}"):
            break
        todo_btns = ocr_roi(context, step_img, f"{prefix}PackTodoB{step}", ISLAND_TODO_BUTTONS_ROI)
        todo_lvl = ocr_roi(context, step_img, f"{prefix}PackTodoL{step}", ISLAND_TODO_LEVEL_ROI)
        if is_island_todo_entries(todo_btns + todo_lvl):
            break
        reward_t = ocr_roi(context, step_img, f"{prefix}PackRT{step}", REWARD_POPUP_TITLE_ROI)
        reward_h = ocr_roi(context, step_img, f"{prefix}PackRH{step}", REWARD_POPUP_HINT_ROI)
        if has_reward_popup_entries(reward_t, reward_h):
            if not dismiss_reward_popup_if_present(context, f"{prefix}PackDismiss{step}", step_img):
                return True, False
            continue
        if not tap_point(context, f"{prefix}PackNext{step}", (640, 620)):
            return True, False
        if not sleep_with_stop(context, 0.9):
            return True, False

    _record_diag(diag, "card_pack", "opened", "已自动划开海岛卡包奖励并关闭展示与结算弹窗")
    return True, not is_stopping(context)


def _ensure_on_island_main(context: Context, prefix: str, *, max_backs: int = 4) -> bool:
    for step in range(max_backs):
        img = safe_screencap(context)
        if img is None:
            return False
        if _is_on_island_main(context, img, f"{prefix}Chk{step}"):
            return True
        if not dismiss_reward_popup_if_present(context, f"{prefix}Dismiss{step}", img):
            return False
        pack_handled, pack_ok = _handle_island_card_pack_if_present(context, f"{prefix}Pack{step}")
        if not pack_ok:
            return False
        if pack_handled:
            continue
        img2 = safe_screencap(context)
        if img2 is None:
            return False
        if _is_on_island_main(context, img2, f"{prefix}ChkAfter{step}"):
            return True
        # 检查是否处于经营报表居中弹窗
        rep = ocr_roi(context, img2, f"{prefix}RepChk{step}", ISLAND_REPORT_MODAL_ROI)
        if is_island_report_entries(rep):
            if not tap_point(context, f"{prefix}CloseReport{step}", ISLAND_REPORT_CLOSE_POINT):
                return False
            if not sleep_with_stop(context, 0.8):
                return False
            continue
        # 检查是否打开着好友抽屉
        fhdr = ocr_roi(context, img2, f"{prefix}FHdrChk{step}", ISLAND_FRIENDS_HEADER_ROI)
        if is_island_friends_drawer_entries(fhdr):
            if not tap_point(context, f"{prefix}CloseFriends{step}", ISLAND_FRIENDS_CLOSE_POINT):
                return False
            if not sleep_with_stop(context, 0.8):
                return False
            continue
        if not tap_point(context, f"{prefix}Back{step}", ISLAND_BACK_POINT):
            return False
        if not sleep_with_stop(context, 1.4):
            return False
    final_img = safe_screencap(context)
    return bool(final_img is not None and _is_on_island_main(context, final_img, f"{prefix}FinalChk"))


def _record_diag(
    diag: IslandDiagnosticRecorder | None,
    stage: str,
    event: str,
    detail: str = "",
    *,
    data: dict[str, Any] | None = None,
    level: str = "INFO",
) -> None:
    if diag is not None:
        diag.record(stage, event, detail, data=data, level=level)


def _capture_diag(diag: IslandDiagnosticRecorder | None, tag: str, image: Any) -> None:
    if diag is not None and image is not None:
        diag.capture_frame(tag, image)


def _dismiss_tooltip_and_restore(
    context: Context,
    prefix: str,
    *,
    is_friend_island: bool = False,
) -> bool:
    """轻点空白天区关闭误触打开的家具/NPC气泡，并校验仍在预期海岛视图。"""
    tap_point(context, f"{prefix}SkyDismiss", ISLAND_SKY_DISMISS_POINT)
    if not sleep_with_stop(context, 0.3):
        return False
    frame = safe_screencap(context)
    if frame is None:
        return False
    if is_friend_island:
        if _is_on_friend_island(context, frame, f"{prefix}FChk"):
            return True
        tap_point(context, f"{prefix}FBack", ISLAND_BACK_POINT)
        sleep_with_stop(context, 0.8)
        frame2 = safe_screencap(context)
        return bool(frame2 is not None and _is_on_friend_island(context, frame2, f"{prefix}FChk2"))
    if _is_on_island_main(context, frame, f"{prefix}MChk"):
        return True
    return _ensure_on_island_main(context, f"{prefix}MBack")


def _read_live_own_monster_count(context: Context, frame: Any, prefix: str) -> int | None:
    """在当前HUD可清晰读到双计数器时返回最新红怪数，否则返回 None 表示不确定。"""
    cnt_e = ocr_roi(context, frame, f"{prefix}HudCnt", ISLAND_COUNTS_HUD_ROI)
    valid_nums = [
        e
        for e in cnt_e
        if isinstance(e, dict) and any(ch.isdigit() for ch in str(e.get("text") or ""))
    ]
    if len(valid_nums) < 2:
        return None
    parsed = parse_island_main_hud((), (), cnt_e)
    return int(parsed.get("active_monsters") or 0)


def _navigate_lobby_to_island(context: Context, prefix: str) -> tuple[bool, str, dict[str, int], str]:
    """回到大厅读取 UID/资产后，通过活动中心 -> 经营活动 -> 海岛物语 -> 海岛入口进岛。"""
    if not return_to_lobby(context, f"{prefix}ToLobby"):
        return False, "unknown", {}, "stopped" if is_stopping(context) else "not_in_lobby"

    uid = "unknown"
    drawer_wallet: dict[str, int] = {}
    drawer_img, drawer_entries = open_drawer(context, f"{prefix}Drawer")
    if drawer_img is not None:
        read_uid = read_drawer_uid(context, f"{prefix}Uid", drawer_img)
        if read_uid:
            uid = read_uid
        drawer_wallet = parse_drawer_wallet(drawer_entries)
        tap_point(context, f"{prefix}CloseDrawer", DRAWER_CLOSE_POINT)
        if not sleep_with_stop(context, 0.65):
            return False, uid, drawer_wallet, "stopped"
    else:
        _acc_path, acc_data = find_account_config()
        if isinstance(acc_data, dict) and str(acc_data.get("uid") or "").strip():
            uid = str(acc_data["uid"]).strip()

    if not open_activity_hub(context, f"{prefix}ActHub"):
        return False, uid, drawer_wallet, "stopped" if is_stopping(context) else "activity_hub_failed"

    tab_ok, _ = select_activity_tab(context, f"{prefix}SelectTab", "经营活动", ("海岛物语", "海岛"))
    if not tab_ok:
        return False, uid, drawer_wallet, "stopped" if is_stopping(context) else "island_tab_not_found"

    def _check_banner(frame: Any, idx: int) -> tuple[int, int] | None:
        entries = ocr_roi(context, frame, f"{prefix}Banner{idx}", ISLAND_BANNER_ENTRY_ROI)
        if not is_island_banner_entries(entries):
            return None
        for e in entries:
            if isinstance(e, dict) and "海岛入口" in str(e.get("text") or "").replace(" ", ""):
                if "center_x" in e and "center_y" in e:
                    return int(round(float(e["center_x"]))), int(round(float(e["center_y"])))
        return ISLAND_BANNER_ENTRY_POINT

    _, entry_pt, aborted = poll_screen(
        context,
        _check_banner,
        initial_delay=0.6,
        interval=0.5,
        max_checks=4,
        screencap_fn=safe_screencap,
        sleep_fn=sleep_with_stop,
    )
    if aborted:
        return False, uid, drawer_wallet, "stopped"
    tap_xy = entry_pt if isinstance(entry_pt, tuple) else ISLAND_BANNER_ENTRY_POINT
    if not tap_point(context, f"{prefix}TapEntry", tap_xy):
        return False, uid, drawer_wallet, "stopped"

    _, entered, aborted = poll_screen(
        context,
        lambda frame, idx: True if _is_on_island_main(context, frame, f"{prefix}MainPoll{idx}") else None,
        initial_delay=2.4,
        interval=0.7,
        max_checks=7,
        screencap_fn=safe_screencap,
        sleep_fn=sleep_with_stop,
    )
    if aborted:
        return False, uid, drawer_wallet, "stopped"
    if not entered:
        return_to_lobby(context, f"{prefix}EnterFailLobby")
        return False, uid, drawer_wallet, "island_enter_timeout"
    return True, uid, drawer_wallet, "ok_activity_hub"


def _scan_report_modal(context: Context, prefix: str) -> dict[str, Any]:
    if not tap_point(context, f"{prefix}OpenReport", ISLAND_REPORT_BTN_POINT):
        return {}
    img, matched, aborted = poll_screen(
        context,
        lambda frame, idx: True
        if is_island_report_entries(ocr_roi(context, frame, f"{prefix}RepChk{idx}", ISLAND_REPORT_MODAL_ROI))
        else None,
        initial_delay=1.0,
        interval=0.45,
        max_checks=4,
        screencap_fn=safe_screencap,
        sleep_fn=sleep_with_stop,
    )
    if aborted or not matched or img is None:
        _ensure_on_island_main(context, f"{prefix}RepMissBack")
        return {}
    left_e = ocr_roi(context, img, f"{prefix}RepLeft", ISLAND_REPORT_LEFT_ROI)
    scores_e = ocr_roi(context, img, f"{prefix}RepScores", ISLAND_REPORT_SCORES_ROI)
    basic_e = ocr_roi(context, img, f"{prefix}RepBasic", ISLAND_REPORT_BASIC_ROI)
    data = parse_island_report_overview(left_e, scores_e, basic_e)
    tap_point(context, f"{prefix}CloseReport", ISLAND_REPORT_CLOSE_POINT)
    sleep_with_stop(context, 0.85)
    _ensure_on_island_main(context, f"{prefix}RepBack")
    return data


def _maybe_exec_island_invest(
    context: Context,
    prefix: str,
    *,
    ops_data: dict[str, Any],
    invest_data: dict[str, Any],
    coins_budget: int,
    reserve_coins: int,
    state: _IslandExecState,
    diag: IslandDiagnosticRecorder | None = None,
) -> None:
    """在运营投资页按「分成>票价>减税 + 底线留存 + 零桦石 + 投后核验」安全执行可用投资。"""
    rem = int(invest_data.get("invest_remaining") or 0)
    if rem <= 0:
        detail = "当前剩余投资次数为 0，已跳过。"
        state.skipped.append(
            IslandActionOutcome(
                stage="auto_invest",
                action_type="auto_invest",
                target="海角城运营投资",
                status="skipped",
                detail=detail,
            )
        )
        _record_diag(diag, "auto_invest", "skipped_zero_remaining", detail)
        return

    cur_coins = int(invest_data.get("live_coins") or 0) or (
        int(coins_budget) + int(state.revenue_claimed_coins) if int(coins_budget) > 0 else 0
    )
    if cur_coins <= 0:
        guard_msg = "未能读取当前铁盟币余额，已按底线保护硬中止运营投资。"
        state.guard_aborts.append(
            IslandActionOutcome(
                stage="auto_invest",
                action_type="auto_invest",
                target="海角城运营投资",
                status="aborted",
                detail=guard_msg,
            )
        )
        _record_diag(diag, "auto_invest", "guard_unknown_coins", guard_msg, level="WARNING")
        return

    reason_labels = {
        "no_spendable_coins": "可动用铁盟币（超出留存底线部分）为 0，已按底线保护跳过",
        "exceeds_reserve": "候选投资所需铁盟币超出留存底线，已按底线保护跳过",
        "all_capped": "分成/票价/税率均已达目标上限，已跳过",
        "no_eligible_card": "未识别到安全可投的运营立牌（可能含桦石/已满）",
    }

    max_rounds = min(rem, 5)
    for step in range(max_rounds):
        if is_stopping(context):
            break
        cards = list(invest_data.get("cards") or [])
        spendable = max(0, int(cur_coins) - int(reserve_coins))
        chosen, pick_reason = choose_best_island_invest_card(
            cards,
            spendable_coins=spendable,
            share_ratio_pct=float(ops_data.get("share_ratio_pct") or 0.0),
            ticket_price=int(ops_data.get("ticket_price") or 0),
            tax_rate_pct=float(ops_data.get("tax_rate_pct") or 5.0),
        )
        if chosen is None:
            detail = reason_labels.get(pick_reason, f"未执行投资（{pick_reason}）")
            if state.invest_executed_count == 0:
                state.skipped.append(
                    IslandActionOutcome(
                        stage="auto_invest",
                        action_type="auto_invest",
                        target="海角城运营投资",
                        status="skipped",
                        detail=detail,
                    )
                )
            _record_diag(
                diag,
                "auto_invest",
                f"skipped_{pick_reason}",
                detail,
                data={"cur_coins": cur_coins, "reserve_coins": reserve_coins, "spendable": spendable},
            )
            break

        before_rem = int(invest_data.get("invest_remaining") or 0)
        before_inv = int(invest_data.get("invested_total") or 0)
        tap_xy = chosen.get("tap_point")
        if not tap_xy or not tap_point(context, f"{prefix}ExecInv{step}", tap_xy):
            break
        if not sleep_with_stop(context, 0.9):
            break

        post_img = safe_screencap(context)
        if post_img is not None:
            conf_e = ocr_roi(context, post_img, f"{prefix}InvConf{step}", ISLAND_INVEST_CONFIRM_MODAL_ROI)
            conf_joined = "".join(str(e.get("text") or "").replace(" ", "") for e in conf_e if isinstance(e, dict))
            if "桦石" in conf_joined:
                cancel_xy = None
                for e in conf_e:
                    if isinstance(e, dict) and "取消" in str(e.get("text") or "").replace(" ", ""):
                        if "center_x" in e and "center_y" in e:
                            cancel_xy = (int(round(float(e["center_x"]))), int(round(float(e["center_y"]))))
                            break
                if cancel_xy is not None:
                    tap_point(context, f"{prefix}InvCancelHua{step}", cancel_xy)
                guard_msg = "投资弹窗检测到桦石消耗词，硬护栏已中止。"
                state.guard_aborts.append(
                    IslandActionOutcome(
                        stage="auto_invest",
                        action_type="auto_invest",
                        target="海角城运营投资",
                        status="aborted",
                        detail=guard_msg,
                    )
                )
                _record_diag(diag, "auto_invest", "guard_huashi", guard_msg, level="WARNING")
                break
            confirm_xy = None
            for e in conf_e:
                if isinstance(e, dict):
                    txt = str(e.get("text") or "").replace(" ", "")
                    if ("确认" in txt or "确定" in txt) and "center_x" in e and "center_y" in e:
                        confirm_xy = (int(round(float(e["center_x"]))), int(round(float(e["center_y"]))))
                        break
            if confirm_xy is not None:
                if not tap_point(context, f"{prefix}InvConfirm{step}", confirm_xy):
                    break
                sleep_with_stop(context, 0.9)

        dismiss_reward_popup_if_present(context, f"{prefix}InvReward{step}")

        after_img = safe_screencap(context)
        if after_img is None:
            break
        after_rem_e = ocr_roi(context, after_img, f"{prefix}InvAfterRem{step}", ISLAND_INVEST_REMAINING_ROI)
        after_sum_e = ocr_roi(context, after_img, f"{prefix}InvAfterSum{step}", ISLAND_INVEST_SUMMARY_ROI)
        after_cards_e = ocr_roi(context, after_img, f"{prefix}InvAfterCards{step}", ISLAND_INVEST_CARDS_ROI)
        after_coins_e = ocr_roi(context, after_img, f"{prefix}InvAfterCoins{step}", ISLAND_OPS_COINS_ROI)

        after_parsed = parse_island_ops_invest(after_rem_e, after_sum_e)
        after_rem = int(after_parsed.get("invest_remaining") or 0)
        after_inv = int(after_parsed.get("invested_total") or 0)
        after_coins = parse_island_ops_coins(after_coins_e)
        after_cards = parse_island_invest_cards(after_cards_e)
        if after_cards:
            invest_data["cards"] = after_cards
        if after_coins > 0:
            invest_data["live_coins"] = after_coins

        if after_rem < before_rem or after_inv > before_inv:
            cost = int(chosen.get("cost_coins") or 0)
            state.invest_executed_count += 1
            state.invest_spent_coins += cost
            invest_data["invest_remaining"] = after_rem
            invest_data["invested_total"] = max(before_inv, after_inv)
            cur_coins = after_coins if after_coins > 0 else max(0, cur_coins - cost)
            detail = (
                f"执行运营投资 [{chosen.get('kind')}]（+{chosen.get('benefit_value')}，"
                f"消耗 {cost:,} 币，余次 {before_rem} -> {after_rem}）"
            )
            state.executed.append(
                IslandActionOutcome(
                    stage="auto_invest",
                    action_type="auto_invest",
                    target="海角城运营投资",
                    status="executed",
                    detail=detail,
                )
            )
            _record_diag(
                diag,
                "auto_invest",
                "invested",
                detail,
                data={
                    "kind": chosen.get("kind"),
                    "cost": cost,
                    "before_rem": before_rem,
                    "after_rem": after_rem,
                    "after_invested": after_inv,
                },
            )
            if after_rem <= 0:
                break
        else:
            detail = f"点击投资后未检测到次数减少或已投金额上升（rem={after_rem}, inv={after_inv}），安全停止"
            if state.invest_executed_count == 0:
                state.skipped.append(
                    IslandActionOutcome(
                        stage="auto_invest",
                        action_type="auto_invest",
                        target="海角城运营投资",
                        status="skipped",
                        detail=detail,
                    )
                )
            _record_diag(diag, "auto_invest", "verify_unchanged", detail, level="WARNING")
            break


def _scan_and_maybe_claim_ops(
    context: Context,
    prefix: str,
    *,
    claim_revenue: bool,
    auto_invest: bool = False,
    reserve_coins: int = 15_000_000,
    coins_budget: int = 0,
    state: _IslandExecState,
    diag: IslandDiagnosticRecorder | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """点击左下金币气泡进营运概览，读取营业与投资信息；按需收钱与投资。"""
    if not tap_point(context, f"{prefix}OpenOps", ISLAND_REVENUE_BUBBLE_POINT):
        return {}, {}
    img, matched, aborted = poll_screen(
        context,
        lambda frame, idx: True
        if is_island_ops_overview_entries(
            ocr_roi(context, frame, f"{prefix}OpsTab{idx}", ISLAND_OPS_TABS_ROI),
            ocr_roi(context, frame, f"{prefix}OpsBody{idx}", ISLAND_OPS_METRICS_ROI),
        )
        else None,
        initial_delay=1.2,
        interval=0.5,
        max_checks=5,
        screencap_fn=safe_screencap,
        sleep_fn=sleep_with_stop,
    )
    if aborted or not matched or img is None:
        _ensure_on_island_main(context, f"{prefix}OpsMissBack")
        return {}, {}

    stay_e = ocr_roi(context, img, f"{prefix}OpsStay", ISLAND_OPS_STAY_DAYS_ROI)
    met_e = ocr_roi(context, img, f"{prefix}OpsMetrics", ISLAND_OPS_METRICS_ROI)
    foot_e = ocr_roi(context, img, f"{prefix}OpsFooter", ISLAND_OPS_FOOTER_ROI)
    ops_data = parse_island_ops_overview(stay_e, met_e, foot_e)

    pending = int(ops_data.get("pending_revenue_coins") or 0)
    if claim_revenue and pending > 0:
        collect_pt = ops_data.get("collect_point") or ISLAND_OPS_COLLECT_POINT
        if tap_point(context, f"{prefix}ClaimRev", collect_pt):
            sleep_with_stop(context, 1.1)
            dismiss_reward_popup_if_present(context, f"{prefix}ClaimRevReward")
            after_img = safe_screencap(context)
            after_pending = pending
            if after_img is not None:
                after_foot = ocr_roi(context, after_img, f"{prefix}OpsAfterFoot", ISLAND_OPS_FOOTER_ROI)
                after_stay = ocr_roi(context, after_img, f"{prefix}OpsAfterStay", ISLAND_OPS_STAY_DAYS_ROI)
                after_met = ocr_roi(context, after_img, f"{prefix}OpsAfterMet", ISLAND_OPS_METRICS_ROI)
                after_parsed = parse_island_ops_overview(after_stay, after_met, after_foot)
                after_pending = int(after_parsed.get("pending_revenue_coins") or 0)
            claimed = max(0, pending - after_pending) if after_pending < pending else pending
            state.revenue_claimed_coins += claimed
            ops_data["pending_revenue_coins"] = after_pending
            state.executed.append(
                IslandActionOutcome(
                    stage="claim_revenue",
                    action_type="collect_revenue",
                    target="管理中心营运收益",
                    status="executed",
                    detail=f"收取待领收益 {claimed:,} 铁盟币（收后待领 {after_pending:,}）",
                )
            )
            _record_diag(
                diag,
                "claim_revenue",
                "claimed",
                f"收取营运待领收益 {claimed} 币（收后待领 {after_pending}）",
                data={"pending_before": pending, "pending_after": after_pending, "claimed": claimed},
            )
    elif claim_revenue:
        state.skipped.append(
            IslandActionOutcome(
                stage="claim_revenue",
                action_type="collect_revenue",
                target="管理中心营运收益",
                status="skipped",
                detail="当前待领收益为 0，无需领取",
            )
        )
        _record_diag(diag, "claim_revenue", "skipped", "当前待领收益为 0，无需领取")

    # 切到「投资」页签读取剩余次数、已投总额与 3 张立牌，若开启 auto_invest 则按底线执行
    invest_data: dict[str, Any] = {}
    if tap_point(context, f"{prefix}TapInvestTab", ISLAND_OPS_INVEST_TAB_POINT):
        inv_img, inv_ok, inv_aborted = poll_screen(
            context,
            lambda frame, idx: True
            if is_island_ops_invest_entries(
                ocr_roi(context, frame, f"{prefix}InvTab{idx}", ISLAND_OPS_TABS_ROI),
                ocr_roi(context, frame, f"{prefix}InvSumChk{idx}", ISLAND_INVEST_SUMMARY_ROI),
            )
            else None,
            initial_delay=0.9,
            interval=0.45,
            max_checks=4,
            screencap_fn=safe_screencap,
            sleep_fn=sleep_with_stop,
        )
        if not inv_aborted and inv_ok and inv_img is not None:
            rem_e = ocr_roi(context, inv_img, f"{prefix}InvRem", ISLAND_INVEST_REMAINING_ROI)
            sum_e = ocr_roi(context, inv_img, f"{prefix}InvSum", ISLAND_INVEST_SUMMARY_ROI)
            cards_e = ocr_roi(context, inv_img, f"{prefix}InvCards", ISLAND_INVEST_CARDS_ROI)
            coins_e = ocr_roi(context, inv_img, f"{prefix}InvCoins", ISLAND_OPS_COINS_ROI)
            invest_data = parse_island_ops_invest(rem_e, sum_e)
            cards = parse_island_invest_cards(cards_e)
            live_coins_top = parse_island_ops_coins(coins_e)
            invest_data["cards"] = cards
            invest_data["live_coins"] = live_coins_top
            _record_diag(
                diag,
                "scan",
                "invest_cards",
                f"解析到 {len(cards)} 张运营投资卡（实时铁盟币={live_coins_top:,}）",
                data={"live_coins": live_coins_top, "cards": cards},
            )
            if auto_invest:
                _maybe_exec_island_invest(
                    context,
                    prefix,
                    ops_data=ops_data,
                    invest_data=invest_data,
                    coins_budget=coins_budget,
                    reserve_coins=reserve_coins,
                    state=state,
                    diag=diag,
                )

    _ensure_on_island_main(context, f"{prefix}OpsBack")
    return ops_data, invest_data


def _scan_exchange_shop_readonly(
    context: Context,
    prefix: str,
    *,
    diag: IslandDiagnosticRecorder | None = None,
) -> dict[str, Any]:
    """只读扫描「海岛兑换处」顶栏货币（排球奖币/贝币）与商品价目库存，严禁点击兑换按钮。"""
    if not tap_point(context, f"{prefix}OpenExch", ISLAND_EXCHANGE_BTN_POINT):
        return {}
    img, ok, aborted = poll_screen(
        context,
        lambda frame, idx: True
        if is_island_exchange_shop_entries(
            ocr_roi(context, frame, f"{prefix}ExchHdr{idx}", ISLAND_EXCHANGE_HEADER_ROI),
            ocr_roi(context, frame, f"{prefix}ExchListChk{idx}", ISLAND_EXCHANGE_LIST_ROI),
        )
        else None,
        initial_delay=1.0,
        interval=0.45,
        max_checks=4,
        screencap_fn=safe_screencap,
        sleep_fn=sleep_with_stop,
    )
    if aborted or not ok or img is None:
        _record_diag(diag, "scan", "exchange_shop_miss", "未能打开海岛兑换处界面（已安全返回）", level="WARNING")
        _ensure_on_island_main(context, f"{prefix}ExchMissBack")
        return {}
    cur_e = ocr_roi(context, img, f"{prefix}ExchCur", ISLAND_EXCHANGE_CURRENCIES_ROI)
    list_e = ocr_roi(context, img, f"{prefix}ExchList", ISLAND_EXCHANGE_LIST_ROI)
    data = parse_island_exchange_shop(cur_e, list_e)
    _record_diag(
        diag,
        "scan",
        "exchange_shop",
        f"海岛兑换处只读扫描完成：排球币={data.get('volleyball_coins', 0)}, 贝币={data.get('shell_coins', 0)}, 商品={len(data.get('items', []))}项",
        data=data,
    )
    _ensure_on_island_main(context, f"{prefix}ExchBack")
    return data


def _scan_and_maybe_expand_island(
    context: Context,
    prefix: str,
    *,
    allow_execute: bool,
    current_level: int,
    live_coins: int,
    live_tickets: int,
    reserve_coins: int,
    state: _IslandExecState,
    diag: IslandDiagnosticRecorder | None = None,
) -> dict[str, Any]:
    """点击底栏「扩建」扫描下一岛需求；未开启自动扩建、处于PlanOnly或护栏未通过时一律点「取消」。"""
    if not tap_point(context, f"{prefix}OpenExp", ISLAND_EXPAND_BTN_POINT):
        return {}
    img, ok, aborted = poll_screen(
        context,
        lambda frame, idx: True
        if is_island_expand_modal_entries(
            ocr_roi(context, frame, f"{prefix}ExpChk{idx}", ISLAND_EXPAND_MODAL_ROI)
        )
        else None,
        initial_delay=0.9,
        interval=0.45,
        max_checks=3,
        screencap_fn=safe_screencap,
        sleep_fn=sleep_with_stop,
    )
    if aborted or not ok or img is None:
        detail = "未检测到海岛扩建确认弹窗（可能已解锁全部 6 岛或当前不可扩建）"
        _record_diag(diag, "auto_expand", "no_modal", detail)
        if allow_execute:
            state.skipped.append(
                IslandActionOutcome(
                    stage="auto_expand",
                    action_type="auto_expand",
                    target="海岛扩建",
                    status="skipped",
                    detail=detail,
                )
            )
        _ensure_on_island_main(context, f"{prefix}ExpNoModalBack")
        return {}

    modal_e = ocr_roi(context, img, f"{prefix}ExpModal", ISLAND_EXPAND_MODAL_ROI)
    btn_e = ocr_roi(context, img, f"{prefix}ExpBtns", ISLAND_EXPAND_BUTTONS_ROI)
    modal_data = parse_island_expand_modal(modal_e, btn_e)
    _record_diag(
        diag,
        "scan",
        "expand_modal",
        f"海岛扩建需求：LV{modal_data.get('required_level', 0)} · {modal_data.get('cost_coins', 0):,}币 + {modal_data.get('cost_tickets', 0):,}券",
        data={k: v for k, v in modal_data.items() if k not in ("cancel_point", "confirm_point")}
        | {
            "has_confirm_btn": modal_data.get("confirm_point") is not None,
        },
    )

    if not allow_execute:
        tap_point(context, f"{prefix}ExpReadOnlyCancel", modal_data["cancel_point"])
        sleep_with_stop(context, 0.55)
        _ensure_on_island_main(context, f"{prefix}ExpReadOnlyBack")
        return modal_data

    safe_ok, reason = evaluate_island_expand_safe(
        modal_data,
        current_level=current_level,
        live_coins=live_coins,
        live_tickets=live_tickets,
        reserve_coins=reserve_coins,
    )
    if not safe_ok:
        tap_point(context, f"{prefix}ExpGuardCancel", modal_data["cancel_point"])
        sleep_with_stop(context, 0.55)
        is_guard = any(kw in reason for kw in ("桦石", "未能完整", "未安全识别", "未知"))
        target_list = state.guard_aborts if is_guard else state.skipped
        target_list.append(
            IslandActionOutcome(
                stage="auto_expand",
                action_type="auto_expand",
                target="海岛扩建",
                status="aborted" if is_guard else "skipped",
                detail=reason,
            )
        )
        _record_diag(
            diag,
            "auto_expand",
            "guard_abort" if is_guard else "skipped",
            reason,
            level="WARNING" if is_guard else "INFO",
        )
        _ensure_on_island_main(context, f"{prefix}ExpCancelBack")
        return modal_data

    confirm_pt = modal_data["confirm_point"]
    if tap_point(context, f"{prefix}ExpConfirm", confirm_pt):
        sleep_with_stop(context, 1.4)
        dismiss_reward_popup_if_present(context, f"{prefix}ExpReward")
        after_img = safe_screencap(context)
        still_open = bool(
            after_img is not None
            and is_island_expand_modal_entries(
                ocr_roi(context, after_img, f"{prefix}ExpAfterChk", ISLAND_EXPAND_MODAL_ROI)
            )
        )
        if still_open:
            tap_point(context, f"{prefix}ExpRetryCancel", modal_data["cancel_point"])
            sleep_with_stop(context, 0.55)
            detail = "点击扩建确认后弹窗仍未关闭，已点击取消并中止计入扩建"
            state.skipped.append(
                IslandActionOutcome(
                    stage="auto_expand",
                    action_type="auto_expand",
                    target="海岛扩建",
                    status="skipped",
                    detail=detail,
                )
            )
            _record_diag(diag, "auto_expand", "confirm_still_open", detail, level="WARNING")
        else:
            cost_coins = int(modal_data.get("cost_coins") or 0)
            cost_tickets = int(modal_data.get("cost_tickets") or 0)
            state.islands_expanded += 1
            state.expand_spent_coins += cost_coins
            state.expand_spent_tickets += cost_tickets
            detail = f"海岛扩建成功（消耗 {cost_coins:,} 币 + {cost_tickets:,} 资材券，单趟上限 1 次）"
            state.executed.append(
                IslandActionOutcome(
                    stage="auto_expand",
                    action_type="auto_expand",
                    target="海岛扩建",
                    status="executed",
                    detail=detail,
                )
            )
            _record_diag(
                diag,
                "auto_expand",
                "expanded",
                detail,
                data={"cost_coins": cost_coins, "cost_tickets": cost_tickets},
            )
    _ensure_on_island_main(context, f"{prefix}ExpDoneBack")
    return modal_data


def _scan_and_maybe_collect_trash(
    context: Context,
    prefix: str,
    *,
    collect_trash: bool,
    state: _IslandExecState,
    diag: IslandDiagnosticRecorder | None = None,
) -> dict[str, Any]:
    """打开海岛垃圾产出总览读取等级与暂存容量；仅在 collect_trash=True 时安全点击右侧「一键收取」。"""
    if not tap_point(context, f"{prefix}TapBroom", ISLAND_BROOM_BTN_POINT):
        return {}
    img, ok, aborted = poll_screen(
        context,
        lambda frame, idx: True
        if is_island_trash_screen_entries(ocr_roi(context, frame, f"{prefix}TrashChk{idx}", ISLAND_TRASH_HEADER_ROI))
        else None,
        initial_delay=1.1,
        interval=0.5,
        max_checks=5,
        screencap_fn=safe_screencap,
        sleep_fn=sleep_with_stop,
    )
    if aborted or not ok or img is None:
        if collect_trash:
            state.skipped.append(
                IslandActionOutcome(
                    stage="collect_trash",
                    action_type="collect_trash",
                    target="海岛垃圾产出总览",
                    status="failed",
                    detail="未能打开海岛垃圾产出总览界面",
                )
            )
            _record_diag(diag, "collect_trash", "open_failed", "未能打开海岛垃圾产出总览界面", level="WARNING")
            _capture_diag(diag, "trash_open_fail", safe_screencap(context))
        _ensure_on_island_main(context, f"{prefix}TrashMissBack")
        return {}

    hdr_e = ocr_roi(context, img, f"{prefix}TrashHdr", ISLAND_TRASH_HEADER_ROI)
    pend_e = ocr_roi(context, img, f"{prefix}TrashPend", ISLAND_TRASH_PENDING_ROI)
    mac_e = ocr_roi(context, img, f"{prefix}TrashMac", ISLAND_TRASH_MACHINE_ROI)
    sto_e = ocr_roi(context, img, f"{prefix}TrashSto", ISLAND_TRASH_STORAGE_ROI)
    trash_info = parse_island_trash_screen(hdr_e, pend_e, mac_e, sto_e)

    if not collect_trash:
        _ensure_on_island_main(context, f"{prefix}TrashReadOnlyBack")
        return trash_info

    stored_before = int(trash_info.get("trash_blocks_stored") or 0)
    if stored_before <= 0:
        detail = f"暂存区为空（0/{trash_info.get('trash_blocks_cap', 0)}）"
        state.skipped.append(
            IslandActionOutcome(
                stage="collect_trash",
                action_type="collect_trash",
                target="海岛垃圾站一键收取",
                status="skipped",
                detail=detail,
            )
        )
        _record_diag(diag, "collect_trash", "skipped", detail)
        _ensure_on_island_main(context, f"{prefix}TrashEmptyBack")
        return trash_info

    act_e = ocr_roi(context, img, f"{prefix}TrashBtns", ISLAND_TRASH_ACTIONS_ROI)
    collect_pt = find_island_trash_collect_point(act_e)
    if collect_pt is None:
        guard_msg = "未安全识别到右侧【一键收取】按钮，已触发防误触【一键处理】硬护栏跳过。"
        state.guard_aborts.append(
            IslandActionOutcome(
                stage="collect_trash",
                action_type="collect_trash",
                target="海岛垃圾站一键收取",
                status="aborted",
                detail=guard_msg,
            )
        )
        _record_diag(diag, "collect_trash", "guard_abort", guard_msg, level="WARNING")
        _capture_diag(diag, "trash_guard_abort", img)
        _ensure_on_island_main(context, f"{prefix}TrashGuardBack")
        return trash_info

    if tap_point(context, f"{prefix}TapCollect", collect_pt):
        sleep_with_stop(context, 1.1)
        dismiss_reward_popup_if_present(context, f"{prefix}TrashReward")
        after_img = safe_screencap(context)
        stored_after = stored_before
        if after_img is not None:
            after_sto = ocr_roi(context, after_img, f"{prefix}TrashStoAfter", ISLAND_TRASH_STORAGE_ROI)
            after_parsed = parse_island_trash_screen(hdr_e, pend_e, mac_e, after_sto)
            stored_after = int(after_parsed.get("trash_blocks_stored") or 0)
            trash_info["trash_blocks_stored"] = stored_after
        delta = max(0, stored_before - stored_after) if stored_after < stored_before else stored_before
        state.trash_blocks_collected += delta
        detail = f"收取海岛垃圾块 {delta} 块（暂存 {stored_before} -> {stored_after}）"
        state.executed.append(
            IslandActionOutcome(
                stage="collect_trash",
                action_type="collect_trash",
                target="海岛垃圾站一键收取",
                status="executed",
                detail=detail,
            )
        )
        _record_diag(
            diag,
            "collect_trash",
            "collected",
            detail,
            data={"stored_before": stored_before, "stored_after": stored_after, "collected": delta},
        )
    _ensure_on_island_main(context, f"{prefix}TrashDoneBack")
    return trash_info


def _exec_claim_todo_rewards(
    context: Context,
    prefix: str,
    state: _IslandExecState,
    diag: IslandDiagnosticRecorder | None = None,
) -> int:
    if not tap_point(context, f"{prefix}OpenTodo", ISLAND_TODO_BTN_POINT):
        return 0
    img, ok, aborted = poll_screen(
        context,
        lambda frame, idx: True
        if is_island_todo_entries(
            ocr_roi(context, frame, f"{prefix}TodoChk{idx}", ISLAND_TODO_BUTTONS_ROI)
            + ocr_roi(context, frame, f"{prefix}TodoLvl{idx}", ISLAND_TODO_LEVEL_ROI)
        )
        else None,
        initial_delay=1.0,
        interval=0.45,
        max_checks=4,
        screencap_fn=safe_screencap,
        sleep_fn=sleep_with_stop,
    )
    if aborted or not ok:
        state.skipped.append(
            IslandActionOutcome(
                stage="claim_todo",
                action_type="claim_todo",
                target="事项一览",
                status="failed",
                detail="未能进入事项一览界面",
            )
        )
        _record_diag(diag, "claim_todo", "open_failed", "未能进入事项一览界面", level="WARNING")
        _capture_diag(diag, "todo_open_fail", safe_screencap(context))
        _ensure_on_island_main(context, f"{prefix}TodoMissBack")
        return 0

    def _read_todo_state(frame: Any, tag: str) -> tuple[list[tuple[int, int]], tuple[int, int, str], list[dict[str, Any]]]:
        btn_entries = ocr_roi(context, frame, f"{prefix}TodoBtns{tag}", ISLAND_TODO_BUTTONS_ROI)
        title_entries = ocr_roi(context, frame, f"{prefix}TodoTitles{tag}", ISLAND_TODO_TITLES_ROI)
        pts = find_island_todo_claim_points(btn_entries)
        titles_key = "".join(
            str(e.get("text") or "").replace(" ", "")
            for e in title_entries
            if isinstance(e, dict)
        )[:120]
        sig = (len(pts), pts[0][1] // 12 if pts else -1, titles_key)
        return pts, sig, btn_entries

    claimed = 0
    cur = img
    unchanged_sig: tuple[int, int, str] | None = None
    tried_alt_y = False
    stopped_unchanged = False

    for step in range(12):
        if claimed >= 8 or is_stopping(context):
            break
        if cur is None:
            cur = safe_screencap(context)
        if cur is None:
            break
        claim_pts, before_sig, _ = _read_todo_state(cur, f"{step}")
        if not claim_pts:
            break

        if before_sig == unchanged_sig:
            if not tried_alt_y:
                tap_xy = claim_pts[0]
                tried_alt_y = True
            else:
                stopped_unchanged = True
                _record_diag(
                    diag,
                    "claim_todo",
                    "unchanged_stop",
                    "点击领取圆钮及文字区后列表无变化，停止重复点击",
                    level="WARNING",
                )
                break
        else:
            tap_xy = island_todo_claim_circle_point(claim_pts[0])
            tried_alt_y = False

        if not tap_point(context, f"{prefix}TodoClaim{step}", tap_xy):
            break
        if not sleep_with_stop(context, 0.95):
            break

        mid_img = safe_screencap(context)
        popup_seen = False
        if mid_img is not None:
            pack_handled, pack_ok = _handle_island_card_pack_if_present(
                context,
                f"{prefix}TodoPack{step}",
                mid_img,
                diag=diag,
            )
            if not pack_ok:
                break
            if pack_handled:
                popup_seen = True
            else:
                reward_t = ocr_roi(context, mid_img, f"{prefix}TodoRTitle{step}", REWARD_POPUP_TITLE_ROI)
                reward_h = ocr_roi(context, mid_img, f"{prefix}TodoRHint{step}", REWARD_POPUP_HINT_ROI)
                popup_seen = has_reward_popup_entries(reward_t, reward_h)
                if not dismiss_reward_popup_if_present(context, f"{prefix}TodoReward{step}", mid_img):
                    break

        after_img = safe_screencap(context)
        if after_img is None:
            break

        after_pts, after_sig, after_btns = _read_todo_state(after_img, f"After{step}")
        after_lvl = ocr_roi(context, after_img, f"{prefix}TodoLvlAfter{step}", ISLAND_TODO_LEVEL_ROI)
        still_on_todo = is_island_todo_entries(after_btns + after_lvl)

        if popup_seen or (still_on_todo and after_sig != before_sig):
            claimed += 1
            unchanged_sig = None
            tried_alt_y = False
            _record_diag(
                diag,
                "claim_todo",
                f"claimed_{step}",
                f"成功领取第 {claimed} 项任务奖励（tap={tap_xy}, popup={popup_seen}）",
            )
        else:
            unchanged_sig = before_sig
            _record_diag(
                diag,
                "claim_todo",
                f"no_change_{step}",
                f"点击 {tap_xy} 后任务列表与弹窗均无变化（不计入领取）",
            )

        if not still_on_todo:
            if not popup_seen:
                _record_diag(
                    diag,
                    "claim_todo",
                    "left_todo_screen",
                    "点击领取后界面已离开事项一览，停止继续领取并准备返回",
                    level="WARNING",
                )
            break
        cur = after_img

    state.todo_rewards_claimed += claimed
    if claimed > 0:
        detail = f"自动领取 {claimed} 项已完成任务奖励（严格跳过【追踪】）"
        state.executed.append(
            IslandActionOutcome(
                stage="claim_todo",
                action_type="claim_todo",
                target="事项一览领奖",
                status="executed",
                detail=detail,
            )
        )
        _record_diag(diag, "claim_todo", "claimed", detail, data={"claimed": claimed})
    else:
        detail = (
            "检测到【领取】但点击圆钮与文字区均未触发领奖，已安全停止重复点击"
            if stopped_unchanged
            else "当前无待领取任务（已保护跳过【追踪】）"
        )
        state.skipped.append(
            IslandActionOutcome(
                stage="claim_todo",
                action_type="claim_todo",
                target="事项一览领奖",
                status="skipped",
                detail=detail,
            )
        )
        _record_diag(diag, "claim_todo", "skipped", detail, level="WARNING" if stopped_unchanged else "INFO")
    _ensure_on_island_main(context, f"{prefix}TodoDoneBack")
    return claimed


def _run_zero_cost_monster_battle(
    context: Context,
    prefix: str,
) -> tuple[bool, str]:
    """在已打开的编队页核验 0 体力 -> 点开始作战 -> 跑快斩自动战斗 -> 结算回到上层海岛。"""
    img, formation_ok, aborted = poll_screen(
        context,
        lambda frame, idx: True
        if is_free_island_formation_entries(
            ocr_roi(context, frame, f"{prefix}FormBtn{idx}", ISLAND_FORMATION_BTN_ROI),
            ocr_roi(context, frame, f"{prefix}FormCost{idx}", ISLAND_FORMATION_COST_ROI),
        )
        else None,
        initial_delay=0.25,
        interval=0.35,
        max_checks=3,
        screencap_fn=safe_screencap,
        sleep_fn=sleep_with_stop,
    )
    if aborted:
        return False, "stopped"
    if not formation_ok or img is None:
        return False, "not_free_formation"

    if not tap_point(context, f"{prefix}StartBattle", ISLAND_FORMATION_START_POINT):
        return False, "tap_start_failed"

    sleep_with_stop(context, 2.2)

    battle_action = BattleAutoplayLoopAction()
    battle_arg = SimpleNamespace(
        node_name=f"{prefix}Battle",
        custom_action_param=json.dumps(
            {
                "prefer_native_auto": True,
                "play_mode": "fast_rush",
                "max_steps": 600,
                "enable_leader_skill": True,
            }
        ),
    )
    battle_action.run(context, battle_arg)

    # 战后结算循环：识别胜利/失败/下一步/空白退出，直到回到自家或好友海岛主界面
    for settle_step in range(18):
        frame = safe_screencap(context)
        if frame is None:
            return False, "stopped"
        if _is_on_island_main(context, frame, f"{prefix}SettleOwn{settle_step}"):
            return True, "ok"
        f_dash = ocr_roi(context, frame, f"{prefix}SettleFDash{settle_step}", FRIEND_ISLAND_DASHBOARD_ROI)
        f_bot = ocr_roi(context, frame, f"{prefix}SettleFBot{settle_step}", FRIEND_ISLAND_BOTTOM_ROI)
        if is_friend_island_entries(f_dash, f_bot):
            return True, "ok"

        center_e = ocr_roi(context, frame, f"{prefix}SettleCenter{settle_step}", (120, 80, 1040, 625))
        center_txt = "".join(str(e.get("text") or "") for e in center_e if isinstance(e, dict)).replace(" ", "")
        if any(kw in center_txt for kw in ("作战失败", "挑战失败", "重新挑战")):
            tap_point(context, f"{prefix}DefeatBack", ISLAND_BACK_POINT)
            sleep_with_stop(context, 1.5)
            return False, "defeated"

        right_e = ocr_roi(context, frame, f"{prefix}SettleRight{settle_step}", (1020, 500, 260, 220))
        next_pt = None
        for e in right_e:
            if isinstance(e, dict):
                txt = str(e.get("text") or "").replace(" ", "")
                if any(kw in txt for kw in ("下一步", "继续", "离开")):
                    if "center_x" in e and "center_y" in e:
                        next_pt = (int(round(float(e["center_x"]))), int(round(float(e["center_y"]))))
                        break
        if next_pt is not None:
            tap_point(context, f"{prefix}SettleNext{settle_step}", next_pt)
            sleep_with_stop(context, 1.1)
            continue

        if any(
            kw in center_txt
            for kw in ("触碰空白区域退出", "点击空白区域退出", "任务完成", "作战胜利", "SUCCESSFUL", "获得物品", "获得道具")
        ):
            tap_point(context, f"{prefix}SettleTap{settle_step}", (640, 660))
            sleep_with_stop(context, 1.0)
            continue

        sleep_with_stop(context, 0.85)

    return False, "settlement_timeout"


def _try_enter_and_fight_monster(
    context: Context,
    prefix: str,
    pts: list[tuple[int, int]],
    *,
    is_friend_island: bool,
    max_tries: int,
    diag: IslandDiagnosticRecorder | None = None,
    diag_stage: str = "clear_own_monsters",
) -> tuple[bool, bool, str]:
    """依次尝试点候选红叹号坐标 -> 核验 0 体力编队 -> 未命中时点空白天区消弹窗 -> 进入战斗。"""
    entered_battle = False
    for try_i, m_pt in enumerate(pts[:max_tries]):
        if not tap_point(context, f"{prefix}TapM{try_i}", m_pt):
            break
        _, is_form, aborted = poll_screen(
            context,
            lambda f, chk_i: True
            if is_free_island_formation_entries(
                ocr_roi(context, f, f"{prefix}ChkForm{try_i}_{chk_i}", ISLAND_FORMATION_BTN_ROI),
                ocr_roi(context, f, f"{prefix}ChkCost{try_i}_{chk_i}", ISLAND_FORMATION_COST_ROI),
            )
            else None,
            initial_delay=0.95,
            interval=0.4,
            max_checks=2,
            screencap_fn=safe_screencap,
            sleep_fn=sleep_with_stop,
        )
        if aborted:
            return False, False, "stopped"
        if is_form:
            entered_battle = True
            break
        _record_diag(
            diag,
            diag_stage,
            "candidate_miss",
            f"候选坐标 {m_pt} 未进入0体力编队，点击空白天区关闭弹窗",
            data={"point": [int(m_pt[0]), int(m_pt[1])], "try_i": try_i},
        )
        if not _dismiss_tooltip_and_restore(context, f"{prefix}Miss{try_i}", is_friend_island=is_friend_island):
            return False, False, "restore_failed"
    if not entered_battle:
        return False, False, "not_free_formation"
    won, reason = _run_zero_cost_monster_battle(context, f"{prefix}Fight")
    return True, won, reason


def _exec_clear_own_monsters(
    context: Context,
    prefix: str,
    *,
    max_fights: int,
    stability_current: int,
    stability_max: int,
    active_monsters: int,
    state: _IslandExecState,
    diag: IslandDiagnosticRecorder | None = None,
) -> int:
    if (stability_current >= stability_max and active_monsters <= 0) or active_monsters <= 0:
        detail = (
            f"稳定指数已满 {stability_current}/{stability_max} 且岛上无怪，已跳过。"
            if active_monsters <= 0 and stability_current >= stability_max
            else "当前岛上无入侵怪，已跳过。"
        )
        state.skipped.append(
            IslandActionOutcome(
                stage="clear_own_monsters",
                action_type="clear_monsters",
                target="自家入侵野怪",
                status="skipped",
                detail=detail,
            )
        )
        _record_diag(diag, "clear_own_monsters", "skipped", detail)
        return 0
    if max_fights <= 0:
        return 0

    cleared = 0
    consecutive_misses = 0
    max_attempts = max(max_fights, max_fights * 2 + 2)
    for idx in range(max_attempts):
        if cleared >= max_fights:
            break
        if is_stopping(context) or not _ensure_on_island_main(context, f"{prefix}Pre{idx}"):
            break
        if idx > 0:
            live_frame = safe_screencap(context)
            live_cnt = _read_live_own_monster_count(context, live_frame, f"{prefix}LiveHud{idx}") if live_frame is not None else None
            if live_cnt == 0:
                _record_diag(diag, "clear_own_monsters", "hud_zero", "主界面 HUD 怪物数量已归零，停止清怪")
                break
        # 点左下浣熊图标让镜头自动居中一只怪
        if not tap_point(context, f"{prefix}CenterMonster{idx}", ISLAND_RACCOON_BTN_POINT):
            break
        if not sleep_with_stop(context, 1.0):
            break
        frame = safe_screencap(context)
        if frame is None:
            break
        pts = detect_island_monster_tap_points(frame)
        _record_diag(
            diag,
            "clear_own_monsters",
            f"scan_{idx}",
            f"第 {idx + 1} 轮检测到 {len(pts)} 个红叹号候选",
            data={"candidates": [list(p) for p in pts[:6]]},
        )
        if not pts:
            consecutive_misses += 1
            _capture_diag(diag, f"own_mob_empty_{idx}", frame)
            _dismiss_tooltip_and_restore(context, f"{prefix}EmptyRst{idx}", is_friend_island=False)
            if consecutive_misses >= 2:
                break
            continue

        entered, won, reason = _try_enter_and_fight_monster(
            context,
            f"{prefix}Round{idx}_",
            pts,
            is_friend_island=False,
            max_tries=3,
            diag=diag,
            diag_stage="clear_own_monsters",
        )
        if reason == "stopped":
            break
        if not entered:
            consecutive_misses += 1
            _capture_diag(diag, f"own_mob_miss_{idx}", safe_screencap(context))
            _ensure_on_island_main(context, f"{prefix}MissFormBack{idx}")
            if consecutive_misses >= 2:
                break
            continue

        if won:
            cleared += 1
            state.own_monsters_cleared += 1
            consecutive_misses = 0
            _record_diag(
                diag,
                "clear_own_monsters",
                f"won_{idx}",
                f"完成自家第 {cleared} 次 0 体力清怪",
                data={"cleared": cleared},
            )
        else:
            if reason == "defeated":
                detail = "检测到作战失败，已安全中止剩余清怪任务。"
                state.guard_aborts.append(
                    IslandActionOutcome(
                        stage="clear_own_monsters",
                        action_type="clear_monsters",
                        target="自家入侵野怪",
                        status="aborted",
                        detail=detail,
                    )
                )
                _record_diag(diag, "clear_own_monsters", "defeated", detail, level="WARNING")
            else:
                _record_diag(diag, "clear_own_monsters", "battle_abort", f"清怪流程中止：{reason}", level="WARNING")
            _capture_diag(diag, f"own_mob_fail_{idx}", safe_screencap(context))
            _ensure_on_island_main(context, f"{prefix}FightRecover{idx}")
            break

    if cleared > 0:
        detail = f"共清理 {cleared} 只红感叹号入侵野怪"
        state.executed.append(
            IslandActionOutcome(
                stage="clear_own_monsters",
                action_type="clear_monsters",
                target="自家入侵野怪（0体力）",
                status="executed",
                detail=detail,
            )
        )
        _record_diag(diag, "clear_own_monsters", "summary", detail, data={"cleared": cleared})
    elif not any(a.stage == "clear_own_monsters" for a in state.guard_aborts):
        detail = "未命中有效红叹号 0 体力编队入口，跳过剩余清怪"
        state.skipped.append(
            IslandActionOutcome(
                stage="clear_own_monsters",
                action_type="clear_monsters",
                target="自家入侵野怪（0体力）",
                status="skipped",
                detail=detail,
            )
        )
        _record_diag(diag, "clear_own_monsters", "skipped", detail, level="WARNING")
    return cleared


def _is_on_friend_island(context: Context, frame: Any, prefix: str) -> bool:
    dash = ocr_roi(context, frame, f"{prefix}FDash", FRIEND_ISLAND_DASHBOARD_ROI)
    bot = ocr_roi(context, frame, f"{prefix}FBot", FRIEND_ISLAND_BOTTOM_ROI)
    return is_friend_island_entries(dash, bot)


def _open_friends_drawer_and_visit_first(
    context: Context,
    prefix: str,
    tab_point: tuple[int, int],
    *,
    diag: IslandDiagnosticRecorder | None = None,
) -> bool:
    drawer_opened = False
    for attempt in range(2):
        if not _ensure_on_island_main(context, f"{prefix}EnsureMain{attempt}"):
            return False
        if not tap_point(context, f"{prefix}OpenDrawer{attempt}", ISLAND_FRIENDS_BTN_POINT):
            return False
        _, open_ok, aborted = poll_screen(
            context,
            lambda frame, idx: True
            if is_island_friends_drawer_entries(
                ocr_roi(context, frame, f"{prefix}FHdr{attempt}_{idx}", ISLAND_FRIENDS_HEADER_ROI)
            )
            else None,
            initial_delay=0.85,
            interval=0.4,
            max_checks=2 if attempt == 0 else 3,
            screencap_fn=safe_screencap,
            sleep_fn=sleep_with_stop,
        )
        if aborted:
            return False
        if open_ok:
            drawer_opened = True
            break
        if attempt == 0:
            _record_diag(
                diag,
                "friends_social",
                "drawer_retry",
                "首次点击好友按钮未打开抽屉，轻点空白天区消弹窗后重试",
            )
            tap_point(context, f"{prefix}DrawerSkyDismiss", ISLAND_SKY_DISMISS_POINT)
            sleep_with_stop(context, 0.3)

    if not drawer_opened:
        _record_diag(diag, "friends_social", "drawer_open_failed", "连续 2 次点击好友按钮均未打开抽屉", level="WARNING")
        _capture_diag(diag, "friends_drawer_fail", safe_screencap(context))
        _ensure_on_island_main(context, f"{prefix}DrawerOpenFailBack")
        return False

    if not tap_point(context, f"{prefix}SelectTab", tab_point):
        return False
    if not sleep_with_stop(context, 0.9):
        return False
    list_img = safe_screencap(context)
    if list_img is None:
        return False
    list_e = ocr_roi(context, list_img, f"{prefix}List", ISLAND_FRIENDS_LIST_ROI)
    visit_pts = find_friend_list_visit_points(list_e)
    if not visit_pts:
        _record_diag(diag, "friends_social", "empty_friend_list", "好友列表当前页签无可访问按钮")
        _ensure_on_island_main(context, f"{prefix}NoFriendsBack")
        return False
    if not tap_point(context, f"{prefix}VisitFirst", visit_pts[0]):
        return False

    _, visited, aborted = poll_screen(
        context,
        lambda frame, idx: True if _is_on_friend_island(context, frame, f"{prefix}PollF{idx}") else None,
        initial_delay=2.0,
        interval=0.6,
        max_checks=5,
        screencap_fn=safe_screencap,
        sleep_fn=sleep_with_stop,
    )
    if aborted or not visited:
        _record_diag(diag, "friends_social", "visit_failed", "进入首位好友海岛超时", level="WARNING")
        _capture_diag(diag, "friends_visit_fail", safe_screencap(context))
        _ensure_on_island_main(context, f"{prefix}VisitFailBack")
        return False
    return True


def _visit_friends_pass(
    context: Context,
    prefix: str,
    tab_point: tuple[int, int],
    *,
    visit_budget: int,
    runtime_cfg: IslandRuntimeConfig,
    state: _IslandExecState,
    do_clean: bool,
    do_like: bool,
    do_help: bool,
    visited_names: set[str],
    liked_names: set[str],
    cleaned_names: set[str],
    help_checked_names: set[str],
    diag: IslandDiagnosticRecorder | None = None,
) -> dict[str, Any]:
    """在指定好友列表页签依次访问好友并执行点赞/清扫/0体力治安打怪。"""
    result: dict[str, Any] = {
        "opened": False,
        "saw_wrap": False,
        "defeated": False,
        "last_help_rem": None,
        "last_clean_rem": None,
    }
    if visit_budget <= 0:
        return result
    if not _open_friends_drawer_and_visit_first(context, prefix, tab_point, diag=diag):
        return result

    result["opened"] = True
    seen_in_pass: set[str] = set()
    for v_idx in range(visit_budget):
        if is_stopping(context):
            break
        f_img = safe_screencap(context)
        if f_img is None or not _is_on_friend_island(context, f_img, f"{prefix}Chk{v_idx}"):
            break
        dash_e = ocr_roi(context, f_img, f"{prefix}Dash{v_idx}", FRIEND_ISLAND_DASHBOARD_ROI)
        info_e = ocr_roi(context, f_img, f"{prefix}Info{v_idx}", FRIEND_ISLAND_INFO_ROI)
        cnt_e = ocr_roi(context, f_img, f"{prefix}Cnt{v_idx}", FRIEND_ISLAND_COUNTS_ROI)
        bot_e = ocr_roi(context, f_img, f"{prefix}Bot{v_idx}", FRIEND_ISLAND_BOTTOM_ROI)
        f_status = parse_friend_island_status(dash_e, info_e, cnt_e, bot_e)
        fname = str(f_status.get("friend_name") or "").strip()
        if fname and fname in seen_in_pass:
            result["saw_wrap"] = True
            _record_diag(diag, "friends_social", "loop_wrapped", f"好友列表已轮回至 {fname}，结束本轮巡访")
            break
        if fname:
            seen_in_pass.add(fname)
        if not fname or fname not in visited_names:
            state.friend_visits += 1
            if fname:
                visited_names.add(fname)

        help_known = bool(f_status.get("help_remaining_known"))
        clean_known = bool(f_status.get("clean_remaining_known"))
        help_rem = int(f_status.get("help_remaining") or 0)
        clean_rem = int(f_status.get("clean_remaining") or 0)
        f_monsters = int(f_status.get("active_monsters") or 0)
        if help_known:
            result["last_help_rem"] = help_rem
        if clean_known:
            result["last_clean_rem"] = clean_rem

        _record_diag(
            diag,
            "friends_social",
            f"visit_{v_idx}",
            f"访问好友 {fname or '(未识别)'}（怪={f_monsters}, 清扫={clean_rem}, 助战={help_rem}）",
            data={
                "friend_name": fname,
                "active_monsters": f_monsters,
                "clean_remaining": clean_rem,
                "help_remaining": help_rem,
            },
        )

        if do_like and (not fname or fname not in liked_names):
            like_pt = f_status.get("like_point") or FRIEND_ISLAND_LIKE_POINT
            if tap_point(context, f"{prefix}Like{v_idx}", like_pt):
                state.friend_likes_sent += 1
                if fname:
                    liked_names.add(fname)
                sleep_with_stop(context, 0.55)

        if (
            do_clean
            and state.friend_trash_cleaned < runtime_cfg.max_friend_clean_count
            and (not clean_known or clean_rem > 0)
            and (not fname or fname not in cleaned_names)
        ):
            clean_pt = f_status.get("clean_point") or FRIEND_ISLAND_CLEAN_POINT
            if tap_point(context, f"{prefix}Clean{v_idx}", clean_pt):
                sleep_with_stop(context, 1.0)
                dismiss_reward_popup_if_present(context, f"{prefix}CleanReward{v_idx}")
                after_img = safe_screencap(context)
                if after_img is not None:
                    after_dash = ocr_roi(context, after_img, f"{prefix}AfterDash{v_idx}", FRIEND_ISLAND_DASHBOARD_ROI)
                    after_parsed = parse_friend_island_status(after_dash, (), (), ())
                    after_clean_known = bool(after_parsed.get("clean_remaining_known"))
                    after_clean = int(after_parsed.get("clean_remaining") or 0)
                    if after_clean_known:
                        result["last_clean_rem"] = after_clean
                        if after_clean < clean_rem:
                            state.friend_trash_cleaned += 1
                            _record_diag(
                                diag,
                                "friends_social",
                                "cleaned",
                                f"在 {fname or '好友'} 岛清扫垃圾成功（{clean_rem} -> {after_clean}）",
                            )
                        else:
                            _record_diag(
                                diag,
                                "friends_social",
                                "clean_no_change",
                                f"在 {fname or '好友'} 岛点击清扫后余量未下降（仍为 {after_clean}）",
                            )
                    else:
                        _record_diag(
                            diag,
                            "friends_social",
                            "clean_after_unreadable",
                            "清扫后右上角余量未读出，保守不计入清扫成功次数",
                            level="WARNING",
                        )
                if fname:
                    cleaned_names.add(fname)

        if (
            do_help
            and not result["defeated"]
            and state.friend_monsters_helped < runtime_cfg.max_friend_help_fights
            and (not help_known or help_rem > 0)
            and f_monsters > 0
            and (not fname or fname not in help_checked_names)
        ):
            consecutive_misses = 0
            while (
                not is_stopping(context)
                and state.friend_monsters_helped < runtime_cfg.max_friend_help_fights
                and (not help_known or help_rem > 0)
                and f_monsters > 0
                and consecutive_misses < 2
            ):
                if not tap_point(context, f"{prefix}Raccoon{v_idx}_{state.friend_monsters_helped}", FRIEND_ISLAND_RACCOON_POINT):
                    break
                if not sleep_with_stop(context, 1.0):
                    break
                m_img = safe_screencap(context)
                if m_img is None:
                    break
                pts = detect_island_monster_tap_points(m_img)
                _record_diag(
                    diag,
                    "friends_social",
                    f"help_scan_{v_idx}",
                    f"好友 {fname or '(未识别)'} 检测到 {len(pts)} 个红叹号候选",
                    data={"candidates": [list(p) for p in pts[:6]]},
                )
                if not pts:
                    consecutive_misses += 1
                    _capture_diag(diag, f"friend_mob_empty_{v_idx}", m_img)
                    break
                entered, won, reason = _try_enter_and_fight_monster(
                    context,
                    f"{prefix}Help_{v_idx}_{state.friend_monsters_helped}_",
                    pts,
                    is_friend_island=True,
                    max_tries=2,
                    diag=diag,
                    diag_stage="friends_social",
                )
                if reason == "stopped":
                    _ensure_on_island_main(context, f"{prefix}HelpStopBack")
                    return result
                if not entered:
                    consecutive_misses += 1
                    _capture_diag(diag, f"friend_mob_miss_{v_idx}", safe_screencap(context))
                    continue
                if not won:
                    if reason == "defeated":
                        result["defeated"] = True
                        state.guard_aborts.append(
                            IslandActionOutcome(
                                stage="friends_social",
                                action_type="friends_social",
                                target="好友海岛治安助战",
                                status="aborted",
                                detail="好友海岛助战失败，已安全中止剩余助战。",
                            )
                        )
                        _record_diag(diag, "friends_social", "help_defeated", "好友助战失败，安全中止", level="WARNING")
                    else:
                        _record_diag(diag, "friends_social", "help_abort", f"好友助战中止：{reason}", level="WARNING")
                    break

                state.friend_monsters_helped += 1
                consecutive_misses = 0
                after_f_img = safe_screencap(context)
                if after_f_img is not None and _is_on_friend_island(context, after_f_img, f"{prefix}HelpAfterChk{v_idx}"):
                    f_status = parse_friend_island_status(
                        ocr_roi(context, after_f_img, f"{prefix}AfterHDash{v_idx}", FRIEND_ISLAND_DASHBOARD_ROI),
                        ocr_roi(context, after_f_img, f"{prefix}AfterHInfo{v_idx}", FRIEND_ISLAND_INFO_ROI),
                        ocr_roi(context, after_f_img, f"{prefix}AfterHCnt{v_idx}", FRIEND_ISLAND_COUNTS_ROI),
                        ocr_roi(context, after_f_img, f"{prefix}AfterHBot{v_idx}", FRIEND_ISLAND_BOTTOM_ROI),
                    )
                    help_known = bool(f_status.get("help_remaining_known"))
                    help_rem = int(f_status.get("help_remaining") or 0)
                    f_monsters = int(f_status.get("active_monsters") or 0)
                    if help_known:
                        result["last_help_rem"] = help_rem
                else:
                    f_monsters = max(0, f_monsters - 1)
                _record_diag(
                    diag,
                    "friends_social",
                    "help_won",
                    f"好友 {fname or '(未识别)'} 助战打怪成功（累计={state.friend_monsters_helped}, 余怪={f_monsters}, 余次={help_rem}）",
                )
            if fname:
                help_checked_names.add(fname)
        elif do_help and fname:
            help_checked_names.add(fname)

        if result["defeated"]:
            break
        need_clean = (
            do_clean
            and state.friend_trash_cleaned < runtime_cfg.max_friend_clean_count
            and (result["last_clean_rem"] is None or int(result["last_clean_rem"]) > 0)
        )
        need_help = (
            do_help
            and not result["defeated"]
            and state.friend_monsters_helped < runtime_cfg.max_friend_help_fights
            and (result["last_help_rem"] is None or int(result["last_help_rem"]) > 0)
        )
        if not need_clean and not need_help and not do_like:
            break
        if v_idx + 1 >= visit_budget:
            break
        next_pt = f_status.get("next_point") or FRIEND_ISLAND_NEXT_POINT
        if not tap_point(context, f"{prefix}Next{v_idx}", next_pt):
            break
        sleep_with_stop(context, 1.6)

    _ensure_on_island_main(context, f"{prefix}ExitBack")
    return result


def _exec_friends_social_routine(
    context: Context,
    prefix: str,
    *,
    runtime_cfg: IslandRuntimeConfig,
    state: _IslandExecState,
    diag: IslandDiagnosticRecorder | None = None,
) -> None:
    do_clean = runtime_cfg.is_enabled("friend_clean_trash") and runtime_cfg.max_friend_clean_count > 0
    do_like = runtime_cfg.is_enabled("friend_like")
    do_help = runtime_cfg.is_enabled("friend_help_monsters") and runtime_cfg.max_friend_help_fights > 0
    if not (do_clean or do_like or do_help):
        return

    visited_names: set[str] = set()
    liked_names: set[str] = set()
    cleaned_names: set[str] = set()
    help_checked_names: set[str] = set()

    first_tab = ISLAND_FRIENDS_CLEAN_TAB_POINT if (do_clean or do_like) else ISLAND_FRIENDS_SECURITY_TAB_POINT
    p1 = _visit_friends_pass(
        context,
        f"{prefix}Pass1",
        first_tab,
        visit_budget=runtime_cfg.max_friend_visits,
        runtime_cfg=runtime_cfg,
        state=state,
        do_clean=do_clean,
        do_like=do_like,
        do_help=do_help,
        visited_names=visited_names,
        liked_names=liked_names,
        cleaned_names=cleaned_names,
        help_checked_names=help_checked_names,
        diag=diag,
    )

    last_help_rem = p1["last_help_rem"]
    still_need_help = (
        do_help
        and not p1["defeated"]
        and not is_stopping(context)
        and state.friend_monsters_helped < runtime_cfg.max_friend_help_fights
        and (last_help_rem is None or int(last_help_rem) > 0)
    )
    if (
        still_need_help
        and first_tab == ISLAND_FRIENDS_CLEAN_TAB_POINT
        and (not p1["opened"] or not p1["saw_wrap"])
    ):
        pass2_budget = max(1, runtime_cfg.max_friend_visits)
        _visit_friends_pass(
            context,
            f"{prefix}Pass2Sec",
            ISLAND_FRIENDS_SECURITY_TAB_POINT,
            visit_budget=pass2_budget,
            runtime_cfg=runtime_cfg,
            state=state,
            do_clean=do_clean,
            do_like=do_like,
            do_help=do_help,
            visited_names=visited_names,
            liked_names=liked_names,
            cleaned_names=cleaned_names,
            help_checked_names=help_checked_names,
            diag=diag,
        )

    summary_detail = (
        f"拜访 {state.friend_visits} 位好友：清扫垃圾 {state.friend_trash_cleaned} 次、"
        f"点赞 {state.friend_likes_sent} 次、助战打怪 {state.friend_monsters_helped} 次"
    )
    if state.friend_trash_cleaned > 0 or state.friend_likes_sent > 0 or state.friend_monsters_helped > 0:
        state.executed.append(
            IslandActionOutcome(
                stage="friends_social",
                action_type="friends_social",
                target="好友海岛清扫/点赞/助战",
                status="executed",
                detail=summary_detail,
            )
        )
        _record_diag(diag, "friends_social", "summary", summary_detail)
    else:
        state.skipped.append(
            IslandActionOutcome(
                stage="friends_social",
                action_type="friends_social",
                target="好友海岛清扫/点赞/助战",
                status="skipped",
                detail=f"{summary_detail}（未达成有效收益或抽屉/次数受限）",
            )
        )
        _record_diag(diag, "friends_social", "skipped", summary_detail)


@AgentServer.custom_action("island_plan_scan_run")
class IslandPlanScanAction(CustomAction):
    """海岛（蜃息岛）只读体检扫描、规划看板与零风险日常闭环自动执行。"""

    @retry_on_network_restart(max_restarts=1)
    def run(
        self,
        context: Context,
        argv: CustomAction.RunArg,
    ) -> CustomAction.RunResult:
        diag_holder: list[IslandDiagnosticRecorder] = []
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
                    else IslandDiagnosticRecorder(export_mode="bundle", root_path=ROOT_PATH)
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
            err_msg = f"[IslandPlan] 运行过程中发生异常：{type(exc).__name__}: {exc}{bundle_hint}"
            print(err_msg, flush=True)
            _push_complete_focus(context, err_msg)
            return CustomAction.RunResult(success=False)

    def _run_scan(
        self,
        context: Context,
        argv: CustomAction.RunArg,
        *,
        _diag_holder: list[IslandDiagnosticRecorder] | None = None,
    ) -> CustomAction.RunResult:
        prefix = "IslandPlan"
        params = _resolve_plan_params(context, argv)
        runtime_cfg = resolve_island_runtime_config(params)

        diag = IslandDiagnosticRecorder(
            export_mode=runtime_cfg.diag_export_mode,
            root_path=ROOT_PATH,
            options_summary=runtime_cfg.to_summary_dict(),
        )
        if _diag_holder is not None:
            _diag_holder.append(diag)
        diag.record(
            "init",
            "options_resolved",
            f"mode={runtime_cfg.exec_mode}, scope={runtime_cfg.auto_scope}, reserve={runtime_cfg.reserve_coins}",
            data=runtime_cfg.to_summary_dict(),
        )

        first_img = safe_screencap(context)
        if first_img is None:
            diag.record("init", "screencap_failed", "首帧截图失败", level="ERROR")
            return CustomAction.RunResult(success=False)

        in_island = _is_on_island_main(context, first_img, f"{prefix}Init")
        entered_from_lobby = False
        uid = "unknown"
        drawer_wallet: dict[str, int] = {}

        if in_island:
            _acc_path, acc_data = find_account_config()
            if isinstance(acc_data, dict) and str(acc_data.get("uid") or "").strip():
                uid = str(acc_data["uid"]).strip()
            diag.set_uid(uid)
            diag.record("entry", "already_in_island", "启动时已处于海岛主界面")
        else:
            entered, nav_uid, drawer_wallet, reason = _navigate_lobby_to_island(context, prefix)
            if nav_uid and nav_uid != "unknown":
                uid = nav_uid
                diag.set_uid(uid)
            if reason == "stopped" or is_stopping(context):
                diag.record("entry", "stopped", f"导航过程中收到停止信号（reason={reason}）", level="WARNING")
                return CustomAction.RunResult(success=False)
            if entered:
                in_island = True
                entered_from_lobby = True
                diag.record("entry", f"entered_{reason}", "已通过活动中心经营活动进入海岛", data=drawer_wallet)
            else:
                diag.record("entry", "entry_failed", f"未能进入海岛（{reason}），回退使用已有快照生成报告", level="WARNING")
                diag.capture_frame("entry_failed", safe_screencap(context))

        account_path = _account_config_path_for_uid(uid)
        previous_snapshot = load_account_snapshot(account_path)

        main_hud: dict[str, Any] = {}
        report_data: dict[str, Any] = {}
        ops_data: dict[str, Any] = {}
        invest_data: dict[str, Any] = {}
        trash_data: dict[str, Any] = {}
        exchange_data: dict[str, Any] = {}
        expand_data: dict[str, Any] = {}
        post_hud: dict[str, Any] = {}
        post_live_monsters: int | None = None
        exec_state = _IslandExecState()
        coins_before = int(drawer_wallet.get("coins") or previous_snapshot.wallet.coins or 0)

        if in_island:
            main_img = safe_screencap(context)
            if main_img is None:
                return CustomAction.RunResult(success=False)
            main_hud = parse_island_main_hud(
                ocr_roi(context, main_img, f"{prefix}HudTop", ISLAND_TOP_BAR_ROI),
                ocr_roi(context, main_img, f"{prefix}HudLeft", ISLAND_LEFT_HUD_ROI),
                ocr_roi(context, main_img, f"{prefix}HudCnt", ISLAND_COUNTS_HUD_ROI),
                ticket_entries=ocr_roi(context, main_img, f"{prefix}HudTkt", ISLAND_TICKETS_ROI),
                shell_entries=ocr_roi(context, main_img, f"{prefix}HudShl", ISLAND_SHELLS_ROI),
            )
            diag.record("scan", "main_hud", "完成主界面 HUD 扫描", data=main_hud)

            if not is_stopping(context):
                report_data = _scan_report_modal(context, f"{prefix}Scan")
                diag.record("scan", "report_modal", "完成海岛经营报表总览扫描", data=report_data)

            if not is_stopping(context):
                should_claim_rev = runtime_cfg.exec_mode == "execute_safe_auto" and runtime_cfg.is_enabled("claim_revenue")
                should_auto_invest = runtime_cfg.exec_mode == "execute_safe_auto" and runtime_cfg.is_enabled("auto_invest")
                ops_data, invest_data = _scan_and_maybe_claim_ops(
                    context,
                    f"{prefix}ScanOps",
                    claim_revenue=should_claim_rev,
                    auto_invest=should_auto_invest,
                    reserve_coins=runtime_cfg.reserve_coins,
                    coins_budget=coins_before,
                    state=exec_state,
                    diag=diag,
                )
                invest_summary = {k: v for k, v in invest_data.items() if k != "cards"}
                diag.record("scan", "ops_and_invest", "完成营运概览与投资扫描", data={**ops_data, **invest_summary})

            if not is_stopping(context):
                should_collect_trash = (
                    runtime_cfg.exec_mode == "execute_safe_auto" and runtime_cfg.is_enabled("collect_trash")
                )
                try:
                    trash_data = _scan_and_maybe_collect_trash(
                        context,
                        f"{prefix}Trash",
                        collect_trash=should_collect_trash,
                        state=exec_state,
                        diag=diag,
                    )
                    diag.record("scan", "trash_station", "完成垃圾站总览扫描", data=trash_data)
                except NetworkRestartedToLobbyError:
                    raise
                except Exception as exc:
                    diag.record_exception("collect_trash", exc, traceback.format_exc())
                    _ensure_on_island_main(context, f"{prefix}TrashErrBack")

            if not is_stopping(context):
                try:
                    exchange_data = _scan_exchange_shop_readonly(
                        context,
                        f"{prefix}Exch",
                        diag=diag,
                    )
                except NetworkRestartedToLobbyError:
                    raise
                except Exception as exc:
                    diag.record_exception("exchange_shop", exc, traceback.format_exc())
                    _ensure_on_island_main(context, f"{prefix}ExchErrBack")

            should_auto_expand = runtime_cfg.exec_mode == "execute_safe_auto" and runtime_cfg.is_enabled("auto_expand")
            if not is_stopping(context) and (runtime_cfg.exec_mode == "plan_only" or should_auto_expand):
                cur_level = int(report_data.get("level") or main_hud.get("level") or previous_snapshot.island.level or 0)
                cur_live_coins = int(invest_data.get("live_coins") or 0) or max(
                    0,
                    coins_before + int(exec_state.revenue_claimed_coins) - int(exec_state.invest_spent_coins),
                )
                cur_live_tickets = int(
                    main_hud.get("material_tickets") or previous_snapshot.island.material_tickets or 0
                )
                try:
                    expand_data = _scan_and_maybe_expand_island(
                        context,
                        f"{prefix}Expand",
                        allow_execute=should_auto_expand,
                        current_level=cur_level,
                        live_coins=cur_live_coins,
                        live_tickets=cur_live_tickets,
                        reserve_coins=runtime_cfg.reserve_coins,
                        state=exec_state,
                        diag=diag,
                    )
                except NetworkRestartedToLobbyError:
                    raise
                except Exception as exc:
                    diag.record_exception("auto_expand", exc, traceback.format_exc())
                    _ensure_on_island_main(context, f"{prefix}ExpErrBack")

            if runtime_cfg.exec_mode == "execute_safe_auto" and not is_stopping(context):
                if runtime_cfg.is_enabled("clear_own_monsters") and not is_stopping(context):
                    try:
                        _exec_clear_own_monsters(
                            context,
                            f"{prefix}OwnMob",
                            max_fights=runtime_cfg.max_own_monster_fights,
                            stability_current=int(report_data.get("stability_current") or previous_snapshot.island.stability_current or 0),
                            stability_max=int(report_data.get("stability_max") or previous_snapshot.island.stability_max or 200),
                            active_monsters=int(main_hud.get("active_monsters") or previous_snapshot.island.active_monsters or 0),
                            state=exec_state,
                            diag=diag,
                        )
                    except NetworkRestartedToLobbyError:
                        raise
                    except Exception as exc:
                        diag.record_exception("clear_own_monsters", exc, traceback.format_exc())
                        _ensure_on_island_main(context, f"{prefix}MobErrBack")

                if not is_stopping(context):
                    try:
                        _exec_friends_social_routine(
                            context,
                            f"{prefix}Friend",
                            runtime_cfg=runtime_cfg,
                            state=exec_state,
                            diag=diag,
                        )
                    except NetworkRestartedToLobbyError:
                        raise
                    except Exception as exc:
                        diag.record_exception("friends_social", exc, traceback.format_exc())
                        _ensure_on_island_main(context, f"{prefix}FriendErrBack")

                if runtime_cfg.is_enabled("claim_todo") and not is_stopping(context):
                    try:
                        _exec_claim_todo_rewards(context, f"{prefix}Todo", exec_state, diag=diag)
                    except NetworkRestartedToLobbyError:
                        raise
                    except Exception as exc:
                        diag.record_exception("claim_todo", exc, traceback.format_exc())
                        _ensure_on_island_main(context, f"{prefix}TodoErrBack")

                if not is_stopping(context) and _ensure_on_island_main(context, f"{prefix}PostHudBack"):
                    post_img = safe_screencap(context)
                    if post_img is not None:
                        post_cnt_e = ocr_roi(context, post_img, f"{prefix}PostHudCnt", ISLAND_COUNTS_HUD_ROI)
                        post_hud = parse_island_main_hud(
                            ocr_roi(context, post_img, f"{prefix}PostHudTop", ISLAND_TOP_BAR_ROI),
                            ocr_roi(context, post_img, f"{prefix}PostHudLeft", ISLAND_LEFT_HUD_ROI),
                            post_cnt_e,
                            ticket_entries=ocr_roi(context, post_img, f"{prefix}PostHudTkt", ISLAND_TICKETS_ROI),
                            shell_entries=ocr_roi(context, post_img, f"{prefix}PostHudShl", ISLAND_SHELLS_ROI),
                        )
                        valid_post_cnt = [
                            e
                            for e in post_cnt_e
                            if isinstance(e, dict) and any(ch.isdigit() for ch in str(e.get("text") or ""))
                        ]
                        if len(valid_post_cnt) >= 2:
                            post_live_monsters = int(post_hud.get("active_monsters") or 0)
                        diag.record("scan", "post_main_hud", "完成执行后主界面 HUD 刷新", data=post_hud)

        tickets_before = int(main_hud.get("material_tickets") or previous_snapshot.island.material_tickets or 0)
        shells_before = int(
            main_hud.get("shell_coins")
            or exchange_data.get("shell_coins")
            or previous_snapshot.island.shell_coins
            or 0
        )
        coins_after = max(
            0,
            coins_before
            + int(exec_state.revenue_claimed_coins)
            - int(exec_state.invest_spent_coins)
            - int(exec_state.expand_spent_coins),
        )
        wallet_payload = previous_snapshot.wallet.model_dump(mode="python")
        wallet_payload["coins"] = coins_after
        if drawer_wallet.get("huashi"):
            wallet_payload["huashi"] = int(drawer_wallet["huashi"])

        island_payload = previous_snapshot.island.model_dump(mode="python")
        if in_island:
            island_payload["level"] = int(
                report_data.get("level")
                or post_hud.get("level")
                or main_hud.get("level")
                or island_payload.get("level")
                or 0
            )
            if exec_state.islands_expanded > 0:
                island_payload["unlocked_islands"] = min(
                    6,
                    max(1, int(island_payload.get("unlocked_islands") or 1)) + int(exec_state.islands_expanded),
                )
            island_payload["cabin_level"] = int(report_data.get("cabin_level") or island_payload.get("cabin_level") or 0)
            island_payload["stability_current"] = int(report_data.get("stability_current") if "stability_current" in report_data else island_payload.get("stability_current") or 0)
            island_payload["stability_max"] = int(report_data.get("stability_max") or island_payload.get("stability_max") or 200)
            if post_live_monsters is not None:
                island_payload["active_monsters"] = post_live_monsters
            else:
                island_payload["active_monsters"] = max(
                    0,
                    int(main_hud.get("active_monsters") if "active_monsters" in main_hud else island_payload.get("active_monsters") or 0)
                    - int(exec_state.own_monsters_cleared),
                )
            island_payload["visitors_current"] = int(
                post_hud.get("visitors_current")
                or main_hud.get("visitors_current")
                or island_payload.get("visitors_current")
                or 0
            )
            island_payload["total_visitors"] = int(ops_data.get("total_visitors") or report_data.get("total_visitors") or island_payload.get("total_visitors") or 0)
            island_payload["operating_days"] = int(report_data.get("operating_days") or island_payload.get("operating_days") or 0)
            island_payload["facilities_count"] = int(report_data.get("facilities_count") or island_payload.get("facilities_count") or 0)
            island_payload["decorations_count"] = int(report_data.get("decorations_count") or island_payload.get("decorations_count") or 0)
            island_payload["cleanliness_pct"] = int(report_data.get("cleanliness_pct") if "cleanliness_pct" in report_data else main_hud.get("cleanliness_pct") or 100)
            island_payload["trash_rate_per_hour"] = int(trash_data.get("trash_rate_per_hour") or report_data.get("trash_rate_per_hour") or island_payload.get("trash_rate_per_hour") or 0)
            if "trash_blocks_stored" in trash_data:
                island_payload["trash_blocks_stored"] = int(trash_data["trash_blocks_stored"])
            elif "trash_blocks_stored" in report_data:
                island_payload["trash_blocks_stored"] = int(report_data["trash_blocks_stored"])
            if "trash_blocks_cap" in trash_data:
                island_payload["trash_blocks_cap"] = int(trash_data["trash_blocks_cap"])
            if "trash_pending_raw" in trash_data:
                island_payload["trash_pending_raw"] = int(trash_data["trash_pending_raw"])
            if "trash_station_level" in trash_data:
                island_payload["trash_station_level"] = int(trash_data["trash_station_level"])
            if isinstance(report_data.get("scores"), dict):
                island_payload["scores"] = dict(report_data["scores"])
            if "avg_stay_days" in ops_data:
                island_payload["avg_stay_days"] = float(ops_data["avg_stay_days"])
            if "share_ratio_pct" in ops_data:
                island_payload["share_ratio_pct"] = float(ops_data["share_ratio_pct"])
            if "ticket_price" in ops_data:
                island_payload["ticket_price"] = int(ops_data["ticket_price"])
            if "tax_rate_pct" in ops_data:
                island_payload["tax_rate_pct"] = float(ops_data["tax_rate_pct"])
            if "pending_revenue_coins" in ops_data:
                island_payload["pending_revenue_coins"] = int(ops_data["pending_revenue_coins"])
            if post_hud.get("today_revenue_coins"):
                island_payload["today_revenue_coins"] = int(post_hud["today_revenue_coins"])
            elif "today_revenue_coins" in main_hud:
                island_payload["today_revenue_coins"] = int(main_hud["today_revenue_coins"])
            if "invested_total" in invest_data:
                island_payload["invested_total"] = int(invest_data["invested_total"])
            if "invest_remaining" in invest_data:
                island_payload["invest_remaining"] = int(invest_data["invest_remaining"])

            post_tickets = int(post_hud.get("material_tickets") or 0)
            if post_tickets > 0:
                island_payload["material_tickets"] = post_tickets
            elif exec_state.expand_spent_tickets > 0:
                island_payload["material_tickets"] = max(0, tickets_before - int(exec_state.expand_spent_tickets))
            else:
                island_payload["material_tickets"] = tickets_before

            post_shells = int(post_hud.get("shell_coins") or 0)
            island_payload["shell_coins"] = post_shells or int(
                main_hud.get("shell_coins") or exchange_data.get("shell_coins") or island_payload.get("shell_coins") or 0
            )
            if exchange_data and "volleyball_coins" in exchange_data:
                island_payload["volleyball_coins"] = int(exchange_data["volleyball_coins"])
            island_payload["updated_at"] = None

        save_account_snapshot_sections(
            account_path,
            uid=uid,
            wallet=wallet_payload,
            island=island_payload,
        )
        snapshot = load_account_snapshot(account_path)
        island_report = plan_island(
            snapshot,
            IslandPlanOptions(reserve_coins=runtime_cfg.reserve_coins),
        )
        run_receipt = IslandRunReceipt(
            exec_mode=runtime_cfg.exec_mode,
            auto_scope=runtime_cfg.auto_scope,
            coins_before=coins_before,
            coins_after=coins_after,
            tickets_before=tickets_before,
            tickets_after=int(snapshot.island.material_tickets),
            shells_before=shells_before,
            shells_after=int(snapshot.island.shell_coins),
            revenue_claimed_coins=exec_state.revenue_claimed_coins,
            trash_blocks_collected=exec_state.trash_blocks_collected,
            own_monsters_cleared=exec_state.own_monsters_cleared,
            todo_rewards_claimed=exec_state.todo_rewards_claimed,
            friend_visits=exec_state.friend_visits,
            friend_trash_cleaned=exec_state.friend_trash_cleaned,
            friend_likes_sent=exec_state.friend_likes_sent,
            friend_monsters_helped=exec_state.friend_monsters_helped,
            invest_executed_count=exec_state.invest_executed_count,
            invest_spent_coins=exec_state.invest_spent_coins,
            islands_expanded=exec_state.islands_expanded,
            expand_spent_coins=exec_state.expand_spent_coins,
            expand_spent_tickets=exec_state.expand_spent_tickets,
            executed=exec_state.executed,
            skipped=exec_state.skipped,
            guard_aborts=exec_state.guard_aborts,
        )

        safe_uid = "".join(ch for ch in str(snapshot.uid or "unknown") if ch.isalnum() or ch in {"_", "-"}) or "unknown"
        report_dir = ROOT_PATH / "config" / "planning"
        report_dir.mkdir(parents=True, exist_ok=True)
        md_path = report_dir / f"latest_island_report_{safe_uid}.md"
        json_path = report_dir / f"latest_island_report_{safe_uid}.json"
        html_path = report_dir / f"latest_island_report_{safe_uid}.html"

        diag.record(
            "summary",
            "receipt",
            (
                f"revenue={exec_state.revenue_claimed_coins}, trash={exec_state.trash_blocks_collected}, "
                f"own_mob={exec_state.own_monsters_cleared}, todo={exec_state.todo_rewards_claimed}, "
                f"visits={exec_state.friend_visits}, clean={exec_state.friend_trash_cleaned}, "
                f"like={exec_state.friend_likes_sent}, help={exec_state.friend_monsters_helped}, "
                f"invest={exec_state.invest_executed_count}, expand={exec_state.islands_expanded}"
            ),
            data=run_receipt.model_dump(mode="json"),
        )

        diag_log_path: Path | None = None
        issue_bundle_path: Path | None = None
        try:
            diag_files = diag.export(
                report_dir / "logs",
                snapshot=snapshot,
                island_report=island_report,
                run_receipt=run_receipt,
            )
            diag_log_path = diag_files.get("log_path")
            issue_bundle_path = diag_files.get("bundle_path")
        except Exception as diag_exc:
            print(f"[IslandPlan] 诊断日志导出失败（不影响主流程）：{diag_exc}", flush=True)

        md_path.write_text(format_island_plan_markdown(island_report, run_receipt), encoding="utf-8")
        json_path.write_text(
            json.dumps(
                {
                    "island": island_report.model_dump(mode="json"),
                    "run_receipt": run_receipt.model_dump(mode="json"),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        html_path.write_text(
            format_island_report_html(
                island_report,
                run_receipt,
                diag_log_path=diag_log_path,
                issue_bundle_path=issue_bundle_path,
            ),
            encoding="utf-8",
        )

        summary_text = format_island_mxu_summary(
            island_report,
            run_receipt,
            issue_bundle_path=issue_bundle_path or diag_log_path,
        )
        print(summary_text, flush=True)
        _push_complete_focus(context, summary_text)

        if entered_from_lobby and not is_stopping(context):
            return_to_lobby(context, f"{prefix}FinishLobby")

        if runtime_cfg.auto_open_report and not is_stopping(context):
            _open_report_in_browser(html_path)

        return CustomAction.RunResult(success=not is_stopping(context))
