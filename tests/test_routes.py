import pytest
from app.models import SearchQuery, Product


def test_index_page(client):
    response = client.get("/")
    assert response.status_code == 200
    assert b"Willhaben" in response.data


def test_search_post_redirects_on_empty_keyword(client):
    response = client.post("/scraper/search", data={"keyword": ""})
    assert response.status_code == 302


def test_search_post_scrapes_and_redirects(client, db):
    from unittest.mock import patch

    mock_products = [
        {
            "title": "Testprodukt",
            "price": 100.0,
            "location": "Wien",
            "url": "https://www.willhaben.at/test",
            "description": "Ein Test",
        }
    ]

    with patch("app.controllers.scraper.scrape_willhaben", return_value=mock_products):
        response = client.post(
            "/scraper/search",
            data={"keyword": "testprodukt"},
            follow_redirects=False,
        )

    assert response.status_code == 302
    assert "/scraper/products/" in response.headers["Location"]


def test_search_post_passes_form_max_pages(client, db):
    from unittest.mock import patch

    with patch("app.controllers.scraper.scrape_willhaben", return_value=[]) as mock_scrape:
        response = client.post(
            "/scraper/search",
            data={"keyword": "testprodukt", "max_pages": "7"},
            follow_redirects=False,
        )

    assert response.status_code == 302
    mock_scrape.assert_called_once_with("testprodukt", max_pages=7, timeout=10)


def test_index_page_contains_default_max_pages(client):
    response = client.get("/")

    assert response.status_code == 200
    assert b'name="max_pages"' in response.data
    assert b'value="5"' in response.data


def test_products_page(client, db):
    from unittest.mock import patch

    mock_products = [
        {
            "title": f"Produkt {i}",
            "price": float(i * 50),
            "location": "Wien",
            "url": f"https://www.willhaben.at/ad/{i}",
            "description": "",
        }
        for i in range(1, 4)
    ]

    with patch("app.controllers.scraper.scrape_willhaben", return_value=mock_products):
        response = client.post(
            "/scraper/search",
            data={"keyword": "sofa"},
            follow_redirects=True,
        )

    assert response.status_code == 200
    assert b"Produkt 1" in response.data


def test_predict_page(client, db):
    sq = SearchQuery(keyword="laptop")
    db.session.add(sq)
    db.session.flush()
    for price in [300.0, 400.0, 500.0, 600.0, 700.0]:
        db.session.add(Product(search_query_id=sq.id, title="Laptop", price=price))
    db.session.commit()

    response = client.get(f"/scraper/predict/{sq.id}")
    assert response.status_code == 200
    assert "Preisprognose".encode() in response.data


def test_predict_page_not_enough_data(client, db):
    sq = SearchQuery(keyword="rare_item")
    db.session.add(sq)
    db.session.flush()
    db.session.add(Product(search_query_id=sq.id, title="Seltenes Ding", price=None))
    db.session.commit()

    response = client.get(f"/scraper/predict/{sq.id}")
    assert response.status_code == 200
    assert b"Nicht genug" in response.data


def test_delete_search(client, db):
    sq = SearchQuery(keyword="zu_loeschen")
    db.session.add(sq)
    db.session.commit()
    sq_id = sq.id

    response = client.post(f"/scraper/delete/{sq_id}", follow_redirects=False)
    assert response.status_code == 302

    assert db.session.get(SearchQuery, sq_id) is None


def test_404_for_missing_search(client):
    response = client.get("/scraper/products/99999")
    assert response.status_code == 404
