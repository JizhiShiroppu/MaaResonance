"""海岛（蜃息岛）页面识别、OCR/像素解析、硬护栏校验与红叹号野怪检测（720p 逻辑坐标基准）。"""
from __future__ import annotations

import re
from typing import Any, Mapping, Sequence

import numpy as np

# ==============================================================================
# 1280x720 逻辑分辨率实机标定 ROI 与关键坐标（2026-11-24 MuMu 1920x1080 ÷ 1.5）
# ==============================================================================

ISLAND_BANNER_ENTRY_ROI: tuple[int, int, int, int] = (840, 520, 260, 160)
ISLAND_BANNER_ENTRY_POINT: tuple[int, int] = (987, 607)

ISLAND_TOP_BAR_ROI: tuple[int, int, int, int] = (770, 20, 500, 120)
ISLAND_TICKETS_ROI: tuple[int, int, int, int] = (848, 58, 115, 34)
ISLAND_SHELLS_ROI: tuple[int, int, int, int] = (1020, 55, 140, 40)
ISLAND_BOTTOM_DOCK_ROI: tuple[int, int, int, int] = (590, 580, 680, 120)
ISLAND_LEFT_HUD_ROI: tuple[int, int, int, int] = (10, 600, 250, 110)
ISLAND_COUNTS_HUD_ROI: tuple[int, int, int, int] = (265, 605, 220, 100)

ISLAND_BACK_POINT: tuple[int, int] = (77, 39)
ISLAND_LOBBY_POINT: tuple[int, int] = (195, 39)
ISLAND_SKY_DISMISS_POINT: tuple[int, int] = (640, 140)
ISLAND_REVENUE_BUBBLE_POINT: tuple[int, int] = (183, 533)
ISLAND_REPORT_BTN_POINT: tuple[int, int] = (1210, 64)
ISLAND_TODO_BTN_POINT: tuple[int, int] = (1183, 152)
ISLAND_FRIENDS_BTN_POINT: tuple[int, int] = (28, 360)
ISLAND_BROOM_BTN_POINT: tuple[int, int] = (417, 637)
ISLAND_RACCOON_BTN_POINT: tuple[int, int] = (357, 637)

# 海岛经营报表（总览弹窗）
ISLAND_REPORT_MODAL_ROI: tuple[int, int, int, int] = (140, 105, 1000, 515)
ISLAND_REPORT_LEFT_ROI: tuple[int, int, int, int] = (170, 360, 330, 230)
ISLAND_REPORT_SCORES_ROI: tuple[int, int, int, int] = (615, 210, 495, 115)
ISLAND_REPORT_BASIC_ROI: tuple[int, int, int, int] = (505, 350, 600, 225)
ISLAND_REPORT_CLOSE_POINT: tuple[int, int] = (640, 680)

ISLAND_OPS_COINS_ROI: tuple[int, int, int, int] = (1070, 10, 200, 50)
ISLAND_OPS_TABS_ROI: tuple[int, int, int, int] = (590, 65, 670, 75)
ISLAND_OPS_OVERVIEW_TAB_POINT: tuple[int, int] = (767, 103)
ISLAND_OPS_INVEST_TAB_POINT: tuple[int, int] = (1093, 103)
ISLAND_OPS_STAY_DAYS_ROI: tuple[int, int, int, int] = (1160, 145, 95, 65)
ISLAND_OPS_METRICS_ROI: tuple[int, int, int, int] = (600, 210, 660, 190)
ISLAND_OPS_FOOTER_ROI: tuple[int, int, int, int] = (600, 610, 660, 95)
ISLAND_OPS_COLLECT_POINT: tuple[int, int] = (1167, 647)

ISLAND_INVEST_REMAINING_ROI: tuple[int, int, int, int] = (1040, 148, 220, 45)
ISLAND_INVEST_SUMMARY_ROI: tuple[int, int, int, int] = (610, 190, 650, 80)
ISLAND_INVEST_CARDS_ROI: tuple[int, int, int, int] = (610, 280, 650, 390)
ISLAND_INVEST_CONFIRM_MODAL_ROI: tuple[int, int, int, int] = (350, 160, 580, 420)

# 海岛扩建弹窗
ISLAND_EXPAND_BTN_POINT: tuple[int, int] = (1023, 662)
ISLAND_EXPAND_MODAL_ROI: tuple[int, int, int, int] = (350, 120, 580, 360)
ISLAND_EXPAND_BUTTONS_ROI: tuple[int, int, int, int] = (10, 500, 1260, 100)
ISLAND_EXPAND_CANCEL_FALLBACK: tuple[int, int] = (320, 545)

# 海岛兑换处（只读扫描）
ISLAND_EXCHANGE_BTN_POINT: tuple[int, int] = (1080, 64)
ISLAND_EXCHANGE_CURRENCIES_ROI: tuple[int, int, int, int] = (650, 10, 620, 55)
ISLAND_EXCHANGE_HEADER_ROI: tuple[int, int, int, int] = (750, 75, 350, 65)
ISLAND_EXCHANGE_LIST_ROI: tuple[int, int, int, int] = (580, 145, 680, 560)

# 海岛垃圾产出总览
ISLAND_TRASH_HEADER_ROI: tuple[int, int, int, int] = (500, 0, 760, 150)
ISLAND_TRASH_PENDING_ROI: tuple[int, int, int, int] = (480, 140, 460, 60)
ISLAND_TRASH_MACHINE_ROI: tuple[int, int, int, int] = (40, 575, 420, 95)
ISLAND_TRASH_STORAGE_ROI: tuple[int, int, int, int] = (920, 165, 340, 55)
ISLAND_TRASH_ACTIONS_ROI: tuple[int, int, int, int] = (930, 605, 330, 80)
ISLAND_TRASH_COLLECT_FALLBACK: tuple[int, int] = (1160, 643)

# 事项一览 & 卡包奖励弹窗
ISLAND_TODO_LEVEL_ROI: tuple[int, int, int, int] = (50, 635, 330, 65)
ISLAND_TODO_TITLES_ROI: tuple[int, int, int, int] = (670, 40, 450, 650)
ISLAND_TODO_BUTTONS_ROI: tuple[int, int, int, int] = (1115, 40, 155, 670)
ISLAND_TODO_HEADER_ROI: tuple[int, int, int, int] = (500, 10, 760, 130)
ISLAND_CARD_PACK_PROMPT_ROI: tuple[int, int, int, int] = (480, 100, 320, 75)
ISLAND_CARD_PACK_SWIPE_START: tuple[int, int] = (500, 182)
ISLAND_CARD_PACK_SWIPE_END: tuple[int, int] = (800, 182)

# 好友抽屉 & 好友海岛
ISLAND_FRIENDS_HEADER_ROI: tuple[int, int, int, int] = (120, 50, 520, 135)
ISLAND_FRIENDS_CLEAN_TAB_POINT: tuple[int, int] = (310, 148)
ISLAND_FRIENDS_SECURITY_TAB_POINT: tuple[int, int] = (407, 148)
ISLAND_FRIENDS_LIST_ROI: tuple[int, int, int, int] = (155, 185, 470, 515)
ISLAND_FRIENDS_CLOSE_POINT: tuple[int, int] = (1000, 330)
ISLAND_FRIENDS_FIRST_VISIT_FALLBACK: tuple[int, int] = (507, 237)

