from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal


@dataclass
class CanonicalSaleItem:
    product_sku: str
    quantity: int
    unit_price: Decimal
    unit_cost: Decimal
    # Optional catalog hints; importers that read them (e.g. the PDF report,
    # which embeds the catalog) let persist() auto-create missing products.
    product_name: str = ""
    category_name: str = ""


@dataclass
class CanonicalSale:
    external_id: str
    occurred_at: datetime
    total: Decimal
    payment_method: str = ""
    server_name: str = ""
    table_number: str = ""
    items: list[CanonicalSaleItem] = field(default_factory=list)
