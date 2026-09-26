"""Spot products that are really the same dish under a new name (US37).

The POS renames dishes ("EXTRA DE AGUACATE" comes back as "EXTRA AGUACATE").
The resolver matches what it safely can (:mod:`catalog.identity`), but a rename
it cannot prove creates a second product and splits the history in two. This
module surfaces the leftovers for a human to confirm.

The signal, validated against the real catalog: the names are similar **and the
sales windows hand off** -- one product stops selling right before the other
starts. Two filters remove the false alarms that signal alone produces:

* a different **serving group** means a different product (a wine by the glass
  is not the same as the bottle),
* **overlapping** sales windows mean the two coexist, so they are not a rename,
  and
* each name carrying a **word of its own** means two different dishes that merely
  share a family ("GLENFIDDICH 12" vs "GLENFIDDICH 15", "CATENA APELLATION SAN
  CARLOS" vs "CATENA APELLATION VISTA FLORES"). A plural or a spelled-out unit
  ("TOSTADA"/"TOSTADAS", "4"/"4UND") is not a word of its own.

A differing number ("ACQUA PANNA" vs "ACQUA PANNA * 505 ML") is deliberately
not filtered: it was a real rename, even though the same difference legitimately
separates 505 ML from 750 ML. It is shown with its evidence, not hidden.
"""
from __future__ import annotations

import difflib
from dataclasses import dataclass
from datetime import date

from django.db.models import Max, Min, Sum

from .identity import _serving_key, normalize_name
from .models import Product

# Measured against the real catalog: the six renames found in Junio/Julio 2026
# score 0.85-1.00, while genuinely different dishes that share a word top out at
# 0.76 ("GARZON MARSELAN" vs "GARZON RESERVA"). 0.80 sits in that gap.
_MIN_RATIO = 0.80


@dataclass(frozen=True)
class Candidate:
    """A pair that looks like one dish split in two, with its evidence."""

    keep: Product          # the longer history -- survives a merge
    merge: Product         # the newcomer -- folded into ``keep``
    ratio: float
    keep_last: date
    merge_first: date
    keep_units: int
    merge_units: int


def _sales_window(restaurant) -> dict[int, tuple[date, date, int]]:
    """First sale, last sale and units per product, in one query."""
    rows = (
        Product.objects.filter(restaurant=restaurant)
        .annotate(
            first=Min("sale_items__sale__occurred_at"),
            last=Max("sale_items__sale__occurred_at"),
            units=Sum("sale_items__quantity"),
        )
        .values("id", "first", "last", "units")
    )
    return {
        r["id"]: (r["first"].date(), r["last"].date(), r["units"] or 0)
        for r in rows
        if r["first"] and r["last"]
    }


def find_possible_duplicates(restaurant) -> list[Candidate]:
    """Pairs worth a human's eye, strongest evidence first."""
    products = list(
        Product.objects.filter(restaurant=restaurant).select_related("category")
    )
    window = _sales_window(restaurant)
    norm = {p.id: normalize_name(p.name) for p in products}

    # Only compare products sharing a word; everything else cannot be close.
    by_token: dict[str, list[Product]] = {}
    for product in products:
        for token in set(norm[product.id].split()):
            by_token.setdefault(token, []).append(product)

    seen: set[tuple[int, int]] = set()
    found: list[Candidate] = []
    for group in by_token.values():
        for i, a in enumerate(group):
            for b in group[i + 1:]:
                pair = (min(a.id, b.id), max(a.id, b.id))
                if pair in seen:
                    continue
                seen.add(pair)
                candidate = _judge(a, b, norm, window)
                if candidate is not None:
                    found.append(candidate)

    found.sort(key=lambda c: c.ratio, reverse=True)
    return found


def _each_has_its_own_word(norm_a: str, norm_b: str) -> bool:
    """True when both names carry a word the other lacks -- two different dishes.

    A rename only ever adds or drops words on one side ("ACQUA PANNA" gaining
    "505"), so when *each* side has a word of its own the two are siblings in a
    family, not the same dish. Plurals and spelled-out units are not words of
    their own: "TOSTADAS" is "TOSTADA", and "4UND" is the "4" it starts with.
    """
    only_a = set(norm_a.split()) - set(norm_b.split())
    only_b = set(norm_b.split()) - set(norm_a.split())
    if not only_a or not only_b:
        return False
    for token_a in only_a:
        for token_b in only_b:
            if token_a.startswith(token_b) or token_b.startswith(token_a):
                return False
            if difflib.SequenceMatcher(None, token_a, token_b).ratio() >= 0.85:
                return False
    return True


def _judge(a, b, norm, window) -> Candidate | None:
    """Return the pair as a candidate, or None when the evidence says no."""
    if a.id not in window or b.id not in window:
        return None  # one of them never sold: nothing to hand off

    # A wine by the glass is not the bottle.
    serving_a, serving_b = _serving_key(a.category.name), _serving_key(b.category.name)
    if serving_a and serving_b and serving_a != serving_b:
        return None

    ratio = difflib.SequenceMatcher(None, norm[a.id], norm[b.id]).ratio()
    if ratio < _MIN_RATIO:
        return None
    if _each_has_its_own_word(norm[a.id], norm[b.id]):
        return None

    first_a, last_a, units_a = window[a.id]
    first_b, last_b, units_b = window[b.id]
    # Selling at the same time means they coexist -- not a rename.
    if first_a <= last_b and first_b <= last_a:
        return None

    # The one that sold first carries the history and survives the merge.
    if last_a < first_b:
        keep, merge = (a, first_a, last_a, units_a), (b, first_b, last_b, units_b)
    else:
        keep, merge = (b, first_b, last_b, units_b), (a, first_a, last_a, units_a)
    return Candidate(
        keep=keep[0],
        merge=merge[0],
        ratio=round(ratio, 2),
        keep_last=keep[2],
        merge_first=merge[1],
        keep_units=keep[3],
        merge_units=merge[3],
    )
