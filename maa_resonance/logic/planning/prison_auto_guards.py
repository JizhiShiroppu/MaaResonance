"""整顿中心（监狱）Stage 3 实机标定坐标、像素安全护栏与子界面 OCR 解析器。"""
from __future__ import annotations

import re
from typing import Any, Mapping, Optional, Sequence

import numpy as np

from maa_resonance.logic.planning.catalogs import load_prison_strategy_catalog
from maa_resonance.logic.planning.prison_scanner import (
    ORDER_UI_STOPWORDS,
    _clean_text,
    _entry_box,
    _entry_center,
    _filter_top_bar_icon_noise,
    _known_order_item_names,
    _merge_horizontal_adjacent,
    _parse_fraction,
    parse_cn_number,
)

# ---------------- 1280x720 实机标定坐标与 ROI ----------------

PRISON_DOCK_SHOP_FALLBACK: tuple[int, int] = (430, 616)

# 黑月订单站（2 跳：总览 -> 门面 -> 运输订单）
ORDERS_FOYER_DAILY_POINT: tuple[int, int] = (950, 321)
ORDERS_FOYER_WEEKLY_POINT: tuple[int, int] = (950, 404)
ORDERS_DELIVER_BUTTON_ROI: tuple[int, int, int, int] = (785, 585, 265, 75)
ORDERS_DELIVER_POINT: tuple[int, int] = (955, 622)
ORDERS_SLOT_POINTS: tuple[tuple[int, int], ...] = (
    (1165, 115),
    (1165, 185),
    (1165, 258),
    (1165, 340),
    (1165, 415),
    (1165, 490),
)
ORDERS_RIGHT_SLOTS_ROI: tuple[int, int, int, int] = (1030, 90, 240, 560)

# 仓库与双币扩容弹窗（严守左侧铁盟币页签、绝不触碰右侧桦石页签）
WAREHOUSE_RAW_EXPAND_POINT: tuple[int, int] = (1163, 323)
WAREHOUSE_FIN_EXPAND_POINT: tuple[int, int] = (1163, 654)
WAREHOUSE_BUY_CARD_POINT: tuple[int, int] = (490, 420)
WAREHOUSE_OVERLAY_EXIT_POINT: tuple[int, int] = (200, 360)
WAREHOUSE_MODAL_COIN_TAB_POINT: tuple[int, int] = (503, 443)
WAREHOUSE_MODAL_COIN_PATCH_ROI: tuple[int, int, int, int] = (372, 436, 40, 16)
WAREHOUSE_MODAL_HUASHI_PATCH_ROI: tuple[int, int, int, int] = (870, 436, 40, 16)
WAREHOUSE_MODAL_TABS_ROI: tuple[int, int, int, int] = (350, 415, 590, 130)
WAREHOUSE_MODAL_PLUS1_POINT: tuple[int, int] = (828, 381)
WAREHOUSE_MODAL_CANCEL_POINT: tuple[int, int] = (324, 591)
WAREHOUSE_MODAL_CONFIRM_POINT: tuple[int, int] = (958, 588)

# 整顿中心兑换商店（含精确工票 + 铁盟币顶栏）
SHOP_WORK_TICKETS_ROI: tuple[int, int, int, int] = (867, 8, 192, 52)
SHOP_COINS_ROI: tuple[int, int, int, int] = (1075, 8, 192, 52)
SHOP_TAB_RECIPES_POINT: tuple[int, int] = (931, 108)
SHOP_TAB_ITEMS_POINT: tuple[int, int] = (1130, 108)
SHOP_BODY_ROI: tuple[int, int, int, int] = (440, 128, 825, 580)
SHOP_CONFIRM_MODAL_ROI: tuple[int, int, int, int] = (220, 180, 840, 440)
SHOP_MODAL_CANCEL_POINT: tuple[int, int] = (322, 536)
SHOP_MODAL_CONFIRM_POINT: tuple[int, int] = (957, 536)

# 右翼房间缩放、建造升级（含电力中心严禁切换至安装电机页护栏）
PRISON_RIGHT_WING_PAN_SWIPE: tuple[tuple[int, int], tuple[int, int]] = ((960, 520), (420, 180))
PRISON_UPPER_WING_PAN_SWIPE: tuple[tuple[int, int], tuple[int, int]] = ((640, 220), (640, 560))
ROOM_BUBBLE_ROI: tuple[int, int, int, int] = (690, 210, 210, 230)
ROOM_BUBBLE_TOP_FALLBACK: tuple[int, int] = (792, 319)
ROOM_BUBBLE_BOTTOM_FALLBACK: tuple[int, int] = (792, 382)
POWER_BUBBLE_BUILD_FALLBACK: tuple[int, int] = (793, 349)
ROOM_UNZOOM_LEFT_COL_POINT: tuple[int, int] = (640, 200)
ROOM_UNZOOM_RIGHT_COL_POINT: tuple[int, int] = (1050, 360)
POWER_TAB_ROOM_UPGRADE_PATCH_ROI: tuple[int, int, int, int] = (805, 24, 40, 14)
POWER_TAB_MOTOR_PATCH_ROI: tuple[int, int, int, int] = (1180, 24, 40, 14)
POWER_TABS_OCR_ROI: tuple[int, int, int, int] = (770, 10, 480, 62)
ROOM_BUILD_PANEL_ROI: tuple[int, int, int, int] = (720, 60, 540, 580)
ROOM_BUILD_BUTTON_ROI: tuple[int, int, int, int] = (880, 570, 280, 85)
ROOM_BUILD_CONFIRM_POINT: tuple[int, int] = (1020, 612)

# 原料车间预存铁盟币弹窗（x=88 起排除左侧黄色金币图标防误拼首位 "1"）
RAW_PREDEPOSIT_BAL_ROI: tuple[int, int, int, int] = (88, 405, 232, 65)
RAW_PREDEPOSIT_BTN_POINT: tuple[int, int] = (398, 438)
RAW_PREDEPOSIT_SLIDER_X_MIN: int = 506
RAW_PREDEPOSIT_SLIDER_X_MAX: int = 773
RAW_PREDEPOSIT_SLIDER_Y: int = 396
RAW_PREDEPOSIT_MODAL_QTY_ROI: tuple[int, int, int, int] = (485, 345, 310, 45)
RAW_PREDEPOSIT_CANCEL_POINT: tuple[int, int] = (322, 536)
RAW_PREDEPOSIT_CONFIRM_POINT: tuple[int, int] = (957, 536)

