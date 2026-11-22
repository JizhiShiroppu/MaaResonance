"""Pure logic helpers for Security Agency (铁安局) auto-farming."""
from __future__ import annotations

import re
from typing import Any

# 1280x720 ROIs verified against real Security Agency screenshots.
SECURITY_REPUTATION_ROI: tuple[int, int, int, int] = (60, 635, 390, 65)
SECURITY_TITLE_ROI: tuple[int, int, int, int] = (140, 520, 210, 110)
SECURITY_FIGHT_BTN_ROI: tuple[int, int, int, int] = (820, 500, 440, 80)
SECURITY_PROGRESS_ROI: tuple[int, int, int, int] = (1110, 175, 155, 105)
SECURITY_TABS_ROI: tuple[int, int, int, int] = (495, 610, 780, 100)
SECURITY_TAB_SWIPE: tuple[int, int, int, int] = (1160, 655, 560, 655)
SECURITY_REMOTE_MARKER_ROI: tuple[int, int, int, int] = (60, 640, 380, 75)
SECURITY_REMOTE_REWARD_ROI: tuple[int, int, int, int] = (840, 10, 260, 50)
SECURITY_CITY_LIST_ROI: tuple[int, int, int, int] = (25, 80, 445, 565)
SECURITY_CITY_SWIPE_DOWN: tuple[int, int, int, int] = (220, 520, 220, 180)
SECURITY_CITY_SWIPE_UP: tuple[int, int, int, int] = (220, 180, 220, 520)

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


def _entry_box(entry: dict[str, Any]) -> tuple[int, int, int, int] | None:
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


