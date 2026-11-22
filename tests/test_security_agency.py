from __future__ import annotations

import json
from pathlib import Path
import re
import unittest

from maa_resonance.logic.security_agency import (
    find_start_combat_box,
    find_terminal_security_agency_go_point,
    has_remote_security_hub,
    has_security_agency_title,
    parse_expulsion_progress,
    parse_remote_city_cards,
    parse_reputation_level,
    parse_reputation_progress,
    parse_tab_progress_candidates,
    select_unfinished_remote_cities,
    select_unfinished_tab_candidates,
    should_stop_for_reputation,
)

ROOT = Path(__file__).resolve().parents[1]


class SecurityAgencyLogicTest(unittest.TestCase):
    def test_parse_reputation_level_handles_standard_split_and_confusions(self) -> None:
        self.assertEqual(parse_reputation_level([{"text": "声望等级：0级"}]), 0)
        self.assertEqual(parse_reputation_level([{"text": "声望等级: 1级"}]), 1)
        self.assertEqual(parse_reputation_level([{"text": "声望等级：O级"}]), 0)
        self.assertEqual(parse_reputation_level([{"text": "声望等级：l级"}]), 1)
        self.assertEqual(
            parse_reputation_level([
                {"text": "声望等级：", "box": [94, 656, 70, 22]},
                {"text": "2级", "box": [170, 656, 36, 22]},
            ]),
            2,
        )
        self.assertEqual(
            parse_reputation_level([
                {"text": "声望等级", "box": [94, 656, 60, 22]},
                {"text": "207/500", "box": [362, 653, 67, 23]},
                {"text": "1级", "box": [170, 656, 36, 22]},
            ]),
            1,
        )
        self.assertIsNone(parse_reputation_level([{"text": "207/500"}]))

    def test_parse_reputation_progress(self) -> None:
        self.assertEqual(
            parse_reputation_progress([{"text": "声望等级：0级"}, {"text": "207/500"}]),
            (207, 500),
        )
        self.assertIsNone(parse_reputation_progress([{"text": "声望等级：0级"}]))

    def test_title_and_start_combat_detection(self) -> None:
        self.assertTrue(has_security_agency_title([{"text": "铁安局", "box": [193, 550, 87, 36]}]))
        self.assertFalse(has_security_agency_title([{"text": "岚心城"}]))
        self.assertEqual(
            find_start_combat_box([{"text": "前往作战", "box": [941, 522, 125, 33]}]),
            (941, 522, 125, 33),
        )
        self.assertIsNone(find_start_combat_box([{"text": "变更难度", "box": [681, 529, 84, 24]}]))

    def test_should_stop_for_reputation(self) -> None:
        self.assertFalse(should_stop_for_reputation(0, 1))
        self.assertTrue(should_stop_for_reputation(1, 1))
        self.assertTrue(should_stop_for_reputation(2, 1))
        self.assertFalse(should_stop_for_reputation(None, 1))
        self.assertFalse(should_stop_for_reputation(3, 0))

    def test_expulsion_progress_and_unfinished_tab_selection(self) -> None:
        self.assertEqual(parse_expulsion_progress([{"text": "100%"}, {"text": "驱逐进度"}]), 100)
        self.assertEqual(parse_expulsion_progress([{"text": "20%"}]), 20)
        self.assertEqual(parse_expulsion_progress([{"text": "0％"}]), 0)
        self.assertEqual(parse_expulsion_progress([{"text": "O%"}]), 0)
        self.assertIsNone(parse_expulsion_progress([{"text": "驱逐进度"}]))

        tab_entries = [
            {"text": "特殊个体歼灭", "box": [517, 624, 111, 24]},
            {"text": "100%", "box": [670, 651, 78, 41]},
            {"text": "熄灯行动1", "box": [774, 626, 84, 22]},
            {"text": "0%", "box": [954, 652, 50, 40]},
            {"text": "黑月联合演习1", "box": [1032, 626, 120, 22]},
            {"text": "0%", "box": [1210, 652, 50, 41]},
        ]
        parsed = parse_tab_progress_candidates(tab_entries)
        self.assertEqual([t["percent"] for t in parsed], [100, 0, 0])

        unfinished = select_unfinished_tab_candidates(tab_entries)
        self.assertEqual(len(unfinished), 2)
        self.assertEqual(unfinished[0]["percent"], 0)
        # Tap point sits safely inside the 2nd tab card (755..1010)
        self.assertGreaterEqual(unfinished[0]["tap_point"][0], 755)
        self.assertLessEqual(unfinished[0]["tap_point"][0], 1010)

        # Excluding 2nd tab selects 3rd tab
        unfinished_after_exclude = select_unfinished_tab_candidates(
            tab_entries,
            excluded_x_centers={unfinished[0]["center_x"]},
        )
        self.assertEqual(len(unfinished_after_exclude), 1)
        self.assertGreaterEqual(unfinished_after_exclude[0]["tap_point"][0], 1015)

    def test_remote_hub_city_list_and_terminal_card_parsing(self) -> None:
        self.assertTrue(has_remote_security_hub([{"text": "驱逐任务"}]))
        self.assertTrue(has_remote_security_hub([], [{"text": "查看驱逐进度奖励"}]))
        self.assertFalse(has_remote_security_hub([{"text": "声望等级：0级"}]))

        city_entries = [
            {"text": "修格里城", "box": [49, 160, 79, 23]},
            {"text": "驱逐进度100%", "box": [310, 164, 142, 27]},
            {"text": "曼德矿场", "box": [50, 280, 76, 24]},
            {"text": "驱逐进度45%", "box": [310, 280, 142, 32]},
            {"text": "7号自由港", "box": [48, 401, 90, 23]},
            {"text": "驱逐进度0%", "box": [310, 402, 143, 30]},
            # Clipped bottom entry beyond y=640 should be ignored
            {"text": "底部半截城", "box": [48, 628, 90, 23]},
            {"text": "驱逐进度0%", "box": [310, 626, 143, 24]},
        ]
        cards = parse_remote_city_cards(city_entries)
        self.assertEqual([c["city_name"] for c in cards], ["修格里城", "曼德矿场", "7号自由港"])
        self.assertEqual([c["percent"] for c in cards], [100, 45, 0])

        unfinished = select_unfinished_remote_cities(city_entries, excluded_cities={"曼德矿场"})
        self.assertEqual([c["city_name"] for c in unfinished], ["7号自由港"])

        terminal_entries = [
            {"text": "铁安局", "box": [242, 420, 173, 65]},
            {"text": "前往>", "box": [81, 565, 498, 81]},
            {"text": "完成全部驱逐进度可获得", "box": [191, 707, 348, 36]},
        ]
        self.assertEqual(find_terminal_security_agency_go_point(terminal_entries), (330, 606))
        # Must NOT trigger on local Security Agency screen where 前往作战 exists
        self.assertIsNone(
            find_terminal_security_agency_go_point([
                {"text": "铁安局", "box": [193, 550, 87, 36]},
                {"text": "前往作战", "box": [941, 522, 125, 33]},
            ])
        )

    def test_remote_city_list_recognizes_bottom_most_city_card(self) -> None:
        # Real OCR boxes from bottom-scrolled 1280x720 screen where 岚心城 sits at y=522..630
        city_entries = [
            {"text": "澄明数据中心", "box": [49, 119, 117, 23]},
            {"text": "驱逐进度", "box": [313, 125, 72, 20]},
            {"text": "100%", "box": [376, 120, 75, 28]},
            {"text": "海角城", "box": [47, 236, 64, 28]},
            {"text": "驱逐进度", "box": [312, 243, 69, 23]},
            {"text": "100%", "box": [381, 240, 71, 28]},
            {"text": "阿妮塔发射中心", "box": [51, 358, 132, 24]},
            {"text": "驱逐进度", "box": [312, 365, 68, 20]},
            {"text": "100%", "box": [383, 363, 68, 25]},
            {"text": "贡露城", "box": [48, 476, 62, 27]},
            {"text": "驱逐进度", "box": [311, 484, 70, 22]},
            {"text": "100%", "box": [381, 480, 70, 28]},
            {"text": "岚心城", "box": [49, 597, 62, 26]},
            {"text": "驱逐进度", "box": [326, 605, 71, 20]},
            {"text": "33%", "box": [389, 603, 60, 24]},
        ]
        cards = parse_remote_city_cards(city_entries)
        self.assertEqual(
            [(c["city_name"], c["percent"]) for c in cards],
            [
                ("澄明数据中心", 100),
                ("海角城", 100),
                ("阿妮塔发射中心", 100),
                ("贡露城", 100),
                ("岚心城", 33),
            ],
        )

        unfinished = select_unfinished_remote_cities(city_entries)
        self.assertEqual(len(unfinished), 1)
        self.assertEqual(unfinished[0]["city_name"], "岚心城")
        self.assertEqual(unfinished[0]["percent"], 33)
        self.assertEqual(unfinished[0]["tap_point"], (220, 585))
        self.assertGreaterEqual(unfinished[0]["tap_point"][1], 522)
        self.assertLess(unfinished[0]["tap_point"][1], 630)

        # Slightly taller/shifted bottom card (cy=620, y+h=635) passes, overflowing card (cy=638, y+h=650) does not.
        boundary_entries = [
            {"text": "贴底可点城", "box": [49, 604, 80, 26]},
            {"text": "50%", "box": [389, 605, 60, 30]},
            {"text": "溢出半截城", "box": [49, 626, 80, 24]},
            {"text": "20%", "box": [389, 626, 60, 24]},
        ]
        boundary_cards = parse_remote_city_cards(boundary_entries)
        self.assertEqual([(c["city_name"], c["percent"]) for c in boundary_cards], [("贴底可点城", 50)])

    def test_terminal_card_ignores_header_and_dialogue_and_hits_security_agency(self) -> None:
        # Full-screen 1280x720 OCR entries on the PC 铁安协同终端 screen where top header
        # description and dialogue bubble both mention '铁安局' above/left of the card.
        base_entries = [
            {"text": "铁安协同终端", "box": [725, 37, 160, 27]},
            {"text": "铁安局的治安任务协同终端，完成作战任务可以获得大量桦石", "box": [726, 78, 468, 18]},
            {"text": "铁安局最新发布的协同终端功能，在这里", "box": [216, 370, 338, 24]},
            {"text": "可以方便地确认各地铁安局任务的完成情", "box": [218, 402, 335, 18]},
            {"text": "铁安局", "box": [698, 381, 95, 33]},
            {"text": "区域作战中心", "box": [1000, 379, 180, 36]},
            {"text": "前往>", "box": [1052, 461, 169, 37]},
            {"text": "完成全部驱逐进度可获得", "box": [666, 534, 196, 19]},
        ]
        entries_with_go = base_entries + [{"text": "前往", "box": [617, 460, 264, 41]}]
        self.assertEqual(find_terminal_security_agency_go_point(entries_with_go), (749, 480))

        # Even if OCR misses '前往' on the 铁安局 card, must NOT click 区域作战中心 at (1136, 480).
        fallback_point = find_terminal_security_agency_go_point(base_entries)
        self.assertEqual(fallback_point, (746, 483))

    def test_security_agency_pipeline_and_task_integrity(self) -> None:
        pipe_path = ROOT / "assets/resource/base/pipeline/combat/security_agency.json"
        task_path = ROOT / "assets/resource/tasks/SecurityAgency.json"
        iface_path = ROOT / "assets/interface.json"

        pipeline = json.loads(pipe_path.read_text(encoding="utf-8"))
        common_guard_path = ROOT / "assets/resource/base/pipeline/common/network_guard.json"
        common_guard = json.loads(common_guard_path.read_text(encoding="utf-8"))
        known_nodes = set(pipeline) | set(common_guard)
        task_cfg = json.loads(task_path.read_text(encoding="utf-8"))
        iface_cfg = json.loads(iface_path.read_text(encoding="utf-8"))

        # All next / on_error references must resolve inside security_agency.json or shared common nodes.
        missing_refs: list[tuple[str, str]] = []
        for node_name, node_def in pipeline.items():
            for field in ("next", "on_error"):
                refs = node_def.get(field) or []
                for ref in refs:
                    raw_name = ref["name"] if isinstance(ref, dict) else str(ref)
                    ref_name = re.sub(r"^(\[(?:JumpBack|Anchor)\])+", "", raw_name)
                    if ref_name not in known_nodes:
                        missing_refs.append((node_name, ref_name))
        self.assertEqual(missing_refs, [])

        # Reputation stop and 100%-tab-switch must run before EnterCombat in the main loop.
        loop_next = pipeline["SecurityAgencyLoop"]["next"]
        self.assertLess(
            loop_next.index("SecurityAgencyReputationStop"),
            loop_next.index("SecurityAgencyRemoteAdvance"),
        )
        self.assertLess(
            loop_next.index("SecurityAgencyRemoteAdvance"),
            loop_next.index("SecurityAgencySwitchTab"),
        )
        self.assertLess(
            loop_next.index("SecurityAgencySwitchTab"),
            loop_next.index("SecurityAgencyEnterCombat"),
        )
        self.assertLess(
            loop_next.index("SecurityAgencyEnterCombat"),
            loop_next.index("SecurityAgencyTerminalEnter"),
        )
        self.assertLess(
            loop_next.index("SecurityAgencySettleMission"),
            loop_next.index("SecurityAgencyReputationStop"),
        )

        # Task definition & pipeline_override target validation.
        task_entry = task_cfg["task"][0]
        self.assertEqual(task_entry["name"], "SecurityAgency")
        self.assertIn(task_entry["entry"], pipeline)
        for opt_name in task_entry["option"]:
            self.assertIn(opt_name, task_cfg["option"])

        for opt_name, opt_def in task_cfg["option"].items():
            if "cases" in opt_def:
                for case in opt_def["cases"]:
                    for target_node in (case.get("pipeline_override") or {}):
                        self.assertIn(target_node, pipeline, msg=f"{opt_name}.{case['name']} -> {target_node}")
            for target_node in (opt_def.get("pipeline_override") or {}):
                self.assertIn(target_node, pipeline, msg=f"{opt_name} -> {target_node}")

        self.assertIn("resource/tasks/SecurityAgency.json", iface_cfg["import"])
        preset_names = {p["name"] for p in iface_cfg["preset"]}
        self.assertIn("security-agency-remote", preset_names)
        self.assertIn("security-agency", preset_names)

        # SecurityAgency UI clicks must go through guarded_click for Win32 background protection.
        for click_node in (
            "SecurityAgencyEnterCombat",
            "SecurityAgencyFormationStartBattle",
            "SecurityAgencySettleNextTemplate",
            "SecurityAgencyDifficultyWarnConfirm",
        ):
            self.assertEqual(pipeline[click_node]["action"], "Custom")
            self.assertEqual(pipeline[click_node]["custom_action"], "guarded_click")

        self.assertIn("SecurityAgencyDifficultyWarnPrompt", loop_next)
        self.assertLess(
            loop_next.index("SecurityAgencyDifficultyWarnPrompt"),
            loop_next.index("SecurityAgencyEnterCombat"),
        )
        self.assertGreaterEqual(pipeline["SecurityAgencyDifficultyWarnConfirm"]["roi"][0], 600)

        # MainlineAdvance should handle the same difficulty warning popup safely.
        mainline_pipeline = json.loads(
            (ROOT / "assets" / "resource" / "base" / "pipeline" / "mainline" / "mainline_advance.json").read_text(
                encoding="utf-8"
            )
        )
        mainline_next = mainline_pipeline["MainlineAdvanceLoop"]["next"]
        self.assertIn("MainlineDifficultyWarnPrompt", mainline_next)
        self.assertLess(
            mainline_next.index("MainlineDifficultyWarnPrompt"),
            mainline_next.index("MainlineStageStartBattle"),
        )
        self.assertEqual(mainline_pipeline["MainlineDifficultyWarnConfirm"]["action"], "Custom")
        self.assertEqual(mainline_pipeline["MainlineDifficultyWarnConfirm"]["custom_action"], "guarded_click")
        self.assertGreaterEqual(mainline_pipeline["MainlineDifficultyWarnConfirm"]["roi"][0], 600)

    def test_battle_options_do_not_overwrite_each_other_across_tasks(self) -> None:
        task_pipeline_pairs = [
            ("assets/resource/tasks/SecurityAgency.json", "assets/resource/base/pipeline/combat/security_agency.json"),
            ("assets/resource/tasks/RegionalCombat.json", "assets/resource/base/pipeline/combat/regional_combat.json"),
            ("assets/resource/tasks/CalculationRecording.json", "assets/resource/base/pipeline/combat/calculation_recording.json"),
            ("assets/resource/tasks/MainlineAdvance.json", "assets/resource/base/pipeline/mainline/mainline_advance.json"),
            ("assets/resource/tasks/AssistMonitor.json", "assets/resource/base/pipeline/assist/assist_monitor.json"),
            ("assets/resource/tasks/AutoBattle.json", "assets/resource/base/pipeline/combat/battle_autoplay.json"),
        ]
        for task_rel, pipe_rel in task_pipeline_pairs:
            task_cfg = json.loads((ROOT / task_rel).read_text(encoding="utf-8"))
            pipeline = json.loads((ROOT / pipe_rel).read_text(encoding="utf-8"))
            custom_param_targets: dict[str, set[str]] = {}
            for opt_name, opt_def in task_cfg["option"].items():
                for case in opt_def.get("cases") or ():
                    for target_node, ov in (case.get("pipeline_override") or {}).items():
                        self.assertIn(target_node, pipeline, msg=f"{task_rel}:{opt_name}.{case['name']} -> {target_node}")
                        if "custom_action_param" in ov:
                            custom_param_targets.setdefault(target_node, set()).add(opt_name)
            # At most one option may touch custom_action_param on the same node (battle options use attach nodes).
            for target_node, opt_names in custom_param_targets.items():
                self.assertLessEqual(
                    len(opt_names),
                    1,
                    msg=f"{task_rel}: multiple options collide on {target_node}.custom_action_param: {sorted(opt_names)}",
                )

    def test_interface_consistency_groups_suboptions_guarded_clicks_and_depersonalized_defaults(self) -> None:
        from maa_resonance.logic.team_formation import DEFAULT_TEAM_ROLES

        iface_cfg = json.loads((ROOT / "assets" / "interface.json").read_text(encoding="utf-8"))
        valid_groups = {g["name"] for g in iface_cfg["group"]}
        self.assertIn("experimental", valid_groups)

        # Load all pipeline nodes across resource/base.
        all_pipeline_nodes: dict[str, dict] = {}
        for p in (ROOT / "assets" / "resource" / "base" / "pipeline").rglob("*.json"):
            all_pipeline_nodes.update(json.loads(p.read_text(encoding="utf-8")))

        # Check every imported task file and option tree (including shared & nested case.option).
        tasks_by_name: dict[str, dict] = {}
        options_by_task: dict[str, dict] = {}
        all_options: dict[str, dict] = dict(iface_cfg.get("option") or {})
        imported_cfgs: list[tuple[str, dict]] = []
        for rel_path in iface_cfg["import"]:
            task_cfg = json.loads((ROOT / "assets" / rel_path).read_text(encoding="utf-8"))
            imported_cfgs.append((rel_path, task_cfg))
            all_options.update(task_cfg.get("option") or {})

        def _validate_option_tree(owner_label: str, initial_options: list[str]) -> None:
            queue = list(initial_options)
            visited: set[str] = set()
            while queue:
                opt_name = queue.pop(0)
                if opt_name in visited:
                    continue
                visited.add(opt_name)
                self.assertIn(opt_name, all_options, msg=f"{owner_label}: missing option {opt_name}")
                opt_def = all_options[opt_name]
                for target_node in (opt_def.get("pipeline_override") or {}):
                    self.assertIn(target_node, all_pipeline_nodes, msg=f"{owner_label}.{opt_name} -> {target_node}")
                for case in opt_def.get("cases") or ():
                    for target_node in (case.get("pipeline_override") or {}):
                        self.assertIn(
                            target_node,
                            all_pipeline_nodes,
                            msg=f"{owner_label}.{opt_name}.{case['name']} -> {target_node}",
                        )
                    queue.extend(case.get("option") or ())

        _validate_option_tree("global_option", list(iface_cfg.get("global_option") or ()))

        for rel_path, task_cfg in imported_cfgs:
            opt_defs = task_cfg.get("option") or {}
            for task in task_cfg["task"]:
                tasks_by_name[task["name"]] = task
                options_by_task[task["name"]] = opt_defs
                self.assertIn(task["entry"], all_pipeline_nodes, msg=f"{rel_path}: missing entry {task['entry']}")
                for grp in task["group"]:
                    self.assertIn(grp, valid_groups, msg=f"{task['name']}: unknown group {grp}")

                _validate_option_tree(task["name"], list(task.get("option") or ()))

        # Validate presets reference real tasks, options, and select/switch case names.
        for preset in iface_cfg["preset"]:
            for t_ref in preset["task"]:
                t_name = t_ref["name"]
                self.assertIn(t_name, tasks_by_name, msg=f"preset {preset['name']} -> unknown task {t_name}")
                for opt_name, opt_val in (t_ref.get("option") or {}).items():
                    self.assertIn(opt_name, all_options, msg=f"preset {preset['name']} -> unknown option {opt_name}")
                    opt_def = all_options[opt_name]
                    if "cases" in opt_def:
                        valid_cases = {c["name"] for c in opt_def["cases"]}
                        if isinstance(opt_val, list):
                            self.assertTrue(set(opt_val).issubset(valid_cases))
                        else:
                            self.assertIn(opt_val, valid_cases, msg=f"preset {preset['name']}:{opt_name}={opt_val}")

        # Experimental / atomic tasks live in experimental group.
        for exp_task in ("StorySkip", "AutoTeamFormation", "AutoBattle", "SyncCardTemplates"):
            self.assertEqual(tasks_by_name[exp_task]["group"], ["experimental"])

        # All 8 self-developed pipelines have 0 raw Click actions.
        self_dev_pipes = (
            "assets/resource/base/pipeline/assist/assist_monitor.json",
            "assets/resource/base/pipeline/combat/battle_autoplay.json",
            "assets/resource/base/pipeline/combat/calculation_recording.json",
            "assets/resource/base/pipeline/combat/card_templates.json",
            "assets/resource/base/pipeline/combat/regional_combat.json",
            "assets/resource/base/pipeline/combat/security_agency.json",
            "assets/resource/base/pipeline/combat/team_formation.json",
            "assets/resource/base/pipeline/daily/daily_routine.json",
            "assets/resource/base/pipeline/mainline/mainline_advance.json",
            "assets/resource/base/pipeline/story/story_skip.json",
        )
        for pipe_rel in self_dev_pipes:
            pipe_data = json.loads((ROOT / pipe_rel).read_text(encoding="utf-8"))
            raw_clicks = [
                k
                for k, v in pipe_data.items()
                if v.get("action") == "Click"
                or (isinstance(v.get("action"), dict) and v["action"].get("type") == "Click")
            ]
            self.assertEqual(raw_clicks, [], msg=f"{pipe_rel} still contains raw Click nodes: {raw_clicks}")

        # No hardcoded personal lineup remains anywhere in tasks, pipelines, or DEFAULT_TEAM_ROLES.
        self.assertEqual(DEFAULT_TEAM_ROLES, ())
        for json_path in list((ROOT / "assets" / "resource" / "tasks").glob("*.json")) + list(
            (ROOT / "assets" / "resource" / "base" / "pipeline").rglob("*.json")
        ):
            self.assertNotIn("小红帽", json_path.read_text(encoding="utf-8"), msg=f"Personal role found in {json_path}")

        # Unified combat/formation option schema across the 4 combat-capable tasks.
        for task_name, prefix in (
            ("SecurityAgency", "Security"),
            ("RegionalCombat", "RegionalCombat"),
            ("CalculationRecording", "CalculationRecording"),
            ("MainlineAdvance", "Mainline"),
            ("AssistMonitor", "AssistMonitor"),
            ("AutoBattle", "AutoBattle"),
        ):
            opt_defs = options_by_task[task_name]
            top_opts = set(tasks_by_name[task_name]["option"])
            for kind in ("PreferNativeAuto", "LeaderSkill"):
                opt_def = opt_defs[f"{prefix}{kind}"]
                self.assertEqual(opt_def["type"], "switch")
                self.assertEqual([c["name"] for c in opt_def["cases"]], ["Yes", "No"])

            play_mode_key = f"{prefix}BattlePlayMode" if f"{prefix}BattlePlayMode" in opt_defs else f"{prefix}PlayMode"
            play_cases = {c["name"]: c for c in opt_defs[play_mode_key]["cases"]}
            min_cost_key = f"{prefix}MinCost"
            self.assertNotIn(min_cost_key, top_opts)
            self.assertEqual(play_cases["Weighted"].get("option"), [min_cost_key])

            if task_name != "AutoBattle":
                form_key = f"{prefix}FormationMode" if f"{prefix}FormationMode" in opt_defs else f"{prefix}Formation"
                roles_key = f"{prefix}FormationRoles"
                self.assertNotIn(roles_key, top_opts)
                form_cases = {c["name"]: c for c in opt_defs[form_key]["cases"]}
                self.assertEqual(opt_defs[form_key]["default_case"], "Off")
                self.assertIn(roles_key, form_cases["EmptyOnly"].get("option") or ())
                self.assertIn(roles_key, form_cases["Strict"].get("option") or ())
                self.assertEqual(opt_defs[roles_key]["inputs"][0]["default"], "")


if __name__ == "__main__":
    unittest.main()