# 生产车间与一键排产面板
WORKSHOP_1_FALLBACK: tuple[int, int] = (950, 260)
WORKSHOP_2_FALLBACK: tuple[int, int] = (950, 150)
WORKSHOP_ENTER_PROD_POINT: tuple[int, int] = (1227, 634)
WORKSHOP_INTERIOR_CHECK_ROI: tuple[int, int, int, int] = (1060, 585, 215, 115)
PROD_SELECT_ALL_ROI: tuple[int, int, int, int] = (1090, 465, 180, 125)
PROD_RECIPE_CARDS_ROI: tuple[int, int, int, int] = (10, 575, 760, 145)
PROD_CARDS_SCROLL_LEFT_SWIPE: tuple[tuple[int, int], tuple[int, int]] = ((660, 635), (180, 635))
PROD_READY_PANEL_ROI: tuple[int, int, int, int] = (775, 515, 495, 200)
PROD_DUR_2H_POINT: tuple[int, int] = (834, 673)
PROD_DUR_4H_POINT: tuple[int, int] = (932, 673)
PROD_DUR_8H_POINT: tuple[int, int] = (1030, 673)
PROD_CONFIRM_START_POINT: tuple[int, int] = (1184, 673)

# 事项一览领奖、囚犯名册入住、财务中心开关、黑月免费删单与兑换道具页签
PRISON_TODO_BTN_ROI: tuple[int, int, int, int] = (1075, 100, 200, 80)
PRISON_TODO_BTN_POINT: tuple[int, int, int] = (1180, 138)
PRISON_TODO_CLAIM_ROI: tuple[int, int, int, int] = (1110, 40, 165, 660)
PRISON_REWARD_DISMISS_POINT: tuple[int, int] = (640, 650)

PRISON_TOP_PRISONER_BAR_POINT: tuple[int, int] = (910, 38)
PRISON_ROSTER_CHECKIN_BTN_ROI: tuple[int, int, int, int] = (1010, 645, 255, 70)
PRISON_ROSTER_CHECKIN_BTN_POINT: tuple[int, int] = (1152, 686)
PRISON_CHECKIN_STATUS_ROI: tuple[int, int, int, int] = (15, 650, 720, 65)
PRISON_CHECKIN_SELECT_ALL_POINT: tuple[int, int] = (935, 686)
PRISON_CHECKIN_CONFIRM_POINT: tuple[int, int] = (1152, 686)

FINANCE_MODAL_CHECK_ROI: tuple[int, int, int, int] = (560, 150, 560, 340)
FINANCE_TOGGLE_LEFT_ROI: tuple[int, int, int, int] = (1026, 415, 12, 11)
FINANCE_TOGGLE_MID_ROI: tuple[int, int, int, int] = (1044, 415, 14, 11)
FINANCE_TOGGLE_RIGHT_ROI: tuple[int, int, int, int] = (1058, 415, 12, 11)
FINANCE_TOGGLE_POINT: tuple[int, int] = (1050, 420)
FINANCE_DISMISS_POINT: tuple[int, int] = (120, 660)

ORDERS_DELETE_BTN_ROI: tuple[int, int, int, int] = (595, 585, 115, 95)
ORDERS_DELETE_BTN_POINT: tuple[int, int] = (645, 628)
SHOP_ITEMS_SCROLL_DOWN_SWIPE: tuple[tuple[int, int], tuple[int, int]] = ((820, 560), (820, 260))

# 原料车间选人开工与生产车间「车间编辑」（快速编队/设组长/机器升级）
RAW_PROD_ACTION_ROI: tuple[int, int, int, int] = (30, 635, 480, 75)
RAW_PROD_START_POINT: tuple[int, int] = (265, 672)
RAW_PROD_WORKERS_ROI: tuple[int, int, int, int] = (530, 260, 420, 55)
RAW_PROD_SELECT_PRISONER_POINT: tuple[int, int] = (885, 668)
RAW_PROD_PICKER_GRID_ROI: tuple[int, int, int, int] = (20, 80, 1240, 455)
RAW_PROD_PICKER_CARD_CENTERS: tuple[tuple[int, int], ...] = (
    (118, 190),
    (326, 190),
    (534, 190),
    (742, 190),
    (950, 190),
    (1158, 190),
    (118, 420),
    (326, 420),
    (534, 420),
    (742, 420),
    (950, 420),
    (1158, 420),
)
RAW_PROD_PICKER_COUNT_ROI: tuple[int, int, int, int] = (20, 645, 360, 65)
RAW_PROD_PICKER_QUICK_BTN_ROI: tuple[int, int, int, int] = (810, 640, 240, 70)
RAW_PROD_PICKER_QUICK_BTN_POINT: tuple[int, int] = (932, 672)
RAW_PROD_PICKER_CONFIRM_POINT: tuple[int, int] = (1152, 672)

WORKSHOP_ENTER_EDIT_POINT: tuple[int, int] = (1134, 634)
WS_EDIT_PANEL_CHECK_ROI: tuple[int, int, int, int] = (30, 470, 380, 60)
WS_EDIT_QUICK_TEAM_POINT: tuple[int, int] = (120, 496)
WS_EDIT_APPLY_POINT: tuple[int, int] = (1180, 496)
WS_EDIT_LEADER_TOP_ROI: tuple[int, int, int, int] = (770, 8, 250, 62)
WS_EDIT_SET_LEADER_ROI: tuple[int, int, int, int] = (610, 620, 150, 85)
WS_EDIT_SET_LEADER_POINT: tuple[int, int] = (675, 656)
WS_EDIT_MACHINE_COST_ROI: tuple[int, int, int, int] = (945, 610, 185, 95)
WS_EDIT_MACHINE_UPGRADE_ROI: tuple[int, int, int, int] = (1120, 620, 150, 85)
WS_EDIT_MACHINE_UPGRADE_POINT: tuple[int, int] = (1192, 656)
WS_EDIT_MACHINE_SLOT_CENTERS: tuple[tuple[int, int], ...] = (
    (140, 155),
    (140, 275),
    (140, 395),
    (340, 155),
    (340, 275),
    (340, 395),
)
WS_EDIT_QUICK_SORT_EFF_POINT: tuple[int, int] = (885, 42)


# ---------------- 通道无关像素安全护栏 ----------------


def _safe_merge(
    entries: Sequence[Mapping[str, Any]],
    *,
    max_gap_x: int = 10,
    max_row_diff: float = 12.0,
) -> list[dict[str, Any]]:
    """合并同一行相近带框 OCR 条目，同时保留无坐标框条目以兼容轻量单元测试输入。"""
    boxed: list[Mapping[str, Any]] = []
    unboxed: list[dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, Mapping):
            continue
        if _entry_box(entry) is not None:
            boxed.append(entry)
        else:
            text = _clean_text(entry.get("text"))
            if text:
                unboxed.append({"text": text})
    merged = _merge_horizontal_adjacent(boxed, max_gap_x=max_gap_x, max_row_diff=max_row_diff)
    return merged + unboxed


