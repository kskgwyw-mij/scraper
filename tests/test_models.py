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
        seller_name="Bike Store",
        item_condition="Used Condition",
        category_path="Sport > Fahrraeder",
    )
    db.session.add(p)
    db.session.commit()

    assert p.id is not None
    assert p.price == 149.99
    assert p.image_url == "https://cache.willhaben.at/example_hoved.jpg"
    assert p.seller_name == "Bike Store"
    assert p.item_condition == "Used Condition"
    assert p.category_path == "Sport > Fahrraeder"


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
        seller_name="Moebelhaus Test",
        item_condition="New Condition",
        category_path="Wohnen > Sofas",
    )
    db.session.add(p)
    db.session.commit()

    d = p.to_dict()
    assert d["title"] == "Rotes Sofa"
    assert d["price"] == 200.0
    assert d["location"] == "Graz"
    assert d["image_url"] == "https://cache.willhaben.at/sofa_hoved.jpg"
    assert d["published_at"] is None
    assert d["seller_name"] == "Moebelhaus Test"
    assert d["item_condition"] == "New Condition"
    assert d["category_path"] == "Wohnen > Sofas"


def test_product_published_at(db):
    from datetime import datetime

    sq = SearchQuery(keyword="kamera")
    db.session.add(sq)
    db.session.flush()

    pub = datetime(2024, 3, 10, 9, 30, 0)
    p = Product(
        search_query_id=sq.id,
        title="Canon EOS",
        price=400.0,
        published_at=pub,
    )
    db.session.add(p)
    db.session.commit()

    assert p.published_at == pub
    d = p.to_dict()
    assert d["published_at"] == "2024-03-10T09:30:00"


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
