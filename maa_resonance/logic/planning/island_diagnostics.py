"""海岛（蜃息岛）运行时配置解析与专项诊断日志 / Issue 压缩包导出（复用公共脱敏与 PNG 工具）。"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import json
from pathlib import Path
import platform
import sys
import time
from typing import Any, Mapping

from maa_resonance.logic.planning.prison_diagnostics import (
    DEFAULT_MAX_DIAG_FILES,
    MAX_DIAG_SCREENSHOTS,
    VALID_DIAG_EXPORT_MODES,
    _DIAG_FILENAME_SANITIZE_RE,
    _dump_model_or_obj,
    _safe_bool,
    _safe_int,
    encode_png_bytes,
    mask_uid,
    prune_old_diagnostic_files,
    sanitize_json_payload,
    sanitize_text_for_export,
)

ZERO_SPEND_ISLAND_MODULES: tuple[str, ...] = (
    "claim_revenue",
    "collect_trash",
    "clear_own_monsters",
    "claim_todo",
    "friend_clean_trash",
    "friend_like",
    "friend_help_monsters",
)

ALL_ISLAND_AUTO_MODULES: tuple[str, ...] = (
    *ZERO_SPEND_ISLAND_MODULES,
    "auto_invest",
    "auto_expand",
)

ISLAND_MODULE_LABELS: dict[str, str] = {
    "claim_revenue": "收取管理中心营运收益",
    "collect_trash": "一键收取自家海岛垃圾块（严禁一键处理）",
    "clear_own_monsters": "0体力清理自家红感叹号入侵野怪",
    "claim_todo": "领取事项一览已完成奖励（禁点追踪）",
    "friend_clean_trash": "好友海岛清扫偷垃圾（每日3次）",
    "friend_like": "好友海岛顺手点赞",
    "friend_help_monsters": "好友海岛治安0体力蹭怪助战（每日5次）",
    "auto_invest": "海角城运营自动投资（仅动用超出留存底线的铁盟币，默认关）",
    "auto_expand": "海岛自动扩建下一片区域（校验等级/底线/资材券，默认关）",
}

ISLAND_SCOPE_PRESETS: dict[str, frozenset[str]] = {
    "full_safe": frozenset(ZERO_SPEND_ISLAND_MODULES),
    "daily_fast": frozenset(
        {
            "claim_revenue",
            "collect_trash",
            "claim_todo",
            "friend_clean_trash",
            "friend_like",
        }
    ),
    "own_island_only": frozenset(
        {
            "claim_revenue",
            "collect_trash",
            "clear_own_monsters",
            "claim_todo",
        }
    ),
}


@dataclass(frozen=True)
class IslandRuntimeConfig:
    """海岛任务的解析后运行时配置（支持预设范围与 9 项细粒度模块开关，消费项默认关闭）。"""

    exec_mode: str = "plan_only"
    auto_scope: str = "daily_fast"
    enabled_modules: frozenset[str] = field(default_factory=lambda: ISLAND_SCOPE_PRESETS["daily_fast"])
    reserve_coins: int = 15_000_000
    max_own_monster_fights: int = 5
    max_friend_clean_count: int = 3
    max_friend_visits: int = 6
    max_friend_help_fights: int = 3
    auto_open_report: bool = True
    diag_export_mode: str = "bundle"

    def is_enabled(self, module_key: str) -> bool:
        return str(module_key) in self.enabled_modules

    def to_summary_dict(self) -> dict[str, Any]:
        return {
            "exec_mode": self.exec_mode,
            "auto_scope": self.auto_scope,
            "enabled_modules": sorted(self.enabled_modules),
            "reserve_coins": int(self.reserve_coins),
            "max_own_monster_fights": int(self.max_own_monster_fights),
            "max_friend_clean_count": int(self.max_friend_clean_count),
            "max_friend_visits": int(self.max_friend_visits),
            "max_friend_help_fights": int(self.max_friend_help_fights),
            "auto_open_report": bool(self.auto_open_report),
            "diag_export_mode": self.diag_export_mode,
        }


def resolve_island_runtime_config(params: Mapping[str, Any] | None) -> IslandRuntimeConfig:
    """从 pipeline attach 与 action param 合并字典中安全解析海岛完整配置。"""
    raw = params if isinstance(params, Mapping) else {}

    raw_mode = str(raw.get("exec_mode") or "plan_only").strip()
    exec_mode = "execute_safe_auto" if raw_mode == "execute_safe_auto" else "plan_only"

    raw_scope = str(raw.get("auto_scope") or "daily_fast").strip()
    auto_scope = raw_scope if raw_scope in (*ISLAND_SCOPE_PRESETS.keys(), "custom") else "daily_fast"

    if auto_scope in ISLAND_SCOPE_PRESETS:
        enabled_modules = ISLAND_SCOPE_PRESETS[auto_scope]
    else:
        picked = frozenset(
            key
            for key in ALL_ISLAND_AUTO_MODULES
            if _safe_bool(raw.get(f"mod_pick_{key}"), False)
        )
        ui_configured = _safe_bool(raw.get("modules_ui_configured"), False)
        if ui_configured or picked:
            enabled_modules = picked
        elif isinstance(raw.get("enabled_modules"), (list, tuple, set, frozenset)):
            enabled_modules = frozenset(
                str(item).strip()
                for item in raw["enabled_modules"]
                if str(item).strip() in ALL_ISLAND_AUTO_MODULES
            )
        else:
            enabled_modules = ISLAND_SCOPE_PRESETS["daily_fast"]

    base_reserve = _safe_int(raw.get("reserve_coins"), 15_000_000, minimum=0)
    if _safe_bool(raw.get("use_custom_reserve_coins"), False):
        reserve_coins = _safe_int(raw.get("custom_reserve_coins"), base_reserve, minimum=0)
    else:
        reserve_coins = base_reserve

    max_own_monster_fights = min(20, max(0, _safe_int(raw.get("max_own_monster_fights"), 5, minimum=0)))
    max_friend_clean_count = min(5, max(0, _safe_int(raw.get("max_friend_clean_count"), 3, minimum=0)))
    max_friend_visits = min(20, max(max_friend_clean_count, _safe_int(raw.get("max_friend_visits"), 6, minimum=1)))
    max_friend_help_fights = min(5, max(0, _safe_int(raw.get("max_friend_help_fights"), 3, minimum=0)))
    auto_open_report = _safe_bool(raw.get("auto_open_report"), True)

    raw_diag = str(raw.get("diag_export_mode") or "bundle").strip().lower()
    diag_export_mode = raw_diag if raw_diag in VALID_DIAG_EXPORT_MODES else "bundle"

    return IslandRuntimeConfig(
        exec_mode=exec_mode,
        auto_scope=auto_scope,
        enabled_modules=enabled_modules,
        reserve_coins=reserve_coins,
        max_own_monster_fights=max_own_monster_fights,
        max_friend_clean_count=max_friend_clean_count,
        max_friend_visits=max_friend_visits,
        max_friend_help_fights=max_friend_help_fights,
        auto_open_report=auto_open_report,
        diag_export_mode=diag_export_mode,
    )


class IslandDiagnosticRecorder:
    """记录单次海岛运行的阶段耗时、决策与异常现场，并打包成脱敏 Issue zip。"""

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
            "MaaResonance 海岛（蜃息岛）专项诊断日志",
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
        island_report: Any = None,
        run_receipt: Any = None,
        bundle_filename: str = "",
    ) -> str:
        masked_uid = mask_uid(self.raw_uid)
        stage_str = str(getattr(island_report, "stage", "unknown")) if island_report is not None else "unknown"
        island_lv = getattr(island_report, "island_level", "unknown") if island_report is not None else "unknown"
        exec_mode = self.options_summary.get("exec_mode", "unknown")
        auto_scope = self.options_summary.get("auto_scope", "unknown")

        receipt_lines: list[str] = []
        if run_receipt is not None:
            receipt_lines.append(
                f"- 执行汇总：收钱 `{getattr(run_receipt, 'revenue_claimed_coins', 0):,}` | "
                f"收垃圾 `{getattr(run_receipt, 'trash_blocks_collected', 0)}` | "
                f"打自家怪 `{getattr(run_receipt, 'own_monsters_cleared', 0)}` | "
                f"领任务 `{getattr(run_receipt, 'todo_rewards_claimed', 0)}` | "
                f"好友清扫 `{getattr(run_receipt, 'friend_trash_cleaned', 0)}` / 点赞 `{getattr(run_receipt, 'friend_likes_sent', 0)}` / 助战 `{getattr(run_receipt, 'friend_monsters_helped', 0)}`"
            )

        exc_lines = [
            f"- `[{item.get('stage', 'run')}]` {sanitize_text_for_export(item.get('error', ''), root_path=self.root_path, raw_uid=self.raw_uid)}"
            for item in self.exceptions
        ]
        lines = [
            "# 海岛（蜃息岛）自动问题反馈 / Issue 模版",
            "",
            "> 请将整个脱敏 `.zip` 诊断包拖入 GitHub Issue 正文附带上传（包内已自动脱敏 UID 与本机路径）。",
            "",
            f"- 诊断包文件名：`{bundle_filename or 'island_issue_<timestamp>.zip'}`",
            f"- UID（已脱敏）：`{masked_uid}` | 海岛等级：`LV{island_lv}`（阶段：`{stage_str}`）",
            f"- 执行模式：`{exec_mode}` | 执行范围：`{auto_scope}`",
            *receipt_lines,
        ]
        if exc_lines:
            lines.extend(["", "## 异常列表", *exc_lines])
        return "\n".join(lines) + "\n"

    def _allocate_timestamp_stem(self, output_dir: Path) -> str:
        base = datetime.now().strftime("%Y%m%d_%H%M%S")
        candidate = base
        seq = 1
        while (output_dir / f"island_run_{candidate}.log").exists() or (
            output_dir / f"island_issue_{candidate}.zip"
        ).exists():
            candidate = f"{base}_{seq:02d}"
            seq += 1
        return candidate

    def export(
        self,
        output_dir: Path,
        *,
        snapshot: Any = None,
        island_report: Any = None,
        run_receipt: Any = None,
        max_keep: int = DEFAULT_MAX_DIAG_FILES,
    ) -> dict[str, Path | None]:
        if self.export_mode == "off":
            return {"log_path": None, "bundle_path": None, "latest_log_path": None}

        output_dir.mkdir(parents=True, exist_ok=True)
        stem = self._allocate_timestamp_stem(output_dir)
        log_path = output_dir / f"island_run_{stem}.log"
        latest_log_path = output_dir / "latest_island_run.log"
        log_text = self.render_text_log()
        log_path.write_text(log_text, encoding="utf-8")
        latest_log_path.write_text(log_text, encoding="utf-8")

        bundle_path: Path | None = None
        if self.export_mode in ("bundle", "bundle_screenshots"):
            bundle_path = output_dir / f"island_issue_{stem}.zip"
            snapshot_trimmed = None
            if snapshot is not None:
                snapshot_trimmed = {
                    "uid": getattr(snapshot, "uid", "unknown"),
                    "wallet": _dump_model_or_obj(getattr(snapshot, "wallet", None)),
                    "island": _dump_model_or_obj(getattr(snapshot, "island", None)),
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
                    "island_report": _dump_model_or_obj(island_report),
                    "run_receipt": _dump_model_or_obj(run_receipt),
                    "events": self.events,
                    "exceptions": self.exceptions,
                },
                root_path=self.root_path,
                raw_uid=self.raw_uid,
            )
            issue_md = self.render_issue_template(
                island_report=island_report,
                run_receipt=run_receipt,
                bundle_filename=bundle_path.name,
            )
            with zipfile_open(bundle_path) as zf:
                zf.writestr("island_run.log", log_text.encode("utf-8"))
                zf.writestr("issue_template.md", issue_md.encode("utf-8"))
                zf.writestr(
                    "report_sanitized.json",
                    json.dumps(sanitized_payload, ensure_ascii=False, indent=2).encode("utf-8"),
                )
                for shot_name, shot_bytes in self.screenshots:
                    zf.writestr(f"screenshots/{shot_name}", shot_bytes)

        prune_old_diagnostic_files(
            output_dir,
            max_keep=max_keep,
            patterns=("island_run_*.log", "island_issue_*.zip"),
        )
        return {
            "log_path": log_path,
            "bundle_path": bundle_path,
            "latest_log_path": latest_log_path,
        }


def zipfile_open(path: Path):
    import zipfile

    return zipfile.ZipFile(path, mode="w", compression=zipfile.ZIP_DEFLATED)