def _sorted_entries(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def _sort_key(item: dict[str, Any]) -> tuple[int, int]:
        box = _entry_box(item)
        if box is None:
            return (0, 0)
        return (box[1] // 16, box[0])

    return sorted((e for e in entries if isinstance(e, dict)), key=_sort_key)


def _normalize_digits(raw: str) -> int | None:
    cleaned = raw.translate(_DIGIT_CONFUSIONS)
    digits = re.sub(r"\D", "", cleaned)
    if not digits:
        return None
    value = int(digits)
    if 0 <= value <= 99:
        return value
    return None


def has_security_agency_title(entries: list[dict[str, Any]]) -> bool:
    """Return True when OCR entries contain the 铁安局 badge text."""
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        text = str(entry.get("text") or "").strip()
        if "铁安局" in text:
            return True
    return False


def find_start_combat_box(entries: list[dict[str, Any]]) -> tuple[int, int, int, int] | None:
    """Return the bounding box of the 前往作战 button if present in OCR entries."""
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        text = str(entry.get("text") or "").replace(" ", "")
        if "前往作战" in text:
            box = _entry_box(entry)
            if box is not None:
                return box
    return None


def parse_reputation_level(entries: list[dict[str, Any]]) -> int | None:
    """Parse city reputation level (e.g. '声望等级：0级' -> 0) from bottom-left OCR entries."""
    ordered = _sorted_entries(entries)
    texts = [str(e.get("text") or "").strip() for e in ordered if str(e.get("text") or "").strip()]

    candidates = list(texts)
    if len(texts) > 1:
        candidates.append("".join(texts))

    for text in candidates:
        match = re.search(r"声望等级\s*[:：]?\s*([0-9OoIl|SsB]+)\s*级?", text)
        if match:
            level = _normalize_digits(match.group(1))
            if level is not None:
                return level

    # Fallback when '声望等级' and '0级' are separated and other text sits between them.
    has_label = any("声望等级" in t or "声望" in t for t in texts)
    if has_label:
        for text in texts:
            match = re.fullmatch(r"([0-9OoIl|SsB]+)\s*级", text)
            if match:
                level = _normalize_digits(match.group(1))
                if level is not None:
                    return level
    return None


def parse_reputation_progress(entries: list[dict[str, Any]]) -> tuple[int, int] | None:
    """Parse current/total reputation points (e.g. '207/500' -> (207, 500))."""
    for entry in _sorted_entries(entries):
        text = str(entry.get("text") or "").strip()
        if not text:
            continue
        match = re.search(r"(\d{1,6})\s*/\s*(\d{1,6})", text)
        if match:
            cur = int(match.group(1))
            total = int(match.group(2))
            if total > 0 and 0 <= cur <= total * 2:
                return (cur, total)
    return None


def should_stop_for_reputation(current_level: int | None, target_level: int) -> bool:
    """Return True when target_level > 0 and current_level has reached target_level."""
    if target_level <= 0 or current_level is None:
        return False
    return current_level >= target_level


def _parse_percent_value(text: str) -> int | None:
    match = re.search(r"([0-9OoIl|]{1,3})\s*[%％]", text)
    if not match:
        return None
    cleaned = match.group(1).translate(_DIGIT_CONFUSIONS)
    if not cleaned.isdigit():
        return None
    val = int(cleaned)
    if 0 <= val <= 100:
        return val
    return None


def parse_expulsion_progress(entries: list[dict[str, Any]]) -> int | None:
    """Parse top-right expulsion progress percentage (e.g. '100%' -> 100)."""
    for entry in _sorted_entries(entries):
        text = str(entry.get("text") or "").strip()
        if not text:
            continue
        pct = _parse_percent_value(text)
        if pct is not None:
            return pct
    return None


def parse_tab_progress_candidates(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Extract bottom mission tab percentage badges and compute safe tap points inside each card."""
    tabs: list[dict[str, Any]] = []
    for entry in _sorted_entries(entries):
        text = str(entry.get("text") or "").strip()
        if not text:
            continue
        pct = _parse_percent_value(text)
        if pct is None:
            continue
        box = _entry_box(entry)
        if box is None:
            continue
        cx = int(round(box[0] + box[2] / 2.0))
        cy = int(round(box[1] + box[3] / 2.0))
        # Percentage badge sits at the right edge of each ~255px wide tab card; shift left into the card center.
        tap_x = max(525, min(1240, cx - 80))
        tap_y = max(625, min(695, cy))
        tabs.append(
            {
                "percent": pct,
                "box": box,
                "center_x": cx,
                "tap_point": (tap_x, tap_y),
            }
        )
    tabs.sort(key=lambda item: int(item["center_x"]))
    return tabs


def select_unfinished_tab_candidates(
    entries: list[dict[str, Any]],
    *,
    excluded_x_centers: tuple[int, ...] | set[int] = (),
) -> list[dict[str, Any]]:
    """Return bottom mission tabs with expulsion progress < 100%, ordered left-to-right."""
    candidates: list[dict[str, Any]] = []
    for tab in parse_tab_progress_candidates(entries):
        if int(tab["percent"]) >= 100:
            continue
        cx = int(tab["center_x"])
        if any(abs(cx - int(ex)) <= 40 for ex in excluded_x_centers):
            continue
        candidates.append(tab)
    return candidates


def has_remote_security_hub(
    marker_entries: list[dict[str, Any]],
    reward_entries: list[dict[str, Any]] = (),
) -> bool:
    """Return True when OCR entries match the remote Security Agency hub (驱逐任务 / 查看驱逐进度奖励)."""
    for entry in marker_entries:
        if not isinstance(entry, dict):
            continue
        text = str(entry.get("text") or "").replace(" ", "")
        if "驱逐任务" in text or "悬赏任务" in text:
            return True
    for entry in reward_entries:
        if not isinstance(entry, dict):
            continue
        text = str(entry.get("text") or "").replace(" ", "")
        if "查看驱逐进度奖励" in text or "驱逐进度奖励" in text:
            return True
    return False


def parse_remote_city_cards(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Parse complete city cards from the remote Security Agency left city list."""
    left_names: list[tuple[int, int, str]] = []
    pct_items: list[tuple[int, int, int, tuple[int, int, int, int]]] = []

    for entry in _sorted_entries(entries):
        text = str(entry.get("text") or "").strip()
        box = _entry_box(entry)
        if not text or box is None:
            continue
        x, y, w, h = box
        cx = int(round(x + w / 2.0))
        cy = int(round(y + h / 2.0))

        pct = _parse_percent_value(text) if x >= 230 else None
        if pct is not None:
            # Allow the bottom-most fully visible city card (banner y≈597..630 above the y=642 bottom tab bar),
            # while ignoring clipped fragments overflowing the top header or bottom tab bar.
            if 95 <= cy <= 628 and (y + h) <= 640:
                pct_items.append((cx, cy, pct, box))
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
        city_name = best_name or f"row_{pct_cy}"
        tap_y = max(95, min(585, pct_cy - 15))
        cards.append(
            {
                "city_name": city_name,
                "percent": pct,
                "box": box,
                "center_y": pct_cy,
                "tap_point": (220, tap_y),
            }
        )
    cards.sort(key=lambda item: int(item["center_y"]))
    return cards


def select_unfinished_remote_cities(
    entries: list[dict[str, Any]],
    *,
    excluded_cities: set[str] | tuple[str, ...] = (),
) -> list[dict[str, Any]]:
    """Return remote city cards with expulsion progress < 100%, skipping excluded cities."""
    excluded = {str(name).strip() for name in excluded_cities if str(name).strip()}
    return [
        card
        for card in parse_remote_city_cards(entries)
        if int(card["percent"]) < 100 and str(card["city_name"]).strip() not in excluded
    ]


def find_terminal_security_agency_go_point(entries: list[dict[str, Any]]) -> tuple[int, int] | None:
    """On the 作战终端 hub screen, locate the '前往' button belonging to the 铁安局 card."""
    title_candidates: list[tuple[int, tuple[int, int, int, int]]] = []
    has_terminal_context = False
    go_candidates: list[tuple[int, int, int, int]] = []

    for entry in _sorted_entries(entries):
        text = str(entry.get("text") or "").replace(" ", "")
        box = _entry_box(entry)
        if not text or box is None:
            continue
        if "前往作战" in text or "声望等级" in text or "驱逐任务" in text:
            return None

        cleaned = re.sub(r"[\s·•.,，。!！?？:：;；\-_/|<>《》【】\[\]()（）]+", "", text)
        if cleaned == "铁安局":
            title_candidates.append((0, box))
        elif "铁安局" in cleaned and len(cleaned) <= 5:
            title_candidates.append((1, box))

        if any(kw in text for kw in ("完成全部驱逐进度", "拉普拉斯", "全部驱逐进度", "铁安协同终端")):
            has_terminal_context = True
        if "前往" in text and "前往目的地" not in text:
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
