import pytest
from app.models import SearchQuery, Product


def test_create_search_query(db):
    sq = SearchQuery(keyword="testprodukt")
    db.session.add(sq)
    db.session.commit()
    assert sq.id is not None
    assert sq.keyword == "testprodukt"
    assert sq.created_at is not None


def test_create_product(db):
    sq = SearchQuery(keyword="fahrrad")
    db.session.add(sq)
    db.session.flush()

    p = Product(
        search_query_id=sq.id,
        title="Mountainbike 26 Zoll",
        price=149.99,
        location="Wien",
        url="https://www.willhaben.at/example",
        image_url="https://cache.willhaben.at/example_hoved.jpg",
        description="Sehr guter Zustand",
    )
    db.session.add(p)
    db.session.commit()

    assert p.id is not None
    assert p.price == 149.99
    assert p.image_url == "https://cache.willhaben.at/example_hoved.jpg"


def test_product_to_dict(db):
    sq = SearchQuery(keyword="sofa")
    db.session.add(sq)
    db.session.flush()

    p = Product(
        search_query_id=sq.id,
        title="Rotes Sofa",
        price=200.0,
        location="Graz",
        image_url="https://cache.willhaben.at/sofa_hoved.jpg",
    )
    db.session.add(p)
    db.session.commit()

    d = p.to_dict()
    assert d["title"] == "Rotes Sofa"
    assert d["price"] == 200.0
    assert d["location"] == "Graz"
    assert d["image_url"] == "https://cache.willhaben.at/sofa_hoved.jpg"


def test_cascade_delete(db):
    sq = SearchQuery(keyword="laptop")
    db.session.add(sq)
    db.session.flush()

    for price in [300.0, 450.0, 600.0]:
        db.session.add(Product(search_query_id=sq.id, title="Laptop", price=price))
    db.session.commit()

    sq_id = sq.id
    db.session.delete(sq)
    db.session.commit()

    remaining = Product.query.filter_by(search_query_id=sq_id).count()
    assert remaining == 0
