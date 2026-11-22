from __future__ import annotations

import json
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
BUSINESS_PIPELINE_DIR = REPO_ROOT / "assets" / "resource" / "base" / "pipeline" / "business"
PC_MANUAL_PIPELINE_PATH = REPO_ROOT / "assets" / "resource" / "pc" / "pipeline" / "pc_manual_business.json"
PC_GUARDED_CLICKS_PATH = REPO_ROOT / "assets" / "resource" / "pc" / "pipeline" / "pc_business_guarded_clicks.json"
PC_GUARDED_SWIPES_PATH = REPO_ROOT / "assets" / "resource" / "pc" / "pipeline" / "pc_business_guarded_swipes.json"


def _normalize_offset(raw: Any) -> list[int] | None:
    if isinstance(raw, (list, tuple)) and len(raw) >= 2:
        return [int(round(float(raw[0]))), int(round(float(raw[1])))]
    return None


def _action_type_and_param(node_data: dict[str, Any]) -> tuple[str | None, dict[str, Any]]:
    action = node_data.get("action")
    if isinstance(action, str):
        return action, node_data
    if isinstance(action, dict):
        act_type = action.get("type")
        param = action.get("param")
        return (act_type if isinstance(act_type, str) else None), (param if isinstance(param, dict) else {})
    return None, {}


def _build_guarded_override(node_data: dict[str, Any]) -> dict[str, Any]:
    _act_type, action_param = _action_type_and_param(node_data)

    target = action_param.get("target", node_data.get("target"))
    target_offset = _normalize_offset(action_param.get("target_offset", node_data.get("target_offset")))

    custom_param: dict[str, Any] = {}
    if target is not None:
        custom_param["target"] = target
    if target_offset is not None:
        custom_param["target_offset"] = target_offset

    param_block: dict[str, Any] = {"custom_action": "guarded_click"}
    if custom_param:
        param_block["custom_action_param"] = custom_param

    return {
        "action": {
            "type": "Custom",
            "param": param_block,
        }
    }


def _build_guarded_swipe_override(node_data: dict[str, Any]) -> dict[str, Any]:
    _act_type, action_param = _action_type_and_param(node_data)

    custom_param: dict[str, Any] = {}
    for key in ("begin", "end"):
        val = action_param.get(key, node_data.get(key))
        if val is not None:
            custom_param[key] = val
    for offset_key in ("begin_offset", "end_offset"):
        norm = _normalize_offset(action_param.get(offset_key, node_data.get(offset_key)))
        if norm is not None:
            custom_param[offset_key] = norm
    for int_key in ("duration", "end_hold"):
        val = action_param.get(int_key, node_data.get(int_key))
        if val is not None and not isinstance(val, bool):
            custom_param[int_key] = int(val)

    param_block: dict[str, Any] = {"custom_action": "guarded_swipe"}
    if custom_param:
        param_block["custom_action_param"] = custom_param

    return {
        "action": {
            "type": "Custom",
            "param": param_block,
        }
    }


def _collect_business_action_overrides(
    target_action: str,
    builder: Any,
) -> dict[str, dict[str, Any]]:
    excluded = set(json.loads(PC_MANUAL_PIPELINE_PATH.read_text(encoding="utf-8")).keys())
    overrides: dict[str, dict[str, Any]] = {}

    for json_path in sorted(BUSINESS_PIPELINE_DIR.rglob("*.json")):
        pipeline_data = json.loads(json_path.read_text(encoding="utf-8"))
        for node_name, node_data in pipeline_data.items():
            if node_name in excluded or not isinstance(node_data, dict):
                continue
            act_type, _ = _action_type_and_param(node_data)
            if act_type == target_action:
                overrides[node_name] = builder(node_data)

    return overrides


def generate_pc_business_guarded_clicks() -> dict[str, dict[str, Any]]:
    return _collect_business_action_overrides("Click", _build_guarded_override)


def generate_pc_business_guarded_swipes() -> dict[str, dict[str, Any]]:
    return _collect_business_action_overrides("Swipe", _build_guarded_swipe_override)


def main() -> None:
    click_overrides = generate_pc_business_guarded_clicks()
    PC_GUARDED_CLICKS_PATH.parent.mkdir(parents=True, exist_ok=True)
    PC_GUARDED_CLICKS_PATH.write_text(
        json.dumps(click_overrides, ensure_ascii=False, indent=4) + "\n",
        encoding="utf-8",
    )
    print(f"Generated {len(click_overrides)} guarded_click overrides -> {PC_GUARDED_CLICKS_PATH}")

    swipe_overrides = generate_pc_business_guarded_swipes()
    PC_GUARDED_SWIPES_PATH.parent.mkdir(parents=True, exist_ok=True)
    PC_GUARDED_SWIPES_PATH.write_text(
        json.dumps(swipe_overrides, ensure_ascii=False, indent=4) + "\n",
        encoding="utf-8",
    )
    print(f"Generated {len(swipe_overrides)} guarded_swipe overrides -> {PC_GUARDED_SWIPES_PATH}")


if __name__ == "__main__":
    main()
