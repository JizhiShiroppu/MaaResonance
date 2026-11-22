"""Pure-stdlib Windows PE icon updater and ICO parser."""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
from dataclasses import dataclass
from pathlib import Path
import struct
import sys
from typing import Sequence

RT_ICON = 3
RT_GROUP_ICON = 14
LOAD_LIBRARY_AS_DATAFILE = 0x00000002
SHCNE_ASSOCCHANGED = 0x08000000
SHCNF_IDLIST = 0x0000
DEFAULT_LANG_ID = 1033
DEFAULT_GROUP_ICON_ID = 32512

_ICONDIR_STRUCT = struct.Struct("<HHH")
_ICONDIRENTRY_STRUCT = struct.Struct("<BBBBHHII")
_GRPICONDIR_STRUCT = struct.Struct("<HHH")
_GRPICONDIRENTRY_STRUCT = struct.Struct("<BBBBHHIH")

ResourceId = int | str


@dataclass(frozen=True)
class IcoEntry:
    """Single image entry parsed from a Windows `.ico` file."""

    width: int
    height: int
    color_count: int
    reserved: int
    planes: int
    bit_count: int
    data: bytes


def parse_ico(ico_bytes: bytes) -> list[IcoEntry]:
    """Parse a Windows `.ico` binary payload into validated `IcoEntry` records."""
    if len(ico_bytes) < _ICONDIR_STRUCT.size:
        raise ValueError("ICO data is truncated before header.")

    reserved, img_type, count = _ICONDIR_STRUCT.unpack_from(ico_bytes, 0)
    if reserved != 0 or img_type != 1 or count < 1:
        raise ValueError(f"Invalid ICO header: reserved={reserved}, type={img_type}, count={count}")

    dir_end = _ICONDIR_STRUCT.size + count * _ICONDIRENTRY_STRUCT.size
    if len(ico_bytes) < dir_end:
        raise ValueError("ICO directory entries exceed file length.")

    entries: list[IcoEntry] = []
    for idx in range(count):
        offset = _ICONDIR_STRUCT.size + idx * _ICONDIRENTRY_STRUCT.size
        width, height, color_count, entry_reserved, planes, bit_count, size, data_off = (
            _ICONDIRENTRY_STRUCT.unpack_from(ico_bytes, offset)
        )
        if size <= 0 or data_off < dir_end or data_off + size > len(ico_bytes):
            raise ValueError(
                f"Invalid ICO entry {idx}: offset={data_off}, size={size}, total={len(ico_bytes)}"
            )
        entries.append(
            IcoEntry(
                width=width,
                height=height,
                color_count=color_count,
                reserved=entry_reserved,
                planes=planes,
                bit_count=bit_count,
                data=ico_bytes[data_off : data_off + size],
            )
        )
    return entries


def build_group_icon_dir(entries: Sequence[IcoEntry], start_id: int = 1) -> bytes:
    """Build a Win32 `RT_GROUP_ICON` (`GRPICONDIR`) resource payload."""
    if not entries:
        raise ValueError("Cannot build RT_GROUP_ICON from empty icon list.")

    parts = [_GRPICONDIR_STRUCT.pack(0, 1, len(entries))]
    for idx, entry in enumerate(entries):
        parts.append(
            _GRPICONDIRENTRY_STRUCT.pack(
                entry.width,
                entry.height,
                entry.color_count,
                entry.reserved,
                entry.planes or 1,
                entry.bit_count or 32,
                len(entry.data),
                start_id + idx,
            )
        )
    return b"".join(parts)


def _require_win32() -> None:
    if sys.platform != "win32":
        raise NotImplementedError("PE icon resource inspection/patching is only supported on Windows.")


