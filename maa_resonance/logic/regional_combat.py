"""Pure logic and pixel/OCR helpers for Regional Combat Center (区域作战中心) auto-combat."""
from __future__ import annotations

import re
from typing import Any

import numpy as np

# 1280x720 ROIs and interaction coordinates verified against live Regional Combat screens.
REGIONAL_CITY_LIST_ROI: tuple[int, int, int, int] = (25, 70, 445, 645)
REGIONAL_CITY_SWIPE_DOWN: tuple[int, int, int, int] = (220, 580, 220, 170)
REGIONAL_CITY_SWIPE_UP: tuple[int, int, int, int] = (220, 170, 220, 580)

REGIONAL_BANNER_ROI: tuple[int, int, int, int] = (520, 130, 740, 235)
REGIONAL_STAGE_TITLE_ROI: tuple[int, int, int, int] = (550, 405, 420, 55)
REGIONAL_DIFF_BTN_ROI: tuple[int, int, int, int] = (960, 400, 260, 80)
REGIONAL_ENEMY_LEVEL_ROI: tuple[int, int, int, int] = (980, 525, 220, 42)
REGIONAL_FIGHT_BTN_ROI: tuple[int, int, int, int] = (950, 560, 265, 65)
REGIONAL_FIRST_CLEAR_ROI: tuple[int, int, int, int] = (635, 550, 340, 45)

REGIONAL_LOW_CLARITY_PROMPT_ROI: tuple[int, int, int, int] = (280, 260, 720, 180)
REGIONAL_LOW_CLARITY_BTN_ROI: tuple[int, int, int, int] = (100, 440, 1080, 130)
REGIONAL_LOW_CLARITY_CANCEL_POINT: tuple[int, int] = (349, 505)
REGIONAL_LOW_CLARITY_CONFIRM_POINT: tuple[int, int] = (986, 504)

_DIGIT_CONFUSIONS = str.maketrans({
    "O": "0",
    "o": "0",
    "I": "1",
    "l": "1",
    "|": "1",
    "S": "5",
    "s": "5",
    "B": "8",
})


def _clean(text: Any) -> str:
    return re.sub(r"\s+", "", str(text or "")).strip()


def _entry_box(entry: dict[str, Any]) -> tuple[int, int, int, int] | None:
    if not isinstance(entry, dict):
        return None
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


def _entry_center(entry: dict[str, Any]) -> tuple[int, int] | None:
    if isinstance(entry, dict) and "center_x" in entry and "center_y" in entry:
        try:
            return int(round(float(entry["center_x"]))), int(round(float(entry["center_y"])))
        except (TypeError, ValueError):
            pass
    box = _entry_box(entry)
    if box is None:
        return None
    x, y, w, h = box
    return int(round(x + w / 2.0)), int(round(y + h / 2.0))


