"""整顿中心（监狱）Stage 3 纯 Python 执行决策引擎（做什么 / 买什么 / 造什么）。"""
from __future__ import annotations

from typing import Any, List, Literal, Optional, Sequence

from pydantic import BaseModel, Field

from maa_resonance.logic.planning.account_snapshot import AccountSnapshot
from maa_resonance.logic.planning.catalogs import load_prison_strategy_catalog
from maa_resonance.logic.planning.prison_planner import (
    LOW_PRIORITY_INCIDENT_ROOM_IDS,
    PrisonPlanOptions,
    PrisonPlanReport,
    RAW_WORKSHOP_IDS,
    recommended_dorm_and_workshop_count,
)


class PrisonActionStep(BaseModel):
    """单条经过资金底线与安全护栏校验的可执行或已拦截操作步骤。"""

    category: Literal["do", "buy", "build"]
    action_type: str
    title: str
    target: str
    allowed: bool
    priority: int = 50
    estimated_coins: int = 0
    estimated_huashi: int = 0
    estimated_tickets: int = 0
    reason: str = ""
    blocked_reason: str = ""


class PrisonActionOutcome(BaseModel):
    """单次实机执行、跳过或护栏拦截动作结果。"""

    category: Literal["do", "buy", "build", "guard"]
    action_type: str
    target: str
    status: Literal["executed", "skipped", "guard_abort", "failed"]
    detail: str = ""
    coins_delta: int = 0
    tickets_delta: int = 0


class SemiAutoGuideItem(BaseModel):
    """需要用户手动介入或接力的半自动精确操作指引。"""

    priority: Literal["urgent", "recommended", "optional"]
    category: Literal["prisoners", "unlock", "production", "orders", "huashi", "setup", "shop"]
    title: str
    why_manual: str
    steps: List[str] = Field(default_factory=list)


class PrisonRunReceipt(BaseModel):
    """整顿中心单次运行的实机执行与安全审计回执。"""

    mode: Literal["plan_only", "execute_safe_auto"]
    scope: str = "full_safe"
    coins_before: int = 0
    coins_after: int = 0
    tickets_before: int = 0
    tickets_after: int = 0
    huashi_before: int = 0
    huashi_after: int = 0
    executed: List[PrisonActionOutcome] = Field(default_factory=list)
    skipped: List[PrisonActionOutcome] = Field(default_factory=list)
    guard_aborts: List[PrisonActionOutcome] = Field(default_factory=list)
    upgraded_buildings: dict[str, int] = Field(default_factory=dict)
    deposit_auto_refill_verified: Optional[bool] = None
    semi_auto_guides: List[SemiAutoGuideItem] = Field(default_factory=list)


class PrisonExecutionPlan(BaseModel):
    """整顿中心分栏可执行动作清单与模拟资金推演。"""

    uid: str
    phase: Literal["rush_leveling", "profit_harvest"]
    prison_level: int
    coins_before: int
    reserve_coins: int
    simulated_coins_after: int
    do_actions: List[PrisonActionStep] = Field(default_factory=list)
    buy_actions: List[PrisonActionStep] = Field(default_factory=list)
    build_actions: List[PrisonActionStep] = Field(default_factory=list)
    blocked_actions: List[PrisonActionStep] = Field(default_factory=list)


def _raw_upgrade_cost(from_level: int, upgrades: list[dict[str, Any]]) -> int:
    for entry in upgrades:
        if isinstance(entry, dict) and int(entry.get("from_level") or -1) == int(from_level):
            return int(entry.get("coins") or 0)
    return 0


def _raw_upgrade_required_research(from_level: int, upgrades: list[dict[str, Any]]) -> int:
    for entry in upgrades:
        if isinstance(entry, dict) and int(entry.get("from_level") or -1) == int(from_level):
            return int(entry.get("required_research_level") or 0)
    return 0


def _append_step(
    target_list: List[PrisonActionStep],
    blocked_list: List[PrisonActionStep],
    step: PrisonActionStep,
) -> None:
    target_list.append(step)
    if not step.allowed:
        blocked_list.append(step)


