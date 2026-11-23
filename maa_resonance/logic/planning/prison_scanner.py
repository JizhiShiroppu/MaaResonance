from __future__ import annotations

import math
from pathlib import Path
import re
from typing import Any, Iterable, Mapping, Optional, Sequence

from maa_resonance.logic.planning.account_snapshot import PrisonOrder
from maa_resonance.logic.planning.catalogs import load_prison_strategy_catalog
from maa_resonance.logic.planning.growth_planner import GrowthPlanReport
from maa_resonance.logic.planning.prison_executor import PrisonExecutionPlan, PrisonRunReceipt
from maa_resonance.logic.planning.prison_planner import PrisonPlanReport

# 1280x720 整顿中心及相关页面关键坐标与宽容 OCR 区域（依据 LV2 / LV7 真机换算）
PRISON_TOP_BAR_ROI: tuple[int, int, int, int] = (0, 0, 1280, 96)
PRISON_OVERVIEW_GRID_ROI: tuple[int, int, int, int] = (0, 88, 1280, 565)
PRISON_BOTTOM_DOCK_ROI: tuple[int, int, int, int] = (0, 555, 760, 150)

PRISON_BACK_POINT: tuple[int, int] = (75, 40)
PRISON_DOCK_WAREHOUSE_FALLBACK: tuple[int, int] = (73, 610)
PRISON_DOCK_ORDERS_FALLBACK: tuple[int, int] = (163, 610)
PRISON_DOCK_SHOP_FALLBACK: tuple[int, int] = (430, 616)

PRISON_PAN_SWIPES: tuple[tuple[str, tuple[int, int], tuple[int, int]], ...] = (
    ("top_left", (360, 220), (960, 500)),
    ("top_right", (960, 300), (300, 300)),
    ("bottom_right", (960, 540), (360, 180)),
    ("bottom_left", (300, 360), (960, 360)),
)

WAREHOUSE_TOP_BAR_ROI: tuple[int, int, int, int] = (240, 0, 1040, 96)
WAREHOUSE_BODY_ROI: tuple[int, int, int, int] = (0, 85, 1280, 580)

ORDERS_HEADER_ROI: tuple[int, int, int, int] = (0, 0, 1280, 145)
ORDERS_BODY_ROI: tuple[int, int, int, int] = (0, 115, 1280, 575)

PRISON_DOCK_KEYWORDS: tuple[str, ...] = (
    "仓库",
    "订单",
    "采购",
    "生活技能",
    "兑换",
    "拼单单",
)

PRISON_EXCLUSIVE_DOCK_KEYWORDS: tuple[str, ...] = (
    "订单",
    "采购",
    "生活技能",
    "兑换",
)

LEFT_DRAWER_EXCLUSION_KEYWORDS: tuple[str, ...] = (
    "制造加工",
    "列车配置",
    "好友",
    "编队",
    "UID",
    "资产",
)

PRISON_INTERIOR_TOP_EXCLUSIONS: tuple[str, ...] = (
    "整顿宿舍",
    "已解锁床位",
    "生产车间",
    "原料车间",
    "一键全选",
)

PRISON_INTERIOR_DOCK_EXCLUSIONS: tuple[str, ...] = (
    "宿舍导航",
    "已解锁生活区域",
    "下一区场",
    "下一区域",
)

LOCKED_HINTS: tuple[str, ...] = (
    "未解锁",
    "暂未解锁",
    "尚未解锁",
    "可解锁",
    "未开启",
    "需整顿",
    "需研发",
    "整顿中心等级",
    "研发中心等级",
    "需达到",
    "解锁条件",
)

REQUIREMENT_LABEL_HINTS: tuple[str, ...] = (
    "等级",
    "整顿中心等级",
    "研发中心等级",
    "需达到",
    "解锁条件",
)

KNOWN_EXTRA_PRISON_GOODS: tuple[str, ...] = (
    "阿妮塔连体衣",
    "普通布袋",
    "丝绸布料",
    "丝绸",
    "天鹅绒",
    "织锦缎",
    "锦缎",
    "高级女装",
    "防弹背心",
    "抗污染防护服",
    "宇航服",
    "雪金锦袍",
    "岚心锦服",
    "天鹅绒椅披",
    "手工编织地毯",
    "真丝羽绒枕头",
    "花呢",
    "蕾丝花边",
    "西服面料",
    "金丝",
    "绣线",
    "缝纫工具包",
)

ORDER_UI_STOPWORDS: frozenset[str] = frozenset(
    {
        "黑月服装订单站",
        "运输订单",
        "每周订单",
        "每日订单",
        "全部",
        "交付",
        "删除",
        "刷新",
        "记录",
        "再交涉请求书",
        "铁盟币",
        "整顿中心经验",
        "整顿中心工票",
        "工票",
        "经验",
        "奖励",
        "需求物资",
    }
)


def _clean_text(value: Any) -> str:
    return "".join(str(value or "").split()).strip()


