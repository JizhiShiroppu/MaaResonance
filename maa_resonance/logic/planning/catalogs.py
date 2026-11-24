from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

from maa_resonance.logic.paths import RESOURCES_PATH, read_json

PLANNING_RESOURCES_PATH = RESOURCES_PATH / "planning"


def _resolve_planning_dir(resources_dir: Optional[Path] = None) -> Path:
    if resources_dir is None:
        return PLANNING_RESOURCES_PATH
    base = Path(resources_dir)
    if (
        (base / "prison_strategy.json").exists()
        or (base / "growth_stages.json").exists()
        or (base / "island_strategy.json").exists()
    ):
        return base
    return base / "planning"


@lru_cache(maxsize=4)
def load_prison_strategy_catalog(resources_dir: Optional[Path] = None) -> dict[str, Any]:
    """加载整顿中心策略与静态数值目录。"""
    planning_dir = _resolve_planning_dir(resources_dir)
    data = read_json(planning_dir / "prison_strategy.json", {})
    return data if isinstance(data, dict) else {}


@lru_cache(maxsize=4)
def load_island_strategy_catalog(resources_dir: Optional[Path] = None) -> dict[str, Any]:
    """加载海岛（蜃息岛）策略与静态数值目录。"""
    planning_dir = _resolve_planning_dir(resources_dir)
    data = read_json(planning_dir / "island_strategy.json", {})
    return data if isinstance(data, dict) else {}


@lru_cache(maxsize=4)
def load_growth_stages_catalog(resources_dir: Optional[Path] = None) -> dict[str, Any]:
    """加载乘员养成与抓囚犯关卡目录。"""
    planning_dir = _resolve_planning_dir(resources_dir)
    data = read_json(planning_dir / "growth_stages.json", {})
    return data if isinstance(data, dict) else {}


@lru_cache(maxsize=4)
def load_prison_wiki_catalog(resources_dir: Optional[Path] = None) -> dict[str, Any]:
    """加载可选的 BWIKI 导出扩充目录（缺失时返回空字典）。"""
    planning_dir = _resolve_planning_dir(resources_dir)
    data = read_json(planning_dir / "prison_wiki_catalog.json", {})
    return data if isinstance(data, dict) else {}


def clear_catalog_caches() -> None:
    """清空静态规划目录缓存（主要用于单元测试隔离）。"""
    load_prison_strategy_catalog.cache_clear()
    load_island_strategy_catalog.cache_clear()
    load_growth_stages_catalog.cache_clear()
    load_prison_wiki_catalog.cache_clear()


def normalize_building_id(name_or_id: str, catalog: Optional[dict[str, Any]] = None) -> str:
    """将建筑中文名、别名或内部 ID 统一规范为 building_id。"""
    raw = str(name_or_id or "").strip()
    if not raw:
        return ""
    strategy = catalog if isinstance(catalog, dict) else load_prison_strategy_catalog()
    buildings = strategy.get("building_catalog")
    if not isinstance(buildings, dict):
        return raw
    if raw in buildings:
        return raw
    for building_id, entry in buildings.items():
        if not isinstance(entry, dict):
            continue
        if raw == str(entry.get("name") or "").strip():
            return str(building_id)
        for alias in entry.get("aliases") or []:
            if raw == str(alias or "").strip():
                return str(building_id)
    return raw


def normalize_purchase_item_name(item_name: str, catalog: Optional[dict[str, Any]] = None) -> str:
    """将原料采购站条目中的简写别名规范为标准名称。"""
    raw = str(item_name or "").strip()
    if not raw:
        return ""
    strategy = catalog if isinstance(catalog, dict) else load_prison_strategy_catalog()
    rules = strategy.get("purchase_station_rules")
    if isinstance(rules, dict):
        aliases = rules.get("item_aliases")
        if isinstance(aliases, dict) and raw in aliases:
            return str(aliases[raw]).strip() or raw
    return raw
