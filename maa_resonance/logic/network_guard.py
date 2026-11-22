"""Pure logic, pixel pre-screen, OCR matching, and retry tracker for NetworkReconnectGuard."""
from __future__ import annotations

import re
import time
from typing import Any, Callable

try:
    import numpy as np
except Exception:  # pragma: no cover
    np = None

GAME_ANDROID_PACKAGE = "com.hermes.goda"

# Calibrated on 1280x720 popup screenshot:
# text '当前网络不佳，请尝试重新连接' -> [482, 346, 315, 26]
# confirm button '确认' -> [955, 484, 56, 36]
NETWORK_POOR_TEXT_ROI: tuple[int, int, int, int] = (260, 290, 760, 140)
NETWORK_POOR_CONFIRM_ROI: tuple[int, int, int, int] = (640, 455, 620, 100)
NETWORK_POOR_DEFAULT_CONFIRM_POINT: tuple[int, int] = (983, 502)

DEFAULT_MAX_RETRIES = 10
DEFAULT_WINDOW_SEC = 120.0
DEFAULT_RETRY_WAIT_SEC = 2.0
DEFAULT_MAX_RESTARTS = 2
DEFAULT_RESTART_WINDOW_SEC = 900.0


def _clean(text: Any) -> str:
    return re.sub(r"\s+", "", str(text or "")).strip()


def _entry_center(entry: dict[str, Any]) -> tuple[int, int] | None:
    if not isinstance(entry, dict):
        return None
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
    if all(k in entry for k in ("x", "y", "w", "h")):
        try:
            return int(round(int(entry["x"]) + int(entry["w"]) / 2.0)), int(round(int(entry["y"]) + int(entry["h"]) / 2.0))
        except (TypeError, ValueError):
            return None
    return None


def _slice_720(image: Any, x1: int, y1: int, x2: int, y2: int) -> Any | None:
    if np is None or not isinstance(image, np.ndarray):
        return None
    if image.ndim != 3 or image.shape[2] < 3:
        return None
    h, w = image.shape[:2]
    if h < 180 or w < 320:
        return None
    sx = w / 1280.0
    sy = h / 720.0
    ix1 = max(0, min(w - 1, int(round(x1 * sx))))
    ix2 = max(ix1 + 1, min(w, int(round(x2 * sx))))
    iy1 = max(0, min(h - 1, int(round(y1 * sy))))
    iy2 = max(iy1 + 1, min(h, int(round(y2 * sy))))
    return image[iy1:iy2, ix1:ix2, :3]


def _is_dark_banner_patch(patch: Any) -> bool:
    if patch is None or patch.size == 0:
        return False
    arr = patch.astype(np.float32)
    means = arr.mean(axis=(0, 1))
    stds = arr.std(axis=(0, 1))
    return bool(np.all((means >= 10.0) & (means <= 65.0)) and np.all(stds <= 22.0))


def _is_neutral_gray_button_patch(patch: Any) -> bool:
    if patch is None or patch.size == 0:
        return False
    arr = patch.astype(np.float32)
    means = arr.mean(axis=(0, 1))
    stds = arr.std(axis=(0, 1))
    spread = float(np.max(means) - np.min(means))
    return bool(
        np.all((means >= 50.0) & (means <= 130.0))
        and spread <= 18.0
        and np.all(stds <= 22.0)
    )


def _is_bright_blue_button_patch(patch: Any) -> bool:
    if patch is None or patch.size == 0:
        return False
    arr = patch.astype(np.int16)
    b, g, r = arr[:, :, 0], arr[:, :, 1], arr[:, :, 2]
    blue_mask = (b >= 175) & ((b - r) >= 105) & ((b - g) >= 60)
    return float(np.mean(blue_mask)) >= 0.75


def is_network_poor_popup_pixels(bgr_image: Any) -> bool:
    """Fast (<0.2ms) pixel pre-screen for the '当前网络不佳，请尝试重新连接' modal."""
    if np is None or not isinstance(bgr_image, np.ndarray):
        return False
    if bgr_image.ndim != 3 or bgr_image.shape[2] < 3:
        return False
    h, w = bgr_image.shape[:2]
    if h < 180 or w < 320:
        return False

    # 1. Top bright blue horizontal border line (y=259..265, x=120..1160 on 720p).
    top_line = _slice_720(bgr_image, 120, 259, 1160, 266)
    if top_line is None or top_line.size == 0:
        return False
    line_i16 = top_line.astype(np.int16)
    lb, lg, lr = line_i16[:, :, 0], line_i16[:, :, 1], line_i16[:, :, 2]
    line_mask = (lb >= 130) & ((lb - lr) >= 65) & ((lb - lg) >= 35)
    if float(np.max(np.mean(line_mask, axis=1))) < 0.70:
        return False

    # 2. Dark blue-gray banner sides (avoid centered prompt text).
    if not _is_dark_banner_patch(_slice_720(bgr_image, 40, 278, 280, 448)):
        return False
    if not _is_dark_banner_patch(_slice_720(bgr_image, 1000, 278, 1240, 448)):
        return False

    # 3. Bottom-left neutral gray cancel button (avoid centered icon/text).
    if not _is_neutral_gray_button_patch(_slice_720(bgr_image, 80, 485, 250, 525)):
        return False
    if not _is_neutral_gray_button_patch(_slice_720(bgr_image, 420, 485, 580, 525)):
        return False

    # 4. Bottom-right bright blue confirm button (avoid centered icon/text).
    if not _is_bright_blue_button_patch(_slice_720(bgr_image, 700, 485, 880, 525)):
        return False
    if not _is_bright_blue_button_patch(_slice_720(bgr_image, 1060, 485, 1220, 525)):
        return False

    return True


