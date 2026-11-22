"""Pure logic and pixel/OCR helpers for Calculation Recording (虚演刻录) auto-combat."""
from __future__ import annotations

import re
from typing import Any

import numpy as np

# 1280x720 ROIs and interaction coordinates verified against live 虚演刻录 screens on MuMu 12.
CALC_TOP_PROGRESS_ROI: tuple[int, int, int, int] = (470, 15, 300, 50)
CALC_TICKET_ROI: tuple[int, int, int, int] = (1085, 15, 170, 48)
CALC_LEFT_LIST_ROI: tuple[int, int, int, int] = (10, 95, 600, 515)
CALC_LEFT_SLOT_CENTERS_Y: tuple[int, int, int, int] = (162, 287, 412, 537)
CALC_LEFT_SLOT_TAP_X: int = 310

CALC_LIST_SWIPE_DOWN: tuple[int, int, int, int] = (310, 480, 310, 220)
CALC_LIST_SWIPE_UP: tuple[int, int, int, int] = (310, 220, 310, 480)
CALC_LIST_NUDGE_UP: tuple[int, int, int, int] = (310, 290, 310, 420)

CALC_BOSS_NO_ROI: tuple[int, int, int, int] = (675, 115, 200, 175)
CALC_RECORD_PROGRESS_ROI: tuple[int, int, int, int] = (905, 125, 325, 65)
CALC_RIGHT_PCT_ROI: tuple[int, int, int, int] = (1025, 192, 150, 50)
CALC_BOSS_NAME_ROI: tuple[int, int, int, int] = (1025, 232, 200, 44)
CALC_ENEMY_LEVEL_ROI: tuple[int, int, int, int] = (1020, 282, 180, 40)
CALC_START_BTN_ROI: tuple[int, int, int, int] = (745, 595, 400, 58)
CALC_START_BTN_FALLBACK: tuple[int, int] = (920, 625)

CALC_HUB_LEFT_ENTER_FALLBACK: tuple[int, int] = (499, 441)
CALC_MORE_RECORD_ROI: tuple[int, int, int, int] = (340, 610, 140, 95)
CALC_RECORD_MODAL_DISMISS_POINT: tuple[int, int] = (120, 360)
CALC_SETTLE_NEXT_POINT: tuple[int, int] = (1176, 610)
CALC_SHORTAGE_BTN_ROI: tuple[int, int, int, int] = (100, 440, 1080, 130)

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


def _normalize_int(raw: str, *, min_val: int = 0, max_val: int = 9999) -> int | None:
    cleaned = raw.translate(_DIGIT_CONFUSIONS)
    digits = re.sub(r"\D", "", cleaned)
    if not digits:
        return None
    value = int(digits)
    if min_val <= value <= max_val:
        return value
    return None


def find_calc_recording_hub_enter_point(entries: list[dict[str, Any]]) -> tuple[int, int] | None:
    """On Activity Hub -> 常规活动 -> 虚演刻录, return left card's '前往虚演空间' button point."""
    has_left_anchor = False
    has_hub_context = False
    enter_candidates: list[tuple[int, int, int, int]] = []

    for entry in _sorted_entries(entries):
        text = _clean(entry.get("text"))
        if not text:
            continue
        if any(kw in text for kw in ("开始虚演刻录", "刻录进度")):
            return None

        box = _entry_box(entry)
        center = _entry_center(entry)
        if box is None or center is None:
            continue
        cx, cy = center
        upper = text.upper()

        if any(kw in upper for kw in ("虚演刻录", "CALCULATION", "RECORDING")) and 270 <= cx <= 690 and cy >= 100:
            has_left_anchor = True
        if any(kw in text for kw in ("虚演进度", "深度演算", "兑换商店")):
            has_hub_context = True

        if ("前往虚演空间" in text or "虚演空间" in text) and 290 <= cx <= 705 and 380 <= cy <= 500:
            enter_candidates.append(box)

    if not has_left_anchor:
        return None

    if enter_candidates:
        best_box = min(enter_candidates, key=lambda b: abs((b[0] + b[2] / 2.0) - CALC_HUB_LEFT_ENTER_FALLBACK[0]))
        return (
            int(round(best_box[0] + best_box[2] / 2.0)),
            int(round(best_box[1] + best_box[3] / 2.0)),
        )

    if has_hub_context:
        return CALC_HUB_LEFT_ENTER_FALLBACK
    return None


