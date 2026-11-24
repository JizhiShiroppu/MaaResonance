"""离线零外链 HTML 可视化报告生成器（海岛 / 蜃息岛体检与执行看板）。"""
from __future__ import annotations

from datetime import datetime
import html
from pathlib import Path
from typing import Any, Optional, Sequence

from maa_resonance.logic.planning.island_planner import (
    IslandPlanReport,
    IslandRecommendation,
    IslandRunReceipt,
)
from maa_resonance.logic.planning.prison_diagnostics import mask_uid


def _e(value: Any) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def _fmt_coins_short(amount: int) -> str:
    val = int(amount)
    if val >= 100_000_000:
        return f"{val / 100_000_000:.2f} 亿"
    if val >= 10_000:
        return f"{val // 10_000:,} 万"
    return f"{val:,}"


_PRIO_BADGE: dict[str, tuple[str, str]] = {
    "blocker": ("紧迫处理", "badge-danger"),
    "high": ("优先建议", "badge-success"),
    "medium": ("按需推进", "badge-info"),
    "optional": ("可选扩展", "badge-muted"),
    "warning": ("风险预警", "badge-warn"),
}


def _render_cards(items: Sequence[IslandRecommendation], empty_text: str) -> str:
    if not items:
        return f"<p class='muted-note'>{_e(empty_text)}</p>"
    out: list[str] = []
    for item in items:
        label, cls = _PRIO_BADGE.get(item.priority, ("提示", "badge-muted"))
        cost_parts: list[str] = []
        if item.estimated_coins > 0:
            cost_parts.append(f"{item.estimated_coins:,} 铁盟币")
        if item.estimated_tickets > 0:
            cost_parts.append(f"{item.estimated_tickets:,} 资材券")
        cost_html = f"<div class='step-cost num'>预估消耗：{_e(' + '.join(cost_parts))}</div>" if cost_parts else ""
        out.append(
            f"""
            <div class="step-item">
              <div class="step-head">
                <span class="fw-bold">{_e(item.title)}</span>
                <span class="badge {cls}">{_e(label)}</span>
              </div>
              {cost_html}
              <div class="text-sub">{_e(item.reason)}</div>
            </div>
            """
        )
    return "".join(out)


