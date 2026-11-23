"""离线零外链 HTML 可视化报告生成器（整顿中心 / 监狱专属「做什么/买什么/造什么」执行看板）。"""
from __future__ import annotations

from datetime import datetime
import html
from pathlib import Path
from typing import Any, Optional, Sequence

from maa_resonance.logic.planning.growth_planner import GrowthPlanReport
from maa_resonance.logic.planning.prison_executor import (
    PrisonActionStep,
    PrisonExecutionPlan,
    PrisonRunReceipt,
)
from maa_resonance.logic.planning.prison_planner import PrisonPlanReport


def _e(value: Any) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def _fmt_coins_short(amount: int) -> str:
    val = int(amount)
    if val >= 100_000_000:
        return f"{val / 100_000_000:.2f} 亿"
    if val >= 10_000:
        return f"{val // 10_000:,} 万"
    return f"{val:,}"


_PRIORITY_BADGE: dict[str, tuple[str, str]] = {
    "blocker": ("阻断前置", "badge-danger"),
    "high": ("优先升级", "badge-success"),
    "medium": ("建议核对", "badge-info"),
    "warning": ("超限警示", "badge-warn"),
    "defer": ("暂缓", "badge-muted"),
    "ignore": ("无视省钱", "badge-dim"),
}

_ORDER_BADGE: dict[str, tuple[str, str]] = {
    "deliver": ("直接交单", "badge-success"),
    "produce_then_deliver": ("排产补足", "badge-info"),
    "delete_free": ("免费删单", "badge-danger"),
    "skip_weekly": ("周单不接", "badge-muted"),
    "skip_profit_phase": ("毕业停交", "badge-muted"),
}

_HUASHI_BADGE: dict[str, tuple[str, str]] = {
    "blocked_by_guardrail": ("护栏已保护", "badge-warn"),
    "opt_in_enabled": ("已允许计划", "badge-danger"),
    "completed": ("已完成", "badge-success"),
}

_SHOP_BADGE: dict[str, tuple[str, str]] = {
    "buy_one_time": ("优先兑换", "badge-success"),
    "skip_renewable": ("跳过不换", "badge-muted"),
    "block_huashi": ("严禁桦石", "badge-danger"),
    "review_manual": ("按需自查", "badge-info"),
}


def _format_step_cost(step: PrisonActionStep) -> str:
    parts: list[str] = []
    if step.estimated_coins > 0:
        parts.append(f"{step.estimated_coins:,} 币")
    if step.estimated_huashi > 0:
        parts.append(f"{step.estimated_huashi:,} 桦石")
    if step.estimated_tickets > 0:
        parts.append(f"{step.estimated_tickets:,} 工票")
    return " + ".join(parts)


def _render_action_column(steps: Sequence[PrisonActionStep], empty_hint: str) -> str:
    if not steps:
        return f"<p class='muted-note'>{_e(empty_hint)}</p>"
    cards: list[str] = []
    for step in steps:
        badge_html = (
            "<span class='badge badge-success'>可放行</span>"
            if step.allowed
            else "<span class='badge badge-warn'>暂缓/拦截</span>"
        )
        cost_text = _format_step_cost(step)
        cost_html = f"<div class='step-cost num'>预估消耗：{_e(cost_text)}</div>" if cost_text else ""
        note_text = step.reason if step.allowed else (step.blocked_reason or step.reason)
        cards.append(
            f"""
            <div class="step-item {'step-allowed' if step.allowed else 'step-blocked'}">
              <div class="step-head">
                <span class="fw-bold">{_e(step.title)}</span>
                {badge_html}
              </div>
              {cost_html}
              <div class="text-sub">{_e(note_text)}</div>
            </div>
            """
        )
    return "".join(cards)


