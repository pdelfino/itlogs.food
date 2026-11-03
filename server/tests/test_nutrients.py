import pytest

from itlogs import nutrients


def test_every_curated_code_is_in_the_snapshot():
    rows = nutrients.cnf()
    missing = {n: c for n, c in nutrients.CURATED.items() if c not in rows}
    assert missing == {}
    assert len(rows) > 5000


def test_grams_times_per_100g_from_the_cnf():
    n = nutrients.for_grams("cooked white rice", 200)  # CNF 4523, long-grain, cooked
    assert n is not None
    assert n.kcal == pytest.approx(260, abs=6)
    assert n.protein_g == pytest.approx(5.4, abs=0.4)
    assert n.carbs_g == pytest.approx(56, abs=3)


def test_aliases_and_normalization():
    assert nutrients.canonical("  Rice ") == "cooked white rice"
    assert nutrients.canonical("Egg White") == "egg whites"
    assert nutrients.canonical("whole banana") == "banana"
    assert nutrients.canonical("durian") == "durian"


def test_salt_is_sodium():
    n = nutrients.for_grams("sea salt", 1.0)
    assert n is not None and n.sodium_mg == pytest.approx(388, abs=2)


def test_the_cnf_rows_pedro_weighs():
    """Five CNF rows, checked against the source: the values are per 100 g."""
    assert nutrients.lookup("banana")[0] == pytest.approx(89, abs=3)  # type: ignore[index]
    assert nutrients.lookup("red apple")[0] == pytest.approx(52, abs=3)  # type: ignore[index]
    eggw = nutrients.lookup("egg whites")
    assert eggw is not None and eggw[1] == pytest.approx(10.5, abs=1)  # protein (CNF: 9.99)
    chicken = nutrients.lookup("chicken breast")
    assert chicken is not None and chicken[1] == pytest.approx(31, abs=1.5)
    milk = nutrients.lookup("milk")  # 2% by default
    assert milk is not None and milk[0] == pytest.approx(50, abs=4)


def test_search_finds_plain_cnf_names_and_refuses_containers():
    hit = nutrients.search("cantaloupe")
    assert hit is not None and "cantaloupe" in hit.name.lower()  # Melon, cantaloupe, raw
    assert nutrients.search("ceramic bowl") is None
    assert nutrients.search("bowl") is None
    assert nutrients.search("oil") is None  # one word must head the name
    assert nutrients.for_grams("cherries", 100) is not None  # plural tried in the singular


def test_label_rows_for_what_the_cnf_lacks():
    oat = nutrients.for_grams("oat milk", 250)
    assert oat is not None and oat.kcal == pytest.approx(115, abs=1)


def test_unknown_food_has_no_nutrients():
    assert nutrients.for_grams("zzz unknown thing", 100) is None
