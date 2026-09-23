"""Expected partner workbooks, relative to the repository's data directory."""

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class WorkbookSource:
    """A file location and its purpose; this is not a parsed planning input."""

    brand: str
    purpose: str
    filename: str

    def path(self, data_dir: Path) -> Path:
        return data_dir / self.brand / self.filename


SOURCES = (
    WorkbookSource("IEK", "minimum_dispatch", "MOQ  ИЭК.xlsx"),
    WorkbookSource("IEK", "document_sales", "Динамика продаж_2025-2026.xlsx"),
    WorkbookSource(
        "IEK", "monthly_stock", "Ежемесячные остатки продукции за последние 2 года  ИЭК.xlsx"
    ),
    WorkbookSource(
        "IEK",
        "monthly_sales",
        "Ежемесячные продажи в количественном выражении за последние 2 года.xlsx",
    ),
    WorkbookSource("IEK", "goods_in_transit", "Путь ИЭК 22.09.2026.xlsx"),
    WorkbookSource("IEK", "seasonality", "Сезонность ИЭК.xlsx"),
    WorkbookSource("Systeme electric", "packing_multiple", "MOQ SystemElectric.xlsx"),
    WorkbookSource(
        "Systeme electric", "document_sales", "Динамика продаж_Syseme Electric_2025-2026.xlsx"
    ),
    WorkbookSource(
        "Systeme electric", "monthly_stock", "Ежемесячные остатки SystemElectric 2024-2026.xlsx"
    ),
    WorkbookSource(
        "Systeme electric",
        "monthly_sales",
        "Ежемесячные продажи в кол-м выражении SystemElectric 2024-2026.xlsx",
    ),
    WorkbookSource("Systeme electric", "seasonality", "Сезонность SystemElectric 2024-2026.xlsx"),
    WorkbookSource(
        "Systeme electric",
        "goods_in_transit",
        "Товар в пути_SystemElectric на 22.09.2026.xlsx",
    ),
)
