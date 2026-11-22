"""Runtime NetworkReconnectGuard helpers, decorators, ADB restart, and Win32 alert."""
from __future__ import annotations

from contextlib import contextmanager
import functools
import sys
import threading
from typing import Any, Callable, Iterator, TypeVar

from agent.utils.action_helpers import ocr_roi, tap_point
from agent.utils.input_guard import get_effective_controller_info, sleep_with_stop
from maa_resonance.logic.network_guard import (
    DEFAULT_MAX_RESTARTS,
    DEFAULT_MAX_RETRIES,
    DEFAULT_RESTART_WINDOW_SEC,
    DEFAULT_RETRY_WAIT_SEC,
    DEFAULT_WINDOW_SEC,
    GAME_ANDROID_PACKAGE,
    NETWORK_POOR_CONFIRM_ROI,
    NETWORK_POOR_DEFAULT_CONFIRM_POINT,
    NETWORK_POOR_TEXT_ROI,
    NetworkGuardTracker,
    find_network_poor_confirm_point,
    is_network_poor_popup_entries,
    is_network_poor_popup_pixels,
)

F = TypeVar("F", bound=Callable[..., Any])

NETWORK_GUARD_ATTACH_NODES: tuple[str, ...] = (
    "CommonNetworkGuardConfig",
    "CommonNetworkGuardOptRetryLimit",
    "CommonNetworkGuardOptAdbRestart",
    "CommonNetworkGuardOptPcAlert",
)

_GUARD_TLS = threading.local()
_TRACKER_LOCK = threading.RLock()
_TRACKER = NetworkGuardTracker()
_ALERT_HANDLER: Callable[[str, str], Any] | None = None

# Optional override point for tests; defaults to lazy import of agent.wake_up_action.run_wake_up_to_lobby.
run_wake_up_to_lobby: Callable[..., bool] | None = None


class NetworkRestartedToLobbyError(RuntimeError):
    """Raised inside restart-aware scopes after an ADB restart successfully returns to lobby."""


def get_tracker() -> NetworkGuardTracker:
    """Return the shared runtime network guard tracker."""
    return _TRACKER


def reset_network_guard_task_state() -> None:
    """Reset per-task alert and lobby-reentry flags."""
    with _TRACKER_LOCK:
        _TRACKER.reset_task_state()


def reset_network_guard_all() -> None:
    """Reset all tracker timestamps and flags (primarily for unit tests)."""
    with _TRACKER_LOCK:
        _TRACKER.reset_all()


def set_pending_lobby_reentry(flag: bool) -> None:
    """Set or clear the pending lobby-reentry flag for pipeline loop recovery nodes."""
    with _TRACKER_LOCK:
        _TRACKER.pending_lobby_reentry = bool(flag)


def consume_pending_lobby_reentry() -> bool:
    """Atomically read and clear the pending lobby-reentry flag."""
    with _TRACKER_LOCK:
        flag = bool(_TRACKER.pending_lobby_reentry)
        _TRACKER.pending_lobby_reentry = False
        return flag


def _get_guard_mode() -> str:
    return str(getattr(_GUARD_TLS, "mode", "normal") or "normal")


def _get_restart_depth() -> int:
    return int(getattr(_GUARD_TLS, "restart_aware_depth", 0) or 0)


@contextmanager
def _guard_mode(mode: str) -> Iterator[None]:
    prev = _get_guard_mode()
    _GUARD_TLS.mode = mode
    try:
        yield
    finally:
        _GUARD_TLS.mode = prev


@contextmanager
def _restart_aware_scope() -> Iterator[None]:
    depth = _get_restart_depth()
    _GUARD_TLS.restart_aware_depth = depth + 1
    try:
        yield
    finally:
        _GUARD_TLS.restart_aware_depth = depth


def _is_stopping(context: Any) -> bool:
    tasker = getattr(context, "tasker", None)
    return getattr(tasker, "stopping", False) is True


