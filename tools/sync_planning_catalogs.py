from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys
import time
from typing import Any, Optional, Sequence
import urllib.parse
import urllib.request

BWIKI_API_URL = "https://wiki.biligame.com/resonance/api.php"
MIN_REQUEST_DELAY_SECONDS = 1.5
DEFAULT_REQUEST_DELAY_SECONDS = 2.5

_REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_PATH = _REPO_ROOT / "resources" / "planning" / "prison_wiki_catalog.json"


def _clean_text(value: str) -> str:
    text = str(value or "").strip()
    if text.startswith("*"):
        text = text[1:].strip()
    return text


def _strip_wiki_links(value: str) -> str:
    text = _clean_text(value)
    text = re.sub(r"\[\[([^|\]]+\|)?([^\]]+)\]\]", r"\2", text)
    return text.strip()


def _parse_int_prefix(value: str, default: int = 0) -> int:
    text = _clean_text(value)
    match = re.search(r"-?\d+", text)
    return int(match.group(0)) if match else default


def _parse_float_prefix(value: str, default: float = 0.0) -> float:
    text = _clean_text(value)
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    return float(match.group(0)) if match else default


def parse_cn_resource_pairs(text: str) -> dict[str, int]:
    """解析类似「铁盟币：10000、整顿中心工票：100」的中文键值对。"""
    cleaned = _clean_text(text)
    if not cleaned or cleaned in {"无", "-", "None"}:
        return {}
    result: dict[str, int] = {}
    for segment in re.split(r"[、,，]", cleaned):
        part = segment.strip()
        if not part:
            continue
        sep = "：" if "：" in part else (":" if ":" in part else None)
        if sep is None:
            continue
        name, raw_qty = part.split(sep, 1)
        clean_name = _strip_wiki_links(name)
        if not clean_name:
            continue
        result[clean_name] = _parse_int_prefix(raw_qty, 0)
    return result


def parse_single_name_qty(text: str) -> tuple[str, int]:
    """解析单组「物品名：数量」或「[[物品名]]：数量」。"""
    cleaned = _clean_text(text)
    if not cleaned:
        return "", 0
    sep = "：" if "：" in cleaned else (":" if ":" in cleaned else None)
    if sep is None:
        return _strip_wiki_links(cleaned), 1
    raw_name, raw_qty = cleaned.split(sep, 1)
    return _strip_wiki_links(raw_name), _parse_int_prefix(raw_qty, 1)


def _extract_invoke_blocks(wikitext: str) -> list[str]:
    """提取所有 {{#invoke: 数据| 生成列表 ...}} 模板完整体文本。"""
    blocks: list[str] = []
    idx = 0
    text = str(wikitext or "")
    pattern = re.compile(r"\{\{\s*#invoke\s*:\s*数据\s*\|\s*生成列表", re.IGNORECASE)
    while idx < len(text):
        match = pattern.search(text, idx)
        if not match:
            break
        start = match.start()
        depth = 0
        pos = start
        end = len(text)
        while pos < len(text) - 1:
            pair = text[pos : pos + 2]
            if pair == "{{":
                depth += 1
                pos += 2
                continue
            if pair == "}}":
                depth -= 1
                pos += 2
                if depth <= 0:
                    end = pos
                    break
                continue
            pos += 1
        blocks.append(text[start:end])
        idx = end
    return blocks


def _split_top_level_pipes(block_text: str) -> list[str]:
    """仅在内部 {{...}} / [[...]] 深度为 0 时按 `|` 分割参数。"""
    inner = block_text
    if inner.startswith("{{") and inner.endswith("}}"):
        inner = inner[2:-2]
    parts: list[str] = []
    cur: list[str] = []
    brace_depth = 0
    bracket_depth = 0
    i = 0
    while i < len(inner):
        two = inner[i : i + 2]
        if two == "{{":
            brace_depth += 1
            cur.append(two)
            i += 2
        elif two == "}}":
            brace_depth = max(0, brace_depth - 1)
            cur.append(two)
            i += 2
        elif two == "[[":
            bracket_depth += 1
            cur.append(two)
            i += 2
        elif two == "]]":
            bracket_depth = max(0, bracket_depth - 1)
            cur.append(two)
            i += 2
        elif inner[i] == "|" and brace_depth == 0 and bracket_depth == 0:
            parts.append("".join(cur))
            cur = []
            i += 1
        else:
            cur.append(inner[i])
            i += 1
    if cur:
        parts.append("".join(cur))
    return parts


