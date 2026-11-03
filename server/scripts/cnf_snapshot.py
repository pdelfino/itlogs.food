"""Build server/data/cnf.csv from Health Canada's Canadian Nutrient File CSV bundle.

Usage: python server/scripts/cnf_snapshot.py <folder with FOOD NAME.csv and NUTRIENT AMOUNT.csv>

Source: Canadian Nutrient File (CNF), 2015, Health Canada, under the Open Government Licence,
Canada (https://open.canada.ca/en/open-government-licence-canada). The bundle is
cnf-fcen-csv.zip from canada.ca (about 5 MB, latin-1); the snapshot keeps one row per food with
the six nutrients the app writes to Apple Health, per 100 g. The bundle itself is not in git.
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

# CNF nutrient ids: energy kcal, protein, carbohydrate (by difference), fat, total dietary
# fibre, sodium
WANTED = {
    208: "kcal",
    203: "protein_g",
    205: "carbs_g",
    204: "fat_g",
    291: "fiber_g",
    307: "sodium_mg",
}
COLUMNS = ["code", "name", "kcal", "protein_g", "carbs_g", "fat_g", "fiber_g", "sodium_mg"]


def main(src: Path, out: Path) -> None:
    names: dict[str, tuple[str, str]] = {}  # FoodID -> (code, description)
    with (src / "FOOD NAME.csv").open(encoding="latin-1", newline="") as f:
        for r in csv.DictReader(f):
            names[r["FoodID"]] = (r["FoodCode"], r["FoodDescription"].strip())
    values: dict[str, dict[str, str]] = {}
    with (src / "NUTRIENT AMOUNT.csv").open(encoding="latin-1", newline="") as f:
        for r in csv.DictReader(f):
            key = WANTED.get(int(r["NutrientID"]))
            if key is None or r["FoodID"] not in names:
                continue
            values.setdefault(r["FoodID"], {})[key] = r["NutrientValue"].strip()
    rows = []
    for food_id, (code, name) in names.items():
        v = values.get(food_id, {})
        if "kcal" not in v:
            continue  # a food without energy is of no use to the app
        rows.append([code, name] + [v.get(k, "") for k in COLUMNS[2:]])
    rows.sort(key=lambda r: int(r[0]))
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(COLUMNS)
        w.writerows(rows)
    print(f"{len(rows)} foods -> {out}")


if __name__ == "__main__":
    here = Path(__file__).resolve().parents[1]
    main(Path(sys.argv[1]), here / "itlogs" / "data" / "cnf.csv")
