from __future__ import annotations

import base64
import json
from pathlib import Path
import re
from typing import Any

try:
    import numpy as np
except Exception:  # pragma: no cover
    np = None


BOX_COL_CENTERS_X = (160, 293, 426, 559, 692, 825, 958, 1091)
BOX_ROW_CENTERS_Y = (278, 468, 658)

FEAT_H = 26
FEAT_W = 12

# Right-half outer strip (+8..+46px from diamond center) keeps clear of left-card overlap.
TMPL_X_OFFSET_START = 8
TMPL_X_OFFSET_END = 46
TMPL_HALF_H = 46


def _resize_nn(patch: Any, out_h: int, out_w: int) -> Any:
    ys = np.linspace(0, patch.shape[0] - 1, out_h).astype(int)
    xs = np.linspace(0, patch.shape[1] - 1, out_w).astype(int)
    return patch[ys][:, xs]


def _right_diamond_mask() -> Any:
    mask = np.zeros((FEAT_H, FEAT_W), dtype=bool)
    for y in range(FEAT_H):
        dy = abs(y - (FEAT_H - 1) / 2.0) / ((FEAT_H - 1) / 2.0)
        max_x = int(round((1.0 - dy) * (FEAT_W + 1) - 1))
        if max_x >= 1:
            mask[y, : min(FEAT_W - 1, max_x)] = True
    return mask


_MASK = _right_diamond_mask() if np is not None else None


def extract_right_diamond_feature(bgr_patch: Any) -> dict[str, Any] | None:
    """Extract normalized BGR + gradient feature vector from a right-half diamond patch."""
    if np is None or bgr_patch is None:
        return None
    arr = np.asarray(bgr_patch)
    if arr.ndim != 3 or arr.shape[0] < 16 or arr.shape[1] < 10:
        return None
    small = _resize_nn(arr[..., :3], FEAT_H, FEAT_W).astype(np.float32)
    vals = small[_MASK]
    raw_vec = vals.reshape(-1)
    std = max(float(raw_vec.std()), 20.0)
    z_vec = (raw_vec - raw_vec.mean()) / std
    color_mean = vals.mean(axis=0)
    color_norm = color_mean / (float(np.linalg.norm(color_mean)) + 1e-6)
    return {
        "raw": raw_vec.astype(np.uint8),
        "z": z_vec.astype(np.float32),
        "color": color_norm.astype(np.float32),
    }


def score_right_diamond_feature(cand: dict[str, Any], tmpl: dict[str, Any]) -> float:
    """Compute hybrid L1 + NCC + color similarity in [0, 1], rejecting color mismatches."""
    col_sim = float((cand["color"] * tmpl["color"]).sum())
    if col_sim < 0.88:
        return 0.0
    raw_a = cand["raw"].astype(np.float32)
    raw_b = tmpl["raw"].astype(np.float32)
    l1_sim = 1.0 - float(np.abs(raw_a - raw_b).mean()) / 255.0
    if l1_sim < 0.65:
        return 0.0
    ncc_sim = float((cand["z"] * tmpl["z"]).mean())
    return 0.45 * l1_sim + 0.35 * max(-1.0, ncc_sim) + 0.20 * col_sim


def _entry_box(entry: dict[str, Any]) -> tuple[int, int, int, int]:
    box = entry.get("box")
    if isinstance(box, (list, tuple)) and len(box) >= 4:
        return int(box[0]), int(box[1]), int(box[2]), int(box[3])
    return (
        int(entry.get("x", 0) or 0),
        int(entry.get("y", 0) or 0),
        int(entry.get("w", 0) or 0),
        int(entry.get("h", 0) or 0),
    )


def _match_grid_name(
    entries: list[dict[str, Any]],
    col_x: int,
    name_y_min: int,
    name_y_max: int,
) -> str | None:
    best: tuple[float, str] | None = None
    for entry in entries:
        text = str(entry.get("text") or "").strip()
        if not text:
            continue
        x, y, w, h = _entry_box(entry)
        cx = x + w / 2.0
        cy = y + h / 2.0
        if not (name_y_min <= cy <= name_y_max):
            continue
        if abs(cx - col_x) > 58:
            continue
        # Ignore pure digits (costs)
        if re.fullmatch(r"\d+", text):
            continue
        dist = abs(cx - col_x)
        if best is None or dist < best[0]:
            best = (dist, text)
    return best[1] if best else None


def _match_grid_cost(
    entries: list[dict[str, Any]],
    col_x: int,
    cost_y_min: int,
    cost_y_max: int,
) -> int | None:
    for entry in entries:
        text = str(entry.get("text") or "").strip()
        if not text:
            continue
        x, y, w, h = _entry_box(entry)
        cx = x + w / 2.0
        cy = y + h / 2.0
        if not (cost_y_min <= cy <= cost_y_max):
            continue
        if not (col_x + 5 <= cx <= col_x + 65):
            continue
        m = re.search(r"(\d{1,2})", text)
        if m:
            val = int(m.group(1))
            if 0 <= val <= 15:
                return val
    return None


