from pathlib import Path, PurePosixPath, PureWindowsPath
import tempfile
import unittest
import zipfile

from maa_resonance.logic.planning import (
    AccountSnapshot,
    IslandDiagnosticRecorder,
    IslandPlanOptions,
    IslandRunReceipt,
    IslandSnapshot,
    WalletSnapshot,
    clear_catalog_caches,
    compute_stay_days_breakdown,
    format_island_mxu_summary,
    format_island_plan_markdown,
    format_island_report_html,
    load_account_snapshot,
    load_island_strategy_catalog,
    plan_island,
    resolve_island_runtime_config,
    save_account_snapshot_sections,
    snapshot_from_account_payload,
)
from maa_resonance.logic.planning.prison_diagnostics import sanitize_text_for_export


class IslandPlannerTest(unittest.TestCase):
    def setUp(self) -> None:
        clear_catalog_caches()

    def test_catalog_and_stay_days_formula(self):
        cat = load_island_strategy_catalog()
        self.assertEqual(cat["graduation_targets"]["unlocked_islands"], 6)
        self.assertEqual(cat["daily_limits"]["friend_clean_daily_limit"], 3)

        # 实机 UID 8820083699 快照等价输入：舒适 3579 (<6000->0), 美食 527 (<3000->0) => 1.0 天
        bd_low = compute_stay_days_breakdown({"舒适": 3579, "美食": 527}, cat)
        self.assertEqual(bd_low.estimated_stay_days, 1.0)
        self.assertEqual(len(bd_low.dimensions), 7)

        # 4 维拉满 (+0.5 * 4 = +2.0 => 3.0 天) 即使第 5 维也高也封顶 3.0
        bd_full = compute_stay_days_breakdown(
            {"舒适": 30000, "绿植": 15000, "美食": 15000, "娱乐": 15000, "水族": 20000},
            cat,
        )
        self.assertEqual(bd_full.effective_bonus_days, 2.0)
        self.assertEqual(bd_full.estimated_stay_days, 3.0)

    def test_stage_classification_and_trash_station_warning(self):
        snap_early = AccountSnapshot(
            uid="8820083699",
            wallet=WalletSnapshot(coins=46_991_972, huashi=7905),
            island=IslandSnapshot(
                level=14,
                unlocked_islands=1,
                cabin_level=3,
                trash_station_level=4,
                stability_current=35,
                stability_max=200,
                active_monsters=11,
                cleanliness_pct=100,
                trash_blocks_stored=143,
                trash_blocks_cap=90,
                scores={"舒适": 3579, "美食": 527},
                avg_stay_days=1.0,
                invest_remaining=1,
                material_tickets=70160,
                shell_coins=40,
            ),
        )
        rep_early = plan_island(snap_early, IslandPlanOptions(reserve_coins=15_000_000))
        self.assertEqual(rep_early.stage, "construction")
        self.assertTrue(any("3 亿" in w or "3亿" in w for w in rep_early.warnings))
        self.assertTrue(any("投资机会" in w for w in rep_early.warnings))

        snap_grad = AccountSnapshot(
            uid="99001122",
            wallet=WalletSnapshot(coins=80_000_000),
            island=IslandSnapshot(
                level=35,
                unlocked_islands=6,
                cabin_level=6,
                stability_current=200,
                stability_max=200,
                avg_stay_days=3.0,
                share_ratio_pct=35.0,
                ticket_price=2000,
                tax_rate_pct=0.0,
                scores={"舒适": 32000, "绿植": 16000, "美食": 16000, "水族": 30000},
            ),
        )
        rep_grad = plan_island(snap_grad)
        self.assertEqual(rep_grad.stage, "graduated_daily")
        self.assertEqual(len(rep_grad.graduated_checklist), 3)

    def test_account_snapshot_preserves_existing_trade_and_prison_fields(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            acc_path = Path(tmpdir) / "8820083699.json"
            acc_path.write_text(
                '{"version":1,"uid":"8820083699","trade":{"available_cities":["海角城"]},"prison":{"level":8}}',
                encoding="utf-8",
            )
            save_account_snapshot_sections(
                acc_path,
                uid="8820083699",
                island={"level": 14, "cabin_level": 3, "scores": {"舒适": 3579, "美食": 527}},
            )
            loaded_raw = acc_path.read_text(encoding="utf-8")
            self.assertIn("海角城", loaded_raw)
            snap = load_account_snapshot(acc_path)
            self.assertEqual(snap.prison.level, 8)
            self.assertEqual(snap.island.level, 14)
            self.assertEqual(snap.island.scores["舒适"], 3579)

            legacy_snap = snapshot_from_account_payload({"uid": "1234", "trade": {"role_resonance": {"静流": 5}}})
            self.assertEqual(legacy_snap.island.level, 0)
            self.assertEqual(legacy_snap.trade_role_resonance["静流"], 5)

    def test_runtime_config_html_escaping_and_diag_bundle(self):
        cfg_custom = resolve_island_runtime_config(
            {
                "exec_mode": "execute_safe_auto",
                "auto_scope": "custom",
                "modules_ui_configured": True,
                "mod_pick_claim_revenue": True,
                "mod_pick_collect_trash": True,
                "reserve_coins": 15000000,
                "use_custom_reserve_coins": True,
                "custom_reserve_coins": "25000000",
                "max_own_monster_fights": "11",
            }
        )
        self.assertEqual(cfg_custom.enabled_modules, frozenset({"claim_revenue", "collect_trash"}))
        self.assertEqual(cfg_custom.reserve_coins, 25_000_000)
        self.assertEqual(cfg_custom.max_own_monster_fights, 11)

        snap = AccountSnapshot(
            uid="8820083699",
            wallet=WalletSnapshot(coins=46_991_972),
            island=IslandSnapshot(level=14, cabin_level=3, scores={"舒适": 3579}),
        )
        rep = plan_island(snap)
        receipt = IslandRunReceipt(
            exec_mode="execute_safe_auto",
            auto_scope="daily_fast",
            revenue_claimed_coins=123456,
            trash_blocks_collected=50,
        )
        html_text = format_island_report_html(rep, receipt, diag_log_path="<xss>", issue_bundle_path="bundle.zip")
        self.assertIn("8820****99", html_text)
        self.assertNotIn("8820083699", html_text)
        self.assertIn("&lt;xss&gt;", html_text)
        self.assertIn("123,456", html_text)
        self.assertIn("收钱123,456", format_island_mxu_summary(rep, receipt, issue_bundle_path="a/b/island_issue.zip"))
        self.assertIn("8820083699", format_island_plan_markdown(rep, receipt))

        # 跨平台路径脱敏
        win_root = PureWindowsPath(r"E:\Projects\MaaResonance")
        self.assertEqual(
            sanitize_text_for_export("err at E:/Projects/MaaResonance/agent/island_plan_action.py", root_path=win_root),
            "err at <APP_ROOT>/agent/island_plan_action.py",
        )
        posix_root = PurePosixPath("/home/runner/work/MaaResonance")
        self.assertEqual(
            sanitize_text_for_export("err at /home/runner/work/MaaResonance/test.py", root_path=posix_root),
            "err at <APP_ROOT>/test.py",
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            logs_dir = Path(tmpdir)
            diag = IslandDiagnosticRecorder(export_mode="bundle", root_path=Path(tmpdir), raw_uid="8820083699")
            diag.record("scan", "ok", "scanned")
            res = diag.export(logs_dir, snapshot=snap, island_report=rep, run_receipt=receipt)
            self.assertTrue(res["log_path"] and res["log_path"].exists())
            self.assertTrue(res["bundle_path"] and res["bundle_path"].exists())
            with zipfile.ZipFile(res["bundle_path"], "r") as zf:
                names = set(zf.namelist())
                self.assertTrue({"island_run.log", "issue_template.md", "report_sanitized.json"} <= names)
                json_text = zf.read("report_sanitized.json").decode("utf-8")
                self.assertNotIn("8820083699", json_text)
                self.assertIn("8820****99", json_text)

    def test_stage3a_preset_isolation_and_opt_in_config(self):
        from maa_resonance.logic.planning import ISLAND_SCOPE_PRESETS

        for preset_name, modules in ISLAND_SCOPE_PRESETS.items():
            with self.subTest(preset=preset_name):
                self.assertNotIn("auto_invest", modules)
                self.assertNotIn("auto_expand", modules)

        for scope in ("daily_fast", "full_safe", "own_island_only"):
            cfg = resolve_island_runtime_config({"exec_mode": "execute_safe_auto", "auto_scope": scope})
            self.assertFalse(cfg.is_enabled("auto_invest"))
            self.assertFalse(cfg.is_enabled("auto_expand"))

        cfg_stage3 = resolve_island_runtime_config(
            {
                "exec_mode": "execute_safe_auto",
                "auto_scope": "custom",
                "modules_ui_configured": True,
                "mod_pick_auto_invest": True,
                "mod_pick_auto_expand": True,
            }
        )
        self.assertEqual(cfg_stage3.enabled_modules, frozenset({"auto_invest", "auto_expand"}))

        snap = AccountSnapshot(
            uid="8820083699",
            wallet=WalletSnapshot(coins=47_000_000),
            island=IslandSnapshot(level=14, unlocked_islands=1, cabin_level=3, volleyball_coins=125),
        )
        rep = plan_island(snap)
        receipt = IslandRunReceipt(
            exec_mode="execute_safe_auto",
            auto_scope="custom",
            invest_executed_count=2,
            invest_spent_coins=180_000,
            islands_expanded=1,
            expand_spent_coins=600_000,
            expand_spent_tickets=6_000,
        )
        self.assertIn("排球币 125", format_island_report_html(rep, receipt))
        self.assertIn("运营投资", format_island_report_html(rep, receipt))
        self.assertIn("海岛扩建", format_island_report_html(rep, receipt))
        self.assertIn("投资2", format_island_mxu_summary(rep, receipt))
        self.assertIn("扩建1", format_island_mxu_summary(rep, receipt))
        self.assertIn("运营投资 `2` 次", format_island_plan_markdown(rep, receipt))


if __name__ == "__main__":
    unittest.main()
