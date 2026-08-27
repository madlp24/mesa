from .base import BaseImporter
from .canonical import CanonicalSale, CanonicalSaleItem
from .persistence import persist
from .registry import autodiscover, get_importer_for, register

# Import every importer module so its @register decorator runs. Adding a new
# format needs no edit here: just drop a new module in this package.
autodiscover(__name__, __path__)

__all__ = [
    "BaseImporter",
    "CanonicalSale",
    "CanonicalSaleItem",
    "get_importer_for",
    "persist",
    "register",
]