def find_start_button_box(entries: list[dict[str, Any]]) -> tuple[int, int, int, int] | None:
    """Locate the '开始虚演刻录' button box inside the right detail panel."""
    for entry in _sorted_entries(entries):
        text = _clean(entry.get("text"))
        if not text:
            continue
        box = _entry_box(entry)
        if box is None:
            continue
        cx = box[0] + box[2] / 2.0
        cy = box[1] + box[3] / 2.0
        if "开始虚演刻录" in text or ("虚演刻录" in text and cx >= 740 and cy >= 585):
            return box
    return None


def is_calculation_recording_page(
    start_entries: list[dict[str, Any]],
    record_entries: list[dict[str, Any]],
    top_entries: list[dict[str, Any]],
) -> bool:
    """Return True when the inner 虚演刻录 stage-selection screen is visible."""
    if find_start_button_box(start_entries) is None:
        return False

    record_texts = [_clean(e.get("text")).upper() for e in record_entries if isinstance(e, dict)]
    if any(kw in txt for txt in record_texts for kw in ("刻录进度", "S级", "作战达到")):
        return True

    top_texts = [_clean(e.get("text")) for e in top_entries if isinstance(e, dict)]
    return any("虚演进度" in txt or parse_total_progress([e]) is not None for e, txt in zip(top_entries, top_texts))


def parse_total_progress(entries: list[dict[str, Any]]) -> tuple[int, int] | None:
    """Parse overall progress such as '21/185(11%)' -> (21, 185)."""
    ordered = _sorted_entries(entries)
    candidates = [_clean(e.get("text")) for e in ordered if _clean(e.get("text"))]
    if len(candidates) > 1:
        candidates.append("".join(candidates))

    for text in candidates:
        match = re.search(r"([0-9OoIl|SsB]{1,3})\s*/\s*([0-9OoIl|SsB]{1,3})", text)
        if not match:
            continue
        cleared = _normalize_int(match.group(1), min_val=0, max_val=999)
        total = _normalize_int(match.group(2), min_val=5, max_val=999)
        if cleared is not None and total is not None and cleared <= total:
            return (cleared, total)
    return None


def parse_ticket_count(entries: list[dict[str, Any]]) -> int | None:
    """Parse remaining recording tape tickets from the top-right badge."""
    ordered = _sorted_entries(entries)
    right_candidates: list[int] = []
    fallback_candidates: list[int] = []

    for entry in ordered:
        text = _clean(entry.get("text"))
        if not text:
            continue
        if not re.fullmatch(r"[0-9OoIl|SsB]{1,4}", text):
            match = re.search(r"([0-9]{1,4})\s*$", text)
            if not match:
                continue
            val = _normalize_int(match.group(1), min_val=0, max_val=9999)
        else:
            val = _normalize_int(text, min_val=0, max_val=9999)
        if val is None:
            continue
        center = _entry_center(entry)
        if center is not None and center[0] >= 1110:
            right_candidates.append(val)
        else:
            fallback_candidates.append(val)

    if right_candidates:
        return right_candidates[-1]
    if fallback_candidates:
        return fallback_candidates[-1]
    return None


def parse_boss_number(entries: list[dict[str, Any]]) -> int | None:
    """Parse the giant 2-digit Boss index ('01'..'99') from CALC_BOSS_NO_ROI."""
    preferred: list[tuple[int, int]] = []
    fallback: list[tuple[int, int]] = []

    for entry in _sorted_entries(entries):
        text = _clean(entry.get("text"))
        if not text:
            continue
        upper = text.upper()
        if any(word in upper for word in ("VIRTUAL", "SIMULATION", "SEQUENCE", "MATU", "VRTU", "SRTU")):
            continue
        if not re.fullmatch(r"[0-9OoIl|SsB]{1,2}", text):
            continue
        val = _normalize_int(text, min_val=1, max_val=99)
        if val is None:
            continue
        box = _entry_box(entry)
        h = box[3] if box is not None else 0
        y = box[1] if box is not None else 0
        if box is None or y < 250:
            preferred.append((h, val))
        else:
            fallback.append((h, val))

    if preferred:
        preferred.sort(key=lambda item: item[0], reverse=True)
        return preferred[0][1]
    if fallback:
        fallback.sort(key=lambda item: item[0], reverse=True)
        return fallback[0][1]
    return None