def _entry_box(entry: Mapping[str, Any]) -> tuple[int, int, int, int] | None:
    box = entry.get("box")
    if isinstance(box, (list, tuple)) and len(box) >= 4:
        try:
            return int(box[0]), int(box[1]), int(box[2]), int(box[3])
        except (TypeError, ValueError):
            return None
    if isinstance(box, Mapping):
        try:
            return (
                int(box.get("x", 0) or 0),
                int(box.get("y", 0) or 0),
                int(box.get("w", box.get("width", 0)) or 0),
                int(box.get("h", box.get("height", 0)) or 0),
            )
        except (TypeError, ValueError):
            return None
    if all(k in entry for k in ("x", "y", "w", "h")):
        try:
            return int(entry["x"]), int(entry["y"]), int(entry["w"]), int(entry["h"])
        except (TypeError, ValueError):
            return None
    if "center_x" in entry and "center_y" in entry:
        try:
            cx = int(round(float(entry["center_x"])))
            cy = int(round(float(entry["center_y"])))
            return cx - 20, cy - 12, 40, 24
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


def _merge_horizontal_adjacent(
    entries: Sequence[Mapping[str, Any]],
    *,
    max_gap_x: int = 34,
    max_row_diff: Optional[float] = None,
) -> list[dict[str, Any]]:
    """合并同一行相近的 OCR 拆字片段（如 'LV' + '7'、'整顿中心等级' + 'LV11'）。"""
    items: list[tuple[int, int, int, int, str]] = []
    for entry in entries:
        if not isinstance(entry, Mapping):
            continue
        text = _clean_text(entry.get("text"))
        if not text:
            continue
        box = _entry_box(entry)
        if box is None:
            continue
        items.append((*box, text))

    items.sort(key=lambda item: (round(item[1] / 18.0), item[0]))
    merged: list[dict[str, Any]] = []
    for x, y, w, h, text in items:
        if merged:
            prev = merged[-1]
            px, py, pw, ph = prev["box"]
            row_limit = max_row_diff if max_row_diff is not None else max(18.0, min(h, ph) * 0.9)
            same_row = abs((y + h / 2.0) - (py + ph / 2.0)) <= row_limit
            gap_x = x - (px + pw)
            if same_row and -8 <= gap_x <= max_gap_x:
                nx = min(px, x)
                ny = min(py, y)
                nx2 = max(px + pw, x + w)
                ny2 = max(py + ph, y + h)
                prev["text"] = f"{prev['text']}{text}"
                prev["box"] = [nx, ny, nx2 - nx, ny2 - ny]
                continue
        merged.append({"text": text, "box": [x, y, w, h]})
    return merged


def parse_cn_number(text: Any) -> Optional[int]:
    """解析带千分位或 K/M/万/亿 后缀的中文数值写法。"""
    cleaned = _clean_text(text).replace(",", "").replace("，", "")
    if not cleaned:
        return None
    match = re.search(r"(\d+(?:\.\d+)?)\s*([kKmMwW万亿]?)", cleaned)
    if not match:
        return None
    try:
        num = float(match.group(1))
    except ValueError:
        return None
    unit = match.group(2).lower()
    multiplier = {
        "": 1,
        "k": 1_000,
        "m": 1_000_000,
        "w": 10_000,
        "万": 10_000,
        "亿": 100_000_000,
    }.get(unit, 1)
    return int(round(num * multiplier))


def _parse_fraction(text: str) -> Optional[tuple[int, int]]:
    cleaned = _clean_text(text).replace(",", "").replace("，", "")
    match = re.search(r"(\d+)\s*/\s*(\d+)", cleaned)
    if not match:
        return None
    return int(match.group(1)), int(match.group(2))


def is_prison_overview_entries(
    top_entries: Sequence[Mapping[str, Any]],
    dock_entries: Sequence[Mapping[str, Any]],
) -> bool:
    """判定当前界面是否为整顿中心（监狱）总览界面，严防误判左抽屉或 3D 房间内景。"""
    dock_text = "".join(_clean_text(e.get("text")) for e in dock_entries if isinstance(e, Mapping))
    top_text = "".join(_clean_text(e.get("text")) for e in top_entries if isinstance(e, Mapping))
    all_text = f"{top_text}{dock_text}"
    if any(excl in all_text for excl in LEFT_DRAWER_EXCLUSION_KEYWORDS):
        return False
    if any(excl in top_text for excl in PRISON_INTERIOR_TOP_EXCLUSIONS):
        return False
    if any(excl in dock_text for excl in PRISON_INTERIOR_DOCK_EXCLUSIONS):
        return False
    # 左抽屉入口卡本身包含「整顿中心」，整顿中心底栏绝无此词
    if "整顿中心" in dock_text:
        return False

    dock_hits = sum(1 for kw in PRISON_DOCK_KEYWORDS if kw in dock_text)
    if dock_hits >= 2 and any(kw in dock_text for kw in PRISON_EXCLUSIVE_DOCK_KEYWORDS):
        return True
    top_upper = top_text.upper()
    return (
        "LV" in top_upper
        and ("事项" in top_upper or "电力" in top_upper or "整顿" in top_upper)
        and (dock_hits >= 1 or not dock_text)
    )


