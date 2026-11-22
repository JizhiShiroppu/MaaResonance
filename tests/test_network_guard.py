from __future__ import annotations

from contextlib import contextmanager
import importlib
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import numpy as np

from maa_resonance.logic.network_guard import (
    GAME_ANDROID_PACKAGE,
    NETWORK_POOR_DEFAULT_CONFIRM_POINT,
    NetworkGuardTracker,
    find_network_poor_confirm_point,
    is_network_poor_popup_entries,
    is_network_poor_popup_pixels,
)

ROOT = Path(__file__).resolve().parents[1]


@contextmanager
def _real_maa_resource():
    saved = {}
    maa_mod = sys.modules.get("maa")
    stashed = maa_mod is not None and not hasattr(maa_mod, "__path__")
    if stashed:
        for name in list(sys.modules):
            if name == "maa" or name.startswith("maa."):
                saved[name] = sys.modules.pop(name)
    try:
        try:
            resource_mod = importlib.import_module("maa.resource")
            yield resource_mod.Resource
        except ImportError:
            yield None
    finally:
        if stashed:
            for name in list(sys.modules):
                if name == "maa" or name.startswith("maa."):
                    sys.modules.pop(name, None)
            sys.modules.update(saved)


def _make_network_popup_bgr(width: int = 1280, height: int = 720) -> np.ndarray:
    """Create a synthetic 720p-proportioned BGR frame matching the network reconnect popup layout."""
    img = np.full((height, width, 3), 24, dtype=np.uint8)
    sx = width / 1280.0
    sy = height / 720.0

    def _rect(x1: int, y1: int, x2: int, y2: int, bgr: tuple[int, int, int]) -> None:
        ix1, ix2 = int(round(x1 * sx)), int(round(x2 * sx))
        iy1, iy2 = int(round(y1 * sy)), int(round(y2 * sy))
        img[iy1:iy2, ix1:ix2] = bgr

    # Dark blue-gray modal band
    _rect(0, 266, 1280, 456, (37, 30, 27))
    # Top bright blue horizontal border line
    _rect(0, 260, 1280, 265, (184, 100, 62))
    # Left gray '取消' button
    _rect(20, 470, 615, 535, (80, 80, 80))
    # Right bright blue '确认' button
    _rect(665, 470, 1260, 535, (231, 114, 59))
    return img


def _make_clean_bgr(width: int = 1280, height: int = 720) -> np.ndarray:
    return np.full((height, width, 3), 220, dtype=np.uint8)


