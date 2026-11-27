"""Where every page sits in the app, in one place (US49).

The old menu was a single dropdown listing ten pages side by side, hidden
behind a button even on a wide screen. Pages that answer one question --
margins and margin alerts, quotes and the event menu -- were separate entries
with nothing saying they belonged together. Here each page belongs to a
section; the side navigation lists the sections and each section shows its
pages as tabs.
"""
from django.urls import reverse
from django.utils.translation import gettext_lazy as _

#: (key, label, [(url name, tab label), ...], extra url names that belong here)
SECTIONS = (
    ("overview", _("Overview"), [("analytics:dashboard", _("Overview"))], ()),
    (
        "alerts",
        _("Alerts"),
        [
            ("alerts:report", _("Alerts")),
            ("alerts:settings", _("Alert settings")),
        ],
        (),
    ),
    (
        "sales",
        _("Sales"),
        [
            ("analytics:comparisons", _("Against last year")),
            ("analytics:pnl_summary", _("By month")),
            ("analytics:days", _("Days and holidays")),
            ("analytics:meat", _("Meat in kilos")),
        ],
        (),
    ),
    (
        "margins",
        _("Margins"),
        [
            ("analytics:margin_alerts", _("To review")),
            ("analytics:margin_analysis", _("All products")),
            ("analytics:menu_engineering", _("Menu engineering")),
        ],
        ("analytics:menu_families",),
    ),
    (
        "products",
        _("Products"),
        [
            ("catalog:product_list", _("Products")),
            ("catalog:supplies", _("Supply costs")),
            ("catalog:duplicates", _("Possible duplicates")),
        ],
        ("catalog:product_detail", "catalog:merge_products", "catalog:merge_pair"),
    ),
    (
        "events",
        _("Events"),
        [
            ("quotes:quote_list", _("Quotes")),
            ("quotes:menu_list", _("Event menu")),
        ],
        ("quotes:quote_detail", "quotes:quote_create", "quotes:quote_compose"),
    ),
    (
        "workbook",
        _("My workbook"),
        [("analytics:workbook_update", _("My workbook"))],
        (),
    ),
)


def navigation(request):
    """Sections for the side navigation and tabs for the current section."""
    if not getattr(request, "user", None) or not request.user.is_authenticated:
        return {}
    match = getattr(request, "resolver_match", None)
    current = match.view_name if match else ""

    sections = []
    tabs = []
    for key, label, pages, extra in SECTIONS:
        names = [name for name, _tab in pages]
        active = current in names or current in extra
        sections.append(
            {"key": key, "label": label, "url": reverse(names[0]), "active": active}
        )
        if active and len(pages) > 1:
            tabs = [
                {"label": tab, "url": reverse(name), "active": name == current}
                for name, tab in pages
            ]
    return {"nav_sections": sections, "nav_tabs": tabs, "nav_current": current}