def sample_roi_mean_brightness(
    image: Any,
    roi: tuple[int, int, int, int],
) -> Optional[float]:
    """按 1280x720 比例采样区域均值亮度（通道无关，空图或异常形状返回 None）。"""
    if image is None:
        return None
    try:
        arr = np.asarray(image)
    except Exception:
        return None
    if arr.ndim != 3 or arr.shape[2] < 3 or arr.shape[0] <= 0 or arr.shape[1] <= 0:
        return None
    img_h, img_w = int(arr.shape[0]), int(arr.shape[1])
    rx, ry, rw, rh = roi
    x1 = max(0, min(img_w - 1, int(round(rx * img_w / 1280.0))))
    y1 = max(0, min(img_h - 1, int(round(ry * img_h / 720.0))))
    x2 = max(x1 + 1, min(img_w, int(round((rx + rw) * img_w / 1280.0))))
    y2 = max(y1 + 1, min(img_h, int(round((ry + rh) * img_h / 720.0))))
    patch = arr[y1:y2, x1:x2, :3]
    if patch.size == 0:
        return None
    return float(patch.mean())


def _verify_left_white_right_dark_tabs(
    image: Any,
    tab_ocr_entries: Sequence[Mapping[str, Any]],
    *,
    left_roi: tuple[int, int, int, int],
    right_roi: tuple[int, int, int, int],
    required_left_keyword: str,
    context_label: str,
) -> tuple[bool, str]:
    left_mean = sample_roi_mean_brightness(image, left_roi)
    right_mean = sample_roi_mean_brightness(image, right_roi)
    if left_mean is None or right_mean is None:
        return False, f"{context_label}：截图无效，无法完成双重像素校验。"
    joined_ocr = "".join(_clean_text(e.get("text")) for e in tab_ocr_entries if isinstance(e, Mapping))
    if required_left_keyword not in joined_ocr:
        return False, f"{context_label}：OCR 未检测到「{required_left_keyword}」安全页签（当前：{joined_ocr or '空'}）。"
    if left_mean < 215.0 or right_mean > 85.0:
        return (
            False,
            f"{context_label}：左右页签高亮异常（左均值={left_mean:.1f}，右均值={right_mean:.1f}），怀疑处于危险页签，已拦截。",
        )
    return True, "ok"


def has_warehouse_left_coin_price(
    tab_ocr_entries: Sequence[Mapping[str, Any]],
) -> bool:
    """判定弹窗左侧铁盟币页签区是否识别到合法铁盟币价格数字（实机通常为 >= 1000 整数如 10000）。"""
    for entry in _safe_merge(tab_ocr_entries, max_gap_x=6, max_row_diff=12.0):
        text = _clean_text(entry.get("text"))
        if not text or "/" in text:
            continue
        center = _entry_center(entry)
        if center is not None and not (center[0] < 640 and 410 <= center[1] <= 485):
            continue
        cleaned = text.replace(",", "").replace("，", "")
        for tok in re.findall(r"\d+", cleaned):
            val = int(tok)
            if 1000 <= val <= 1_000_000:
                return True
        if "剩余" not in text and any(unit in cleaned for unit in ("k", "K", "w", "W", "万")):
            parsed = parse_cn_number(cleaned)
            if parsed is not None and 1000 <= parsed <= 10_000_000:
                return True
            for abbr_tok in re.findall(r"\d+(?:\.\d+)?\s*[kKwW万]", cleaned):
                abbr_val = parse_cn_number(abbr_tok)
                if abbr_val is not None and 1000 <= abbr_val <= 10_000_000:
                    return True
    return False


def verify_warehouse_coins_tab_safe(
    image: Any,
    tab_ocr_entries: Sequence[Mapping[str, Any]],
) -> tuple[bool, str]:
    """仓库扩容确认前硬护栏：左侧「铁盟币」必须高亮白底（>=215）且右侧「桦石」必须暗灰（<=85）。"""
    left_mean = sample_roi_mean_brightness(image, WAREHOUSE_MODAL_COIN_PATCH_ROI)
    right_mean = sample_roi_mean_brightness(image, WAREHOUSE_MODAL_HUASHI_PATCH_ROI)
    if left_mean is None or right_mean is None:
        return False, "仓库扩容护栏：截图无效，无法完成双重像素校验。"
    entries = [e for e in tab_ocr_entries if isinstance(e, Mapping)]
    joined_ocr = "".join(_clean_text(e.get("text")) for e in entries)
    for entry in entries:
        text = _clean_text(entry.get("text"))
        center = _entry_center(entry)
        if "桦石" in text and (center is None or center[0] < 640) and "铁盟币" not in joined_ocr:
            return False, f"仓库扩容护栏：左侧页签疑似出现「桦石」（当前：{joined_ocr}），已拦截。"
    if "铁盟币" not in joined_ocr and not has_warehouse_left_coin_price(entries):
        return False, f"仓库扩容护栏：OCR 未检测到「铁盟币」或左侧合法铁盟币价格（当前：{joined_ocr or '空'}）。"
    if left_mean < 215.0 or right_mean > 85.0:
        return (
            False,
            f"仓库扩容护栏：左右页签高亮异常（左均值={left_mean:.1f}，右均值={right_mean:.1f}），怀疑处于危险页签，已拦截。",
        )
    return True, "ok"


def verify_power_room_upgrade_tab_safe(
    image: Any,
    tab_ocr_entries: Sequence[Mapping[str, Any]],
) -> tuple[bool, str]:
    """电力中心建造确认前硬护栏：左侧「房间升级」必须高亮白底（>=215）且右侧「安装电机」必须暗灰（<=85）。"""
    return _verify_left_white_right_dark_tabs(
        image,
        tab_ocr_entries,
        left_roi=POWER_TAB_ROOM_UPGRADE_PATCH_ROI,
        right_roi=POWER_TAB_MOTOR_PATCH_ROI,
        required_left_keyword="房间升级",
        context_label="电力中心护栏",
    )


# ---------------- 子界面 OCR 解析器 ----------------


def is_orders_foyer_entries(entries: Sequence[Mapping[str, Any]]) -> bool:
    """判定是否位于黑月订单站门面页（需再点「运输订单」进入日单卡片页）。"""
    joined = "".join(_clean_text(e.get("text")) for e in entries if isinstance(e, Mapping))
    return (
        "运输订单" in joined
        and "需求物资" not in joined
        and "奖励物品" not in joined
    )