class NetworkGuardLogicTest(unittest.TestCase):
    def test_pixel_prescreen_matches_popup_and_rejects_other_frames(self) -> None:
        popup_720 = _make_network_popup_bgr(1280, 720)
        popup_1080 = _make_network_popup_bgr(1920, 1080)
        self.assertTrue(is_network_poor_popup_pixels(popup_720))
        self.assertTrue(is_network_poor_popup_pixels(popup_1080))

        self.assertFalse(is_network_poor_popup_pixels(None))
        self.assertFalse(is_network_poor_popup_pixels("not_an_image"))
        self.assertFalse(is_network_poor_popup_pixels(_make_clean_bgr()))
        self.assertFalse(is_network_poor_popup_pixels(np.zeros((720, 1280, 3), dtype=np.uint8)))

        # Missing top bright blue border line
        no_line = popup_720.copy()
        no_line[258:267, :] = (37, 30, 27)
        self.assertFalse(is_network_poor_popup_pixels(no_line))

        # Missing right bright blue confirm button
        no_blue_btn = popup_720.copy()
        no_blue_btn[470:535, 665:1260] = (80, 80, 80)
        self.assertFalse(is_network_poor_popup_pixels(no_blue_btn))

    def test_ocr_text_matching_and_confirm_button_resolution(self) -> None:
        self.assertTrue(is_network_poor_popup_entries([{"text": "当前网络不佳，请尝试重新连接"}]))
        self.assertTrue(is_network_poor_popup_entries([{"text": "网络不佳"}, {"text": "重新连接"}]))
        self.assertFalse(is_network_poor_popup_entries([{"text": "当前关卡难度过高，是否仍要继续挑战？"}]))
        self.assertFalse(is_network_poor_popup_entries([]))

        self.assertEqual(
            find_network_poor_confirm_point([
                {"text": "确认", "box": [200, 484, 56, 36]},  # left side should be ignored
                {"text": "确认", "box": [955, 484, 56, 36]},
            ]),
            (983, 502),
        )
        self.assertEqual(find_network_poor_confirm_point([]), NETWORK_POOR_DEFAULT_CONFIRM_POINT)

    def test_tracker_sliding_window_adb_restart_and_pc_alert(self) -> None:
        now = [100.0]
        tracker = NetworkGuardTracker(
            max_retries=10,
            window_sec=120.0,
            max_restarts=2,
            restart_window_sec=900.0,
            clock=lambda: now[0],
        )

        # Retries 1..9 -> retry_confirm
        for i in range(1, 10):
            dec = tracker.decide_on_popup(is_adb=True, adb_auto_restart=True, pc_popup_alert=True)
            self.assertEqual(dec["action"], "retry_confirm")
            self.assertEqual(dec["attempt"], i)
            now[0] += 2.0

        # 10th within 120s on ADB -> adb_restart (1/2)
        dec10 = tracker.decide_on_popup(is_adb=True, adb_auto_restart=True, pc_popup_alert=True)
        self.assertEqual(dec10["action"], "adb_restart")
        self.assertEqual(dec10["restart_count"], 1)

        # Advance 130s so window expires after 1st retry; 9 retries again don't immediately restart
        for _ in range(9):
            tracker.decide_on_popup(is_adb=True, adb_auto_restart=True, pc_popup_alert=True)
            now[0] += 1.0
        dec_restart2 = tracker.decide_on_popup(is_adb=True, adb_auto_restart=True, pc_popup_alert=True)
        self.assertEqual(dec_restart2["action"], "adb_restart")
        self.assertEqual(dec_restart2["restart_count"], 2)

        # 3rd restart inside 900s -> stop_max_restarts
        for _ in range(9):
            tracker.decide_on_popup(is_adb=True, adb_auto_restart=True, pc_popup_alert=True)
            now[0] += 1.0
        dec_cap = tracker.decide_on_popup(is_adb=True, adb_auto_restart=True, pc_popup_alert=True)
        self.assertEqual(dec_cap["action"], "stop_max_restarts")

        # Window expiration clears old retries
        tracker.reset_all()
        for _ in range(5):
            tracker.decide_on_popup(is_adb=False, adb_auto_restart=True, pc_popup_alert=True)
            now[0] += 1.0
        now[0] += 125.0  # all 5 expired
        dec_after_expire = tracker.decide_on_popup(is_adb=False, adb_auto_restart=True, pc_popup_alert=True)
        self.assertEqual(dec_after_expire["action"], "retry_confirm")
        self.assertEqual(dec_after_expire["attempt"], 1)

        # PC 10th -> pc_alert_stop
        for _ in range(8):
            tracker.decide_on_popup(is_adb=False, adb_auto_restart=True, pc_popup_alert=True)
        pc_stop = tracker.decide_on_popup(is_adb=False, adb_auto_restart=True, pc_popup_alert=True)
        self.assertEqual(pc_stop["action"], "pc_alert_stop")
        self.assertTrue(pc_stop["show_popup"])


