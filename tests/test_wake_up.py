from __future__ import annotations

from contextlib import contextmanager
import importlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np

from maa_resonance.logic.daily_routine import TOP_BACK_POINT, TOP_HOME_POINT
from maa_resonance.logic.wake_up import (
    WAKEUP_BLIND_DISMISS_POINT,
    WAKEUP_NEWS_DISMISS_POINT,
    WAKEUP_POPUP_DISMISS_POINTS,
    WAKEUP_POPUP_SAFE_POINT,
    WAKEUP_TITLE_TAP_POINT,
    choose_wake_up_action,
    is_game_screen_entries,
    is_loading_screen,
    is_login_auth_blocker,
    is_news_announcement_popup,
    is_subpage_screen,
    is_title_start_screen,
    parse_resource_download_mb,
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


class WakeUpLogicTest(unittest.TestCase):
    def test_download_news_title_loading_and_auth_blockers(self) -> None:
        self.assertAlmostEqual(
            parse_resource_download_mb([{"text": "需要下载资源包（共26.44MB）"}]),
            26.44,
        )
        self.assertAlmostEqual(
            parse_resource_download_mb([{"text": "需要下载资源包（共1.5GB）"}]),
            1536.0,
        )
        self.assertEqual(
            choose_wake_up_action(
                [
                    {"text": "需要下载资源包（共26.44MB）"},
                    {"text": "确认", "box": [600, 490, 80, 30]},
                ]
            ),
            {"action": "confirm_download", "point": (640, 505), "size_mb": 26.44},
        )
        large = choose_wake_up_action([{"text": "需要下载资源包（共1.5GB）"}])
        self.assertEqual(large["action"], "stop_large_download")

        self.assertTrue(is_login_auth_blocker([{"text": "请输入验证码"}]))
        self.assertEqual(choose_wake_up_action([{"text": "手机号登录"}])["action"], "stop_auth")

        news = [{"text": "资讯"}, {"text": "公告"}, {"text": "触碰空白区域退出"}]
        self.assertTrue(is_news_announcement_popup(news))
        self.assertEqual(choose_wake_up_action(news)["point"], WAKEUP_NEWS_DISMISS_POINT)

        title = [{"text": "点击屏幕进入游戏", "box": [558, 547, 163, 23]}]
        self.assertTrue(is_title_start_screen(title))
        self.assertEqual(choose_wake_up_action(title)["point"], WAKEUP_TITLE_TAP_POINT)

        loading = [{"text": "89%"}]
        self.assertTrue(is_loading_screen(loading))
        self.assertTrue(is_game_screen_entries(loading))
        self.assertEqual(choose_wake_up_action(loading)["action"], "wait")

        self.assertEqual(WAKEUP_POPUP_SAFE_POINT, (40, 360))
        self.assertEqual(WAKEUP_BLIND_DISMISS_POINT, (40, 360))
        self.assertNotIn((640, 680), WAKEUP_POPUP_DISMISS_POINTS)
        self.assertNotIn((200, 660), WAKEUP_POPUP_DISMISS_POINTS)
        self.assertTrue(all(pt[1] < 600 for pt in WAKEUP_POPUP_DISMISS_POINTS))

        monthly_popup = [{"text": "月卡每日领取"}, {"text": "触碰空白区域退出"}]
        self.assertEqual(
            choose_wake_up_action(monthly_popup),
            {"action": "dismiss_popup", "point": WAKEUP_POPUP_SAFE_POINT},
        )

        checkin_popup = [{"text": "每日签到奖励"}, {"text": "触碰空白区域退出"}]
        self.assertEqual(
            [choose_wake_up_action(checkin_popup, dismiss_attempt=idx)["point"] for idx in range(4)],
            list(WAKEUP_POPUP_DISMISS_POINTS),
        )

        self.assertEqual(
            choose_wake_up_action([{"text": "未知活动大图"}], allow_blind_dismiss=True, unknown_streak=2)["action"],
            "blind_dismiss",
        )

    def test_wake_up_regression_markers_and_subpage_back_priority(self) -> None:
        # Clipped title screen OCR from real PC log (2026-11-24 10:01:45)
        clipped_title = [{"text": "击屏幕进入游戏", "box": [576, 550, 144, 19]}]
        self.assertTrue(is_title_start_screen(clipped_title))
        self.assertTrue(is_game_screen_entries(clipped_title))
        self.assertEqual(
            choose_wake_up_action(clipped_title),
            {"action": "tap_title", "point": WAKEUP_TITLE_TAP_POINT},
        )

        # Birthday overlay & truncated blank-area dismiss hint
        birthday_popup = [{"text": "生日快乐"}, {"text": "空白区域退出"}]
        self.assertEqual(
            choose_wake_up_action(birthday_popup),
            {"action": "dismiss_popup", "point": (40, 360)},
        )
        self.assertEqual(
            choose_wake_up_action([{"text": "生日祝福"}]),
            {"action": "dismiss_popup", "point": (40, 360)},
        )

        # Loading hints observed in real logs
        for loading_txt in ("正在检测更新", "正在稳定列车的形态场", "81%"):
            entries = [{"text": loading_txt}]
            self.assertTrue(is_loading_screen(entries), msg=loading_txt)
            self.assertEqual(choose_wake_up_action(entries)["action"], "wait")

        # Train Power screen OCR from real log (2026-11-24 10:02:01)
        train_power_entries = [
            {"text": "耗电占比"},
            {"text": "电力等级"},
            {"text": "提升等级"},
            {"text": "列车电力"},
            {"text": "模块供电"},
            {"text": "引擎核心"},
        ]
        self.assertTrue(is_subpage_screen(train_power_entries))
        self.assertEqual(
            choose_wake_up_action(train_power_entries),
            {"action": "nav_back", "point": TOP_BACK_POINT},
        )

        # Priority: explicit popups must still override has_top_back/has_top_home
        self.assertEqual(
            choose_wake_up_action([{"text": "获得物品"}], has_top_back=True, has_top_home=True),
            {"action": "dismiss_popup", "point": (40, 360)},
        )
        self.assertEqual(
            choose_wake_up_action([{"text": "月卡"}], has_top_back=True),
            {"action": "dismiss_popup", "point": (40, 360)},
        )
        self.assertEqual(
            choose_wake_up_action([{"text": "资讯"}, {"text": "公告"}], has_top_back=True),
            {"action": "dismiss_news", "point": (40, 360)},
        )
        self.assertEqual(
            choose_wake_up_action([], has_top_back=True, has_top_home=True),
            {"action": "nav_home", "point": TOP_HOME_POINT},
        )
        self.assertEqual(
            choose_wake_up_action([], has_top_back=True, has_top_home=False),
            {"action": "nav_back", "point": TOP_BACK_POINT},
        )

    def test_wake_up_action_rotates_dismiss_points_on_consecutive_popups(self) -> None:
        with _real_maa_resource() as Resource:
            if Resource is None:
                self.skipTest("maafw is not installed")
            import agent.wake_up_action as wua

            img = np.zeros((720, 1280, 3), dtype=np.uint8)
            tapped: list[tuple[str, tuple[int, int]]] = []
            lobby_calls = {"count": 0}

            def fake_is_lobby(_ctx, name: str, _img) -> bool:
                if name.endswith("InitLobby"):
                    return False
                lobby_calls["count"] += 1
                # First two loop checks (L0, L1) see check-in popup; L2 + LVerify2 see lobby.
                return lobby_calls["count"] >= 3

            def fake_ocr(_ctx, _img, name: str, _roi):
                return [{"text": "每日签到奖励"}, {"text": "触碰空白区域退出"}]

            def fake_tap(_ctx, name: str, pt: tuple[int, int]) -> bool:
                tapped.append((name, pt))
                return True

            ctx = SimpleNamespace(tasker=SimpleNamespace(stopping=False), get_node_data=lambda _n: None)
            argv = SimpleNamespace(node_name="WakeUpStart", custom_action_param={})
            action = wua.WakeUpToLobbyAction()
            with (
                patch.object(wua, "safe_screencap", return_value=img),
                patch.object(wua, "is_drawer", return_value=(False, [])),
                patch.object(wua, "is_lobby", side_effect=fake_is_lobby),
                patch.object(wua, "ocr_roi", side_effect=fake_ocr),
                patch.object(wua, "tap_point", side_effect=fake_tap),
                patch.object(wua, "_is_adb_controller", return_value=False),
                patch.object(wua, "sleep_with_stop", return_value=True),
            ):
                res = action.run(ctx, argv)

            self.assertTrue(getattr(res, "success", True))
            self.assertEqual(
                tapped,
                [
                    ("WakeUpStartAct0_dismiss_popup", (40, 360)),
                    ("WakeUpStartAct1_dismiss_popup", (640, 28)),
                ],
            )

    def test_wake_up_action_rotates_blind_dismiss_across_wait_steps(self) -> None:
        with _real_maa_resource() as Resource:
            if Resource is None:
                self.skipTest("maafw is not installed")
            import agent.wake_up_action as wua

            img = np.zeros((720, 1280, 3), dtype=np.uint8)
            tapped: list[tuple[str, tuple[int, int]]] = []
            lobby_calls = {"count": 0}

            def fake_is_lobby(_ctx, name: str, _img) -> bool:
                if name.endswith("InitLobby"):
                    return False
                lobby_calls["count"] += 1
                # Steps 0..5 are non-lobby (wait, wait, blind_dismiss@0, wait, wait, blind_dismiss@1); L6 + LVerify6 = lobby.
                return lobby_calls["count"] >= 7

            def fake_tap(_ctx, name: str, pt: tuple[int, int]) -> bool:
                tapped.append((name, pt))
                return True

            ctx = SimpleNamespace(tasker=SimpleNamespace(stopping=False), get_node_data=lambda _n: None)
            argv = SimpleNamespace(node_name="WakeUpStart", custom_action_param={})
            action = wua.WakeUpToLobbyAction()
            with (
                patch.object(wua, "safe_screencap", return_value=img),
                patch.object(wua, "is_drawer", return_value=(False, [])),
                patch.object(wua, "is_lobby", side_effect=fake_is_lobby),
                patch.object(wua, "ocr_roi", return_value=[]),
                patch.object(wua, "tap_point", side_effect=fake_tap),
                patch.object(wua, "_is_adb_controller", return_value=False),
                patch.object(wua, "sleep_with_stop", return_value=True),
            ):
                res = action.run(ctx, argv)

            self.assertTrue(getattr(res, "success", True))
            self.assertEqual(
                tapped,
                [
                    ("WakeUpStartAct2_blind_dismiss", (40, 360)),
                    ("WakeUpStartAct5_blind_dismiss", (640, 28)),
                ],
            )

    def test_wake_up_action_escapes_train_power_subpage_immediately(self) -> None:
        with _real_maa_resource() as Resource:
            if Resource is None:
                self.skipTest("maafw is not installed")
            import agent.wake_up_action as wua

            img = np.zeros((720, 1280, 3), dtype=np.uint8)
            img[14:59, 16:148] = (245, 245, 245)
            img[28:32, 72:96] = (15, 15, 15)
            img[32:44, 92:96] = (15, 15, 15)
            img[40:44, 74:92] = (15, 15, 15)

            tapped: list[tuple[str, tuple[int, int]]] = []
            lobby_calls = {"count": 0}

            def fake_is_lobby(_ctx, name: str, _img) -> bool:
                if name.endswith("InitLobby"):
                    return False
                lobby_calls["count"] += 1
                # L0 is Train Power; L1 + LVerify1 are Lobby.
                return lobby_calls["count"] >= 2

            def fake_tap(_ctx, name: str, pt: tuple[int, int]) -> bool:
                tapped.append((name, pt))
                return True

            ctx = SimpleNamespace(tasker=SimpleNamespace(stopping=False), get_node_data=lambda _n: None)
            argv = SimpleNamespace(node_name="WakeUpStart", custom_action_param={})
            action = wua.WakeUpToLobbyAction()
            with (
                patch.object(wua, "safe_screencap", return_value=img),
                patch.object(wua, "is_drawer", return_value=(False, [])),
                patch.object(wua, "is_lobby", side_effect=fake_is_lobby),
                patch.object(wua, "ocr_roi", return_value=[{"text": "列车电力"}, {"text": "模块供电"}]),
                patch.object(wua, "tap_point", side_effect=fake_tap),
                patch.object(wua, "_is_adb_controller", return_value=False),
                patch.object(wua, "sleep_with_stop", return_value=True),
            ):
                res = action.run(ctx, argv)

            self.assertTrue(getattr(res, "success", True))
            self.assertEqual(tapped, [("WakeUpStartAct0_nav_back", TOP_BACK_POINT)])

    def test_wake_up_action_falls_back_to_return_to_lobby_after_blind_rotations(self) -> None:
        with _real_maa_resource() as Resource:
            if Resource is None:
                self.skipTest("maafw is not installed")
            import agent.wake_up_action as wua

            img = np.zeros((720, 1280, 3), dtype=np.uint8)
            tapped: list[tuple[str, tuple[int, int]]] = []
            ret_calls: list[tuple[str, int, tuple[int, int]]] = []

            def fake_tap(_ctx, name: str, pt: tuple[int, int]) -> bool:
                tapped.append((name, pt))
                return True

            def fake_return_to_lobby(_ctx, name: str, max_steps: int = 6, *, dismiss_point=(200, 660)) -> bool:
                ret_calls.append((name, max_steps, dismiss_point))
                return True

            ctx = SimpleNamespace(tasker=SimpleNamespace(stopping=False), get_node_data=lambda _n: None)
            argv = SimpleNamespace(node_name="WakeUpStart", custom_action_param={})
            action = wua.WakeUpToLobbyAction()
            with (
                patch.object(wua, "safe_screencap", return_value=img),
                patch.object(wua, "is_drawer", return_value=(False, [])),
                patch.object(wua, "is_lobby", return_value=False),
                patch.object(wua, "ocr_roi", return_value=[{"text": "神秘弹窗广告"}]),
                patch.object(wua, "tap_point", side_effect=fake_tap),
                patch.object(wua, "return_to_lobby", side_effect=fake_return_to_lobby),
                patch.object(wua, "_is_adb_controller", return_value=False),
                patch.object(wua, "sleep_with_stop", return_value=True),
            ):
                res = action.run(ctx, argv)

            self.assertTrue(getattr(res, "success", True))
            self.assertEqual(
                tapped,
                [
                    ("WakeUpStartAct2_blind_dismiss", (40, 360)),
                    ("WakeUpStartAct5_blind_dismiss", (640, 28)),
                    ("WakeUpStartAct8_blind_dismiss", (40, 220)),
                ],
            )
            self.assertEqual(ret_calls, [("WakeUpStartTryBack8", 2, (40, 360))])

    def test_pipeline_loads_and_no_native_click_swipe(self) -> None:
        pipeline = json.loads((ROOT / "assets/resource/base/pipeline/daily/wake_up.json").read_text(encoding="utf-8"))
        for node_name, node in pipeline.items():
            act = node.get("action")
            act_type = act.get("type") if isinstance(act, dict) else act
            self.assertNotIn(act_type, ("Click", "Swipe"), msg=node_name)

        with _real_maa_resource() as Resource:
            if Resource is None:
                self.skipTest("maafw is not installed")
            res = Resource()
            self.assertTrue(res.post_bundle(ROOT / "assets" / "resource" / "base").wait().succeeded)
            for node_name in pipeline:
                self.assertIsNotNone(res.get_node_data(node_name), msg=f"Missing node: {node_name}")


if __name__ == "__main__":
    unittest.main()