def _request_task_stop(context: Any) -> None:
    tasker = getattr(context, "tasker", None)
    post_stop = getattr(tasker, "post_stop", None)
    if callable(post_stop):
        try:
            post_stop()
        except Exception:
            pass


def _is_adb_controller(context: Any) -> bool:
    info = get_effective_controller_info(context)
    ctrl_type = str(info.get("type") or "").strip().lower() if isinstance(info, dict) else ""
    if ctrl_type:
        return ctrl_type == "adb"
    ctrl = getattr(getattr(context, "tasker", None), "controller", None)
    cls_name = type(ctrl).__name__.lower() if ctrl is not None else ""
    return "adb" in cls_name


def _parse_int(value: Any, default: int, *, minimum: int = 0) -> int:
    if isinstance(value, bool):
        return default
    try:
        parsed = int(value)
        return max(minimum, parsed)
    except (TypeError, ValueError):
        return default


def _parse_float(value: Any, default: float, *, minimum: float = 0.1) -> float:
    if isinstance(value, bool):
        return default
    try:
        parsed = float(value)
        return max(minimum, parsed)
    except (TypeError, ValueError):
        return default


def resolve_network_guard_config(context: Any) -> dict[str, Any]:
    """Read network guard settings from sibling attach nodes, safely ignoring non-dict/Mock values."""
    cfg: dict[str, Any] = {
        "enabled": False,
        "max_retries": DEFAULT_MAX_RETRIES,
        "window_sec": DEFAULT_WINDOW_SEC,
        "retry_wait_sec": DEFAULT_RETRY_WAIT_SEC,
        "adb_auto_restart": True,
        "pc_popup_alert": True,
        "max_restarts": DEFAULT_MAX_RESTARTS,
        "restart_window_sec": DEFAULT_RESTART_WINDOW_SEC,
    }
    get_node_data = getattr(context, "get_node_data", None)
    if not callable(get_node_data):
        return cfg

    for node_name in NETWORK_GUARD_ATTACH_NODES:
        try:
            node_data = get_node_data(node_name)
        except Exception:
            node_data = None
        if not isinstance(node_data, dict):
            continue
        attach = node_data.get("attach")
        if not isinstance(attach, dict):
            continue
        if "enabled" in attach:
            cfg["enabled"] = attach.get("enabled") is True
        if "max_retries" in attach:
            cfg["max_retries"] = _parse_int(attach.get("max_retries"), cfg["max_retries"], minimum=1)
        if "window_sec" in attach:
            cfg["window_sec"] = _parse_float(attach.get("window_sec"), cfg["window_sec"], minimum=1.0)
        if "retry_wait_sec" in attach:
            cfg["retry_wait_sec"] = _parse_float(attach.get("retry_wait_sec"), cfg["retry_wait_sec"], minimum=0.1)
        if "adb_auto_restart" in attach and isinstance(attach.get("adb_auto_restart"), bool):
            cfg["adb_auto_restart"] = attach["adb_auto_restart"]
        if "pc_popup_alert" in attach and isinstance(attach.get("pc_popup_alert"), bool):
            cfg["pc_popup_alert"] = attach["pc_popup_alert"]
        if "max_restarts" in attach:
            cfg["max_restarts"] = _parse_int(attach.get("max_restarts"), cfg["max_restarts"], minimum=0)
        if "restart_window_sec" in attach:
            cfg["restart_window_sec"] = _parse_float(
                attach.get("restart_window_sec"), cfg["restart_window_sec"], minimum=1.0
            )
    return cfg


def show_network_alert_popup(
    title: str,
    message: str,
    *,
    non_blocking: bool = True,
    alert_handler: Callable[[str, str], Any] | None = None,
) -> bool:
    """Display an alert dialog on Windows without blocking the Agent IPC loop."""
    handler = alert_handler or _ALERT_HANDLER
    if handler is not None:
        handler(str(title), str(message))
        return True
    if sys.platform != "win32":
        return False

    import ctypes

    # MB_OK (0x0) | MB_ICONWARNING (0x30) | MB_SETFOREGROUND (0x10000) | MB_TOPMOST (0x40000)
    flags = 0x00050030
    t_str = str(title)
    m_str = str(message)

    def _show() -> None:
        try:
            ctypes.windll.user32.MessageBoxW(None, m_str, t_str, flags)
        except Exception:
            pass

    if non_blocking:
        threading.Thread(target=_show, name="maa-network-alert", daemon=True).start()
    else:
        _show()
    return True


