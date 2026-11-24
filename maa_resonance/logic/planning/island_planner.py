"""海岛（蜃息岛）纯 Python 阶段规划引擎：计算 7 维 3 天逗留差额、识别建设/过渡/毕业常驻阶段并输出执行建议。"""
from __future__ import annotations

import math
from typing import Any, Literal, Mapping, Optional, Sequence

from pydantic import BaseModel, Field

from maa_resonance.logic.planning.account_snapshot import AccountSnapshot, IslandSnapshot
from maa_resonance.logic.planning.catalogs import load_island_strategy_catalog

IslandStage = Literal["construction", "transition", "graduated_daily"]


class IslandPlanOptions(BaseModel):
    """海岛规划计算选项。"""

    reserve_coins: int = 15_000_000
    prefer_fish_farming: bool = False


class IslandStayDimension(BaseModel):
    """海岛 7 维属性中单维的当前得分与逗留天数拆解。"""

    dim_id: str
    name: str
    score: int = 0
    step_points: int = 3000
    full_target: int = 15000
    bonus_days: float = 0.0
    max_bonus_days: float = 0.5
    points_to_next_step: int = 0
    points_to_full: int = 0


class IslandStayBreakdown(BaseModel):
    """海岛游客平均游玩天数（逗留天数）公式核算结果。"""

    base_days: float = 1.0
    raw_bonus_days: float = 0.0
    effective_bonus_days: float = 0.0
    estimated_stay_days: float = 1.0
    max_total_days: float = 3.0
    dimensions: list[IslandStayDimension] = Field(default_factory=list)


class IslandRecommendation(BaseModel):
    """海岛单条规划建议（日常 / 建设 / 毕业常驻 / 风险预警）。"""

    category: Literal["daily", "construction", "graduated_daily", "warning"]
    priority: Literal["blocker", "high", "medium", "optional", "warning"]
    title: str
    reason: str
    estimated_coins: int = 0
    estimated_tickets: int = 0


class IslandActionOutcome(BaseModel):
    """单次自动海岛操作执行结果条目。"""

    stage: str
    action_type: str
    target: str
    status: Literal["executed", "skipped", "aborted", "failed"]
    detail: str = ""


class IslandRunReceipt(BaseModel):
    """单趟海岛自动执行全量回执。"""

    exec_mode: str = "plan_only"
    auto_scope: str = "daily_fast"
    coins_before: int = 0
    coins_after: int = 0
    tickets_before: int = 0
    tickets_after: int = 0
    shells_before: int = 0
    shells_after: int = 0
    revenue_claimed_coins: int = 0
    trash_blocks_collected: int = 0
    own_monsters_cleared: int = 0
    todo_rewards_claimed: int = 0
    friend_visits: int = 0
    friend_trash_cleaned: int = 0
    friend_likes_sent: int = 0
    friend_monsters_helped: int = 0
    invest_executed_count: int = 0
    invest_spent_coins: int = 0
    islands_expanded: int = 0
    expand_spent_coins: int = 0
    expand_spent_tickets: int = 0
    executed: list[IslandActionOutcome] = Field(default_factory=list)
    skipped: list[IslandActionOutcome] = Field(default_factory=list)
    guard_aborts: list[IslandActionOutcome] = Field(default_factory=list)


