"""Printed nutrition facts, once found, stay found (#13): a product's label does not change between
meals and the web search takes about 30 s. Kept under server/.cache/facts/, out of git, and only
numbers that passed the checks in session.row_from_facts."""

from __future__ import annotations

import logging
import re
from pathlib import Path

from itlogs.models import LabelFacts, WrapperLabel

log = logging.getLogger("itlogs.facts")

CACHE = Path(__file__).resolve().parents[1] / ".cache" / "facts"


def key(label: WrapperLabel) -> str:
    """Brand, flavour and net weight: the reader words a product line differently between looks
    ("Snack Bar Crispy", "Crispy"), and these three stay put."""
    text = f"{label.brand or ''} {label.flavour or label.product or ''}".lower()
    words = sorted(set(re.findall(r"[a-z0-9]+", text)))
    return "-".join(words)[:120] + f"-{label.net_grams or 0:g}"


def _load(path: Path) -> LabelFacts | None:
    try:
        return LabelFacts.model_validate_json(path.read_text())
    except (OSError, ValueError):
        return None


def get(label: WrapperLabel) -> LabelFacts | None:
    found = _load(CACHE / f"{key(label)}.json")
    if found is not None or label.flavour or label.product or not label.brand:
        return found
    # only the brand was legible (16:05, 2026-NOVEMBER-04): that brand's saved label, if it has
    # exactly one. The caller still checks it against the protein printed on the wrapper.
    words = set(re.findall(r"[a-z0-9]+", label.brand.lower()))
    saved = [p for p in CACHE.glob("*.json") if words <= set(p.stem.split("-"))]
    return _load(saved[0]) if len(saved) == 1 else None


def put(label: WrapperLabel, facts: LabelFacts) -> None:
    try:
        CACHE.mkdir(parents=True, exist_ok=True)
        (CACHE / f"{key(label)}.json").write_text(facts.model_dump_json())
    except OSError as e:  # a read-only checkout: the row still has its numbers
        log.warning("could not keep the facts for %s: %s", label.name, e)
