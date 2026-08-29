"""Regression guards for the shared document-date scope.

The Dashboard's date range is the authoritative operational scope for every
document-derived view. Product Master is intentionally not date-scoped because
it is reference data rather than document data.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "frontend" / "app"


def _read(relative: str) -> str:
    return (FRONTEND / relative).read_text(encoding="utf-8")


def test_store_exposes_shared_date_scoped_document_and_product_selectors():
    source = _read("state.js")
    assert "getDateScopedDocuments()" in source
    assert "getDateScopedProducts()" in source
    assert "dashboardDateFrom" in source
    assert "dashboardDateTo" in source
    assert "inDocumentDateRange(doc.documentDate, dashboardDateFrom, dashboardDateTo)" in source
    assert "completedDocumentIds.has(product.docId)" in source


def test_all_document_derived_views_use_the_shared_date_scope():
    expected = {
        "views/products.js": "store.getDateScopedProducts()",
        "views/review.js": "store.getDateScopedProducts()",
        "views/nonproduct.js": "store.getDateScopedProducts()",
        "views/documents.js": "store.getDateScopedDocuments()",
        "views/departments.js": "store.getDateScopedProducts()",
    }
    for path, needle in expected.items():
        assert needle in _read(path), f"{path} must follow the Dashboard document-date scope"


def test_sidebar_counts_follow_the_same_date_scope():
    source = _read("components/sidebar.js")
    assert "store.getDateScopedDocuments()" in source
    assert "store.getDateScopedProducts()" in source


def test_departments_recalculate_counts_from_scoped_rows_when_date_filter_active():
    source = _read("views/departments.js")
    assert "buildDateScopedDepartments" in source
    assert "Boolean(dashboardDateFrom || dashboardDateTo)" in source
    assert "entry.rowCount += 1" in source
    assert "entry.reviewCount += 1" in source
    assert '["weight_qty", "pu_qty", "sku_qty"]' in source


def test_product_master_is_not_document_date_scoped():
    source = _read("views/productMaster.js")
    assert "getDateScopedDocuments" not in source
    assert "getDateScopedProducts" not in source
