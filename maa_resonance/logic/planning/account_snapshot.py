from __future__ import annotations

import json
import os
from pathlib import Path
import time
from typing import Any, Dict, List, Literal, Mapping, Optional

from pydantic import BaseModel, Field

from maa_resonance.logic.paths import read_json
from maa_resonance.logic.planning.catalogs import normalize_building_id


class WalletSnapshot(BaseModel):
    """账号基础货币与澄明度快照。"""

    coins: int = 0
    huashi: int = 0
    clarity_estimate: Optional[int] = None
    updated_at: Optional[str] = None


class MaterialRequirement(BaseModel):
    """单种养成材料的目标需求条目。"""

    name: str
    required: int = 0


class CrewGoal(BaseModel):
    """乘员个人养成目标（含升级/共振/觉醒及对应材料总需求）。"""

    target_level: Optional[int] = None
    target_resonance: Optional[int] = None
    target_awakening: Optional[int] = None
    required_coins: int = 0
    required_materials: Dict[str, int] = Field(default_factory=dict)
    priority: int = 1
    notes: str = ""


class CrewProgressionEntry(BaseModel):
    """单名乘员当前练度与养成目标。"""

    level: Optional[int] = None
    resonance: Optional[int] = None
    awakening: Optional[int] = None
    skills: Dict[str, int] = Field(default_factory=dict)
    target_goal: Optional[CrewGoal] = None
    updated_at: Optional[str] = None


class MaterialInventoryEntry(BaseModel):
    """材料仓库单品库存缓存。"""

    owned: int = 0
    updated_at: Optional[str] = None


class PrisonOrder(BaseModel):
    """黑月服装订单站当前订单条目。"""

    item_name: str
    quantity: int = 60
    order_type: Literal["daily", "weekly"] = "daily"
    stock_owned: int = 0


class PurchaseOffer(BaseModel):
    """原料采购站单条可转换报价。"""

    from_item: str
    to_item: str
    from_qty: int = 1
    to_qty: int = 1


class PrisonSnapshot(BaseModel):
    """整顿中心（监狱）当前经营与建设状态快照。"""

    level: int = 0
    exp: int = 0
    exp_next: int = 0
    work_tickets: int = 0
    power_used: int = 0
    power_max: int = 0
    prisoners_current: int = 0
    prisoners_capacity: int = 0
    raw_warehouse_used: int = 0
    raw_warehouse_cap: int = 0
    finished_warehouse_used: int = 0
    finished_warehouse_cap: int = 0
    deposit_current: int = 0
    deposit_cap: int = 0
    deposit_auto_refill: Optional[bool] = None
    motors_installed: int = 0
    warehouse_coin_expansions_used: int = 0
    warehouse_huashi_expansions_used: int = 0
    dorm_count: int = 1
    production_workshop_count: int = 1
    transfer_anchors: List[str] = Field(default_factory=list)
    buildings: Dict[str, int] = Field(default_factory=dict)
    sewing_machines_maxed: bool = False
    graduated: bool = False
    active_orders: List[PrisonOrder] = Field(default_factory=list)
    purchase_offers: List[PurchaseOffer] = Field(default_factory=list)
    inventory_by_item: Dict[str, int] = Field(default_factory=dict)
    workshop_last_collect_at: Dict[str, str] = Field(default_factory=dict)
    updated_at: Optional[str] = None


class AccountSnapshot(BaseModel):
    """跨跑商、整顿中心与乘员养成的统一只读账号快照。"""

    uid: str = "unknown"
    updated_at: Optional[str] = None
    available_cities: List[str] = Field(default_factory=list)
    trade_role_resonance: Dict[str, int] = Field(default_factory=dict)
    wallet: WalletSnapshot = Field(default_factory=WalletSnapshot)
    crew_progression: Dict[str, CrewProgressionEntry] = Field(default_factory=dict)
    materials_inventory: Dict[str, MaterialInventoryEntry] = Field(default_factory=dict)
    prison: PrisonSnapshot = Field(default_factory=PrisonSnapshot)

    def effective_role_resonance(self, role_name: str) -> Optional[int]:
        """优先读取 crew_progression 中记录的共振等级，缺失时回退到 trade.role_resonance。"""
        entry = self.crew_progression.get(role_name)
        if entry is not None and entry.resonance is not None:
            return entry.resonance
        return self.trade_role_resonance.get(role_name)


