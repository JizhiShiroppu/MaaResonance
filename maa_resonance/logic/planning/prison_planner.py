from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional, Sequence, Tuple

from pydantic import BaseModel, Field

from maa_resonance.logic.planning.account_snapshot import (
    AccountSnapshot,
    PrisonOrder,
    PrisonSnapshot,
    PurchaseOffer,
)
from maa_resonance.logic.planning.catalogs import (
    load_growth_stages_catalog,
    load_prison_strategy_catalog,
    normalize_purchase_item_name,
)

RAW_WORKSHOP_IDS: tuple[str, ...] = (
    "raw_sewing",
    "raw_synthetic",
    "raw_plant",
    "raw_animal",
)
LOW_PRIORITY_INCIDENT_ROOM_IDS: tuple[str, ...] = (
    "confinement_room",
    "infirmary",
    "canteen",
    "yard",
    "visiting_room",
    "security_center",
)


class PrisonPlanOptions(BaseModel):
    """整顿中心规划器参数配置（默认开启所有安全护栏）。"""

    reserve_coins: int = 15_000_000
    allow_huashi_motors: bool = False
    allow_huashi_warehouse: bool = False
    player_level: int = 71
    ignore_incident_rooms: bool = True
    prefer_free_order_refresh: bool = True
    force_phase: Literal["auto", "rush_leveling", "profit_harvest"] = "auto"


class BuildingRecommendation(BaseModel):
    """建筑建设、升级或暂缓建议。"""

    building_id: str
    name: str
    priority: Literal["blocker", "high", "medium", "defer", "ignore", "warning"]
    action: str
    reason: str
    estimated_coin_cost: Optional[int] = None


class GuardedHuashiAction(BaseModel):
    """受桦石开关保护的操作条目与总成本披露。"""

    action_id: str
    title: str
    status: Literal["blocked_by_guardrail", "opt_in_enabled", "completed"]
    next_huashi_cost: int = 0
    next_coin_cost: int = 0
    remaining_total_huashi: int = 0
    remaining_total_coins: int = 0
    notes: str = ""


class OrderDecision(BaseModel):
    """黑月服装订单站单条订单评估结论。"""

    item_name: str
    order_type: Literal["daily", "weekly"]
    quantity: int
    stock_owned: int = 0
    in_whitelist: bool = False
    rating: Optional[int] = None
    action: Literal["deliver", "produce_then_deliver", "delete_free", "skip_weekly", "skip_profit_phase"]
    overflow_warning: bool = False
    defer_until_surplus: bool = False
    reason: str = ""


class PurchaseDecision(BaseModel):
    """原料采购站单条兑换评估结论。"""

    from_item: str
    to_item: str
    normalized_from_item: str
    normalized_to_item: str
    action: Literal["accept", "block"]
    reason: str = ""


class ShopItemDecision(BaseModel):
    """整顿中心兑换商店道具评估结论。"""

    item_name: str
    currency: str
    action: Literal["buy_one_time", "skip_renewable", "block_huashi", "review_manual"]
    reason: str = ""


class PrisonPlanReport(BaseModel):
    """整顿中心（监狱）统一规划报告。"""

    uid: str
    phase: Literal["rush_leveling", "profit_harvest"]
    prison_level: int
    coins_total: int
    reserve_coins: int
    spendable_coins: int
    huashi_total: int
    work_tickets: int
    power_used: int
    power_max: int
    power_free: int
    dorm_count: int
    production_workshop_count: int
    recommended_dorm_and_workshop_cap: int
    next_ladder_unlock_level: Optional[int] = None
    recommended_raw_predeposit: int
    prerequisite_warnings: List[str] = Field(default_factory=list)
    warehouse_advice: List[str] = Field(default_factory=list)
    building_recommendations: List[BuildingRecommendation] = Field(default_factory=list)
    guarded_huashi_actions: List[GuardedHuashiAction] = Field(default_factory=list)
    order_decisions: List[OrderDecision] = Field(default_factory=list)
    purchase_decisions: List[PurchaseDecision] = Field(default_factory=list)
    shop_decisions: List[ShopItemDecision] = Field(default_factory=list)
    production_advice: List[str] = Field(default_factory=list)
    prisoner_farming_recommendations: List[str] = Field(default_factory=list)


def detect_prison_phase(
    prison: PrisonSnapshot,
    options: PrisonPlanOptions,
    catalog: Optional[dict[str, Any]] = None,
) -> Literal["rush_leveling", "profit_harvest"]:
    """判断整顿中心当前所处阶段：冲级阶段 vs 毕业赚钱阶段。"""
    if options.force_phase != "auto":
        return options.force_phase
    strategy = catalog if isinstance(catalog, dict) else load_prison_strategy_catalog()
    thresholds = strategy.get("thresholds") if isinstance(strategy.get("thresholds"), dict) else {}
    graduation_level = int(thresholds.get("graduation_prison_level") or 60)
    if prison.graduated:
        return "profit_harvest"
    raw_all_maxed = all(int(prison.buildings.get(workshop_id, 0)) >= 10 for workshop_id in RAW_WORKSHOP_IDS)
    if prison.level >= graduation_level and prison.sewing_machines_maxed and raw_all_maxed:
        return "profit_harvest"
    return "rush_leveling"