def build_prison_execution_plan(
    snapshot: AccountSnapshot,
    prison_report: PrisonPlanReport,
    options: Optional[PrisonPlanOptions] = None,
    *,
    strategy_catalog: Optional[dict[str, Any]] = None,
) -> PrisonExecutionPlan:
    """将整顿中心规划结论转换为受铁盟币底线/零桦石/阶梯锁保护的执行清单。"""
    opts = options or PrisonPlanOptions()
    strategy = strategy_catalog if isinstance(strategy_catalog, dict) else load_prison_strategy_catalog()
    building_catalog = strategy.get("building_catalog") if isinstance(strategy.get("building_catalog"), dict) else {}
    thresholds = strategy.get("thresholds") if isinstance(strategy.get("thresholds"), dict) else {}
    raw_upgrades = strategy.get("raw_workshop_upgrades") if isinstance(strategy.get("raw_workshop_upgrades"), list) else []

    prison = snapshot.prison
    sim_coins = int(snapshot.wallet.coins)
    reserve = max(0, int(opts.reserve_coins))

    def _try_spend_coins(cost: int) -> bool:
        nonlocal sim_coins
        spend = max(0, int(cost))
        if spend == 0:
            return True
        if sim_coins - spend >= reserve:
            sim_coins -= spend
            return True
        return False

    do_actions: List[PrisonActionStep] = []
    buy_actions: List[PrisonActionStep] = []
    build_actions: List[PrisonActionStep] = []
    blocked_actions: List[PrisonActionStep] = []

    research_lvl = int(prison.buildings.get("research_center", 0))
    power_lvl = int(prison.buildings.get("power_center", 0))
    confinement_lvl = int(prison.buildings.get("confinement_room", 0))
    infirmary_lvl = int(prison.buildings.get("infirmary", 0))
    machine_req = int(thresholds.get("machine_upgrade_research_level") or 6)
    ladder_cap, next_unlock_lv = recommended_dorm_and_workshop_count(prison.level, strategy)

    # ===================== 1. 造什么（建造 / 升级 / 设置）=====================
    if confinement_lvl < 1:
        if prison.level >= 3:
            build_actions.append(
                PrisonActionStep(
                    category="build",
                    action_type="building_unlock",
                    title="立即建造「禁闭室」LV1（解锁生产车间前置）",
                    target="禁闭室",
                    allowed=True,
                    priority=10,
                    reason="整顿 LV3 已解锁禁闭室，开启后 1 号生产车间才能正式投入生产。",
                )
            )
        else:
            blocked_actions.append(
                PrisonActionStep(
                    category="build",
                    action_type="building_unlock",
                    title="建造「禁闭室」LV1（前置解锁）",
                    target="禁闭室",
                    allowed=False,
                    priority=10,
                    blocked_reason="需先推进整顿中心至 LV3 后才会解锁禁闭室。",
                )
            )

    if infirmary_lvl < 1:
        build_actions.append(
            PrisonActionStep(
                category="build",
                action_type="building_unlock",
                title="立即建造「医务室」LV1（解锁生产车间前置）",
                target="医务室",
                allowed=True,
                priority=12,
                reason="1 号生产车间必需基础房间，建至 LV1 后不再优先投入。",
            )
        )

    if prison_report.phase == "rush_leveling":
        research_note = (
            f"阶段目标 LV{machine_req}（解锁全部原料车间与车间机器升级）"
            if research_lvl < machine_req
            else "核心必满设施，随整顿等级持续跟满"
        )
        can_research = sim_coins > reserve
        _append_step(
            build_actions,
            blocked_actions,
            PrisonActionStep(
                category="build",
                action_type="building_upgrade",
                title=f"优先升级「研发中心」LV{research_lvl}→LV{research_lvl + 1}",
                target="研发中心",
                allowed=can_research,
                priority=20,
                reason=research_note,
                blocked_reason="" if can_research else f"当前铁盟币未超过安全底线（{reserve:,}），暂缓投入。",
            ),
        )

        power_free = max(0, int(prison.power_max) - int(prison.power_used))
        can_power = sim_coins > reserve
        _append_step(
            build_actions,
            blocked_actions,
            PrisonActionStep(
                category="build",
                action_type="building_upgrade",
                title=f"跟升「电力中心（仅房间升级页）」LV{power_lvl}→LV{power_lvl + 1}",
                target="电力中心",
                allowed=can_power,
                priority=22,
                reason=f"当前余电 {power_free:,}，防止后续原料/阶梯扩建缺电；严禁切到安装电机页。",
                blocked_reason="" if can_power else f"当前铁盟币未超过安全底线（{reserve:,}），暂缓投入。",
            ),
        )

    # 4 个原料车间逐一查下一级精确费用并扣减模拟余额
    unlocked_raw_names: list[str] = []
    for idx, raw_id in enumerate(RAW_WORKSHOP_IDS):
        info = building_catalog.get(raw_id) if isinstance(building_catalog.get(raw_id), dict) else {}
        name = str(info.get("name") or raw_id)
        req_research = int(info.get("unlock_research_level") or 0)
        cur_lvl = int(prison.buildings.get(raw_id, 0))
        if cur_lvl >= 1:
            unlocked_raw_names.append(name)
        if cur_lvl >= 10:
            continue
        next_cost = _raw_upgrade_cost(cur_lvl, raw_upgrades)
        if cur_lvl == 0 and research_lvl < req_research:
            _append_step(
                build_actions,
                blocked_actions,
                PrisonActionStep(
                    category="build",
                    action_type="building_unlock",
                    title=f"建造「{name}」LV0→LV1",
                    target=name,
                    allowed=False,
                    priority=40 + idx,
                    estimated_coins=next_cost,
                    blocked_reason=f"未达前置：需研发中心 LV{req_research}（当前 LV{research_lvl}）",
                ),
            )
            continue

        req_upgrade_research = _raw_upgrade_required_research(cur_lvl, raw_upgrades) if cur_lvl >= 1 else 0
        if cur_lvl >= 1 and req_upgrade_research > 0 and research_lvl < req_upgrade_research:
            _append_step(
                build_actions,
                blocked_actions,
                PrisonActionStep(
                    category="build",
                    action_type="building_upgrade",
                    title=f"升级「{name}」LV{cur_lvl}→LV{cur_lvl + 1}",
                    target=name,
                    allowed=False,
                    priority=30 + idx,
                    estimated_coins=next_cost,
                    blocked_reason=f"未达前置：升至 LV{cur_lvl + 1} 需研发中心 LV{req_upgrade_research}（当前 LV{research_lvl}）",
                ),
            )
            continue

        act_type = "building_upgrade" if cur_lvl >= 1 else "building_unlock"
        verb = "升级" if cur_lvl >= 1 else "建造"
        if _try_spend_coins(next_cost):
            build_actions.append(
                PrisonActionStep(
                    category="build",
                    action_type=act_type,
                    title=f"{verb}「{name}」LV{cur_lvl}→LV{cur_lvl + 1}",
                    target=name,
                    allowed=True,
                    priority=30 + idx,
                    estimated_coins=next_cost,
                    reason="原料车间互不冲突且无阶梯陷阱，余额充足优先拉升。",
                )
            )
        else:
            _append_step(
                build_actions,
                blocked_actions,
                PrisonActionStep(
                    category="build",
                    action_type=act_type,
                    title=f"{verb}「{name}」LV{cur_lvl}→LV{cur_lvl + 1}",
                    target=name,
                    allowed=False,
                    priority=30 + idx,
                    estimated_coins=next_cost,
                    blocked_reason=f"触及铁盟币保留底线（{reserve:,}），升至 LV{cur_lvl + 1} 需 {next_cost:,} 币。",
                ),
            )

    # 宿舍与车间阶梯控制（1/6/16/26/36/46）
    if prison.dorm_count < ladder_cap or prison.production_workshop_count < ladder_cap:
        build_actions.append(
            PrisonActionStep(
                category="build",
                action_type="building_unlock",
                title=f"补开宿舍/生产车间至 {ladder_cap} 套并清理区域",
                target="宿舍与生产车间阶梯",
                allowed=True,
                priority=48,
                reason=f"当前整顿 LV{prison.level} 阶梯允许 {ladder_cap}/{ladder_cap}（现 {prison.dorm_count}/{prison.production_workshop_count}）。",
            )
        )
    else:
        ladder_hint = (
            f"已达 LV{prison.level} 阶梯上限 {ladder_cap}，等整顿 LV{next_unlock_lv} 再开下一套"
            if next_unlock_lv is not None
            else f"已达最大 {ladder_cap} 套阶梯"
        )
        blocked_actions.append(
            PrisonActionStep(
                category="build",
                action_type="guarded_skip",
                title=f"禁止提前增开宿舍/生产车间（现 {prison.dorm_count}/{prison.production_workshop_count}）",
                target="宿舍与生产车间阶梯",
                allowed=False,
                priority=90,
                blocked_reason=f"{ladder_hint}，严防电力被提前吸干。",
            )
        )

    if prison.deposit_auto_refill is not True:
        build_actions.append(
            PrisonActionStep(
                category="build",
                action_type="setting_check",
                title="核对「财务中心」保证金低于80%自动补满开关",
                target="财务中心",
                allowed=True,
                priority=52,
                reason="开启一次即可防止原料车间因保证金耗尽停产。",
            )
        )

    transfer_unlock = int(thresholds.get("transfer_center_unlock_level") or 9)
    desired_anchors = list(thresholds.get("recommended_transfer_anchors") or ["海角城", "岚心城"])
    if prison.level >= transfer_unlock:
        missing_anchors = [c for c in desired_anchors if c not in prison.transfer_anchors]
        if missing_anchors:
            build_actions.append(
                PrisonActionStep(
                    category="build",
                    action_type="setting_check",
                    title=f"在「转运中心」绑定锚点：{' / '.join(desired_anchors)}",
                    target="转运中心",
                    allowed=True,
                    priority=54,
                    reason=f"当前缺 {'、'.join(missing_anchors)}；既可顺路带囚犯，也供毕业期卖高价货。",
                )
            )
    else:
        blocked_actions.append(
            PrisonActionStep(
                category="build",
                action_type="guarded_skip",
                title=f"解锁「转运中心」并绑定 {' / '.join(desired_anchors)}",
                target="转运中心",
                allowed=False,
                priority=85,
                blocked_reason=f"待整顿 LV{transfer_unlock} 解锁后办理。",
            )
        )

    # 建筑类硬拦截项
    blocked_actions.append(
        PrisonActionStep(
            category="build",
            action_type="guarded_skip",
            title="升级「假释室」或主动假释囚犯",
            target="假释室",
            allowed=False,
            priority=95,
            blocked_reason="攻略避坑：抓囚犯体力远贵于假释返还的一点铁盟币，直接无视假释室。",
        )
    )
    low_room_names = "、".join(
        str((building_catalog.get(bid) or {}).get("name") or bid)
        for bid in LOW_PRIORITY_INCIDENT_ROOM_IDS
    )
    blocked_actions.append(
        PrisonActionStep(
            category="build",
            action_type="guarded_skip",
            title=f"升级治安/降低坏事件挂件房（{low_room_names}）",
            target="治安挂件房",
            allowed=False,
            priority=96,
            blocked_reason="攻略避坑：仅需禁闭室/医务室建 LV1 开车间前置，其余前期绝不砸钱砸电。",
        )
    )

    for guard in prison_report.guarded_huashi_actions:
        if guard.action_id != "power_center_motors" or guard.status == "completed":
            continue
        if opts.allow_huashi_motors:
            can_motor = _try_spend_coins(guard.next_coin_cost) and int(snapshot.wallet.huashi) >= guard.next_huashi_cost
            _append_step(
                build_actions,
                blocked_actions,
                PrisonActionStep(
                    category="build",
                    action_type="power_motor_install",
                    title=guard.title,
                    target="电力中心电机",
                    allowed=can_motor,
                    priority=60,
                    estimated_coins=guard.next_coin_cost,
                    estimated_huashi=guard.next_huashi_cost,
                    reason="你已显式允许消耗桦石安装电机。",
                    blocked_reason="" if can_motor else "桦石或可用铁盟币不足以下一槽电机。",
                ),
            )
        else:
            blocked_actions.append(
                PrisonActionStep(
                    category="build",
                    action_type="guarded_skip",
                    title=guard.title,
                    target="电力中心电机",
                    allowed=False,
                    priority=98,
                    estimated_coins=guard.remaining_total_coins,
                    estimated_huashi=guard.remaining_total_huashi,
                    blocked_reason=(
                        f"默认零桦石护栏拦截（下一槽需 {guard.next_huashi_cost:,} 桦石 + {guard.next_coin_cost:,} 币，"
                        f"剩余累计需 {guard.remaining_total_huashi:,} 桦石 + {guard.remaining_total_coins:,} 币）。"
                    ),
                )
            )

    # ===================== 2. 做什么（订单 / 排产 / 预存）=====================
    urgent_items: set[str] = set()
    for od in prison_report.order_decisions:
        if od.action == "deliver":
            do_actions.append(
                PrisonActionStep(
                    category="do",
                    action_type="order_deliver",
                    title=f"直接交付黑月单：{od.item_name}×{od.quantity}",
                    target=od.item_name,
                    allowed=True,
                    priority=10,
                    reason=od.reason,
                )
            )
        elif od.action == "delete_free":
            do_actions.append(
                PrisonActionStep(
                    category="do",
                    action_type="order_delete_free",
                    title=f"免费删掉非高效单：{od.item_name}×{od.quantity}",
                    target=od.item_name,
                    allowed=True,
                    priority=12,
                    reason=od.reason,
                )
            )
        elif od.action == "produce_then_deliver":
            urgent_items.add(od.item_name)
        else:
            blocked_actions.append(
                PrisonActionStep(
                    category="do",
                    action_type="guarded_skip",
                    title=f"跳过黑月单：{od.item_name}×{od.quantity}",
                    target=od.item_name,
                    allowed=False,
                    priority=88,
                    blocked_reason=od.reason,
                )
            )

    # 推荐车间轮换排产
    if prison_report.phase == "rush_leveling":
        rush_goods = strategy.get("rush_leveling_goods") if isinstance(strategy.get("rush_leveling_goods"), list) else []
        late_level = int(thresholds.get("late_overflow_prison_level") or 20)
        warn_ratio = float(thresholds.get("warehouse_overflow_warning_ratio") or 0.8)
        fin_cap = int(prison.finished_warehouse_cap)
        near_full = fin_cap > 0 and (float(prison.finished_warehouse_used) / float(fin_cap)) >= warn_ratio
        effective_lv = max(1, int(prison.level))

        candidates: list[dict[str, Any]] = []
        for item in rush_goods:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            if not name:
                continue
            guide_idx = int(item.get("guide_index") or 1)
            if guide_idx > effective_lv and name not in urgent_items:
                continue
            if not bool(item.get("daily_recommended", True)) and name not in urgent_items:
                continue
            if bool(item.get("early_only_overflow_risk", False)) and (effective_lv >= late_level or near_full):
                blocked_actions.append(
                    PrisonActionStep(
                        category="do",
                        action_type="guarded_skip",
                        title=f"停止大量排产「{name}」",
                        target=name,
                        allowed=False,
                        priority=86,
                        blocked_reason=f"已达 LV{effective_lv} 或成品仓高占，按攻略防爆仓规则不再囤货。",
                    )
                )
                continue
            candidates.append(item)

        candidates.sort(
            key=lambda g: (
                0 if str(g.get("name") or "") in urgent_items else 1,
                1 if bool(g.get("defer_until_surplus", False)) else 0,
                -int(g.get("rating") if g.get("rating") is not None else 1),
                int(g.get("guide_index") or 99),
            )
        )
        for rank, item in enumerate(candidates[:6]):
            g_name = str(item.get("name") or "")
            tag = "补单急产" if g_name in urgent_items else "轮换防爆仓排产"
            do_actions.append(
                PrisonActionStep(
                    category="do",
                    action_type="produce_good",
                    title=f"生产车间{tag}：{g_name}",
                    target=g_name,
                    allowed=True,
                    priority=20 + rank,
                    reason=str(item.get("notes") or "21 种冲级高效货之一，每轮做满一格即轮换防止成品爆仓。"),
                )
            )
    else:
        profit_goods = strategy.get("profit_harvest_goods") if isinstance(strategy.get("profit_harvest_goods"), list) else []
        for rank, item in enumerate(profit_goods):
            if not isinstance(item, dict):
                continue
            g_name = str(item.get("name") or "")
            if not g_name:
                continue
            do_actions.append(
                PrisonActionStep(
                    category="do",
                    action_type="produce_good",
                    title=f"毕业期主力排产：{g_name}（直卖海角/岚心）",
                    target=g_name,
                    allowed=True,
                    priority=20 + rank,
                    reason=str(item.get("notes") or "毕业期高收益直卖三巨头成品，停交黑月订单。"),
                )
            )

    # 已解锁原料车间预存铁盟币
    predeposit_amt = int(prison_report.recommended_raw_predeposit)
    for rank, raw_name in enumerate(unlocked_raw_names):
        if _try_spend_coins(predeposit_amt):
            do_actions.append(
                PrisonActionStep(
                    category="do",
                    action_type="raw_predeposit",
                    title=f"为「{raw_name}」预存 {predeposit_amt:,} 铁盟币",
                    target=raw_name,
                    allowed=True,
                    priority=40 + rank,
                    estimated_coins=predeposit_amt,
                    reason="保障 24h 原料采集不因垫资耗尽而停工。",
                )
            )
        else:
            _append_step(
                do_actions,
                blocked_actions,
                PrisonActionStep(
                    category="do",
                    action_type="raw_predeposit",
                    title=f"为「{raw_name}」预存 {predeposit_amt:,} 铁盟币",
                    target=raw_name,
                    allowed=False,
                    priority=40 + rank,
                    estimated_coins=predeposit_amt,
                    blocked_reason=f"触及铁盟币保留底线（{reserve:,}），暂不预存。",
                ),
            )

    # ===================== 3. 买什么（扩仓 / 工票商店 / 原料采购站）=====================
    coin_expand_cost = 10_000
    if _try_spend_coins(coin_expand_cost):
        buy_actions.append(
            PrisonActionStep(
                category="buy",
                action_type="warehouse_coin_expand",
                title="仓库扩容：仅点左侧「铁盟币页签」购买",
                target="仓库铁盟币扩容",
                allowed=True,
                priority=15,
                estimated_coins=coin_expand_cost,
                reason="双仓扩容前期优先用铁盟币点满（10,000 币/次），严禁切换到右侧桦石页签。",
            )
        )
    else:
        _append_step(
            buy_actions,
            blocked_actions,
            PrisonActionStep(
                category="buy",
                action_type="warehouse_coin_expand",
                title="仓库扩容：左侧铁盟币页签",
                target="仓库铁盟币扩容",
                allowed=False,
                priority=15,
                estimated_coins=coin_expand_cost,
                blocked_reason=f"触及铁盟币保留底线（{reserve:,}），暂缓扩仓。",
            ),
        )

    for guard in prison_report.guarded_huashi_actions:
        if guard.action_id != "warehouse_huashi_expansion":
            continue
        if opts.allow_huashi_warehouse:
            buy_actions.append(
                PrisonActionStep(
                    category="buy",
                    action_type="warehouse_huashi_expand",
                    title=guard.title,
                    target="仓库桦石扩容",
                    allowed=int(snapshot.wallet.huashi) > 0,
                    priority=60,
                    reason="你已显式允许仓库右侧桦石页签扩容。",
                    blocked_reason="" if int(snapshot.wallet.huashi) > 0 else "当前桦石为 0。",
                )
            )
        else:
            blocked_actions.append(
                PrisonActionStep(
                    category="buy",
                    action_type="guarded_skip",
                    title=guard.title,
                    target="仓库桦石扩容",
                    allowed=False,
                    priority=97,
                    blocked_reason="默认零桦石护栏拦截右侧桦石扩容页签（若需开满防爆仓可在选项放行）。",
                )
            )

    # 兑换商店工票采购
    tickets = int(prison.work_tickets)
    if prison_report.phase == "rush_leveling":
        can_recipe = tickets >= 100 and sim_coins > reserve
        _append_step(
            buy_actions,
            blocked_actions,
            PrisonActionStep(
                category="buy",
                action_type="exchange_ticket_buy",
                title="整顿商店：工票+币解锁冲级「研发配方」",
                target="研发配方",
                allowed=can_recipe,
                priority=20,
                reason="解锁高星黑月高效货配方（非直接卖货，专供冲级交黑月单）。",
                blocked_reason="" if can_recipe else f"工票或可用资金不足（当前工票 {tickets:,}）。",
            ),
        )

    for rank, (item_name, unit_cost, purpose) in enumerate(
        (
            ("拉普拉斯协议", 8000, "一次性限购抽卡协议（2+3+5），性价比极高"),
            ("自观测胶卷", 4000, "一次性限购装备强化耗材（限购 30）"),
        )
    ):
        can_buy_ticket = tickets >= unit_cost
        short = max(0, unit_cost - tickets)
        step = PrisonActionStep(
            category="buy",
            action_type="exchange_ticket_buy",
            title=f"工票兑换「{item_name}」（{unit_cost:,} 工票/份）",
            target=item_name,
            allowed=can_buy_ticket,
            priority=30 + rank,
            estimated_tickets=unit_cost,
            reason=purpose,
            blocked_reason="" if can_buy_ticket else f"工票不足：当前 {tickets:,}，还差 {short:,} 工票。",
        )
        _append_step(buy_actions, blocked_actions, step)

    for bad_name, bad_curr, bad_reason in (
        ("逮捕令", "work_tickets", "攻略避坑：可再生低性价比项，绝对不用工票换。"),
        ("超级帮帮券", "work_tickets", "攻略避坑：可再生低性价比项，绝对不用工票换。"),
        ("超级帮帮券（10 桦石）", "huashi", "零桦石护栏：兑换商店并列 10 桦石陷阱，严禁触碰。"),
    ):
        blocked_actions.append(
            PrisonActionStep(
                category="buy",
                action_type="guarded_skip",
                title=f"禁止兑换「{bad_name}」",
                target=bad_name,
                allowed=False,
                priority=92,
                estimated_huashi=10 if bad_curr == "huashi" else 0,
                blocked_reason=bad_reason,
            )
        )

    # 原料采购站转换核对
    for rank, pd in enumerate(prison_report.purchase_decisions):
        pair_label = f"{pd.from_item} → {pd.to_item}"
        if pd.action == "accept":
            buy_actions.append(
                PrisonActionStep(
                    category="buy",
                    action_type="purchase_convert",
                    title=f"原料采购站点击转换：{pair_label}",
                    target=pair_label,
                    allowed=True,
                    priority=25 + rank,
                    reason=pd.reason,
                )
            )
        else:
            blocked_actions.append(
                PrisonActionStep(
                    category="buy",
                    action_type="guarded_skip",
                    title=f"拦截高危采购转换：{pair_label}",
                    target=pair_label,
                    allowed=False,
                    priority=91,
                    blocked_reason=pd.reason,
                )
            )

    return PrisonExecutionPlan(
        uid=prison_report.uid,
        phase=prison_report.phase,
        prison_level=prison_report.prison_level,
        coins_before=int(snapshot.wallet.coins),
        reserve_coins=reserve,
        simulated_coins_after=sim_coins,
        do_actions=do_actions,
        buy_actions=buy_actions,
        build_actions=build_actions,
        blocked_actions=blocked_actions,
    )


