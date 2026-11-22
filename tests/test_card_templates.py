import tempfile
import unittest
from pathlib import Path

import numpy as np

from maa_resonance.logic.card_templates import (
    BOX_COL_CENTERS_X,
    BOX_ROW_CENTERS_Y,
    extract_box_deck_templates,
    identify_card_at_center,
    load_deck_templates,
    save_deck_templates,
)


class CardTemplatesTest(unittest.TestCase):
    def _build_synthetic_box_frame(self) -> tuple[np.ndarray, list[dict]]:
        img = np.full((720, 1280, 3), 25, dtype=np.uint8)
        entries: list[dict] = []
        card_defs = [
            (0, 0, "肉断大斧", 2, (30, 30, 230)),
            (0, 1, "弃牌", 0, (220, 220, 220)),
            (0, 2, "连涌", 2, (20, 210, 230)),
            (1, 0, "洗牌", 3, (40, 190, 220)),
        ]
        for r_idx, c_idx, name, cost, color in card_defs:
            xc = BOX_COL_CENTERS_X[c_idx]
            yc = BOX_ROW_CENTERS_Y[r_idx]
            # Paint distinctive right-half diamond stripe pattern
            img[yc - 40 : yc + 40, xc + 6 : xc + 44, :] = color
            img[yc - 15 : yc + 15, xc + 16 : xc + 32, :] = (255, 255, 255)
            entries.append({"text": name, "box": [xc - 30, yc + 52, 60, 16]})
            entries.append({"text": str(cost), "box": [xc + 24, yc - 88, 18, 18]})
        return img, entries

    def test_extract_save_load_and_identify_card(self):
        box_img, entries = self._build_synthetic_box_frame()
        deck = extract_box_deck_templates(box_img, entries)
        self.assertGreaterEqual(len(deck["cards"]), 4)
        self.assertIn("肉断大斧", deck["card_weights"])
        self.assertIn("连涌", deck["card_weights"])
        self.assertIsNotNone(deck["discard_weight"])
        self.assertGreater(deck["card_weights"]["肉断大斧"], deck["discard_weight"])
        self.assertLess(deck["card_weights"]["连涌"], deck["discard_weight"])

        with tempfile.TemporaryDirectory() as tmpdir:
            saved = save_deck_templates(Path(tmpdir) / "deck.json", deck)
            loaded = load_deck_templates(saved)
            self.assertIsNotNone(loaded)

            # Build synthetic battle frame containing 肉断大斧 at center (350, 588)
            battle = np.full((720, 1280, 3), 20, dtype=np.uint8)
            battle[588 - 40 : 588 + 40, 350 + 6 : 350 + 44, :] = (30, 30, 230)
            battle[588 - 15 : 588 + 15, 350 + 16 : 350 + 32, :] = (255, 255, 255)

            cid, cost, score = identify_card_at_center(battle, 350, loaded, min_score=0.70)
            self.assertEqual(cid, "肉断大斧")
            self.assertEqual(cost, 2)
            self.assertGreaterEqual(score, 0.70)

            # Distinct yellow card should NOT match red card 肉断大斧
            yellow_battle = np.full((720, 1280, 3), 20, dtype=np.uint8)
            yellow_battle[588 - 40 : 588 + 40, 350 + 6 : 350 + 44, :] = (20, 210, 230)
            cid2, _, _ = identify_card_at_center(yellow_battle, 350, loaded, min_score=0.66)
            self.assertNotEqual(cid2, "肉断大斧")


if __name__ == "__main__":
    unittest.main()