def recommended_dorm_and_workshop_count(
    prison_level: int,
    catalog: Optional[dict[str, Any]] = None,
) -> Tuple[int, Optional[int]]:
    """按 1/6/16/26/36/46 阶梯返回当前允许开启的宿舍与车间数量及下一解锁等级。"""
    strategy = catalog if isinstance(catalog, dict) else load_prison_strategy_catalog()
    ladder_cfg = strategy.get("dorm_and_workshop_ladder") if isinstance(strategy.get("dorm_and_workshop_ladder"), dict) else {}
    raw_levels = ladder_cfg.get("unlock_prison_levels") or [1, 6, 16, 26, 36, 46]
    levels = sorted(int(lv) for lv in raw_levels)
    effective_level = max(1, int(prison_level))
    allowed = 0
    next_level: Optional[int] = None
    for lv in levels:
        if effective_level >= lv:
            allowed += 1
        elif next_level is None:
            next_level = lv
    return max(1, allowed), next_level


def remaining_power_motor_cost(
    motors_installed: int,
    catalog: Optional[dict[str, Any]] = None,
) -> Dict[str, int]:
    """计算电力中心剩余未安装电机的下一槽与累计所需桦石及铁盟币。"""
    strategy = catalog if isinstance(catalog, dict) else load_prison_strategy_catalog()
    motors = strategy.get("power_motors") if isinstance(strategy.get("power_motors"), list) else []
    installed = max(0, int(motors_installed))
    remaining = sorted(
        (entry for entry in motors if isinstance(entry, dict) and int(entry.get("slot") or 0) > installed),
        key=lambda item: int(item["slot"]),
    )
    if not remaining:
        return {
            "remaining_slots": 0,
            "next_huashi": 0,
            "next_coins": 0,
            "total_remaining_huashi": 0,
            "total_remaining_coins": 0,
        }
    return {
        "remaining_slots": len(remaining),
        "next_huashi": int(remaining[0].get("huashi") or 0),
        "next_coins": int(remaining[0].get("coins") or 0),
        "total_remaining_huashi": sum(int(item.get("huashi") or 0) for item in remaining),
        "total_remaining_coins": sum(int(item.get("coins") or 0) for item in remaining),
    }


def raw_workshop_remaining_cost(
    current_level: int,
    catalog: Optional[dict[str, Any]] = None,
) -> int:
    """计算单个原料车间从当前等级升至 LV10 所需的剩余铁盟币总费用。"""
    strategy = catalog if isinstance(catalog, dict) else load_prison_strategy_catalog()
    upgrades = strategy.get("raw_workshop_upgrades") if isinstance(strategy.get("raw_workshop_upgrades"), list) else []
    lvl = max(0, int(current_level))
    return sum(
        int(entry.get("coins") or 0)
        for entry in upgrades
        if isinstance(entry, dict) and int(entry.get("to_level") or 0) > lvl
    )


def sewing_machine_remaining_cost(
    current_level: int,
    catalog: Optional[dict[str, Any]] = None,
) -> Dict[str, int]:
    """计算单台生产车间缝纫机从当前等级升至 LV10 所需的剩余铁盟币与工票。"""
    strategy = catalog if isinstance(catalog, dict) else load_prison_strategy_catalog()
    upgrades = strategy.get("sewing_machine_upgrades") if isinstance(strategy.get("sewing_machine_upgrades"), list) else []
    lvl = max(1, int(current_level))
    remaining = [
        entry
        for entry in upgrades
        if isinstance(entry, dict) and int(entry.get("to_level") or 0) > lvl
    ]
    return {
        "remaining_levels": len(remaining),
        "coins": sum(int(item.get("coins") or 0) for item in remaining),
        "work_tickets": sum(int(item.get("work_tickets") or 0) for item in remaining),
    }