def parse_record_progress_done(entries: list[dict[str, Any]]) -> bool | None:
    """Parse '刻录进度' Stage-I completion: '0/1' -> False, '1/1' -> True."""
    ordered = _sorted_entries(entries)
    candidates = [_clean(e.get("text")) for e in ordered if _clean(e.get("text"))]
    if len(candidates) > 1:
        candidates.append("".join(candidates))

    for text in candidates:
        if "刻录进度" in text or "评级" in text:
            # Extract trailing ratio if merged in the same string.
            pass
        match = re.search(r"([01OoIl|])\s*/\s*([1Il|])", text)
        if not match:
            continue
        num = _normalize_int(match.group(1), min_val=0, max_val=1)
        den = _normalize_int(match.group(2), min_val=1, max_val=1)
        if num is not None and den == 1:
            return num >= 1
    return None


def parse_boss_name(entries: list[dict[str, Any]]) -> str:
    """Extract the primary Boss title below the percentage readout."""
    for entry in _sorted_entries(entries):
        raw = str(entry.get("text") or "").strip()
        cleaned = _clean(raw)
        if not cleaned:
            continue
        if "%" in cleaned or "％" in cleaned or "敌人等级" in cleaned or "敌方等级" in cleaned:
            continue
        if re.fullmatch(r"[0-9.\-_/]+", cleaned):
            continue
        return raw
    return ""


def parse_enemy_level(entries: list[dict[str, Any]]) -> int | None:
    """Parse '敌人等级：37' -> 37 from the Boss detail panel."""
    ordered = _sorted_entries(entries)
    texts = [_clean(e.get("text")) for e in ordered if _clean(e.get("text"))]
    candidates = list(texts)
    if len(texts) > 1:
        candidates.append("".join(texts))

    for text in candidates:
        match = re.search(r"敌[人方]等级\s*[:：]?\s*([0-9OoIl|SsB]{1,3})", text)
        if match:
            lv = _normalize_int(match.group(1), min_val=1, max_val=999)
            if lv is not None:
                return lv
    return None


def count_lit_phase_segments(image: Any) -> int:
    """Count lit cyan phase segments (0..5) below the giant Boss index."""
    if not isinstance(image, np.ndarray) or image.ndim != 3:
        return 0
    h, w = image.shape[:2]
    if h < 360 or w < 640 or image.shape[2] < 3:
        return 0

    sx = w / 1280.0
    sy = h / 720.0
    y1 = max(0, min(h - 1, int(round(286 * sy))))
    y2 = max(y1 + 1, min(h, int(round(294 * sy))))
    thresh = max(8, int(round(40 * sx * sy)))

    seg_w = (882.0 - 673.0) / 5.0
    lit = 0
    for idx in range(5):
        x1 = max(0, min(w - 1, int(round((673.0 + idx * seg_w) * sx))))
        x2 = max(x1 + 1, min(w, int(round((673.0 + (idx + 1) * seg_w) * sx))))
        patch = image[y1:y2, x1:x2]
        cyan_cnt = int(
            np.sum((patch[:, :, 0] > 170) & (patch[:, :, 1] > 170) & (patch[:, :, 2] < 130))
        )
        if cyan_cnt >= thresh:
            lit += 1
    return lit


def _has_100_percent_text(entries: list[dict[str, Any]] | None) -> bool:
    if not entries:
        return False
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        cleaned = _clean(entry.get("text"))
        if not cleaned:
            continue
        norm = cleaned.translate(_DIGIT_CONFUSIONS)
        if re.search(r"(?<!\d)100\s*[%％]?", norm) and re.fullmatch(r"[0-9%％]+", norm):
            return True
    return False


def _has_more_record_text(entries: list[dict[str, Any]] | None) -> bool:
    if not entries:
        return False
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        if "更多记录" in _clean(entry.get("text")):
            return True
    return False


