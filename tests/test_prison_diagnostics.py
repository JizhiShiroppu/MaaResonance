from __future__ import annotations

import json
from pathlib import Path, PurePosixPath, PureWindowsPath
import struct
import tempfile
import unittest
import zipfile
import zlib

import numpy as np

from maa_resonance.logic.planning import (
    ALL_PRISON_AUTO_MODULES,
    MAX_DIAG_SCREENSHOTS,
    PrisonDiagnosticRecorder,
    PrisonPlanOptions,
    PrisonRunReceipt,
    encode_png_bytes,
    format_mxu_plain_summary,
    format_planning_report_html,
    mask_uid,
    plan_prison,
    plan_prisoner_worker_allocation,
    prune_old_diagnostic_files,
    resolve_prison_runtime_config,
    sanitize_json_payload,
    sanitize_text_for_export,
    snapshot_from_account_payload,
)


class PrisonDiagnosticsTests(unittest.TestCase):
    def test_runtime_config_presets_custom_modules_and_limits(self) -> None:
        default_cfg = resolve_prison_runtime_config({})
        self.assertEqual(default_cfg.exec_mode, "plan_only")
        self.assertEqual(default_cfg.auto_scope, "full_safe")
        self.assertEqual(default_cfg.enabled_modules, frozenset(ALL_PRISON_AUTO_MODULES))
        self.assertEqual(default_cfg.reserve_coins, 15_000_000)
        self.assertEqual(default_cfg.prod_duration_pref, "8h")
        self.assertEqual(default_cfg.raw_worker_mode, "balanced")
        self.assertEqual(default_cfg.warehouse_batch_cap, 2)
        self.assertEqual(default_cfg.core_upgrade_cap, 3)
        self.assertEqual(default_cfg.diag_export_mode, "bundle")

        custom_cfg = resolve_prison_runtime_config(
            {
                "exec_mode": "execute_safe_auto",
                "auto_scope": "custom",
                "modules_ui_configured": True,
                "mod_pick_todo_claim": True,
                "mod_pick_order_deliver": True,
                "mod_pick_ws_start_prod": False,
                "reserve_coins": "{reserve_coins}",
                "use_custom_reserve_coins": True,
                "custom_reserve_coins": "22500000",
                "prod_duration_pref": "2h",
                "raw_worker_mode": "raw_priority",
                "warehouse_batch_cap": 99,
                "core_upgrade_cap": 0,
                "diag_export_mode": "bundle_screenshots",
            }
        )
        self.assertEqual(custom_cfg.exec_mode, "execute_safe_auto")
        self.assertEqual(custom_cfg.enabled_modules, frozenset({"todo_claim", "order_deliver"}))
        self.assertTrue(custom_cfg.is_enabled("todo_claim"))
        self.assertFalse(custom_cfg.is_enabled("ws_start_prod"))
        self.assertEqual(custom_cfg.reserve_coins, 22_500_000)
        self.assertEqual(custom_cfg.prod_duration_pref, "2h")
        self.assertEqual(custom_cfg.raw_worker_mode, "raw_priority")
        self.assertEqual(custom_cfg.warehouse_batch_cap, 5)
        self.assertEqual(custom_cfg.core_upgrade_cap, 1)
        self.assertEqual(custom_cfg.diag_export_mode, "bundle_screenshots")

        empty_custom = resolve_prison_runtime_config(
            {
                "auto_scope": "custom",
                "modules_ui_configured": True,
            }
        )
        self.assertEqual(empty_custom.enabled_modules, frozenset())

        orders_cfg = resolve_prison_runtime_config({"auto_scope": "orders_and_prod"})
        self.assertTrue(orders_cfg.is_enabled("order_deliver"))
        self.assertFalse(orders_cfg.is_enabled("building_upgrade"))
        self.assertFalse(orders_cfg.is_enabled("ws_machine_upgrade"))

        list_cfg = resolve_prison_runtime_config(
            {"auto_scope": "custom", "enabled_modules": ["building_upgrade", "invalid_key"]}
        )
        self.assertEqual(list_cfg.enabled_modules, frozenset({"building_upgrade"}))

    def test_sanitization_and_uid_masking(self) -> None:
        self.assertEqual(mask_uid("8820083699"), "8820****99")
        self.assertEqual(mask_uid("unknown"), "unknown")
        self.assertEqual(mask_uid("ab"), "a***b")
        self.assertEqual(mask_uid("x"), "***")

        root = Path(r"E:\Program Files\MaaResonance")
        raw_text = r"Failed at E:\Program Files\MaaResonance\config\accounts\8820083699.json by C:\Users\alice\Desktop"
        cleaned = sanitize_text_for_export(raw_text, root_path=root, raw_uid="8820083699")
        self.assertNotIn("8820083699", cleaned)
        self.assertNotIn("alice", cleaned)
        self.assertIn("8820****99", cleaned)
        self.assertIn("<APP_ROOT>", cleaned)
        self.assertIn("<USER_HOME>", cleaned)

        nested = sanitize_json_payload(
            {
                "uid": "8820083699",
                "items": ["e:/program files/maaresonance/logs", "UID=8820083699"],
            },
            root_path=root,
            raw_uid="8820083699",
        )
        self.assertEqual(nested["uid"], "8820****99")
        self.assertEqual(nested["items"][0], "<APP_ROOT>/logs")
        self.assertEqual(nested["items"][1], "UID=8820****99")

        win_clean = sanitize_text_for_export(
            "e:/program files/maaresonance/a.json and E:\\Program Files\\MaaResonance\\b.json",
            root_path=PureWindowsPath(r"E:\Program Files\MaaResonance"),  # type: ignore[arg-type]
        )
        self.assertEqual(win_clean, "<APP_ROOT>/a.json and <APP_ROOT>\\b.json")
        # 模拟 Linux Runner 上 Path(r"E:\...") 成为 PosixPath 时的行为
        posix_sim = sanitize_text_for_export(
            "e:/program files/maaresonance/logs",
            root_path=PurePosixPath(r"E:\Program Files\MaaResonance"),  # type: ignore[arg-type]
        )
        self.assertEqual(posix_sim, "<APP_ROOT>/logs")

    def test_pure_python_png_encoder(self) -> None:
        # 构造 BGR 图像：左上蓝色 (B=255, G=0, R=0)，验证编码为 RGB PNG 且自动等比缩放到 max_width=640
        bgr = np.zeros((720, 1280, 3), dtype=np.uint8)
        bgr[:, :, 0] = 200
        bgr[:, :, 1] = 100
        bgr[:, :, 2] = 50
        png = encode_png_bytes(bgr, bgr=True, max_width=640)
        self.assertIsNotNone(png)
        assert png is not None
        self.assertTrue(png.startswith(b"\x89PNG\r\n\x1a\n"))

        ihdr_len = struct.unpack("!I", png[8:12])[0]
        self.assertEqual(png[12:16], b"IHDR")
        self.assertEqual(ihdr_len, 13)
        width, height, depth, color_type = struct.unpack("!IIBB", png[16:26])
        self.assertEqual((width, height, depth, color_type), (640, 360, 8, 2))

        # 读取 IDAT 并验证第一像素 RGB 为 (50, 100, 200)
        pos = 8
        idat_parts: list[bytes] = []
        while pos < len(png):
            length = struct.unpack("!I", png[pos : pos + 4])[0]
            ctype = png[pos + 4 : pos + 8]
            cdata = png[pos + 8 : pos + 8 + length]
            if ctype == b"IDAT":
                idat_parts.append(cdata)
            pos += 12 + length
        raw_scanlines = zlib.decompress(b"".join(idat_parts))
        self.assertEqual(raw_scanlines[0], 0)
        self.assertEqual(tuple(raw_scanlines[1:4]), (50, 100, 200))

        # 2D 灰度与非法输入
        gray = np.full((120, 160), 77, dtype=np.uint8)
        self.assertIsNotNone(encode_png_bytes(gray, max_width=320))
        self.assertIsNone(encode_png_bytes(None))
        self.assertIsNone(encode_png_bytes(np.zeros((10, 10, 1), dtype=np.uint8)))

    def test_diagnostic_recorder_modes_bundle_screenshots_and_rotation(self) -> None:
        snap = snapshot_from_account_payload(
            {
                "uid": "8820083699",
                "wallet": {"coins": 25_000_000, "huashi": 14_880},
                "prison": {"level": 8, "work_tickets": 1200},
            }
        )
        report = plan_prison(snap, PrisonPlanOptions())
        receipt = PrisonRunReceipt(mode="execute_safe_auto", scope="custom")

        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            out_dir = root / "config" / "planning" / "logs"

            # 1. off 模式不写任何文件
            rec_off = PrisonDiagnosticRecorder(export_mode="off", root_path=root, raw_uid="8820083699")
            rec_off.record("init", "test", "ignored")
            self.assertEqual(
                rec_off.export(out_dir),
                {"log_path": None, "bundle_path": None, "latest_log_path": None},
            )
            self.assertFalse(out_dir.exists())

            # 2. log_only 模式只写日志不打包 zip
            rec_log = PrisonDiagnosticRecorder(export_mode="log_only", root_path=root, raw_uid="8820083699")
            rec_log.record("scan", "ok", f"Account at {root}\\accounts\\8820083699.json")
            res_log = rec_log.export(out_dir, snapshot=snap, prison_report=report, run_receipt=receipt)
            self.assertIsNotNone(res_log["log_path"])
            self.assertIsNone(res_log["bundle_path"])
            self.assertTrue((out_dir / "latest_prison_run.log").is_file())
            log_body = res_log["log_path"].read_text(encoding="utf-8")  # type: ignore[union-attr]
            self.assertNotIn("8820083699", log_body)
            self.assertIn("8820****99", log_body)
            self.assertIn("<APP_ROOT>", log_body)

            # 3. bundle_screenshots 模式打包日志、脱敏 JSON、Issue 模版和限幅截图
            rec_shot = PrisonDiagnosticRecorder(
                export_mode="bundle_screenshots",
                root_path=root,
                raw_uid="8820083699",
                options_summary={"exec_mode": "execute_safe_auto", "auto_scope": "custom", "enabled_modules": ["todo_claim"]},
            )
            frame = np.full((720, 1280, 3), 128, dtype=np.uint8)
            for idx in range(MAX_DIAG_SCREENSHOTS + 3):
                captured = rec_shot.capture_frame(f"shot_{idx}", frame)
                self.assertEqual(captured, idx < MAX_DIAG_SCREENSHOTS)
            rec_shot.record_exception("stage.test", RuntimeError(f"boom {root}"), f"Traceback {root}\\agent\\x.py")

            res_bundle = rec_shot.export(out_dir, snapshot=snap, prison_report=report, run_receipt=receipt, max_keep=10)
            zip_path = res_bundle["bundle_path"]
            self.assertIsNotNone(zip_path)
            assert zip_path is not None
            self.assertTrue(zip_path.is_file())

            with zipfile.ZipFile(zip_path, "r") as zf:
                names = set(zf.namelist())
                self.assertIn("prison_run.log", names)
                self.assertIn("issue_template.md", names)
                self.assertIn("report_sanitized.json", names)
                shot_files = [n for n in names if n.startswith("screenshots/")]
                self.assertEqual(len(shot_files), MAX_DIAG_SCREENSHOTS)

                sanitized_json = zf.read("report_sanitized.json").decode("utf-8")
                self.assertNotIn("8820083699", sanitized_json)
                self.assertIn("8820****99", sanitized_json)
                parsed_json = json.loads(sanitized_json)
                self.assertEqual(parsed_json["meta"]["screenshot_count"], MAX_DIAG_SCREENSHOTS)
                self.assertEqual(parsed_json["account_snapshot"]["uid"], "8820****99")

                issue_md = zf.read("issue_template.md").decode("utf-8")
                self.assertIn("8820****99", issue_md)
                self.assertNotIn("8820083699", issue_md)
                self.assertIn("RuntimeError", issue_md)

            # 4. 轮转清理：连续导出多次只保留最新 max_keep 份（latest_prison_run.log 常驻）
            for _ in range(4):
                r_extra = PrisonDiagnosticRecorder(export_mode="bundle", root_path=root, raw_uid="8820083699")
                r_extra.record("loop", "tick", "ok")
                r_extra.export(out_dir, snapshot=snap, prison_report=report, max_keep=2)
            self.assertLessEqual(len(list(out_dir.glob("prison_run_*.log"))), 2)
            self.assertLessEqual(len(list(out_dir.glob("prison_issue_*.zip"))), 2)
            self.assertTrue((out_dir / "latest_prison_run.log").is_file())
            self.assertGreaterEqual(prune_old_diagnostic_files(out_dir, max_keep=1), 0)

    def test_worker_allocation_modes_and_report_rendering(self) -> None:
        self.assertEqual(plan_prisoner_worker_allocation(11, 4, 0, 2, mode="balanced"), {"raw_per_room": 2, "prod_reserve": 3})
        self.assertEqual(plan_prisoner_worker_allocation(11, 4, 100, 2, mode="raw_priority"), {"raw_per_room": 2, "prod_reserve": 3})
        self.assertEqual(plan_prisoner_worker_allocation(18, 4, 100, 2, mode="raw_priority"), {"raw_per_room": 4, "prod_reserve": 2})
        self.assertEqual(plan_prisoner_worker_allocation(18, 4, 0, 2, mode="predeposit_only"), {"raw_per_room": 0, "prod_reserve": 18})

        snap = snapshot_from_account_payload({"uid": "8820083699", "wallet": {"coins": 25_000_000}, "prison": {"level": 8}})
        report = plan_prison(snap, PrisonPlanOptions())
        bundle_p = Path(r"E:\Program Files\MaaResonance\config\planning\logs\prison_issue_20261123_200000.zip")
        log_p = Path(r"E:\Program Files\MaaResonance\config\planning\logs\prison_run_20261123_200000.log")

        html_doc = format_planning_report_html(report, issue_bundle_path=bundle_p, diag_log_path=log_p)
        self.assertIn("问题反馈与专项诊断日志", html_doc)
        self.assertIn("prison_issue_20261123_200000.zip", html_doc)
        self.assertIn("prison_run_20261123_200000.log", html_doc)
        self.assertIn("issue_template.md", html_doc)
        self.assertNotIn("http://", html_doc)
        self.assertNotIn("https://", html_doc)

        lines = format_mxu_plain_summary(report, issue_bundle_path=bundle_p)
        self.assertTrue(any("prison_issue_20261123_200000.zip" in line and "提Issue请附此包" in line for line in lines))


if __name__ == "__main__":
    unittest.main()