def evaluate_black_moon_order(
    order: PrisonOrder,
    prison: PrisonSnapshot,
    phase: Literal["rush_leveling", "profit_harvest"],
    catalog: Optional[dict[str, Any]] = None,
) -> OrderDecision:
    """结合当前阶段与 21 种冲级高效货物白名单评估黑月订单。"""
    strategy = catalog if isinstance(catalog, dict) else load_prison_strategy_catalog()
    thresholds = strategy.get("thresholds") if isinstance(strategy.get("thresholds"), dict) else {}
    item_name = str(order.item_name or "").strip()
    stock_owned = max(int(order.stock_owned), int(prison.inventory_by_item.get(item_name, 0)))

    if phase == "profit_harvest":
        return OrderDecision(
            item_name=item_name,
            order_type=order.order_type,
            quantity=order.quantity,
            stock_owned=stock_owned,
            in_whitelist=False,
            action="skip_profit_phase",
            reason="毕业赚钱阶段停止交付黑月订单，成品通过转运中心运往海角城/岚心城高价卖出。",
        )

    rush_list = strategy.get("rush_leveling_goods") if isinstance(strategy.get("rush_leveling_goods"), list) else []
    rush_map = {
        str(item.get("name") or "").strip(): item
        for item in rush_list
        if isinstance(item, dict) and str(item.get("name") or "").strip()
    }
    good = rush_map.get(item_name)
    if good is None:
        if order.order_type == "weekly":
            return OrderDecision(
                item_name=item_name,
                order_type=order.order_type,
                quantity=order.quantity,
                stock_owned=stock_owned,
                in_whitelist=False,
                action="skip_weekly",
                reason="不在冲级21种高效货物表内；每周订单仅多+25%奖励，单位收益仍输给表中1.0x日常单，建议不接。",
            )
        return OrderDecision(
            item_name=item_name,
            order_type=order.order_type,
            quantity=order.quantity,
            stock_owned=stock_owned,
            in_whitelist=False,
            action="delete_free",
            reason="不在冲级21种高效货物表内，建议免费删单（5分钟后自动刷新，或使用再交涉请求书）。",
        )

    rating = good.get("rating")
    defer_until_surplus = bool(good.get("defer_until_surplus", False))

    if order.order_type == "daily" and not bool(good.get("daily_recommended", True)):
        return OrderDecision(
            item_name=item_name,
            order_type=order.order_type,
            quantity=order.quantity,
            stock_owned=stock_owned,
            in_whitelist=True,
            rating=rating,
            action="delete_free",
            reason=f"《{item_name}》为攻略特例：仅周单可做，每日订单建议直接删除重刷。",
        )

    late_level = int(thresholds.get("late_overflow_prison_level") or 20)
    warn_ratio = float(thresholds.get("warehouse_overflow_warning_ratio") or 0.8)
    cap = int(prison.finished_warehouse_cap)
    near_full = cap > 0 and (float(prison.finished_warehouse_used) / float(cap)) >= warn_ratio
    if bool(good.get("early_only_overflow_risk", False)):
        if prison.level >= late_level or near_full:
            return OrderDecision(
                item_name=item_name,
                order_type=order.order_type,
                quantity=order.quantity,
                stock_owned=stock_owned,
                in_whitelist=True,
                rating=rating,
                action="skip_weekly" if order.order_type == "weekly" else "delete_free",
                overflow_warning=True,
                reason=f"《{item_name}》在后期（整顿 LV{late_level}+ 或高仓占）极易爆仓，按攻略避坑停止大量排产并跳过该单。",
            )
        action: Literal["deliver", "produce_then_deliver"] = (
            "deliver" if stock_owned >= order.quantity else "produce_then_deliver"
        )
        return OrderDecision(
            item_name=item_name,
            order_type=order.order_type,
            quantity=order.quantity,
            stock_owned=stock_owned,
            in_whitelist=True,
            rating=rating,
            action=action,
            overflow_warning=True,
            defer_until_surplus=defer_until_surplus,
            reason=f"前期冲级白名单货物，可{('直接交付' if action == 'deliver' else '按需排产后交付')}；注意控制仓占，后期易爆仓。",
        )

    action = "deliver" if stock_owned >= order.quantity else "produce_then_deliver"
    note_extra = "（前期不建议优先做，等其他主力冲级货不太缺后再排产）" if defer_until_surplus else ""
    return OrderDecision(
        item_name=item_name,
        order_type=order.order_type,
        quantity=order.quantity,
        stock_owned=stock_owned,
        in_whitelist=True,
        rating=rating,
        action=action,
        defer_until_surplus=defer_until_surplus,
        reason=f"位于冲级高效白名单内，建议{('立即交付' if action == 'deliver' else '排产补足后交付')}{note_extra}。",
    )


def evaluate_purchase_offer(
    offer: PurchaseOffer,
    prison: PrisonSnapshot,
    catalog: Optional[dict[str, Any]] = None,
) -> PurchaseDecision:
    """评估原料采购站单条转换是否安全（默认硬拦截 36 级缝纫包转蚕丝暗雷）。"""
    strategy = catalog if isinstance(catalog, dict) else load_prison_strategy_catalog()
    norm_from = normalize_purchase_item_name(offer.from_item, strategy)
    norm_to = normalize_purchase_item_name(offer.to_item, strategy)
    rules = strategy.get("purchase_station_rules") if isinstance(strategy.get("purchase_station_rules"), dict) else {}
    for blocked in rules.get("blocked_conversions") or []:
        if not isinstance(blocked, dict):
            continue
        b_from = normalize_purchase_item_name(str(blocked.get("from_item") or ""), strategy)
        b_to = normalize_purchase_item_name(str(blocked.get("to_item") or ""), strategy)
        min_level = int(blocked.get("min_prison_level") or 0)
        always_block = bool(blocked.get("always_block", False))
        if norm_from == b_from and norm_to == b_to and (always_block or prison.level >= min_level):
            return PurchaseDecision(
                from_item=offer.from_item,
                to_item=offer.to_item,
                normalized_from_item=norm_from,
                normalized_to_item=norm_to,
                action="block",
                reason=str(blocked.get("reason") or f"高危采购暗雷：禁止用「{norm_from}」转换「{norm_to}」。"),
            )
    return PurchaseDecision(
        from_item=offer.from_item,
        to_item=offer.to_item,
        normalized_from_item=norm_from,
        normalized_to_item=norm_to,
        action="accept",
        reason=f"安全无消耗转换：「{norm_from}」→「{norm_to}」等同白送原料，可点击转换。",
    )