def detect_network_poor_popup(
    context: Any,
    image: Any,
    *,
    prefix: str = "NetGuard",
) -> tuple[bool, tuple[int, int] | None]:
    """Two-stage detector: L1 pixel pre-screen followed by small-ROI OCR verification."""
    if image is None or not is_network_poor_popup_pixels(image):
        return False, None

    text_entries = ocr_roi(context, image, f"{prefix}Text", NETWORK_POOR_TEXT_ROI)
    if not is_network_poor_popup_entries(text_entries):
        return False, None

    btn_entries = ocr_roi(context, image, f"{prefix}Confirm", NETWORK_POOR_CONFIRM_ROI)
    return True, find_network_poor_confirm_point(btn_entries)


def _invoke_wake_up_to_lobby(context: Any, *, prefix: str) -> bool:
    wake_fn = run_wake_up_to_lobby
    if wake_fn is None:
        import agent.wake_up_action as wake_up_action

        wake_fn = wake_up_action.run_wake_up_to_lobby
    return bool(
        wake_fn(
            context,
            prefix=prefix,
            auto_launch_adb=True,
            auto_confirm_small_update=True,
            allow_blind_dismiss=True,
            max_download_mb=200.0,
            max_steps=42,
        )
    )


def _restart_adb_to_lobby(context: Any, *, prefix: str) -> bool:
    tasker = getattr(context, "tasker", None)
    controller = getattr(tasker, "controller", None)
    if controller is None:
        print("[NetworkGuard] 无法获取 ADB 控制器，大退重启失败。", flush=True)
        return False

    stop_fn = getattr(controller, "post_stop_app", None)
    start_fn = getattr(controller, "post_start_app", None)
    if not callable(stop_fn) or not callable(start_fn):
        print("[NetworkGuard] 当前控制器不支持 post_stop_app/post_start_app。", flush=True)
        return False

    stop_job = stop_fn(GAME_ANDROID_PACKAGE)
    if hasattr(stop_job, "wait"):
        stop_job.wait()
    if not sleep_with_stop(context, 3.0):
        return False

    start_job = start_fn(GAME_ANDROID_PACKAGE)
    if hasattr(start_job, "wait"):
        start_job.wait()
    if not sleep_with_stop(context, 6.0):
        return False

    with _guard_mode("confirm_only"):
        return _invoke_wake_up_to_lobby(context, prefix=f"{prefix}RestartWakeUp")


def _emit_stop_alert(
    context: Any,
    *,
    show_popup: bool,
    title: str,
    message: str,
    alert_fn: Callable[[str, str], Any] | None = None,
) -> None:
    print(f"[NetworkGuard] {message}", flush=True)
    should_pop = False
    with _TRACKER_LOCK:
        if show_popup and not _TRACKER.alerted:
            _TRACKER.alerted = True
            should_pop = True
    if should_pop:
        if alert_fn is not None:
            alert_fn(title, message)
        else:
            show_network_alert_popup(title, message, non_blocking=True)
    _request_task_stop(context)


