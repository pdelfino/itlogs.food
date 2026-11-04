"""A barcode becomes a known food (#13): Open Food Facts, the open product database (ODbL),
per-100 g nutriments from the label. One lookup per EAN, cached on disk (server/.cache/off/,
ignored by git) so a bar scanned twice costs one request. No key, a User-Agent is the only
requirement of the API."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

import httpx

from itlogs.nutrients import Row

log = logging.getLogger("itlogs.off")

API = "https://world.openfoodfacts.org/api/v2/product/{ean}.json"
FIELDS = "product_name,brands,nutriments,serving_quantity"
USER_AGENT = "itlogs.food/0.1 (https://github.com/pdelfino/itlogs.food)"
CACHE = Path(__file__).resolve().parents[2] / ".cache" / "off"


@dataclass(frozen=True)
class Product:
    ean: str
    name: str  # "Quest Protein Bar, Cookies & Cream"
    brand: str | None
    per100g: Row  # kcal, protein, carbs, fat, fiber, sodium mg, per 100 g
    serving_g: float | None
    source: str = "openfoodfacts"


def _num(v: object) -> float | None:
    try:
        return float(v)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def parse(ean: str, data: dict) -> Product | None:
    """The API's JSON to a Product, or None when the code is unknown or the label has no
    energy value (the row would be a guess)."""
    if data.get("status") != 1 or not isinstance(data.get("product"), dict):
        return None
    p = data["product"]
    n = p.get("nutriments") or {}
    kcal = _num(n.get("energy-kcal_100g"))
    if kcal is None:
        kj = _num(n.get("energy_100g"))
        kcal = kj / 4.184 if kj is not None else None
    if kcal is None:
        return None
    sodium = _num(n.get("sodium_100g"))
    if sodium is None:
        salt = _num(n.get("salt_100g"))
        sodium = salt / 2.5 if salt is not None else 0.0
    row: Row = (
        round(kcal, 1),
        round(_num(n.get("proteins_100g")) or 0.0, 2),
        round(_num(n.get("carbohydrates_100g")) or 0.0, 2),
        round(_num(n.get("fat_100g")) or 0.0, 2),
        round(_num(n.get("fiber_100g")) or 0.0, 2),
        round(sodium * 1000.0, 1),
    )
    brand = (p.get("brands") or "").split(",")[0].strip() or None
    name = (p.get("product_name") or "").strip()
    if not name:
        name = f"{brand} product" if brand else f"product {ean}"
    elif brand and brand.lower() not in name.lower():
        name = f"{brand} {name}"
    return Product(
        ean=ean,
        name=name,
        brand=brand,
        per100g=row,
        serving_g=_num(p.get("serving_quantity")),
    )


def _cached(ean: str) -> dict | None:
    f = CACHE / f"{ean}.json"
    if f.exists():
        try:
            return json.loads(f.read_text())
        except json.JSONDecodeError:
            return None
    return None


def _cache(ean: str, data: dict) -> None:
    try:
        CACHE.mkdir(parents=True, exist_ok=True)
        (CACHE / f"{ean}.json").write_text(json.dumps(data))
    except OSError as e:  # a read-only checkout: the lookup still worked
        log.warning("could not cache %s: %s", ean, e)


async def lookup(
    ean: str, transport: httpx.AsyncBaseTransport | None = None, use_cache: bool = True
) -> Product | None:
    """The product behind an EAN-13, EAN-8 or UPC code; None when unknown or unreachable."""
    ean = "".join(ch for ch in ean if ch.isdigit())
    if not ean:
        return None
    data = _cached(ean) if use_cache else None
    if data is None:
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(8, connect=5),
                headers={"User-Agent": USER_AGENT},
                transport=transport,
            ) as http:
                r = await http.get(API.format(ean=ean), params={"fields": FIELDS})
        except httpx.HTTPError as e:
            log.warning("open food facts unreachable for %s: %s", ean, e)
            return None
        if r.status_code == 404:
            data = {"status": 0}
        else:
            try:
                data = r.json()
            except ValueError:
                return None
        if use_cache and data.get("status") == 1:
            _cache(ean, data)
    return parse(ean, data)