def evaluate_exchange_shop_item(
    item_name: str,
    currency: str = "work_tickets",
    catalog: Optional[dict[str, Any]] = None,
) -> ShopItemDecision:
    """评估整顿中心兑换商店道具：屏蔽桦石项与可再生低效项，保留一次性高价值奖励。"""
    strategy = catalog if isinstance(catalog, dict) else load_prison_strategy_catalog()
    name = str(item_name or "").strip()
    curr = str(currency or "work_tickets").strip().lower()
    shop_rules = strategy.get("exchange_shop_rules") if isinstance(strategy.get("exchange_shop_rules"), dict) else {}

    if curr == "huashi":
        return ShopItemDecision(
            item_name=name,
            currency=curr,
            action="block_huashi",
            reason="严禁在兑换商店花费桦石（含 10 桦石超级帮帮券并列陷阱）。",
        )

    blocked_renewables = {str(item).strip() for item in (shop_rules.get("blocked_renewable_items") or [])}
    if name in blocked_renewables:
        return ShopItemDecision(
            item_name=name,
            currency=curr,
            action="skip_renewable",
            reason="可再生兑换项（逮捕令/超级帮帮券）性价比极低，攻略建议完全跳过。",
        )

    for rec in shop_rules.get("recommended_one_time_items") or []:
        if not isinstance(rec, dict):
            continue
        rec_name = str(rec.get("name") or "").strip()
        if name == rec_name or (rec_name == "研发配方" and ("配方" in name or "织造法" in name or "剪裁法" in name or "缝制" in name or "制造法" in name)):
            return ShopItemDecision(
                item_name=name,
                currency=curr,
                action="buy_one_time",
                reason=str(rec.get("notes") or "一次性高价值兑换项，按当前需求优先换取。"),
            )

    return ShopItemDecision(
        item_name=name,
        currency=curr,
        action="review_manual",
        reason="非核心清单项，若属一次性独有道具可酌情兑换，否则节省工票。",
    )


def _building_name(building_id: str, building_catalog: dict[str, Any]) -> str:
    entry = building_catalog.get(building_id)
    if isinstance(entry, dict) and entry.get("name"):
        return str(entry["name"])
    return building_id


def _raw_upgrade_required_research(from_level: int, strategy: dict[str, Any]) -> int:
    upgrades = strategy.get("raw_workshop_upgrades") if isinstance(strategy.get("raw_workshop_upgrades"), list) else []
    for entry in upgrades:
        if isinstance(entry, dict) and int(entry.get("from_level") or -1) == int(from_level):
            return int(entry.get("required_research_level") or 0)
    return 0