def parse_wiki_generated_list_blocks(wikitext: str) -> list[list[dict[str, str]]]:
    """解析 wikitext 中每个 {{#invoke: 数据| 生成列表}} 表格为行列表。"""
    tables: list[list[dict[str, str]]] = []
    for block in _extract_invoke_blocks(wikitext):
        titles_by_idx: dict[int, str] = {}
        raw_params: list[tuple[str, str]] = []
        for segment in _split_top_level_pipes(block)[1:]:
            if "=" not in segment:
                continue
            key, val = segment.split("=", 1)
            key = key.strip()
            val = val.strip()
            if key in {"表格列数"}:
                continue
            title_match = re.fullmatch(r"标题(\d+)", key)
            if title_match:
                title_idx = int(title_match.group(1))
                clean_title = val.split("#", 1)[0].strip()
                titles_by_idx[title_idx] = clean_title
                continue
            raw_params.append((key, val))

        rows_by_idx: dict[int, dict[str, str]] = {}
        for key, val in raw_params:
            row_match = re.fullmatch(r"(.+?)(\d+)", key)
            if not row_match:
                continue
            col_name = row_match.group(1).strip()
            row_idx = int(row_match.group(2))
            row_dict = rows_by_idx.setdefault(row_idx, {})
            row_dict[col_name] = val

        ordered_titles = [titles_by_idx[idx] for idx in sorted(titles_by_idx)]
        rows: list[dict[str, str]] = []
        for r_idx in sorted(rows_by_idx):
            row = rows_by_idx[r_idx]
            if ordered_titles and not any(t in row for t in ordered_titles):
                # 兜底支持某些列键未严格匹配标题文字的情况
                rows.append(row)
            else:
                rows.append(row)
        if rows:
            tables.append(rows)
    return tables


def parse_wiki_generated_list(
    wikitext: str,
    *,
    required_column: Optional[str] = None,
) -> list[dict[str, str]]:
    """解析第一个匹配（或全部拼接）的 BWIKI 生成列表行字典。"""
    blocks = parse_wiki_generated_list_blocks(wikitext)
    if required_column:
        matched: list[dict[str, str]] = []
        for table in blocks:
            if any(required_column in row for row in table):
                matched.extend(table)
        return matched
    return blocks[0] if blocks else []


def parse_power_motors_wikitext(wikitext: str) -> list[dict[str, int]]:
    """从「整顿中心」词条解析电力中心 1~20 次模块供电消耗表。"""
    rows = parse_wiki_generated_list(wikitext, required_column="模块安装次数")
    motors: list[dict[str, int]] = []
    for row in rows:
        slot = _parse_int_prefix(row.get("模块安装次数", ""), 0)
        materials = parse_cn_resource_pairs(row.get("所需材料", ""))
        if slot <= 0:
            continue
        motors.append(
            {
                "slot": slot,
                "huashi": int(materials.get("桦石", 0)),
                "coins": int(materials.get("铁盟币", 0)),
            }
        )
    motors.sort(key=lambda item: item["slot"])
    return motors


