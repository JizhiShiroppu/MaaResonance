"""Custom MaaFramework recognition, action, and task sink for NetworkReconnectGuard."""
from __future__ import annotations

from typing import Any

from maa.agent.agent_server import AgentServer
from maa.context import Context
from maa.custom_action import CustomAction
from maa.custom_recognition import CustomRecognition

try:
    from maa.event_sink import NotificationType
    from maa.tasker import Tasker, TaskerEventSink
except ImportError:  # pragma: no cover - lightweight test stubs without maa.tasker
    NotificationType = None  # type: ignore[assignment,misc]
    Tasker = Any  # type: ignore[assignment,misc]
    TaskerEventSink = None  # type: ignore[assignment,misc]

from agent.utils.input_guard import _raw_screencap
from agent.utils.network_guard import (
    consume_pending_lobby_reentry,
    detect_network_poor_popup,
    handle_network_poor_popup,
    reset_network_guard_task_state,
    resolve_network_guard_config,
)
from maa_resonance.logic.network_guard import NETWORK_POOR_DEFAULT_CONFIRM_POINT


@AgentServer.custom_recognition("network_poor_popup_detect")
class NetworkPoorPopupDetectRecognition(CustomRecognition):
    """Detect the '当前网络不佳，请尝试重新连接' popup when NetworkReconnectGuard is enabled."""

    def analyze(
        self,
        context: Context,
        argv: CustomRecognition.AnalyzeArg,
    ) -> CustomRecognition.AnalyzeResult | None:
        cfg = resolve_network_guard_config(context)
        if not cfg["enabled"]:
            return None
        image = getattr(argv, "image", None)
        if image is None:
            return None
        detected, confirm_pt = detect_network_poor_popup(
            context,
            image,
            prefix=f"{getattr(argv, 'node_name', 'NetGuard')}Detect",
        )
        if not detected:
            return None
        px, py = confirm_pt or NETWORK_POOR_DEFAULT_CONFIRM_POINT
        return CustomRecognition.AnalyzeResult(
            box=(max(0, px - 28), max(0, py - 18), 56, 36),
            detail={"kind": "network_poor_popup"},
        )


@AgentServer.custom_action("network_poor_popup_handle")
class NetworkPoorPopupHandleAction(CustomAction):
    """Handle detected network reconnect popups with retry, ADB restart, or PC alert/stop."""

    def run(self, context: Context, argv: CustomAction.RunArg) -> CustomAction.RunResult:
        img = _raw_screencap(context)
        if img is None:
            return CustomAction.RunResult(success=False)
        _, status = handle_network_poor_popup(
            context,
            img,
            raw_screencap_fn=_raw_screencap,
            prefix=str(getattr(argv, "node_name", "NetGuard") or "NetGuard"),
            allow_restart_exception=False,
        )
        return CustomAction.RunResult(success=(status != "stopped"))


@AgentServer.custom_recognition("network_guard_consume_restart")
class NetworkGuardConsumeRestartRecognition(CustomRecognition):
    """Consume pending lobby-reentry state after an ADB network restart so loops can re-navigate."""

    def analyze(
        self,
        context: Context,
        argv: CustomRecognition.AnalyzeArg,
    ) -> CustomRecognition.AnalyzeResult | None:
        _ = (context, argv)
        if consume_pending_lobby_reentry():
            return CustomRecognition.AnalyzeResult(
                box=(0, 0, 1, 1),
                detail={"restarted_to_lobby": True},
            )
        return None


def _is_task_lifecycle_notification(noti_type: Any) -> bool:
    if NotificationType is not None:
        return noti_type in (
            NotificationType.Starting,
            NotificationType.Succeeded,
            NotificationType.Failed,
        )
    return getattr(noti_type, "name", None) in ("Starting", "Succeeded", "Failed")


class NetworkGuardTaskerSink(TaskerEventSink if TaskerEventSink is not None else object):
    """Reset per-task alert and restart flags at task start/end boundaries."""

    def on_tasker_task(
        self,
        tasker: Tasker,
        noti_type: Any,
        detail: Any,
    ) -> None:
        _ = (tasker, detail)
        if _is_task_lifecycle_notification(noti_type):
            reset_network_guard_task_state()


if TaskerEventSink is not None and NotificationType is not None and hasattr(AgentServer, "tasker_sink"):
    if hasattr(AgentServer, "_set_api_properties"):
        AgentServer._set_api_properties()
    AgentServer.tasker_sink()(NetworkGuardTaskerSink)
