import ctypes
import ctypes.wintypes as wt
import json
from pathlib import Path
import shutil
import struct
import sys
import tempfile
import unittest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "tools"))

from sync_to_packaged import sync_to_packaged
from win32_exe_icon import (
    IcoEntry,
    build_group_icon_dir,
    inspect_exe_icons,
    parse_ico,
    patch_exe_icon,
)


class AppIconTests(unittest.TestCase):
    def test_interface_icon_and_png_asset_are_valid(self) -> None:
        interface_path = REPO_ROOT / "assets" / "interface.json"
        interface = json.loads(interface_path.read_text(encoding="utf-8"))
        icon_rel = interface.get("icon")
        self.assertEqual(icon_rel, "resource/icon/logo.png")

        png_path = REPO_ROOT / "assets" / icon_rel
        self.assertTrue(png_path.is_file(), f"Missing icon file: {png_path}")
        raw = png_path.read_bytes()
        self.assertEqual(raw[:8], b"\x89PNG\r\n\x1a\n")
        self.assertEqual(raw[12:16], b"IHDR")
        width, height, bit_depth, color_type = struct.unpack(">IIBB", raw[16:26])
        self.assertEqual((width, height), (512, 512))
        self.assertEqual(bit_depth, 8)
        self.assertEqual(color_type, 6)  # RGBA

    def test_logo_ico_contains_expected_multi_size_frames(self) -> None:
        ico_path = REPO_ROOT / "assets" / "resource" / "icon" / "logo.ico"
        self.assertTrue(ico_path.is_file(), f"Missing ICO file: {ico_path}")
        entries = parse_ico(ico_path.read_bytes())
        sizes = [(e.width or 256, e.height or 256) for e in entries]
        self.assertEqual(
            sizes,
            [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
        )
        for entry in entries:
            self.assertGreater(len(entry.data), 0)

    def test_build_group_icon_dir_packs_expected_structure(self) -> None:
        entries = [
            IcoEntry(width=16, height=16, color_count=0, reserved=0, planes=0, bit_count=32, data=b"a" * 100),
            IcoEntry(width=0, height=0, color_count=0, reserved=0, planes=1, bit_count=32, data=b"b" * 200),
        ]
        payload = build_group_icon_dir(entries, start_id=5)
        self.assertEqual(len(payload), 6 + 2 * 14)
        reserved, rtype, count = struct.unpack_from("<HHH", payload, 0)
        self.assertEqual((reserved, rtype, count), (0, 1, 2))
        first = struct.unpack_from("<BBBBHHIH", payload, 6)
        second = struct.unpack_from("<BBBBHHIH", payload, 20)
        self.assertEqual(first, (16, 16, 0, 0, 1, 32, 100, 5))
        self.assertEqual(second, (0, 0, 0, 0, 1, 32, 200, 6))

    def test_parse_ico_rejects_malformed_inputs(self) -> None:
        with self.assertRaises(ValueError):
            parse_ico(b"\x00\x00")
        bad_type = struct.pack("<HHH", 0, 2, 1) + b"\x00" * 16
        with self.assertRaises(ValueError):
            parse_ico(bad_type)
        oob_entry = struct.pack("<HHH", 0, 1, 1) + struct.pack("<BBBBHHII", 16, 16, 0, 0, 1, 32, 50, 999)
        with self.assertRaises(ValueError):
            parse_ico(oob_entry)

    @unittest.skipUnless(sys.platform == "win32", "Windows PE resource patching only runs on win32")
    def test_patch_exe_icon_and_sync_to_packaged(self) -> None:
        packaged_exe = Path(r"E:\Program Files\MaaResonance\MaaResonance.exe")
        source_exe = packaged_exe if packaged_exe.is_file() else Path(sys.executable)
        ico_path = REPO_ROOT / "assets" / "resource" / "icon" / "logo.ico"

        shell32 = ctypes.WinDLL("shell32", use_last_error=True)
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        shell32.ExtractIconExW.argtypes = [
            wt.LPCWSTR,
            ctypes.c_int,
            ctypes.POINTER(wt.HICON),
            ctypes.POINTER(wt.HICON),
            wt.UINT,
        ]
        shell32.ExtractIconExW.restype = wt.UINT
        user32.DestroyIcon.argtypes = [wt.HICON]
        user32.DestroyIcon.restype = wt.BOOL

        with tempfile.TemporaryDirectory() as tmp_dir:
            target_root = Path(tmp_dir)
            tmp_exe = target_root / "MaaResonance.exe"
            shutil.copy2(source_exe, tmp_exe)

            sync_to_packaged(target_root)

            self.assertTrue((target_root / "resource" / "icon" / "logo.png").is_file())
            self.assertTrue((target_root / "resource" / "icon" / "logo.ico").is_file())
            synced_iface = json.loads((target_root / "interface.json").read_text(encoding="utf-8"))
            self.assertEqual(synced_iface.get("icon"), "resource/icon/logo.png")

            groups, icons = inspect_exe_icons(tmp_exe)
            self.assertEqual(len(groups), 1)
            self.assertEqual([res_id for res_id, _ in icons], [1, 2, 3, 4, 5, 6, 7])

            large = wt.HICON()
            small = wt.HICON()
            extracted = shell32.ExtractIconExW(str(tmp_exe), 0, ctypes.byref(large), ctypes.byref(small), 1)
            try:
                self.assertGreaterEqual(extracted, 1)
                self.assertTrue(bool(large.value) or bool(small.value))
            finally:
                if large.value:
                    user32.DestroyIcon(large)
                if small.value:
                    user32.DestroyIcon(small)

            # Verify direct patch_exe_icon return value is consistent
            group_id, lang_id, count = patch_exe_icon(tmp_exe, ico_path, notify_shell=False)
            self.assertEqual(count, 7)
            self.assertIn((group_id, lang_id), inspect_exe_icons(tmp_exe)[0])


if __name__ == "__main__":
    unittest.main()