def parse_sewing_machine_upgrades_wikitext(wikitext: str) -> list[dict[str, Any]]:
    """从「整顿中心/制造加工/生产车间/*」解析缝纫机 1→10 级升级表。"""
    rows = parse_wiki_generated_list(wikitext, required_column="升级所需材料")
    upgrades: list[dict[str, Any]] = []
    for row in rows:
        level = _parse_int_prefix(row.get("等级", ""), 0)
        materials = parse_cn_resource_pairs(row.get("升级所需材料", ""))
        if level <= 0 or not materials:
            continue
        upgrades.append(
            {
                "from_level": level,
                "to_level": level + 1,
                "coins": int(materials.get("铁盟币", 0)),
                "work_tickets": int(materials.get("整顿中心工票", 0)),
                "extra_output_percent": float(level + 1),
                "required_research_level": 6,
            }
        )
    upgrades.sort(key=lambda item: item["from_level"])
    return upgrades


def parse_raw_workshop_upgrades_wikitext(wikitext: str) -> list[dict[str, Any]]:
    """从「整顿中心/制造加工/*原料车间」解析原料车间 1~10 级建造升级表。"""
    rows = parse_wiki_generated_list(wikitext, required_column="囚犯数量")
    upgrades: list[dict[str, Any]] = []
    for row in rows:
        to_level = _parse_int_prefix(row.get("等级", ""), 0)
        materials = parse_cn_resource_pairs(row.get("升级所需材料", ""))
        if to_level <= 0:
            continue
        upgrades.append(
            {
                "from_level": to_level - 1,
                "to_level": to_level,
                "coins": int(materials.get("铁盟币", 0)),
                "power_cost": _parse_int_prefix(row.get("电力需求", ""), 0),
                "prisoner_slots": _parse_int_prefix(row.get("囚犯数量", ""), 0),
                "extra_output_percent": _parse_float_prefix(row.get("额外产出", ""), 0.0),
                "build_minutes": _parse_int_prefix(row.get("升级所需时间", ""), 0),
            }
        )
    upgrades.sort(key=lambda item: item["to_level"])
    return upgrades


def parse_black_moon_orders_wikitext(wikitext: str) -> list[dict[str, Any]]:
    """从「云岫桥基地/黑月服装订单站」解析全量黑月订单条目。"""
    rows = parse_wiki_generated_list(wikitext, required_column="需求物资")
    orders: list[dict[str, Any]] = []
    for row in rows:
        item_name, quantity = parse_single_name_qty(row.get("需求物资", ""))
        rewards = parse_cn_resource_pairs(row.get("奖励", ""))
        if not item_name:
            continue
        orders.append(
            {
                "unlock_prison_level": _parse_int_prefix(row.get("解锁所需等级", ""), 1),
                "item_name": item_name,
                "quantity": quantity,
                "weight": _parse_int_prefix(row.get("权重", ""), 0),
                "reward_coins": int(rewards.get("铁盟币", 0)),
                "reward_exp": int(rewards.get("整顿中心经验", 0)),
                "reward_work_tickets": int(rewards.get("整顿中心工票", 0)),
            }
        )
    return orders


def parse_exchange_shop_wikitext(wikitext: str) -> list[dict[str, Any]]:
    """从「整顿中心」解析兑换商店道具与研发配方兑换项。"""
    blocks = parse_wiki_generated_list_blocks(wikitext)
    items: list[dict[str, Any]] = []
    for table in blocks:
        if not any("可兑换物" in row for row in table):
            continue
        for row in table:
            name, per_qty = parse_single_name_qty(row.get("可兑换物", ""))
            materials = parse_cn_resource_pairs(row.get("所需材料", ""))
            if not name:
                continue
            is_recipe = any(suffix in name for suffix in ("织造法", "剪裁法", "缝制法", "缝制指南", "粘制法", "取制法", "制造法"))
            items.append(
                {
                    "name": name,
                    "per_exchange_qty": per_qty,
                    "max_exchanges": _parse_int_prefix(row.get("可兑换次数", ""), 1),
                    "coins": int(materials.get("铁盟币", 0)),
                    "work_tickets": int(materials.get("整顿中心工票", 0)),
                    "huashi": int(materials.get("桦石", 0)),
                    "is_recipe": is_recipe,
                }
            )
    return items