def _kernel32() -> ctypes.WinDLL:
    _require_win32()
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)

    k32.LoadLibraryExW.argtypes = [wt.LPCWSTR, wt.HANDLE, wt.DWORD]
    k32.LoadLibraryExW.restype = wt.HMODULE

    k32.FreeLibrary.argtypes = [wt.HMODULE]
    k32.FreeLibrary.restype = wt.BOOL

    k32.BeginUpdateResourceW.argtypes = [wt.LPCWSTR, wt.BOOL]
    k32.BeginUpdateResourceW.restype = wt.HANDLE

    k32.UpdateResourceW.argtypes = [
        wt.HANDLE,
        ctypes.c_void_p,
        ctypes.c_void_p,
        wt.WORD,
        ctypes.c_void_p,
        wt.DWORD,
    ]
    k32.UpdateResourceW.restype = wt.BOOL

    k32.EndUpdateResourceW.argtypes = [wt.HANDLE, wt.BOOL]
    k32.EndUpdateResourceW.restype = wt.BOOL
    return k32


def _decode_resource_id(ptr_val: int) -> ResourceId:
    if ptr_val < 0x10000:
        return int(ptr_val)
    return ctypes.wstring_at(ptr_val)


def _resource_arg(res_id: ResourceId) -> tuple[ctypes.c_void_p, object | None]:
    if isinstance(res_id, int):
        return ctypes.c_void_p(res_id), None
    buf = ctypes.create_unicode_buffer(res_id)
    return ctypes.cast(buf, ctypes.c_void_p), buf


def inspect_exe_icons(exe_path: Path) -> tuple[list[tuple[ResourceId, int]], list[tuple[ResourceId, int]]]:
    """Return `(group_icons, icons)` embedded in a PE executable as `(id_or_name, lang_id)` tuples."""
    k32 = _kernel32()
    enum_names_cb = ctypes.WINFUNCTYPE(wt.BOOL, wt.HMODULE, ctypes.c_void_p, ctypes.c_void_p, wt.LPARAM)
    enum_langs_cb = ctypes.WINFUNCTYPE(
        wt.BOOL, wt.HMODULE, ctypes.c_void_p, ctypes.c_void_p, wt.WORD, wt.LPARAM
    )
    k32.EnumResourceNamesW.argtypes = [wt.HMODULE, ctypes.c_void_p, enum_names_cb, wt.LPARAM]
    k32.EnumResourceNamesW.restype = wt.BOOL
    k32.EnumResourceLanguagesW.argtypes = [
        wt.HMODULE,
        ctypes.c_void_p,
        ctypes.c_void_p,
        enum_langs_cb,
        wt.LPARAM,
    ]
    k32.EnumResourceLanguagesW.restype = wt.BOOL

    hmod = k32.LoadLibraryExW(str(exe_path), None, LOAD_LIBRARY_AS_DATAFILE)
    if not hmod:
        err = ctypes.get_last_error()
        raise OSError(err, f"LoadLibraryExW failed for {exe_path}: {ctypes.FormatError(err)}")

    try:
        results: dict[int, list[tuple[ResourceId, int]]] = {RT_GROUP_ICON: [], RT_ICON: []}
        for rtype in (RT_GROUP_ICON, RT_ICON):
            collected: list[tuple[ResourceId, int]] = []

            @enum_names_cb
            def on_name(h_mod: int, r_type: int, name_ptr: int, _lparam: int) -> bool:
                res_id = _decode_resource_id(name_ptr)
                langs: list[int] = []

                @enum_langs_cb
                def on_lang(_h2: int, _r2: int, _n2: int, lang: int, _lp2: int) -> bool:
                    langs.append(int(lang))
                    return True

                name_arg = ctypes.c_void_p(name_ptr)
                if not k32.EnumResourceLanguagesW(h_mod, ctypes.c_void_p(r_type), name_arg, on_lang, 0):
                    # Ignore ERROR_RESOURCE_NAME_NOT_FOUND / EMPTY, keep empty langs check simple
                    pass
                for lang in langs or [DEFAULT_LANG_ID]:
                    collected.append((res_id, lang))
                return True

            ok = k32.EnumResourceNamesW(hmod, ctypes.c_void_p(rtype), on_name, 0)
            if not ok:
                err = ctypes.get_last_error()
                # ERROR_RESOURCE_DATA_NOT_FOUND (1812) / ERROR_RESOURCE_TYPE_NOT_FOUND (1813)
                if err not in (0, 1812, 1813):
                    raise OSError(err, f"EnumResourceNamesW({rtype}) failed: {ctypes.FormatError(err)}")
            results[rtype] = collected
        return results[RT_GROUP_ICON], results[RT_ICON]
    finally:
        k32.FreeLibrary(hmod)