def handle_network_poor_popup(
    context: Any,
    image: Any,
    *,
    raw_screencap_fn: Callable[[Any], Any | None],
    prefix: str = "NetGuard",
    allow_restart_exception: bool = True,
    alert_fn: Callable[[str, str], Any] | None = None,
) -> tuple[Any | None, str]:
    """Inspect a captured frame and handle any network reconnect popup with retry/restart/stop."""
    cfg = resolve_network_guard_config(context)
    prev_mode = _get_guard_mode()
    if not cfg["enabled"] or prev_mode == "bypass":
        return image, "clean"

    cur_img = image
    handled = 0
    max_loop = max(4, int(cfg["max_retries"]) + 2)

    with _guard_mode("bypass"):
        for idx in range(max_loop):
            if _is_stopping(context):
                return None, "stopped"

            detected, confirm_pt = detect_network_poor_popup(context, cur_img, prefix=f"{prefix}_{idx}")
            if not detected:
                return cur_img, ("clean" if handled == 0 else "reconnected")

            tap_target = confirm_pt or NETWORK_POOR_DEFAULT_CONFIRM_POINT
            if prev_mode == "confirm_only":
                if handled >= 3:
                    return cur_img, "reconnected"
                print("[NetworkGuard] 重启引导期检测到网络不佳弹窗，点击「确认」等待恢复...", flush=True)
                if not tap_point(context, f"{prefix}ConfirmOnly_{idx}", tap_target):
                    return None, "stopped"
                handled += 1
                if not sleep_with_stop(context, float(cfg["retry_wait_sec"])):
                    return None, "stopped"
                cur_img = raw_screencap_fn(context)
                if cur_img is None:
                    return None, "stopped"
                continue

            is_adb = _is_adb_controller(context)
            with _TRACKER_LOCK:
                decision = _TRACKER.decide_on_popup(
                    is_adb=is_adb,
                    adb_auto_restart=bool(cfg["adb_auto_restart"]),
                    pc_popup_alert=bool(cfg["pc_popup_alert"]),
                    max_retries=int(cfg["max_retries"]),
                    window_sec=float(cfg["window_sec"]),
                    max_restarts=int(cfg["max_restarts"]),
                    restart_window_sec=float(cfg["restart_window_sec"]),
                )

            action = decision["action"]
            if action == "retry_confirm":
                attempt = int(decision["attempt"])
                limit = int(decision["max_retries"])
                win_sec = int(round(float(cfg["window_sec"])))
                print(
                    f"[NetworkGuard] 检测到网络不佳弹窗，点击「确认」重试（第 {attempt}/{limit} 次，{win_sec}s 窗口内）...",
                    flush=True,
                )
                handled += 1
                if not tap_point(context, f"{prefix}Retry_{attempt}", tap_target):
                    return None, "stopped"
                if not sleep_with_stop(context, float(cfg["retry_wait_sec"])):
                    return None, "stopped"
                cur_img = raw_screencap_fn(context)
                if cur_img is None:
                    return None, "stopped"
                continue

            if action == "adb_restart":
                print(
                    f"[NetworkGuard] ADB 端短期内重试达上限（{decision['attempt']}/{decision['max_retries']}），"
                    f"暂停当前任务并大退重启游戏（第 {decision['restart_count']}/{decision['max_restarts']} 次）...",
                    flush=True,
                )
                ok = _restart_adb_to_lobby(context, prefix=prefix)
                if not ok:
                    if not _is_stopping(context):
                        _emit_stop_alert(
                            context,
                            show_popup=True,
                            title="MaaResonance 网络重连提醒",
                            message="模拟器大退重启并恢复至列车大厅失败，已停止当前任务，请手动检查游戏状态。",
                            alert_fn=alert_fn,
                        )
                    return None, "stopped"

                with _TRACKER_LOCK:
                    _TRACKER.reset_retries()
                    _TRACKER.pending_lobby_reentry = True

                lobby_img = raw_screencap_fn(context)
                if lobby_img is None:
                    return None, "stopped"

                if allow_restart_exception and _get_restart_depth() > 0:
                    raise NetworkRestartedToLobbyError("ADB game restarted and returned to lobby")
                return lobby_img, "restarted_to_lobby"

            if action == "pc_alert_stop":
                _emit_stop_alert(
                    context,
                    show_popup=bool(decision.get("show_popup", True)),
                    title="MaaResonance 网络重连提醒",
                    message=(
                        f"PC 端短期内连续重试 {decision['attempt']}/{decision['max_retries']} 次仍提示网络不佳，"
                        "已保留游戏进程并停止当前任务，请手动大退重开《雷索纳斯》。"
                    ),
                    alert_fn=alert_fn,
                )
                return None, "stopped"

            if action == "stop_max_restarts":
                _emit_stop_alert(
                    context,
                    show_popup=True,
                    title="MaaResonance 网络重连提醒",
                    message=(
                        f"模拟器端在窗口期内已自动大退重启 {decision['restart_count']}/{decision['max_restarts']} 次"
                        "仍遇到网络不佳，已停止当前任务防止死循环，请检查网络或手动重启。"
                    ),
                    alert_fn=alert_fn,
                )
                return None, "stopped"

            # adb_alert_stop
            _emit_stop_alert(
                context,
                show_popup=True,
                title="MaaResonance 网络重连提醒",
                message=(
                    f"模拟器端短期内连续重试 {decision['attempt']}/{decision['max_retries']} 次仍提示网络不佳"
                    "（未开启自动大退重启），已停止当前任务。"
                ),
                alert_fn=alert_fn,
            )
            return None, "stopped"

    return cur_img, ("clean" if handled == 0 else "reconnected")


