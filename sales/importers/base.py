from abc import ABC, abstractmethod
from pathlib import Path

from .canonical import CanonicalSale


class BaseImporter(ABC):
    """Contract every POS report importer must satisfy.

    Subclasses parse one specific file format (Excel sheet, PDF report,
    JSON dump, etc.) and produce a uniform list of CanonicalSale objects.
    Persistence is shared across importers and lives in persistence.py.
    """

    @abstractmethod
    def normalize(self, path: Path) -> list[CanonicalSale]:
        """Read the file at `path` and return canonical sales."""