def parse_single_order_card(
    body_entries: Sequence[Mapping[str, Any]],
    btn_entries: Sequence[Mapping[str, Any]],
    *,
    order_type: str = "daily",
    catalog: Optional[dict[str, Any]] = None,
) -> Optional[dict[str, Any]]:
    """从黑月「运输订单」单卡视图解析货物名、需求数量、现有库存与可交付状态。"""
    resolved_type = "weekly" if order_type == "weekly" else "daily"
    merged_body = _merge_horizontal_adjacent(body_entries, max_gap_x=22, max_row_diff=14.0)
    known_names = _known_order_item_names(catalog)

    item_name = ""
    best_name_y = 10_000
    demand_qty: Optional[int] = None

    for entry in merged_body:
        text = _clean_text(entry.get("text"))
        if not text:
            continue
        center = _entry_center(entry)
        cx = center[0] if center else 550
        cy = center[1] if center else 220

        # 过滤右侧栏与底部奖励栏，避免误读右侧订单列表或底部奖励金币
        if cx > 1030 or cy > 340 or cy < 150:
            continue

        matched_known = next((name for name in known_names if name in text), None)
        if matched_known and cy < best_name_y:
            item_name = matched_known
            best_name_y = cy
        elif (
            not item_name
            and 450 <= cx <= 880
            and 155 <= cy <= 325
            and re.fullmatch(r"[\u4e00-\u9fff]{2,8}", text)
            and text not in ORDER_UI_STOPWORDS
            and not text.endswith("锁")
        ):
            item_name = text
            best_name_y = cy

        # 需求数量单独位于数量框 (x=660..1030, y=215..325)
        if 660 <= cx <= 1030 and 215 <= cy <= 325 and "/" not in text:
            cleaned_num = text.replace(",", "").replace("，", "")
            if re.fullmatch(r"\d{1,5}", cleaned_num):
                val = int(cleaned_num)
                if 10 <= val <= 5000:
                    demand_qty = val

    if not item_name or demand_qty is None:
        return None

    merged_btn = _merge_horizontal_adjacent(btn_entries, max_gap_x=20, max_row_diff=14.0)
    btn_parts: list[str] = []
    stock_owned = 0
    for entry in merged_btn:
        text = _clean_text(entry.get("text"))
        if not text:
            continue
        btn_parts.append(text)
        center = _entry_center(entry)
        cx = center[0] if center else 750
        if 600 <= cx <= 885 and "/" not in text:
            cleaned_stock = text.replace(",", "").replace("，", "")
            if re.fullmatch(r"\d{1,6}", cleaned_stock):
                stock_owned = int(cleaned_stock)
            else:
                parsed = parse_cn_number(cleaned_stock)
                if parsed is not None and any(ch.isdigit() for ch in cleaned_stock):
                    stock_owned = parsed

    btn_text = "".join(btn_parts)
    deliverable = ("交付" in btn_text) and ("不足" not in btn_text)
    return {
        "item_name": item_name,
        "quantity": int(demand_qty),
        "stock_owned": int(stock_owned),
        "deliverable": deliverable,
        "button_text": btn_text,
        "order_type": resolved_type,
    }


def is_exchange_shop_entries(entries: Sequence[Mapping[str, Any]]) -> bool:
    """判定当前界面是否为「整顿中心商店 / 研发中心」页面。"""
    joined = "".join(_clean_text(e.get("text")) for e in entries if isinstance(e, Mapping))
    return any(kw in joined for kw in ("研发配方", "兑换道具", "整顿中心商店"))


def _extract_pill_numeric(
    entries: Sequence[Mapping[str, Any]],
    *,
    min_num_cx: int,
) -> Optional[int]:
    cleaned = _filter_top_bar_icon_noise(entries)
    merged = _merge_horizontal_adjacent(cleaned, max_gap_x=10, max_row_diff=12.0)
    candidates: list[tuple[int, int, int]] = []
    for entry in merged:
        text = _clean_text(entry.get("text"))
        if not text or "/" in text:
            continue
        digits = re.sub(r"[^0-9kKmM.]", "", text)
        if not any(ch.isdigit() for ch in digits):
            continue
        center = _entry_center(entry)
        cx = center[0] if center else min_num_cx
        if center is not None and cx < min_num_cx:
            continue
        val = parse_cn_number(text)
        if val is not None:
            candidates.append((len(digits), cx, val))
    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return candidates[0][2]


def parse_exchange_shop_top_bar(
    ticket_entries: Sequence[Mapping[str, Any]],
    coin_entries: Sequence[Mapping[str, Any]],
) -> dict[str, int]:
    """从整顿中心商店右上角双胶囊读取精确工票与铁盟币数值。"""
    result: dict[str, int] = {}
    tickets = _extract_pill_numeric(ticket_entries, min_num_cx=920)
    if tickets is not None:
        result["work_tickets"] = tickets
    coins = _extract_pill_numeric(coin_entries, min_num_cx=1125)
    if coins is not None:
        result["coins"] = coins
    return result