class IslandPlanReport(BaseModel):
    """海岛体检、阶段判断与后续规划全量输出对象。"""

    uid: str = "unknown"
    stage: IslandStage = "construction"
    stage_label: str = "开荒建设期"
    island_level: int = 0
    unlocked_islands: int = 1
    cabin_level: int = 0
    trash_station_level: int = 1
    stability_current: int = 0
    stability_max: int = 200
    active_monsters: int = 0
    cleanliness_pct: int = 100
    trash_rate_per_hour: int = 0
    trash_blocks_stored: int = 0
    trash_blocks_cap: int = 0
    visitors_current: int = 0
    visitors_capacity: int = 0
    reported_stay_days: float = 1.0
    stay_breakdown: IslandStayBreakdown = Field(default_factory=IslandStayBreakdown)
    share_ratio_pct: float = 3.0
    ticket_price: int = 500
    tax_rate_pct: float = 5.0
    invested_total: int = 0
    invest_remaining: int = 0
    pending_revenue_coins: int = 0
    today_revenue_coins: int = 0
    material_tickets: int = 0
    shell_coins: int = 0
    volleyball_coins: int = 0
    coins_total: int = 0
    reserve_coins: int = 15_000_000
    spendable_coins: int = 0
    daily_actions: list[IslandRecommendation] = Field(default_factory=list)
    construction_milestones: list[IslandRecommendation] = Field(default_factory=list)
    graduated_checklist: list[IslandRecommendation] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


_DEFAULT_DIMENSIONS: tuple[dict[str, Any], ...] = (
    {"id": "comfort", "name": "舒适", "step_points": 6000, "step_days": 0.1, "max_bonus_days": 0.5, "full_score_target": 30000},
    {"id": "greenery", "name": "绿植", "step_points": 3000, "step_days": 0.1, "max_bonus_days": 0.5, "full_score_target": 15000},
    {"id": "food", "name": "美食", "step_points": 3000, "step_days": 0.1, "max_bonus_days": 0.5, "full_score_target": 15000},
    {"id": "entertainment", "name": "娱乐", "step_points": 3000, "step_days": 0.1, "max_bonus_days": 0.5, "full_score_target": 15000},
    {"id": "medical", "name": "医疗", "step_points": 3000, "step_days": 0.1, "max_bonus_days": 0.5, "full_score_target": 15000},
    {"id": "pet", "name": "宠物", "step_points": 3000, "step_days": 0.1, "max_bonus_days": 0.5, "full_score_target": 15000},
    {"id": "aquarium", "name": "水族", "step_points": 3000, "step_days": 0.1, "max_bonus_days": 0.5, "full_score_target": 15000},
)