def _normalize_building_levels(raw_buildings: Any) -> dict[str, int]:
    if not isinstance(raw_buildings, Mapping):
        return {}
    normalized: dict[str, int] = {}
    for raw_key, raw_level in raw_buildings.items():
        key = normalize_building_id(str(raw_key or ""))
        if not key:
            continue
        try:
            level = max(0, int(raw_level or 0))
        except (TypeError, ValueError):
            continue
        prev = normalized.get(key)
        normalized[key] = max(prev, level) if prev is not None else level
    return normalized


def _normalize_int_map(raw_map: Any) -> dict[str, int]:
    if not isinstance(raw_map, Mapping):
        return {}
    result: dict[str, int] = {}
    for key, val in raw_map.items():
        name = str(key or "").strip()
        if not name:
            continue
        try:
            result[name] = int(val)
        except (TypeError, ValueError):
            continue
    return result


def snapshot_from_account_payload(payload: Mapping[str, Any]) -> AccountSnapshot:
    """将 config/accounts/<uid>.json 解析为强类型 AccountSnapshot，兼容仅有 trade/planner 的旧版配置。"""
    if not isinstance(payload, Mapping):
        return AccountSnapshot()

    trade = payload.get("trade") if isinstance(payload.get("trade"), Mapping) else {}
    raw_cities = trade.get("available_cities")
    if not isinstance(raw_cities, list):
        raw_cities = payload.get("available_cities")
    available_cities = [str(city).strip() for city in (raw_cities or []) if str(city).strip()]

    trade_role_resonance = _normalize_int_map(
        trade.get("role_resonance") or payload.get("trade_role_resonance") or {}
    )

    wallet = WalletSnapshot.model_validate(payload.get("wallet") or {})

    raw_crew = payload.get("crew_progression") if isinstance(payload.get("crew_progression"), Mapping) else {}
    crew_progression: dict[str, CrewProgressionEntry] = {}
    for role_name, entry in raw_crew.items():
        key = str(role_name or "").strip()
        if not key:
            continue
        crew_progression[key] = CrewProgressionEntry.model_validate(entry if isinstance(entry, Mapping) else {})

    raw_materials = (
        payload.get("materials_inventory")
        if isinstance(payload.get("materials_inventory"), Mapping)
        else {}
    )
    materials_inventory: dict[str, MaterialInventoryEntry] = {}
    for mat_name, entry in raw_materials.items():
        key = str(mat_name or "").strip()
        if not key:
            continue
        if isinstance(entry, Mapping):
            materials_inventory[key] = MaterialInventoryEntry.model_validate(entry)
        else:
            try:
                materials_inventory[key] = MaterialInventoryEntry(owned=max(0, int(entry or 0)))
            except (TypeError, ValueError):
                continue

    raw_prison = dict(payload.get("prison") or {}) if isinstance(payload.get("prison"), Mapping) else {}
    if "buildings" in raw_prison:
        raw_prison["buildings"] = _normalize_building_levels(raw_prison.get("buildings"))
    prison = PrisonSnapshot.model_validate(raw_prison)

    uid = str(payload.get("uid") or "unknown").strip() or "unknown"
    updated_at = str(payload.get("updated_at")).strip() if payload.get("updated_at") is not None else None

    return AccountSnapshot(
        uid=uid,
        updated_at=updated_at,
        available_cities=available_cities,
        trade_role_resonance=trade_role_resonance,
        wallet=wallet,
        crew_progression=crew_progression,
        materials_inventory=materials_inventory,
        prison=prison,
    )


def load_account_snapshot(path: str | Path) -> AccountSnapshot:
    """从磁盘加载账号配置并解析为 AccountSnapshot；文件缺失或异常时返回安全空快照。"""
    payload = read_json(path, {})
    return snapshot_from_account_payload(payload if isinstance(payload, dict) else {})