def parse_exchange_shop_recipe_rows(
    body_entries: Sequence[Mapping[str, Any]],
    *,
    catalog: Optional[dict[str, Any]] = None,
) -> list[dict[str, Any]]:
    """解析整顿中心商店「研发配方」前 4 行商品名称、锁定状态、余量与花费。"""
    strategy = catalog if isinstance(catalog, dict) else load_prison_strategy_catalog()
    rush_names = sorted(
        (
            str(item.get("name") or "").strip()
            for item in (strategy.get("rush_leveling_goods") or ())
            if isinstance(item, Mapping) and str(item.get("name") or "").strip()
        ),
        key=len,
        reverse=True,
    )
    row_bands = ((145, 275), (276, 405), (406, 535), (536, 668))
    # 使用紧邻间隔避免把相邻材料格（如 31.8m/180k 与 7.7k/1.8k）误合并
    merged = _safe_merge(body_entries, max_gap_x=6, max_row_diff=12.0)

    buckets: list[list[dict[str, Any]]] = [[] for _ in row_bands]
    for entry in merged:
        center = _entry_center(entry)
        if center is None:
            continue
        cy = center[1]
        for idx, (y1, y2) in enumerate(row_bands):
            if y1 <= cy <= y2:
                buckets[idx].append(entry)
                break

    rows: list[dict[str, Any]] = []
    for idx, bucket in enumerate(buckets):
        if not bucket:
            continue
        joined = "".join(_clean_text(e.get("text")) for e in bucket)
        upper = joined.upper()

        recipe_name = ""
        for entry in bucket:
            t = _clean_text(entry.get("text"))
            if any(sfx in t for sfx in ("缝制法", "粘制法", "织造法", "剪裁法", "取制法", "制造法", "缝制指南")):
                recipe_name = t
                break
        if not recipe_name:
            continue

        base_good = next((g for g in rush_names if g in recipe_name), "")
        locked = ("LEVEL" in upper) or ("等级" in joined) or ("已售罄" in joined)
        rem_match = re.search(r"剩余\s*(\d+)\s*次", joined)
        remaining = int(rem_match.group(1)) if rem_match else (0 if "已售罄" in joined else 1)

        coin_cost = 0
        ticket_cost = 0
        for entry in bucket:
            t = _clean_text(entry.get("text"))
            if "/" not in t:
                continue
            center = _entry_center(entry)
            cx = center[0] if center else 750
            for _owned_raw, cost_raw in re.findall(
                r"([0-9]+(?:\.[0-9]+)?[kKmMwW万亿]?)\s*/\s*([0-9]+(?:\.[0-9]+)?[kKmMwW万亿]?)",
                t,
            ):
                cost_val = parse_cn_number(cost_raw)
                if cost_val is None or cost_val <= 0:
                    continue
                if cx < 785 and coin_cost == 0:
                    coin_cost = cost_val
                elif 785 <= cx < 880 and ticket_cost == 0:
                    ticket_cost = cost_val
                elif coin_cost == 0 and cost_val >= 20_000:
                    coin_cost = cost_val
                elif ticket_cost == 0:
                    ticket_cost = cost_val

        y1, _y2 = row_bands[idx]
        exchange_point = (1152, y1 + 56)
        for entry in bucket:
            if "EXCHANGE" in _clean_text(entry.get("text")).upper():
                center = _entry_center(entry)
                if center is not None:
                    exchange_point = center
                    break
        rows.append(
            {
                "row_index": idx,
                "recipe_name": recipe_name,
                "base_good_name": base_good,
                "locked": locked,
                "remaining": remaining,
                "coin_cost": coin_cost,
                "ticket_cost": ticket_cost,
                "exchange_point": exchange_point,
            }
        )
    return rows


def find_room_bubble_point(
    bubble_entries: Sequence[Mapping[str, Any]],
    keyword: str,
    fallback: tuple[int, int],
) -> Optional[tuple[int, int]]:
    """在聚焦房间右侧黄色气泡区查找指定按钮（「建设」「生产」「详情」），未见则不盲点。"""
    target_kw = _clean_text(keyword)
    if not target_kw:
        return None
    merged = _safe_merge(bubble_entries, max_gap_x=14, max_row_diff=12.0)
    for entry in merged:
        text = _clean_text(entry.get("text"))
        if target_kw in text:
            return _entry_center(entry) or fallback
    return None