def find_dock_button_point(
    dock_entries: Sequence[Mapping[str, Any]],
    keywords: Sequence[str],
    fallback: tuple[int, int],
) -> tuple[int, int]:
    """从底部 Dock 识别目标按钮可点击图标中心（文字标签在 y>=645 时自动上移到图标区）。"""
    for entry in dock_entries:
        if not isinstance(entry, Mapping):
            continue
        text = _clean_text(entry.get("text"))
        if not any(kw in text for kw in keywords):
            continue
        box = _entry_box(entry)
        pt = _entry_center(entry)
        # 多个底栏按钮被 OCR 拼成一个宽框时（如「订单站RCA-F02-B采购」），退回已标定图标中心
        if box is not None and box[2] > 80 and len(text) > 5:
            return fallback
        if pt is not None:
            if pt[1] >= 645:
                return pt[0], max(595, pt[1] - 58)
            return pt
    return fallback


def find_city_prison_npc_point(city_entries: Sequence[Mapping[str, Any]]) -> Optional[tuple[int, int]]:
    """在城市页面地标 OCR 中定位「整顿中心」点击点。"""
    for entry in city_entries:
        if not isinstance(entry, Mapping):
            continue
        text = _clean_text(entry.get("text"))
        if "整顿中心" in text and "订单" not in text:
            return _entry_center(entry)
    return None


def is_warehouse_screen_entries(entries: Sequence[Mapping[str, Any]]) -> bool:
    """判定当前界面是否为整顿中心「仓库」页面。"""
    joined = "".join(_clean_text(e.get("text")) for e in entries if isinstance(e, Mapping))
    return ("原料仓库" in joined and "成品仓库" in joined) or ("仓库容量" in joined and "扩容" in joined)


def is_orders_screen_entries(entries: Sequence[Mapping[str, Any]]) -> bool:
    """判定当前界面是否为「黑月服装订单站」页面（兼容英文标题 COLUMBA 艺术字）。"""
    joined = "".join(_clean_text(e.get("text")) for e in entries if isinstance(e, Mapping))
    if "黑月服装订单" in joined or ("运输订单" in joined and "每周订单" in joined):
        return True
    upper = joined.upper()
    return "COLUMBA" in upper and any(kw in joined for kw in ("帮助", "订单", "交付", "删除"))


def find_weekly_orders_tab_point(header_entries: Sequence[Mapping[str, Any]]) -> Optional[tuple[int, int]]:
    """在订单页顶部栏寻找「每周订单」页签中心点。"""
    for entry in header_entries:
        if not isinstance(entry, Mapping):
            continue
        text = _clean_text(entry.get("text"))
        if "每周订单" in text or text == "每周":
            return _entry_center(entry)
    return None


