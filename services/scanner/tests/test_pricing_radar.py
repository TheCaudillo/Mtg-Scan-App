"""Spanish / non-English pricing fallback, finish detection, foil-inversion flags, treatments."""
from scanner.match.base import VisualHit
from scanner.models import VisionRead
from scanner.radar import detect_foil, treatments, unit_price, to_printing


def test_spanish_card_priced_from_english_equivalent(resolver):
    read = VisionRead(printed_name="Comando cátaro", language="es", set_code="mid", collector_number="10")
    r = resolver.resolve([VisualHit("ill-cathar", "cc-mid", 0.9)], read, "test")
    assert r.lang == "es"
    assert r.selected.scryfall_id == "cc-mid-es"          # localized printing chosen (all_cards sync)
    assert r.selected.printed_name == "Comando cátaro"
    assert r.price_source == "english_equivalent"
    assert r.selected.usd == 0.21 and r.selected.usd_foil == 0.33  # EN MID #10 prices
    assert "non_english" in r.flags


def test_spanish_card_without_localized_row(resolver):
    read = VisionRead(name="Cathar Commando", language="es", set_code="fdn", collector_number="139")
    r = resolver.resolve([], read, "test")
    assert r.selected.scryfall_id == "cc-fdn" and r.lang == "es"
    assert r.price_source == "english_equivalent"


def test_no_price_is_null_not_fabricated(resolver):
    r = resolver.resolve([], VisionRead(set_code="pjp", collector_number="1", language="ja"), "test")
    assert r.selected.scryfall_id == "jp-only"
    assert r.unit_price_usd is None and r.price_source is None


def test_foil_price_inversion_flag(resolver):
    r = resolver.resolve([], VisionRead(name="Sword of Once and Future", set_code="mom", collector_number="265"), "t")
    assert r.selected.price_inversion
    assert "foil_price_inversion" in r.flags
    assert r.foil_detection == "uncertain"
    assert "foil_price_inversion" in r.review_reasons
    # uncertain finish → conservative (lower) price
    assert r.unit_price_usd == 5.38


def test_clear_dot_resolves_finish(resolver):
    read = VisionRead(name="Sword of Once and Future", set_code="mom", collector_number="265",
                      foil_symbol="dot", foil_sheen="none")
    r = resolver.resolve([], read, "t")
    assert r.foil_detection == "nonfoil" and r.finish == "nonfoil" and r.unit_price_usd == 6.10
    assert "foil_price_inversion" not in r.review_reasons  # still flagged, but no review needed
    assert "foil_price_inversion" in r.flags


def test_glare_over_finish_with_big_gap(resolver):
    r = resolver.resolve([], VisionRead(set_code="dbl", collector_number="10"), "t")
    assert r.foil_detection == "uncertain"
    assert "glare_over_finish" in r.review_reasons


def test_detect_foil_rules():
    assert detect_foil(["foil"], None) == "foil"
    assert detect_foil(["nonfoil"], None) == "nonfoil"
    assert detect_foil(["nonfoil", "foil"], None) == "uncertain"
    assert detect_foil(["nonfoil", "foil"], VisionRead(foil_symbol="star")) == "foil"
    assert detect_foil(["nonfoil", "foil"], VisionRead(foil_symbol="dot", foil_sheen="none")) == "nonfoil"
    assert detect_foil(["nonfoil", "foil"], VisionRead(foil_symbol="dot", foil_sheen="clear")) == "foil"
    assert detect_foil(["nonfoil", "foil"], VisionRead(foil_symbol="unclear")) == "uncertain"


def test_unit_price(db):
    p = to_printing(db.by_id("cc-dbl"))
    assert unit_price(p, "foil", "foil") == 12.49
    assert unit_price(p, "nonfoil", "nonfoil") == 0.49
    assert unit_price(p, "nonfoil", "uncertain") == 0.49
    star = to_printing(db.by_id("reclaim-star"))
    assert unit_price(star, "nonfoil", "nonfoil") is None  # no fabricated price


def test_treatments(db):
    t = treatments(db.by_id("sld-bolt"))
    assert {"Borderless", "Surge Foil", "Secret Lair"} <= set(t)
    assert "Extended Art" in treatments(db.by_id("sword-ext"))
    assert "Mythic" in treatments(db.by_id("sword"))
    assert "White Border" in treatments(db.by_id("reclaim-9ed"))
