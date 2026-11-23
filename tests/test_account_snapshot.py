from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from tests.test_trade_runtime_fix import trade
from maa_resonance.logic.planning import (
    CrewGoal,
    CrewProgressionEntry,
    PrisonSnapshot,
    WalletSnapshot,
    load_account_snapshot,
    save_account_snapshot_sections,
    snapshot_from_account_payload,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "tools"))

from sync_to_packaged import sync_to_packaged


class AccountSnapshotTests(unittest.TestCase):
    def test_save_unified_account_profile_preserves_planning_sections(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            account_path = Path(tmp_dir) / "8820083699.json"
            initial = {
                "version": 1,
                "uid": "8820083699",
                "updated_at": "2026-11-22 11:00:00",
                "completed_parts": ["read_uid", "read_prestige"],
                "trade": {
                    "cargo_capacity": 975,
                    "prestige_by_city": {"7号自由港": 20},
                    "available_cities": ["云岫桥基地", "岚心城"],
                    "role_resonance": {"真咲": 4},
                },
                "wallet": {
                    "coins": 31641061,
                    "huashi": 14880,
                    "clarity_estimate": 220,
                    "updated_at": "2026-11-23 12:00:00",
                },
                "crew_progression": {
                    "真咲": {
                        "level": 70,
                        "resonance": 4,
                        "awakening": 3,
                        "skills": {"1": 10},
                        "target_goal": {
                            "target_resonance": 5,
                            "required_coins": 200000,
                            "required_materials": {"桦树核仁": 4},
                        },
                    }
                },
                "materials_inventory": {
                    "桦树核仁": {"owned": 1, "updated_at": "2026-11-23 12:00:00"}
                },
                "prison": {
                    "level": 7,
                    "work_tickets": 7500,
                    "buildings": {"power_center": 3, "research_center": 3},
                },
                "custom_extension_marker": {"keep": True},
            }
            account_path.write_text(json.dumps(initial, ensure_ascii=False, indent=2), encoding="utf-8")

            with patch.object(trade, "_account_config_path", return_value=account_path), patch.object(
                trade, "_load_account_config", return_value=initial
            ):
                saved_path = trade._save_unified_account_profile(
                    {
                        "uid": "8820083699",
                        "completed_parts": ["read_cargo"],
                        "cargo_capacity": 1020,
                    },
                    task_entry="ReadAccountProfile",
                )

            self.assertEqual(Path(saved_path), account_path)
            saved = json.loads(account_path.read_text(encoding="utf-8"))
            self.assertEqual(saved["trade"]["cargo_capacity"], 1020)
            self.assertEqual(saved["trade"]["prestige_by_city"], {"7号自由港": 20})
            self.assertEqual(saved["wallet"]["coins"], 31641061)
            self.assertEqual(saved["wallet"]["huashi"], 14880)
            self.assertEqual(saved["crew_progression"]["真咲"]["target_goal"]["required_materials"], {"桦树核仁": 4})
            self.assertEqual(saved["materials_inventory"]["桦树核仁"]["owned"], 1)
            self.assertEqual(saved["prison"]["level"], 7)
            self.assertEqual(saved["prison"]["work_tickets"], 7500)
            self.assertEqual(saved["custom_extension_marker"], {"keep": True})

    def test_legacy_trade_payload_loads_cleanly_and_normalizes_buildings(self) -> None:
        legacy_payload = {
            "version": 1,
            "uid": "8820083699",
            "trade": {
                "available_cities": ["云岫桥基地", "海角城", "岚心城"],
                "role_resonance": {"真咲": 4, "苍叶": 5},
            },
            "prison": {
                "level": 7,
                "buildings": {
                    "研发中心": 3,
                    "电力中心": 3,
                    "1号整顿宿舍": 1,
                    "缝纫工具原料车间": 1,
                },
            },
        }
        snapshot = snapshot_from_account_payload(legacy_payload)
        self.assertEqual(snapshot.uid, "8820083699")
        self.assertEqual(snapshot.available_cities, ["云岫桥基地", "海角城", "岚心城"])
        self.assertEqual(snapshot.effective_role_resonance("真咲"), 4)
        self.assertEqual(snapshot.wallet.coins, 0)
        self.assertEqual(snapshot.prison.buildings["research_center"], 3)
        self.assertEqual(snapshot.prison.buildings["power_center"], 3)
        self.assertEqual(snapshot.prison.buildings["dormitory"], 1)
        self.assertEqual(snapshot.prison.buildings["raw_sewing"], 1)

    def test_save_account_snapshot_sections_preserves_trade_and_merges_partial_sections(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "8820083699.json"
            path.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "uid": "8820083699",
                        "completed_parts": ["read_uid"],
                        "trade": {"cargo_capacity": 975, "role_resonance": {"真咲": 3}},
                        "planner": {"max_goods_num": 975},
                        "account_profile_read": {"last_smart_scan_date": "2026-11-22"},
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

            save_account_snapshot_sections(
                path,
                wallet=WalletSnapshot(coins=31641061, huashi=14880),
                crew_progression={
                    "真咲": CrewProgressionEntry(
                        level=70,
                        target_goal=CrewGoal(target_resonance=5, required_materials={"桦树核仁": 4}),
                    )
                },
                materials_inventory={"深眠木": 3},
            )
            save_account_snapshot_sections(
                path,
                prison=PrisonSnapshot(level=7, work_tickets=7500, buildings={"研发中心": 3}),
                materials_inventory={"桦树核仁": 1},
            )

            raw = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(raw["trade"]["cargo_capacity"], 975)
            self.assertEqual(raw["planner"]["max_goods_num"], 975)
            self.assertEqual(raw["account_profile_read"]["last_smart_scan_date"], "2026-11-22")
            self.assertEqual(raw["wallet"]["coins"], 31641061)
            self.assertEqual(raw["materials_inventory"]["深眠木"]["owned"], 3)
            self.assertEqual(raw["materials_inventory"]["桦树核仁"]["owned"], 1)

            loaded = load_account_snapshot(path)
            self.assertEqual(loaded.effective_role_resonance("真咲"), 3)
            self.assertEqual(loaded.prison.buildings["research_center"], 3)

    def test_sync_to_packaged_copies_planning_resources(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            target = Path(tmp_dir)
            sync_to_packaged(target)
            self.assertTrue((target / "resources" / "planning" / "prison_strategy.json").is_file())
            self.assertTrue((target / "resources" / "planning" / "growth_stages.json").is_file())
            self.assertTrue((target / "maa_resonance" / "logic" / "planning" / "prison_planner.py").is_file())


if __name__ == "__main__":
    unittest.main()
