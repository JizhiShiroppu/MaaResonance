from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Optional, Sequence

if __package__ in {None, ""}:
    _repo_root = str(Path(__file__).resolve().parents[3])
    if _repo_root not in sys.path:
        sys.path.insert(0, _repo_root)

from maa_resonance.logic.planning.account_snapshot import (
    AccountSnapshot,
    load_account_snapshot,
    snapshot_from_account_payload,
)
from maa_resonance.logic.planning.growth_planner import (
    GrowthPlanOptions,
    format_growth_plan_markdown,
    plan_growth,
)
from maa_resonance.logic.planning.prison_planner import (
    PrisonPlanOptions,
    format_prison_plan_markdown,
    plan_prison,
)


def _apply_cli_overrides(snapshot: AccountSnapshot, args: argparse.Namespace) -> AccountSnapshot:
    wallet = snapshot.wallet.model_copy()
    prison = snapshot.prison.model_copy()
    buildings = dict(prison.buildings)

    if args.coins is not None:
        wallet.coins = int(args.coins)
    if args.huashi is not None:
        wallet.huashi = int(args.huashi)
    if args.prison_level is not None:
        prison.level = int(args.prison_level)
    if args.tickets is not None:
        prison.work_tickets = int(args.tickets)
    if args.research_level is not None:
        buildings["research_center"] = int(args.research_level)
    if args.power_level is not None:
        buildings["power_center"] = int(args.power_level)
    if args.dorms is not None:
        prison.dorm_count = int(args.dorms)
    if args.workshops is not None:
        prison.production_workshop_count = int(args.workshops)
    if args.prisoners is not None:
        prison.prisoners_current = int(args.prisoners)
    if args.prisoner_cap is not None:
        prison.prisoners_capacity = int(args.prisoner_cap)

    prison.buildings = buildings
    return snapshot.model_copy(update={"wallet": wallet, "prison": prison})


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="MaaResonance 整顿中心与乘员养成只读 Dry-Run 规划报告工具（零消费）",
    )
    parser.add_argument("--account", type=Path, help="config/accounts/<uid>.json 路径（仅只读，绝不回写）")
    parser.add_argument("--section", choices=("all", "prison", "growth"), default="all")
    parser.add_argument("--weekday", type=int, default=None, help="星期几（0=周一 .. 6=周日）")
    parser.add_argument("--clarity-budget", type=int, default=240, help="每日可用澄明度预算")
    parser.add_argument("--reserve-coins", type=int, default=15_000_000, help="铁盟币安全保留地板")
    parser.add_argument("--player-level", type=int, default=71, help="列车长当前等级")
    parser.add_argument("--prison-level", type=int, default=None, help="覆盖整顿中心等级用于离线推演")
    parser.add_argument("--coins", type=int, default=None, help="覆盖当前铁盟币用于离线推演")
    parser.add_argument("--huashi", type=int, default=None, help="覆盖当前桦石用于离线推演")
    parser.add_argument("--tickets", type=int, default=None, help="覆盖当前工票用于离线推演")
    parser.add_argument("--research-level", type=int, default=None, help="覆盖研发中心等级")
    parser.add_argument("--power-level", type=int, default=None, help="覆盖电力中心等级")
    parser.add_argument("--dorms", type=int, default=None, help="覆盖已建宿舍数量")
    parser.add_argument("--workshops", type=int, default=None, help="覆盖已建生产车间数量")
    parser.add_argument("--prisoners", type=int, default=None, help="覆盖当前在监囚犯数")
    parser.add_argument("--prisoner-cap", type=int, default=None, help="覆盖当前囚犯床位上限")
    parser.add_argument("--allow-huashi-motors", action="store_true", help="显式开启电力中心桦石安装电机")
    parser.add_argument("--allow-huashi-warehouse", action="store_true", help="显式开启仓库右侧桦石扩容")
    parser.add_argument("--json", action="store_true", dest="as_json", help="以 JSON 格式输出结构化规划结果")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

    args = build_parser().parse_args(argv)
    if args.account is not None:
        snapshot = load_account_snapshot(args.account)
    else:
        snapshot = snapshot_from_account_payload({"uid": "dry_run"})

    snapshot = _apply_cli_overrides(snapshot, args)

    prison_options = PrisonPlanOptions(
        reserve_coins=args.reserve_coins,
        allow_huashi_motors=bool(args.allow_huashi_motors),
        allow_huashi_warehouse=bool(args.allow_huashi_warehouse),
        player_level=args.player_level,
    )
    growth_options = GrowthPlanOptions(
        daily_clarity_budget=args.clarity_budget,
        weekday=args.weekday,
        reserve_coins=args.reserve_coins,
    )

    output_payload: dict[str, Any] = {}
    markdown_parts: list[str] = []

    if args.section in ("all", "prison"):
        prison_report = plan_prison(snapshot, prison_options)
        output_payload["prison"] = prison_report.model_dump(mode="json")
        markdown_parts.append(format_prison_plan_markdown(prison_report))

    if args.section in ("all", "growth"):
        growth_report = plan_growth(snapshot, growth_options)
        output_payload["growth"] = growth_report.model_dump(mode="json")
        markdown_parts.append(format_growth_plan_markdown(growth_report))

    if args.as_json:
        print(json.dumps(output_payload, ensure_ascii=False, indent=2))
    else:
        print("\n\n---\n\n".join(markdown_parts))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