def _build_building_recommendations(
    prison: PrisonSnapshot,
    options: PrisonPlanOptions,
    phase: Literal["rush_leveling", "profit_harvest"],
    spendable_coins: int,
    strategy: dict[str, Any],
) -> Tuple[List[BuildingRecommendation], int, Optional[int]]:
    building_catalog = strategy.get("building_catalog") if isinstance(strategy.get("building_catalog"), dict) else {}
    thresholds = strategy.get("thresholds") if isinstance(strategy.get("thresholds"), dict) else {}
    recs: List[BuildingRecommendation] = []

    research_lvl = int(prison.buildings.get("research_center", 0))
    power_lvl = int(prison.buildings.get("power_center", 0))
    confinement_lvl = int(prison.buildings.get("confinement_room", 0))
    infirmary_lvl = int(prison.buildings.get("infirmary", 0))
    ladder_cap, next_unlock_lv = recommended_dorm_and_workshop_count(prison.level, strategy)

    # 1. 生产车间硬前置检查（实机 LV2 验证）
    if confinement_lvl < 1:
        if prison.level < 3:
            recs.append(
                BuildingRecommendation(
                    building_id="confinement_room",
                    name=_building_name("confinement_room", building_catalog),
                    priority="blocker",
                    action="先交黑月/初期任务推进整顿中心至 LV3，随后建「禁闭室」LV1",
                    reason="1 号生产车间必须电力中心、研发中心、医务室、禁闭室均开启才放行；禁闭室在 LV3 解锁。",
                )
            )
        else:
            recs.append(
                BuildingRecommendation(
                    building_id="confinement_room",
                    name=_building_name("confinement_room", building_catalog),
                    priority="blocker",
                    action="立即建造「禁闭室」LV1（之后不再优先加升）",
                    reason="解除 1 号生产车间前置锁定所需，后续仅作低优治安挂件。",
                )
            )

    if infirmary_lvl < 1:
        recs.append(
            BuildingRecommendation(
                building_id="infirmary",
                name=_building_name("infirmary", building_catalog),
                priority="blocker",
                action="立即建造「医务室」LV1",
                reason="1 号生产车间基础设施前置之一。",
            )
        )

    # 2. 核心必满双雄：研发中心 & 电力中心
    if phase == "rush_leveling":
        machine_req = int(thresholds.get("machine_upgrade_research_level") or 6)
        milestones = (building_catalog.get("research_center") or {}).get("milestones") or {}
        pending_milestones = [
            f"LV{lv}:{desc}"
            for lv, desc in sorted(((int(k), str(v)) for k, v in milestones.items()), key=lambda pair: pair[0])
            if lv > research_lvl
        ]
        milestone_note = "；下一节点：" + " -> ".join(pending_milestones[:2]) if pending_milestones else "已解锁全部主要原料车间与机器升级，继续跟满。"
        if research_lvl < machine_req:
            recs.append(
                BuildingRecommendation(
                    building_id="research_center",
                    name=_building_name("research_center", building_catalog),
                    priority="high",
                    action=f"核心优先升级「研发中心」（当前 LV{research_lvl} → 先冲 LV{min(research_lvl + 1, machine_req)}，阶段目标 LV{machine_req}）",
                    reason=f"每次整顿升级优先跟升研发中心{milestone_note}",
                )
            )
        else:
            recs.append(
                BuildingRecommendation(
                    building_id="research_center",
                    name=_building_name("research_center", building_catalog),
                    priority="high",
                    action=f"继续跟升「研发中心」（当前 LV{research_lvl}）解锁新研发配方",
                    reason="核心建筑，随整顿中心等级优先拉满。",
                )
            )

        recs.append(
            BuildingRecommendation(
                building_id="power_center",
                name=_building_name("power_center", building_catalog),
                priority="high",
                action=f"优先随整顿等级跟升「电力中心」（当前 LV{power_lvl}，余电 {max(0, prison.power_max - prison.power_used)}）",
                reason="核心基础设施，防止原料车间与阶梯扩建出现电力瓶颈。",
            )
        )

    # 3. 4 个原料车间（无电力陷阱，能升尽量升）
    beginner_dep = int(thresholds.get("raw_workshop_predeposit_beginner") or 500_000)
    veteran_dep = int(thresholds.get("raw_workshop_predeposit_veteran") or 2_500_000)
    vet_lv = int(thresholds.get("raw_workshop_veteran_player_level") or 80)
    rec_predeposit = veteran_dep if options.player_level >= vet_lv else beginner_dep
    for raw_id in RAW_WORKSHOP_IDS:
        info = building_catalog.get(raw_id) or {}
        req_research = int(info.get("unlock_research_level") or 0)
        cur_lvl = int(prison.buildings.get(raw_id, 0))
        name = _building_name(raw_id, building_catalog)
        if research_lvl < req_research:
            recs.append(
                BuildingRecommendation(
                    building_id=raw_id,
                    name=name,
                    priority="defer",
                    action=f"暂未解锁（需研发中心 LV{req_research}）",
                    reason=f"待研发中心达 LV{req_research} 后立即建造并拉满。",
                )
            )
        elif cur_lvl < 10:
            rem_coins = raw_workshop_remaining_cost(cur_lvl, strategy)
            req_upgrade_research = _raw_upgrade_required_research(cur_lvl, strategy) if cur_lvl >= 1 else 0
            if cur_lvl >= 1 and req_upgrade_research > 0 and research_lvl < req_upgrade_research:
                recs.append(
                    BuildingRecommendation(
                        building_id=raw_id,
                        name=name,
                        priority="defer",
                        action=f"暂缓升级「{name}」（当前 LV{cur_lvl}，升至 LV{cur_lvl + 1} 需研发中心 LV{req_upgrade_research}）",
                        reason=f"实机前置要求研发中心达 LV{req_upgrade_research} 后才能继续升至 LV{cur_lvl + 1}（单间升满累计仍需 {rem_coins:,} 铁盟币）；开干前可先预存 {rec_predeposit:,} 铁盟币。",
                        estimated_coin_cost=rem_coins,
                    )
                )
                continue
            budget_note = "可用余额充足可续升" if spendable_coins > 0 else "当前金币已达保留地板，只作排期暂不动款"
            recs.append(
                BuildingRecommendation(
                    building_id=raw_id,
                    name=name,
                    priority="high",
                    action=f"持续升级「{name}」（当前 LV{cur_lvl}→LV10），开干前预存 {rec_predeposit:,} 铁盟币",
                    reason=f"原料车间互不冲突且无阶梯陷阱，能升尽量升（单间升至满级仍需 {rem_coins:,} 铁盟币；{budget_note}）。",
                    estimated_coin_cost=rem_coins,
                )
            )

    # 4. 宿舍 & 生产车间阶梯控制（1/6/16/26/36/46）
    if prison.dorm_count < ladder_cap or prison.production_workshop_count < ladder_cap:
        recs.append(
            BuildingRecommendation(
                building_id="dormitory",
                name="宿舍与生产车间阶梯",
                priority="high",
                action=f"当前整顿 LV{prison.level} 允许开至 {ladder_cap} 宿舍 + {ladder_cap} 生产车间（现 {prison.dorm_count}/{prison.production_workshop_count}），可补开并清满区域",
                reason="每间宿舍 36 床按 18成品 + 10原料 + 8病/刑满缓冲 分配。",
            )
        )
    elif prison.dorm_count > ladder_cap or prison.production_workshop_count > ladder_cap:
        recs.append(
            BuildingRecommendation(
                building_id="dormitory",
                name="宿舍与生产车间阶梯",
                priority="warning",
                action=f"当前宿舍/车间数（{prison.dorm_count}/{prison.production_workshop_count}）超过 LV{prison.level} 阶梯上限 {ladder_cap}，立即停止继续新增",
                reason="过早多开宿舍与车间会直接吸干有限电力导致核心产线停转。",
            )
        )
    else:
        next_hint = f"等整顿 LV{next_unlock_lv} 再开下一套（末尾为 6 节奏）" if next_unlock_lv else "已达到最大 6 套阶梯"
        recs.append(
            BuildingRecommendation(
                building_id="dormitory",
                name="宿舍与生产车间阶梯",
                priority="defer",
                action=f"保持当前 {prison.dorm_count} 宿舍 + {prison.production_workshop_count} 车间暂不新开，{next_hint}",
                reason="严格按 1/6/16/26/36/46 阶梯扩建，省电保核心设施与原料车间。",
            )
        )

    # 5. 财务中心 & 转运中心一次性设定
    if prison.deposit_auto_refill is not True:
        recs.append(
            BuildingRecommendation(
                building_id="finance_center",
                name=_building_name("finance_center", building_catalog),
                priority="medium",
                action="进入「财务中心」确认开启「保证金低于80%自动补满」后无需再管",
                reason="避免保证金耗尽造成停产。",
            )
        )

    transfer_unlock = int(thresholds.get("transfer_center_unlock_level") or 9)
    desired_anchors = list(thresholds.get("recommended_transfer_anchors") or ["海角城", "岚心城"])
    if prison.level >= transfer_unlock:
        missing_anchors = [city for city in desired_anchors if city not in prison.transfer_anchors]
        if missing_anchors:
            recs.append(
                BuildingRecommendation(
                    building_id="transfer_center",
                    name=_building_name("transfer_center", building_catalog),
                    priority="high",
                    action=f"立即在「转运中心」绑定锚点：{' / '.join(desired_anchors)}（当前缺：{'、'.join(missing_anchors)}）",
                    reason="9 级解锁后既可跑商顺路带囚犯回狱，也是毕业赚钱阶段卖成品高价出货的唯一通道。",
                )
            )
    else:
        recs.append(
            BuildingRecommendation(
                building_id="transfer_center",
                name=_building_name("transfer_center", building_catalog),
                priority="defer",
                action=f"待整顿 LV{transfer_unlock} 解锁「转运中心」后立即绑定锚点：{' / '.join(desired_anchors)}",
                reason="提前规划跑商带囚犯与后期高价出货通道。",
            )
        )

    # 6. 假释室与低优先治安挂件房
    recs.append(
        BuildingRecommendation(
            building_id="parole_room",
            name=_building_name("parole_room", building_catalog),
            priority="ignore",
            action="直接无视「假释室」，不花铁盟币升也不主动假释囚犯",
            reason="抓囚犯消耗的体力/疲劳远贵于假释返还的一点铁盟币，应让囚犯留岗打满剩余价值至刑满。",
        )
    )
    if options.ignore_incident_rooms:
        low_names = "、".join(_building_name(bid, building_catalog) for bid in LOW_PRIORITY_INCIDENT_ROOM_IDS)
        recs.append(
            BuildingRecommendation(
                building_id="incident_rooms_bundle",
                name="治安与降低坏事件挂件房",
                priority="ignore",
                action=f"冲级期不优先投资：{low_names}",
                reason="攻略明确标注“并不关键”（仅禁闭室/医务室建 LV1 开车间前置即可），省下海量铁盟币与电力。",
            )
        )

    return recs, ladder_cap, next_unlock_lv


