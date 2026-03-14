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
            "image_url": "https://cache.willhaben.at/testprodukt_hoved.jpg",
            "description": "Ein Test",
            "seller_name": "Test Shop",
            "item_condition": "Used Condition",
            "category_path": "Elektronik > Smartphones",
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

    stored_product = Product.query.one()
    assert stored_product.image_url == "https://cache.willhaben.at/testprodukt_hoved.jpg"
    assert stored_product.seller_name == "Test Shop"
    assert stored_product.item_condition == "Used Condition"
    assert stored_product.category_path == "Elektronik > Smartphones"


def test_search_post_passes_form_max_pages(client, db):
    from unittest.mock import patch

    with patch("app.controllers.scraper.scrape_willhaben", return_value=[]) as mock_scrape:
        response = client.post(
            "/scraper/search",
            data={"keyword": "testprodukt", "max_pages": "7"},
            follow_redirects=False,
        )

    assert response.status_code == 302
    mock_scrape.assert_called_once_with(
        "testprodukt", max_pages=7, timeout=10, include_details=False
    )


def test_index_page_contains_default_max_pages(client):
    response = client.get("/")

    assert response.status_code == 200
    assert b'name="max_pages"' in response.data
    assert b'value="5"' in response.data


def test_index_page_contains_include_details_checkbox(client):
    response = client.get("/")

    assert response.status_code == 200
    assert b'name="include_details"' in response.data


def test_search_post_passes_include_details_true(client, db):
    from unittest.mock import patch

    with patch("app.controllers.scraper.scrape_willhaben", return_value=[]) as mock_scrape:
        client.post(
            "/scraper/search",
            data={"keyword": "test", "include_details": "1"},
            follow_redirects=False,
        )

    call_kwargs = mock_scrape.call_args
    assert call_kwargs.kwargs.get("include_details") is True


def test_search_post_passes_include_details_false_when_unchecked(client, db):
    from unittest.mock import patch

    with patch("app.controllers.scraper.scrape_willhaben", return_value=[]) as mock_scrape:
        client.post(
            "/scraper/search",
            data={"keyword": "test"},
            follow_redirects=False,
        )

    call_kwargs = mock_scrape.call_args
    assert call_kwargs.kwargs.get("include_details") is False


def test_products_page(client, db):
    from unittest.mock import patch

    mock_products = [
        {
            "title": f"Produkt {i}",
            "price": float(i * 50),
            "location": "Wien",
            "url": f"https://www.willhaben.at/ad/{i}",
            "image_url": f"https://cache.willhaben.at/ad/{i}_hoved.jpg",
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
    assert b"https://cache.willhaben.at/ad/1_hoved.jpg" in response.data


def test_predict_page(client, db):
    sq = SearchQuery(keyword="laptop")
    db.session.add(sq)
    db.session.flush()
    for i, price in enumerate([300.0, 400.0, 500.0, 600.0, 700.0]):
        db.session.add(
            Product(
                search_query_id=sq.id,
                title="Laptop",
                price=price,
                is_better_result=i < 3,
            )
        )
    db.session.commit()

    response = client.get(f"/scraper/predict/{sq.id}")
    assert response.status_code == 200
    assert "Preisprognose".encode() in response.data


def test_predict_page_not_enough_data(client, db):
    sq = SearchQuery(keyword="rare_item")
    db.session.add(sq)
    db.session.flush()
    db.session.add(
        Product(
            search_query_id=sq.id,
            title="Seltenes Ding",
            price=100.0,
            is_better_result=False,
        )
    )
    db.session.commit()

    response = client.get(f"/scraper/predict/{sq.id}")
    assert response.status_code == 200
    assert b"Nicht genug" in response.data


def test_catalog_page_contains_prediction_action(client):
    response = client.get("/scraper/catalog")

    assert response.status_code == 200
    assert b"/scraper/catalog/predict" in response.data


def test_catalog_predict_page_uses_filters(client, db):
    sq = SearchQuery(keyword="smartphones")
    db.session.add(sq)
    db.session.flush()

    products = [
        Product(
            search_query_id=sq.id,
            title="iPhone 14",
            price=300.0,
            location="Wien",
            is_better_result=True,
        ),
        Product(
            search_query_id=sq.id,
            title="iPhone 13",
            price=400.0,
            location="Wien",
            is_better_result=True,
        ),
        Product(
            search_query_id=sq.id,
            title="iPhone 12",
            price=500.0,
            location="Wien",
            is_better_result=True,
        ),
        Product(
            search_query_id=sq.id,
            title="Samsung Galaxy",
            price=800.0,
            location="Linz",
            is_better_result=False,
        ),
    ]
    db.session.add_all(products)
    db.session.commit()

    response = client.get("/scraper/catalog/predict?search=iPhone&location=Wien&percentile=50")

    assert response.status_code == 200
    assert b"Preisprognose f\xc3\xbcr aktuelle Katalogfilter" in response.data
    assert b"iPhone" in response.data
    assert b"Wien" in response.data
    assert b"3 aktuell gefilterten besten Treffern" in response.data


def test_catalog_predict_page_not_enough_data(client, db):
    sq = SearchQuery(keyword="moebel")
    db.session.add(sq)
    db.session.flush()
    db.session.add(
        Product(
            search_query_id=sq.id,
            title="Sofa",
            price=120.0,
            location="Graz",
            is_better_result=False,
        )
    )
    db.session.commit()

    response = client.get("/scraper/catalog/predict?search=Sofa")

    assert response.status_code == 200
    assert b"Nicht genug Preisdaten" in response.data


def test_catalog_filter_better_only(client, db):
    sq = SearchQuery(keyword="enten")
    db.session.add(sq)
    db.session.flush()
    db.session.add_all(
        [
            Product(
                search_query_id=sq.id,
                title="Badeente Gelb",
                price=10.0,
                is_better_result=True,
            ),
            Product(
                search_query_id=sq.id,
                title="Badeente Blau",
                price=12.0,
                is_better_result=False,
            ),
        ]
    )
    db.session.commit()

    response = client.get("/scraper/catalog?search=Badeente&better_only=1")

    assert response.status_code == 200
    assert b"Badeente Gelb" in response.data
    assert b"Badeente Blau" not in response.data


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
