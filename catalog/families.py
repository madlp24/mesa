"""Menu families: which dishes compete with which (US53).

Menu engineering only means something among dishes a guest chooses between. A
POS group is the closest thing the data has, but it is how whoever installed
the POS filed things: "CORTES" and "CARNE PRIME" apart, voids and corkage as
groups of their own. A family is the owner's view of the menu. Mesa suggests
one for every POS group from its name; the owner can rename, regroup or hide
them, and what the owner sets always wins.
"""
from __future__ import annotations

from decimal import Decimal

from django.utils.translation import gettext_lazy as _

#: Groups that are not dishes: voids, corkage, courtesies, staff accounts.
_HIDDEN_HINTS = ("ANULA", "DESCORCHE", "CORTESIA", "PROPINA", "EMPLEAD", "PERSONAL")

#: (any of these, and any of these, family, suggested target food cost %).
#: Checked in order; first hit wins. The targets are what Colombian grills
#: commonly price to (US56): beef runs dear -- 30% is hard on a cut -- while
#: wine by the bottle at 45% is normal and a cocktail sits near 22%.
_RULES = (
    (("PRIME", "WAGYU", "PREMIUM"), (), _("Premium cuts"), 40),
    (("CORTE", "STEAK", "PARRILLA"), (), _("Cuts"), 35),
    (("ENSALADA", "SALAD"), (), _("Salads"), 28),
    (("ENTRADA", "PICOTEO", "STARTER", "APPETIZER"), (), _("Starters and snacks"), 30),
    (("ACOMPA", "GUARNICI", "SIDE"), (), _("Sides"), 25),
    (("ADICION", "EXTRA"), (), _("Add-ons"), 25),
    (("POSTRE", "DESSERT"), (), _("Desserts"), 28),
    (("VINO", "ESPUMOSO", "WINE"), ("BOTELLA", "BOTTLE"), _("Wine by the bottle"), 45),
    (("VINO", "ESPUMOSO", "WINE", "SANGRIA"), (), _("Wine by the glass and sangria"), 35),
    (("COCTEL", "COCKTAIL"), (), _("Cocktails"), 22),
    (("DESTILADO", "LICOR", "SPIRIT"), ("BOTELLA", "BOTTLE"), _("Spirits by the bottle"), 40),
    (("DESTILADO", "LICOR", "SPIRIT"), (), _("Spirits by the glass"), 28),
    (("CERVEZA", "BEER"), (), _("Beers"), 35),
    (("LIMONADA", "SODA", "AGUA", "BEBIDA", "CAFE", "JUGO", "SOFT"), (), _("Soft drinks"), 25),
    (("FUERTE", "ESPECIAL", "NIÑO", "NINO", "MAIN"), (), _("Other mains"), 32),
)


def _rule(group_name: str):
    upper = (group_name or "").upper()
    for first, second, family, target in _RULES:
        if any(k in upper for k in first) and (not second or any(k in upper for k in second)):
            return family, target
    return None


#: The rules whose groups are cuts of meat, for the kilos page (US57).
_MEAT_RULES = 2


def is_meat(category) -> bool:
    """Whether a POS group holds cuts of meat (the first two rules)."""
    upper = (category.name or "").upper()
    for first, second, _family, _target in _RULES[:_MEAT_RULES]:
        if any(k in upper for k in first) and (not second or any(k in upper for k in second)):
            return True
    return False


def suggest_hidden(group_name: str) -> bool:
    upper = (group_name or "").upper()
    return any(hint in upper for hint in _HIDDEN_HINTS)


def suggest_family(group_name: str) -> str:
    """The family a POS group most likely belongs to; its own name if unknown."""
    rule = _rule(group_name)
    if rule:
        return str(rule[0])
    return (group_name or "").strip().capitalize()


def suggest_target(group_name: str) -> Decimal | None:
    """The food cost % such a group is usually priced to, or ``None``."""
    rule = _rule(group_name)
    return Decimal(rule[1]) if rule else None


def family_of(category) -> str:
    return category.menu_family or suggest_family(category.name)


def is_hidden(category) -> bool:
    if category.menu_hidden is not None:
        return category.menu_hidden
    return suggest_hidden(category.name)


def target_of(category) -> tuple[Decimal | None, str]:
    """The category's target and where it came from: ``"set"`` by the owner,
    ``"suggested"`` by Mesa, or ``(None, "default")`` for the restaurant's."""
    if category.target_cost_pct is not None:
        return Decimal(str(category.target_cost_pct)), "set"
    suggestion = suggest_target(category.name)
    if suggestion is not None:
        return suggestion, "suggested"
    return None, "default"