FRIEND_ISLAND_DASHBOARD_ROI: tuple[int, int, int, int] = (790, 35, 450, 110)
FRIEND_ISLAND_BOTTOM_ROI: tuple[int, int, int, int] = (560, 595, 700, 100)
FRIEND_ISLAND_INFO_ROI: tuple[int, int, int, int] = (10, 570, 260, 130)
FRIEND_ISLAND_COUNTS_ROI: tuple[int, int, int, int] = (265, 600, 150, 95)
FRIEND_ISLAND_CLEAN_POINT: tuple[int, int] = (740, 640)
FRIEND_ISLAND_LIKE_POINT: tuple[int, int] = (860, 640)
FRIEND_ISLAND_NEXT_POINT: tuple[int, int] = (1153, 640)
FRIEND_ISLAND_RACCOON_POINT: tuple[int, int] = (302, 654)

# 0 体力编队核验
ISLAND_FORMATION_BTN_ROI: tuple[int, int, int, int] = (1080, 240, 190, 260)
ISLAND_FORMATION_COST_ROI: tuple[int, int, int, int] = (1120, 380, 130, 90)
ISLAND_FORMATION_START_POINT: tuple[int, int] = (1188, 360)

# 红叹号野怪排除区域（顶栏、左边好友标签、右上管理中心/事项一览、沙滩排球气泡、左下HUD、底栏5按钮）
ISLAND_MONSTER_EXCLUDED_ZONES: tuple[tuple[int, int, int, int], ...] = (
    (0, 0, 1280, 95),
    (0, 180, 80, 480),
    (220, 105, 150, 150),
    (835, 95, 210, 175),
    (1100, 95, 180, 130),
    (0, 470, 495, 250),
    (580, 565, 700, 155),
)

_NUMBER_RE = re.compile(r"(\d+(?:\.\d+)?)\s*([kKmMwW万亿]?)")
_RATIO_RE = re.compile(r"(\d+)\s*/\s*(\d+)")
_RATE_RE = re.compile(r"(\d+)\s*/\s*[hH小时]")
_LV_RE = re.compile(r"L[Vv]\.?\s*(\d+)")
_PCT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*%")


def _clean_text(text: Any) -> str:
    return re.sub(r"\s+", "", str(text or "")).strip()


def _entry_box(entry: Mapping[str, Any]) -> tuple[int, int, int, int] | None:
    box = entry.get("box")
    if isinstance(box, (list, tuple)) and len(box) >= 4:
        try:
            return int(box[0]), int(box[1]), int(box[2]), int(box[3])
        except (TypeError, ValueError):
            return None
    if all(k in entry for k in ("x", "y", "w", "h")):
        try:
            return int(entry["x"]), int(entry["y"]), int(entry["w"]), int(entry["h"])
        except (TypeError, ValueError):
            return None
    return None


def _entry_center(entry: Mapping[str, Any]) -> tuple[int, int] | None:
    if "center_x" in entry and "center_y" in entry:
        try:
            return int(round(float(entry["center_x"]))), int(round(float(entry["center_y"])))
        except (TypeError, ValueError):
            pass
    box = _entry_box(entry)
    if box is None:
        return None
    x, y, w, h = box
    return int(round(x + w / 2.0)), int(round(y + h / 2.0))


def _entry_score(entry: Mapping[str, Any]) -> float:
    raw_score = entry.get("score")
    if raw_score is None:
        return 1.0
    try:
        return float(raw_score)
    except (TypeError, ValueError):
        return 1.0


def parse_compact_number(raw: Any, default: int = 0) -> int:
    """解析 1,234 / 46M / 70.1k / 2k / 140万 等紧凑数字。"""
    cleaned = _clean_text(raw).replace(",", "")
    if not cleaned:
        return default
    m = _NUMBER_RE.search(cleaned)
    if not m:
        return default
    val = float(m.group(1))
    unit = m.group(2).lower()
    if unit == "k":
        val *= 1_000
    elif unit == "m":
        val *= 1_000_000
    elif unit in ("w", "万"):
        val *= 10_000
    elif unit == "亿":
        val *= 100_000_000
    return int(round(val))


def _texts(entries: Sequence[Mapping[str, Any]]) -> list[str]:
    return [_clean_text(e.get("text")) for e in entries if isinstance(e, Mapping) and _clean_text(e.get("text"))]


def _joined(entries: Sequence[Mapping[str, Any]]) -> str:
    return " ".join(_texts(entries))


# ==============================================================================
# 页面判别器
# ==============================================================================


def is_island_banner_entries(entries: Sequence[Mapping[str, Any]]) -> bool:
    joined = _joined(entries)
    return "海岛入口" in joined or ("开拓" in joined and "海岛" in joined)


def is_island_main_entries(
    top_entries: Sequence[Mapping[str, Any]],
    dock_entries: Sequence[Mapping[str, Any]],
) -> bool:
    top_txt = _joined(top_entries)
    dock_txt = _joined(dock_entries)
    top_hits = sum(1 for kw in ("装修商店", "海岛兑换", "营收报表", "事项一览", "管理中心") if kw in top_txt)
    dock_hits = sum(1 for kw in ("巡逻", "导航", "装修", "扩建", "宣传") if kw in dock_txt)
    return (top_hits >= 2 and dock_hits >= 2) or dock_hits >= 3


def is_island_report_entries(entries: Sequence[Mapping[str, Any]]) -> bool:
    joined = _joined(entries)
    return "海岛经营报表" in joined or ("海岛评分" in joined and "稳定指数" in joined)


def is_island_ops_overview_entries(
    tab_entries: Sequence[Mapping[str, Any]],
    body_entries: Sequence[Mapping[str, Any]],
) -> bool:
    tab_txt = _joined(tab_entries)
    body_txt = _joined(body_entries)
    return ("营收概览" in tab_txt or "当前营业概况" in body_txt) and ("当前分成比例" in body_txt or "收钱" in body_txt)


def is_island_ops_invest_entries(
    tab_entries: Sequence[Mapping[str, Any]],
    body_entries: Sequence[Mapping[str, Any]],
) -> bool:
    tab_txt = _joined(tab_entries)
    body_txt = _joined(body_entries)
    return "投资增益" in body_txt or ("剩余投资次数" in body_txt) or ("已投资金额" in body_txt and "投资" in tab_txt)


def is_island_trash_screen_entries(entries: Sequence[Mapping[str, Any]]) -> bool:
    joined = _joined(entries)
    return "海岛垃圾产出总览" in joined or ("压缩垃圾暂存区" in joined) or ("待压缩垃圾数量" in joined)


def is_island_todo_entries(entries: Sequence[Mapping[str, Any]]) -> bool:
    joined = _joined(entries)
    return "海岛管理局" in joined or "海岛等级" in joined or ("剧情任务" in joined and "建设任务" in joined)


def is_island_card_pack_entries(entries: Sequence[Mapping[str, Any]]) -> bool:
    """判定当前是否弹出需要右划撕开的「海岛纪念卡包」提示界面。"""
    joined = _joined(entries)
    return "请用手指滑动" in joined or "滑动屏幕" in joined


def is_island_friends_drawer_entries(entries: Sequence[Mapping[str, Any]]) -> bool:
    joined = _joined(entries)
    return ("FRIEND" in joined.upper() or "今日访客" in joined or "好友" in joined) and (
        "清扫" in joined or "治安" in joined or "访问记录" in joined
    )


def is_friend_island_entries(
    dash_entries: Sequence[Mapping[str, Any]],
    bottom_entries: Sequence[Mapping[str, Any]],
) -> bool:
    dash_txt = _joined(dash_entries)
    bot_txt = _joined(bottom_entries)
    return (
        "帮助次数" in dash_txt
        or "可被清理" in dash_txt
        or "可被洁理" in dash_txt
        or "获得垃圾概率" in dash_txt
    ) and ("清扫" in bot_txt or "下一位" in bot_txt)


