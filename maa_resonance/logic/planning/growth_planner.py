from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from maa_resonance.logic.planning.account_snapshot import AccountSnapshot
from maa_resonance.logic.planning.catalogs import load_growth_stages_catalog

WEEKDAY_NAMES: tuple[str, ...] = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")


class GrowthPlanOptions(BaseModel):
    """乘员养成与抓囚犯协同规划参数。"""

    daily_clarity_budget: int = 240
    weekday: Optional[int] = None
    need_prisoners: Optional[bool] = None
    reserve_coins: int = 15_000_000
    prefer_sweepable_event: bool = True


class MaterialShortfall(BaseModel):
    """单种养成材料的总需求与当前缺口。"""

    name: str
    required: int
    owned: int
    shortfall: int


class CrewPlanItem(BaseModel):
    """单名目标乘员的练度差距与材料汇总。"""

    role_name: str
    priority: int = 1
    current_level: Optional[int] = None
    target_level: Optional[int] = None
    current_resonance: Optional[int] = None
    target_resonance: Optional[int] = None
    current_awakening: Optional[int] = None
    target_awakening: Optional[int] = None
    required_coins: int = 0
    material_shortfalls: List[MaterialShortfall] = Field(default_factory=list)
    notes: str = ""


class StageAllocation(BaseModel):
    """单日澄明度在各关卡的分配条目。"""

    stage_id: str
    stage_name: str
    category: str
    runs: int
    clarity_spent: int
    expected_prisoners: int
    sweepable: bool
    reason: str


class TicketRewardCrossCheck(BaseModel):
    """整顿中心工票商店对乘员养成的一次性可兑换资源核对。"""

    item_name: str
    unit_cost: int
    total_limit: int
    affordable_count: int
    tickets_short_for_one: int
    purpose: str


class GrowthPlanReport(BaseModel):
    """乘员养成缺口与澄明度协同规划报告。"""

    uid: str
    weekday: int
    weekday_name: str
    daily_clarity_budget: int
    clarity_remaining: int
    need_prisoners: bool
    coins_total: int
    spendable_coins: int
    total_required_coins: int
    coin_shortfall: int
    crew_plans: List[CrewPlanItem] = Field(default_factory=list)
    aggregated_material_shortfalls: List[MaterialShortfall] = Field(default_factory=list)
    stage_allocations: List[StageAllocation] = Field(default_factory=list)
    expected_total_prisoners: int = 0
    ticket_reward_checks: List[TicketRewardCrossCheck] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)


def _resolve_weekday(raw_weekday: Optional[int]) -> int:
    if raw_weekday is None:
        return datetime.now().weekday()
    return int(raw_weekday) % 7


def _infer_need_prisoners(snapshot: AccountSnapshot, explicit: Optional[bool]) -> bool:
    if explicit is not None:
        return bool(explicit)
    prison = snapshot.prison
    if prison.level <= 0:
        return False
    if prison.prisoners_capacity <= 0:
        return True
    return prison.prisoners_current < prison.prisoners_capacity


def _append_allocation(
    allocations: List[StageAllocation],
    stage: dict[str, Any],
    runs: int,
    reason: str,
) -> int:
    if runs <= 0:
        return 0
    cost = int(stage.get("clarity_cost") or 0)
    spent = runs * cost
    prisoners = runs * int(stage.get("prisoners") or 0)
    allocations.append(
        StageAllocation(
            stage_id=str(stage.get("id") or ""),
            stage_name=str(stage.get("name") or ""),
            category=str(stage.get("category") or ""),
            runs=runs,
            clarity_spent=spent,
            expected_prisoners=prisoners,
            sweepable=bool(stage.get("sweepable", False)),
            reason=reason,
        )
    )
    return spent