class NetworkGuardRuntimeTest(unittest.TestCase):
    def _make_guard_context(
        self,
        *,
        enabled: bool,
        ctrl_type: str,
        frames: list[np.ndarray],
        max_retries: int = 10,
        adb_auto_restart: bool = True,
        pc_popup_alert: bool = True,
    ):
        idx = {"i": 0}
        stop_called = {"count": 0}
        stopped_apps: list[str] = []
        started_apps: list[str] = []

        class _FakeController:
            def __init__(self) -> None:
                self.info = {"type": ctrl_type}
                self.cached_image = frames[0]

            def post_screencap(self):
                i = min(idx["i"], len(frames) - 1)
                self.cached_image = frames[i]
                idx["i"] += 1
                return SimpleNamespace(wait=lambda: SimpleNamespace(succeeded=True))

            def post_stop_app(self, pkg: str):
                stopped_apps.append(pkg)
                return SimpleNamespace(wait=lambda: SimpleNamespace(succeeded=True))

            def post_start_app(self, pkg: str):
                started_apps.append(pkg)
                return SimpleNamespace(wait=lambda: SimpleNamespace(succeeded=True))

        ctrl = _FakeController()
        tasker = SimpleNamespace(
            stopping=False,
            controller=ctrl,
            post_stop=lambda: stop_called.__setitem__("count", stop_called["count"] + 1),
        )

        node_map = {
            "CommonNetworkGuardConfig": {
                "attach": {
                    "enabled": enabled,
                    "max_retries": max_retries,
                    "window_sec": 120.0,
                    "retry_wait_sec": 0.1,
                    "adb_auto_restart": adb_auto_restart,
                    "pc_popup_alert": pc_popup_alert,
                    "max_restarts": 2,
                    "restart_window_sec": 900.0,
                }
            },
            "CommonNetworkGuardOptRetryLimit": {"attach": {"max_retries": max_retries, "window_sec": 120.0}},
            "CommonNetworkGuardOptAdbRestart": {"attach": {"adb_auto_restart": adb_auto_restart}},
            "CommonNetworkGuardOptPcAlert": {"attach": {"pc_popup_alert": pc_popup_alert}},
        }
        ctx = SimpleNamespace(tasker=tasker, get_node_data=lambda name: node_map.get(name))
        return ctx, stop_called, stopped_apps, started_apps

    def test_disabled_or_mock_context_is_noop(self) -> None:
        from agent.utils.input_guard import clear_recorded_controller_info, safe_screencap
        from agent.utils.network_guard import reset_network_guard_all, resolve_network_guard_config

        clear_recorded_controller_info()
        reset_network_guard_all()
        self.addCleanup(reset_network_guard_all)

        # Mock context must resolve to disabled (never truthy Mock leak).
        mock_ctx = Mock()
        mock_ctx.tasker.stopping = False
        self.assertFalse(resolve_network_guard_config(mock_ctx)["enabled"])

        popup = _make_network_popup_bgr()
        ctx, stop_called, stopped_apps, started_apps = self._make_guard_context(
            enabled=False,
            ctrl_type="win32",
            frames=[popup],
        )
        with patch("agent.utils.network_guard.ocr_roi") as mock_ocr:
            out = safe_screencap(ctx)
        self.assertIs(out, popup)
        mock_ocr.assert_not_called()
        self.assertEqual(stop_called["count"], 0)
        self.assertEqual(stopped_apps, [])
        self.assertEqual(started_apps, [])

    def test_silent_retry_reconnects_within_limit(self) -> None:
        from agent.utils.input_guard import clear_recorded_controller_info, safe_screencap
        from agent.utils.network_guard import reset_network_guard_all

        clear_recorded_controller_info()
        reset_network_guard_all()
        self.addCleanup(reset_network_guard_all)

        popup = _make_network_popup_bgr()
        clean = _make_clean_bgr()
        ctx, stop_called, _, _ = self._make_guard_context(
            enabled=True,
            ctrl_type="win32",
            frames=[popup, popup, clean],
            max_retries=10,
        )
        taps: list[tuple[str, tuple[int, int]]] = []

        def fake_ocr(_ctx, _img, name: str, _roi):
            if "Text" in name:
                return [{"text": "当前网络不佳，请尝试重新连接"}]
            if "Confirm" in name:
                return [{"text": "确认", "box": [955, 484, 56, 36]}]
            return []

        with (
            patch("agent.utils.network_guard.ocr_roi", side_effect=fake_ocr),
            patch("agent.utils.network_guard.tap_point", side_effect=lambda _c, n, pt: taps.append((n, pt)) or True),
            patch("agent.utils.network_guard.sleep_with_stop", return_value=True),
        ):
            out = safe_screencap(ctx)

        self.assertIs(out, clean)
        self.assertEqual(len(taps), 2)
        self.assertEqual(taps[0][1], (983, 502))
        self.assertEqual(stop_called["count"], 0)

    def test_pc_max_retries_alerts_and_stops_without_killing_game(self) -> None:
        from agent.utils.input_guard import clear_recorded_controller_info, safe_screencap
        from agent.utils.network_guard import reset_network_guard_all
        import agent.utils.network_guard as ng

        clear_recorded_controller_info()
        reset_network_guard_all()
        self.addCleanup(reset_network_guard_all)

        popup = _make_network_popup_bgr()
        ctx, stop_called, stopped_apps, started_apps = self._make_guard_context(
            enabled=True,
            ctrl_type="win32",
            frames=[popup] * 12,
            max_retries=10,
            pc_popup_alert=True,
        )
        alerts: list[tuple[str, str]] = []
        taps: list[tuple[int, int]] = []

        def fake_ocr(_ctx, _img, name: str, _roi):
            if "Text" in name:
                return [{"text": "当前网络不佳，请尝试重新连接"}]
            return [{"text": "确认", "box": [955, 484, 56, 36]}]

        with (
            patch("agent.utils.network_guard.ocr_roi", side_effect=fake_ocr),
            patch("agent.utils.network_guard.tap_point", side_effect=lambda _c, _n, pt: taps.append(pt) or True),
            patch("agent.utils.network_guard.sleep_with_stop", return_value=True),
            patch.object(ng, "_ALERT_HANDLER", side_effect=lambda t, m: alerts.append((t, m))),
        ):
            out = safe_screencap(ctx)

        self.assertIsNone(out)
        self.assertEqual(len(taps), 9)
        self.assertEqual(len(alerts), 1)
        self.assertIn("PC 端", alerts[0][1])
        self.assertEqual(stop_called["count"], 1)
        self.assertEqual(stopped_apps, [])
        self.assertEqual(started_apps, [])

    def test_adb_max_retries_restarts_and_recovers_retry_and_exit_scopes(self) -> None:
        from agent.utils.input_guard import clear_recorded_controller_info, safe_screencap
        from agent.utils.network_guard import (
            consume_pending_lobby_reentry,
            exit_on_network_restart,
            reset_network_guard_all,
            retry_on_network_restart,
        )
        import agent.utils.network_guard as ng

        clear_recorded_controller_info()
        reset_network_guard_all()
        self.addCleanup(reset_network_guard_all)

        popup = _make_network_popup_bgr()
        clean = _make_clean_bgr()

        # 1. @retry_on_network_restart: initial run hits 3rd popup -> restarts -> reruns cleanly & consumes flag
        ctx1, stop1, stopped1, started1 = self._make_guard_context(
            enabled=True,
            ctrl_type="adb",
            frames=[popup, popup, popup, clean, clean],
            max_retries=3,
        )
        runs = {"count": 0}

        @retry_on_network_restart(max_restarts=2)
        def entry_action(c):
            runs["count"] += 1
            frame = safe_screencap(c)
            self.assertIs(frame, clean)
            return "done"

        def fake_ocr(_ctx, _img, name: str, _roi):
            if "Text" in name:
                return [{"text": "当前网络不佳，请尝试重新连接"}]
            return [{"text": "确认", "box": [955, 484, 56, 36]}]

        with (
            patch("agent.utils.network_guard.ocr_roi", side_effect=fake_ocr),
            patch("agent.utils.network_guard.tap_point", return_value=True),
            patch("agent.utils.network_guard.sleep_with_stop", return_value=True),
            patch.object(ng, "run_wake_up_to_lobby", return_value=True) as mock_wake,
        ):
            res = entry_action(ctx1)

        self.assertEqual(res, "done")
        self.assertEqual(runs["count"], 2)
        self.assertEqual(stopped1, [GAME_ANDROID_PACKAGE])
        self.assertEqual(started1, [GAME_ANDROID_PACKAGE])
        self.assertEqual(stop1["count"], 0)
        self.assertEqual(mock_wake.call_count, 1)
        self.assertFalse(consume_pending_lobby_reentry())

        # 2. @exit_on_network_restart: exits sub-loop cleanly and preserves flag for loop reenter node
        reset_network_guard_all()
        ctx2, stop2, stopped2, started2 = self._make_guard_context(
            enabled=True,
            ctrl_type="adb",
            frames=[popup, popup, popup, clean],
            max_retries=3,
        )

        @exit_on_network_restart(return_value="exited_to_loop")
        def sub_loop(c):
            safe_screencap(c)
            return "unreachable"

        with (
            patch("agent.utils.network_guard.ocr_roi", side_effect=fake_ocr),
            patch("agent.utils.network_guard.tap_point", return_value=True),
            patch("agent.utils.network_guard.sleep_with_stop", return_value=True),
            patch.object(ng, "run_wake_up_to_lobby", return_value=True),
        ):
            sub_res = sub_loop(ctx2)

        self.assertEqual(sub_res, "exited_to_loop")
        self.assertEqual(stopped2, [GAME_ANDROID_PACKAGE])
        self.assertEqual(started2, [GAME_ANDROID_PACKAGE])
        self.assertEqual(stop2["count"], 0)
        self.assertTrue(consume_pending_lobby_reentry())
        self.assertFalse(consume_pending_lobby_reentry())

    def test_adb_restart_aborts_when_user_requests_stop(self) -> None:
        from agent.utils.input_guard import clear_recorded_controller_info, safe_screencap
        from agent.utils.network_guard import reset_network_guard_all
        import agent.utils.network_guard as ng

        clear_recorded_controller_info()
        reset_network_guard_all()
        self.addCleanup(reset_network_guard_all)

        popup = _make_network_popup_bgr()
        ctx, stop_called, _, _ = self._make_guard_context(
            enabled=True,
            ctrl_type="adb",
            frames=[popup] * 4,
            max_retries=2,
        )
        alerts: list[tuple[str, str]] = []

        def stop_during_wake(*_args, **_kwargs) -> bool:
            ctx.tasker.stopping = True
            return False

        def fake_ocr(_ctx, _img, name: str, _roi):
            if "Text" in name:
                return [{"text": "当前网络不佳，请尝试重新连接"}]
            return [{"text": "确认", "box": [955, 484, 56, 36]}]

        with (
            patch("agent.utils.network_guard.ocr_roi", side_effect=fake_ocr),
            patch("agent.utils.network_guard.tap_point", return_value=True),
            patch("agent.utils.network_guard.sleep_with_stop", return_value=True),
            patch.object(ng, "run_wake_up_to_lobby", side_effect=stop_during_wake),
            patch.object(ng, "_ALERT_HANDLER", side_effect=lambda t, m: alerts.append((t, m))),
        ):
            out = safe_screencap(ctx)

        self.assertIsNone(out)
        self.assertEqual(alerts, [])
        self.assertEqual(stop_called["count"], 0)

    def test_confirm_only_mode_clicks_confirm_without_recursive_restart(self) -> None:
        from agent.utils.input_guard import clear_recorded_controller_info, safe_screencap
        from agent.utils.network_guard import _guard_mode, reset_network_guard_all

        clear_recorded_controller_info()
        reset_network_guard_all()
        self.addCleanup(reset_network_guard_all)

        popup = _make_network_popup_bgr()
        clean = _make_clean_bgr()
        ctx, stop_called, stopped_apps, started_apps = self._make_guard_context(
            enabled=True,
            ctrl_type="adb",
            frames=[popup, popup, clean],
            max_retries=1,
        )
        taps: list[tuple[int, int]] = []

        def fake_ocr(_ctx, _img, name: str, _roi):
            if "Text" in name:
                return [{"text": "当前网络不佳，请尝试重新连接"}]
            return [{"text": "确认", "box": [955, 484, 56, 36]}]

        with (
            patch("agent.utils.network_guard.ocr_roi", side_effect=fake_ocr),
            patch("agent.utils.network_guard.tap_point", side_effect=lambda _c, _n, pt: taps.append(pt) or True),
            patch("agent.utils.network_guard.sleep_with_stop", return_value=True),
            _guard_mode("confirm_only"),
        ):
            out = safe_screencap(ctx)

        self.assertIs(out, clean)
        self.assertEqual(len(taps), 2)
        self.assertEqual(stop_called["count"], 0)
        self.assertEqual(stopped_apps, [])
        self.assertEqual(started_apps, [])

    def test_show_network_alert_popup_non_windows_returns_false(self) -> None:
        import agent.utils.network_guard as ng

        with patch.object(ng, "_ALERT_HANDLER", None), patch.object(ng.sys, "platform", "linux"):
            self.assertFalse(ng.show_network_alert_popup("title", "msg", non_blocking=False))

    def test_network_guard_action_recognition_and_task_sink(self) -> None:
        with _real_maa_resource() as Resource:
            if Resource is None:
                self.skipTest("maafw is not installed")

        # Exercise agent.network_guard_action in an isolated AgentServer-mode subprocess so
        # importing maa.agent.agent_server cannot pollute Library._is_agent_server in-process.
        script = f"""
import sys
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0, {str(ROOT)!r})
sys.path.insert(0, {str(ROOT / 'agent')!r})
import numpy as np
import agent.network_guard_action as nga
from agent.utils.network_guard import get_tracker, reset_network_guard_all, set_pending_lobby_reentry

popup = np.full((720, 1280, 3), 24, dtype=np.uint8)
popup[266:456, 0:1280] = (37, 30, 27)
popup[260:265, 0:1280] = (184, 100, 62)
popup[470:535, 20:615] = (80, 80, 80)
popup[470:535, 665:1260] = (231, 114, 59)
clean = np.full((720, 1280, 3), 220, dtype=np.uint8)

idx = {{"i": 0}}
frames = [popup, clean]
class _Ctrl:
    info = {{"type": "win32"}}
    cached_image = frames[0]
    def post_screencap(self):
        self.cached_image = frames[min(idx["i"], len(frames) - 1)]
        idx["i"] += 1
        return SimpleNamespace(wait=lambda: SimpleNamespace(succeeded=True))

node_map = {{
    "CommonNetworkGuardConfig": {{"attach": {{"enabled": True, "max_retries": 10, "window_sec": 120.0, "retry_wait_sec": 0.1}}}},
}}
ctx = SimpleNamespace(
    tasker=SimpleNamespace(stopping=False, controller=_Ctrl(), post_stop=lambda: None),
    get_node_data=lambda name: node_map.get(name),
)

reset_network_guard_all()
reco = nga.NetworkPoorPopupDetectRecognition()
with patch("agent.utils.network_guard.ocr_roi", side_effect=[
    [{{"text": "当前网络不佳，请尝试重新连接"}}],
    [{{"text": "确认", "box": [955, 484, 56, 36]}}],
]):
    hit = reco.analyze(ctx, SimpleNamespace(node_name="CommonNetworkPoorGuard", image=popup))
assert hit is not None and hit.detail == {{"kind": "network_poor_popup"}}

handler = nga.NetworkPoorPopupHandleAction()
with (
    patch("agent.utils.network_guard.ocr_roi", side_effect=[
        [{{"text": "当前网络不佳，请尝试重新连接"}}],
        [{{"text": "确认", "box": [955, 484, 56, 36]}}],
    ]),
    patch("agent.utils.network_guard.tap_point", return_value=True),
    patch("agent.utils.network_guard.sleep_with_stop", return_value=True),
):
    res = handler.run(ctx, SimpleNamespace(node_name="CommonNetworkPoorGuard"))
assert res.success is True

consume = nga.NetworkGuardConsumeRestartRecognition()
assert consume.analyze(ctx, SimpleNamespace(node_name="Reenter")) is None
set_pending_lobby_reentry(True)
reentry_hit = consume.analyze(ctx, SimpleNamespace(node_name="Reenter"))
assert reentry_hit is not None
assert consume.analyze(ctx, SimpleNamespace(node_name="Reenter")) is None

get_tracker().alerted = True
set_pending_lobby_reentry(True)
sink = nga.NetworkGuardTaskerSink()
noti = nga.NotificationType.Succeeded if nga.NotificationType is not None else SimpleNamespace(name="Succeeded")
sink.on_tasker_task(None, noti, None)
assert get_tracker().alerted is False
assert get_tracker().pending_lobby_reentry is False
"""
        proc = subprocess.run(
            [sys.executable, "-c", script],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, msg=proc.stderr or proc.stdout)