def is_network_poor_popup_entries(entries: list[dict[str, Any]]) -> bool:
    """Return True when OCR entries in the modal text ROI confirm the network reconnect prompt."""
    texts = [_clean(e.get("text")) for e in entries if isinstance(e, dict)]
    if not texts:
        return False
    joined = "".join(texts)
    if "当前网络不佳" in joined or "尝试重新连接" in joined:
        return True
    return "网络不佳" in joined and "重新连接" in joined


def find_network_poor_confirm_point(entries: list[dict[str, Any]]) -> tuple[int, int]:
    """Resolve the right-side confirm button center from OCR entries, with calibrated fallback."""
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        cleaned = _clean(entry.get("text"))
        if "确认" not in cleaned and "确定" not in cleaned:
            continue
        center = _entry_center(entry)
        if center is not None and center[0] >= 640:
            return center
    return NETWORK_POOR_DEFAULT_CONFIRM_POINT


class NetworkGuardTracker:
    """Sliding-window retry & restart decision tracker for network reconnect popups."""

    def __init__(
        self,
        *,
        max_retries: int = DEFAULT_MAX_RETRIES,
        window_sec: float = DEFAULT_WINDOW_SEC,
        max_restarts: int = DEFAULT_MAX_RESTARTS,
        restart_window_sec: float = DEFAULT_RESTART_WINDOW_SEC,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.max_retries = max_retries
        self.window_sec = window_sec
        self.max_restarts = max_restarts
        self.restart_window_sec = restart_window_sec
        self._clock = clock
        self._retry_timestamps: list[float] = []
        self._restart_timestamps: list[float] = []
        self.alerted = False
        self.pending_lobby_reentry = False

    def reset_retries(self) -> None:
        self._retry_timestamps.clear()

    def reset_task_state(self) -> None:
        self.alerted = False
        self.pending_lobby_reentry = False

    def reset_all(self) -> None:
        self._retry_timestamps.clear()
        self._restart_timestamps.clear()
        self.alerted = False
        self.pending_lobby_reentry = False

    def decide_on_popup(
        self,
        *,
        is_adb: bool,
        adb_auto_restart: bool,
        pc_popup_alert: bool,
        max_retries: int | None = None,
        window_sec: float | None = None,
        max_restarts: int | None = None,
        restart_window_sec: float | None = None,
        now: float | None = None,
    ) -> dict[str, Any]:
        """Record a detected popup occurrence and return the action decision."""
        t_now = float(self._clock() if now is None else now)
        limit = max(1, int(self.max_retries if max_retries is None else max_retries))
        win_sec = max(1.0, float(self.window_sec if window_sec is None else window_sec))
        r_limit = max(0, int(self.max_restarts if max_restarts is None else max_restarts))
        r_win_sec = max(1.0, float(self.restart_window_sec if restart_window_sec is None else restart_window_sec))

        cutoff = t_now - win_sec
        self._retry_timestamps = [ts for ts in self._retry_timestamps if ts >= cutoff]
        self._retry_timestamps.append(t_now)
        attempt = len(self._retry_timestamps)

        if attempt < limit:
            return {
                "action": "retry_confirm",
                "attempt": attempt,
                "max_retries": limit,
            }

        if is_adb and adb_auto_restart:
            r_cutoff = t_now - r_win_sec
            self._restart_timestamps = [ts for ts in self._restart_timestamps if ts >= r_cutoff]
            if len(self._restart_timestamps) < r_limit:
                self._restart_timestamps.append(t_now)
                self._retry_timestamps.clear()
                return {
                    "action": "adb_restart",
                    "attempt": attempt,
                    "max_retries": limit,
                    "restart_count": len(self._restart_timestamps),
                    "max_restarts": r_limit,
                }
            return {
                "action": "stop_max_restarts",
                "show_popup": True,
                "attempt": attempt,
                "max_retries": limit,
                "restart_count": len(self._restart_timestamps),
                "max_restarts": r_limit,
            }

        return {
            "action": "pc_alert_stop" if not is_adb else "adb_alert_stop",
            "show_popup": bool(pc_popup_alert) if not is_adb else True,
            "attempt": attempt,
            "max_retries": limit,
        }
