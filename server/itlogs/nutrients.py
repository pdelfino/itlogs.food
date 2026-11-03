"""Grams to nutrients: grams × a per-100 g row.

The table here is a placeholder of a dozen foods (USDA FoodData Central values, rounded) so the
loop works end to end; issue #3 replaces it with a lookup in the Canadian Nutrient File. Salt
is in the table on purpose: 1 g of salt is about 390 mg of sodium, and no camera sees salt,
which is why it gets weighed like everything else.
"""

from __future__ import annotations

import re

from itlogs.models import Nutrients

# per 100 g: kcal, protein_g, carbs_g, fat_g, fiber_g, sodium_mg
TABLE: dict[str, tuple[float, float, float, float, float, float]] = {
    "cooked white rice": (130, 2.7, 28.2, 0.3, 0.4, 1),
    "cooked brown rice": (123, 2.7, 25.6, 1.0, 1.6, 4),
    "chicken breast": (165, 31.0, 0.0, 3.6, 0.0, 74),
    "egg whites": (52, 10.9, 0.7, 0.2, 0.0, 166),
    "whole egg": (155, 12.6, 1.1, 10.6, 0.0, 124),
    "canned pumpkin": (34, 1.1, 8.1, 0.3, 2.9, 5),
    "oats": (389, 16.9, 66.3, 6.9, 10.6, 2),
    "banana": (89, 1.1, 22.8, 0.3, 2.6, 1),
    "apple": (52, 0.3, 13.8, 0.2, 2.4, 1),
    "orange": (47, 0.9, 11.8, 0.1, 2.4, 0),
    "avocado": (160, 2.0, 8.5, 14.7, 6.7, 7),
    "tomato": (18, 0.9, 3.9, 0.2, 1.2, 5),
    "carrot": (41, 0.9, 9.6, 0.2, 2.8, 69),
    "cucumber": (15, 0.7, 3.6, 0.1, 0.5, 2),
    "white bread": (265, 9.0, 49.0, 3.2, 2.7, 491),
    "greek yogurt": (59, 10.0, 3.6, 0.4, 0.0, 36),
    "cooked pasta": (158, 5.8, 30.9, 0.9, 1.8, 1),
    "cooked salmon": (206, 22.1, 0.0, 12.4, 0.0, 61),
    "ground beef": (250, 26.1, 0.0, 15.4, 0.0, 75),
    "sweet potato": (86, 1.6, 20.1, 0.1, 3.0, 55),
    "broccoli": (34, 2.8, 6.6, 0.4, 2.6, 33),
    "black beans": (132, 8.9, 23.7, 0.5, 8.7, 1),
    "olive oil": (884, 0.0, 0.0, 100.0, 0.0, 2),
    "peanut butter": (588, 25.1, 20.0, 50.4, 6.0, 17),
    "salt": (0, 0.0, 0.0, 0.0, 0.0, 38758),
}

ALIASES = {
    "white rice": "cooked white rice",
    "rice": "cooked white rice",
    "brown rice": "cooked brown rice",
    "chicken": "chicken breast",
    "egg white": "egg whites",
    "egg": "whole egg",
    "eggs": "whole egg",
    "pumpkin": "canned pumpkin",
    "pumpkin puree": "canned pumpkin",
    "rolled oats": "oats",
    "oatmeal": "oats",
    "table salt": "salt",
    "sea salt": "salt",
    "red apple": "apple",
    "green apple": "apple",
    "apples": "apple",
    "bananas": "banana",
    "oranges": "orange",
    "bread": "white bread",
    "pasta": "cooked pasta",
    "spaghetti": "cooked pasta",
    "salmon": "cooked salmon",
    "beef": "ground beef",
    "yogurt": "greek yogurt",
    "tomatoes": "tomato",
    "carrots": "carrot",
}


def normalize(food: str) -> str:
    return re.sub(r"\s+", " ", food.strip().lower())


def canonical(food: str) -> str:
    """The table's name for a food, or the food itself when unknown."""
    f = normalize(food)
    return ALIASES.get(f, f)


def lookup(food: str) -> tuple[float, float, float, float, float, float] | None:
    return TABLE.get(canonical(food))


def for_grams(food: str, grams: float) -> Nutrients | None:
    row = lookup(food)
    if row is None:
        return None
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
