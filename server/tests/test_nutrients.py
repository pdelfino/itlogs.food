import pytest

from itlogs import nutrients


def test_grams_times_per_100g():
    n = nutrients.for_grams("cooked white rice", 200)
    assert n is not None
    assert (n.kcal, n.protein_g, n.carbs_g) == (260.0, 5.4, 56.4)


def test_aliases_and_normalization():
    assert nutrients.canonical("  Rice ") == "cooked white rice"
    assert nutrients.canonical("Egg White") == "egg whites"
    assert nutrients.canonical("quinoa") == "quinoa"


def test_salt_is_sodium():
    n = nutrients.for_grams("sea salt", 1.0)
    assert n is not None and n.sodium_mg == pytest.approx(387.6)


def test_unknown_food_has_no_nutrients():
    assert nutrients.for_grams("quinoa", 100) is None