def _now_timestamp() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _atomic_write_json(target: Path, payload: Mapping[str, Any]) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    text = json.dumps(payload, ensure_ascii=False, indent=2, default=str)
    try:
        tmp_path.write_text(text, encoding="utf-8")
        os.replace(tmp_path, target)
    finally:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)


def save_account_snapshot_sections(
    path: str | Path,
    *,
    uid: Optional[str] = None,
    wallet: Optional[WalletSnapshot | Mapping[str, Any]] = None,
    crew_progression: Optional[Mapping[str, CrewProgressionEntry | Mapping[str, Any]]] = None,
    materials_inventory: Optional[Mapping[str, MaterialInventoryEntry | Mapping[str, Any] | int]] = None,
    prison: Optional[PrisonSnapshot | Mapping[str, Any]] = None,
    merge_crew: bool = True,
    merge_materials: bool = True,
) -> Path:
    """非破坏式写入账号扩展段（wallet / crew_progression / materials_inventory / prison），完整保留原有 trade/planner 等键。"""
    target = Path(path)
    existing = read_json(target, {})
    payload: dict[str, Any] = dict(existing) if isinstance(existing, dict) else {}
    if "version" not in payload:
        payload["version"] = 1

    now_ts = _now_timestamp()
    if uid is not None and str(uid).strip():
        payload["uid"] = str(uid).strip()
    elif not str(payload.get("uid") or "").strip():
        payload["uid"] = "unknown"
    payload["updated_at"] = now_ts

    if wallet is not None:
        wallet_model = wallet if isinstance(wallet, WalletSnapshot) else WalletSnapshot.model_validate(dict(wallet))
        if not wallet_model.updated_at:
            wallet_model = wallet_model.model_copy(update={"updated_at": now_ts})
        payload["wallet"] = wallet_model.model_dump(mode="json")

    if crew_progression is not None:
        base_crew: dict[str, Any] = (
            dict(payload.get("crew_progression") or {})
            if merge_crew and isinstance(payload.get("crew_progression"), Mapping)
            else {}
        )
        for role_name, entry in crew_progression.items():
            key = str(role_name or "").strip()
            if not key:
                continue
            entry_model = (
                entry
                if isinstance(entry, CrewProgressionEntry)
                else CrewProgressionEntry.model_validate(dict(entry))
            )
            if not entry_model.updated_at:
                entry_model = entry_model.model_copy(update={"updated_at": now_ts})
            base_crew[key] = entry_model.model_dump(mode="json")
        payload["crew_progression"] = base_crew

    if materials_inventory is not None:
        base_mats: dict[str, Any] = (
            dict(payload.get("materials_inventory") or {})
            if merge_materials and isinstance(payload.get("materials_inventory"), Mapping)
            else {}
        )
        for mat_name, entry in materials_inventory.items():
            key = str(mat_name or "").strip()
            if not key:
                continue
            if isinstance(entry, MaterialInventoryEntry):
                mat_model = entry
            elif isinstance(entry, Mapping):
                mat_model = MaterialInventoryEntry.model_validate(dict(entry))
            else:
                mat_model = MaterialInventoryEntry(owned=max(0, int(entry)))
            if not mat_model.updated_at:
                mat_model = mat_model.model_copy(update={"updated_at": now_ts})
            base_mats[key] = mat_model.model_dump(mode="json")
        payload["materials_inventory"] = base_mats

    if prison is not None:
        raw_prison = dict(prison) if isinstance(prison, Mapping) else prison.model_dump(mode="python")
        if "buildings" in raw_prison:
            raw_prison["buildings"] = _normalize_building_levels(raw_prison.get("buildings"))
        prison_model = PrisonSnapshot.model_validate(raw_prison)
        if not prison_model.updated_at:
            prison_model = prison_model.model_copy(update={"updated_at": now_ts})
        payload["prison"] = prison_model.model_dump(mode="json")

    _atomic_write_json(target, payload)
    return target