def compute_stay_days_breakdown(
    scores: Mapping[str, int] | None,
    catalog: Optional[dict[str, Any]] = None,
) -> IslandStayBreakdown:
    """根据 7 维评分计算游玩天数拆解与每维距离满加成的差值。"""
    cat = catalog if isinstance(catalog, dict) else load_island_strategy_catalog()
    dims_cfg = cat.get("stay_dimensions") or _DEFAULT_DIMENSIONS
    formula_cfg = cat.get("stay_formula") if isinstance(cat.get("stay_formula"), Mapping) else {}
    base_days = float(formula_cfg.get("base_days", 1.0) or 1.0)
    max_bonus = float(formula_cfg.get("max_bonus_days", 2.0) or 2.0)
    max_total = float(formula_cfg.get("max_total_days", 3.0) or 3.0)

    raw_scores = scores if isinstance(scores, Mapping) else {}
    dim_models: list[IslandStayDimension] = []
    raw_bonus_sum = 0.0

    for entry in dims_cfg:
        if not isinstance(entry, Mapping):
            continue
        dim_id = str(entry.get("id") or "").strip()
        dim_name = str(entry.get("name") or dim_id).strip()
        step_pts = max(1, int(entry.get("step_points", 3000) or 3000))
        step_days = float(entry.get("step_days", 0.1) or 0.1)
        dim_max_bonus = float(entry.get("max_bonus_days", 0.5) or 0.5)
        full_target = int(entry.get("full_score_target", step_pts * 5) or (step_pts * 5))

        score_val = max(0, int(raw_scores.get(dim_name) or raw_scores.get(dim_id) or 0))
        steps_reached = min(int(round(dim_max_bonus / step_days)), score_val // step_pts)
        bonus_days = round(min(dim_max_bonus, steps_reached * step_days), 2)
        raw_bonus_sum += bonus_days

        if bonus_days >= dim_max_bonus - 1e-6:
            pts_next = 0
        else:
            next_step_score = (steps_reached + 1) * step_pts
            pts_next = max(0, next_step_score - score_val)
        pts_full = max(0, full_target - score_val)

        dim_models.append(
            IslandStayDimension(
                dim_id=dim_id,
                name=dim_name,
                score=score_val,
                step_points=step_pts,
                full_target=full_target,
                bonus_days=bonus_days,
                max_bonus_days=dim_max_bonus,
                points_to_next_step=pts_next,
                points_to_full=pts_full,
            )
        )

    effective_bonus = round(min(max_bonus, raw_bonus_sum), 2)
    est_days = round(min(max_total, base_days + effective_bonus), 2)
    return IslandStayBreakdown(
        base_days=base_days,
        raw_bonus_days=round(raw_bonus_sum, 2),
        effective_bonus_days=effective_bonus,
        estimated_stay_days=est_days,
        max_total_days=max_total,
        dimensions=dim_models,
    )


def _is_investment_maxed(island: IslandSnapshot, targets: Mapping[str, Any]) -> bool:
    share_target = float(targets.get("share_ratio_pct", 35.0) or 35.0)
    ticket_target = int(targets.get("ticket_price", 2000) or 2000)
    tax_target = float(targets.get("tax_rate_pct", 0.0) or 0.0)
    return (
        float(island.share_ratio_pct) >= share_target - 0.05
        and int(island.ticket_price) >= ticket_target
        and float(island.tax_rate_pct) <= tax_target + 0.05
    )


def classify_island_stage(
    island: IslandSnapshot,
    stay_breakdown: IslandStayBreakdown,
    catalog: Optional[dict[str, Any]] = None,
) -> tuple[IslandStage, str]:
    """区分开荒建设期 / 冲毕业过渡期 / 毕业常驻日常期。"""
    cat = catalog if isinstance(catalog, dict) else load_island_strategy_catalog()
    targets = cat.get("graduation_targets") if isinstance(cat.get("graduation_targets"), Mapping) else {}
    target_islands = int(targets.get("unlocked_islands", 6) or 6)
    target_cabin = int(targets.get("cabin_level", 6) or 6)
    target_stability = int(targets.get("stability_max", 200) or 200)
    target_stay = float(targets.get("avg_stay_days", 3.0) or 3.0)

    stay_ok = max(float(island.avg_stay_days), float(stay_breakdown.estimated_stay_days)) >= target_stay - 0.05
    invest_ok = _is_investment_maxed(island, targets)
    if (
        island.graduated
        or (
            int(island.unlocked_islands) >= target_islands
            and int(island.cabin_level) >= target_cabin
            and int(island.stability_current) >= target_stability
            and stay_ok
            and invest_ok
        )
    ):
        return "graduated_daily", "毕业常驻日常期（零消耗极简收菜）"

    if int(island.cabin_level) >= target_cabin and int(island.unlocked_islands) >= 4:
        return "transition", "冲毕业过渡期（补全评分/投资/200波）"

    return "construction", "开荒建设期（扩岛/升木屋/清200波怪）"


def plan_island(
    snapshot: AccountSnapshot,
    options: Optional[IslandPlanOptions] = None,
    *,
    catalog: Optional[dict[str, Any]] = None,
) -> IslandPlanReport:
    """结合账号快照输出当前海岛阶段判断、日常执行项、建设里程碑与防坑提示。"""
    opts = options or IslandPlanOptions()
    cat = catalog if isinstance(catalog, dict) else load_island_strategy_catalog()
    targets = cat.get("graduation_targets") if isinstance(cat.get("graduation_targets"), Mapping) else {}
    island = snapshot.island
    stay_bd = compute_stay_days_breakdown(island.scores, cat)
    stage, stage_label = classify_island_stage(island, stay_bd, cat)

    coins_total = max(0, int(snapshot.wallet.coins))
    reserve = max(0, int(opts.reserve_coins))
    spendable = max(0, coins_total - reserve)

    daily_actions: list[IslandRecommendation] = []
    construction_milestones: list[IslandRecommendation] = []
    graduated_checklist: list[IslandRecommendation] = []
    warnings: list[str] = []

    # 1. 日常零风险动作（过渡期与毕业期共用）
    if island.pending_revenue_coins > 0:
        daily_actions.append(
            IslandRecommendation(
                category="daily",
                priority="high",
                title=f"收取营运收益（待领 {island.pending_revenue_coins:,} 铁盟币）",
                reason="管理中心 -> 营运收益 -> 收钱，远程可领、零风险无消耗。",
            )
        )
    else:
        daily_actions.append(
            IslandRecommendation(
                category="daily",
                priority="optional",
                title="检查并收取营运收益",
                reason="当前待领为 0 或未刷新；日常运行顺路核验营运概览。",
            )
        )

    if island.trash_blocks_stored > 0 or island.cleanliness_pct < 100 or island.trash_pending_raw >= 100:
        over_cap = island.trash_blocks_cap > 0 and island.trash_blocks_stored > island.trash_blocks_cap
        daily_actions.append(
            IslandRecommendation(
                category="daily",
                priority="blocker" if over_cap else "high",
                title=f"一键收取海岛垃圾块（{island.trash_blocks_stored}/{max(1, island.trash_blocks_cap)}）",
                reason="点底栏扫帚进垃圾站后仅点右下角【一键收取】（直接收进火车暂存区），严禁点左侧一键处理；超48小时会降清洁度。",
            )
        )

    if island.stability_current < island.stability_max or island.active_monsters > 0:
        rem = max(0, island.stability_max - island.stability_current)
        daily_actions.append(
            IslandRecommendation(
                category="daily",
                priority="high",
                title=f"0体力清理岛上红感叹号野怪（当前×{island.active_monsters}，稳定 {island.stability_current}/{island.stability_max}）",
                reason=f"海岛累计固定 {island.stability_max} 波野怪，0 澄明度消耗；尚余约 {rem} 波，打完后永久停刷且消除48h收益下降惩罚。",
            )
        )

    daily_actions.append(
        IslandRecommendation(
            category="daily",
            priority="high",
            title="领取「事项一览」已完成任务奖励",
            reason="推动海岛等级与资材券/贝币回血；脚本严格拒点未完成行的【追踪】。",
        )
    )

    daily_actions.append(
        IslandRecommendation(
            category="daily",
            priority="medium",
            title="好友海岛「清扫」偷垃圾（每日 3 次）+ 顺手点赞",
            reason="2025.04.09 更新后每日上限 3 次（05:00 刷新），偷得垃圾块直入火车暂存区供荒原变现；可顺路按治安标签 0 体力蹭怪抓囚犯。",
        )
    )

    # 2. 一次性建设里程碑（未毕业前提示）
    if island.unlocked_islands < int(targets.get("unlocked_islands", 6) or 6):
        next_island = island.unlocked_islands + 1
        construction_milestones.append(
            IslandRecommendation(
                category="construction",
                priority="high",
                title=f"扩建解锁第 0{next_island} 岛（当前 {island.unlocked_islands}/6 岛）",
                reason="扩建后提供更多鱼缸与绿植/设施面积，建议对照底线在海岛主界面点击【扩建】按序开启。",
                estimated_coins=600_000 if next_island == 2 else 0,
                estimated_tickets=6_000 if next_island == 2 else 0,
            )
        )

    if island.cabin_level < int(targets.get("cabin_level", 6) or 6):
        cabin_rows = {int(r["level"]): r for r in (cat.get("cabin_levels") or []) if isinstance(r, Mapping)}
        cur_row = cabin_rows.get(island.cabin_level) or {}
        next_coins = int(cur_row.get("upgrade_to_next_coins", 0) or 0)
        next_tickets = int(cur_row.get("upgrade_to_next_tickets", 0) or 0)
        construction_milestones.append(
            IslandRecommendation(
                category="construction",
                priority="high",
                title=f"推进海岛剧情并升满沙滩小屋（当前 LV{island.cabin_level} -> LV6）",
                reason="推进剧情与木屋等级以解锁 02~06 岛与高阶治安巡逻关卡。",
                estimated_coins=next_coins,
                estimated_tickets=next_tickets,
            )
        )

    if not _is_investment_maxed(island, targets):
        construction_milestones.append(
            IslandRecommendation(
                category="construction",
                priority="medium",
                title=(
                    f"海角城运营投资拉满（当前分成 {island.share_ratio_pct:.1f}%/35% · "
                    f"票价 {island.ticket_price}/2000 · 税率 {island.tax_rate_pct:.1f}%/0%）"
                ),
                reason=(
                    f"每趟列车驶入海角城刷新 1 次投资（当前余 {island.invest_remaining} 次），"
                    "全满约需 1,300~1,500 万币；建议跑商顺路投满，优先拉高分成与票价。"
                ),
            )
        )

    if stay_bd.estimated_stay_days < float(targets.get("avg_stay_days", 3.0) or 3.0) - 0.05:
        need_dims = [
            f"{d.name}(+{d.points_to_full:,}满)"
            for d in stay_bd.dimensions
            if d.points_to_full > 0
        ]
        construction_milestones.append(
            IslandRecommendation(
                category="construction",
                priority="medium",
                title=f"凑满 3.0 天游玩天数（当前估算 {stay_bd.estimated_stay_days:.1f} 天，实显 {island.avg_stay_days:.1f} 天）",
                reason="凑满相当于 4 维上限（舒适 30,000 / 其余单维 15,000）即可零宣传自然满客；差额维度："
                + ("、".join(need_dims[:5]) if need_dims else "按需补摆装饰"),
            )
        )

    if opts.prefer_fish_farming or island.unlocked_islands >= 4:
        construction_milestones.append(
            IslandRecommendation(
                category="construction",
                priority="optional",
                title="中后期「养鱼大户流」：装修商店海岛鱼缸 + 海角城水族馆每日买鱼",
                reason="4~6 岛后排种树、空位堆满海岛专属鱼缸并塞满海角城高分鱼，兼顾水族评分与高额海岛垃圾产率（注意区分于列车鱼缸）。",
            )
        )

    construction_milestones.append(
        IslandRecommendation(
            category="construction",
            priority="optional",
            title="海岛兑换处搬空顺序：喧闹摇滚 -> 祖父反应装甲 -> 拉普拉斯协议/胶卷/进货书",
            reason="贝币主要靠建设任务与治安巡逻（SP-4 兼顾抓紫囚犯 / SP-6~8 纯刷 1200 资材券），排球每日 3 把保底亦可攒币。",
        )
    )

    # 3. 毕业常驻 3 步闭环
    graduated_checklist.extend(
        [
            IslandRecommendation(
                category="graduated_daily",
                priority="high",
                title="1. 远程进海岛收钱（日均约 100 万铁盟币）",
                reason="满足 3 天逗留 + 满投资 + 清完 200 波后，无需再做宣传与巡逻，每天上线一键收钱即可。",
            ),
            IslandRecommendation(
                category="graduated_daily",
                priority="high",
                title="2. 一键收取自家海岛垃圾块（防 48 小时掉清洁度）",
                reason="垃圾块收进火车暂存区后随跑商经荒原站统一卖出变现。",
            ),
            IslandRecommendation(
                category="graduated_daily",
                priority="medium",
                title="3. 好友海岛清扫偷垃圾（3 次）+ 可选治安蹭怪/点赞",
                reason="全程 0 体力消耗、可稳定接入【一键自动日常】极速常驻队列。",
            ),
        ]
    )

    # 4. 风险与大坑显式提醒
    if island.cleanliness_pct < 100 or (
        island.trash_blocks_cap > 0 and island.trash_blocks_stored >= island.trash_blocks_cap
    ):
        warnings.append(
            f"海岛垃圾暂存已达 {island.trash_blocks_stored}/{max(1, island.trash_blocks_cap)}（清洁度 {island.cleanliness_pct}%），"
            "超 48 小时未清理会大幅降低海岛清洁度与游客收益，请优先运行【一键收取】。"
        )
    if island.active_monsters > 0 and island.stability_current < island.stability_max:
        warnings.append(
            f"岛上当前滞留 {island.active_monsters} 只入侵生物（稳定 {island.stability_current}/{island.stability_max}），"
            "超 48 小时未清理将触发游客收益下降；打完总计 200 波后永久不再刷新。"
        )
    if island.invest_remaining > 0 and not _is_investment_maxed(island, targets):
        warnings.append(
            f"当前海角城运营中心尚余 {island.invest_remaining} 次可用投资机会，跑商经过海角城时记得投掉（倒车不刷新次数）。"
        )
    trash_warn = cat.get("trash_station_warning") if isinstance(cat.get("trash_station_warning"), Mapping) else {}
    warnings.append(
        str(
            trash_warn.get("recommended_stop_rule")
            or "【大坑预警】海岛垃圾站 1→60 级总计需 3 亿+ 铁盟币及笃学灯芯/形而上粒子等稀缺材料，脚本已默认硬屏蔽自动升级，切勿前期盲目砸钱。"
        )
    )

    return IslandPlanReport(
        uid=snapshot.uid,
        stage=stage,
        stage_label=stage_label,
        island_level=island.level,
        unlocked_islands=island.unlocked_islands,
        cabin_level=island.cabin_level,
        trash_station_level=island.trash_station_level,
        stability_current=island.stability_current,
        stability_max=island.stability_max,
        active_monsters=island.active_monsters,
        cleanliness_pct=island.cleanliness_pct,
        trash_rate_per_hour=island.trash_rate_per_hour,
        trash_blocks_stored=island.trash_blocks_stored,
        trash_blocks_cap=island.trash_blocks_cap,
        visitors_current=island.visitors_current,
        visitors_capacity=island.visitors_capacity,
        reported_stay_days=island.avg_stay_days,
        stay_breakdown=stay_bd,
        share_ratio_pct=island.share_ratio_pct,
        ticket_price=island.ticket_price,
        tax_rate_pct=island.tax_rate_pct,
        invested_total=island.invested_total,
        invest_remaining=island.invest_remaining,
        pending_revenue_coins=island.pending_revenue_coins,
        today_revenue_coins=island.today_revenue_coins,
        material_tickets=island.material_tickets,
        shell_coins=island.shell_coins,
        volleyball_coins=island.volleyball_coins,
        coins_total=coins_total,
        reserve_coins=reserve,
        spendable_coins=spendable,
        daily_actions=daily_actions,
        construction_milestones=construction_milestones,
        graduated_checklist=graduated_checklist,
        warnings=warnings,
    )


def format_island_plan_markdown(
    report: IslandPlanReport,
    receipt: Optional[IslandRunReceipt] = None,
) -> str:
    """生成可读的海岛体检与规划 Markdown 报告。"""
    lines = [
        f"# 海岛（蜃息岛）自动化体检与规划报告（UID {report.uid}）",
        "",
        f"- **当前阶段**：{report.stage_label}",
        f"- **海岛等级 / 岛屿**：LV{report.island_level} · 已解锁 {report.unlocked_islands}/6 岛 · 木屋 LV{report.cabin_level}/6",
        f"- **稳定与垃圾**：稳定 {report.stability_current}/{report.stability_max}（活跃怪 ×{report.active_monsters}） · "
        f"垃圾站 LV{report.trash_station_level}（{report.trash_rate_per_hour}/h · 暂存 {report.trash_blocks_stored}/{report.trash_blocks_cap}）",
        f"- **营运与币**：分成 {report.share_ratio_pct:.1f}% / 票价 {report.ticket_price} / 税率 {report.tax_rate_pct:.1f}% "
        f"· 估算游玩 {report.stay_breakdown.estimated_stay_days:.1f} 天（实显 {report.reported_stay_days:.1f} 天）",
        f"- **海岛代币**：资材券 {report.material_tickets:,} · 贝币 {report.shell_coins:,} · 排球奖币 {report.volleyball_coins:,}",
    ]
    if receipt is not None:
        lines.extend(
            [
                "",
                "## 本次执行回执",
                f"- 模式：`{receipt.exec_mode}`（范围 `{receipt.auto_scope}`）",
                f"- 收钱 `{receipt.revenue_claimed_coins:,}` 币 · 收垃圾 `{receipt.trash_blocks_collected}` 块 · "
                f"清自家怪 `{receipt.own_monsters_cleared}` 场 · 领任务 `{receipt.todo_rewards_claimed}` 次 · "
                f"好友清扫 `{receipt.friend_trash_cleaned}` / 点赞 `{receipt.friend_likes_sent}` / 助战 `{receipt.friend_monsters_helped}`",
            ]
        )
        stage3a_parts: list[str] = []
        if receipt.invest_executed_count > 0:
            stage3a_parts.append(f"运营投资 `{receipt.invest_executed_count}` 次（消耗 `{receipt.invest_spent_coins:,}` 币）")
        if receipt.islands_expanded > 0:
            stage3a_parts.append(
                f"海岛扩建 `{receipt.islands_expanded}` 岛（消耗 `{receipt.expand_spent_coins:,}` 币 + `{receipt.expand_spent_tickets:,}` 券）"
            )
        if stage3a_parts:
            lines.append(f"- 建设投资：{' · '.join(stage3a_parts)}")
    lines.extend(["", "## 立刻可做的日常动作"])
    for item in report.daily_actions:
        lines.append(f"- **[{item.priority}] {item.title}**：{item.reason}")
    if report.construction_milestones:
        lines.extend(["", "## 建设里程碑"])
        for item in report.construction_milestones:
            lines.append(f"- **{item.title}**：{item.reason}")
    if report.warnings:
        lines.extend(["", "## 风险预警与避坑"])
        for w in report.warnings:
            lines.append(f"- {w}")
    return "\n".join(lines) + "\n"


def format_island_mxu_summary(
    report: IslandPlanReport,
    receipt: Optional[IslandRunReceipt] = None,
    *,
    issue_bundle_path: Optional[Any] = None,
) -> str:
    """生成适配 MXU 右侧窄日志栏的 6~7 行精简短句。"""
    lines = [
        f"海岛 LV{report.island_level} · {report.stage_label} · {report.unlocked_islands}/6岛 · 木屋LV{report.cabin_level}",
        f"稳定 {report.stability_current}/{report.stability_max}（怪×{report.active_monsters}）· 垃圾 {report.trash_blocks_stored}/{report.trash_blocks_cap} · 游玩{report.stay_breakdown.estimated_stay_days:.1f}天",
        f"资材券 {report.material_tickets:,} · 贝币 {report.shell_coins:,} · 待领 {report.pending_revenue_coins:,}币",
    ]
    if receipt is not None and receipt.exec_mode == "execute_safe_auto":
        receipt_line = (
            f"本次收钱{receipt.revenue_claimed_coins:,} / 收垃圾{receipt.trash_blocks_collected} / "
            f"打怪{receipt.own_monsters_cleared} / 领奖{receipt.todo_rewards_claimed} / "
            f"好友扫{receipt.friend_trash_cleaned}赞{receipt.friend_likes_sent}帮{receipt.friend_monsters_helped}"
        )
        if receipt.invest_executed_count > 0:
            receipt_line += f" / 投资{receipt.invest_executed_count}"
        if receipt.islands_expanded > 0:
            receipt_line += f" / 扩建{receipt.islands_expanded}"
        lines.append(receipt_line)
    else:
        lines.append("当前为只读体检模式；可开启自动执行零风险海岛日常。")
    if report.construction_milestones:
        lines.append(f"建设重点：{report.construction_milestones[0].title}")
    if issue_bundle_path:
        lines.append(f"排错包：{str(issue_bundle_path).split('/')[-1].split(chr(92))[-1]}")
    return "\n".join(lines[:6])