def parse_prison_top_bar(entries: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """解析整顿中心顶栏等级、经验、囚犯数、电力及可选资产字段。"""
    combined = list(entries) + _merge_horizontal_adjacent(entries)
    result: dict[str, Any] = {}

    for entry in combined:
        if not isinstance(entry, Mapping):
            continue
        text = _clean_text(entry.get("text"))
        if not text:
            continue
        center = _entry_center(entry)
        cx = center[0] if center else 0

        if "level" not in result:
            lv_match = re.search(r"(?:LV|Lv|lv)\.?\s*(\d{1,3})", text)
            if lv_match:
                result["level"] = int(lv_match.group(1))

        if "work_tickets" not in result and ("工票" in text):
            num = parse_cn_number(text.split("工票", 1)[-1])
            if num is not None:
                result["work_tickets"] = num

        if "coins" not in result and ("铁盟币" in text):
            num = parse_cn_number(text.split("铁盟币", 1)[-1])
            if num is not None:
                result["coins"] = num

        frac = _parse_fraction(text)
        if frac is None:
            continue
        cur, cap = frac
        if ("电力" in text or cap >= 1000) and "power_max" not in result:
            result["power_used"] = cur
            result["power_max"] = cap
        elif ("囚犯" in text or (cx >= 580 and cap <= 300)) and "prisoners_capacity" not in result:
            result["prisoners_current"] = cur
            result["prisoners_capacity"] = cap
        elif (cx < 580 or "经验" in text) and "exp_next" not in result and cap > 0:
            result["exp"] = cur
            result["exp_next"] = cap

    return result


def _building_keyword_pairs(catalog: Optional[dict[str, Any]] = None) -> list[tuple[str, str]]:
    strategy = catalog if isinstance(catalog, dict) else load_prison_strategy_catalog()
    bcat = strategy.get("building_catalog") if isinstance(strategy.get("building_catalog"), dict) else {}
    pairs: list[tuple[str, str]] = []
    for bid, info in bcat.items():
        if not isinstance(info, Mapping):
            continue
        names = [info.get("name"), *(info.get("aliases") or ())]
        for raw_name in names:
            clean = _clean_text(raw_name)
            if len(clean) >= 2:
                pairs.append((clean, str(bid)))
    pairs.sort(key=lambda pair: len(pair[0]), reverse=True)
    return pairs


def _has_any_hint(text: str, hints: Sequence[str]) -> bool:
    return any(hint in text for hint in hints)


def parse_prison_grid_buildings(
    entries: Sequence[Mapping[str, Any]],
    *,
    catalog: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """解析单屏整顿中心四翼网格中的建筑解锁状态、等级与宿舍/车间数量。"""
    keyword_pairs = _building_keyword_pairs(catalog)
    filtered_entries: list[Mapping[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, Mapping):
            continue
        center = _entry_center(entry)
        if center is None:
            continue
        # 过滤底栏文字区，避免把底栏按钮或状态标签误认作建筑节点
        if center[0] < 560 and center[1] >= 655:
            continue
        filtered_entries.append(entry)

    merged_entries = _merge_horizontal_adjacent(filtered_entries, max_gap_x=24, max_row_diff=14.0)
    normalized_entries: list[tuple[str, tuple[int, int]]] = []
    for entry in merged_entries:
        text = _clean_text(entry.get("text"))
        center = _entry_center(entry)
        if text and center is not None:
            normalized_entries.append((text, center))

    buildings: dict[str, int] = {}
    locked_buildings: set[str] = set()
    unlocked_dorm_indices: set[int] = set()
    unlocked_workshop_indices: set[int] = set()

    for text, (cx, cy) in normalized_entries:
        # 跳过「整顿中心等级LV11 / 研发中心等级LV4」等前置提示条，防止把其中的「研发中心」当成本体建筑
        if _has_any_hint(text, REQUIREMENT_LABEL_HINTS):
            continue

        matched_bid: Optional[str] = None
        dorm_match = re.search(r"([1-6])号整顿宿舍", text)
        workshop_match = re.search(r"([1-6])号生产车间", text)
        if dorm_match:
            matched_bid = "dormitory"
        elif workshop_match:
            matched_bid = "production_workshop"
        else:
            for kw, bid in keyword_pairs:
                if kw in text:
                    matched_bid = bid
                    break

        if matched_bid is None:
            continue

        is_locked = _has_any_hint(text, LOCKED_HINTS)
        detected_level: Optional[int] = None
        if not is_locked:
            inline_lv = re.search(r"(?:LV|Lv|lv)\.?\s*(\d{1,2})", text)
            if inline_lv:
                detected_level = int(inline_lv.group(1))

        best_lv_dist = 10_000.0
        for nb_text, (nx, ny) in normalized_entries:
            dx = abs(nx - cx)
            dy = ny - cy
            # 同一水平行放宽 dx<=165；正下方锁定/等级副标签收紧到 dx<=95, 0<=dy<=60 防止邻列误伤
            same_row = abs(dy) <= 18 and dx <= 165
            directly_below = 0 <= dy <= 60 and dx <= 95
            if not (same_row or directly_below):
                continue
            if _has_any_hint(nb_text, LOCKED_HINTS):
                is_locked = True
                continue
            if "等级" in nb_text:
                continue
            lv_m = re.search(r"(?:LV|Lv|lv)\.?\s*(\d{1,2})", nb_text)
            if lv_m and (dx + abs(dy)) < best_lv_dist:
                best_lv_dist = float(dx + abs(dy))
                detected_level = int(lv_m.group(1))

        if is_locked:
            locked_buildings.add(matched_bid)
            continue

        if dorm_match:
            unlocked_dorm_indices.add(int(dorm_match.group(1)))
        if workshop_match:
            unlocked_workshop_indices.add(int(workshop_match.group(1)))

        lv = max(1, detected_level or 1)
        buildings[matched_bid] = max(buildings.get(matched_bid, 0), lv)

    return {
        "buildings": buildings,
        "locked_buildings": sorted(locked_buildings),
        "unlocked_dorm_indices": sorted(unlocked_dorm_indices),
        "unlocked_workshop_indices": sorted(unlocked_workshop_indices),
    }


def merge_prison_grid_scans(scans: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """合并多视角平移扫描得到的整顿中心建筑与阶梯数量。"""
    buildings: dict[str, int] = {}
    locked: set[str] = set()
    dorm_indices: set[int] = set()
    workshop_indices: set[int] = set()

    for scan in scans:
        if not isinstance(scan, Mapping):
            continue
        for bid, lv in (scan.get("buildings") or {}).items():
            try:
                buildings[str(bid)] = max(buildings.get(str(bid), 0), int(lv))
            except (TypeError, ValueError):
                continue
        for bid in scan.get("locked_buildings") or ():
            locked.add(str(bid))
        for idx in scan.get("unlocked_dorm_indices") or ():
            dorm_indices.add(int(idx))
        for idx in scan.get("unlocked_workshop_indices") or ():
            workshop_indices.add(int(idx))

    # 若在其它视角中确认已解锁并识别到建筑条目，从 locked 中剔除
    for bid in buildings:
        locked.discard(bid)

    result: dict[str, Any] = {
        "buildings": buildings,
        "locked_buildings": sorted(locked),
        "unlocked_dorm_indices": sorted(dorm_indices),
        "unlocked_workshop_indices": sorted(workshop_indices),
    }
    if dorm_indices:
        result["dorm_count"] = len(dorm_indices)
    elif "dormitory" in buildings:
        result["dorm_count"] = 1
    if workshop_indices:
        result["production_workshop_count"] = len(workshop_indices)
    elif "production_workshop" in buildings:
        result["production_workshop_count"] = 1
    return result


def _filter_top_bar_icon_noise(entries: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    """过滤仓库/通用顶栏里高框低字数的图标误识别噪点（如高度>=34px 的单字 '1'/'?'）。"""
    cleaned: list[Mapping[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, Mapping):
            continue
        text = _clean_text(entry.get("text"))
        if not text:
            continue
        box = _entry_box(entry)
        if box is not None and box[3] >= 34 and len(text) <= 2:
            continue
        cleaned.append(entry)
    return cleaned


def parse_warehouse_screen(
    top_entries: Sequence[Mapping[str, Any]],
    body_entries: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """只读解析整顿中心「仓库」页面中的两仓库存占用、铁盟币、桦石与工票。"""
    result: dict[str, Any] = {}
    clean_top_entries = _filter_top_bar_icon_noise(top_entries)
    all_entries = _merge_horizontal_adjacent(list(clean_top_entries) + list(body_entries))

    def _nearest_fraction_for(keyword: str) -> Optional[tuple[int, int]]:
        anchors: list[tuple[int, int, str]] = []
        fracs: list[tuple[int, int, tuple[int, int]]] = []
        for entry in all_entries:
            text = _clean_text(entry.get("text"))
            center = _entry_center(entry)
            if not text or center is None:
                continue
            if keyword in text:
                inline = _parse_fraction(text)
                if inline is not None:
                    return inline
                anchors.append((center[0], center[1], text))
            f = _parse_fraction(text)
            if f is not None:
                fracs.append((center[0], center[1], f))
        best: Optional[tuple[float, tuple[int, int]]] = None
        for ax, ay, _ in anchors:
            for fx, fy, frac in fracs:
                dist = math.hypot(fx - ax, fy - ay)
                if dist <= 260.0 and (best is None or dist < best[0]):
                    best = (dist, frac)
        return best[1] if best else None

    raw_frac = _nearest_fraction_for("原料仓库")
    if raw_frac is not None:
        result["raw_warehouse_used"], result["raw_warehouse_cap"] = raw_frac

    fin_frac = _nearest_fraction_for("成品仓库")
    if fin_frac is not None:
        result["finished_warehouse_used"], result["finished_warehouse_cap"] = fin_frac

    # 顶栏资产解析：先滤除高框单字图标噪点并使用紧邻参数合并，防铁盟币粘上相邻图标数字
    merged_top = _merge_horizontal_adjacent(clean_top_entries, max_gap_x=10, max_row_diff=12.0)
    unlabeled_nums: list[tuple[int, int]] = []
    for entry in merged_top:
        text = _clean_text(entry.get("text"))
        center = _entry_center(entry)
        if not text or center is None:
            continue
        if "铁盟币" in text or "金币" in text:
            val = parse_cn_number(text)
            if val is not None:
                result["coins"] = val
            continue
        if "桦石" in text:
            val = parse_cn_number(text)
            if val is not None:
                result["huashi"] = val
            continue
        if "工票" in text:
            val = parse_cn_number(text)
            if val is not None:
                result["work_tickets"] = val
            continue
        if "/" in text:
            continue
        val = parse_cn_number(text)
        if val is not None:
            unlabeled_nums.append((center[0], val))

    # 无文字标签的纯图标顶栏（常见左->右：[铁盟币, 桦石, 工票] 或 [铁盟币, 桦石]）
    if unlabeled_nums:
        unlabeled_nums.sort(key=lambda pair: pair[0])
        vals = [v for _, v in unlabeled_nums]
        if "coins" not in result:
            large_candidates = [v for v in vals if v >= 100_000]
            if large_candidates:
                result["coins"] = max(large_candidates)
        remaining_vals = [v for v in vals if v != result.get("coins")]
        if len(remaining_vals) >= 2:
            if "huashi" not in result:
                result["huashi"] = remaining_vals[0]
            if "work_tickets" not in result:
                result["work_tickets"] = remaining_vals[1]
        elif len(remaining_vals) == 1 and "huashi" not in result:
            result["huashi"] = remaining_vals[0]

    return result


def _known_order_item_names(catalog: Optional[dict[str, Any]] = None) -> list[str]:
    strategy = catalog if isinstance(catalog, dict) else load_prison_strategy_catalog()
    names: set[str] = set(KNOWN_EXTRA_PRISON_GOODS)
    for item in strategy.get("rush_leveling_goods") or ():
        if isinstance(item, Mapping) and item.get("name"):
            names.add(str(item["name"]).strip())
    for item in strategy.get("profit_harvest_goods") or ():
        if isinstance(item, Mapping) and item.get("name"):
            names.add(str(item["name"]).strip())
    return sorted((n for n in names if n), key=len, reverse=True)


def _match_order_quantity_token(text: str) -> Optional[tuple[int, int]]:
    frac = _parse_fraction(text)
    if frac is not None and 1 <= frac[1] <= 10_000:
        return frac
    cleaned = _clean_text(text).replace(",", "").replace("，", "")
    qty_match = re.search(r"[xX×\*：:]\s*(\d{2,4})$", cleaned)
    if qty_match:
        return 0, int(qty_match.group(1))
    return None


def parse_orders_screen(
    header_entries: Sequence[Mapping[str, Any]],
    body_entries: Sequence[Mapping[str, Any]],
    *,
    order_type: str = "daily",
    catalog: Optional[dict[str, Any]] = None,
) -> list[PrisonOrder]:
    """只读解析黑月服装订单站可见订单（货物名、需求量与当前持仓）。"""
    resolved_type = "weekly" if order_type == "weekly" else "daily"
    if resolved_type == "daily":
        header_text = "".join(_clean_text(e.get("text")) for e in header_entries if isinstance(e, Mapping))
        if "每周订单" in header_text and "运输订单" not in header_text:
            resolved_type = "weekly"

    known_names = _known_order_item_names(catalog)
    merged_body = _merge_horizontal_adjacent(body_entries)
    qty_tokens: list[tuple[int, int, int, int, str]] = []
    name_tokens: list[tuple[str, int, int, Optional[tuple[int, int]]]] = []

    for entry in merged_body:
        text = _clean_text(entry.get("text"))
        center = _entry_center(entry)
        if not text or center is None:
            continue
        cx, cy = center
        qty_pair = _match_order_quantity_token(text)
        matched_name = next((name for name in known_names if name in text), None)
        if matched_name is not None:
            name_tokens.append((matched_name, cx, cy, qty_pair))
            continue
        if re.fullmatch(r"[\u4e00-\u9fff]{2,8}", text) and text not in ORDER_UI_STOPWORDS:
            # 对目录尚未收录的新成品名保留保守中文词匹配（必须与数量框近距配对才生效）
            name_tokens.append((text, cx, cy, None))

        if qty_pair is not None:
            qty_tokens.append((cx, cy, qty_pair[0], qty_pair[1], text))

    orders: list[PrisonOrder] = []
    seen: set[tuple[str, int, str]] = set()
    used_qty_indices: set[int] = set()

    for name, nx, ny, inline_qty in name_tokens:
        stock_owned = 0
        req_qty = 0
        if inline_qty is not None:
            stock_owned, req_qty = inline_qty
        else:
            best_idx: Optional[int] = None
            best_dist = 10_000.0
            for idx, (qx, qy, q_stock, q_req, _) in enumerate(qty_tokens):
                if idx in used_qty_indices:
                    continue
                if abs(qx - nx) > 260 or abs(qy - ny) > 150:
                    continue
                dist = math.hypot(qx - nx, qy - ny)
                if dist < best_dist:
                    best_dist = dist
                    best_idx = idx
            if best_idx is None:
                continue
            used_qty_indices.add(best_idx)
            _, _, stock_owned, req_qty, _ = qty_tokens[best_idx]

        key = (name, req_qty, resolved_type)
        if req_qty <= 0 or key in seen:
            continue
        seen.add(key)
        orders.append(
            PrisonOrder(
                item_name=name,
                quantity=req_qty,
                order_type=resolved_type,  # type: ignore[arg-type]
                stock_owned=stock_owned,
            )
        )
    return orders


def parse_target_crews_text(raw_text: str) -> list[str]:
    """解析 MXU 输入框中的乘员名单（逗号/顿号/换行分隔并去重）。"""
    seen: set[str] = set()
    names: list[str] = []
    for part in re.split(r"[,，、;\n\r]+", str(raw_text or "")):
        clean = part.strip()
        if clean and clean not in seen:
            seen.add(clean)
            names.append(clean)
    return names


def parse_drawer_clarity(drawer_entries: Sequence[Mapping[str, Any]]) -> Optional[int]:
    """从左抽屉顶部资产区解析当前澄明度数值（按 X 坐标优先取最左侧的澄明度，如 '57/292+' -> 57）。"""
    candidates: list[tuple[int, int]] = []
    for entry in drawer_entries:
        if not isinstance(entry, Mapping):
            continue
        center = _entry_center(entry)
        if center is not None and center[1] >= 360:
            continue
        text = _clean_text(entry.get("text"))
        if not text:
            continue
        frac = _parse_fraction(text)
        if frac is None:
            continue
        cur, cap = frac
        if cap >= 60 and 0 <= cur <= 9999:
            cx = center[0] if center is not None else 0
            candidates.append((cx, cur))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0])
    return candidates[0][1]


def parse_drawer_wallet(drawer_entries: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    """从左抽屉顶部「资产」栏解析铁盟币、桦石与澄明度（未扫到某项时不写入）。"""
    result: dict[str, int] = {}
    clarity = parse_drawer_clarity(drawer_entries)
    if clarity is not None:
        result["clarity_estimate"] = clarity

    asset_y: Optional[int] = None
    for entry in drawer_entries:
        if not isinstance(entry, Mapping):
            continue
        text = _clean_text(entry.get("text"))
        center = _entry_center(entry)
        if "资产" in text and center is not None:
            asset_y = center[1]
            break

    coin_candidates: list[tuple[int, int]] = []
    huashi_candidates: list[tuple[int, int]] = []
    for entry in drawer_entries:
        if not isinstance(entry, Mapping):
            continue
        center = _entry_center(entry)
        if center is None:
            continue
        cx, cy = center
        if asset_y is not None:
            if abs(cy - asset_y) > 24:
                continue
        elif not (185 <= cy <= 240):
            continue
        if not (145 <= cx <= 560):
            continue
        text = _clean_text(entry.get("text"))
        upper = text.upper()
        if not text or "/" in text or "LV" in upper or "UID" in upper:
            continue
        val = parse_cn_number(text)
        if val is None:
            continue
        if cx < 350:
            coin_candidates.append((cx, val))
        else:
            huashi_candidates.append((cx, val))

    if coin_candidates:
        coin_candidates.sort(key=lambda item: (-item[1], item[0]))
        result["coins"] = coin_candidates[0][1]
    if huashi_candidates:
        huashi_candidates.sort(key=lambda item: item[0])
        result["huashi"] = huashi_candidates[0][1]
    return result


def _short_coin_str(amount: int) -> str:
    if amount >= 100_000_000:
        return f"{amount / 100_000_000:.2f}亿"
    if amount >= 10_000:
        return f"{amount // 10_000:,}万"
    return f"{amount:,}"


_SHORT_BUILDING_NAMES: dict[str, str] = {
    "research_center": "研发中心",
    "power_center": "电力中心",
    "raw_sewing": "缝纫原料",
    "raw_synthetic": "人造原料",
    "raw_plant": "植物原料",
    "raw_animal": "动物原料",
    "dormitory": "宿舍/车间",
    "transfer_center": "转运中心",
    "confinement_room": "禁闭室",
    "infirmary": "医务室",
}


def _short_building_step(rec: Any) -> str:
    short_name = _SHORT_BUILDING_NAMES.get(rec.building_id, rec.name)
    action = str(rec.action or "")
    if rec.building_id == "dormitory":
        if rec.priority == "warning":
            return f"{short_name}(勿增)"
        if rec.priority == "high":
            return f"{short_name}(补开)"
    if rec.building_id in ("confinement_room", "infirmary") and rec.priority == "blocker":
        return f"{short_name}(建LV1)"
    lv_match = re.search(r"LV(\d+)(?:[^→\d]*→[^L\d]*(?:先冲\s*)?(?:LV)?(\d+))?", action)
    if lv_match:
        cur_lv, nxt_lv = lv_match.group(1), lv_match.group(2)
        if nxt_lv:
            return f"{short_name}(LV{cur_lv}→{nxt_lv})"
        return f"{short_name}(LV{cur_lv})"
    return short_name


def _ladder_short_tag(prison_report: PrisonPlanReport) -> str:
    dorm_n = prison_report.dorm_count
    ws_n = prison_report.production_workshop_count
    cap_n = prison_report.recommended_dorm_and_workshop_cap
    next_lv = prison_report.next_ladder_unlock_level
    if dorm_n > cap_n or ws_n > cap_n:
        return f"超上限{cap_n}勿增"
    if dorm_n < cap_n or ws_n < cap_n:
        return f"未满上限{cap_n}可补开"
    if next_lv is not None:
        return f"LV{next_lv}开下套"
    return "已满6套"


def _fallback_produce_targets(prison_report: PrisonPlanReport) -> list[str]:
    strategy = load_prison_strategy_catalog()
    if prison_report.phase == "profit_harvest":
        return [
            str(item.get("name") or "")
            for item in (strategy.get("profit_harvest_goods") or ())[:3]
            if isinstance(item, Mapping) and item.get("name")
        ]
    eff_lv = max(1, int(prison_report.prison_level))
    items = [
        item
        for item in (strategy.get("rush_leveling_goods") or ())
        if isinstance(item, Mapping)
        and int(item.get("guide_index") or 1) <= eff_lv
        and bool(item.get("daily_recommended", True))
        and not (eff_lv >= 20 and bool(item.get("early_only_overflow_risk", False)))
    ]
    items.sort(
        key=lambda g: (
            1 if bool(g.get("defer_until_surplus", False)) else 0,
            -int(g.get("rating") if g.get("rating") is not None else 1),
            int(g.get("guide_index") or 99),
        )
    )
    return [str(item.get("name") or "") for item in items[:3] if item.get("name")]


def format_mxu_plain_summary(
    prison_report: PrisonPlanReport,
    growth_report: Optional[GrowthPlanReport | Path] = None,
    report_path: Optional[Path] = None,
    *,
    execution_plan: Optional[PrisonExecutionPlan] = None,
    run_receipt: Optional[PrisonRunReceipt] = None,
    semi_auto_guides: Optional[Sequence[Any]] = None,
    issue_bundle_path: Optional[Path] = None,
) -> list[str]:
    """生成适配 MXU 右侧窄日志栏的精简短行摘要（默认纯监狱 6 行）。"""
    if isinstance(growth_report, Path) and report_path is None:
        report_path = growth_report
        growth_report = None

    phase_short = "冲级期" if prison_report.phase == "rush_leveling" else "毕业赚钱期"
    title_tag = "整顿中心（实验型）" if growth_report is None else "整顿与养成规划"
    lines = [
        f"【{title_tag}】UID {prison_report.uid} · LV{prison_report.prison_level}（{phase_short}）",
        (
            f"资产：可用 {_short_coin_str(prison_report.spendable_coins)}币"
            f"（底线{_short_coin_str(prison_report.reserve_coins)}）| "
            f"{prison_report.huashi_total:,}桦石 | {prison_report.work_tickets:,}工票"
        ),
    ]

    high_recs = [r for r in prison_report.building_recommendations if r.priority in ("blocker", "high")]
    build_steps = " / ".join(_short_building_step(r) for r in high_recs[:3]) if high_recs else "按阶梯稳步维护"
    lines.append(
        f"造什么：{build_steps}（宿舍/车间 {prison_report.dorm_count}/{prison_report.production_workshop_count} · {_ladder_short_tag(prison_report)}）"
    )

    do_parts: list[str] = []
    if prison_report.order_decisions:
        ods = prison_report.order_decisions
        n_del = sum(1 for o in ods if o.action == "deliver")
        n_prod = sum(1 for o in ods if o.action == "produce_then_deliver")
        n_free = sum(1 for o in ods if o.action in ("delete_free", "skip_weekly", "skip_profit_phase"))
        do_parts.append(f"黑月直交{n_del}/排产{n_prod}/免费删{n_free}")

    if execution_plan is not None:
        prod_targets = [s.target for s in execution_plan.do_actions if s.allowed and s.action_type == "produce_good"][:3]
    else:
        prod_targets = _fallback_produce_targets(prison_report)
    if prod_targets:
        do_parts.append(f"轮换造 {'/'.join(prod_targets)}")
    elif not do_parts:
        do_parts.append("按高效白名单轮换排产")
    lines.append(f"做什么：{'；'.join(do_parts)}")

    huashi_guarded = all(g.status != "opt_in_enabled" for g in prison_report.guarded_huashi_actions)
    guard_note = "零桦石保护已开" if huashi_guarded else "已放行指定桦石项"
    buy_parts: list[str] = []
    if execution_plan is not None:
        allowed_buys = [s for s in execution_plan.buy_actions if s.allowed]
        if any(s.action_type == "warehouse_coin_expand" for s in allowed_buys):
            buy_parts.append("仓库仅点铁盟币扩容")
        else:
            buy_parts.append("资金触底暂缓扩仓")
        ticket_buys = [s.target for s in allowed_buys if s.action_type == "exchange_ticket_buy"]
        if ticket_buys:
            buy_parts.append(f"工票兑{'/'.join(ticket_buys[:2])}")
        else:
            buy_parts.append("工票留换配方/拉普拉斯/胶卷")
        if any(s.action_type == "purchase_convert" for s in allowed_buys):
            buy_parts.append("采购安全转换")
    else:
        buy_parts.append("仓库仅点铁盟币扩容")
        buy_parts.append("工票留换配方/拉普拉斯/胶卷")
    lines.append(f"买什么：{'；'.join(buy_parts)}（{guard_note}）")

    if growth_report is not None and growth_report.stage_allocations:
        stages_short = " → ".join(f"{s.stage_name}×{s.runs}" for s in growth_report.stage_allocations[:4])
        lines.append(f"{growth_report.weekday_name}体力：{stages_short}（+{growth_report.expected_total_prisoners}囚犯）")

    if run_receipt is not None and run_receipt.mode == "execute_safe_auto":
        spent_coins = max(0, int(run_receipt.coins_before) - int(run_receipt.coins_after))
        spent_tickets = max(0, int(run_receipt.tickets_before) - int(run_receipt.tickets_after))
        spent_huashi = max(0, int(run_receipt.huashi_before) - int(run_receipt.huashi_after))
        lines.append(
            f"本次执行：完成 {len(run_receipt.executed)} 项 / 跳过 {len(run_receipt.skipped)} 项 / "
            f"护栏拦截 {len(run_receipt.guard_aborts)} 项（花币 {_short_coin_str(spent_coins)}、工票 {spent_tickets:,}、桦石 {spent_huashi:,}）"
        )

    guides = (
        list(semi_auto_guides)
        if semi_auto_guides is not None
        else (list(run_receipt.semi_auto_guides) if run_receipt is not None and getattr(run_receipt, "semi_auto_guides", None) else [])
    )
    if guides:
        pri_map = {"urgent": "优先", "recommended": "建议", "optional": "可选"}
        for g_idx, guide in enumerate(guides[:2]):
            if isinstance(guide, Mapping):
                pri = str(guide.get("priority") or "recommended")
                title = str(guide.get("title") or "")
                g_steps = list(guide.get("steps") or ())
                why = str(guide.get("why_manual") or "")
            else:
                pri = str(getattr(guide, "priority", "recommended"))
                title = str(getattr(guide, "title", ""))
                g_steps = list(getattr(guide, "steps", ()) or ())
                why = str(getattr(guide, "why_manual", ""))
            first_step = str(g_steps[0]).rstrip("。；") if g_steps else why
            prefix_idx = f"#{g_idx + 1}" if len(guides) > 1 else ""
            lines.append(f"手动接力{prefix_idx}[{pri_map.get(pri, pri)}]：{title}（{first_step}）")

    report_name = report_path.name if report_path is not None else "latest_report.html"
    lines.append(f"详细看板：{report_name}（config/planning/）")
    if issue_bundle_path is not None:
        if issue_bundle_path.suffix.lower() == ".zip":
            lines.append(f"排错日志：{issue_bundle_path.name}（config/planning/logs/，提Issue请附此包）")
        else:
            lines.append(f"排错日志：{issue_bundle_path.name}（config/planning/logs/）")
    return lines