def is_island_exchange_shop_entries(
    header_entries: Sequence[Mapping[str, Any]],
    list_entries: Sequence[Mapping[str, Any]] = (),
) -> bool:
    """判定是否已进入「海岛兑换处」界面。"""
    hdr_txt = _joined(header_entries)
    if "海岛兑换" in hdr_txt:
        return True
    list_txt = _joined(list_entries)
    if "EXCHANGE" in list_txt.upper() and any(
        kw in list_txt for kw in ("剩余", "拉普拉斯", "喧闹摇滚", "沙滩比赛用球", "祖父反应装甲")
    ):
        return True
    return False


def is_island_expand_modal_entries(entries: Sequence[Mapping[str, Any]]) -> bool:
    """判定当前是否弹出「海岛扩建」确认弹窗。"""
    joined = _joined(entries)
    return "海岛扩建" in joined or ("解锁" in joined and "需求" in joined)


def is_free_island_formation_entries(
    btn_entries: Sequence[Mapping[str, Any]],
    cost_entries: Sequence[Mapping[str, Any]],
) -> bool:
    """校验处于编队界面的「开始作战」且为 0 体力消耗（含 `-0` 或无消耗数字）。"""
    btn_txt = _joined(btn_entries)
    if "开始作战" not in btn_txt and "START" not in btn_txt.upper():
        return False
    cost_txt = _joined(cost_entries)
    if not cost_txt:
        return True
    nums = [int(m) for m in re.findall(r"\d+", cost_txt)]
    return all(n == 0 for n in nums)


# ==============================================================================
# 数据提取器
# ==============================================================================

_PURE_COMPACT_RE = re.compile(r"^\d+(?:,\d{3})*(?:\.\d+)?\s*[kKmMwW万亿]?$")
_PURE_INT_RE = re.compile(r"^\d+(?:,\d{3})*$")
_LENIENT_LV_RE = re.compile(r"(?<![A-Za-z])[Vv]\.?\s*(\d+)")


def _extract_level_value(text: str) -> int | None:
    """提取等级数字，兼容 `LV14` / `LV 14` 及左缘 L 被遮挡时的 `v14`。"""
    m_lv = _LV_RE.search(text) or _LENIENT_LV_RE.search(text)
    return int(m_lv.group(1)) if m_lv else None


def _pick_compact_number_entry(
    entries: Sequence[Mapping[str, Any]],
    *,
    min_score: float = 0.5,
    min_cx: int | None = None,
    max_cx: int | None = None,
) -> int | None:
    """在 OCR 候选列表中过滤低置信度噪声后提取最优紧凑数字。"""
    best_key: tuple[int, float, int, int] | None = None
    best_val: int | None = None
    for entry in entries:
        if not isinstance(entry, Mapping):
            continue
        score = _entry_score(entry)
        if score < min_score:
            continue
        txt = _clean_text(entry.get("text")).rstrip("+")
        if not txt or not re.search(r"\d", txt):
            continue
        center = _entry_center(entry)
        cx_val = center[0] if center is not None else 0
        if min_cx is not None or max_cx is not None:
            if center is None:
                continue
            if min_cx is not None and cx_val < min_cx:
                continue
            if max_cx is not None and cx_val > max_cx:
                continue
        val = parse_compact_number(txt, -1)
        if val < 0:
            continue
        is_pure = 1 if _PURE_COMPACT_RE.fullmatch(txt) else 0
        digit_count = sum(1 for ch in txt if ch.isdigit())
        key = (is_pure, score, digit_count, cx_val)
        if best_key is None or key > best_key:
            best_key = key
            best_val = val
    return best_val


