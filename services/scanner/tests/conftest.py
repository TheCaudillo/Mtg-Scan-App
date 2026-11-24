import gzip
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

FIXTURES = Path(__file__).parent / "fixtures"

CC_ORACLE = "oracle-cathar"
CC_ILL = "ill-cathar"


def _card(**kw):
    base = {
        "object": "card", "lang": "en", "games": ["paper"], "digital": False, "layout": "normal",
        "rarity": "common", "border_color": "black", "frame": "2015", "frame_effects": [], "promo_types": [],
        "full_art": False, "promo": False, "finishes": ["nonfoil", "foil"], "set_type": "expansion",
        "type_line": "Creature — Human Soldier", "oracle_text": "Flash", "artist": "Eyyn Fong",
        "image_uris": {"normal": "https://img/n.jpg", "small": "https://img/s.jpg", "art_crop": "https://img/a.jpg"},
        "scryfall_uri": "https://scryfall.com/card/x",
    }
    base.update(kw)
    return base


CARDS = [
    _card(id="cc-mid", oracle_id=CC_ORACLE, illustration_id=CC_ILL, name="Cathar Commando", set="mid",
          set_name="Innistrad: Midnight Hunt", collector_number="10", released_at="2021-09-24",
          prices={"usd": "0.21", "usd_foil": "0.33"}),
    _card(id="cc-inr", oracle_id=CC_ORACLE, illustration_id=CC_ILL, name="Cathar Commando", set="inr",
          set_name="Innistrad Remastered", collector_number="15", released_at="2025-01-24",
          prices={"usd": "0.27", "usd_foil": "0.30"}),
    _card(id="cc-fdn", oracle_id=CC_ORACLE, illustration_id=CC_ILL, name="Cathar Commando", set="fdn",
          set_name="Foundations", collector_number="139", released_at="2024-11-15",
          prices={"usd": "0.32", "usd_foil": "0.31"}),
    _card(id="cc-dbl", oracle_id=CC_ORACLE, illustration_id="ill-cathar-dbl", name="Cathar Commando", set="dbl",
          set_name="Innistrad: Double Feature", collector_number="10", released_at="2022-01-28",
          frame_effects=["inverted"], prices={"usd": "0.49", "usd_foil": "12.49"}),
    # Spanish printing of MID #10 (present only with an all_cards --langs en,es sync)
    _card(id="cc-mid-es", oracle_id=CC_ORACLE, illustration_id=CC_ILL, name="Cathar Commando",
          printed_name="Comando cátaro", lang="es", set="mid", set_name="Innistrad: Midnight Hunt",
          collector_number="10", released_at="2021-09-24", prices={"usd": None, "usd_foil": None}),
    # price inversion: non-foil > foil
    _card(id="sword", oracle_id="oracle-sword", illustration_id="ill-sword", name="Sword of Once and Future",
          set="mom", set_name="March of the Machine", collector_number="265", rarity="mythic",
          released_at="2023-04-21", prices={"usd": "6.10", "usd_foil": "5.38"}, type_line="Artifact — Equipment"),
    _card(id="sword-ext", oracle_id="oracle-sword", illustration_id="ill-sword", name="Sword of Once and Future",
          set="mom", set_name="March of the Machine", collector_number="375", rarity="mythic",
          released_at="2023-04-21", frame_effects=["extendedart"], prices={"usd": "5.72", "usd_foil": "6.91"}),
    # foil-only star printing, and non-foil-only white border
    _card(id="reclaim-star", oracle_id="oracle-reclaim", illustration_id="ill-reclaim", name="Reclaim", set="9ed",
          set_name="Ninth Edition", collector_number="264★", finishes=["foil"], released_at="2005-07-29",
          prices={"usd": None, "usd_foil": "2.02"}),
    _card(id="reclaim-9ed", oracle_id="oracle-reclaim", illustration_id="ill-reclaim", name="Reclaim", set="9ed",
          set_name="Ninth Edition", collector_number="264", finishes=["nonfoil"], border_color="white",
          released_at="2005-07-29", prices={"usd": "2.35", "usd_foil": None}),
    # Japanese-only printing with no English equivalent and no price
    _card(id="jp-only", oracle_id="oracle-jp", illustration_id="ill-jp", name="Some JP Promo", lang="ja",
          printed_name="日本語プロモ", set="pjp", set_name="JP Promos", collector_number="1", promo=True,
          set_type="promo", released_at="2020-01-01", prices={"usd": None, "usd_foil": None}),
    # special treatments
    _card(id="sld-bolt", oracle_id="oracle-bolt", illustration_id="ill-bolt-sld", name="Lightning Bolt", set="sld",
          set_name="Secret Lair Drop", collector_number="1500", border_color="borderless", finishes=["foil"],
          promo_types=["surgefoil"], rarity="rare", released_at="2023-01-01", prices={"usd": None, "usd_foil": "9.99"}),
    # filtered out: digital-only
    _card(id="arena", oracle_id="oracle-arena", illustration_id="ill-arena", name="Arena Only", set="ymid",
          collector_number="1", digital=True, games=["arena"], released_at="2022-01-01", prices={}),
]


@pytest.fixture(scope="session")
def db_path(tmp_path_factory):
    from scanner.scryfall_sync import sync

    d = tmp_path_factory.mktemp("db")
    bulk = d / "default-cards-test.jsonl.gz"
    with gzip.open(bulk, "wt", encoding="utf-8") as f:
        for c in CARDS:
            f.write(json.dumps(c) + "\n")
    path = d / "scryfall.db"
    sync(bulk_file=bulk, db_path=path)
    return path


@pytest.fixture()
def db(db_path):
    from scanner.db import ScryfallDB
    return ScryfallDB(db_path)


@pytest.fixture()
def resolver(db):
    from scanner.match.resolver import Resolver
    return Resolver(db)
