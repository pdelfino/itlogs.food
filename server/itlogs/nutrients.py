"""Grams to nutrients: grams × a per-100 g row from the Canadian Nutrient File (issue #3).

Three layers, in order: a curated map of plain names to CNF food codes (what the reader says,
"banana", "chicken breast", to one CNF row), a few rows the CNF does not have (plant milks,
label values), and a careful search over the CNF names for everything else. Unknown stays
unknown: the entry logs its grams and the table shows "?". Salt is in the map on purpose: 1 g
of table salt is about 388 mg of sodium, and no camera sees salt, which is why it gets weighed
like everything else.

Data: itlogs/data/cnf.csv, built by scripts/cnf_snapshot.py (see data/README.org for the
licence).
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from itlogs.models import Nutrients

Row = tuple[float, float, float, float, float, float]  # kcal, protein, carbs, fat, fiber, sodium

CNF_CSV = Path(__file__).resolve().parent / "data" / "cnf.csv"

# plain name -> CNF food code (the name in the comment is the CNF's)
CURATED: dict[str, int] = {
    "cooked white rice": 4523,  # Grains, rice, white, long-grain, regular, cooked
    "cooked brown rice": 4497,  # Grains, rice, brown, long-grain, cooked
    "cooked quinoa": 5917,
    "cooked pasta": 4464,  # Pasta, spaghetti, enriched, cooked
    "oats": 4421,  # Grains, oats (dry)
    "cooked oatmeal": 1465,  # Cereal, hot, oats, large flakes, prepared
    "white bread": 4066,  # Bread, white, commercial
    "bagel": 3671,  # plain
    "tortilla": 4049,  # flour
    "rice cakes": 4124,
    "chicken breast": 842,  # Chicken, broiler, breast, meat, roasted
    "chicken thigh": 854,
    "turkey breast": 743,
    "ground beef": 2687,  # Beef, ground, lean, broiled
    "beef steak": 6146,  # top sirloin, lean, broiled
    "pork loin": 1780,
    "cooked salmon": 3183,  # Fish, salmon, atlantic, farmed, baked or broiled
    "canned tuna": 3081,
    "sardines": 3203,
    "cod": 3195,  # atlantic, baked or broiled
    "shrimp": 3212,
    "egg whites": 126,  # Egg, chicken, white, fresh or frozen, raw
    "cooked egg whites": 6605,
    "whole egg": 125,  # Egg, chicken, whole, fresh or frozen, raw
    "boiled egg": 130,
    "scrambled eggs": 133,
    "tofu": 3418,
    "lentils": 3393,  # boiled
    "chickpeas": 7061,  # canned, drained, rinsed
    "black beans": 3377,  # boiled
    "hummus": 4870,
    "canned pumpkin": 2192,
    "sweet potato": 2242,  # boiled without skin
    "potato": 2422,  # boiled without skin, flesh
    "banana": 1704,
    "apple": 1696,  # Apple, raw, with skin
    "orange": 1616,
    "pear": 1731,
    "peach": 1728,
    "mango": 1603,
    "pineapple": 1734,
    "kiwi": 1585,
    "grapes": 1718,  # red or green, European type, raw
    "watermelon": 1691,
    "blueberries": 1705,
    "strawberries": 1749,
    "lemon": 1587,
    "avocado": 1511,
    "tomato": 2460,
    "carrot": 2380,
    "cucumber": 2363,
    "onion": 2401,
    "garlic": 2394,
    "ginger": 2091,
    "red bell pepper": 2484,
    "green bell pepper": 2413,
    "broccoli": 2374,
    "cauliflower": 2385,
    "zucchini": 2225,
    "spinach": 2213,
    "lettuce": 2116,
    "mushrooms": 2399,
    "green beans": 2371,
    "corn": 2068,  # sweet, yellow, boiled
    "greek yogurt": 7469,  # Yogourt, Greek style, plain, 2% M.F.
    "yogurt": 6961,  # Yogourt, plain (2-3.9% M.F.)
    "cottage cheese": 120,
    "cheddar cheese": 119,
    "mozzarella": 110,
    "cream cheese": 28,
    "butter": 118,
    "ice cream": 4163,
    "2% milk": 61,
    "whole milk": 113,
    "skim milk": 114,
    "soy milk": 6720,
    "protein powder": 7231,  # Beverage, protein powder, whey based, powder
    "plant protein powder": 7232,  # Plant-based beverage, protein powder, soy based, powder
    "whey protein isolate": 7229,
    "olive oil": 422,
    "coconut oil": 420,
    "peanut butter": 6289,  # natural
    "almonds": 2534,
    "walnuts": 2590,
    "peanuts": 3362,
    "chia seeds": 2511,
    "flax seeds": 4528,
    "hemp seeds": 7568,
    "dark chocolate": 6672,  # 70-85% cacao
    "honey": 4294,
    "white sugar": 4318,
    "maple syrup": 6175,
    "mayonnaise": 531,
    "ketchup": 2494,
    "soy sauce": 3403,
    "coffee": 2873,
    "salt": 214,  # Salt, table
}

# foods the CNF 2015 does not have: label values per 100 g
# (kcal, protein, carbs, fat, fiber, sodium)
EXTRA: dict[str, Row] = {
    "oat milk": (46, 1.0, 6.6, 1.5, 0.8, 40),  # Oatly original
    "almond milk": (13, 0.4, 0.4, 1.0, 0.4, 63),  # unsweetened, Silk
}

ALIASES = {
    "white rice": "cooked white rice",
    "rice": "cooked white rice",
    "brown rice": "cooked brown rice",
    "quinoa": "cooked quinoa",
    "pasta": "cooked pasta",
    "spaghetti": "cooked pasta",
    "rolled oats": "oats",
    "oatmeal": "oats",
    # plain "cashews" matched the CNF's cashew drink, 23 kcal per 100 g (2026-NOVEMBER-04)
    "walnut": "walnuts",
    "almond": "almonds",
    "peanut": "peanuts",
    "raw oats": "oats",
    "cashew": "cashew nuts",
    "cashews": "cashew nuts",
    "porridge": "cooked oatmeal",
    "bread": "white bread",
    "chicken": "chicken breast",
    "turkey": "turkey breast",
    "beef": "ground beef",
    "steak": "beef steak",
    "pork": "pork loin",
    "salmon": "cooked salmon",
    "tuna": "canned tuna",
    "egg white": "egg whites",
    "liquid egg whites": "egg whites",
    "egg": "whole egg",
    "eggs": "whole egg",
    "whole eggs": "whole egg",
    "hard boiled egg": "boiled egg",
    "boiled eggs": "boiled egg",
    "scrambled egg": "scrambled eggs",
    "pumpkin": "canned pumpkin",
    "pumpkin puree": "canned pumpkin",
    "red apple": "apple",
    "green apple": "apple",
    "whole apple": "apple",
    "apples": "apple",
    "whole banana": "banana",
    "yellow banana": "banana",
    "bananas": "banana",
    "oranges": "orange",
    "pears": "pear",
    "blueberry": "blueberries",
    "strawberry": "strawberries",
    "grape": "grapes",
    "tomatoes": "tomato",
    "carrots": "carrot",
    "onions": "onion",
    "bell pepper": "red bell pepper",
    "red pepper": "red bell pepper",
    "green pepper": "green bell pepper",
    "mushroom": "mushrooms",
    "yogourt": "yogurt",
    "plain yogurt": "yogurt",
    "greek yogourt": "greek yogurt",
    "cheese": "cheddar cheese",
    "milk": "2% milk",
    "whole milk 3.25%": "whole milk",
    "skimmed milk": "skim milk",
    "soya milk": "soy milk",
    "almond beverage": "almond milk",
    "oat beverage": "oat milk",
    "whey protein": "protein powder",
    "whey protein powder": "protein powder",
    "protein": "protein powder",
    "powder": "protein powder",
    "pea protein": "plant protein powder",
    "vegan protein powder": "plant protein powder",
    "sugar": "white sugar",
    "table salt": "salt",
    "sea salt": "salt",
    "mayo": "mayonnaise",
    "oil": "olive oil",
    "cooking oil": "olive oil",
}


@dataclass(frozen=True)
class CnfRow:
    code: int
    name: str
    words: frozenset[str]
    segs: tuple[str, ...]  # the first two comma segments, lowercased ("melon", "cantaloupe")
    values: Row


def _num(s: str) -> float:
    return float(s) if s else 0.0


@lru_cache(maxsize=1)
def cnf() -> dict[int, CnfRow]:
    out: dict[int, CnfRow] = {}
    with CNF_CSV.open(encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            name = r["name"]
            words = frozenset(re.findall(r"[a-z0-9%]+", name.lower()))
            segs = tuple(seg.strip().lower() for seg in name.split(",")[:2])
            values = (
                _num(r["kcal"]),
                _num(r["protein_g"]),
                _num(r["carbs_g"]),
                _num(r["fat_g"]),
                _num(r["fiber_g"]),
                _num(r["sodium_mg"]),
            )
            out[int(r["code"])] = CnfRow(int(r["code"]), name, words, segs, values)
    return out


def normalize(food: str) -> str:
    return re.sub(r"\s+", " ", food.strip().lower())


# How a food was cut does not change it. "banana slices" had no row at all, and "sliced apple" and
# "sliced strawberries" found the canned and the sweetened frozen products (2026-NOVEMBER-04).
CUT_WORDS = frozenset(
    {"sliced", "slice", "slices", "chopped", "diced", "cubed", "halved", "peeled", "cut"}
    | {"piece", "pieces", "chunk", "chunks", "wedge", "wedges", "fresh"}
)


def canonical(food: str) -> str:
    """The curated name for a food, or the food itself when unknown. Words for how it was cut go
    only when what is left is a food the table knows: "chocolate chunks" stays as it is."""
    f = normalize(food)
    if f in ALIASES:
        return ALIASES[f]
    uncut = " ".join(w for w in f.split() if w not in CUT_WORDS)
    uncut = ALIASES.get(uncut, uncut)
    return uncut if uncut != f and (uncut in CURATED or uncut in EXTRA) else f


def search(food: str) -> CnfRow | None:
    """A careful match over the CNF names: every word of the query must be a word of the name,
    the shortest name wins, and a single word must be one of the name's first two segments
    ("banana" finds "Banana, raw", "cantaloupe" finds "Melon, cantaloupe, raw"; "oil" or
    "bowl" alone find nothing). Plurals are tried in the singular."""
    words = normalize(food).split()
    if not words:
        return None
    rows = cnf().values()
    hits = [r for r in rows if all(w in r.words for w in words)]
    if len(words) == 1:
        hits = [r for r in hits if words[0] in r.segs]
    if not hits:
        singular = [_singular(w) for w in words]
        if singular != words:
            return search(" ".join(singular))
        return None
    return min(hits, key=lambda r: (len(r.name), r.name))


def _singular(w: str) -> str:
    if len(w) > 4 and w.endswith("ies"):
        return w[:-3] + "y"  # cherries, blueberries
    if len(w) > 3 and w.endswith("s"):
        return w[:-1]
    return w


# A wrapper read by name ("protein bar", "granola bar", "chips") is a packaged product: the
# table's nearest generic row is a guess (21:23, 2026-NOVEMBER-03: "protein bar" became the
# CNF's yogourt-coated fruit granola bar, 25 g of carbs for a 4 g bar). No row: the barcode
# brings the label's numbers (#13), and until then the table shows "?".
PACKAGED_LAST_WORDS = frozenset({"bar", "bars", "chips", "crisps", "cracker", "crackers", "candy"})


def lookup(food: str) -> Row | None:
    name = canonical(food)
    code = CURATED.get(name)
    if code is not None:
        return cnf()[code].values
    if name in EXTRA:
        return EXTRA[name]
    if name.split()[-1:] and name.split()[-1] in PACKAGED_LAST_WORDS:
        return None
    hit = search(name)
    return hit.values if hit else None


def for_grams(food: str, grams: float) -> Nutrients | None:
    row = lookup(food)
    if row is None:
        return None
    return scale(row, grams)


def scale(row: Row, grams: float) -> Nutrients:
    """A per-100 g row (the CNF's or a product label's) at the grams on the scale."""
    k = grams / 100.0
    kcal, protein, carbs, fat, fiber, sodium = row
    return Nutrients(
        kcal=round(kcal * k, 1),
        protein_g=round(protein * k, 2),
        carbs_g=round(carbs * k, 2),
        fat_g=round(fat * k, 2),
        fiber_g=round(fiber * k, 2),
        sodium_mg=round(sodium * k, 1),
    )
