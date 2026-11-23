"""整顿中心（监狱）运行时配置解析与专项诊断日志 / Issue 压缩包导出（纯 Python 零外置视觉依赖）。"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import json
from pathlib import Path
import platform
import re
import struct
import sys
import time
from typing import Any, Mapping, Sequence
import zipfile
import zlib

import numpy as np

ALL_PRISON_AUTO_MODULES: tuple[str, ...] = (
    "todo_claim",
    "prisoner_checkin",
    "finance_auto_refill",
    "order_deliver",
    "order_delete_free",
    "building_upgrade",
    "warehouse_coin_expand",
    "shop_recipes",
    "shop_items",
    "raw_predeposit",
    "raw_start",
    "ws_edit_team",
    "ws_machine_upgrade",
    "ws_start_prod",
)

PRISON_MODULE_LABELS: dict[str, str] = {
    "todo_claim": "事项一览自动领奖",
    "prisoner_checkin": "名册未整顿囚犯办理入住",
    "finance_auto_refill": "财务中心保证金 80% 自动补满",
    "order_deliver": "黑月运输订单自动交付",
    "order_delete_free": "黑月低效订单免费删除",
    "building_upgrade": "核心与合规建筑升级/解锁",
    "warehouse_coin_expand": "双仓左侧铁盟币扩容",
    "shop_recipes": "兑换商店冲级配方兑换",
    "shop_items": "兑换商店拉普拉斯协议/胶卷兑换",
    "raw_predeposit": "原料车间铁盟币预存",
    "raw_start": "原料车间配员与启动采集",
    "ws_edit_team": "生产车间快速编队与设组长",
    "ws_machine_upgrade": "生产车间 LV6 缝纫机升级",
    "ws_start_prod": "生产车间高优白名单排产",
}

PRISON_SCOPE_PRESETS: dict[str, frozenset[str]] = {
    "full_safe": frozenset(ALL_PRISON_AUTO_MODULES),
    "orders_and_prod": frozenset(
        {
            "todo_claim",
            "prisoner_checkin",
            "finance_auto_refill",
            "order_deliver",
            "order_delete_free",
            "raw_predeposit",
            "raw_start",
            "ws_edit_team",
            "ws_start_prod",
        }
    ),
    "build_and_buy": frozenset(
        {
            "building_upgrade",
            "warehouse_coin_expand",
            "shop_recipes",
            "shop_items",
        }
    ),
}

VALID_DIAG_EXPORT_MODES: tuple[str, ...] = (
    "off",
    "log_only",
    "bundle",
    "bundle_screenshots",
)

VALID_PROD_DURATION_PREFS: tuple[str, ...] = ("8h", "4h", "2h")
VALID_RAW_WORKER_MODES: tuple[str, ...] = ("balanced", "raw_priority", "predeposit_only")

MAX_DIAG_SCREENSHOTS: int = 6
DEFAULT_MAX_DIAG_FILES: int = 10

_USER_HOME_RE = re.compile(r"[A-Za-z]:[\\/]+Users[\\/]+[^\\/\s\"']+")
_DIAG_FILENAME_SANITIZE_RE = re.compile(r"[^A-Za-z0-9_.-]+")


def _safe_int(value: Any, default: int, *, minimum: int = 0) -> int:
    if isinstance(value, bool):
        return default
    try:
        text = str(value).strip()
        if not text or text.startswith("{"):
            return default
        parsed = int(float(text))
        return max(minimum, parsed)
    except (TypeError, ValueError):
        return default


def _safe_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return default


@dataclass(frozen=True)
class PrisonRuntimeConfig:
    """整顿中心任务的解析后运行时配置（支持预设范围与 14 项细粒度模块开关）。"""

    exec_mode: str = "plan_only"
    auto_scope: str = "full_safe"
    enabled_modules: frozenset[str] = field(default_factory=lambda: frozenset(ALL_PRISON_AUTO_MODULES))
    reserve_coins: int = 15_000_000
    scan_subpages: bool = True
    allow_huashi_motors: bool = False
    allow_huashi_warehouse: bool = False
    player_level: int = 71
    auto_open_report: bool = True
    prod_duration_pref: str = "8h"
    raw_worker_mode: str = "balanced"
    warehouse_batch_cap: int = 2
    core_upgrade_cap: int = 3
    diag_export_mode: str = "bundle"

    def is_enabled(self, module_key: str) -> bool:
        return str(module_key) in self.enabled_modules

    def to_summary_dict(self) -> dict[str, Any]:
        return {
            "exec_mode": self.exec_mode,
            "auto_scope": self.auto_scope,
            "enabled_modules": sorted(self.enabled_modules),
            "reserve_coins": int(self.reserve_coins),
            "scan_subpages": bool(self.scan_subpages),
            "allow_huashi_motors": bool(self.allow_huashi_motors),
            "allow_huashi_warehouse": bool(self.allow_huashi_warehouse),
            "player_level": int(self.player_level),
            "auto_open_report": bool(self.auto_open_report),
            "prod_duration_pref": self.prod_duration_pref,
            "raw_worker_mode": self.raw_worker_mode,
            "warehouse_batch_cap": int(self.warehouse_batch_cap),
            "core_upgrade_cap": int(self.core_upgrade_cap),
            "diag_export_mode": self.diag_export_mode,
        }


def resolve_prison_runtime_config(params: Mapping[str, Any] | None) -> PrisonRuntimeConfig:
    """从 pipeline attach 与 action param 合并字典中安全解析整顿中心完整配置。"""
    raw = params if isinstance(params, Mapping) else {}

    raw_mode = str(raw.get("exec_mode") or "plan_only").strip()
    exec_mode = "execute_safe_auto" if raw_mode == "execute_safe_auto" else "plan_only"

    raw_scope = str(raw.get("auto_scope") or "full_safe").strip()
    auto_scope = raw_scope if raw_scope in (*PRISON_SCOPE_PRESETS.keys(), "custom") else "full_safe"

    if auto_scope in PRISON_SCOPE_PRESETS:
        enabled_modules = PRISON_SCOPE_PRESETS[auto_scope]
    else:
        picked = frozenset(
            key
            for key in ALL_PRISON_AUTO_MODULES
            if _safe_bool(raw.get(f"mod_pick_{key}"), False)
        )
        ui_configured = _safe_bool(raw.get("modules_ui_configured"), False)
        if ui_configured:
            enabled_modules = picked
        elif picked:
            enabled_modules = picked
        elif isinstance(raw.get("enabled_modules"), (list, tuple, set, frozenset)):
            enabled_modules = frozenset(
                str(item).strip()
                for item in raw["enabled_modules"]
                if str(item).strip() in ALL_PRISON_AUTO_MODULES
            )
        else:
            enabled_modules = PRISON_SCOPE_PRESETS["full_safe"]

    base_reserve = _safe_int(raw.get("reserve_coins"), 15_000_000, minimum=0)
    if _safe_bool(raw.get("use_custom_reserve_coins"), False):
        reserve_coins = _safe_int(raw.get("custom_reserve_coins"), base_reserve, minimum=0)
    else:
        reserve_coins = base_reserve

    scan_subpages = _safe_bool(raw.get("scan_subpages"), True)
    allow_huashi_motors = _safe_bool(raw.get("allow_huashi_motors"), False)
    allow_huashi_warehouse = _safe_bool(raw.get("allow_huashi_warehouse"), False)
    player_level = _safe_int(raw.get("player_level"), 71, minimum=1)
    auto_open_report = _safe_bool(raw.get("auto_open_report"), True)

    raw_dur = str(raw.get("prod_duration_pref") or "8h").strip().lower()
    prod_duration_pref = raw_dur if raw_dur in VALID_PROD_DURATION_PREFS else "8h"

    raw_wrk = str(raw.get("raw_worker_mode") or "balanced").strip().lower()
    raw_worker_mode = raw_wrk if raw_wrk in VALID_RAW_WORKER_MODES else "balanced"

    warehouse_batch_cap = min(5, max(1, _safe_int(raw.get("warehouse_batch_cap"), 2, minimum=1)))
    core_upgrade_cap = min(5, max(1, _safe_int(raw.get("core_upgrade_cap"), 3, minimum=1)))

    raw_diag = str(raw.get("diag_export_mode") or "bundle").strip().lower()
    diag_export_mode = raw_diag if raw_diag in VALID_DIAG_EXPORT_MODES else "bundle"

    return PrisonRuntimeConfig(
        exec_mode=exec_mode,
        auto_scope=auto_scope,
        enabled_modules=enabled_modules,
        reserve_coins=reserve_coins,
        scan_subpages=scan_subpages,
        allow_huashi_motors=allow_huashi_motors,
        allow_huashi_warehouse=allow_huashi_warehouse,
        player_level=player_level,
        auto_open_report=auto_open_report,
        prod_duration_pref=prod_duration_pref,
        raw_worker_mode=raw_worker_mode,
        warehouse_batch_cap=warehouse_batch_cap,
        core_upgrade_cap=core_upgrade_cap,
        diag_export_mode=diag_export_mode,
    )


def mask_uid(uid: Any) -> str:
    """对账号 UID 做脱敏处理，仅保留头尾用于定位同时避免泄露完整 UID。"""
    text = str(uid or "").strip()
    if not text or text.lower() == "unknown":
        return "unknown"
    if len(text) >= 6:
        return f"{text[:4]}{'*' * max(2, len(text) - 6)}{text[-2:]}"
    if len(text) >= 2:
        return f"{text[0]}***{text[-1]}"
    return "***"


def sanitize_text_for_export(
    text: Any,
    *,
    root_path: Path | None = None,
    raw_uid: str = "",
) -> str:
    """脱敏导出的文本与路径（隐藏本机盘符目录、Windows 用户名及完整 UID）。"""
    result = str(text if text is not None else "")
    if not result:
        return ""

    if root_path is not None:
        raw_variants = [str(root_path), root_path.as_posix()]
        resolve_fn = getattr(root_path, "resolve", None)
        if callable(resolve_fn):
            try:
                resolved = resolve_fn()
                raw_variants.extend((str(resolved), resolved.as_posix()))
            except OSError:
                pass
        variants: set[str] = set()
        for item in raw_variants:
            if item:
                variants.add(item)
                variants.add(item.replace("\\", "/"))
                variants.add(item.replace("/", "\\"))
        for variant in sorted(variants, key=len, reverse=True):
            result = re.sub(re.escape(variant), "<APP_ROOT>", result, flags=re.IGNORECASE)

    result = _USER_HOME_RE.sub("<USER_HOME>", result)

    uid_clean = str(raw_uid or "").strip()
    if len(uid_clean) >= 4 and uid_clean.lower() != "unknown":
        masked = mask_uid(uid_clean)
        result = result.replace(uid_clean, masked)
    return result


def sanitize_json_payload(
    obj: Any,
    *,
    root_path: Path | None = None,
    raw_uid: str = "",
) -> Any:
    """递归脱敏可序列化对象中的敏感路径与 UID 字段。"""
    if isinstance(obj, Mapping):
        sanitized: dict[str, Any] = {}
        for key, val in obj.items():
            key_str = str(key)
            if key_str == "uid":
                sanitized[key_str] = mask_uid(val)
            else:
                sanitized[key_str] = sanitize_json_payload(val, root_path=root_path, raw_uid=raw_uid)
        return sanitized
    if isinstance(obj, (list, tuple)):
        return [sanitize_json_payload(item, root_path=root_path, raw_uid=raw_uid) for item in obj]
    if isinstance(obj, Path):
        return sanitize_text_for_export(str(obj), root_path=root_path, raw_uid=raw_uid)
    if isinstance(obj, str):
        return sanitize_text_for_export(obj, root_path=root_path, raw_uid=raw_uid)
    return obj


def _png_chunk(tag: bytes, payload: bytes) -> bytes:
    crc = zlib.crc32(tag + payload) & 0xFFFFFFFF
    return struct.pack("!I", len(payload)) + tag + payload + struct.pack("!I", crc)


def encode_png_bytes(
    image: Any,
    *,
    bgr: bool = True,
    max_width: int = 640,
) -> bytes | None:
    """纯 Python + numpy 将图像编码为紧凑 PNG 字节流（零 cv2 / PIL 依赖）。"""
    if not isinstance(image, np.ndarray):
        return None
    if image.ndim not in (2, 3) or image.shape[0] <= 0 or image.shape[1] <= 0:
        return None

    arr = image
    if arr.dtype != np.uint8:
        arr = np.clip(arr, 0, 255).astype(np.uint8)

    if arr.ndim == 2:
        rgb = np.stack((arr, arr, arr), axis=-1)
    else:
        if arr.shape[2] < 3:
            return None
        channels = arr[:, :, :3]
        rgb = channels[:, :, ::-1] if bgr else channels

    width = int(rgb.shape[1])
    if max_width > 0 and width > max_width:
        step = max(1, (width + max_width - 1) // max_width)
        rgb = rgb[::step, ::step]

    rgb = np.ascontiguousarray(rgb, dtype=np.uint8)
    out_h, out_w = int(rgb.shape[0]), int(rgb.shape[1])
    if out_h <= 0 or out_w <= 0:
        return None

    # 每行前插入 1 字节滤波器类型 0（None），再用 zlib 压缩成标准 IDAT
    flat_rows = rgb.reshape(out_h, out_w * 3)
    with_filter = np.empty((out_h, out_w * 3 + 1), dtype=np.uint8)
    with_filter[:, 0] = 0
    with_filter[:, 1:] = flat_rows
    compressed = zlib.compress(with_filter.tobytes(), level=6)

    ihdr = struct.pack("!IIBBBBB", out_w, out_h, 8, 2, 0, 0, 0)
    return b"".join(
        (
            b"\x89PNG\r\n\x1a\n",
            _png_chunk(b"IHDR", ihdr),
            _png_chunk(b"IDAT", compressed),
            _png_chunk(b"IEND", b""),
        )
    )


def prune_old_diagnostic_files(
    output_dir: Path,
    *,
    max_keep: int = DEFAULT_MAX_DIAG_FILES,
) -> int:
    """按文件名时间倒序清理超出保留数量的旧日志与 Issue 压缩包。"""
    if not output_dir.exists() or not output_dir.is_dir():
        return 0
    keep = max(0, int(max_keep))
    removed = 0
    for pattern in ("prison_run_*.log", "prison_issue_*.zip"):
        matched = sorted(
            (p for p in output_dir.glob(pattern) if p.is_file()),
            key=lambda p: p.name,
            reverse=True,
        )
        for stale in matched[keep:]:
            try:
                stale.unlink()
                removed += 1
            except OSError:
                pass
    return removed


def _dump_model_or_obj(value: Any) -> Any:
    if value is None:
        return None
    dump_fn = getattr(value, "model_dump", None)
    if callable(dump_fn):
        return dump_fn(mode="json")
    return value


class PrisonDiagnosticRecorder:
    """记录单次整顿中心运行的阶段耗时、决策与异常现场，并打包成便于提交 Issue 的 zip。"""

    def __init__(
        self,
        *,
        export_mode: str = "bundle",
        root_path: Path | None = None,
        raw_uid: str = "unknown",
        options_summary: Mapping[str, Any] | None = None,
    ) -> None:
        raw_mode = str(export_mode or "bundle").strip().lower()
        self.export_mode: str = raw_mode if raw_mode in VALID_DIAG_EXPORT_MODES else "bundle"
        self.root_path: Path | None = root_path
        self.raw_uid: str = str(raw_uid or "unknown").strip() or "unknown"
        self.options_summary: dict[str, Any] = dict(options_summary or {})
        self.started_at: datetime = datetime.now()
        self.started_mono: float = time.monotonic()
        self.events: list[dict[str, Any]] = []
        self.exceptions: list[dict[str, str]] = []
        self.screenshots: list[tuple[str, bytes]] = []

    def set_uid(self, uid: str) -> None:
        cleaned = str(uid or "").strip()
        if cleaned and cleaned.lower() != "unknown":
            self.raw_uid = cleaned

    def set_options(self, options_summary: Mapping[str, Any]) -> None:
        self.options_summary = dict(options_summary)

    def _elapsed_ms(self) -> int:
        return max(0, int(round((time.monotonic() - self.started_mono) * 1000)))

    def record(
        self,
        stage: str,
        event: str,
        detail: str = "",
        *,
        data: Mapping[str, Any] | None = None,
        level: str = "INFO",
    ) -> None:
        if self.export_mode == "off":
            return
        entry: dict[str, Any] = {
            "ts": datetime.now().strftime("%H:%M:%S.%f")[:-3],
            "elapsed_ms": self._elapsed_ms(),
            "level": str(level or "INFO").upper(),
            "stage": str(stage or "general"),
            "event": str(event or "note"),
            "detail": str(detail or ""),
        }
        if data:
            entry["data"] = dict(data)
        self.events.append(entry)

    def record_exception(self, stage: str, exc: BaseException, tb_text: str = "") -> None:
        if self.export_mode == "off":
            return
        exc_line = f"{type(exc).__name__}: {exc}"
        self.exceptions.append(
            {
                "ts": datetime.now().strftime("%H:%M:%S.%f")[:-3],
                "stage": str(stage or "run"),
                "error": exc_line,
                "traceback": str(tb_text or "").strip(),
            }
        )
        self.record(stage, "exception", exc_line, level="ERROR")

    def capture_frame(self, tag: str, image: Any) -> bool:
        """仅在开启 `bundle_screenshots` 且未达数量上限时压缩保留 PNG 现场截图。"""
        if self.export_mode != "bundle_screenshots":
            return False
        if len(self.screenshots) >= MAX_DIAG_SCREENSHOTS or image is None:
            return False
        png_bytes = encode_png_bytes(image, bgr=True, max_width=640)
        if not png_bytes:
            return False
        safe_tag = _DIAG_FILENAME_SANITIZE_RE.sub("_", str(tag or "frame")).strip("_") or "frame"
        filename = f"{len(self.screenshots) + 1:02d}_{safe_tag[:40]}.png"
        self.screenshots.append((filename, png_bytes))
        return True

    def render_text_log(self) -> str:
        sanitized_opts = sanitize_json_payload(
            self.options_summary,
            root_path=self.root_path,
            raw_uid=self.raw_uid,
        )
        lines = [
            "============================================================",
            "MaaResonance 整顿中心（监狱）专项诊断日志",
            f"开始时间: {self.started_at.strftime('%Y-%m-%d %H:%M:%S')}",
            f"UID(已脱敏): {mask_uid(self.raw_uid)}",
            f"运行环境: {platform.system()} {platform.release()} | Python {sys.version.split()[0]}",
            f"诊断模式: {self.export_mode}",
            f"运行时配置: {json.dumps(sanitized_opts, ensure_ascii=False, sort_keys=True)}",
            "============================================================",
            "",
        ]
        for ev in self.events:
            sanitized_ev = sanitize_json_payload(ev, root_path=self.root_path, raw_uid=self.raw_uid)
            base = (
                f"[{sanitized_ev['ts']} +{sanitized_ev['elapsed_ms']}ms] "
                f"[{sanitized_ev['level']}] [{sanitized_ev['stage']}/{sanitized_ev['event']}] "
                f"{sanitized_ev['detail']}"
            )
            if "data" in sanitized_ev:
                data_json = json.dumps(sanitized_ev["data"], ensure_ascii=False, sort_keys=True)
                base = f"{base} | data={data_json}"
            lines.append(base)

        if self.exceptions:
            lines.extend(["", "---------------- 异常堆栈记录 ----------------"])
            for exc_item in self.exceptions:
                s_item = sanitize_json_payload(exc_item, root_path=self.root_path, raw_uid=self.raw_uid)
                lines.append(f"[{s_item['ts']}] [{s_item['stage']}] {s_item['error']}")
                if s_item.get("traceback"):
                    lines.append(str(s_item["traceback"]))
                lines.append("")

        return "\n".join(lines) + "\n"

    def render_issue_template(
        self,
        *,
        prison_report: Any = None,
        run_receipt: Any = None,
        bundle_filename: str = "",
    ) -> str:
        masked_uid = mask_uid(self.raw_uid)
        phase_str = str(getattr(prison_report, "phase", "unknown")) if prison_report is not None else "unknown"
        prison_lv = getattr(prison_report, "prison_level", "unknown") if prison_report is not None else "unknown"
        exec_mode = self.options_summary.get("exec_mode", "unknown")
        auto_scope = self.options_summary.get("auto_scope", "unknown")
        reserve_coins = self.options_summary.get("reserve_coins", "unknown")
        enabled_cnt = len(self.options_summary.get("enabled_modules") or ())

        receipt_lines: list[str] = []
        guard_lines: list[str] = []
        if run_receipt is not None:
            executed = list(getattr(run_receipt, "executed", ()) or ())
            skipped = list(getattr(run_receipt, "skipped", ()) or ())
            aborts = list(getattr(run_receipt, "guard_aborts", ()) or ())
            receipt_lines.append(
                f"- 执行统计：完成 `{len(executed)}` 项 / 跳过 `{len(skipped)}` 项 / 护栏拦截 `{len(aborts)}` 项"
            )
            receipt_lines.append(
                f"- 资产变化：铁盟币 `{getattr(run_receipt, 'coins_before', 0):,}` -> `{getattr(run_receipt, 'coins_after', 0):,}` | "
                f"工票 `{getattr(run_receipt, 'tickets_before', 0):,}` -> `{getattr(run_receipt, 'tickets_after', 0):,}` | "
                f"桦石 `{getattr(run_receipt, 'huashi_before', 0):,}` -> `{getattr(run_receipt, 'huashi_after', 0):,}`"
            )
            for item in aborts:
                detail = sanitize_text_for_export(getattr(item, "detail", ""), root_path=self.root_path, raw_uid=self.raw_uid)
                guard_lines.append(f"- [护栏] `{getattr(item, 'target', '')}` ({getattr(item, 'action_type', '')}): {detail}")
            for item in skipped:
                if getattr(item, "status", "") == "failed":
                    detail = sanitize_text_for_export(getattr(item, "detail", ""), root_path=self.root_path, raw_uid=self.raw_uid)
                    guard_lines.append(f"- [异常] `{getattr(item, 'target', '')}` ({getattr(item, 'action_type', '')}): {detail}")

        exc_lines: list[str] = []
        for exc_item in self.exceptions:
            err = sanitize_text_for_export(exc_item.get("error", ""), root_path=self.root_path, raw_uid=self.raw_uid)
            exc_lines.append(f"- `[{exc_item.get('stage', 'run')}]` {err}")

        lines = [
            "# 整顿中心（监狱）自动问题反馈 / Issue 模版",
            "",
            "> 请在 GitHub 仓库 Issues 页面新建 Issue，粘贴下方内容并将整个 `.zip` 诊断包拖入正文上传（包内已自动脱敏 UID 与本机路径）。",
            "",
            "## 1. 现象描述（请用户补充）",
            "- 发生了什么异常 / 卡在哪个页面 / 点偏了哪个按钮：",
            "- 模拟器/客户端与分辨率（例如 MuMu 1280x720 / PC 端）：",
            "",
            "## 2. 自动采集环境与配置",
            f"- 诊断包文件名：`{bundle_filename or 'prison_issue_<timestamp>.zip'}`",
            f"- 时间：`{self.started_at.strftime('%Y-%m-%d %H:%M:%S')}` | 系统：`{platform.system()} {platform.release()}` | Python：`{sys.version.split()[0]}`",
            f"- UID（已脱敏）：`{masked_uid}` | 整顿等级：`LV{prison_lv}`（阶段：`{phase_str}`）",
            f"- 执行模式：`{exec_mode}` | 执行范围：`{auto_scope}`（启用模块数：`{enabled_cnt}`） | 保留底线：`{reserve_coins}`",
            f"- 附带异常截图数量：`{len(self.screenshots)}` 张",
        ]
        if receipt_lines:
            lines.extend(["", "## 3. 本次执行回执摘要", *receipt_lines])
        if guard_lines or exc_lines:
            lines.extend(["", "## 4. 自动检测到的护栏拦截 / 异常", *guard_lines, *exc_lines])
        else:
            lines.extend(["", "## 4. 自动检测到的护栏拦截 / 异常", "- 运行过程未触发程序异常或护栏拦截；如出现识图误判，请补充截图与描述。"])
        return "\n".join(lines) + "\n"

    def _allocate_timestamp_stem(self, output_dir: Path) -> str:
        base = datetime.now().strftime("%Y%m%d_%H%M%S")
        candidate = base
        seq = 1
        while (output_dir / f"prison_run_{candidate}.log").exists() or (output_dir / f"prison_issue_{candidate}.zip").exists():
            candidate = f"{base}_{seq:02d}"
            seq += 1
        return candidate

    def export(
        self,
        output_dir: Path,
        *,
        snapshot: Any = None,
        prison_report: Any = None,
        execution_plan: Any = None,
        run_receipt: Any = None,
        semi_auto_guides: Sequence[Any] = (),
        max_keep: int = DEFAULT_MAX_DIAG_FILES,
    ) -> dict[str, Path | None]:
        """写入专项 `.log` 与脱敏 `prison_issue_*.zip` 排错包并自动轮转清理旧文件。"""
        if self.export_mode == "off":
            return {"log_path": None, "bundle_path": None, "latest_log_path": None}

        output_dir.mkdir(parents=True, exist_ok=True)
        stem = self._allocate_timestamp_stem(output_dir)
        log_path = output_dir / f"prison_run_{stem}.log"
        latest_log_path = output_dir / "latest_prison_run.log"
        log_text = self.render_text_log()
        log_path.write_text(log_text, encoding="utf-8")
        latest_log_path.write_text(log_text, encoding="utf-8")

        bundle_path: Path | None = None
        if self.export_mode in ("bundle", "bundle_screenshots"):
            bundle_path = output_dir / f"prison_issue_{stem}.zip"
            snapshot_trimmed = None
            if snapshot is not None:
                snapshot_trimmed = {
                    "uid": getattr(snapshot, "uid", "unknown"),
                    "wallet": _dump_model_or_obj(getattr(snapshot, "wallet", None)),
                    "prison": _dump_model_or_obj(getattr(snapshot, "prison", None)),
                }

            sanitized_payload = sanitize_json_payload(
                {
                    "meta": {
                        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "elapsed_ms": self._elapsed_ms(),
                        "uid": self.raw_uid,
                        "platform": f"{platform.system()} {platform.release()}",
                        "python": sys.version.split()[0],
                        "diag_export_mode": self.export_mode,
                        "screenshot_count": len(self.screenshots),
                    },
                    "options": self.options_summary,
                    "account_snapshot": snapshot_trimmed,
                    "prison_report": _dump_model_or_obj(prison_report),
                    "execution_plan": _dump_model_or_obj(execution_plan),
                    "run_receipt": _dump_model_or_obj(run_receipt),
                    "semi_auto_guides": [_dump_model_or_obj(g) for g in semi_auto_guides],
                    "events": self.events,
                    "exceptions": self.exceptions,
                },
                root_path=self.root_path,
                raw_uid=self.raw_uid,
            )
            issue_md = self.render_issue_template(
                prison_report=prison_report,
                run_receipt=run_receipt,
                bundle_filename=bundle_path.name,
            )
            with zipfile.ZipFile(bundle_path, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
                zf.writestr("prison_run.log", log_text.encode("utf-8"))
                zf.writestr("issue_template.md", issue_md.encode("utf-8"))
                zf.writestr(
                    "report_sanitized.json",
                    json.dumps(sanitized_payload, ensure_ascii=False, indent=2).encode("utf-8"),
                )
                for shot_name, shot_bytes in self.screenshots:
                    zf.writestr(f"screenshots/{shot_name}", shot_bytes)

        prune_old_diagnostic_files(output_dir, max_keep=max_keep)
        return {
            "log_path": log_path,
            "bundle_path": bundle_path,
            "latest_log_path": latest_log_path,
        }