def _fallback_preview_columns(
    prison_report: PrisonPlanReport,
) -> tuple[list[PrisonActionStep], list[PrisonActionStep], list[PrisonActionStep]]:
    """当未传入 PrisonExecutionPlan 时，从 PrisonPlanReport 提炼只读预览三栏。"""
    do_steps: list[PrisonActionStep] = []
    for od in prison_report.order_decisions[:4]:
        allowed = od.action in ("deliver", "delete_free")
        do_steps.append(
            PrisonActionStep(
                category="do",
                action_type=f"order_{od.action}",
                title=f"黑月单 · {od.item_name}×{od.quantity}",
                target=od.item_name,
                allowed=allowed,
                reason=od.reason,
                blocked_reason="" if allowed else od.reason,
            )
        )
    if not do_steps:
        do_steps.append(
            PrisonActionStep(
                category="do",
                action_type="produce_good",
                title="按攻略高效表轮换排产防爆仓",
                target="生产车间",
                allowed=True,
                reason=prison_report.production_advice[0] if prison_report.production_advice else "",
            )
        )

    buy_steps = [
        PrisonActionStep(
            category="buy",
            action_type="warehouse_coin_expand",
            title="仓库仅点左侧「铁盟币页签」扩容",
            target="仓库扩容",
            allowed=prison_report.spendable_coins > 0,
            reason="先点满铁盟币扩容，严禁触碰右侧桦石页签。",
            blocked_reason="可用余额不足。" if prison_report.spendable_coins <= 0 else "",
        )
    ]

    build_steps: list[PrisonActionStep] = []
    for rec in prison_report.building_recommendations:
        if rec.priority in ("blocker", "high", "medium"):
            build_steps.append(
                PrisonActionStep(
                    category="build",
                    action_type="building_upgrade",
                    title=rec.action,
                    target=rec.name,
                    allowed=True,
                    reason=rec.reason,
                )
            )
    return do_steps, buy_steps, build_steps