def _sorted_entries(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def _sort_key(item: dict[str, Any]) -> tuple[int, int]:
        box = _entry_box(item)
        if box is None:
            return (0, 0)
        return (box[1] // 16, box[0])

    return sorted((e for e in entries if isinstance(e, dict)), key=_sort_key)


def _normalize_int(raw: str, *, min_val: int = 0, max_val: int = 999) -> int | None:
    cleaned = raw.translate(_DIGIT_CONFUSIONS)
    digits = re.sub(r"\D", "", cleaned)
    if not digits:
        return None
    value = int(digits)
    if min_val <= value <= max_val:
        return value
    return None


def _parse_percent_value(text: str) -> int | None:
    match = re.search(r"([0-9OoIl|SsB]{1,3})\s*[%％]", text)
    if not match:
        return None
    cleaned = match.group(1).translate(_DIGIT_CONFUSIONS)
    if not cleaned.isdigit():
        return None
    val = int(cleaned)
    if 0 <= val <= 100:
        return val
    return None


def find_terminal_regional_combat_go_point(entries: list[dict[str, Any]]) -> tuple[int, int] | None:
    """On the 铁安协同终端 hub screen, locate the '前往' button belonging to the 区域作战中心 card."""
    title_candidates: list[tuple[int, tuple[int, int, int, int]]] = []
    has_terminal_context = False
    go_candidates: list[tuple[int, int, int, int]] = []

    for entry in _sorted_entries(entries):
        text = _clean(entry.get("text"))
        box = _entry_box(entry)
        if not text or box is None:
            continue
        if any(kw in text for kw in ("前往作战", "威胁等级", "点击变更难度", "声望等级", "驱逐任务")):
            return None

        cx = int(round(box[0] + box[2] / 2.0))
        cleaned = re.sub(r"[\s·•.,，。!！?？:：;；\-_/|<>《》【】\[\]()（）]+", "", text)
        if cleaned == "区域作战中心":
            title_candidates.append((0, box))
        elif "区域作战" in cleaned and len(cleaned) <= 8 and cx >= 750:
            title_candidates.append((1, box))

        if any(kw in text for kw in ("铁安协同终端", "完成全部作战计划", "铁安局", "派遣委托")):
            has_terminal_context = True
        if "前往" in text and "前往目的地" not in text and "前往车站" not in text:
            go_candidates.append(box)

    if not title_candidates or (not has_terminal_context and not go_candidates):
        return None

    best_score: tuple[int, int, int] | None = None
    best_go_point: tuple[int, int] | None = None
    for prio, tbox in title_candidates:
        tx = int(round(tbox[0] + tbox[2] / 2.0))
        ty = int(round(tbox[1] + tbox[3] / 2.0))
        for gbox in go_candidates:
            gx = int(round(gbox[0] + gbox[2] / 2.0))
            gy = int(round(gbox[1] + gbox[3] / 2.0))
            dx = abs(gx - tx)
            dy = gy - ty
            if 0 < dy <= 220 and dx <= 180:
                score = (prio, dx, dy)
                if best_score is None or score < best_score:
                    best_score = score
                    best_go_point = (gx, gy)

    if best_go_point is not None:
        return best_go_point
    if has_terminal_context:
        title_candidates.sort(key=lambda item: (item[0], -item[1][1]))
        _, tbox = title_candidates[0]
        tx = int(round(tbox[0] + tbox[2] / 2.0))
        ty = int(round(tbox[1] + tbox[3] / 2.0))
        return (tx, min(680, ty + 85))
    return None


def find_regional_fight_button_box(entries: list[dict[str, Any]]) -> tuple[int, int, int, int] | None:
    """Return the bounding box of the 前往作战 button if present in OCR entries."""
    for entry in _sorted_entries(entries):
        text = _clean(entry.get("text"))
        if "前往作战" in text:
            box = _entry_box(entry)
            if box is not None:
                return box
    return None


def is_regional_combat_page(
    banner_entries: list[dict[str, Any]],
    diff_entries: list[dict[str, Any]],
    fight_entries: list[dict[str, Any]],
) -> bool:
    """Return True when the screen shows the Regional Combat Center main view."""
    if find_regional_fight_button_box(fight_entries) is None:
        return False

    banner_texts = [_clean(e.get("text")).upper() for e in banner_entries if isinstance(e, dict)]
    if any("威胁等级" in t or "威胁" in t or "LEVEL" in t or "CLEAR" in t for t in banner_texts):
        return True

    diff_texts = [_clean(e.get("text")) for e in diff_entries if isinstance(e, dict)]
    return any("变更难度" in t for t in diff_texts)


def has_first_clear_badge(entries: list[dict[str, Any]]) -> bool:
    """Return True when the reward strip shows at least one red '首通' tag."""
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        text = _clean(entry.get("text"))
        if "首通" in text:
            return True
    return False


def parse_enemy_level(entries: list[dict[str, Any]]) -> int | None:
    """Parse '敌方等级：31' -> 31 from the bottom-right warning line."""
    ordered = _sorted_entries(entries)
    texts = [_clean(e.get("text")) for e in ordered if _clean(e.get("text"))]
    candidates = list(texts)
    if len(texts) > 1:
        candidates.append("".join(texts))

    for text in candidates:
        match = re.search(r"敌方等级\s*[:：]?\s*([0-9OoIl|SsB]{1,3})", text)
        if match:
            level = _normalize_int(match.group(1), min_val=1, max_val=999)
            if level is not None:
                return level
    return None


def parse_stage_title(entries: list[dict[str, Any]]) -> str:
    """Extract the primary stage title below the threat banners for logging."""
    for entry in _sorted_entries(entries):
        raw = str(entry.get("text") or "").strip()
        cleaned = _clean(raw)
        if not cleaned:
            continue
        upper = cleaned.upper()
        if "EVICTION" in upper or "PROCESS" in upper or upper in {"CLEAR", "LEVEL"}:
            continue
        return raw
    return ""


def parse_level_range(text: str) -> tuple[int, int | None] | None:
    """Parse level ranges such as 'LV21~LV125', 'LV21-LV125', 'ELV56~LV80', or single 'LV36'."""
    cleaned = _clean(text)
    if not cleaned:
        return None
    range_match = re.search(
        r"(?:E?[L1I|]?\s*V)\s*([0-9OoIl|SsB]{1,3})\s*[~\-—–]+\s*(?:E?[L1I|]?\s*V)?\s*([0-9OoIl|SsB]{1,3})",
        cleaned,
        re.IGNORECASE,
    )
    if range_match:
        lo = _normalize_int(range_match.group(1), min_val=1, max_val=999)
        hi = _normalize_int(range_match.group(2), min_val=1, max_val=999)
        if lo is not None and hi is not None:
            return (min(lo, hi), max(lo, hi))

    single_match = re.search(r"(?:E?[L1I|]?\s*V)\s*([0-9OoIl|SsB]{1,3})", cleaned, re.IGNORECASE)
    if single_match:
        lv = _normalize_int(single_match.group(1), min_val=1, max_val=999)
        if lv is not None:
            return (lv, None)
    return None


def _resolve_card_level_range(
    row_items: list[tuple[int, int, str]],
) -> tuple[int, int | None] | None:
    """Resolve full (min_level, max_level) from one or multiple split OCR fragments on a card's LV row."""
    if not row_items:
        return None
    ordered = sorted(row_items, key=lambda item: item[0])
    for _, _, txt in ordered:
        parsed = parse_level_range(txt)
        if parsed is not None and parsed[1] is not None:
            return parsed

    if len(ordered) >= 2:
        joined = "~".join(_clean(txt) for _, _, txt in ordered if _clean(txt))
        parsed_joined = parse_level_range(joined)
        if parsed_joined is not None and parsed_joined[1] is not None:
            return parsed_joined

    for _, _, txt in ordered:
        parsed = parse_level_range(txt)
        if parsed is not None:
            return parsed
    return None


def parse_regional_city_cards(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Parse unlocked city/station cards from the left Regional Combat list."""
    left_names: list[tuple[int, int, str]] = []
    pct_items: list[tuple[int, int, int, tuple[int, int, int, int]]] = []
    right_level_fragments: list[tuple[int, int, str]] = []

    for entry in _sorted_entries(entries):
        text = str(entry.get("text") or "").strip()
        box = _entry_box(entry)
        if not text or box is None:
            continue
        x, y, w, h = box
        cx = int(round(x + w / 2.0))
        cy = int(round(y + h / 2.0))

        pct = _parse_percent_value(text) if x >= 280 else None
        if pct is not None:
            if 100 <= cy <= 685 and (y + h) <= 705:
                pct_items.append((cx, cy, pct, box))
            continue

        if x >= 280:
            cleaned = _clean(text)
            if cleaned and not any(kw in cleaned for kw in ("LOCK", "作战进度", "前往", "解锁")) and re.search(r"[0-9]", cleaned):
                right_level_fragments.append((x, cy, text))
            continue

        if x < 230 and not re.fullmatch(r"[A-Za-z0-9~\- ]+", text):
            left_names.append((cx, cy, text))

    cards: list[dict[str, Any]] = []
    for _, pct_cy, pct, box in pct_items:
        best_name = ""
        best_dy = 999
        for _, name_cy, name_txt in left_names:
            dy = abs(name_cy - pct_cy)
            if dy <= 32 and dy < best_dy:
                best_dy = dy
                best_name = name_txt

        row_fragments = [
            frag for frag in right_level_fragments if 40 <= (pct_cy - frag[1]) <= 100
        ]
        lv_range = _resolve_card_level_range(row_fragments)
        min_lv = lv_range[0] if lv_range is not None else None
        max_lv = lv_range[1] if lv_range is not None else None
        stage_count = (
            (max_lv - min_lv + 1)
            if (min_lv is not None and max_lv is not None and max_lv >= min_lv)
            else None
        )
        if pct >= 100:
            remaining_stages: int | None = 0
        elif stage_count is not None:
            remaining_stages = max(1, int(round(stage_count * (100 - pct) / 100.0)))
        else:
            remaining_stages = None

        city_name = best_name or f"row_{pct_cy}"
        tap_y = max(110, min(650, pct_cy - 30))
        cards.append(
            {
                "city_name": city_name,
                "percent": pct,
                "min_level": min_lv,
                "max_level": max_lv,
                "stage_count": stage_count,
                "remaining_stages": remaining_stages,
                "box": box,
                "center_y": pct_cy,
                "tap_point": (220, tap_y),
            }
        )

    cards.sort(key=lambda item: int(item["center_y"]))
    return cards


def find_selected_city_card(image: Any, cards: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Detect the currently selected city card via the bright-yellow '<' '>' edge arrows."""
    if not cards or not isinstance(image, np.ndarray) or image.ndim != 3:
        return None
    h, w = image.shape[:2]
    if h < 700 or w < 500 or image.shape[2] < 3:
        return None

    sx = w / 1280.0
    sy = h / 720.0
    lx1, lx2 = max(0, int(round(6 * sx))), min(w, int(round(46 * sx)))
    rx1, rx2 = max(0, int(round(425 * sx))), min(w, int(round(468 * sx)))
    if lx2 <= lx1 or rx2 <= rx1:
        return None

    best_card: dict[str, Any] | None = None
    best_score = 0
    for card in cards:
        cy = int(card.get("center_y", 0))
        y1 = max(0, int(round(max(65, cy - 75) * sy)))
        y2 = min(h, int(round(min(710, cy - 5) * sy)))
        if y2 <= y1:
            continue

        left_patch = image[y1:y2, lx1:lx2]
        right_patch = image[y1:y2, rx1:rx2]
        left_cnt = int(
            np.sum((left_patch[:, :, 2] >= 220) & (left_patch[:, :, 1] >= 180) & (left_patch[:, :, 0] <= 85))
        )
        right_cnt = int(
            np.sum((right_patch[:, :, 2] >= 220) & (right_patch[:, :, 1] >= 180) & (right_patch[:, :, 0] <= 85))
        )
        score = min(left_cnt, right_cnt)
        if score >= 120 and score > best_score:
            best_score = score
            best_card = card

    return best_card


def should_skip_for_enemy_level(
    enemy_level: int | None,
    max_enemy_level: int,
    *,
    city_min_level: int | None = None,
) -> bool:
    """Return True when enemy_level (or city_min_level fallback) exceeds max_enemy_level (> 0)."""
    if max_enemy_level <= 0:
        return False
    if enemy_level is not None:
        return int(enemy_level) > int(max_enemy_level)
    if city_min_level is not None:
        return int(city_min_level) > int(max_enemy_level)
    return False


def merge_city_catalog(
    catalog: dict[str, dict[str, Any]],
    cards: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Merge visible station cards into a cumulative catalog preserving first-seen order and full LV spans."""
    for card in cards:
        name = str(card.get("city_name") or "").strip()
        if not name:
            continue
        pct = int(card.get("percent", 0))
        if name not in catalog:
            entry = dict(card)
            entry["city_name"] = name
            entry["order_idx"] = int(card.get("order_idx", len(catalog)))
            catalog[name] = entry
            continue

        existing = catalog[name]
        existing["percent"] = pct
        existing["box"] = card.get("box", existing.get("box"))
        existing["center_y"] = card.get("center_y", existing.get("center_y"))
        existing["tap_point"] = card.get("tap_point", existing.get("tap_point"))

        new_stage_count = card.get("stage_count")
        old_stage_count = existing.get("stage_count")
        if new_stage_count is not None or (old_stage_count is None and card.get("min_level") is not None):
            existing["min_level"] = card.get("min_level")
            existing["max_level"] = card.get("max_level")
            existing["stage_count"] = new_stage_count

        eff_count = existing.get("stage_count")
        if pct >= 100:
            existing["remaining_stages"] = 0
        elif eff_count is not None:
            existing["remaining_stages"] = max(1, int(round(int(eff_count) * (100 - pct) / 100.0)))
        else:
            existing["remaining_stages"] = None
    return catalog


def rank_unfinished_regional_cities(
    cards: list[dict[str, Any]],
    *,
    excluded_cities: set[str] | tuple[str, ...] = (),
    max_enemy_level: int = 0,
    city_order: str = "fewest_stages_first",
) -> list[dict[str, Any]]:
    """Filter and order unfinished city cards according to city_order ('fewest_stages_first' or 'list_order')."""
    excluded = {str(name).strip() for name in excluded_cities if str(name).strip()}
    eligible: list[tuple[int, dict[str, Any]]] = []
    for idx, card in enumerate(cards):
        if int(card.get("percent", 100)) >= 100:
            continue
        if str(card.get("city_name") or "").strip() in excluded:
            continue
        min_lv = card.get("min_level")
        if max_enemy_level > 0 and min_lv is not None and int(min_lv) > int(max_enemy_level):
            continue
        eligible.append((idx, card))

    if city_order == "fewest_stages_first":
        def _sort_key(pair: tuple[int, dict[str, Any]]) -> tuple[int, int, int, int]:
            idx, item = pair
            sc = item.get("stage_count")
            rem = item.get("remaining_stages")
            min_lv = item.get("min_level")
            order_idx = item.get("order_idx")
            return (
                int(sc) if sc is not None else 9999,
                int(rem) if rem is not None else 9999,
                int(min_lv) if min_lv is not None else 999,
                int(order_idx) if order_idx is not None else idx,
            )

        eligible.sort(key=_sort_key)

    return [card for _, card in eligible]


def select_unfinished_regional_cities(
    entries: list[dict[str, Any]],
    *,
    excluded_cities: set[str] | tuple[str, ...] = (),
    max_enemy_level: int = 0,
    city_order: str = "list_order",
) -> list[dict[str, Any]]:
    """Return city cards with progress < 100%, skipping excluded cities and over-level stations."""
    return rank_unfinished_regional_cities(
        parse_regional_city_cards(entries),
        excluded_cities=excluded_cities,
        max_enemy_level=max_enemy_level,
        city_order=city_order,
    )


def find_low_clarity_popup_button(entries: list[dict[str, Any]], *, kind: str) -> tuple[int, int] | None:
    """Locate '取消' (left) or '确认' (right) on the insufficient Clarity modal."""
    keyword = "取消" if kind == "cancel" else "确认"
    for entry in _sorted_entries(entries):
        text = _clean(entry.get("text"))
        if keyword not in text:
            continue
        center = _entry_center(entry)
        if center is None:
            continue
        cx, _ = center
        if kind == "cancel" and cx < 640:
            return center
        if kind == "confirm" and cx >= 640:
            return center
    return None


def resolve_effective_max_enemy_level(params: dict[str, Any]) -> int:
    """Resolve effective enemy-level ceiling (0 = unlimited) from select + optional custom input."""
    use_custom = bool(params.get("use_custom_max_enemy_level", False))
    raw_val = params.get("custom_max_enemy_level") if use_custom else params.get("max_enemy_level", 0)
    try:
        parsed = int(raw_val)
    except (TypeError, ValueError):
        return 0
    return parsed if parsed > 0 else 0


def resolve_effective_max_runs(params: dict[str, Any]) -> int:
    """Resolve effective max runs (0 = unlimited) from run_mode + run_count."""
    if str(params.get("run_mode") or "unlimited") != "fixed_count":
        return 0
    try:
        parsed = int(params.get("run_count", 0))
    except (TypeError, ValueError):
        return 0
    return parsed if parsed > 0 else 0