def fetch_bwiki_page_wikitext(title: str, *, timeout_seconds: float = 20.0) -> str:
    """单页串行请求 BWIKI MediaWiki API；遇到 567 限流或非 200 立即中止。"""
    params = urllib.parse.urlencode(
        {
            "action": "query",
            "prop": "revisions",
            "titles": title,
            "rvslots": "main",
            "rvprop": "content|timestamp",
            "format": "json",
            "formatversion": "2",
        }
    )
    url = f"{BWIKI_API_URL}?{params}"
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "MaaResonancePlanningCatalogSync/1.0 (+https://github.com/DaiMao204/MaaResonance)",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        if response.status != 200:
            raise RuntimeError(f"BWIKI returned HTTP {response.status} for {title}")
        raw = response.read().decode("utf-8")
    payload = json.loads(raw)
    pages = payload.get("query", {}).get("pages") or []
    if not pages or pages[0].get("missing"):
        raise RuntimeError(f"BWIKI page not found: {title}")
    revisions = pages[0].get("revisions") or []
    if not revisions:
        raise RuntimeError(f"BWIKI page has no revisions: {title}")
    return str(revisions[0]["slots"]["main"]["content"])


def sync_bwiki_prison_catalog(
    output_path: Path = DEFAULT_OUTPUT_PATH,
    *,
    delay_seconds: float = DEFAULT_REQUEST_DELAY_SECONDS,
) -> dict[str, Any]:
    """低频串行从 BWIKI 同步整顿中心静态扩张表（运行时不调用，仅供人工离线更新）。"""
    if delay_seconds < MIN_REQUEST_DELAY_SECONDS:
        raise ValueError(
            f"Refusing BWIKI sync with delay {delay_seconds}s < {MIN_REQUEST_DELAY_SECONDS}s (HTTP 567 rate limit guard)."
        )

    titles = [
        "整顿中心",
        "云岫桥基地/黑月服装订单站",
        "整顿中心/制造加工/生产车间/纺织品",
        "整顿中心/制造加工/缝纫工具原料车间",
    ]
    pages_wikitext: dict[str, str] = {}
    for index, title in enumerate(titles):
        if index > 0:
            time.sleep(delay_seconds)
        pages_wikitext[title] = fetch_bwiki_page_wikitext(title)

    catalog = {
        "meta": {
            "version": 1,
            "synced_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "source": "wiki.biligame.com/resonance",
        },
        "power_motors": parse_power_motors_wikitext(pages_wikitext["整顿中心"]),
        "exchange_shop": parse_exchange_shop_wikitext(pages_wikitext["整顿中心"]),
        "black_moon_orders": parse_black_moon_orders_wikitext(pages_wikitext["云岫桥基地/黑月服装订单站"]),
        "sewing_machine_upgrades": parse_sewing_machine_upgrades_wikitext(
            pages_wikitext["整顿中心/制造加工/生产车间/纺织品"]
        ),
        "raw_workshop_upgrades": parse_raw_workshop_upgrades_wikitext(
            pages_wikitext["整顿中心/制造加工/缝纫工具原料车间"]
        ),
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(catalog, ensure_ascii=False, indent=2), encoding="utf-8")
    return catalog


def main(argv: Optional[Sequence[str]] = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

    parser = argparse.ArgumentParser(
        description="低频串行从 BWIKI 离线同步整顿中心静态数据表（写入 resources/planning/）",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument(
        "--delay",
        type=float,
        default=DEFAULT_REQUEST_DELAY_SECONDS,
        help=f"串行请求间隔秒数（硬性下限 {MIN_REQUEST_DELAY_SECONDS}s，防止触发 567 限流）",
    )
    args = parser.parse_args(argv)
    catalog = sync_bwiki_prison_catalog(args.output, delay_seconds=args.delay)
    print(
        "Synced BWIKI prison catalog -> "
        f"{args.output} ("
        f"motors={len(catalog['power_motors'])}, "
        f"orders={len(catalog['black_moon_orders'])}, "
        f"shop={len(catalog['exchange_shop'])})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