def guard_screencap_frame(
    context: Any,
    image: Any,
    *,
    raw_screencap_fn: Callable[[Any], Any | None],
) -> Any | None:
    """Fast hook called by safe_screencap() before returning a frame to callers."""
    if image is None or _get_guard_mode() == "bypass":
        return image
    cfg = resolve_network_guard_config(context)
    if not cfg["enabled"]:
        return image
    new_img, status = handle_network_poor_popup(
        context,
        image,
        raw_screencap_fn=raw_screencap_fn,
        prefix="NetGuard",
        allow_restart_exception=True,
    )
    if status == "stopped":
        return None
    return new_img


def _clone_result(value: Any) -> Any:
    cls = type(value)
    if cls.__name__ == "RunResult" and hasattr(value, "success"):
        return cls(success=bool(value.success))
    return value


def retry_on_network_restart(
    max_restarts: int = 2,
    *,
    failure_value: Any = False,
) -> Callable[[F], F]:
    """Decorator for lobby-entry idempotent actions: re-run from start after an ADB restart."""
    limit = max(0, int(max_restarts))

    def _decorator(fn: F) -> F:
        @functools.wraps(fn)
        def _wrapper(*args: Any, **kwargs: Any) -> Any:
            for attempt in range(limit + 1):
                try:
                    with _restart_aware_scope():
                        return fn(*args, **kwargs)
                except NetworkRestartedToLobbyError:
                    consume_pending_lobby_reentry()
                    if attempt < limit:
                        print(
                            f"[NetworkGuard] 已大退重启回到列车大厅，重跑 {fn.__name__}（第 {attempt + 1}/{limit} 次恢复）...",
                            flush=True,
                        )
                        continue
                    print(
                        f"[NetworkGuard] {fn.__name__} 恢复次数达上限（{limit}），停止当前任务。",
                        flush=True,
                    )
                    for arg in args:
                        if hasattr(arg, "tasker"):
                            _request_task_stop(arg)
                            break
                    return _clone_result(failure_value)
            return _clone_result(failure_value)

        return _wrapper  # type: ignore[return-value]

    return _decorator


def exit_on_network_restart(return_value: Any = True) -> Callable[[F], F]:
    """Decorator for sub-loop actions: exit cleanly to parent loop after an ADB restart."""

    def _decorator(fn: F) -> F:
        @functools.wraps(fn)
        def _wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                with _restart_aware_scope():
                    return fn(*args, **kwargs)
            except NetworkRestartedToLobbyError:
                print(
                    f"[NetworkGuard] 已大退重启回到列车大厅，退出子流程 {fn.__name__} 交回主循环恢复。",
                    flush=True,
                )
                return _clone_result(return_value)

        return _wrapper  # type: ignore[return-value]

    return _decorator