def is_boss_completed_100(
    image: Any,
    right_pct_entries: list[dict[str, Any]] | None = None,
    more_record_entries: list[dict[str, Any]] | None = None,
) -> bool:
    """Distinguish a 100% Boss (all 5 phases S-cleared) from 80% without relying on 首通-S."""
    has_valid_img = (
        isinstance(image, np.ndarray)
        and image.ndim == 3
        and image.shape[0] >= 360
        and image.shape[1] >= 640
        and image.shape[2] >= 3
    )
    if has_valid_img and count_lit_phase_segments(image) < 5:
        return False

    sig_ocr_100 = _has_100_percent_text(right_pct_entries)
    sig_more_record = _has_more_record_text(more_record_entries)
    sig_white_span = False

    if has_valid_img:
        h, w = image.shape[:2]
        sx = w / 1280.0
        sy = h / 720.0

        bx1, bx2 = max(0, int(round(358 * sx))), min(w, int(round(462 * sx)))
        by1, by2 = max(0, int(round(618 * sy))), min(h, int(round(692 * sy)))
        if bx2 > bx1 and by2 > by1:
            btn_patch = image[by1:by2, bx1:bx2]
            dark_ratio = float(
                np.mean((btn_patch[:, :, 0] < 70) & (btn_patch[:, :, 1] < 70) & (btn_patch[:, :, 2] < 70))
            )
            if dark_ratio >= 0.35:
                sig_more_record = True

        px1, px2 = max(0, int(round(1038 * sx))), min(w, int(round(1150 * sx)))
        py1, py2 = max(0, int(round(198 * sy))), min(h, int(round(238 * sy)))
        if px2 > px1 and py2 > py1:
            pct_patch = image[py1:py2, px1:px2]
            white_mask = (pct_patch[:, :, 0] > 180) & (pct_patch[:, :, 1] > 180) & (pct_patch[:, :, 2] > 180)
            xs = np.where(white_mask.any(axis=0))[0]
            if len(xs) > 0:
                span = int(xs.max() - xs.min() + 1)
                if span >= 68.0 * sx:
                    sig_white_span = True

    return sig_ocr_100 or (sig_more_record and sig_white_span)


def is_left_slot_unlocked(
    image: Any,
    slot_cy: int,
    left_entries: list[dict[str, Any]] | None = None,
) -> bool:
    """Return True when left Boss card at ``slot_cy`` is unlocked (cyan radar vs locked gray)."""
    if left_entries:
        for entry in left_entries:
            if not isinstance(entry, dict):
                continue
            text = _clean(entry.get("text"))
            if "前置关卡未完成" in text or "未解锁" in text:
                center = _entry_center(entry)
                if center is not None and abs(center[1] - int(slot_cy)) <= 55:
                    return False

    if not isinstance(image, np.ndarray) or image.ndim != 3:
        return False
    h, w = image.shape[:2]
    if h < 360 or w < 640 or image.shape[2] < 3:
        return False

    sx = w / 1280.0
    sy = h / 720.0
    x1, x2 = max(0, int(round(80 * sx))), min(w, int(round(280 * sx)))
    y1 = max(0, int(round(max(95, int(slot_cy) - 40) * sy)))
    y2 = min(h, int(round(min(610, int(slot_cy) + 40) * sy)))
    if x2 <= x1 or y2 <= y1:
        return False

    patch = image[y1:y2, x1:x2]
    cyan_cnt = int(
        np.sum((patch[:, :, 0] > 130) & (patch[:, :, 1] > 140) & (patch[:, :, 2] < 110))
    )
    thresh = max(50, int(round(500 * sx * sy)))
    return cyan_cnt >= thresh