def _build_guarded_huashi_actions(
    prison: PrisonSnapshot,
    options: PrisonPlanOptions,
    strategy: dict[str, Any],
) -> List[GuardedHuashiAction]:
    motor_cost = remaining_power_motor_cost(prison.motors_installed, strategy)
    motor_status: Literal["blocked_by_guardrail", "opt_in_enabled", "completed"]
    if motor_cost["remaining_slots"] == 0:
        motor_status = "completed"
    elif options.allow_huashi_motors:
        motor_status = "opt_in_enabled"
    else:
        motor_status = "blocked_by_guardrail"

    actions = [
        GuardedHuashiAction(
            action_id="power_center_motors",
            title=f"电力中心安装电机（已装 {prison.motors_installed}/20 槽）",
            status=motor_status,
            next_huashi_cost=motor_cost["next_huashi"],
            next_coin_cost=motor_cost["next_coins"],
            remaining_total_huashi=motor_cost["total_remaining_huashi"],
            remaining_total_coins=motor_cost["total_remaining_coins"],
            notes=(
                "1~20 槽累计共需 3,500 桦石 + 28,700,000 铁盟币；二周年攻略强烈建议拉满防后期缺电。"
                "受桦石保护护栏默认屏蔽，仅在显式开启 allow_huashi_motors 时放行。"
            ),
        ),
        GuardedHuashiAction(
            action_id="warehouse_huashi_expansion",
            title="仓库扩容右侧「桦石页签」（双仓防爆仓）",
            status="opt_in_enabled" if options.allow_huashi_warehouse else "blocked_by_guardrail",
            notes=(
                "与左侧铁盟币扩容并列（实机含 100 次上限）；二周年攻略建议随升级点满防爆仓。"
                "默认屏蔽右侧桦石页签，需显式开启 allow_huashi_warehouse。"
            ),
        ),
    ]
    return actions


def _build_prisoner_recommendations(
    prison: PrisonSnapshot,
    growth_catalog: dict[str, Any],
) -> List[str]:
    stages = growth_catalog.get("stages") if isinstance(growth_catalog.get("stages"), list) else []
    need_note = (
        f"当前在监囚犯 {prison.prisoners_current}/{prison.prisoners_capacity}，尚缺工位 {max(0, prison.prisoners_capacity - prison.prisoners_current)} 名："
        if prison.prisoners_capacity > 0 and prison.prisoners_current < prison.prisoners_capacity
        else "囚犯常规补员路线："
    )
    recs = [need_note]
    priority_ids = ("material_tiaodeng", "equip_zhishi", "equip_yazhi", "event_leyuan_shallow1", "event_haidao_sp4")
    by_id = {str(s.get("id") or ""): s for s in stages if isinstance(s, dict)}
    for sid in priority_ids:
        stage = by_id.get(sid)
        if stage:
            recs.append(f"• {stage['name']}（{stage['clarity_cost']} 澄明度 / {stage['prisoners']} 囚犯）：{stage['notes']}")
    return recs


