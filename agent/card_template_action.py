from __future__ import annotations

from pathlib import Path
from typing import Any

from maa.agent.agent_server import AgentServer
from maa.context import Context
from maa.custom_action import CustomAction

from agent.utils.action_helpers import ocr_roi
from agent.utils.input_guard import safe_screencap
from maa_resonance.logic.card_templates import extract_box_deck_templates, save_deck_templates

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DECK_CACHE_PATH = PROJECT_ROOT / "debug" / "card_templates" / "active_deck.json"

# Dedicated narrow bands avoid character portrait textures confusing OCR det.
BOX_OCR_ROIS = (
    [80, 182, 1120, 44],   # Row 1 costs
    [80, 324, 1120, 34],   # Row 1 names
    [80, 372, 1120, 44],   # Row 2 costs
    [80, 514, 1120, 34],   # Row 2 names
    [80, 562, 1120, 44],   # Row 3 costs
)


def _ocr_box_bands(context: Context, image: Any, node_name: str) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for idx, roi in enumerate(BOX_OCR_ROIS):
        entries.extend(ocr_roi(context, image, f"{node_name}Band{idx}", roi))
    return entries


@AgentServer.custom_action("sync_box_card_templates")
class SyncBoxCardTemplatesAction(CustomAction):
    """Capture card diamond templates, costs, and priority weights from Box custom-weight UI."""

    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        image = safe_screencap(context)
        if image is None:
            return False
        entries = _ocr_box_bands(context, image, f"{argv.node_name}BoxOCR")
        deck = extract_box_deck_templates(image, entries)
        save_path = save_deck_templates(DEFAULT_DECK_CACHE_PATH, deck)
        named_count = sum(1 for c in deck["cards"] if not c["card_id"].startswith("R"))
        print(
            f"[SyncCardTemplates] saved {len(deck['cards'])} cards "
            f"(named={named_count}, discard_weight={deck['discard_weight']}) -> {save_path}",
            flush=True,
        )
        return bool(deck["cards"])