def build_semi_auto_guidance(
    snapshot: AccountSnapshot,
    prison_report: PrisonPlanReport,
    execution_plan: Optional[PrisonExecutionPlan] = None,
    run_receipt: Optional[PrisonRunReceipt] = None,
    *,
    strategy_catalog: Optional[dict[str, Any]] = None,
) -> List[SemiAutoGuideItem]:
    """根据账号实况与本次执行回执，仅针对外部抓囚、LV9锚点、桦石护栏或真实兜底项生成半自动指引。"""
    strategy = strategy_catalog if isinstance(strategy_catalog, dict) else load_prison_strategy_catalog()
    thresholds = strategy.get("thresholds") if isinstance(strategy.get("thresholds"), dict) else {}

    prison = snapshot.prison
    prisoner_gap = max(0, int(prison.prisoners_capacity) - int(prison.prisoners_current))
    skipped = list(run_receipt.skipped) if run_receipt is not None else []
    guard_aborts = list(run_receipt.guard_aborts) if run_receipt is not None else []
    _ = execution_plan

    guides: List[SemiAutoGuideItem] = []

    # 1. 仅在狱内配员后仍真缺囚犯/缺材料或总囚犯工位明显不满时，指引外部消耗澄明度抓囚（绝不擅自扣体力）
    prod_skips = [
        o
        for o in skipped
        if o.action_type in ("produce_good", "raw_start_production")
    ]
    truly_no_idle = any(
        any(kw in o.detail for kw in ("请先选择生产人员", "空闲", "暂无空闲"))
        for o in prod_skips
    )
    lack_materials = any("原料不足" in o.detail for o in prod_skips)
    if prisoner_gap >= 4 or truly_no_idle or lack_materials:
        reasons: list[str] = []
        if prisoner_gap >= 4:
            reasons.append(f"当前在监囚犯 {prison.prisoners_current}/{prison.prisoners_capacity}（尚缺 {prisoner_gap} 个工位）")
        if truly_no_idle:
            reasons.append("自动配员后已无剩余空闲囚犯可供额外上工")
        if lack_materials:
            reasons.append("白名单配方所需基础原料暂无足够存量，需待原料车间产出累积")

        farm_tips = [t for t in prison_report.prisoner_farming_recommendations if not str(t).startswith("当前在监")]
        steps: list[str] = [
            "狱内「办理入住」、原料/生产车间配员与设组长已由脚本自动接管，无需回整顿中心手工调整。",
        ]
        if farm_tips:
            steps.append(f"若要加快扩编，请在整顿中心外使用澄明度/扫荡刷本抓囚：{'；'.join(farm_tips[:2])}。")
        else:
            steps.append("可在外部刷每日材料本或活动本补抓囚犯后再跑一趟，脚本会自动办理入住并上工。")

        guides.append(
            SemiAutoGuideItem(
                priority="urgent",
                category="prisoners",
                title=(
                    f"外部补抓囚犯以填满工位（在监 {prison.prisoners_current}/{prison.prisoners_capacity}）"
                    if (prisoner_gap >= 4 or truly_no_idle)
                    else "原料累积中：可顺路外出补抓囚犯加速产出"
                ),
                why_manual="；".join(reasons) + "。刷副本抓人会消耗外部澄明度（体力），脚本不擅自替你扣除体力。",
                steps=steps,
            )
        )

    # 2. 整顿 LV9+「转运中心」一次性绑定城市锚点
    transfer_unlock = int(thresholds.get("transfer_center_unlock_level") or 9)
    desired_anchors = [str(c) for c in (thresholds.get("recommended_transfer_anchors") or ["海角城", "岚心城"])]
    missing_anchors = [c for c in desired_anchors if c not in (prison.transfer_anchors or ())]
    if int(prison.level) >= transfer_unlock and missing_anchors:
        guides.append(
            SemiAutoGuideItem(
                priority="recommended",
                category="setup",
                title=f"转运中心绑定城市锚点：{' / '.join(desired_anchors)}",
                why_manual="城市锚点选择需一次性下拉绑定，人工设好后即长期生效，供带囚犯与毕业高价出货。",
                steps=[
                    f"进总览右翼「转运中心」，绑定推荐锚点城市：{' / '.join(desired_anchors)}（当前缺 {'、'.join(missing_anchors)}）。",
                ],
            )
        )

    # 3. 仅当本次实机运行真出现未完成兜底（failed / building_unlock / order_delete_free 跳过）时才生成兜底指引
    if run_receipt is not None:
        failed_outcomes = [o for o in skipped if o.status == "failed"]
        unlock_fallbacks = [
            o for o in skipped if o.action_type == "building_unlock"
        ]
        order_del_fallbacks = [
            o for o in skipped if o.action_type == "order_delete_free"
        ]
        if unlock_fallbacks:
            targets = "、".join(dict.fromkeys(o.target for o in unlock_fallbacks))
            guides.append(
                SemiAutoGuideItem(
                    priority="recommended",
                    category="unlock",
                    title=f"自动首建未完成兜底：{targets}",
                    why_manual=f"脚本尝试自动首建「{targets}」时未确认完成（{unlock_fallbacks[0].detail}）。",
                    steps=[
                        f"进整顿中心总览找到「{targets}」→ 点『建设』→ 确认建造 LV1。",
                    ],
                )
            )
        if order_del_fallbacks:
            targets = "、".join(dict.fromkeys(o.target for o in order_del_fallbacks))
            guides.append(
                SemiAutoGuideItem(
                    priority="recommended",
                    category="orders",
                    title=f"免费删单未完成兜底：{targets}",
                    why_manual=f"尝试删除卡仓黑月订单「{targets}」时未确认生效（{order_del_fallbacks[0].detail}）。",
                    steps=[
                        f"点底栏『订单站』→『运输订单』→ 切换到「{targets}」并点左下垃圾桶确认删除。",
                    ],
                )
            )
        if failed_outcomes:
            summary = "、".join(dict.fromkeys(f"{o.target}({o.detail})" for o in failed_outcomes[:2]))
            guides.append(
                SemiAutoGuideItem(
                    priority="recommended",
                    category="setup",
                    title="部分自动步骤执行异常，建议复核",
                    why_manual=f"本次运行捕获到异常阶段：{summary}。",
                    steps=[
                        "可直接重跑一次整顿中心全自动任务，或按上述异常对象名检查对应游戏弹窗。",
                    ],
                )
            )

    # 4. 桦石护栏触发或低余电说明
    has_blocked_huashi = any(g.status == "blocked_by_guardrail" for g in prison_report.guarded_huashi_actions)
    if guard_aborts or (prison_report.phase == "rush_leveling" and int(prison_report.power_free) < 2000 and has_blocked_huashi):
        abort_desc = (
            f"本次护栏已拦截：{', '.join(g.target for g in guard_aborts)}"
            if guard_aborts
            else f"当前余电仅 {int(prison_report.power_free):,}，已屏蔽 3,500 桦石安装电机选项"
        )
        guides.append(
            SemiAutoGuideItem(
                priority="optional",
                category="huashi",
                title="桦石保护项处于拦截状态（电力电机 / 双仓桦石扩容）",
                why_manual=f"{abort_desc}；脚本默认严格零桦石保护，任何可能扣桦石页签均强制拦截不点。",
                steps=[
                    "若暂不想花桦石，直接忽略本条，继续靠自动升级「电力中心」稳步涨上限即可；",
                    "若确定按攻略投入桦石补电：请手动进入「电力中心 → 建设 → 顶部右侧『安装电机』页签」（合计约 3,500 桦石），或开启对应桦石放行开关。",
                ],
            )
        )

    priority_order = {"urgent": 0, "recommended": 1, "optional": 2}
    guides.sort(key=lambda item: priority_order.get(item.priority, 9))
    return guides