def find_selected_left_slot(image: Any) -> int | None:
    """Detect the active left slot index (0..3) via black outer selection ticks."""
    if not isinstance(image, np.ndarray) or image.ndim != 3:
        return None
    h, w = image.shape[:2]
    if h < 360 or w < 640 or image.shape[2] < 3:
        return None

    sx = w / 1280.0
    sy = h / 720.0
    lx1, lx2 = max(0, int(round(6 * sx))), min(w, int(round(26 * sx)))
    rx1, rx2 = max(0, int(round(598 * sx))), min(w, int(round(618 * sx)))
    if lx2 <= lx1 or rx2 <= rx1:
        return None

    thresh = max(10, int(round(40 * sx * sy)))
    best_slot: int | None = None
    best_score = 0

    for idx, cy in enumerate(CALC_LEFT_SLOT_CENTERS_Y):
        y1 = max(0, int(round((cy - 10) * sy)))
        y2 = min(h, int(round((cy + 10) * sy)))
        if y2 <= y1:
            continue
        left_patch = image[y1:y2, lx1:lx2]
        right_patch = image[y1:y2, rx1:rx2]
        l_dark = int(np.sum((left_patch[:, :, 0] < 35) & (left_patch[:, :, 1] < 35) & (left_patch[:, :, 2] < 35)))
        r_dark = int(np.sum((right_patch[:, :, 0] < 35) & (right_patch[:, :, 1] < 35) & (right_patch[:, :, 2] < 35)))
        score = min(l_dark, r_dark)
        if score >= thresh and score > best_score:
            best_score = score
            best_slot = idx

    return best_slot


def did_stage_advance(before: dict[str, Any], after: dict[str, Any]) -> bool:
    """Return True if battle outcome advanced S-rank progress; False implies non-S clear."""
    b_total = before.get("total_cleared")
    a_total = after.get("total_cleared")
    if b_total is not None and a_total is not None and int(a_total) > int(b_total):
        return True

    b_no = before.get("boss_no")
    a_no = after.get("boss_no")
    if b_no is not None and a_no is not None and int(a_no) == int(b_no):
        if int(after.get("lit_segments", 0)) > int(before.get("lit_segments", 0)):
            return True
        if bool(after.get("is_100")) and not bool(before.get("is_100")):
            return True
        if before.get("record_done") is False and after.get("record_done") is True:
            return True
        b_lv = before.get("enemy_level")
        a_lv = after.get("enemy_level")
        if b_lv is not None and a_lv is not None and int(a_lv) > int(b_lv):
            return True

    return False


def should_skip_for_enemy_level(enemy_level: int | None, max_enemy_level: int) -> bool:
    """Return True when enemy_level exceeds max_enemy_level (> 0)."""
    if max_enemy_level <= 0 or enemy_level is None:
        return False
    return int(enemy_level) > int(max_enemy_level)


def rank_unfinished_bosses(
    catalog_items: list[dict[str, Any]],
    *,
    excluded_bosses: set[int] | tuple[int, ...] = (),
    max_enemy_level: int = 0,
    boss_order: str = "lowest_level_first",
) -> list[dict[str, Any]]:
    """Filter and order unfinished Boss records by lowest enemy level or list order."""
    excluded = {int(b) for b in excluded_bosses}
    eligible: list[dict[str, Any]] = []

    for item in catalog_items:
        if not isinstance(item, dict):
            continue
        boss_no = item.get("boss_no")
        if boss_no is None or int(boss_no) in excluded:
            continue
        if bool(item.get("is_100")):
            continue
        enemy_lv = item.get("enemy_level")
        if should_skip_for_enemy_level(enemy_lv, max_enemy_level):
            continue
        eligible.append(item)

    if boss_order == "lowest_level_first":
        eligible.sort(
            key=lambda item: (
                int(item["enemy_level"]) if item.get("enemy_level") is not None else 9999,
                int(item["boss_no"]),
            )
        )
    else:
        eligible.sort(key=lambda item: int(item["boss_no"]))

    return eligible


def find_popup_cancel_or_confirm_point(entries: list[dict[str, Any]]) -> tuple[int, int] | None:
    """Locate '取消' (preferred) or '确认'/'确定' on a shortage/info modal."""
    confirm_fallback: tuple[int, int] | None = None
    for entry in _sorted_entries(entries):
        text = _clean(entry.get("text"))
        center = _entry_center(entry)
        if center is None:
            continue
        if "取消" in text:
            return center
        if ("确认" in text or "确定" in text) and confirm_fallback is None:
            confirm_fallback = center
    return confirm_fallback


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
