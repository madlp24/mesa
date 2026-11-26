"""Number formatting for the interface (US49).

Pesos have no cents worth printing, and ``floatformat:2|intcomma`` under the
Spanish locale produced "$276,436,985,75" -- commas for thousands *and* for
decimals. Every amount on a page goes through these filters instead, which
follow the active language's separators ("$276.436.986" in Spanish,
"$276,436,986" in English).
"""
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from django import template
from django.utils.formats import number_format
from django.utils.translation import gettext as _

register = template.Library()

_DASH = "–"
_MINUS = "−"


def _decimal(value) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _group(value: Decimal, places: int = 0) -> str:
    quantum = Decimal(1).scaleb(-places)
    rounded = value.quantize(quantum, rounding=ROUND_HALF_UP)
    return number_format(rounded, decimal_pos=places, force_grouping=True)


def _signed(text: str, negative: bool) -> str:
    return f"{_MINUS}{text}" if negative else text


@register.filter
def cop(value):
    """Whole pesos with thousands separators: ``$276.436.986``."""
    amount = _decimal(value)
    if amount is None:
        return _DASH
    return _signed(f"${_group(abs(amount))}", amount < 0)


@register.filter
def cop_short(value):
    """A compact amount for headlines: ``$276,4 M``, ``$1,2 mil M``, ``$84.938``."""
    amount = _decimal(value)
    if amount is None:
        return _DASH
    size = abs(amount)
    if size >= Decimal("1e9"):
        text = _("$%(amount)s bn") % {"amount": _group(size / Decimal("1e9"), 1)}
    elif size >= Decimal("1e6"):
        text = _("$%(amount)s M") % {"amount": _group(size / Decimal("1e6"), 1)}
    else:
        text = f"${_group(size)}"
    return _signed(text, amount < 0)


@register.filter
def num(value, places=0):
    """A grouped number: ``84.938``; ``places`` decimals when asked."""
    amount = _decimal(value)
    if amount is None:
        return _DASH
    return _signed(_group(abs(amount), int(places)), amount < 0)


@register.filter
def pct(value, places=1):
    """A percentage with the language's decimal mark: ``68,6 %`` / ``68.6%``."""
    amount = _decimal(value)
    if amount is None:
        return _DASH
    return _signed(_("%(value)s%%") % {"value": _group(abs(amount), int(places))},
                   amount < 0)


@register.filter
def change(value, places=1):
    """A signed percentage change: ``+8,2 %``, ``−3,1 %``."""
    amount = _decimal(value)
    if amount is None:
        return _DASH
    sign = "+" if amount > 0 else (_MINUS if amount < 0 else "")
    return sign + _("%(value)s%%") % {"value": _group(abs(amount), int(places))}


@register.filter
def signed(value, places=1):
    """A signed number without a unit: ``+0,3``, for points of margin."""
    amount = _decimal(value)
    if amount is None:
        return _DASH
    sign = "+" if amount > 0 else (_MINUS if amount < 0 else "")
    return sign + _group(abs(amount), int(places))


@register.filter
def trend(value):
    """``up``, ``down`` or ``flat``, for styling a change."""
    amount = _decimal(value)
    if amount is None or amount == 0:
        return "flat"
    return "up" if amount > 0 else "down"
