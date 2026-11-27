"""Menu families: which dishes compete with which (US53).

Menu engineering only means something among dishes a guest chooses between. A
POS group is the closest thing the data has, but it is how whoever installed
the POS filed things: "CORTES" and "CARNE PRIME" apart, voids and corkage as
groups of their own. A family is the owner's view of the menu. Mesa suggests
one for every POS group from its name; the owner can rename, regroup or hide
them, and what the owner sets always wins.
"""
from __future__ import annotations

from django.utils.translation import gettext_lazy as _

#: Groups that are not dishes: voids, corkage, courtesies, staff accounts.
_HIDDEN_HINTS = ("ANULA", "DESCORCHE", "CORTESIA", "PROPINA", "EMPLEAD", "PERSONAL")

#: (any of these, and any of these, family). Checked in order; first hit wins.
_RULES = (
    (("PRIME", "WAGYU", "PREMIUM"), (), _("Premium cuts")),
    (("CORTE", "STEAK", "PARRILLA"), (), _("Cuts")),
    (("ENSALADA", "SALAD"), (), _("Salads")),
    (("ENTRADA", "PICOTEO", "STARTER", "APPETIZER"), (), _("Starters and snacks")),
    (("ACOMPA", "GUARNICI", "SIDE"), (), _("Sides")),
    (("ADICION", "EXTRA"), (), _("Add-ons")),
    (("POSTRE", "DESSERT"), (), _("Desserts")),
    (("VINO", "ESPUMOSO", "WINE"), ("BOTELLA", "BOTTLE"), _("Wine by the bottle")),
    (("VINO", "ESPUMOSO", "WINE", "SANGRIA"), (), _("Wine by the glass and sangria")),
    (("COCTEL", "COCKTAIL"), (), _("Cocktails")),
    (("DESTILADO", "LICOR", "SPIRIT"), ("BOTELLA", "BOTTLE"), _("Spirits by the bottle")),
    (("DESTILADO", "LICOR", "SPIRIT"), (), _("Spirits by the glass")),
    (("CERVEZA", "BEER"), (), _("Beers")),
    (("LIMONADA", "SODA", "AGUA", "BEBIDA", "CAFE", "JUGO", "SOFT"), (), _("Soft drinks")),
    (("FUERTE", "ESPECIAL", "NIÑO", "NINO", "MAIN"), (), _("Other mains")),
)


def suggest_hidden(group_name: str) -> bool:
    upper = (group_name or "").upper()
    return any(hint in upper for hint in _HIDDEN_HINTS)


def suggest_family(group_name: str) -> str:
    """The family a POS group most likely belongs to; its own name if unknown."""
    upper = (group_name or "").upper()
    for first, second, family in _RULES:
        if any(k in upper for k in first) and (not second or any(k in upper for k in second)):
            return str(family)
    return (group_name or "").strip().capitalize()


def family_of(category) -> str:
    return category.menu_family or suggest_family(category.name)


def is_hidden(category) -> bool:
    if category.menu_hidden is not None:
        return category.menu_hidden
    return suggest_hidden(category.name)
