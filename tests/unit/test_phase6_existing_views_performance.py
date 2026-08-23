from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PRODUCTS = ROOT / "frontend" / "app" / "views" / "products.js"
REVIEW = ROOT / "frontend" / "app" / "views" / "review.js"
APP = ROOT / "pdf_document_intelligence" / "api" / "app.py"


def test_phase6_caches_existing_products_and_review_derivations():
    products = PRODUCTS.read_text(encoding="utf-8")
    review = REVIEW.read_text(encoding="utf-8")

    assert "cachedProductsRef" in products
    assert "cachedBaseRows" in products
    assert "cachedQueryRows" in products
    assert "cachedProductsRef" in review
    assert "derivedReviewItems" in review
    assert "cachedCounts" in review


def test_phase6_does_not_add_parallel_products_or_review_endpoints():
    app = APP.read_text(encoding="utf-8")
    assert app.count('@app.get("/api/products")') == 1
    assert app.count('@app.get("/api/review")') == 1