def extract_box_deck_templates(
    top_image: Any,
    top_entries: list[dict[str, Any]],
    *,
    bottom_entries: list[dict[str, Any]] | None = None,
    row2_name_shift_y: int = 0,
) -> dict[str, Any]:
    """Extract card templates, costs, and priority weights from Box custom-weight UI."""
    if np is None or top_image is None:
        return {"cards": [], "card_weights": {}, "discard_weight": None}

    arr = np.asarray(top_image)
    cards: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    for r_idx, y_c in enumerate(BOX_ROW_CENTERS_Y):
        for c_idx, x_c in enumerate(BOX_COL_CENTERS_X):
            if y_c + TMPL_HALF_H > arr.shape[0] or x_c + TMPL_X_OFFSET_END > arr.shape[1]:
                continue

            if r_idx < 2:
                name_entries = top_entries
                name_y_min, name_y_max = y_c + 45, y_c + 82
            else:
                name_entries = bottom_entries if bottom_entries is not None else top_entries
                name_y_min = y_c + 45 - row2_name_shift_y
                name_y_max = y_c + 82 - row2_name_shift_y

            raw_name = _match_grid_name(name_entries, x_c, name_y_min, name_y_max)
            cost = _match_grid_cost(top_entries, x_c, y_c - 105, y_c - 55)
            card_id = raw_name or f"R{r_idx + 1}C{c_idx + 1}"
            if card_id in seen_ids:
                card_id = f"{card_id}_{r_idx + 1}_{c_idx + 1}"
            seen_ids.add(card_id)

            patch = arr[
                y_c - TMPL_HALF_H : y_c + TMPL_HALF_H,
                x_c + TMPL_X_OFFSET_START : x_c + TMPL_X_OFFSET_END,
                :3,
            ]
            feat = extract_right_diamond_feature(patch)
            if feat is None:
                continue

            order_idx = r_idx * 8 + c_idx
            cards.append(
                {
                    "card_id": card_id,
                    "order_index": order_idx,
                    "cost": cost,
                    "raw_b64": base64.b64encode(feat["raw"].tobytes()).decode("ascii"),
                    "is_discard": "弃牌" in card_id,
                }
            )

    card_weights: dict[str, int] = {}
    discard_weight: int | None = None
    for card in cards:
        weight = 1000 - card["order_index"] * 10
        if card["is_discard"]:
            discard_weight = weight
        else:
            card_weights[card["card_id"]] = weight

    return {
        "cards": cards,
        "card_weights": card_weights,
        "discard_weight": discard_weight,
    }


def save_deck_templates(path: str | Path, deck: dict[str, Any]) -> Path:
    out_path = Path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(deck, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_path


def load_deck_templates(path: str | Path) -> dict[str, Any] | None:
    in_path = Path(path)
    if not in_path.exists():
        return None
    try:
        data = json.loads(in_path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def _decode_deck_features(deck: dict[str, Any]) -> list[dict[str, Any]]:
    decoded: list[dict[str, Any]] = []
    for item in deck.get("cards") or ():
        if item.get("is_discard"):
            continue
        raw_b64 = item.get("raw_b64")
        if not raw_b64:
            continue
        raw_bytes = base64.b64decode(raw_b64)
        raw_arr = np.frombuffer(raw_bytes, dtype=np.uint8)
        expected_len = int(_MASK.sum()) * 3
        if raw_arr.size != expected_len:
            continue
        vals = raw_arr.reshape(-1, 3).astype(np.float32)
        raw_vec = vals.reshape(-1)
        std = max(float(raw_vec.std()), 20.0)
        z_vec = (raw_vec - raw_vec.mean()) / std
        color_mean = vals.mean(axis=0)
        color_norm = color_mean / (float(np.linalg.norm(color_mean)) + 1e-6)
        decoded.append(
            {
                "card_id": item["card_id"],
                "cost": item.get("cost"),
                "raw": raw_arr,
                "z": z_vec,
                "color": color_norm,
            }
        )
    return decoded


def identify_card_at_center(
    image: Any,
    center_x: int,
    deck: dict[str, Any],
    *,
    center_y: int = 588,
    min_score: float = 0.66,
) -> tuple[str | None, int | None, float]:
    """Identify the card ID and cost around a detected hand-card diamond center."""
    if np is None or image is None or not deck:
        return None, None, 0.0
    arr = np.asarray(image)
    if arr.ndim != 3:
        return None, None, 0.0

    templates = deck.get("_decoded")
    if templates is None:
        templates = _decode_deck_features(deck)
        deck["_decoded"] = templates
    if not templates:
        return None, None, 0.0

    best_score = 0.0
    best_id: str | None = None
    best_cost: int | None = None

    for half_h in (46, 54):
        half_w_start = int(round(half_h * (TMPL_X_OFFSET_START / TMPL_HALF_H)))
        half_w_end = int(round(half_h * (TMPL_X_OFFSET_END / TMPL_HALF_H)))
        for dy in (-6, 0, 6):
            # Stacked right-half blobs shift centroid rightwards, so search left-shifted dx too.
            for dx in (-26, -18, -10, -2, 6):
                y1 = center_y + dy - half_h
                y2 = center_y + dy + half_h
                x1 = center_x + dx + half_w_start
                x2 = center_x + dx + half_w_end
                if y1 < 0 or y2 > arr.shape[0] or x1 < 0 or x2 > arr.shape[1]:
                    continue
                feat = extract_right_diamond_feature(arr[y1:y2, x1:x2, :3])
                if feat is None:
                    continue
                for tmpl in templates:
                    score = score_right_diamond_feature(feat, tmpl)
                    if score > best_score:
                        best_score = score
                        best_id = tmpl["card_id"]
                        best_cost = tmpl.get("cost")

    if best_score >= min_score and best_id is not None:
        return best_id, best_cost, best_score
    return None, None, best_score