def plan_prison(
    snapshot: AccountSnapshot,
    options: Optional[PrisonPlanOptions] = None,
    *,
    strategy_catalog: Optional[dict[str, Any]] = None,
    growth_catalog: Optional[dict[str, Any]] = None,
) -> PrisonPlanReport:
    """根据统一账号快照与策略目录生成整顿中心零消费规划报告。"""
    opts = options or PrisonPlanOptions()
    strategy = strategy_catalog if isinstance(strategy_catalog, dict) else load_prison_strategy_catalog()
    growth = growth_catalog if isinstance(growth_catalog, dict) else load_growth_stages_catalog()
    thresholds = strategy.get("thresholds") if isinstance(strategy.get("thresholds"), dict) else {}

    prison = snapshot.prison
    wallet = snapshot.wallet
    phase = detect_prison_phase(prison, opts, strategy)
    spendable_coins = max(0, int(wallet.coins) - int(opts.reserve_coins))
    power_free = int(prison.power_max) - int(prison.power_used)

    prereq_warnings: List[str] = []
    if snapshot.available_cities:
        if "岚心城" not in snapshot.available_cities:
            prereq_warnings.append(
                "尚未解锁「岚心城」：二周年攻略明确不建议在未解锁岚心城、客运与海岛毕业前重投整顿中心。"
            )
        if "云岫桥基地" not in snapshot.available_cities:
            prereq_warnings.append("可用城市列表未检测到整顿中心所在站点「云岫桥基地」。")
    if wallet.coins > 0 and spendable_coins == 0:
        prereq_warnings.append(
            f"当前铁盟币（{wallet.coins:,}）未超过保留地板（{opts.reserve_coins:,}），本次可支配预算为 0。"
        )
    full_grad_coins = int(thresholds.get("estimated_full_graduation_coins") or 550_000_000)
    if phase == "rush_leveling" and wallet.coins < full_grad_coins:
        prereq_warnings.append(
            f"整顿中心完美毕业累计约需 {full_grad_coins:,} 铁盟币，当前持有 {wallet.coins:,}，请勿把跑商与养成流动资金一次性砸空。"
        )

    building_recs, ladder_cap, next_unlock_lv = _build_building_recommendations(
        prison, opts, phase, spendable_coins, strategy
    )
    guarded_actions = _build_guarded_huashi_actions(prison, opts, strategy)

    warehouse_advice = [
        f"原料仓 {prison.raw_warehouse_used}/{prison.raw_warehouse_cap}、成品仓 {prison.finished_warehouse_used}/{prison.finished_warehouse_cap}：先点满左侧铁盟币扩容；两仓库存物无种类限制，快爆仓时可把成品与原料互倒腾缓冲。"
    ]

    order_decisions = [
        evaluate_black_moon_order(order, prison, phase, strategy)
        for order in prison.active_orders
    ]
    purchase_decisions = [
        evaluate_purchase_offer(offer, prison, strategy)
        for offer in prison.purchase_offers
    ]
    default_shop_checks = [
        ("拉普拉斯协议", "work_tickets"),
        ("自观测胶卷", "work_tickets"),
        ("逮捕令", "work_tickets"),
        ("超级帮帮券", "work_tickets"),
        ("超级帮帮券", "huashi"),
    ]
    shop_decisions = [
        evaluate_exchange_shop_item(name, currency, strategy)
        for name, currency in default_shop_checks
    ]

    if phase == "rush_leveling":
        production_advice = [
            "冲级阶段核心原则：绝不直接卖成品，全部通过黑月服装订单站交单换整顿经验。",
            "并行防爆仓：同时排产 21 种冲级白名单内不同原料系货物（吃满 4 原料车间），每种做一轮就轮换，避免单一成品囤积卡死。",
            "特例提醒：《冲锋衣》仅周单做（日单删）；《牛仔布》《牛仔裤》后期（20级+）极易爆仓不再大量做；《真丝睡衣》前期等其他货充裕后再做。",
        ]
    else:
        rules = strategy.get("profit_harvest_rules") if isinstance(strategy.get("profit_harvest_rules"), dict) else {}
        align_hours = int(thresholds.get("silk_align_hours") or 10)
        production_advice = [
            "毕业赚钱阶段：停止交付黑月订单，锁定三巨头高收益直卖成品：「真丝睡衣（动+缝）」「蕾丝连衣裙（植+缝）」「阿妮塔连体衣（人+缝）」。",
            f"通过转运中心运往「{' / '.join(rules.get('sell_cities') or ['海角城', '岚心城'])}」价格更高的一方出售；严禁暂停缝纫工具与人造纤维原料车间（仅植物/动物囤积过多时可暂缓）。",
            f"缝纫包/绣线不足时前往「{rules.get('restock_city') or '云岫桥基地'}」用进货书补货塞进仓库；「蚕丝→丝绸」单轮建议定为 {align_hours} 小时（上限 20h），与其余 12h 上限产线对齐同收。",
        ]

    beginner_dep = int(thresholds.get("raw_workshop_predeposit_beginner") or 500_000)
    veteran_dep = int(thresholds.get("raw_workshop_predeposit_veteran") or 2_500_000)
    vet_lv = int(thresholds.get("raw_workshop_veteran_player_level") or 80)
    rec_predeposit = veteran_dep if opts.player_level >= vet_lv else beginner_dep

    return PrisonPlanReport(
        uid=snapshot.uid,
        phase=phase,
        prison_level=prison.level,
        coins_total=wallet.coins,
        reserve_coins=opts.reserve_coins,
        spendable_coins=spendable_coins,
        huashi_total=wallet.huashi,
        work_tickets=prison.work_tickets,
        power_used=prison.power_used,
        power_max=prison.power_max,
        power_free=power_free,
        dorm_count=prison.dorm_count,
        production_workshop_count=prison.production_workshop_count,
        recommended_dorm_and_workshop_cap=ladder_cap,
        next_ladder_unlock_level=next_unlock_lv,
        recommended_raw_predeposit=rec_predeposit,
        prerequisite_warnings=prereq_warnings,
        warehouse_advice=warehouse_advice,
        building_recommendations=building_recs,
        guarded_huashi_actions=guarded_actions,
        order_decisions=order_decisions,
        purchase_decisions=purchase_decisions,
        shop_decisions=shop_decisions,
        production_advice=production_advice,
        prisoner_farming_recommendations=_build_prisoner_recommendations(prison, growth),
    )


