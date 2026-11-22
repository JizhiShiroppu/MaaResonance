from contextlib import contextmanager
import importlib
import json
import sys
import unittest
from pathlib import Path


ASSETS = Path(__file__).resolve().parents[1] / "assets"


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


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


class PcTradeInterfaceTest(unittest.TestCase):
    def test_task_visibility_and_trade_presets(self):
        interface = read_json(ASSETS / "interface.json")
        tasks = [task for path in interface["import"] for task in read_json(ASSETS / path)["task"]]
        manual, auto, launch = "ManualTwoCityBusiness", "AutoTwoCityBusiness", "LaunchGame"
        custom_pc_tasks = {
            "WakeUp",
            "DailyPrep",
            "AutoShop",
            "CoopAssault",
            "EventStageFarm",
            "EventStoryDaily",
            "DailyClaim",
            "AssistMonitor",
            "SecurityAgency",
            "RegionalCombat",
            "CalculationRecording",
            "DailyRoutine",
            "MainlineAdvance",
            "AutoBattle",
            "AutoTeamFormation",
            "StorySkip",
            "SyncCardTemplates",
        }
        pc_controllers = ("Win32", "Win32BackgroundWindowPos", "Win32BackgroundCursorPos")
        available = {ctrl: {t["name"] for t in tasks if ctrl in t["controller"]} for ctrl in ("ADB", *pc_controllers)}
        for ctrl in pc_controllers:
            with self.subTest(controller=ctrl):
                self.assertEqual(available[ctrl] & {manual, auto, launch}, {manual, auto})
                self.assertEqual(available[ctrl], {manual, auto} | custom_pc_tasks)
        self.assertTrue(({manual, auto, launch} | custom_pc_tasks) <= available["ADB"])

        presets = {p["name"]: [t for t in p["task"] if t["enabled"]] for p in interface["preset"]}
        pc = presets["pc-manual-business"]
        self.assertEqual([t["name"] for t in pc], [manual])
        options = pc[0]["option"]
        self.assertEqual(options["ManualTwoCityRunMode"], "one_round")
        self.assertEqual(int(options["ManualTwoCityStartParams"]["start_book"]), 0)
        self.assertEqual(int(options["ManualTwoCityTargetParams"]["target_book"]), 0)

        pc_auto = presets["pc-auto-business"]
        self.assertEqual([t["name"] for t in pc_auto], [auto])
        pc_auto_opts = pc_auto[0]["option"]
        self.assertEqual(pc_auto_opts["ManualTwoCityRunMode"], "until_fatigue_exhausted")
        self.assertEqual(pc_auto_opts["ManualTwoCityAccountProfileReadMode"], "smart")
        self.assertEqual(pc_auto_opts["ManualTwoCityAutoPickup"], "No")

        for preset, task in (("manual-business", manual), ("auto-business", auto)):
            enabled = presets[preset]
            self.assertEqual([t["name"] for t in enabled], [launch, task])
            self.assertEqual(enabled[1]["option"]["ManualTwoCityRunMode"], "until_fatigue_exhausted")

        all_in_one = next(p for p in interface["preset"] if p["name"] == "daily-all-in-one")
        self.assertEqual(
            [(t["name"], bool(t["enabled"])) for t in all_in_one["task"]],
            [
                ("WakeUp", True),
                ("DailyPrep", True),
                ("AutoShop", True),
                ("CoopAssault", True),
                ("EventStageFarm", True),
                ("EventStoryDaily", True),
                ("SecurityAgency", False),
                ("RegionalCombat", False),
                ("CalculationRecording", False),
                ("AutoTwoCityBusiness", False),
                ("DailyClaim", True),
            ],
        )

    def test_android_lifecycle_actions_are_overridden_only_on_pc(self):
        interface = read_json(ASSETS / "interface.json")
        controllers = {entry["name"]: entry for entry in interface["controller"]}
        official = next(resource for resource in interface["resource"] if resource["name"] == "official")
        expected_pc_mouse = {
            "Win32": "Seize",
            "Win32BackgroundWindowPos": "PostMessageWithWindowPos",
            "Win32BackgroundCursorPos": "PostMessageWithCursorPos",
        }
        self.assertEqual(set(official["controller"]), {"ADB", *expected_pc_mouse.keys()})
        self.assertEqual(official["path"], ["./resource/base"])
        self.assertFalse(controllers["ADB"].get("attach_resource_path"))
        for ctrl_name, mouse_mode in expected_pc_mouse.items():
            with self.subTest(controller=ctrl_name):
                ctrl_cfg = controllers[ctrl_name]
                self.assertEqual(ctrl_cfg["type"], "Win32")
                self.assertEqual(ctrl_cfg["display_short_side"], 720)
                self.assertEqual(ctrl_cfg["attach_resource_path"], ["./resource/pc"])
                self.assertEqual(ctrl_cfg["win32"]["screencap"], "FramePool")
                self.assertEqual(ctrl_cfg["win32"]["mouse"], mouse_mode)
        base = {}
        for path in (ASSETS / official["path"][0] / "pipeline").rglob("*.json"):
            base.update(read_json(path))
        pc = read_json(ASSETS / "resource/pc/pipeline/pc_manual_business.json")
        expected = {
            "LaunchGameStartApp": "StartApp",
            "StateRecoveryRestartGameOnce": "StopApp",
            "StateRecoveryStartGameOnce": "StartApp",
            "ManualTwoCityBusinessTravelStuckRestartStopApp": "StopApp",
            "ManualTwoCityBusinessTravelStuckRestartStartApp": "StartApp",
        }
        for node, action in expected.items():
            with self.subTest(node=node):
                self.assertEqual(base[node]["action"], {"type": action, "param": {"package": "com.hermes.goda"}})
                self.assertEqual(pc[node]["action"], "DoNothing")

    def test_pc_business_guarded_click_overlay_covers_all_business_clicks(self):
        pc_manual = read_json(ASSETS / "resource/pc/pipeline/pc_manual_business.json")
        guarded = read_json(ASSETS / "resource/pc/pipeline/pc_business_guarded_clicks.json")
        expected_nodes: set[str] = set()
        for path in (ASSETS / "resource/base/pipeline/business").rglob("*.json"):
            data = read_json(path)
            for node_name, node_data in data.items():
                if node_name in pc_manual or not isinstance(node_data, dict):
                    continue
                act = node_data.get("action")
                if act == "Click" or (isinstance(act, dict) and act.get("type") == "Click"):
                    expected_nodes.add(node_name)
        self.assertEqual(set(guarded.keys()), expected_nodes)
        for node_name, ov in guarded.items():
            self.assertEqual(ov["action"]["type"], "Custom", msg=node_name)
            self.assertEqual(ov["action"]["param"]["custom_action"], "guarded_click", msg=node_name)

        for arrived_node in ("ManualTwoCityBusinessArrivedVisitCity", "ManualTwoCityBusinessArrivedVisitCityByStatus"):
            arrived_act = pc_manual[arrived_node]["action"]
            self.assertEqual(arrived_act["type"], "Custom", msg=arrived_node)
            self.assertEqual(arrived_act["param"]["custom_action"], "guarded_click", msg=arrived_node)

    def test_pc_business_guarded_swipe_overlay_covers_all_business_swipes(self):
        pc_manual = read_json(ASSETS / "resource/pc/pipeline/pc_manual_business.json")
        guarded = read_json(ASSETS / "resource/pc/pipeline/pc_business_guarded_swipes.json")
        expected_nodes: set[str] = set()
        for path in (ASSETS / "resource/base/pipeline/business").rglob("*.json"):
            data = read_json(path)
            for node_name, node_data in data.items():
                if node_name in pc_manual or not isinstance(node_data, dict):
                    continue
                act = node_data.get("action")
                if act == "Swipe" or (isinstance(act, dict) and act.get("type") == "Swipe"):
                    expected_nodes.add(node_name)
        self.assertEqual(len(expected_nodes), 44)
        self.assertEqual(set(guarded.keys()), expected_nodes)
        for node_name, ov in guarded.items():
            self.assertEqual(ov["action"]["type"], "Custom", msg=node_name)
            self.assertEqual(ov["action"]["param"]["custom_action"], "guarded_swipe", msg=node_name)

    def test_resource_pc_overlay_loads_cleanly(self):
        base_dir = ASSETS / "resource" / "base"
        pc_dir = ASSETS / "resource" / "pc"
        expected_nodes = (
            "LaunchGameStartApp",
            "StateRecoveryRestartGameOnce",
            "StateRecoveryStartGameOnce",
            "ManualTwoCityBusinessTravelStuckRestartStopApp",
            "ManualTwoCityBusinessTravelStuckRestartStartApp",
        )
        with _real_maa_resource() as Resource:
            if Resource is None:
                self.skipTest("maafw is not installed in current interpreter")
            res = Resource()
            self.assertTrue(res.post_bundle(base_dir).wait().succeeded)
            self.assertTrue(res.post_bundle(pc_dir).wait().succeeded)
            for node_name in expected_nodes:
                node = res.get_node_data(node_name)
                self.assertIsNotNone(node, msg=f"Missing node after pc overlay: {node_name}")
                self.assertEqual(node["action"]["type"], "DoNothing")

            run_auto = res.get_node_data("RunAutoTwoCityBusiness")
            self.assertEqual([item["name"] for item in run_auto["next"]], ["PcAutoBusinessCheckFrame"])
            auto_check = res.get_node_data("PcAutoBusinessCheckFrame")
            self.assertEqual(auto_check["action"]["param"]["custom_action"], "pc_manual_business_check_frame")
            self.assertEqual([item["name"] for item in auto_check["next"]], ["AutoTwoCityBusinessSetPriorityCities"])

            arrived = res.get_node_data("ManualTwoCityBusinessArrivedMainMap")
            self.assertEqual(arrived["action"]["param"]["custom_action"], "pc_manual_business_enter_arrived_city")

            for arrived_visit in ("ManualTwoCityBusinessArrivedVisitCity", "ManualTwoCityBusinessArrivedVisitCityByStatus"):
                visit_node = res.get_node_data(arrived_visit)
                self.assertEqual(visit_node["action"]["type"], "Custom", msg=arrived_visit)
                self.assertEqual(visit_node["action"]["param"]["custom_action"], "guarded_click", msg=arrived_visit)

            role_start = res.get_node_data("AccountProfileRoleResonanceStart")
            self.assertEqual(role_start["action"]["type"], "Custom")
            self.assertEqual(role_start["action"]["param"]["custom_action"], "guarded_click")
            self.assertEqual(role_start["action"]["param"]["custom_action_param"], {"target": [1225, 58]})

            open_buy = res.get_node_data("ManualTwoCityBusinessOpenBuyPage")
            self.assertEqual(open_buy["action"]["type"], "Custom")
            self.assertEqual(open_buy["action"]["param"]["custom_action"], "guarded_click")

            for swipe_node in (
                "ManualTwoCityBusinessProductScanScroll001",
                "AccountProfileRoleResonanceScroll001",
                "CityTradeOutletSwipeLeft",
            ):
                loaded_swipe = res.get_node_data(swipe_node)
                self.assertEqual(loaded_swipe["action"]["type"], "Custom", msg=swipe_node)
                self.assertEqual(loaded_swipe["action"]["param"]["custom_action"], "guarded_swipe", msg=swipe_node)

            for loaded_name in res.node_list:
                loaded_node = res.get_node_data(loaded_name)
                if not isinstance(loaded_node, dict):
                    continue
                act = loaded_node.get("action")
                act_type = act.get("type") if isinstance(act, dict) else act
                self.assertNotIn(act_type, ("Click", "Swipe"), msg=loaded_name)
