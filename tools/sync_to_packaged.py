from __future__ import annotations

import json
from pathlib import Path
import shutil
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TARGET_ROOT = Path(r"E:\Program Files\MaaResonance")


def _copy_tree_files(src_dir: Path, dst_dir: Path, *, suffixes: tuple[str, ...]) -> int:
    count = 0
    for src_file in src_dir.rglob("*"):
        if not src_file.is_file():
            continue
        if "__pycache__" in src_file.parts:
            continue
        if suffixes and src_file.suffix.lower() not in suffixes:
            continue
        rel = src_file.relative_to(src_dir)
        dst_file = dst_dir / rel
        dst_file.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_file, dst_file)
        count += 1
    return count


def _packaged_dev_version(raw_version: object) -> str:
    """Return a non-beta/rc semver prerelease so MXU treats the synced build as local dev and skips auto-update."""
    text = str(raw_version or "v2.0.0").strip()
    base = text.split("+", 1)[0].split("-", 1)[0] or "v2.0.0"
    if not base.startswith("v"):
        base = f"v{base}"
    return f"{base}-dev.local"


def sync_to_packaged(target_root: Path = DEFAULT_TARGET_ROOT) -> None:
    if not target_root.exists():
        raise FileNotFoundError(f"Packaged target not found: {target_root}")

    copied = 0
    copied += _copy_tree_files(REPO_ROOT / "maa_resonance", target_root / "maa_resonance", suffixes=(".py",))
    copied += _copy_tree_files(REPO_ROOT / "agent", target_root / "agent", suffixes=(".py",))
    copied += _copy_tree_files(
        REPO_ROOT / "assets" / "resource" / "tasks",
        target_root / "resource" / "tasks",
        suffixes=(".json",),
    )
    for sub in ("assist", "business", "combat", "common", "daily", "mainline", "story"):
        src_pipe = REPO_ROOT / "assets" / "resource" / "base" / "pipeline" / sub
        if src_pipe.exists():
            copied += _copy_tree_files(
                src_pipe,
                target_root / "resource" / "base" / "pipeline" / sub,
                suffixes=(".json",),
            )
    src_quest_img = REPO_ROOT / "assets" / "resource" / "base" / "image" / "quest"
    if src_quest_img.exists():
        copied += _copy_tree_files(
            src_quest_img,
            target_root / "resource" / "base" / "image" / "quest",
            suffixes=(".png",),
        )
    src_pc = REPO_ROOT / "assets" / "resource" / "pc"
    if src_pc.exists():
        copied += _copy_tree_files(
            src_pc,
            target_root / "resource" / "pc",
            suffixes=(".json", ".png"),
        )
    stale_win32 = target_root / "resource" / "win32"
    if stale_win32.exists():
        shutil.rmtree(stale_win32)

    src_readme = REPO_ROOT / "README.md"
    if src_readme.exists():
        shutil.copy2(src_readme, target_root / "README.md")
        copied += 1

    dst_interface = target_root / "interface.json"
    backup_interface = target_root / "interface.json.bak"
    if dst_interface.exists() and not backup_interface.exists():
        shutil.copy2(dst_interface, backup_interface)

    interface_data = json.loads((REPO_ROOT / "assets" / "interface.json").read_text(encoding="utf-8"))
    interface_data["version"] = _packaged_dev_version(interface_data.get("version"))
    # Strip MirrorChyan RID in the local packaged copy so MXU will not auto-download and overwrite it.
    interface_data.pop("mirrorchyan_rid", None)
    if isinstance(interface_data.get("agent"), dict):
        interface_data["agent"]["child_exec"] = "./python/python.exe"
        interface_data["agent"]["child_args"] = ["-u", "./agent/main.py"]
    dst_interface.write_text(json.dumps(interface_data, ensure_ascii=False, indent=4), encoding="utf-8")

    print(f"Synced {copied} files + interface.json -> {target_root}")


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_TARGET_ROOT
    sync_to_packaged(target)