def _select_target_group(existing_groups: Sequence[tuple[ResourceId, int]]) -> tuple[ResourceId, int]:
    for res_id, lang in existing_groups:
        if res_id == DEFAULT_GROUP_ICON_ID:
            return res_id, lang
    if existing_groups:
        return existing_groups[0]
    return DEFAULT_GROUP_ICON_ID, DEFAULT_LANG_ID


def patch_exe_icon(
    exe_path: Path,
    ico_path: Path,
    *,
    notify_shell: bool = False,
) -> tuple[ResourceId, int, int]:
    """Replace the Windows PE icon group in `exe_path` with all frames from `ico_path`."""
    _require_win32()
    exe_path = Path(exe_path)
    ico_path = Path(ico_path)
    entries = parse_ico(ico_path.read_bytes())

    existing_groups, existing_icons = inspect_exe_icons(exe_path)
    group_id, target_lang = _select_target_group(existing_groups)
    group_payload = build_group_icon_dir(entries, start_id=1)

    k32 = _kernel32()
    handle = k32.BeginUpdateResourceW(str(exe_path), False)
    if not handle:
        err = ctypes.get_last_error()
        raise OSError(err, f"BeginUpdateResourceW failed for {exe_path}: {ctypes.FormatError(err)}")

    discard = True
    try:
        for rtype, items in ((RT_GROUP_ICON, existing_groups), (RT_ICON, existing_icons)):
            for res_id, lang in items:
                name_ptr, _keep = _resource_arg(res_id)
                if not k32.UpdateResourceW(handle, ctypes.c_void_p(rtype), name_ptr, lang, None, 0):
                    err = ctypes.get_last_error()
                    raise OSError(
                        err,
                        f"Failed removing resource type={rtype} id={res_id}: {ctypes.FormatError(err)}",
                    )

        for idx, entry in enumerate(entries, start=1):
            buf = ctypes.create_string_buffer(entry.data, len(entry.data))
            if not k32.UpdateResourceW(
                handle,
                ctypes.c_void_p(RT_ICON),
                ctypes.c_void_p(idx),
                target_lang,
                ctypes.cast(buf, ctypes.c_void_p),
                len(entry.data),
            ):
                err = ctypes.get_last_error()
                raise OSError(err, f"Failed writing RT_ICON #{idx}: {ctypes.FormatError(err)}")

        group_ptr, _keep_grp_name = _resource_arg(group_id)
        group_buf = ctypes.create_string_buffer(group_payload, len(group_payload))
        if not k32.UpdateResourceW(
            handle,
            ctypes.c_void_p(RT_GROUP_ICON),
            group_ptr,
            target_lang,
            ctypes.cast(group_buf, ctypes.c_void_p),
            len(group_payload),
        ):
            err = ctypes.get_last_error()
            raise OSError(err, f"Failed writing RT_GROUP_ICON {group_id}: {ctypes.FormatError(err)}")

        discard = False
    finally:
        ok = k32.EndUpdateResourceW(handle, discard)
        if not ok and not discard:
            err = ctypes.get_last_error()
            raise OSError(err, f"EndUpdateResourceW failed for {exe_path}: {ctypes.FormatError(err)}")

    if notify_shell:
        shell32 = ctypes.WinDLL("shell32", use_last_error=False)
        shell32.SHChangeNotify.argtypes = [wt.LONG, wt.UINT, wt.LPCVOID, wt.LPCVOID]
        shell32.SHChangeNotify.restype = None
        shell32.SHChangeNotify(SHCNE_ASSOCCHANGED, SHCNF_IDLIST, None, None)

    return group_id, target_lang, len(entries)


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 2:
        print("Usage: python tools/win32_exe_icon.py <exe_path> <ico_path>", file=sys.stderr)
        return 2
    group_id, lang_id, count = patch_exe_icon(Path(args[0]), Path(args[1]), notify_shell=True)
    print(f"Updated PE icon on {args[0]}: group={group_id}, lang={lang_id}, frames={count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