def format_planning_report_html(
    prison_report: PrisonPlanReport,
    growth_report: Optional[GrowthPlanReport] = None,
    *,
    execution_plan: Optional[PrisonExecutionPlan] = None,
    run_receipt: Optional[PrisonRunReceipt] = None,
    semi_auto_guides: Optional[Sequence[Any]] = None,
    issue_bundle_path: Optional[Path] = None,
    diag_log_path: Optional[Path] = None,
    generated_at: Optional[str] = None,
) -> str:
    """生成单文件暗色离线 HTML 整顿中心看板（零外链，全字段 HTML 转义；默认纯监狱视图）。"""
    ts = generated_at or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    is_rush = prison_report.phase == "rush_leveling"
    phase_label = "冲级阶段 · 专交黑月订单" if is_rush else "毕业赚钱阶段 · 转运中心出货"
    phase_cls = "badge-info" if is_rush else "badge-success"

    next_ladder = (
        f"下一阶梯 LV{prison_report.next_ladder_unlock_level}"
        if prison_report.next_ladder_unlock_level is not None
        else "已达最大 6 套阶梯"
    )

    warnings_list = list(prison_report.prerequisite_warnings)
    if growth_report is not None:
        warnings_list.extend(growth_report.warnings)
    warnings_html = ""
    if warnings_list:
        items_li = "".join(f"<li>{_e(w)}</li>" for w in warnings_list)
        warnings_html = f"""
        <section class="alert-box">
          <div class="alert-title">前置与资金风险提醒</div>
          <ul class="bullet-list">{items_li}</ul>
        </section>
        """

    if execution_plan is not None:
        do_steps = execution_plan.do_actions
        buy_steps = execution_plan.buy_actions
        build_steps = execution_plan.build_actions
        blocked_steps = execution_plan.blocked_actions
        sim_after_str = f" · 预计执行后仍留 {_fmt_coins_short(execution_plan.simulated_coins_after)}"
    else:
        do_steps, buy_steps, build_steps = _fallback_preview_columns(prison_report)
        blocked_steps = []
        sim_after_str = ""

    # 建筑与投资优先级表格
    b_rows: list[str] = []
    for rec in prison_report.building_recommendations:
        p_label, p_cls = _PRIORITY_BADGE.get(rec.priority, (rec.priority, "badge-muted"))
        cost_str = f"{rec.estimated_coin_cost:,} 币" if rec.estimated_coin_cost is not None else "—"
        b_rows.append(
            "<tr>"
            f"<td><span class='badge {p_cls}'>{_e(p_label)}</span></td>"
            f"<td class='fw-bold'>{_e(rec.name)}</td>"
            f"<td>{_e(rec.action)}</td>"
            f"<td class='text-sub'>{_e(rec.reason)}</td>"
            f"<td class='num text-right'>{_e(cost_str)}</td>"
            "</tr>"
        )
    buildings_tbody = "".join(b_rows) or "<tr><td colspan='5' class='empty'>暂无建筑推荐条目。</td></tr>"

    # 黑月订单卡片内容
    if prison_report.order_decisions:
        o_rows: list[str] = []
        for od in prison_report.order_decisions:
            o_label, o_cls = _ORDER_BADGE.get(od.action, (od.action, "badge-muted"))
            o_type = "周单" if od.order_type == "weekly" else "日单"
            extra = " · 易爆仓" if od.overflow_warning else (" · 延后做" if od.defer_until_surplus else "")
            o_rows.append(
                "<tr>"
                f"<td class='fw-bold'>{_e(od.item_name)}</td>"
                f"<td>{_e(o_type)}</td>"
                f"<td class='num'>{od.stock_owned:,} / {od.quantity:,}</td>"
                f"<td><span class='badge {o_cls}'>{_e(o_label)}</span></td>"
                f"<td class='text-sub'>{_e(od.reason + extra)}</td>"
                "</tr>"
            )
        orders_block = f"""
        <div class="table-wrap">
          <table>
            <thead>
              <tr><th>货物</th><th>类型</th><th>库存/需求</th><th>决策</th><th>说明</th></tr>
            </thead>
            <tbody>{"".join(o_rows)}</tbody>
          </table>
        </div>
        """
    else:
        orders_block = "<p class='muted-note'>本次未识别到可解析的黑月订单条目（可在开启子页面只读扫描后或订单站刷新后重跑）。</p>"

    warehouse_items = "".join(f"<li>{_e(line)}</li>" for line in prison_report.warehouse_advice)
    prod_items = "".join(f"<li>{_e(line)}</li>" for line in prison_report.production_advice)

    # 原料采购站（如有）
    purchase_block = ""
    if prison_report.purchase_decisions:
        p_rows = []
        for pd in prison_report.purchase_decisions:
            p_badge = "<span class='badge badge-success'>可换</span>" if pd.action == "accept" else "<span class='badge badge-danger'>禁止转换</span>"
            p_rows.append(
                f"<tr><td>{_e(pd.from_item)} → {_e(pd.to_item)}</td><td>{p_badge}</td><td class='text-sub'>{_e(pd.reason)}</td></tr>"
            )
        purchase_block = f"""
        <h3 class="sub-title">原料采购站转换核对</h3>
        <div class="table-wrap">
          <table>
            <thead><tr><th>转换项</th><th>结论</th><th>说明</th></tr></thead>
            <tbody>{"".join(p_rows)}</tbody>
          </table>
        </div>
        """

    # 桦石保护护栏卡片
    guard_cards: list[str] = []
    for ga in prison_report.guarded_huashi_actions:
        g_label, g_cls = _HUASHI_BADGE.get(ga.status, (ga.status, "badge-muted"))
        cost_parts: list[str] = []
        if ga.next_huashi_cost or ga.next_coin_cost:
            cost_parts.append(f"下一槽：{ga.next_huashi_cost:,} 桦石 + {ga.next_coin_cost:,} 币")
        if ga.remaining_total_huashi or ga.remaining_total_coins:
            cost_parts.append(f"剩余累计：{ga.remaining_total_huashi:,} 桦石 + {ga.remaining_total_coins:,} 币")
        cost_line = f"<div class='guard-cost num'>{' ｜ '.join(cost_parts)}</div>" if cost_parts else ""
        guard_cards.append(
            f"""
            <div class="guard-item">
              <div class="guard-head">
                <span class="fw-bold">{_e(ga.title)}</span>
                <span class="badge {g_cls}">{_e(g_label)}</span>
              </div>
              {cost_line}
              <div class="text-sub">{_e(ga.notes)}</div>
            </div>
            """
        )

    # 兑换商店规则表
    shop_rows: list[str] = []
    for sd in prison_report.shop_decisions:
        s_label, s_cls = _SHOP_BADGE.get(sd.action, (sd.action, "badge-muted"))
        curr_label = "桦石" if sd.currency == "huashi" else "工票"
        shop_rows.append(
            "<tr>"
            f"<td class='fw-bold'>{_e(sd.item_name)}</td>"
            f"<td>{_e(curr_label)}</td>"
            f"<td><span class='badge {s_cls}'>{_e(s_label)}</span></td>"
            f"<td class='text-sub'>{_e(sd.reason)}</td>"
            "</tr>"
        )

    # 被护栏/避坑规则拦截项汇总
    blocked_html = ""
    if blocked_steps:
        blk_rows = []
        for bs in blocked_steps:
            blk_rows.append(
                "<tr>"
                f"<td class='fw-bold'>{_e(bs.title)}</td>"
                f"<td><span class='badge badge-danger'>已拦截</span></td>"
                f"<td class='text-sub'>{_e(bs.blocked_reason or bs.reason)}</td>"
                "</tr>"
            )
        blocked_html = f"""
        <section class="card">
          <h2>护栏拦截清单（绝对不碰的避坑与红线操作）</h2>
          <div class="table-wrap">
            <table>
              <thead><tr><th>操作项</th><th>状态</th><th>拦截原因</th></tr></thead>
              <tbody>{"".join(blk_rows)}</tbody>
            </table>
          </div>
        </section>
        """

    # 本监囚犯补员参考本（纯监狱劳动力视角）
    prisoner_items = "".join(
        f"<li>{_e(line)}</li>" for line in prison_report.prisoner_farming_recommendations
    )
    prisoner_section = ""
    if prisoner_items:
        prisoner_section = f"""
        <section class="card">
          <h2>本监囚犯补员参考本（顺路补齐工位）</h2>
          <ul class="bullet-list">{prisoner_items}</ul>
        </section>
        """

    kpi_fourth_sub = f"当前上限 {prison_report.recommended_dorm_and_workshop_cap} · {_e(next_ladder)}"
    header_title = (
        f"整顿中心（监狱）自动规划与执行清单 · UID {_e(prison_report.uid)}"
        if growth_report is None
        else f"整顿中心与养成规划报告 · UID {_e(prison_report.uid)}"
    )

    # 仅在外部显式传入 growth_report 时保留兼容性拓展块；纯监狱模式完全不输出养成板块
    legacy_growth_html = ""
    if growth_report is not None:
        stage_rows: list[str] = []
        for st in growth_report.stage_allocations:
            sweep_badge = "<span class='badge badge-success'>可扫荡</span>" if st.sweepable else "<span class='badge badge-warn'>不可扫荡</span>"
            stage_rows.append(
                "<tr>"
                f"<td class='fw-bold'>{_e(st.stage_name)}</td>"
                f"<td>{_e(st.category)}</td>"
                f"<td class='num'>{st.runs} 次</td>"
                f"<td class='num'>{st.clarity_spent} 体</td>"
                f"<td class='num'>+{st.expected_prisoners} 人</td>"
                f"<td>{sweep_badge}</td>"
                f"<td class='text-sub'>{_e(st.reason)}</td>"
                "</tr>"
            )
        legacy_growth_html = f"""
        <section class="card">
          <h2>{_e(growth_report.weekday_name)}体力（澄明度）参考路线</h2>
          <div class="table-wrap">
            <table>
              <thead><tr><th>关卡</th><th>分类</th><th>次数</th><th>体力</th><th>囚犯</th><th>扫荡</th><th>原因</th></tr></thead>
              <tbody>{"".join(stage_rows)}</tbody>
            </table>
          </div>
        </section>
        """

    receipt_html = ""
    mode_meta_label = "只读零消费规划"
    if run_receipt is not None:
        is_exec = run_receipt.mode == "execute_safe_auto"
        mode_meta_label = "自动执行安全项（零桦石保护）" if is_exec else "只读零消费规划"
        mode_badge = (
            "<span class='badge badge-success'>自动执行安全项</span>"
            if is_exec
            else "<span class='badge badge-info'>仅只读规划</span>"
        )
        all_outcomes = [
            ("已执行", "badge-success", o) for o in run_receipt.executed
        ] + [
            ("已跳过", "badge-warn", o) for o in run_receipt.skipped
        ] + [
            ("护栏拦截", "badge-danger", o) for o in run_receipt.guard_aborts
        ]
        if all_outcomes:
            o_rows_html = "".join(
                "<tr>"
                f"<td><span class='badge {bcls}'>{_e(label)}</span></td>"
                f"<td class='fw-bold'>{_e(out.target)}</td>"
                f"<td>{_e(out.action_type)}</td>"
                f"<td class='text-sub'>{_e(out.detail)}</td>"
                "</tr>"
                for label, bcls, out in all_outcomes
            )
            outcomes_block = f"""
            <div class="table-wrap" style="margin-top:10px;">
              <table>
                <thead><tr><th>状态</th><th>目标</th><th>动作类型</th><th>执行明细</th></tr></thead>
                <tbody>{o_rows_html}</tbody>
              </table>
            </div>
            """
        else:
            outcomes_block = "<p class='muted-note'>本次未产生实机改动或无符合安全护栏的待办项。</p>"
        receipt_html = f"""
        <section class="card">
          <div class="step-head" style="margin-bottom:8px;">
            <h2 style="margin:0;">本次自动执行回执</h2>
            <span>{mode_badge} <span class="badge badge-muted">{_e(run_receipt.scope)}</span></span>
          </div>
          <div class="meta-row">
            <span>铁盟币：<strong class="num">{run_receipt.coins_before:,} → {run_receipt.coins_after:,}</strong></span>
            <span>｜</span>
            <span>工票：<strong class="num">{run_receipt.tickets_before:,} → {run_receipt.tickets_after:,}</strong></span>
            <span>｜</span>
            <span>桦石：<strong class="num">{run_receipt.huashi_before:,} → {run_receipt.huashi_after:,}</strong></span>
          </div>
          {outcomes_block}
        </section>
        """

    guides = (
        list(semi_auto_guides)
        if semi_auto_guides is not None
        else (list(run_receipt.semi_auto_guides) if run_receipt is not None and getattr(run_receipt, "semi_auto_guides", None) else [])
    )
    guides_html = ""
    if guides:
        guide_pri_badge = {
            "urgent": ("优先手动", "badge-danger"),
            "recommended": ("建议手动", "badge-warn"),
            "optional": ("可选/说明", "badge-info"),
        }
        g_cards: list[str] = []
        for g in guides:
            if isinstance(g, dict):
                pri = str(g.get("priority") or "recommended")
                title = str(g.get("title") or "")
                why = str(g.get("why_manual") or "")
                g_steps = list(g.get("steps") or ())
            else:
                pri = str(getattr(g, "priority", "recommended"))
                title = str(getattr(g, "title", ""))
                why = str(getattr(g, "why_manual", ""))
                g_steps = list(getattr(g, "steps", ()) or ())
            g_label, g_cls = guide_pri_badge.get(pri, (pri, "badge-muted"))
            ol_html = "".join(f"<li>{_e(s)}</li>" for s in g_steps)
            steps_block = f"<ol class='bullet-list' style='margin-top:6px;'>{ol_html}</ol>" if ol_html else ""
            g_cards.append(
                f"""
                <div class="step-item {'step-blocked' if pri == 'urgent' else 'step-allowed'}">
                  <div class="step-head">
                    <span class="fw-bold">{_e(title)}</span>
                    <span class="badge {g_cls}">{_e(g_label)}</span>
                  </div>
                  <div class="text-sub">{_e(why)}</div>
                  {steps_block}
                </div>
                """
            )
        guides_html = f"""
        <section class="card">
          <h2>半自动人工接力指引（当前需你手动点这几步）</h2>
          {"".join(g_cards)}
        </section>
        """

    diag_section = ""
    if issue_bundle_path is not None or diag_log_path is not None:
        diag_parts: list[str] = []
        if issue_bundle_path is not None:
            diag_parts.append(
                f"<li><strong>一键提交 Issue 诊断压缩包</strong>：<span class='num'>config/planning/logs/{_e(issue_bundle_path.name)}</span>（含已脱敏运行日志、JSON 快照、Issue 模版与可选现场截图）</li>"
            )
        if diag_log_path is not None:
            diag_parts.append(
                f"<li><strong>纯文本专项运行日志</strong>：<span class='num'>config/planning/logs/{_e(diag_log_path.name)}</span>（最近一次副本为 <span class='num'>latest_prison_run.log</span>）</li>"
            )
        diag_section = f"""
        <section class="card">
          <h2>问题反馈与专项诊断日志</h2>
          <ul class="bullet-list">{"".join(diag_parts)}</ul>
          <h3 class="sub-title">提交 Issue 排错三步</h3>
          <ol class="bullet-list">
            <li>打开上方目录中的诊断文件（优先上传 <code>.zip</code> 排错包；UID 与本机盘符目录均已自动脱敏）。</li>
            <li>解压包内 <code>issue_template.md</code> 可直接复制为 GitHub Issue 正文，补充你遇到的卡点或分辨率即可。</li>
            <li>在仓库 Issues 页面新建 Issue，将 <code>issue_template.md</code> 内容粘贴并拖入 <code>.zip</code> 文件提交。</li>
          </ol>
        </section>
        """

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{header_title}</title>
  <style>
    :root {{
      --bg: #0f1115;
      --card: #171b22;
      --surface: #1d232d;
      --border: #272d38;
      --text: #e6edf3;
      --sub: #9aa4b2;
      --dim: #707a8a;
      --green: #3fb950;
      --green-bg: rgba(63, 185, 80, 0.14);
      --blue: #58a6ff;
      --blue-bg: rgba(88, 166, 255, 0.14);
      --warn: #d29922;
      --warn-bg: rgba(210, 153, 34, 0.14);
      --danger: #f85149;
      --danger-bg: rgba(248, 81, 73, 0.14);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font-family: "Microsoft YaHei UI", "PingFang SC", "Segoe UI", system-ui, -apple-system, sans-serif;
      font-size: 14px;
      line-height: 1.55;
    }}
    .container {{
      max-width: 1220px;
      margin: 0 auto;
      padding: 24px 16px 48px;
    }}
    .header {{
      display: flex;
      flex-wrap: wrap;
      justify-content: space-between;
      align-items: center;
      gap: 12px;
      padding: 18px 20px;
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 12px;
      margin-bottom: 16px;
    }}
    .header h1 {{
      margin: 0 0 6px;
      font-size: 20px;
      font-weight: 600;
    }}
    .meta-row {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      align-items: center;
      color: var(--sub);
      font-size: 13px;
    }}
    .kpi-grid {{
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 12px;
      margin-bottom: 16px;
    }}
    .kpi-card {{
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 14px 16px;
    }}
    .kpi-label {{ color: var(--sub); font-size: 12px; margin-bottom: 6px; }}
    .kpi-value {{ font-size: 22px; font-weight: 700; color: var(--text); margin-bottom: 4px; font-variant-numeric: tabular-nums; }}
    .kpi-sub {{ color: var(--sub); font-size: 12px; font-variant-numeric: tabular-nums; }}
    .three-col {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 14px;
      margin-bottom: 16px;
    }}
    .two-col {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 16px;
      margin-bottom: 16px;
    }}
    .two-col .card, .three-col .card {{ margin-bottom: 0; }}
    .alert-box {{
      background: var(--warn-bg);
      border: 1px solid rgba(210, 153, 34, 0.35);
      border-radius: 12px;
      padding: 14px 18px;
      margin-bottom: 16px;
    }}
    .alert-title {{ color: var(--warn); font-weight: 600; margin-bottom: 6px; }}
    .card {{
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 18px 20px;
      margin-bottom: 16px;
    }}
    .card h2 {{
      margin: 0 0 12px;
      font-size: 16px;
      font-weight: 600;
      border-left: 3px solid var(--green);
      padding-left: 10px;
    }}
    .sub-title {{ margin: 16px 0 8px; font-size: 14px; font-weight: 600; color: var(--text); }}
    .step-item {{
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 10px 12px;
      margin-bottom: 8px;
    }}
    .step-item:last-child {{ margin-bottom: 0; }}
    .step-allowed {{ border-left: 3px solid var(--green); }}
    .step-blocked {{ border-left: 3px solid var(--warn); opacity: 0.92; }}
    .step-head {{
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      gap: 8px;
      margin-bottom: 4px;
    }}
    .step-cost {{ font-size: 12px; color: var(--blue); margin-bottom: 3px; }}
    .table-wrap {{
      overflow-x: auto;
      border: 1px solid var(--border);
      border-radius: 8px;
      background: var(--surface);
    }}
    table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
    th, td {{ padding: 9px 11px; border-bottom: 1px solid var(--border); text-align: left; vertical-align: top; }}
    th {{ color: var(--sub); font-weight: 600; background: rgba(255, 255, 255, 0.02); white-space: nowrap; }}
    tr:last-child td {{ border-bottom: none; }}
    .badge {{
      display: inline-block;
      padding: 2px 8px;
      border-radius: 999px;
      font-size: 12px;
      font-weight: 600;
      white-space: nowrap;
    }}
    .badge-success {{ background: var(--green-bg); color: var(--green); }}
    .badge-info {{ background: var(--blue-bg); color: var(--blue); }}
    .badge-warn {{ background: var(--warn-bg); color: var(--warn); }}
    .badge-danger {{ background: var(--danger-bg); color: var(--danger); }}
    .badge-muted {{ background: rgba(154, 164, 178, 0.14); color: var(--sub); }}
    .badge-dim {{ background: rgba(112, 122, 138, 0.12); color: var(--dim); }}
    .bullet-list {{ margin: 6px 0 0; padding-left: 18px; }}
    .bullet-list li {{ margin-bottom: 4px; }}
    .guard-item {{
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 11px 13px;
      margin-bottom: 10px;
    }}
    .guard-head {{ display: flex; justify-content: space-between; align-items: center; gap: 8px; margin-bottom: 4px; }}
    .guard-cost {{ font-size: 12px; color: var(--text); margin-bottom: 4px; }}
    .fw-bold {{ font-weight: 600; }}
    .text-sub {{ color: var(--sub); }}
    .text-right {{ text-align: right; }}
    .num {{ font-variant-numeric: tabular-nums; white-space: nowrap; }}
    .muted-note {{ color: var(--sub); margin: 4px 0 8px; }}
    .empty {{ text-align: center; color: var(--sub); padding: 18px; }}
    @media (max-width: 1020px) {{
      .kpi-grid {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
      .three-col, .two-col {{ grid-template-columns: 1fr; }}
    }}
    @media (max-width: 560px) {{
      .kpi-grid {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
  <main class="container">
    <header class="header">
      <div>
        <h1>整顿中心（监狱）自动规划与执行清单</h1>
        <div class="meta-row">
          <span>UID：<strong class="num">{_e(prison_report.uid)}</strong></span>
          <span>·</span>
          <span>生成时间：<span class="num">{_e(ts)}</span></span>
          <span>·</span>
          <span>{_e(mode_meta_label)}</span>
        </div>
      </div>
      <div>
        <span class="badge {phase_cls}">{_e(phase_label)}</span>
      </div>
    </header>

    <section class="kpi-grid">
      <div class="kpi-card">
        <div class="kpi-label">整顿中心等级与余电</div>
        <div class="kpi-value">LV {prison_report.prison_level}</div>
        <div class="kpi-sub">可用余电 {prison_report.power_free:,}（已用 {prison_report.power_used:,} / {prison_report.power_max:,}）</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-label">铁盟币可用预算</div>
        <div class="kpi-value">{_e(_fmt_coins_short(prison_report.spendable_coins))}</div>
        <div class="kpi-sub">总持有 {prison_report.coins_total:,} · 底线 {prison_report.reserve_coins:,}{_e(sim_after_str)}</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-label">桦石与工票存量</div>
        <div class="kpi-value">{prison_report.huashi_total:,} 桦石</div>
        <div class="kpi-sub">当前工票：{prison_report.work_tickets:,}</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-label">宿舍 / 生产车间梯次</div>
        <div class="kpi-value">{prison_report.dorm_count} / {prison_report.production_workshop_count} 套</div>
        <div class="kpi-sub">{kpi_fourth_sub}</div>
      </div>
    </section>

    {warnings_html}
    {receipt_html}
    {guides_html}

    <div class="three-col">
      <section class="card">
        <h2>做什么（订单与排产）</h2>
        {_render_action_column(do_steps, "当前暂无可立即执行的订单/排产动作。")}
      </section>
      <section class="card">
        <h2>买什么（扩仓/工票/采购）</h2>
        {_render_action_column(buy_steps, "当前暂无待买条目。")}
      </section>
      <section class="card">
        <h2>造什么（升级顺序与设置）</h2>
        {_render_action_column(build_steps, "当前建筑状态已齐备。")}
      </section>
    </div>

    <section class="card">
      <h2>建筑与投资优先级完整说明</h2>
      <div class="table-wrap">
        <table>
          <thead>
            <tr><th>优先级</th><th>建筑 / 模块</th><th>下一步操作建议</th><th>策略依据</th><th class="text-right">预估费用</th></tr>
          </thead>
          <tbody>{buildings_tbody}</tbody>
        </table>
      </div>
    </section>

    <div class="two-col">
      <section class="card">
        <h2>黑月服装订单与排产规则</h2>
        {orders_block}
        <h3 class="sub-title">仓库与排产核心要点</h3>
        <ul class="bullet-list">
          {warehouse_items}
          {prod_items}
        </ul>
        {purchase_block}
      </section>

      <section class="card">
        <h2>桦石保护护栏与兑换商店</h2>
        {"".join(guard_cards)}
        <h3 class="sub-title">整顿兑换商店红黑榜</h3>
        <div class="table-wrap">
          <table>
            <thead><tr><th>商品</th><th>货币</th><th>判定</th><th>说明</th></tr></thead>
            <tbody>{"".join(shop_rows)}</tbody>
          </table>
        </div>
      </section>
    </div>

    {blocked_html}
    {prisoner_section}
    {legacy_growth_html}
    {diag_section}
  </main>
</body>
</html>
"""