def _allocate_daily_stages(
    *,
    budget: int,
    weekday: int,
    need_prisoners: bool,
    has_resonance_or_material_need: bool,
    prefer_sweepable_event: bool,
    growth_catalog: dict[str, Any],
) -> tuple[List[StageAllocation], int]:
    stages = growth_catalog.get("stages") if isinstance(growth_catalog.get("stages"), list) else []
    by_id = {str(s.get("id") or ""): s for s in stages if isinstance(s, dict)}
    remaining = max(0, int(budget))
    allocations: List[StageAllocation] = []

    # 1. 周一/周三/周日：双倍装备声望+胶卷+最高效抓囚犯本（特供·制式 / 特供·雅致）
    equip_today = [
        s
        for s in stages
        if isinstance(s, dict)
        and s.get("category") == "equip_daily"
        and bool(s.get("double_rep", False))
        and weekday in (s.get("weekdays") or [])
    ]
    equip_today.sort(key=lambda item: int(item.get("recommended_priority") or 99))
    for eq in equip_today:
        cost = int(eq.get("clarity_cost") or 40)
        if remaining >= cost:
            remaining -= _append_allocation(
                allocations,
                eq,
                1,
                f"当日声望双倍 + 掉落胶卷，兼具 {eq.get('prisoners', 0)} 名囚犯抓取收益。",
            )

    # 2. 共振材料缺口：优先安排 利刃围剿（日限 3 次）
    liren = by_id.get("material_liren")
    if has_resonance_or_material_need and isinstance(liren, dict):
        cost = int(liren.get("clarity_cost") or 40)
        limit = int(liren.get("daily_limit") or 3)
        runs = min(limit, remaining // cost) if cost > 0 else 0
        if runs > 0:
            remaining -= _append_allocation(
                allocations,
                liren,
                runs,
                f"优先补齐乘员共振材料（每日限 {limit} 次），同时附带抓 {runs * int(liren.get('prisoners') or 0)} 名囚犯。",
            )

    # 3. 每日材料双倍本首选：挑灯看剑
    tiaodeng = by_id.get("material_tiaodeng")
    if isinstance(tiaodeng, dict):
        cost = int(tiaodeng.get("clarity_cost") or 40)
        if remaining >= cost:
            # 当不需要补囚犯且周内没有特供日时，可多刷 1 次挑灯看剑；需要抓囚犯时留足活动低体本预算
            tiaodeng_runs = 2 if (not need_prisoners and not equip_today and remaining >= 2 * cost) else 1
            if need_prisoners and remaining >= 3 * cost and not equip_today:
                tiaodeng_runs = 2
            remaining -= _append_allocation(
                allocations,
                tiaodeng,
                tiaodeng_runs,
                "每日材料本声望双倍首选（每场 40 体力附带 8 名囚犯，效率居材料本首位）。",
            )

    # 4. 补囚犯低体活动本：乐园·浅层1（可扫荡） vs 海岛 SP4（高囚犯品质 + 海岛发育）
    if need_prisoners:
        preferred_id = "event_leyuan_shallow1" if prefer_sweepable_event else "event_haidao_sp4"
        event_stage = by_id.get(preferred_id)
        if isinstance(event_stage, dict):
            cost = int(event_stage.get("clarity_cost") or 20)
            runs = remaining // cost if cost > 0 else 0
            if runs > 0:
                note = (
                    "20 体 15 囚犯且支持扫荡，澄明度/时间效率最优。"
                    if prefer_sweepable_event
                    else "20 体 15 囚犯，虽不可扫荡但囚犯品质更高且辅助海岛发育。"
                )
                remaining -= _append_allocation(allocations, event_stage, runs, note)

    # 5. 若仍有剩余且未刷囚犯，转日常装备本 私贩追缴
    if not need_prisoners and not equip_today:
        sifan = by_id.get("equip_sifan")
        if isinstance(sifan, dict):
            cost = int(sifan.get("clarity_cost") or 40)
            runs = remaining // cost if cost > 0 else 0
            if runs > 0:
                remaining -= _append_allocation(allocations, sifan, runs, "无抓囚犯需求时用剩余体力补充队员常规装备。")

    return allocations, remaining


def plan_growth(
    snapshot: AccountSnapshot,
    options: Optional[GrowthPlanOptions] = None,
    *,
    growth_catalog: Optional[dict[str, Any]] = None,
) -> GrowthPlanReport:
    """根据统一账号快照与行动汇总目录输出乘员养成缺口与抓囚犯协同规划。"""
    opts = options or GrowthPlanOptions()
    catalog = growth_catalog if isinstance(growth_catalog, dict) else load_growth_stages_catalog()
    weekday = _resolve_weekday(opts.weekday)
    need_prisoners = _infer_need_prisoners(snapshot, opts.need_prisoners)
    spendable_coins = max(0, int(snapshot.wallet.coins) - int(opts.reserve_coins))

    crew_plans: List[CrewPlanItem] = []
    total_material_req: Dict[str, int] = {}
    total_required_coins = 0
    has_resonance_or_material_need = False

    for role_name, entry in snapshot.crew_progression.items():
        current_resonance = snapshot.effective_role_resonance(role_name)
        goal = entry.target_goal
        if goal is None:
            continue
        if goal.target_resonance is not None and (current_resonance is None or current_resonance < goal.target_resonance):
            has_resonance_or_material_need = True
        if goal.required_materials:
            has_resonance_or_material_need = True

        total_required_coins += max(0, int(goal.required_coins))
        shortfalls: List[MaterialShortfall] = []
        for mat_name, req_qty in goal.required_materials.items():
            req = max(0, int(req_qty))
            if req <= 0:
                continue
            owned = int(snapshot.materials_inventory.get(mat_name).owned) if mat_name in snapshot.materials_inventory else 0
            shortfall = max(0, req - owned)
            shortfalls.append(
                MaterialShortfall(
                    name=mat_name,
                    required=req,
                    owned=owned,
                    shortfall=shortfall,
                )
            )
            total_material_req[mat_name] = total_material_req.get(mat_name, 0) + req

        crew_plans.append(
            CrewPlanItem(
                role_name=role_name,
                priority=goal.priority,
                current_level=entry.level,
                target_level=goal.target_level,
                current_resonance=current_resonance,
                target_resonance=goal.target_resonance,
                current_awakening=entry.awakening,
                target_awakening=goal.target_awakening,
                required_coins=max(0, int(goal.required_coins)),
                material_shortfalls=shortfalls,
                notes=goal.notes,
            )
        )

    crew_plans.sort(key=lambda item: (item.priority, item.role_name))

    aggregated_shortfalls: List[MaterialShortfall] = []
    for mat_name, total_req in sorted(total_material_req.items()):
        owned = int(snapshot.materials_inventory.get(mat_name).owned) if mat_name in snapshot.materials_inventory else 0
        aggregated_shortfalls.append(
            MaterialShortfall(
                name=mat_name,
                required=total_req,
                owned=owned,
                shortfall=max(0, total_req - owned),
            )
        )

    # 若未填写任何目标乘员，仍保持日常共振/材料兼顾模板但给出明确提示
    warnings: List[str] = []
    if not crew_plans:
        has_resonance_or_material_need = True
        warnings.append("账号快照尚未设置具体乘员养成目标（crew_progression.target_goal），当前按「常规共振材料 + 囚犯协同」默认模板排程。")

    coin_shortfall = max(0, total_required_coins - spendable_coins)
    if total_required_coins > spendable_coins:
        warnings.append(
            f"目标养成预计需消耗 {total_required_coins:,} 铁盟币，超出保留地板后的可支配预算 {spendable_coins:,}（缺口 {coin_shortfall:,}）。"
        )

    allocations, clarity_remaining = _allocate_daily_stages(
        budget=opts.daily_clarity_budget,
        weekday=weekday,
        need_prisoners=need_prisoners,
        has_resonance_or_material_need=has_resonance_or_material_need,
        prefer_sweepable_event=opts.prefer_sweepable_event,
        growth_catalog=catalog,
    )
    expected_total_prisoners = sum(a.expected_prisoners for a in allocations)

    tickets = max(0, int(snapshot.prison.work_tickets))
    ticket_checks: List[TicketRewardCrossCheck] = []
    for reward in catalog.get("prison_ticket_growth_rewards") or []:
        if not isinstance(reward, dict):
            continue
        unit_cost = int(reward.get("unit_cost") or 0)
        total_limit = int(reward.get("total_limit") or 0)
        if unit_cost <= 0:
            continue
        affordable = min(total_limit, tickets // unit_cost) if total_limit > 0 else (tickets // unit_cost)
        short_for_one = 0 if tickets >= unit_cost else (unit_cost - tickets)
        ticket_checks.append(
            TicketRewardCrossCheck(
                item_name=str(reward.get("name") or ""),
                unit_cost=unit_cost,
                total_limit=total_limit,
                affordable_count=affordable,
                tickets_short_for_one=short_for_one,
                purpose=str(reward.get("purpose") or ""),
            )
        )

    return GrowthPlanReport(
        uid=snapshot.uid,
        weekday=weekday,
        weekday_name=WEEKDAY_NAMES[weekday],
        daily_clarity_budget=opts.daily_clarity_budget,
        clarity_remaining=clarity_remaining,
        need_prisoners=need_prisoners,
        coins_total=snapshot.wallet.coins,
        spendable_coins=spendable_coins,
        total_required_coins=total_required_coins,
        coin_shortfall=coin_shortfall,
        crew_plans=crew_plans,
        aggregated_material_shortfalls=aggregated_shortfalls,
        stage_allocations=allocations,
        expected_total_prisoners=expected_total_prisoners,
        ticket_reward_checks=ticket_checks,
        warnings=warnings,
    )


def format_growth_plan_markdown(report: GrowthPlanReport) -> str:
    """将乘员养成规划报告渲染为简洁中文 Markdown。"""
    lines = [
        f"## 乘员养成与体力协同规划报告（UID `{report.uid}` · {report.weekday_name}）",
        "",
        f"- **每日澄明度预算**：`{report.daily_clarity_budget}`（本次分配 `{report.daily_clarity_budget - report.clarity_remaining}`，剩余 `{report.clarity_remaining}`）",
        f"- **监狱囚犯协同**：`{'开启(需补囚犯)' if report.need_prisoners else '关闭'}`（预计顺带获取囚犯 `{report.expected_total_prisoners}` 名）",
        f"- **资金核对**：持有 `{report.coins_total:,}` 币｜可支配 `{report.spendable_coins:,}` 币｜目标总需 `{report.total_required_coins:,}` 币"
        + (f"（缺口 `{report.coin_shortfall:,}` 币）" if report.coin_shortfall > 0 else "（充足）"),
    ]
    if report.warnings:
        lines.extend(["", "### 提示"])
        for w in report.warnings:
            lines.append(f"- {w}")

    if report.crew_plans:
        lines.extend(["", "### 目标乘员练度差距"])
        for cp in report.crew_plans:
            res_str = f"共振 {cp.current_resonance if cp.current_resonance is not None else '?'}→{cp.target_resonance if cp.target_resonance is not None else '-'}"
            lv_str = f"等级 {cp.current_level if cp.current_level is not None else '?'}→{cp.target_level if cp.target_level is not None else '-'}"
            missing = [f"{m.name} 缺 {m.shortfall}（{m.owned}/{m.required}）" for m in cp.material_shortfalls if m.shortfall > 0]
            missing_text = "、".join(missing) if missing else "材料已齐"
            lines.append(f"- **{cp.role_name}**（优先级 {cp.priority}｜{lv_str}｜{res_str}）：需币 `{cp.required_coins:,}`；{missing_text}")

    if report.aggregated_material_shortfalls:
        lines.extend(["", "### 材料总缺口汇总"])
        for mat in report.aggregated_material_shortfalls:
            lines.append(f"- **{mat.name}**：拥有 `{mat.owned}` / 总需 `{mat.required}` → 缺口 `{mat.shortfall}`")

    lines.extend(["", f"### {report.weekday_name} 行动汇总 / 活动协同刷本分配"])
    for alloc in report.stage_allocations:
        sweep_tag = "可扫荡" if alloc.sweepable else "需手打/自律"
        lines.append(
            f"- **{alloc.stage_name}** ×{alloc.runs} 场（耗体 `{alloc.clarity_spent}`，+{alloc.expected_prisoners} 囚犯，{sweep_tag}）—— {alloc.reason}"
        )

    if report.ticket_reward_checks:
        lines.extend(["", "### 整顿中心工票可联动养成奖励"])
        for tr in report.ticket_reward_checks:
            if tr.affordable_count > 0:
                status = f"当前工票可换 `{tr.affordable_count}` 份（上限 {tr.total_limit}，单价 `{tr.unit_cost:,}`）"
            else:
                status = f"差 `{tr.tickets_short_for_one:,}` 工票可换 1 份（单价 `{tr.unit_cost:,}`）"
            lines.append(f"- **{tr.item_name}**：{status} —— {tr.purpose}")

    return "\n".join(lines)