class NetworkGuardIntegrationTest(unittest.TestCase):
    def test_interface_pipeline_loops_and_resource_registration(self) -> None:
        iface = json.loads((ROOT / "assets/interface.json").read_text(encoding="utf-8"))
        self.assertEqual(iface.get("global_option"), ["NetworkReconnectGuard"])
        opts = iface.get("option") or {}
        guard_opt = opts["NetworkReconnectGuard"]
        self.assertEqual(guard_opt["default_case"], "No")
        self.assertEqual(opts["NetworkReconnectAdbAutoRestart"]["controller"], ["ADB"])
        self.assertEqual(
            opts["NetworkReconnectPcAlert"]["controller"],
            ["Win32", "Win32BackgroundWindowPos", "Win32BackgroundCursorPos"],
        )

        common_pipe = json.loads(
            (ROOT / "assets/resource/base/pipeline/common/network_guard.json").read_text(encoding="utf-8")
        )
        self.assertFalse(common_pipe["CommonNetworkPoorGuard"]["enabled"])
        self.assertFalse(common_pipe["CommonNetworkGuardConfig"]["attach"]["enabled"])
        for node in common_pipe.values():
            act = node.get("action")
            act_type = act.get("type") if isinstance(act, dict) else act
            self.assertNotIn(act_type, ("Click", "Swipe"))

        expected_loops = [
            ("assets/resource/base/pipeline/combat/security_agency.json", "SecurityAgencyLoop"),
            ("assets/resource/base/pipeline/combat/regional_combat.json", "RegionalCombatLoop"),
            ("assets/resource/base/pipeline/combat/calculation_recording.json", "CalculationRecordingLoop"),
            ("assets/resource/base/pipeline/mainline/mainline_advance.json", "MainlineAdvanceLoop"),
            ("assets/resource/base/pipeline/assist/assist_monitor.json", "AssistMonitorLoop"),
            ("assets/resource/base/pipeline/daily/coop_assault.json", "CoopAssaultLoop"),
            ("assets/resource/base/pipeline/daily/event_stage_farm.json", "EventStageFarmLoop"),
            ("assets/resource/base/pipeline/daily/event_story_daily.json", "EventStoryDailyLoop"),
            ("assets/resource/base/pipeline/business/common/state_recovery.json", "StateRecoveryStart"),
            ("assets/resource/base/pipeline/business/common/state_recovery.json", "StateRecoveryPostRestartStart"),
        ]
        for rel_path, loop_name in expected_loops:
            pipe = json.loads((ROOT / rel_path).read_text(encoding="utf-8"))
            self.assertEqual(pipe[loop_name]["next"][0], "[JumpBack]CommonNetworkPoorGuard", msg=f"{rel_path}:{loop_name}")

        with _real_maa_resource() as Resource:
            if Resource is None:
                self.skipTest("maafw is not installed")

        # Run Resource bundle verification in a clean framework-mode subprocess so earlier AgentServer imports
        # in the test runner cannot flip MaaFramework Library._is_agent_server.
        res_script = (
            "import sys; "
            f"sys.path.insert(0, {str(ROOT)!r}); "
            "from maa.resource import Resource; "
            "res = Resource(); "
            f"assert res.post_bundle({str(ROOT / 'assets/resource/base')!r}).wait().succeeded; "
            f"assert res.post_bundle({str(ROOT / 'assets/resource/pc')!r}).wait().succeeded; "
            "node = res.get_node_data('CommonNetworkPoorGuard'); "
            "assert node is not None and node['enabled'] is False; "
            "assert res.get_node_data('CommonNetworkGuardConfig') is not None; "
            "assert res.get_node_data('CoopAssaultAfterRestartReenter') is not None; "
            "assert res.get_node_data('EventStageFarmAfterRestartReenter') is not None; "
            "assert res.get_node_data('EventStoryDailyAfterRestartReenter') is not None; "
        )
        res_proc = subprocess.run(
            [sys.executable, "-c", res_script],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(res_proc.returncode, 0, msg=res_proc.stderr or res_proc.stdout)

        # Verify AgentServer custom recognition/action registration in an AgentServer-mode subprocess.
        agent_script = (
            "import sys; "
            f"sys.path.insert(0, {str(ROOT / 'agent')!r}); "
            f"sys.path.insert(0, {str(ROOT)!r}); "
            "from maa.agent.agent_server import AgentServer; "
            "import main; "
            "assert 'network_poor_popup_detect' in AgentServer._custom_recognition_holder; "
            "assert 'network_guard_consume_restart' in AgentServer._custom_recognition_holder; "
            "assert 'network_poor_popup_handle' in AgentServer._custom_action_holder; "
        )
        agent_proc = subprocess.run(
            [sys.executable, "-c", agent_script],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(agent_proc.returncode, 0, msg=agent_proc.stderr or agent_proc.stdout)


if __name__ == "__main__":
    unittest.main()