def parse_room_build_panel(
    panel_entries: Sequence[Mapping[str, Any]],
    btn_entries: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """解析房间建造面板（建造按钮可行性、所需铁盟币与所需工票）。"""
    merged_panel = _safe_merge(panel_entries, max_gap_x=6, max_row_diff=12.0)
    merged_btn = _safe_merge(btn_entries, max_gap_x=14, max_row_diff=12.0)

    btn_text = "".join(_clean_text(e.get("text")) for e in merged_btn)
    panel_text = "".join(_clean_text(e.get("text")) for e in merged_panel)
    can_build = (
        ("建造" in btn_text)
        and ("已升级" not in btn_text)
        and ("不足" not in btn_text)
        and ("等级不足" not in panel_text)
    )

    required_coins: Optional[int] = None
    required_tickets: int = 0
    for entry in merged_panel:
        text = _clean_text(entry.get("text"))
        if "/" not in text or "-/-" in text:
            continue
        center = _entry_center(entry)
        cx = center[0] if center else 820
        cy = center[1] if center else 520
        if not (430 <= cy <= 570):
            continue
        parsed_vals: list[int] = []
        for cost_raw, _owned_raw in re.findall(
            r"([0-9]+(?:\.[0-9]+)?[kKmMwW万亿]?)\s*/\s*([0-9]+(?:\.[0-9]+)?[kKmMwW万亿]?)",
            text,
        ):
            cost_val = parse_cn_number(cost_raw)
            if cost_val is not None and cost_val > 0:
                parsed_vals.append(cost_val)
        if len(parsed_vals) >= 2 and cx < 1010:
            if required_coins is None:
                required_coins = parsed_vals[0]
            if required_tickets == 0:
                required_tickets = parsed_vals[1]
        elif len(parsed_vals) == 1:
            cost_val = parsed_vals[0]
            if cx < 890 and required_coins is None:
                required_coins = cost_val
            elif 890 <= cx < 1010 and required_tickets == 0:
                required_tickets = cost_val

    return {
        "can_build": can_build,
        "required_coins": required_coins,
        "required_tickets": required_tickets,
        "status_text": btn_text or panel_text,
    }


def parse_warehouse_modal_remaining(
    tab_entries: Sequence[Mapping[str, Any]],
) -> Optional[int]:
    """仅解析仓库购买弹窗左侧「铁盟币」页签下方的剩余购买次数（x < 645）。"""
    merged = _safe_merge(tab_entries, max_gap_x=10, max_row_diff=12.0)
    for entry in merged:
        center = _entry_center(entry)
        if center is None or center[0] >= 645:
            continue
        text = _clean_text(entry.get("text"))
        match = re.search(r"剩余\s*(\d+)\s*次", text)
        if match:
            return int(match.group(1))
    return None


def parse_predeposit_balance(bal_entries: Sequence[Mapping[str, Any]]) -> Optional[int]:
    """解析原料车间生产页左下角「铁盟币存量」数值。"""
    merged = _safe_merge(bal_entries, max_gap_x=14, max_row_diff=12.0)
    for entry in merged:
        text = _clean_text(entry.get("text"))
        if not text or not any(ch.isdigit() for ch in text):
            continue
        val = parse_cn_number(text)
        if val is not None:
            return val
    return None


def parse_predeposit_modal_qty(
    qty_entries: Sequence[Mapping[str, Any]],
) -> Optional[tuple[int, int]]:
    """解析原料预存弹窗中的「当前选中 / 上限」分数（如 1 / 2500000）。"""
    merged = _safe_merge(qty_entries, max_gap_x=14, max_row_diff=12.0)
    for entry in merged:
        text = _clean_text(entry.get("text"))
        frac = _parse_fraction(text)
        if frac is not None and frac[1] > 0:
            return frac
    return None


def compute_predeposit_slider_x(target_coins: int, max_coins: int) -> int:
    """按比例计算预存铁盟币滑块在 1280x720 坐标中的目标 X 值。"""
    if max_coins <= 0 or target_coins <= 1:
        return RAW_PREDEPOSIT_SLIDER_X_MIN
    ratio = max(0.0, min(1.0, float(target_coins) / float(max_coins)))
    span = RAW_PREDEPOSIT_SLIDER_X_MAX - RAW_PREDEPOSIT_SLIDER_X_MIN
    return int(round(RAW_PREDEPOSIT_SLIDER_X_MIN + ratio * span))


def find_production_select_all_point(
    entries: Sequence[Mapping[str, Any]],
) -> tuple[Optional[tuple[int, int]], str]:
    """动态识别生产面板右上方「一键全选」或「一键取消」按钮位置（兼容选配方后抽屉上移）。"""
    merged = _safe_merge(entries, max_gap_x=12, max_row_diff=12.0)
    for entry in merged:
        text = _clean_text(entry.get("text"))
        if "一键取消" in text:
            return _entry_center(entry) or (1183, 496), "cancel_all"
        if "一键全选" in text:
            return _entry_center(entry) or (1183, 559), "select_all"
    return None, "none"


def find_all_production_recipe_card_points(
    card_entries: Sequence[Mapping[str, Any]],
    preferred_targets: Sequence[str],
    *,
    exclude_targets: Sequence[str] = (),
    catalog: Optional[dict[str, Any]] = None,
) -> list[tuple[str, tuple[int, int]]]:
    """按优先级返回当前页全部已解锁且匹配白名单的配方卡片坐标列表（跳过「获取途径」锁卡）。"""
    merged = _safe_merge(card_entries, max_gap_x=10, max_row_diff=12.0)
    locked_xs: list[int] = []
    text_cards: list[tuple[str, int, int]] = []

    for entry in merged:
        text = _clean_text(entry.get("text"))
        center = _entry_center(entry)
        if not text or center is None:
            continue
        cx, cy = center
        if "获取途径" in text:
            locked_xs.append(cx)
            continue
        if len(text) >= 2:
            text_cards.append((text, cx, cy))

    unlocked_cards = [
        (text, cx, cy)
        for text, cx, cy in text_cards
        if not any(abs(cx - lx) <= 85 for lx in locked_xs)
    ]

    excluded = {_clean_text(t) for t in exclude_targets if _clean_text(t)}
    ordered_targets: list[str] = []
    seen_targets: set[str] = set()
    for t in preferred_targets:
        ct = _clean_text(t)
        if ct and ct not in excluded and ct not in seen_targets:
            seen_targets.add(ct)
            ordered_targets.append(ct)

    strategy = catalog if isinstance(catalog, dict) else load_prison_strategy_catalog()
    rush_items = [
        item
        for item in (strategy.get("rush_leveling_goods") or ())
        if isinstance(item, Mapping) and bool(item.get("daily_recommended", True))
    ]
    rush_items.sort(
        key=lambda g: (
            1 if bool(g.get("defer_until_surplus", False)) else 0,
            -int(g.get("rating") if g.get("rating") is not None else 1),
            int(g.get("guide_index") or 99),
        )
    )
    for item in rush_items:
        ct = _clean_text(item.get("name"))
        if ct and ct not in excluded and ct not in seen_targets:
            seen_targets.add(ct)
            ordered_targets.append(ct)
    for item in strategy.get("profit_harvest_goods") or ():
        if not isinstance(item, Mapping):
            continue
        ct = _clean_text(item.get("name"))
        if ct and ct not in excluded and ct not in seen_targets:
            seen_targets.add(ct)
            ordered_targets.append(ct)

    results: list[tuple[str, tuple[int, int]]] = []
    used_cards: set[int] = set()
    for target in ordered_targets:
        for card_idx, (card_text, cx, cy) in enumerate(unlocked_cards):
            if card_idx in used_cards:
                continue
            if target in card_text:
                used_cards.add(card_idx)
                results.append((target, (cx, min(650, max(595, cy - 25)))))
                break
    return results


def find_production_recipe_card_point(
    card_entries: Sequence[Mapping[str, Any]],
    preferred_targets: Sequence[str],
) -> Optional[tuple[str, tuple[int, int]]]:
    """在底部配方栏优先选中已解锁且匹配推荐清单的配方卡片，忽略含「获取途径」锁的卡片。"""
    all_pts = find_all_production_recipe_card_points(card_entries, preferred_targets)
    pref_set = {_clean_text(t) for t in preferred_targets if _clean_text(t)}
    for name, pt in all_pts:
        if name in pref_set:
            return name, pt
    return None


def parse_production_ready_panel(
    panel_entries: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """解析选定配方与囚犯后右下角面板的原料充足度与「确定」状态。"""
    merged = _safe_merge(panel_entries, max_gap_x=10, max_row_diff=12.0)
    joined = "".join(_clean_text(e.get("text")) for e in merged)
    has_confirm = ("确定" in joined) and ("请先选择生产人员和配方" not in joined)

    ratios: list[tuple[int, int]] = []
    for entry in merged:
        text = _clean_text(entry.get("text"))
        if "/" not in text or "-/-" in text:
            continue
        center = _entry_center(entry)
        if center is not None:
            cx, cy = center
            if not (545 <= cy <= 650 and cx <= 1065):
                continue
        frac = _parse_fraction(text)
        if frac is not None and frac[1] > 0:
            ratios.append(frac)

    materials_sufficient = bool(ratios) and all(owned >= req and req > 0 for owned, req in ratios)
    return {
        "has_confirm": has_confirm,
        "materials_sufficient": materials_sufficient,
        "material_ratios": ratios,
    }


def find_modal_confirm_button_point(
    entries: Sequence[Mapping[str, Any]],
) -> Optional[tuple[int, int]]:
    """在全宽确认弹窗底部按钮带查找「确定 / 确认 / 兑换」按钮，避开中部提示句。"""
    for entry in _safe_merge(entries, max_gap_x=10, max_row_diff=12.0):
        text = _clean_text(entry.get("text"))
        if not text or len(text) > 4:
            continue
        center = _entry_center(entry)
        if center is None or center[1] < 480:
            continue
        if text in ("确定", "确认", "兑换"):
            return center
    return None


def find_todo_claim_button_points(
    entries: Sequence[Mapping[str, Any]],
) -> list[tuple[int, int]]:
    """按从上到下顺序返回「事项一览」右侧可点击的「领取」按钮坐标列表。"""
    pts: list[tuple[int, int]] = []
    for entry in _safe_merge(entries, max_gap_x=10, max_row_diff=12.0):
        text = _clean_text(entry.get("text"))
        if not text or "已领取" in text or "领取" not in text:
            continue
        center = _entry_center(entry)
        if center is not None:
            pts.append(center)
    pts.sort(key=lambda pt: pt[1])
    return pts


def parse_prisoner_checkin_counts(
    entries: Sequence[Mapping[str, Any]],
) -> tuple[Optional[int], Optional[int], Optional[int]]:
    """解析「办理入住」页底栏的待办理与整顿中囚犯人数：(waiting_current, active_current, active_capacity)。"""
    merged = _safe_merge(entries, max_gap_x=18, max_row_diff=14.0)
    joined = " ".join(_clean_text(e.get("text")) for e in merged if _clean_text(e.get("text")))

    waiting: Optional[int] = None
    active_cur: Optional[int] = None
    active_cap: Optional[int] = None

    m_wait = re.search(r"未整顿囚犯数量[^0-9]*([0-9]+)\s*/\s*([0-9]+)", joined)
    if m_wait:
        waiting = int(m_wait.group(1))
    elif "暂无囚犯" in joined:
        waiting = 0

    m_active = re.search(r"整顿中囚犯数量[^0-9]*([0-9]+)\s*/\s*([0-9]+)", joined)
    if m_active:
        active_cur = int(m_active.group(1))
        active_cap = int(m_active.group(2))

    return waiting, active_cur, active_cap


def detect_finance_auto_refill_state(image: Any) -> Optional[bool]:
    """用通道无关像素亮度判断财务中心「保证金低于80%自动补满」开关状态（True=已开，False=关闭，None=无法确认）。"""
    left_mean = sample_roi_mean_brightness(image, FINANCE_TOGGLE_LEFT_ROI)
    mid_mean = sample_roi_mean_brightness(image, FINANCE_TOGGLE_MID_ROI)
    if left_mean is None or mid_mean is None:
        return None
    if mid_mean >= 100.0 and left_mean >= 90.0:
        return True
    if mid_mean <= 70.0 and (left_mean - mid_mean) >= 45.0:
        return False
    return None


def parse_exchange_shop_item_rows(
    body_entries: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """严格白名单解析「兑换道具」页可安全兑换的一次性项（仅拉普拉斯协议/自观测胶卷，硬屏蔽桦石与再生项）。"""
    whitelist = ("拉普拉斯协议", "自观测胶卷")
    blocked_keywords = ("桦石", "逮捕令", "帮帮券", "囚服", "LEVEL", "等级", "解锁", "已售罄", "已兑换完")
    row_bands = ((132, 275), (276, 405), (406, 535), (536, 668))
    merged = _safe_merge(body_entries, max_gap_x=6, max_row_diff=12.0)

    buckets: list[list[dict[str, Any]]] = [[] for _ in row_bands]
    for entry in merged:
        center = _entry_center(entry)
        if center is None:
            continue
        cy = center[1]
        for idx, (y1, y2) in enumerate(row_bands):
            if y1 <= cy <= y2:
                buckets[idx].append(entry)
                break

    rows: list[dict[str, Any]] = []
    for idx, bucket in enumerate(buckets):
        if not bucket:
            continue
        joined = "".join(_clean_text(e.get("text")) for e in bucket)
        upper = joined.upper()
        if any(bad in joined or bad in upper for bad in blocked_keywords):
            continue

        item_name = next((name for name in whitelist if name in joined), "")
        if not item_name:
            continue

        rem_match = re.search(r"剩余\s*(\d+)\s*次", joined)
        remaining = int(rem_match.group(1)) if rem_match else 1
        if remaining <= 0:
            continue

        ticket_cost = 0
        for entry in bucket:
            t = _clean_text(entry.get("text"))
            if "/" not in t:
                continue
            center = _entry_center(entry)
            cx = center[0] if center else 760
            if cx >= 920:
                continue
            for _owned_raw, cost_raw in re.findall(
                r"([0-9]+(?:\.[0-9]+)?[kKmMwW万亿]?)\s*/\s*([0-9]+(?:\.[0-9]+)?[kKmMwW万亿]?)",
                t,
            ):
                cost_val = parse_cn_number(cost_raw)
                if cost_val is not None and cost_val > 0:
                    ticket_cost = cost_val
                    break
            if ticket_cost > 0:
                break

        if ticket_cost <= 0:
            continue

        y1, _y2 = row_bands[idx]
        exchange_point = (1152, max(195, y1 + 56))
        for entry in bucket:
            t = _clean_text(entry.get("text")).upper()
            center = _entry_center(entry)
            if "EXCHANGE" in t and center is not None and center[0] >= 1040:
                exchange_point = center
                break

        rows.append(
            {
                "row_index": idx,
                "item_name": item_name,
                "remaining": remaining,
                "ticket_cost": ticket_cost,
                "exchange_point": exchange_point,
            }
        )
    return rows


def parse_raw_workshop_prod_status(
    action_entries: Sequence[Mapping[str, Any]],
    workers_entries: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """解析原料车间生产页当前是否已在运行、可否点击「开始生产」及已上工人数。"""
    action_text = "".join(_clean_text(e.get("text")) for e in _safe_merge(action_entries, max_gap_x=10, max_row_diff=12.0))
    workers_text = "".join(_clean_text(e.get("text")) for e in _safe_merge(workers_entries, max_gap_x=12, max_row_diff=12.0))

    running = ("终止" in action_text) or ("加速" in action_text)
    can_start = ("开始生产" in action_text) and not running

    assigned = 0
    capacity = 6
    m = re.search(r"(\d+)\s*/\s*(\d+)", workers_text)
    if m:
        assigned = int(m.group(1))
        capacity = max(1, int(m.group(2)))

    return {
        "running": running,
        "can_start": can_start,
        "assigned": assigned,
        "capacity": capacity,
    }


def plan_prisoner_worker_allocation(
    total_prisoners: int,
    built_raw_count: int,
    raw_warehouse_used: int,
    prod_ws_count: int = 2,
    *,
    mode: str = "balanced",
) -> dict[str, int]:
    """根据在监囚犯总数、已建原料车间数、原料仓余量及分配策略规划原料车间配员。"""
    total = max(0, int(total_prisoners))
    raw_cnt = max(0, int(built_raw_count))
    raw_used = max(0, int(raw_warehouse_used))
    _ = prod_ws_count
    norm_mode = str(mode or "balanced").strip().lower()

    if norm_mode == "predeposit_only":
        return {"raw_per_room": 0, "prod_reserve": total}
    if total <= 0 or raw_cnt <= 0:
        return {"raw_per_room": 0, "prod_reserve": total}
    if norm_mode == "raw_priority":
        raw_per_room = min(6, total // raw_cnt)
        if raw_per_room <= 0 and total >= raw_cnt:
            raw_per_room = 1
        return {
            "raw_per_room": raw_per_room,
            "prod_reserve": max(0, total - raw_per_room * raw_cnt),
        }
    if total >= raw_cnt * 6 + 6:
        return {"raw_per_room": 6, "prod_reserve": total - raw_cnt * 6}

    if raw_used < 60:
        prod_reserve = min(3, max(0, total - raw_cnt))
    else:
        prod_reserve = min(6, max(1, total // 2))

    raw_budget = max(0, total - prod_reserve)
    raw_per_room = min(6, raw_budget // raw_cnt)
    if raw_per_room <= 0 and total >= raw_cnt:
        raw_per_room = 1
        prod_reserve = total - raw_cnt
    return {
        "raw_per_room": raw_per_room,
        "prod_reserve": max(0, total - raw_per_room * raw_cnt),
    }


_ASSIGNED_ROOM_BADGE_RE = re.compile(r"[仓合舍金室车厂]\s*[1-6](?!\d)")


def find_idle_prisoner_card_points(
    grid_entries: Sequence[Mapping[str, Any]],
    *,
    max_pick: int = 6,
) -> list[tuple[int, int]]:
    """从「选择囚犯 / 快速编队」2×6 网格中挑选未忙碌且未选中的囚犯卡片中心坐标。"""
    if max_pick <= 0:
        return []
    badged_slots: set[tuple[int, int]] = set()
    for entry in grid_entries:
        if not isinstance(entry, Mapping):
            continue
        raw_text = _clean_text(entry.get("text"))
        box = _entry_box(entry)
        if not raw_text or box is None:
            continue
        x, y, w, h = box
        cx = x + w / 2.0
        cy = y + h / 2.0
        if cy < 80.0 or cy > 535.0 or cx < 20.0 or cx > 1265.0:
            continue
        row = 0 if cy < 305.0 else 1
        col = min(5, max(0, int((cx - 20.0) // 208.0)))
        dx = cx - (20.0 + col * 208.0)
        # 卡片右下角所属房间角标区域（如 合1/金2 或被误识成单字符 '8'）
        if w <= 56.0 and 148.0 <= dx <= 195.0 and (
            (row == 0 and 226.0 <= cy <= 250.0) or (row == 1 and 450.0 <= cy <= 474.0)
        ):
            badged_slots.add((row, col))

    merged = _safe_merge(grid_entries, max_gap_x=10, max_row_diff=12.0)
    slot_texts: dict[tuple[int, int], list[str]] = {}

    for entry in merged:
        text = _clean_text(entry.get("text"))
        center = _entry_center(entry)
        if not text or center is None:
            continue
        cx, cy = center
        if cy < 80 or cy > 535 or cx < 20 or cx > 1265:
            continue
        row = 0 if cy < 305 else 1
        col = min(5, max(0, int((cx - 20) // 208)))
        slot_texts.setdefault((row, col), []).append(text)

    populated_hints = ("刑期", "%", "剪裁", "织造", "主管", "经理", "包工头", "0000")
    busy_or_selected_hints = ("生产中", "产中", "忙碌", "工作中", "选中", "号工位", "工位", "车间", "原料")

    picked: list[tuple[int, int]] = []
    for row in (0, 1):
        for col in range(6):
            if (row, col) in badged_slots:
                continue
            joined = "".join(slot_texts.get((row, col), ()))
            if not joined:
                continue
            if any(bad in joined for bad in busy_or_selected_hints):
                continue
            if _ASSIGNED_ROOM_BADGE_RE.search(joined) is not None:
                continue
            if not any(ok in joined for ok in populated_hints):
                continue
            picked.append(RAW_PROD_PICKER_CARD_CENTERS[row * 6 + col])
            if len(picked) >= max_pick:
                return picked
    return picked


def parse_workshop_machine_upgrade_cost(
    cost_entries: Sequence[Mapping[str, Any]],
    btn_entries: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """解析车间编辑「机器升级」按钮可行性与右侧双栏消费（UI 为 owned/required，取后者）。"""
    merged_cost = _safe_merge(cost_entries, max_gap_x=6, max_row_diff=12.0)
    merged_btn = _safe_merge(btn_entries, max_gap_x=12, max_row_diff=12.0)

    btn_text = "".join(_clean_text(e.get("text")) for e in merged_btn)
    cost_text = "".join(_clean_text(e.get("text")) for e in merged_cost)
    combined = btn_text + cost_text

    huashi_blocked = ("桦石" in combined)
    can_upgrade = (
        ("机器升级" in btn_text)
        and (not huashi_blocked)
        and (not any(kw in combined for kw in ("满级", "不足", "锁定", "已升级")))
    )

    required_coins: Optional[int] = None
    required_tickets: int = 0
    for entry in merged_cost:
        text = _clean_text(entry.get("text"))
        if "/" not in text or "-/-" in text:
            continue
        center = _entry_center(entry)
        cx = center[0] if center else 1000
        parsed_vals: list[int] = []
        for _owned_raw, req_raw in re.findall(
            r"([0-9]+(?:\.[0-9]+)?[kKmMwW万亿]?)\s*/\s*([0-9]+(?:\.[0-9]+)?[kKmMwW万亿]?)",
            text,
        ):
            val = parse_cn_number(req_raw)
            if val is not None and val > 0:
                parsed_vals.append(val)
        if len(parsed_vals) >= 2:
            if required_coins is None:
                required_coins = parsed_vals[0]
            if required_tickets == 0:
                required_tickets = parsed_vals[1]
        elif len(parsed_vals) == 1:
            if cx < 1038 and required_coins is None:
                required_coins = parsed_vals[0]
            elif cx >= 1038 and required_tickets == 0:
                required_tickets = parsed_vals[0]

    return {
        "can_upgrade": can_upgrade,
        "required_coins": required_coins,
        "required_tickets": required_tickets,
        "huashi_blocked": huashi_blocked,
        "status_text": btn_text or cost_text,
    }


def has_unset_workshop_leader(top_entries: Sequence[Mapping[str, Any]]) -> bool:
    """判定生产车间顶栏「车间组长」是否仍显示「未设置」。"""
    joined = "".join(_clean_text(e.get("text")) for e in _safe_merge(top_entries, max_gap_x=10, max_row_diff=12.0))
    return "未设置" in joined


def has_workshop_leader_set(top_entries: Sequence[Mapping[str, Any]]) -> bool:
    """判定生产车间顶栏「车间组长」是否已设置有效组长（非「未设置」且含组长名称，避免漏识第二行时误判）。"""
    joined = "".join(_clean_text(e.get("text")) for e in _safe_merge(top_entries, max_gap_x=10, max_row_diff=12.0))
    if "组长" not in joined or "未设置" in joined:
        return False
    remainder = re.sub(r"[\s:：·\-_]+", "", joined.replace("车间组长", "").replace("组长", ""))
    return bool(remainder) and remainder not in {"无", "空", "未"}