def _guide_attr(item: Any, name: str, default: Any = "") -> Any:
    if isinstance(item, dict):
        return item.get(name, default)
    return getattr(item, name, default)


def format_prison_plan_markdown(
    report: PrisonPlanReport,
    *,
    semi_auto_guides: Optional[Sequence[Any]] = None,
) -> str:
    """将整顿中心规划报告渲染为简洁中文 Markdown。"""
    phase_label = "冲级阶段（交黑月订单优先）" if report.phase == "rush_leveling" else "毕业赚钱阶段（转运中心直卖）"
    lines = [
        f"## 整顿中心规划报告（UID `{report.uid}` · LV {report.prison_level}）",
        "",
        f"- **当前阶段**：{phase_label}",
        f"- **资产与预算**：铁盟币 `{report.coins_total:,}`（保留地板 `{report.reserve_coins:,}` → 可支配 `{report.spendable_coins:,}`）｜桦石 `{report.huashi_total:,}`｜工票 `{report.work_tickets:,}`",
        f"- **电力与规模**：电力 `{report.power_used}/{report.power_max}`（余电 `{report.power_free}`）｜宿舍 `{report.dorm_count}` / 生产车间 `{report.production_workshop_count}`（当前阶梯上限 `{report.recommended_dorm_and_workshop_cap}`"
        + (f"，下套解锁 LV {report.next_ladder_unlock_level}）" if report.next_ladder_unlock_level else "，已达上限）"),
        f"- **原料车间单次预存建议**：`{report.recommended_raw_predeposit:,}` 铁盟币",
    ]
    if report.prerequisite_warnings:
        lines.extend(["", "### 风险与前置提醒"])
        for warning in report.prerequisite_warnings:
            lines.append(f"- [警告] {warning}")

    lines.extend(["", "### 建筑与投资优先级"])
    priority_tag = {
        "blocker": "前置阻塞",
        "high": "优先",
        "medium": "一次设置",
        "defer": "暂缓",
        "ignore": "忽略",
        "warning": "越阶警告",
    }
    for rec in report.building_recommendations:
        cost_part = f"（约需 `{rec.estimated_coin_cost:,}` 币）" if rec.estimated_coin_cost else ""
        lines.append(f"- **[{priority_tag.get(rec.priority, rec.priority)}] {rec.name}**：{rec.action}{cost_part} —— {rec.reason}")

    lines.extend(["", "### 桦石保护项（需显式放行）"])
    for item in report.guarded_huashi_actions:
        status_label = {
            "blocked_by_guardrail": "已拦截(默认)",
            "opt_in_enabled": "已放行",
            "completed": "已完成",
        }.get(item.status, item.status)
        cost_desc = ""
        if item.remaining_total_huashi > 0:
            cost_desc = f" | 下槽 `{item.next_huashi_cost}` 桦石 + `{item.next_coin_cost:,}` 币，剩余累计 `{item.remaining_total_huashi:,}` 桦石 + `{item.remaining_total_coins:,}` 币"
        lines.append(f"- **[{status_label}] {item.title}**{cost_desc} —— {item.notes}")

    lines.extend(["", "### 仓库与排产建议"])
    for item in report.warehouse_advice + report.production_advice:
        lines.append(f"- {item}")

    if report.order_decisions:
        lines.extend(["", "### 黑月订单评估"])
        for od in report.order_decisions:
            lines.append(f"- **{od.item_name}×{od.quantity}**（{od.order_type}，存货 `{od.stock_owned}`）→ `{od.action}`：{od.reason}")

    if report.purchase_decisions:
        lines.extend(["", "### 原料采购站评估"])
        for pd in report.purchase_decisions:
            lines.append(f"- **{pd.from_item} → {pd.to_item}** → `{pd.action}`：{pd.reason}")

    lines.extend(["", "### 兑换商店规范"])
    for sd in report.shop_decisions:
        lines.append(f"- **{sd.item_name}**（{sd.currency}）→ `{sd.action}`：{sd.reason}")

    lines.extend(["", "### 抓囚犯关卡参考"])
    for tip in report.prisoner_farming_recommendations:
        lines.append(f"- {tip}" if not tip.startswith("•") else f"  {tip}")

    if semi_auto_guides:
        pri_map = {"urgent": "优先手动", "recommended": "建议手动", "optional": "可选手动"}
        lines.extend(["", "### 半自动人工接力指引"])
        for idx, guide in enumerate(semi_auto_guides, 1):
            pri = str(_guide_attr(guide, "priority", "recommended"))
            title = str(_guide_attr(guide, "title", ""))
            why = str(_guide_attr(guide, "why_manual", ""))
            steps = list(_guide_attr(guide, "steps", ()) or ())
            lines.append(f"- **[{pri_map.get(pri, pri)}] {idx}. {title}** —— {why}")
            for s_idx, step_txt in enumerate(steps, 1):
                lines.append(f"  {s_idx}. {step_txt}")

    return "\n".join(lines)