def parse_island_main_hud(
    top_entries: Sequence[Mapping[str, Any]],
    left_entries: Sequence[Mapping[str, Any]],
    counts_entries: Sequence[Mapping[str, Any]],
    *,
    ticket_entries: Sequence[Mapping[str, Any]] = (),
    shell_entries: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """解析海岛主界面顶栏代币、左下等级/今日收益与人数/怪数/清洁度。"""
    result: dict[str, Any] = {
        "level": 0,
        "today_revenue_coins": 0,
        "visitors_current": 0,
        "active_monsters": 0,
        "cleanliness_pct": 100,
        "material_tickets": 0,
        "shell_coins": 0,
    }
    if ticket_entries:
        tkt_val = _pick_compact_number_entry(ticket_entries)
        if tkt_val is not None:
            result["material_tickets"] = tkt_val
    if shell_entries:
        shl_val = _pick_compact_number_entry(shell_entries)
        if shl_val is not None:
            result["shell_coins"] = shl_val

    if result["material_tickets"] == 0:
        tkt_val = _pick_compact_number_entry(top_entries, min_cx=780, max_cx=975)
        if tkt_val is not None:
            result["material_tickets"] = tkt_val
    if result["shell_coins"] == 0:
        shl_val = _pick_compact_number_entry(top_entries, min_cx=985, max_cx=1165)
        if shl_val is not None:
            result["shell_coins"] = shl_val

    left_txt = _joined(left_entries)
    lv_val = _extract_level_value(left_txt)
    if lv_val is None:
        best_lv_score = -1.0
        for entry in left_entries:
            if not isinstance(entry, Mapping):
                continue
            score = _entry_score(entry)
            if score < 0.5:
                continue
            txt = _clean_text(entry.get("text"))
            if not _PURE_INT_RE.fullmatch(txt):
                continue
            center = _entry_center(entry)
            if center is None:
                continue
            cx, cy = center
            if cx < 75 and 615 <= cy <= 665:
                cand = int(txt.replace(",", ""))
                if 1 <= cand <= 99 and score > best_lv_score:
                    best_lv_score = score
                    lv_val = cand
    if lv_val is not None:
        result["level"] = lv_val

    rev_val: int | None = None
    rev_center: tuple[int, int] | None = None
    for entry in left_entries:
        if not isinstance(entry, Mapping):
            continue
        txt = _clean_text(entry.get("text"))
        if "今日收益" not in txt:
            continue
        rev_center = _entry_center(entry)
        m_inline = re.search(r"今日收益\s*[:：]?\s*(\d+(?:\.\d+)?\s*[kKmMwW万亿]?)", txt)
        if m_inline:
            rev_val = parse_compact_number(m_inline.group(1), 0)
            break
    if rev_val is None and rev_center is not None:
        rev_cx, rev_cy = rev_center
        best_row: tuple[int, int] | None = None
        for entry in left_entries:
            if not isinstance(entry, Mapping):
                continue
            txt = _clean_text(entry.get("text"))
            if not _PURE_COMPACT_RE.fullmatch(txt):
                continue
            center = _entry_center(entry)
            if center is None:
                continue
            cx, cy = center
            if abs(cy - rev_cy) <= 18 and cx > rev_cx:
                dist = (abs(cy - rev_cy), cx)
                if best_row is None or dist < best_row:
                    best_row = dist
                    rev_val = parse_compact_number(txt, 0)
    if rev_val is None and not any(
        isinstance(e, Mapping) and _entry_center(e) is not None for e in left_entries
    ):
        m_rev = re.search(r"今日收益[^\d]*(\d+(?:\.\d+)?\s*[kKmMwW万]?)", left_txt)
        if m_rev:
            rev_val = parse_compact_number(m_rev.group(1), 0)
    if rev_val is not None:
        result["today_revenue_coins"] = rev_val

    counts_items = sorted(
        (
            (_entry_center(e)[0], _clean_text(e.get("text")))  # type: ignore[index]
            for e in counts_entries
            if isinstance(e, Mapping) and _entry_center(e) is not None and _clean_text(e.get("text"))
        ),
        key=lambda item: item[0],
    )
    pct_val: int | None = None
    x_nums: list[int] = []
    for _, txt in counts_items:
        m_pct = _PCT_RE.search(txt)
        if m_pct:
            pct_val = int(round(float(m_pct.group(1))))
            continue
        for m in re.findall(r"[xX×]?\s*(\d+)", txt):
            x_nums.append(int(m))
    if pct_val is not None:
        result["cleanliness_pct"] = min(100, max(0, pct_val))
    if len(x_nums) >= 1:
        result["visitors_current"] = x_nums[0]
    if len(x_nums) >= 2:
        result["active_monsters"] = x_nums[1]
    return result


def parse_island_report_overview(
    left_entries: Sequence[Mapping[str, Any]],
    scores_entries: Sequence[Mapping[str, Any]],
    basic_entries: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """解析海岛经营报表（总览页）：等级、垃圾产出/数量、7 维+清洁度、稳定指数、木屋等级等。"""
    out: dict[str, Any] = {
        "level": 0,
        "trash_rate_per_hour": 0,
        "trash_blocks_stored": 0,
        "scores": {
            "舒适": 0,
            "娱乐": 0,
            "绿植": 0,
            "宠物": 0,
            "水族": 0,
            "美食": 0,
            "医疗": 0,
        },
        "cleanliness_pct": 100,
        "operating_days": 0,
        "total_visitors": 0,
        "stability_current": 0,
        "stability_max": 200,
        "facilities_count": 0,
        "cabin_level": 0,
        "decorations_count": 0,
    }
    left_txt = _joined(left_entries)
    lv_val = _extract_level_value(left_txt)
    if lv_val is not None:
        out["level"] = lv_val
    m_rate = _RATE_RE.search(left_txt)
    if m_rate:
        out["trash_rate_per_hour"] = int(m_rate.group(1))

    # 压缩垃圾数量优先按单框行内或左下角坐标槽匹配，避免 OCR 按 X 排序将 LV14 误匹配为数量
    comp_val: int | None = None
    comp_label_cy: int | None = None
    has_left_coords = False
    for entry in left_entries:
        if not isinstance(entry, Mapping):
            continue
        txt = _clean_text(entry.get("text"))
        center = _entry_center(entry)
        if center is not None:
            has_left_coords = True
        m_inline = re.search(r"压缩垃圾数量\s*[:：]?\s*(\d+)", txt)
        if m_inline:
            comp_val = int(m_inline.group(1))
            break
        if "压缩垃圾" in txt and center is not None:
            comp_label_cy = center[1]
    if comp_val is None and has_left_coords:
        best_comp_key: tuple[int, int] | None = None
        for entry in left_entries:
            if not isinstance(entry, Mapping):
                continue
            txt = _clean_text(entry.get("text"))
            if not _PURE_INT_RE.fullmatch(txt):
                continue
            center = _entry_center(entry)
            if center is None:
                continue
            cx, cy = center
            if cx < 360:
                continue
            if comp_label_cy is not None:
                if not (comp_label_cy - 10 <= cy <= comp_label_cy + 55):
                    continue
                dist_key = (abs(cy - comp_label_cy), -cy)
            else:
                if cy < 520:
                    continue
                dist_key = (-cy, -cx)
            if best_comp_key is None or dist_key < best_comp_key:
                best_comp_key = dist_key
                comp_val = int(txt.replace(",", ""))
    if comp_val is None and not has_left_coords:
        m_comp = re.search(r"压缩垃圾数量[^\d]*(\d+)", left_txt)
        if m_comp:
            comp_val = int(m_comp.group(1))
    if comp_val is not None:
        out["trash_blocks_stored"] = comp_val

    # 8 格顶牌：按 4 列 × 2 行网格归位（ROI 起点 (615, 210, 495, 115)）
    grid_cells: list[tuple[int, int, int]] = []
    for e in scores_entries:
        if not isinstance(e, Mapping) or _entry_score(e) < 0.5:
            continue
        center = _entry_center(e)
        txt = _clean_text(e.get("text"))
        if center is None or not txt:
            continue
        cx, cy = center
        col = min(3, max(0, int((cx - 615) / (495 / 4))))
        row = 0 if cy < 268 else 1
        m_pct = _PCT_RE.search(txt)
        if row == 1 and col == 3 and m_pct:
            out["cleanliness_pct"] = min(100, max(0, int(round(float(m_pct.group(1))))))
            continue
        val = parse_compact_number(txt, -1)
        if val >= 0:
            grid_cells.append((row, col, val))

    slot_names = {
        (0, 0): "舒适",
        (0, 1): "娱乐",
        (0, 2): "绿植",
        (0, 3): "宠物",
        (1, 0): "水族",
        (1, 1): "美食",
        (1, 2): "医疗",
    }
    for r, c, val in grid_cells:
        if (r, c) in slot_names:
            out["scores"][slot_names[(r, c)]] = val

    # 基本信息 3 列 × 2 行网格（ROI (505, 350, 600, 225)）
    basic_txt = _joined(basic_entries)
    m_stab = _RATIO_RE.search(basic_txt)
    if m_stab:
        out["stability_current"] = int(m_stab.group(1))
        out["stability_max"] = max(1, int(m_stab.group(2)))
    for e in basic_entries:
        if not isinstance(e, Mapping) or _entry_score(e) < 0.5:
            continue
        center = _entry_center(e)
        txt = _clean_text(e.get("text"))
        if center is None or not txt or not re.search(r"\d", txt):
            continue
        if any(k in txt for k in ("经营天数", "游客人数", "稳定指数", "设施数量", "木屋等级", "装饰数量", "INFORMATION")):
            continue
        cx, cy = center
        if 410 <= cy <= 465:
            row = 0
        elif 520 <= cy <= 575:
            row = 1
        else:
            continue
        col = min(2, max(0, int((cx - 505) / 200)))
        if row == 0 and col == 2 and "/" in txt:
            continue
        val = parse_compact_number(txt, -1)
        if val < 0:
            continue
        if (row, col) == (0, 0):
            out["operating_days"] = val
        elif (row, col) == (0, 1):
            out["total_visitors"] = val
        elif (row, col) == (1, 0):
            out["facilities_count"] = val
        elif (row, col) == (1, 1):
            out["cabin_level"] = val
        elif (row, col) == (1, 2):
            out["decorations_count"] = val
    return out


def parse_island_ops_overview(
    stay_entries: Sequence[Mapping[str, Any]],
    metrics_entries: Sequence[Mapping[str, Any]],
    footer_entries: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """解析营运概览（平均游玩天数、分成/票价/税率、累计游客、待领收益）。"""
    out: dict[str, Any] = {
        "avg_stay_days": 1.0,
        "share_ratio_pct": 3.0,
        "ticket_price": 500,
        "tax_rate_pct": 5.0,
        "total_visitors": 0,
        "pending_revenue_coins": 0,
        "collect_point": None,
    }
    stay_txt = _joined(stay_entries)
    m_stay = re.search(r"(\d+(?:\.\d+)?)", stay_txt)
    if m_stay:
        out["avg_stay_days"] = float(m_stay.group(1))

    has_metric_coords = False
    found_share = False
    found_ticket = False
    found_tax = False
    found_vis = False
    for entry in metrics_entries:
        if not isinstance(entry, Mapping):
            continue
        center = _entry_center(entry)
        if center is None:
            continue
        has_metric_coords = True
        cx, cy = center
        txt = _clean_text(entry.get("text"))
        if not txt:
            continue
        if 205 <= cy <= 262:
            m_pct = _PCT_RE.search(txt)
            if 720 <= cx <= 845 and m_pct:
                out["share_ratio_pct"] = float(m_pct.group(1))
                found_share = True
            elif 935 <= cx <= 1050 and "%" not in txt and _PURE_COMPACT_RE.fullmatch(txt):
                val = parse_compact_number(txt, -1)
                if val >= 0:
                    out["ticket_price"] = val
                    found_ticket = True
            elif 1130 <= cx <= 1255 and m_pct:
                out["tax_rate_pct"] = float(m_pct.group(1))
                found_tax = True
        elif 262 < cy <= 325 and cx >= 1060 and "%" not in txt and _PURE_COMPACT_RE.fullmatch(txt):
            val = parse_compact_number(txt, -1)
            if val >= 0:
                out["total_visitors"] = val
                found_vis = True

    if not has_metric_coords:
        m_txt = _joined(metrics_entries)
        if not found_share:
            m_share = re.search(r"当前分成比例[^\d]*(\d+(?:\.\d+)?)\s*%", m_txt)
            if m_share:
                out["share_ratio_pct"] = float(m_share.group(1))
        if not found_ticket:
            m_ticket = re.search(r"当前票价[^\d]*(\d+)", m_txt)
            if m_ticket:
                out["ticket_price"] = int(m_ticket.group(1))
        if not found_tax:
            m_tax = re.search(r"税率[^\d]*(\d+(?:\.\d+)?)\s*%", m_txt)
            if m_tax:
                out["tax_rate_pct"] = float(m_tax.group(1))
        if not found_vis:
            m_vis = re.search(r"累计[^\d]*(\d+)", m_txt)
            if m_vis:
                out["total_visitors"] = int(m_vis.group(1))

    footer_txt = _joined(footer_entries)
    m_pend = re.search(r"(?:当前收益|税后分成)[）)\s]*(\d+(?:\.\d+)?\s*[kKmMwW万]?)", footer_txt)
    if m_pend:
        out["pending_revenue_coins"] = parse_compact_number(m_pend.group(1), 0)
    else:
        for e in footer_entries:
            if not isinstance(e, Mapping):
                continue
            pt = _entry_center(e)
            if pt is not None and not (900 <= pt[0] <= 1085):
                continue
            if re.fullmatch(r"[\d,kKmMwW.]+", _clean_text(e.get("text"))):
                out["pending_revenue_coins"] = parse_compact_number(e.get("text"), 0)
                break

    for e in footer_entries:
        if not isinstance(e, Mapping):
            continue
        if "收钱" in _clean_text(e.get("text")):
            pt = _entry_center(e)
            if pt is not None and pt[0] >= 1060:
                out["collect_point"] = pt
                break
    return out


_COMPACT_RATIO_RE = re.compile(
    r"(\d+(?:\.\d+)?\s*[kKmMwW万亿]?)\s*/\s*(\d+(?:\.\d+)?\s*[kKmMwW万亿]?)"
)


def parse_island_ops_invest(
    remaining_entries: Sequence[Mapping[str, Any]],
    summary_entries: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """解析海岛投资页剩余投资次数与累计已投资金额。"""
    rem_txt = _joined(remaining_entries)
    sum_txt = _joined(summary_entries)
    m_rem = re.search(r"剩余投资次数[^\d]*(\d+)", rem_txt)
    rem = int(m_rem.group(1)) if m_rem else 0
    invested = 0
    m_inv = re.search(r"(\d[\d,]*)\s*已投资金额", sum_txt)
    if m_inv:
        invested = parse_compact_number(m_inv.group(1), 0)
    else:
        for e in summary_entries:
            if isinstance(e, Mapping):
                txt = _clean_text(e.get("text")).replace(",", "")
                if txt.isdigit():
                    invested = int(txt)
                    break
    return {"invest_remaining": rem, "invested_total": invested}


def parse_island_ops_coins(entries: Sequence[Mapping[str, Any]]) -> int:
    """解析运营投资界面右上角实时铁盟币余额（如 46991972+ -> 46991972）。"""
    val = _pick_compact_number_entry(entries, min_score=0.5)
    return int(val) if val is not None else 0


_INVEST_COL_FALLBACK_X: tuple[int, int, int] = (714, 932, 1152)


def parse_island_invest_cards(cards_entries: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """解析海岛运营投资页 3 张立牌的类型、加成值、所需铁盟币与点击按钮坐标。"""
    cols: dict[int, list[tuple[int, int, str, float]]] = {0: [], 1: [], 2: []}
    for e in cards_entries:
        if not isinstance(e, Mapping):
            continue
        score = _entry_score(e)
        if score < 0.45:
            continue
        txt = _clean_text(e.get("text"))
        if not txt:
            continue
        center = _entry_center(e)
        if center is None:
            continue
        cx, cy = center
        col = 0 if cx < 825 else (1 if cx < 1042 else 2)
        cols[col].append((cx, cy, txt, score))

    cards: list[dict[str, Any]] = []
    for col in (0, 1, 2):
        items = cols[col]
        if not items:
            continue
        joined = " ".join(it[2] for it in items)
        if "分成" in joined:
            kind = "share_ratio"
        elif "票价" in joined:
            kind = "ticket_price"
        elif "纳税" in joined or "税率" in joined or "税" in joined:
            kind = "tax_reduce"
        else:
            kind = "unknown"

        has_huashi = "桦石" in joined
        is_maxed = any(kw in joined for kw in ("已满", "已达上限", "售罄"))

        benefit_value = 0.0
        m_gain = re.search(
            r"(?:获得|提高|提升|减少)\s*[+-]?\s*(\d+(?:\.\d+)?)\s*%?\s*(?:分成|票价|纳税|税率|税|奖励)?",
            joined,
        )
        if m_gain:
            benefit_value = abs(float(m_gain.group(1)))
        else:
            upper_nums = sorted(
                (
                    (0 if ("%" in txt or txt.startswith(("+", "-"))) else 1, cy, txt)
                    for _, cy, txt, _ in items
                    if cy < 540 and "铁盟币" not in txt and not txt.startswith("投资") and re.search(r"\d", txt)
                ),
                key=lambda item: (item[0], item[1]),
            )
            for _, _, txt in upper_nums:
                m_num = re.search(r"[+-]?\s*(\d+(?:\.\d+)?)", txt)
                if m_num:
                    benefit_value = abs(float(m_num.group(1)))
                    break

        desc_cost = 0
        m_desc_cost = re.search(r"投资\s*(\d+(?:\.\d+)?\s*[kKmMwW万亿]?)\s*铁盟币", joined)
        if m_desc_cost:
            desc_cost = parse_compact_number(m_desc_cost.group(1), 0)

        cost_coins = 0
        tap_point: tuple[int, int] = (_INVEST_COL_FALLBACK_X[col], 648)
        bottom_candidates: list[tuple[int, int, int, int, int, int, str]] = []
        for cx, cy, txt, _ in items:
            if cy < 540 or not re.search(r"\d", txt):
                continue
            parsed_cost = parse_compact_number(txt, 0)
            if parsed_cost <= 0:
                continue
            digit_cnt = sum(1 for ch in txt if ch.isdigit())
            exact_desc = 1 if (desc_cost > 0 and parsed_cost == desc_cost) else 0
            at_button_row = 1 if cy >= 590 else 0
            ge_hundred = 1 if parsed_cost >= 100 else 0
            bottom_candidates.append(
                (exact_desc, at_button_row, ge_hundred, digit_cnt, parsed_cost, cx, cy)
            )
        bottom_candidates.sort(reverse=True)
        if bottom_candidates:
            _, _, _, _, parsed_cost, cx, cy = bottom_candidates[0]
            if parsed_cost < 100 and desc_cost >= 100:
                cost_coins = desc_cost
            else:
                cost_coins = parsed_cost
            tap_point = (cx, cy)
        elif desc_cost > 0:
            cost_coins = desc_cost

        cards.append(
            {
                "col": col,
                "kind": kind,
                "benefit_value": benefit_value,
                "cost_coins": cost_coins,
                "tap_point": tap_point,
                "has_huashi": has_huashi,
                "is_maxed": is_maxed,
                "raw_text": joined,
            }
        )
    return cards


def choose_best_island_invest_card(
    cards: Sequence[Mapping[str, Any]],
    *,
    spendable_coins: int,
    share_ratio_pct: float = 0.0,
    ticket_price: int = 0,
    tax_rate_pct: float = 5.0,
) -> tuple[dict[str, Any] | None, str]:
    """按 分成比例(>票价>纳税减少) 与可动用余额优先级挑出最优投资卡。"""
    if int(spendable_coins) <= 0:
        return None, "no_spendable_coins"

    priority_map = {
        "share_ratio": 3,
        "ticket_price": 2,
        "tax_reduce": 1,
    }
    has_uncapped_candidate = False
    has_non_huashi_candidate = False
    best_card: dict[str, Any] | None = None
    best_key: tuple[int, float, int] | None = None

    for card in cards:
        if not isinstance(card, Mapping):
            continue
        kind = str(card.get("kind") or "unknown")
        if kind not in priority_map:
            continue
        if bool(card.get("has_huashi")) or bool(card.get("is_maxed")):
            continue
        has_non_huashi_candidate = True
        if kind == "share_ratio" and float(share_ratio_pct) >= 35.0:
            continue
        if kind == "ticket_price" and int(ticket_price) >= 2000:
            continue
        if kind == "tax_reduce" and float(tax_rate_pct) <= 0.0:
            continue
        cost = int(card.get("cost_coins") or 0)
        if cost <= 0:
            continue
        has_uncapped_candidate = True
        if cost > int(spendable_coins):
            continue
        key = (priority_map[kind], float(card.get("benefit_value") or 0.0), -cost)
        if best_key is None or key > best_key:
            best_key = key
            best_card = dict(card)

    if best_card is not None:
        return best_card, "ok"
    if has_uncapped_candidate:
        return None, "exceeds_reserve"
    if has_non_huashi_candidate:
        return None, "all_capped"
    return None, "no_eligible_card"


def parse_island_expand_modal(
    modal_entries: Sequence[Mapping[str, Any]],
    button_entries: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """解析海岛扩建确认弹窗的铁盟币/资材券需求、海岛等级要求及取消/确认按钮坐标。"""
    modal_txt = _joined(modal_entries)
    btn_txt = _joined(button_entries)
    out: dict[str, Any] = {
        "is_expand_modal": is_island_expand_modal_entries(modal_entries),
        "has_huashi": ("桦石" in modal_txt or "桦石" in btn_txt),
        "required_level": 0,
        "have_coins": 0,
        "cost_coins": 0,
        "have_tickets": 0,
        "cost_tickets": 0,
        "cancel_point": ISLAND_EXPAND_CANCEL_FALLBACK,
        "confirm_point": None,
    }
    m_req = re.search(r"需求[^\d]*L[Vv]\.?\s*(\d+)", modal_txt)
    if m_req:
        out["required_level"] = int(m_req.group(1))
    else:
        lv_val = _extract_level_value(modal_txt)
        if lv_val is not None:
            out["required_level"] = lv_val

    has_coords = False
    unplaced_ratios: list[tuple[int, int]] = []
    for e in modal_entries:
        if not isinstance(e, Mapping):
            continue
        txt = _clean_text(e.get("text"))
        if not txt:
            continue
        m_rat = _COMPACT_RATIO_RE.search(txt)
        if not m_rat:
            continue
        have_val = parse_compact_number(m_rat.group(1), 0)
        cost_val = parse_compact_number(m_rat.group(2), 0)
        center = _entry_center(e)
        if center is None:
            unplaced_ratios.append((have_val, cost_val))
            continue
        has_coords = True
        if center[0] < 640:
            out["have_coins"] = have_val
            out["cost_coins"] = cost_val
        else:
            out["have_tickets"] = have_val
            out["cost_tickets"] = cost_val

    if not has_coords and unplaced_ratios:
        out["have_coins"], out["cost_coins"] = unplaced_ratios[0]
        if len(unplaced_ratios) >= 2:
            out["have_tickets"], out["cost_tickets"] = unplaced_ratios[1]

    for e in button_entries:
        if not isinstance(e, Mapping):
            continue
        txt = _clean_text(e.get("text"))
        pt = _entry_center(e)
        if pt is None or not txt:
            continue
        if "取消" in txt and pt[0] < 640:
            out["cancel_point"] = pt
        elif ("确认" in txt or "确定" in txt) and pt[0] >= 640:
            out["confirm_point"] = pt
    return out


def evaluate_island_expand_safe(
    modal_data: Mapping[str, Any],
    *,
    current_level: int,
    live_coins: int,
    live_tickets: int,
    reserve_coins: int,
) -> tuple[bool, str]:
    """海岛扩建执行前硬护栏校验：等级、扣费后铁盟币底线、资材券余额、零桦石、确认按钮齐全。"""
    if not bool(modal_data.get("is_expand_modal")):
        return False, "未识别到海岛扩建确认弹窗"
    if bool(modal_data.get("has_huashi")):
        return False, "检测到桦石消耗词，硬护栏已中止扩建"
    cost_coins = int(modal_data.get("cost_coins") or 0)
    cost_tickets = int(modal_data.get("cost_tickets") or 0)
    if cost_coins <= 0 or cost_tickets <= 0:
        return False, "未能完整解析扩建所需铁盟币/资材券，已安全取消"
    if modal_data.get("confirm_point") is None:
        return False, "未安全识别到确认按钮，已安全取消"
    req_lv = int(modal_data.get("required_level") or 0)
    if req_lv > 0 and int(current_level) < req_lv:
        return False, f"海岛等级不足（当前 LV{current_level} < 需求 LV{req_lv}）"
    effective_coins = int(live_coins) if int(live_coins) > 0 else int(modal_data.get("have_coins") or 0)
    if effective_coins <= 0:
        return False, "铁盟币余额未知，无法校验留存底线"
    if effective_coins - cost_coins < int(reserve_coins):
        return (
            False,
            f"扩建后铁盟币将低于底线（{effective_coins:,} - {cost_coins:,} < {int(reserve_coins):,}）",
        )
    effective_tickets = int(live_tickets) if int(live_tickets) > 0 else int(modal_data.get("have_tickets") or 0)
    if effective_tickets < cost_tickets:
        return False, f"资材券不足（{effective_tickets:,} < {cost_tickets:,}）"
    return True, "ok"


def parse_island_exchange_shop(
    currency_entries: Sequence[Mapping[str, Any]],
    list_entries: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """只读解析海岛兑换处顶栏货币（含排球奖币/贝币）与商品库存/可兑状态。"""
    coins = _pick_compact_number_entry(currency_entries, min_score=0.4, min_cx=650, max_cx=860) or 0
    volleyball = _pick_compact_number_entry(currency_entries, min_score=0.4, min_cx=860, max_cx=1070) or 0
    shells = _pick_compact_number_entry(currency_entries, min_score=0.4, min_cx=1070, max_cx=1275) or 0

    _EXCHANGE_BADGE_NOISE = {"福礼", "特惠", "限购", "热卖", "折扣", "新品", "EXCHANGE"}
    positioned: list[tuple[int, int, str]] = []
    for e in list_entries:
        if not isinstance(e, Mapping) or _entry_score(e) < 0.45:
            continue
        txt = _clean_text(e.get("text"))
        if not txt or txt in _EXCHANGE_BADGE_NOISE:
            continue
        center = _entry_center(e)
        if center is None:
            continue
        positioned.append((center[1], center[0], txt))
    positioned.sort(key=lambda item: (item[0], item[1]))

    def _has_ratio(row_items: Sequence[tuple[int, int, str]]) -> bool:
        return any(_COMPACT_RATIO_RE.search(r[2]) for r in row_items)

    def _has_rem(row_items: Sequence[tuple[int, int, str]]) -> bool:
        return any(
            re.search(r"剩余\s*\d+\s*次?", r[2]) or "售罄" in r[2] or "已兑完" in r[2]
            for r in row_items
        )

    rows: list[list[tuple[int, int, str]]] = []
    for item in positioned:
        cy, _, txt = item
        if not rows:
            rows.append([item])
            continue
        cur_row = rows[-1]
        dy = abs(cy - cur_row[0][0])
        is_ratio_item = bool(_COMPACT_RATIO_RE.search(txt))
        is_rem_item = bool(re.search(r"剩余\s*\d+\s*次?", txt) or "售罄" in txt or "已兑完" in txt)
        conflict = (is_ratio_item and _has_ratio(cur_row)) or (is_rem_item and _has_rem(cur_row))
        if dy <= 80 and not conflict:
            cur_row.append(item)
        else:
            rows.append([item])

    items: list[dict[str, Any]] = []
    for row in rows:
        row_txt = " ".join(r[2] for r in row)
        name_candidates = [
            r[2]
            for r in row
            if re.search(r"[\u4e00-\u9fff]", r[2])
            and not _COMPACT_RATIO_RE.search(r[2])
            and "剩余" not in r[2]
            and "兑换" not in r[2]
            and "售罄" not in r[2]
            and "已兑完" not in r[2]
        ]
        name = max(name_candidates, key=len) if name_candidates else ""

        remaining = -1
        if "售罄" in row_txt or "已兑完" in row_txt:
            remaining = 0
        else:
            m_rem = re.search(r"剩余\s*(\d+)\s*次?", row_txt)
            if m_rem:
                remaining = int(m_rem.group(1))

        have = 0
        cost = 0
        for _, _, txt in row:
            m_rat = _COMPACT_RATIO_RE.search(txt)
            if m_rat:
                have = parse_compact_number(m_rat.group(1), 0)
                cost = parse_compact_number(m_rat.group(2), 0)
                break

        if cost <= 0:
            continue
        items.append(
            {
                "name": name or "未知商品",
                "remaining": remaining,
                "have": have,
                "cost": cost,
                "affordable": bool(cost > 0 and have >= cost and remaining != 0),
            }
        )

    return {
        "coins": int(coins),
        "volleyball_coins": int(volleyball),
        "shell_coins": int(shells),
        "items": items,
    }


def parse_island_trash_screen(
    header_entries: Sequence[Mapping[str, Any]],
    pending_entries: Sequence[Mapping[str, Any]],
    machine_entries: Sequence[Mapping[str, Any]],
    storage_entries: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """解析海岛垃圾产出总览：产率、待压缩数、压缩机等级、暂存区 used/cap。"""
    out = {
        "trash_rate_per_hour": 0,
        "trash_pending_raw": 0,
        "trash_station_level": 1,
        "trash_blocks_stored": 0,
        "trash_blocks_cap": 0,
    }
    hdr_txt = _joined(header_entries)
    m_rate = _RATE_RE.search(hdr_txt)
    if m_rate:
        out["trash_rate_per_hour"] = int(m_rate.group(1))
    pend_txt = _joined(pending_entries)
    m_pend = re.search(r"待压缩垃圾数量[^\d]*(\d+)", pend_txt)
    if m_pend:
        out["trash_pending_raw"] = int(m_pend.group(1))
    mac_txt = _joined(machine_entries)
    m_lv = _LV_RE.search(mac_txt)
    if m_lv:
        out["trash_station_level"] = int(m_lv.group(1))
    sto_txt = _joined(storage_entries)
    m_sto = _RATIO_RE.search(sto_txt)
    if m_sto:
        out["trash_blocks_stored"] = int(m_sto.group(1))
        out["trash_blocks_cap"] = int(m_sto.group(2))
    return out


def find_island_trash_collect_point(action_entries: Sequence[Mapping[str, Any]]) -> tuple[int, int] | None:
    """硬护栏：仅定位右侧「一键收取」，严禁误触左侧「一键处理」。"""
    for e in action_entries:
        if not isinstance(e, Mapping):
            continue
        txt = _clean_text(e.get("text"))
        if not txt or "处理" in txt or "收取" not in txt:
            continue
        pt = _entry_center(e)
        if pt is not None and pt[0] >= 1070:
            return pt
    return None


def find_island_todo_claim_points(button_entries: Sequence[Mapping[str, Any]]) -> list[tuple[int, int]]:
    """硬护栏：在事项一览右列仅返回「领取/领奖」文字框中心，绝不点击「追踪」。"""
    points: list[tuple[int, int]] = []
    for e in button_entries:
        if not isinstance(e, Mapping):
            continue
        txt = _clean_text(e.get("text"))
        if not txt or "追踪" in txt:
            continue
        if "领取" in txt or "领奖" in txt:
            pt = _entry_center(e)
            if pt is not None and pt[0] >= 1080:
                points.append(pt)
    points.sort(key=lambda p: p[1])
    return points


def island_todo_claim_circle_point(label_point: tuple[int, int]) -> tuple[int, int]:
    """根据「领取」文字中心计算上方圆形按钮图标区坐标（实机圆钮位于文字上方约 32px）。"""
    return int(label_point[0]), max(55, int(label_point[1]) - 32)


def find_friend_list_visit_points(list_entries: Sequence[Mapping[str, Any]]) -> list[tuple[int, int]]:
    """从好友列表提取每行「访问」按钮坐标（按纵坐标从上到下排序）。"""
    pts: list[tuple[int, int]] = []
    for e in list_entries:
        if not isinstance(e, Mapping):
            continue
        txt = _clean_text(e.get("text"))
        if "访问" not in txt or "记录" in txt:
            continue
        pt = _entry_center(e)
        if pt is not None and 430 <= pt[0] <= 600:
            pts.append(pt)
    pts.sort(key=lambda p: p[1])
    return pts


def parse_friend_island_status(
    dash_entries: Sequence[Mapping[str, Any]],
    info_entries: Sequence[Mapping[str, Any]],
    counts_entries: Sequence[Mapping[str, Any]],
    bottom_entries: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """解析好友海岛右上仪表盘、好友名、怪物数及底部按钮位置。"""
    out: dict[str, Any] = {
        "friend_name": "",
        "help_remaining": 0,
        "help_remaining_known": False,
        "help_max": 5,
        "clean_remaining": 0,
        "clean_remaining_known": False,
        "clean_max": 3,
        "active_monsters": 0,
        "clean_point": None,
        "like_point": None,
        "next_point": None,
    }
    dash_items = sorted(
        (
            (_entry_center(e)[0], _clean_text(e.get("text")))  # type: ignore[index]
            for e in dash_entries
            if isinstance(e, Mapping) and _entry_center(e) is not None and "/" in _clean_text(e.get("text"))
        ),
        key=lambda item: item[0],
    )
    ratios: list[tuple[int, int]] = []
    for _, txt in dash_items:
        m = _RATIO_RE.search(txt)
        if m:
            ratios.append((int(m.group(1)), int(m.group(2))))
    if len(ratios) >= 1:
        out["help_remaining"], out["help_max"] = ratios[0]
        out["help_remaining_known"] = True
    if len(ratios) >= 2:
        out["clean_remaining"], out["clean_max"] = ratios[1]
        out["clean_remaining_known"] = True

    best_name_key: tuple[float, int] | None = None
    for e in info_entries:
        if not isinstance(e, Mapping):
            continue
        score = _entry_score(e)
        if score < 0.5:
            continue
        txt = _clean_text(e.get("text"))
        if (
            not txt
            or "总点赞" in txt
            or txt.isdigit()
            or _LV_RE.search(txt)
            or _LENIENT_LV_RE.search(txt)
            or not re.search(r"[\w\u4e00-\u9fff]", txt)
        ):
            continue
        pt = _entry_center(e)
        if pt is not None and pt[0] >= 90 and pt[1] >= 645:
            cand_key = (score, len(txt))
            if best_name_key is None or cand_key > best_name_key:
                best_name_key = cand_key
                out["friend_name"] = txt

    cnt_txt = _joined(counts_entries)
    m_mon = re.search(r"[xX×]?\s*(\d+)", cnt_txt)
    if m_mon:
        out["active_monsters"] = int(m_mon.group(1))

    for e in bottom_entries:
        if not isinstance(e, Mapping):
            continue
        txt = _clean_text(e.get("text"))
        pt = _entry_center(e)
        if pt is None:
            continue
        if "清扫" in txt:
            out["clean_point"] = pt
        elif "点赞" in txt:
            out["like_point"] = pt
        elif "下一位" in txt:
            out["next_point"] = pt
    return out


# ==============================================================================
# 纯 NumPy 沙滩红叹号 !! 野怪检出（适配任意 16:9 截图，输出 720p 坐标）
# ==============================================================================


def _in_excluded_zone(cx: int, cy: int, zones: Sequence[tuple[int, int, int, int]]) -> bool:
    return any(x <= cx <= x + w and y <= cy <= y + h for x, y, w, h in zones)


def detect_island_monster_tap_points(
    image: Any,
    *,
    excluded_zones: Sequence[tuple[int, int, int, int]] = ISLAND_MONSTER_EXCLUDED_ZONES,
) -> list[tuple[int, int]]:
    """检测海岛沙滩上的珊瑚红 `[!!]` 徽章，返回下方怪物的安全点击点（720p 逻辑坐标）。"""
    if not isinstance(image, np.ndarray) or image.ndim < 3 or image.shape[0] <= 0 or image.shape[1] <= 0:
        return []
    h_img, w_img = image.shape[:2]
    sx = 1280.0 / float(w_img)
    sy = 720.0 / float(h_img)

    # 下采样至接近 640x360，并换算为 720p 逻辑像素面积以消除 720p/1080p/1440p 尺度偏差
    step = max(1, int(round(w_img / 640.0)))
    cell_area_720 = (step * sx) * (step * sy)
    sub = image[::step, ::step, :3]
    b = sub[:, :, 0].astype(np.int16)
    g = sub[:, :, 1].astype(np.int16)
    r = sub[:, :, 2].astype(np.int16)

    # 珊瑚粉红 [!!] 徽章精确色彩掩码，排除西瓜/红木/救生圈与低饱和粉发噪声
    red_mask = (
        (r >= 220)
        & (g >= 90)
        & (g <= 165)
        & (b >= 85)
        & (b <= 165)
        & (np.abs(g - b) <= 28)
        & ((r - g) >= 75)
        & ((r - b) >= 75)
    )
    white_mask = (r >= 230) & (g >= 230) & (b >= 230)

    ys, xs = np.where(red_mask)
    if ys.size == 0:
        return []

    sh, sw = red_mask.shape
    visited = np.zeros((sh, sw), dtype=bool)
    candidates: list[tuple[int, int, int, int]] = []

    for sy0, sx0 in zip(ys.tolist(), xs.tolist()):
        if visited[sy0, sx0]:
            continue
        stack = [(sy0, sx0)]
        visited[sy0, sx0] = True
        pixels = 0
        min_x = max_x = sx0
        min_y = max_y = sy0
        while stack:
            cy_s, cx_s = stack.pop()
            pixels += 1
            if cx_s < min_x:
                min_x = cx_s
            if cx_s > max_x:
                max_x = cx_s
            if cy_s < min_y:
                min_y = cy_s
            if cy_s > max_y:
                max_y = cy_s
            for ny in range(max(0, cy_s - 1), min(sh, cy_s + 2)):
                for nx in range(max(0, cx_s - 1), min(sw, cx_s + 2)):
                    if not visited[ny, nx] and red_mask[ny, nx]:
                        visited[ny, nx] = True
                        stack.append((ny, nx))

        area_720 = pixels * cell_area_720
        if area_720 < 250.0 or area_720 > 12000.0:
            continue
        bw = (max_x - min_x + 1) * step * sx
        bh = (max_y - min_y + 1) * step * sy
        if bw < 20.0 or bh < 20.0 or bw > 140.0 or bh > 140.0:
            continue
        aspect = bw / max(1.0, bh)
        if aspect < 0.55 or aspect > 1.55:
            continue

        # 仅统计徽章内圈白色感叹号，避免外角天空云朵误充数
        ix0 = min_x + max(1, (max_x - min_x) // 6)
        ix1 = max_x - max(1, (max_x - min_x) // 6) + 1
        iy0 = min_y + max(1, (max_y - min_y) // 6)
        iy1 = max_y - max(1, (max_y - min_y) // 5) + 1
        inner_white = int(white_mask[iy0:iy1, ix0:ix1].sum()) if (ix1 > ix0 and iy1 > iy0) else 0
        if inner_white * cell_area_720 < 36.0:
            continue

        total_box_px = max(1, (max_x - min_x + 1) * (max_y - min_y + 1))
        fill_ratio = float(pixels + inner_white) / float(total_box_px)
        if fill_ratio < 0.52:
            continue

        badge_cx = int(round(((min_x + max_x) / 2.0) * step * sx))
        badge_cy = int(round(((min_y + max_y) / 2.0) * step * sy))
        if _in_excluded_zone(badge_cx, badge_cy, excluded_zones):
            continue
        tap_x = min(1240, max(40, badge_cx))
        tap_y = min(555, max(120, int(round(badge_cy + bh * 1.25))))
        if _in_excluded_zone(tap_x, tap_y, excluded_zones):
            tap_y = badge_cy
        is_edge = 0 if 110 <= badge_cx <= 1160 else 1
        candidates.append((is_edge, abs(badge_cx - 640), tap_x, tap_y))

    candidates.sort(key=lambda item: (item[0], item[1]))
    deduped: list[tuple[int, int]] = []
    for _, _, tx, ty in candidates:
        if any(abs(tx - ox) <= 28 and abs(ty - oy) <= 28 for ox, oy in deduped):
            continue
        deduped.append((tx, ty))
    return deduped
