"""Detector on synthetic binder photos, OCR parsing, want-list parsing, exporters, failure isolation."""
import asyncio
import json
from pathlib import Path

import cv2
import numpy as np
import pytest

from scanner.detect import get_detector
from scanner.detect.grid import iou_rect
from scanner.match.ocr import parse_strip
from scanner.store import parse_wantlist

FIX = Path(__file__).parent / "fixtures"


@pytest.mark.parametrize("name,key,chrome", [
    ("binder_flat.jpg", "flat_boxes", False),
    ("binder_angled.jpg", "angled_quads", None),
    ("binder_whatsapp.jpg", "whatsapp_quads", True),
])
def test_detector_finds_nine_and_skips_partials(name, key, chrome):
    m = json.loads((FIX / "binder_manifest.json").read_text())
    gt = m[key]
    if key == "flat_boxes":
        gt = [[[a, b], [c, b], [c, d], [a, d]] for a, b, c, d in gt]
    gt = [np.array(q, np.float32) for q in gt]
    res = get_detector("opencv").detect(cv2.imread(str(FIX / name)))
    assert len(res.cards) == 9, res.method
    for c in res.cards:
        assert iou_rect(c.quad, gt[c.slot - 1])[0] > 0.85, f"slot {c.slot}"
    if chrome is not None:
        assert res.chrome_cropped is chrome


def test_manual_grid():
    img = cv2.imread(str(FIX / "binder_flat.jpg"))
    h, w = img.shape[:2]
    res = get_detector().detect(img, {"corners": [[0, 0], [w, 0], [w, h], [0, h]], "rows": 4, "cols": 3})
    assert len(res.cards) == 12 and res.method == "manual_grid"
    assert [c.slot for c in res.cards] == list(range(1, 13))


@pytest.mark.parametrize("text,exp", [
    ("010/277 C\nMID • EN EYYN FONG", ("10", "mid", "en", "C")),
    ("195/272 C\nORI + EN ANDREW ROBINS", ("195", "ori", "en", "C")),
    ("M 0265\nMOMe«EN JOSHUA CAIROS", ("265", "mom", "en", "M")),
    ("0139 C\nFDN ★ ES ARTIST", ("139", "fdn", "es", "C")),
])
def test_parse_strip(text, exp):
    r = parse_strip(text)
    assert (r.collector_number, r.set_code, r.language, r.rarity_letter) == exp
    assert r.foil_symbol == ("star" if "★" in text else None)  # OCR never asserts a dot


def test_parse_wantlist_plain_and_csv():
    wl = parse_wantlist("4 Lightning Bolt\nSol Ring (CMR) 472\n# comment\nThoughtseize")
    assert [(i.name, i.set_code, i.quantity) for i in wl.items] == [
        ("Lightning Bolt", None, 4), ("Sol Ring", "cmr", 1), ("Thoughtseize", None, 1)]
    wl = parse_wantlist("Name,Quantity,Set\nReclaim,2,ORI\n")
    assert wl.items[0].name == "Reclaim" and wl.items[0].quantity == 2 and wl.items[0].set_code == "ori"


def test_exporters(resolver):
    from scanner.exporters import EXPORTERS
    from scanner.models import BatchRecord, CardRecord, LotSettings, PageRecord, VisionRead
    from scanner.pipeline import result_to_record

    r = resolver.resolve([], VisionRead(name="Cathar Commando", set_code="mid", collector_number="10",
                                        language="es", foil_symbol="dot", foil_sheen="none"), "t")
    card = result_to_record(r, CardRecord(id="c1", batch_id="b", page_id="p", slot=1, row=0, col=0))
    batch = BatchRecord(id="b", name="Lot", pages=[PageRecord(id="p", batch_id="b", index=0, filename="x",
                                                                image_url="/x")], cards=[card])
    out = {k: f(batch, LotSettings()) for k, (f, _, _) in EXPORTERS.items()}
    assert out["csv"].splitlines()[0].startswith("Page,Slot,English Name,Printed Name,Language,Set Code")
    assert "Comando cátaro" in out["csv"] and "english_equivalent" in out["csv"]
    assert out["manabox"].splitlines()[1].startswith("Cathar Commando,MID,")
    assert '"1","0","Cathar Commando","mid","Near Mint","Spanish",""' in out["moxfield"]
    assert "| 1 | 1 | [Cathar Commando]" in out["markdown"]


def test_one_bad_card_never_sinks_the_page(db):
    from scanner.detect.base import CardCrops
    from scanner.match.base import FieldReader
    from scanner.match.hybrid import HybridMatcher

    class Boom(FieldReader):
        async def read(self, crops):
            raise RuntimeError("provider exploded")

    blank = np.zeros((680, 488, 3), np.uint8)
    crops = [CardCrops(blank, blank, blank, blank, blank) for _ in range(3)]
    m = HybridMatcher(db, visual=None, ocr=None, vision=Boom(), mode="vision")
    res = asyncio.run(m.match_cards(crops))
    assert len(res) == 3 and all(r.selected is None and r.error for r in res)