def format_island_report_html(
    report: IslandPlanReport,
    receipt: Optional[IslandRunReceipt] = None,
    *,
    diag_log_path: Optional[Path | str] = None,
    issue_bundle_path: Optional[Path | str] = None,
) -> str:
    """生成离线暗色风格 HTML 看板（纯内联 CSS、全字段转义、零外链）。"""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    stage_cls = {
        "graduated_daily": "badge-success",
        "transition": "badge-info",
        "construction": "badge-warn",
    }.get(report.stage, "badge-info")

    stay = report.stay_breakdown
    dim_rows = "".join(
        f"""
        <tr>
          <td class="fw-bold">{_e(d.name)}</td>
          <td class="num text-right">{d.score:,} / {d.full_target:,}</td>
          <td class="num text-right">+{d.bonus_days:.1f} / +{d.max_bonus_days:.1f} 天</td>
          <td class="num text-right">{'已满' if d.points_to_full == 0 else f'差 {d.points_to_full:,}'}</td>
        </tr>
        """
        for d in stay.dimensions
    )

    warnings_html = ""
    if report.warnings:
        warn_items = "".join(f"<li>{_e(w)}</li>" for w in report.warnings)
        warnings_html = f"""
        <section class="card card-warn">
          <h2>风险预警与大坑防护</h2>
          <ul class="bullet-list">{warn_items}</ul>
        </section>
        """

    receipt_html = ""
    if receipt is not None:
        outcome_rows = "".join(
            f"""
            <tr>
              <td>{_e(o.stage)}</td>
              <td>{_e(o.target)}</td>
              <td><span class="badge {'badge-success' if o.status == 'executed' else ('badge-warn' if o.status == 'aborted' else 'badge-muted')}">{_e(o.status)}</span></td>
              <td>{_e(o.detail)}</td>
            </tr>
            """
            for o in (*receipt.executed, *receipt.guard_aborts, *receipt.skipped)
        )
        receipt_html = f"""
        <section class="card">
          <h2>本次自动化执行回执（{_e(receipt.exec_mode)} · {_e(receipt.auto_scope)}）</h2>
          <div class="kpi-mini-row">
            <span>收取营运收益：<strong class="num">{receipt.revenue_claimed_coins:,}</strong> 币</span>
            <span>收取海岛垃圾块：<strong class="num">{receipt.trash_blocks_collected}</strong></span>
            <span>清自家野怪：<strong class="num">{receipt.own_monsters_cleared}</strong> 场</span>
            <span>领事项一览：<strong class="num">{receipt.todo_rewards_claimed}</strong> 次</span>
            <span>好友互助：清扫 <strong class="num">{receipt.friend_trash_cleaned}</strong> · 点赞 <strong class="num">{receipt.friend_likes_sent}</strong> · 助战 <strong class="num">{receipt.friend_monsters_helped}</strong></span>
            {f"<span>运营投资：<strong class='num'>{receipt.invest_executed_count}</strong> 次（{receipt.invest_spent_coins:,} 币）</span>" if receipt.invest_executed_count > 0 else ""}
            {f"<span>海岛扩建：<strong class='num'>{receipt.islands_expanded}</strong> 岛（{receipt.expand_spent_coins:,} 币 + {receipt.expand_spent_tickets:,} 券）</span>" if receipt.islands_expanded > 0 else ""}
          </div>
          {f"<div class='table-wrap'><table><thead><tr><th>阶段</th><th>目标</th><th>状态</th><th>说明</th></tr></thead><tbody>{outcome_rows}</tbody></table></div>" if outcome_rows else ""}
        </section>
        """

    diag_html = ""
    if diag_log_path or issue_bundle_path:
        diag_html = f"""
        <section class="card">
          <h2>专项诊断与 Issue 反馈包</h2>
          <ul class="bullet-list">
            {f"<li>脱敏排错压缩包（可拖入 GitHub Issue）：<code>{_e(issue_bundle_path)}</code></li>" if issue_bundle_path else ""}
            {f"<li>最新海岛运行日志：<code>{_e(diag_log_path)}</code></li>" if diag_log_path else ""}
          </ul>
        </section>
        """

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>海岛（蜃息岛）自动体检与规划看板</title>
  <style>
    :root {{
      --bg: #0b1120; --surface: #111827; --card: #161f33; --border: #25324d;
      --text: #e2e8f0; --sub: #94a3b8; --accent: #38bdf8;
      --green: #22c55e; --amber: #f59e0b; --red: #ef4444;
    }}
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ background: var(--bg); color: var(--text); font-family: "Segoe UI", "Microsoft YaHei", sans-serif; line-height: 1.55; padding: 24px 16px; }}
    .container {{ max-width: 1220px; margin: 0 auto; display: flex; flex-direction: column; gap: 16px; }}
    .header {{ display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 12px; background: var(--card); border: 1px solid var(--border); border-radius: 12px; padding: 18px 22px; }}
    .header h1 {{ font-size: 20px; color: #f8fafc; }}
    .meta-row {{ font-size: 13px; color: var(--sub); display: flex; gap: 8px; flex-wrap: wrap; margin-top: 4px; }}
    .kpi-grid {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; }}
    .kpi-card {{ background: var(--card); border: 1px solid var(--border); border-radius: 12px; padding: 14px 16px; }}
    .kpi-label {{ font-size: 12px; color: var(--sub); }}
    .kpi-value {{ font-size: 22px; font-weight: 700; color: #f8fafc; margin: 4px 0; }}
    .kpi-sub {{ font-size: 12px; color: var(--sub); }}
    .card {{ background: var(--card); border: 1px solid var(--border); border-radius: 12px; padding: 16px 18px; }}
    .card-warn {{ border-color: rgba(245, 158, 11, 0.55); background: rgba(245, 158, 11, 0.08); }}
    .card h2 {{ font-size: 16px; color: #f1f5f9; margin-bottom: 12px; }}
    .three-col {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 14px; }}
    .step-item {{ background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 10px 12px; margin-bottom: 10px; }}
    .step-head {{ display: flex; justify-content: space-between; align-items: flex-start; gap: 8px; margin-bottom: 4px; }}
    .step-cost {{ font-size: 12px; color: var(--accent); margin-bottom: 4px; }}
    .text-sub {{ font-size: 12px; color: var(--sub); }}
    .fw-bold {{ font-weight: 600; }}
    .num {{ font-variant-numeric: tabular-nums; }}
    .badge {{ display: inline-block; font-size: 11px; padding: 2px 8px; border-radius: 999px; font-weight: 600; white-space: nowrap; }}
    .badge-success {{ background: rgba(34, 197, 94, 0.16); color: #86efac; border: 1px solid rgba(34, 197, 94, 0.35); }}
    .badge-info {{ background: rgba(56, 189, 248, 0.16); color: #7dd3fc; border: 1px solid rgba(56, 189, 248, 0.35); }}
    .badge-warn {{ background: rgba(245, 158, 11, 0.16); color: #fcd34d; border: 1px solid rgba(245, 158, 11, 0.35); }}
    .badge-danger {{ background: rgba(239, 68, 68, 0.16); color: #fca5a5; border: 1px solid rgba(239, 68, 68, 0.35); }}
    .badge-muted {{ background: rgba(148, 163, 184, 0.14); color: #cbd5e1; border: 1px solid rgba(148, 163, 184, 0.3); }}
    .table-wrap {{ overflow-x: auto; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
    th, td {{ padding: 8px 10px; border-bottom: 1px solid var(--border); text-align: left; }}
    th {{ color: var(--sub); font-weight: 600; }}
    .text-right {{ text-align: right; }}
    .bullet-list {{ padding-left: 18px; display: flex; flex-direction: column; gap: 6px; font-size: 13px; }}
    .kpi-mini-row {{ display: flex; flex-wrap: wrap; gap: 14px; font-size: 13px; margin-bottom: 10px; }}
    .muted-note {{ font-size: 13px; color: var(--sub); }}
    code {{ background: var(--surface); padding: 2px 6px; border-radius: 4px; font-size: 12px; color: #cbd5e1; }}
    @media (max-width: 980px) {{ .kpi-grid {{ grid-template-columns: repeat(2, 1fr); }} .three-col {{ grid-template-columns: 1fr; }} }}
  </style>
</head>
<body>
  <main class="container">
    <header class="header">
      <div>
        <h1>海岛（蜃息岛）自动体检与规划看板</h1>
        <div class="meta-row">
          <span>UID：<strong class="num">{_e(mask_uid(report.uid))}</strong></span>
          <span>·</span>
          <span>生成时间：<span class="num">{_e(ts)}</span></span>
        </div>
      </div>
      <span class="badge {stage_cls}">{_e(report.stage_label)}</span>
    </header>

    <section class="kpi-grid">
      <div class="kpi-card">
        <div class="kpi-label">海岛等级与扩建</div>
        <div class="kpi-value">LV {report.island_level} · {report.unlocked_islands}/6 岛</div>
        <div class="kpi-sub">沙滩小屋 LV{report.cabin_level}/6 · 垃圾站 LV{report.trash_station_level}</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-label">稳定指数与垃圾清洁</div>
        <div class="kpi-value">{report.stability_current}/{report.stability_max}（怪×{report.active_monsters}）</div>
        <div class="kpi-sub">清洁 {report.cleanliness_pct}% · 垃圾 {report.trash_rate_per_hour}/h · 暂存 {report.trash_blocks_stored}/{report.trash_blocks_cap}</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-label">游玩天数与运营投资</div>
        <div class="kpi-value">{stay.estimated_stay_days:.1f} / {stay.max_total_days:.1f} 天</div>
        <div class="kpi-sub">分成 {report.share_ratio_pct:.1f}% · 票价 {report.ticket_price} · 税 {report.tax_rate_pct:.1f}% · 余次 {report.invest_remaining}</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-label">代币与预算（底线 {_e(_fmt_coins_short(report.reserve_coins))}）</div>
        <div class="kpi-value">{report.material_tickets:,} 券 / {report.shell_coins:,} 贝</div>
        <div class="kpi-sub">铁盟币 {_e(_fmt_coins_short(report.coins_total))} · 排球币 {report.volleyball_coins:,} · 待领 {report.pending_revenue_coins:,} 币</div>
      </div>
    </section>

    {warnings_html}
    {receipt_html}

    <div class="three-col">
      <section class="card">
        <h2>日常马上能做（零风险闭环）</h2>
        {_render_cards(report.daily_actions, "暂无待办日常。")}
      </section>
      <section class="card">
        <h2>阶段建设里程碑（做完即毕业）</h2>
        {_render_cards(report.construction_milestones, "全部建设里程碑已完成！")}
      </section>
      <section class="card">
        <h2>毕业后常驻 3 步收菜</h2>
        {_render_cards(report.graduated_checklist, "暂无常驻项。")}
      </section>
    </div>

    <section class="card">
      <h2>7 维评分与 3.0 天游玩时长拆解（基础 1.0 天 + 最高 2.0 天属性加成）</h2>
      <div class="table-wrap">
        <table>
          <thead>
            <tr><th>属性维度</th><th class="text-right">当前 / 满额</th><th class="text-right">当前加成</th><th class="text-right">距离单维满额</th></tr>
          </thead>
          <tbody>{dim_rows}</tbody>
        </table>
      </div>
    </section>

    {diag_html}
  </main>
</body>
</html>
"""
