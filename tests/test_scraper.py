import pytest
import json
from datetime import datetime
from unittest.mock import patch, MagicMock
from app.services.willhaben_scraper import (
    _extract_next_data_products,
    _parse_price,
    _parse_listing,
    _parse_published_at,
    scrape_willhaben,
)


def test_parse_price_euro_format():
    assert _parse_price("€ 1.234,56") == pytest.approx(1234.56)


def test_parse_price_comma_format():
    assert _parse_price("150,00 €") == pytest.approx(150.0)


def test_parse_price_integer():
    assert _parse_price("500 €") == pytest.approx(500.0)


def test_parse_price_none_on_empty():
    assert _parse_price("") is None
    assert _parse_price(None) is None


def test_parse_price_none_on_vhb():
    # "VHB" (Verhandlungsbasis) should not parse to a number
    assert _parse_price("VHB") is None


def test_parse_listing_basic():
    from bs4 import BeautifulSoup

    html = """
    <article>
            <img src="https://cache.willhaben.at/mmo/test_hoved.jpg" alt="Cover Image" />
      <a data-testid="ad-detail-link" href="/iad/ad/12345">Cooles Produkt</a>
      <span data-testid="ad-price">€ 99,00</span>
      <span data-testid="ad-location">Wien</span>
    </article>
    """
    soup = BeautifulSoup(html, "lxml")
    article = soup.find("article")
    result = _parse_listing(article)

    assert result["title"] == "Cooles Produkt"
    assert result["price"] == pytest.approx(99.0)
    assert result["location"] == "Wien"
    assert "willhaben.at" in result["url"]
    assert result["image_url"] == "https://cache.willhaben.at/mmo/test_hoved.jpg"


def test_extract_next_data_products_includes_image_url():
    payload = {
        "props": {
            "pageProps": {
                "searchResult": {
                    "advertSummaryList": {
                        "advertSummary": [
                            {
                                "id": "12345",
                                "description": "Tolles Smartphone",
                                "attributes": {
                                    "attribute": [
                                        {"name": "HEADING", "values": ["iPhone 14"]},
                                        {"name": "PRICE", "values": ["\u20ac 750,00"]},
                                        {"name": "LOCATION", "values": ["Wien"]},
                                    ]
                                },
                                "contextLinkList": {
                                    "contextLink": [
                                        {
                                            "id": "iadShareLink",
                                            "uri": "https://www.willhaben.at/iad/kaufen-und-verkaufen/d/iphone-14-12345/",
                                        }
                                    ]
                                },
                                "advertImageList": {
                                    "advertImage": [
                                        {
                                            "mainImageUrl": "https://cache.willhaben.at/mmo/1/test_hoved.jpg"
                                        }
                                    ]
                                },
                            }
                        ]
                    }
                }
            }
        }
    }
    html = (
        '<script id="__NEXT_DATA__" type="application/json">'
        f"{json.dumps(payload)}"
        "</script>"
    )

    result = _extract_next_data_products(html)

    assert len(result) == 1
    assert result[0]["title"] == "iPhone 14"
    assert result[0]["image_url"] == "https://cache.willhaben.at/mmo/1/test_hoved.jpg"
    assert result[0]["url"] == "https://www.willhaben.at/iad/kaufen-und-verkaufen/d/iphone-14-12345/"



def test_scrape_willhaben_http_error():
    """When the request fails, scrape_willhaben should return an empty list."""
    with patch("app.services.willhaben_scraper.requests.get") as mock_get:
        mock_get.side_effect = Exception("Network error")
        result = scrape_willhaben("iphone", max_pages=1)
    assert result == []


def test_scrape_willhaben_empty_page():
    """When no articles are found, scraping stops and returns empty list."""
    mock_response = MagicMock()
    mock_response.raise_for_status.return_value = None
    mock_response.text = "<html><body><p>No results</p></body></html>"

    with patch("app.services.willhaben_scraper.requests.get", return_value=mock_response):
        result = scrape_willhaben("xyznonexistent", max_pages=2)

    assert result == []


def test_scrape_willhaben_parses_articles():
    """Verify that articles on a mocked page are parsed correctly."""
    mock_html = """
    <html><body>
      <article>
                <img src="https://cache.willhaben.at/mmo/1/iphone14_hoved.jpg" alt="Cover Image">
        <a data-testid="ad-detail-link" href="/iad/ad/1">iPhone 14</a>
        <span data-testid="ad-price">€ 750,00</span>
        <span data-testid="ad-location">Salzburg</span>
      </article>
      <article>
                <img src="https://cache.willhaben.at/mmo/1/iphone13_hoved.jpg" alt="Cover Image">
        <a data-testid="ad-detail-link" href="/iad/ad/2">iPhone 13</a>
        <span data-testid="ad-price">€ 550,00</span>
        <span data-testid="ad-location">Linz</span>
      </article>
    </body></html>
    """
    mock_response = MagicMock()
    mock_response.raise_for_status.return_value = None
    mock_response.text = mock_html

    with patch("app.services.willhaben_scraper.requests.get", return_value=mock_response):
        with patch("app.services.willhaben_scraper.time.sleep"):
            # only 1 page so we get the two articles above, then the second page fetch
            # will also return the same html but we set max_pages=1 to avoid that
            result = scrape_willhaben("iphone", max_pages=1)

    assert len(result) == 2
    assert result[0]["title"] == "iPhone 14"
    assert result[0]["price"] == pytest.approx(750.0)
    assert result[0]["image_url"] == "https://cache.willhaben.at/mmo/1/iphone14_hoved.jpg"
    assert result[1]["price"] == pytest.approx(550.0)
    assert result[1]["image_url"] == "https://cache.willhaben.at/mmo/1/iphone13_hoved.jpg"


def test_parse_published_at_iso_format():
    dt = _parse_published_at("2024-01-15T10:30:00")
    assert dt == datetime(2024, 1, 15, 10, 30, 0)


def test_parse_published_at_iso_with_z():
    dt = _parse_published_at("2024-03-01T08:00:00Z")
    assert dt == datetime(2024, 3, 1, 8, 0, 0)


def test_parse_published_at_date_only():
    dt = _parse_published_at("2024-06-20")
    assert dt == datetime(2024, 6, 20, 0, 0, 0)


def test_parse_published_at_ms_timestamp():
    # 2024-01-15 10:30:00 UTC in milliseconds
    ms = 1705315800000
    dt = _parse_published_at(str(ms))
    assert dt is not None
    assert dt.year == 2024
    assert dt.month == 1
    assert dt.day == 15


def test_parse_published_at_empty():
    assert _parse_published_at("") is None
    assert _parse_published_at(None) is None


def test_parse_published_at_invalid():
    assert _parse_published_at("not-a-date") is None


def test_parse_listing_with_published_at():
    from bs4 import BeautifulSoup

    html = """
    <article>
      <img src="https://cache.willhaben.at/mmo/test_hoved.jpg" alt="Cover Image" />
      <a data-testid="ad-detail-link" href="/iad/ad/12345">Cooles Produkt</a>
      <span data-testid="ad-price">€ 99,00</span>
      <span data-testid="ad-location">Wien</span>
      <time datetime="2024-02-10T09:00:00">10. Februar 2024</time>
    </article>
    """
    soup = BeautifulSoup(html, "lxml")
    article = soup.find("article")
    result = _parse_listing(article)

    assert result["published_at"] == datetime(2024, 2, 10, 9, 0, 0)


def test_parse_listing_without_published_at():
    from bs4 import BeautifulSoup

    html = """
    <article>
      <a data-testid="ad-detail-link" href="/iad/ad/99">Produkt ohne Datum</a>
      <span data-testid="ad-price">€ 50,00</span>
    </article>
    """
    soup = BeautifulSoup(html, "lxml")
    article = soup.find("article")
    result = _parse_listing(article)

    assert result["published_at"] is None


def test_extract_next_data_products_with_published_at():
    payload = {
        "props": {
            "pageProps": {
                "searchResult": {
                    "advertSummaryList": {
                        "advertSummary": [
                            {
                                "description": "Laptop",
                                "attributes": {
                                    "attribute": [
                                        {"name": "HEADING", "values": ["MacBook Pro"]},
                                        {"name": "PRICE", "values": ["€ 1200,00"]},
                                        {"name": "LOCATION", "values": ["Graz"]},
                                        {"name": "PUBLISHED", "values": ["2024-03-05T14:00:00"]},
                                    ]
                                },
                                "contextLinkList": {"contextLink": []},
                                "advertImageList": {"advertImage": []},
                            }
                        ]
                    }
                }
            }
        }
    }
    html = (
        '<script id="__NEXT_DATA__" type="application/json">'
        f"{json.dumps(payload)}"
        "</script>"
    )

    result = _extract_next_data_products(html)

    assert len(result) == 1
    assert result[0]["title"] == "MacBook Pro"
    assert result[0]["published_at"] == datetime(2024, 3, 5, 14, 0, 0)


def test_extract_next_data_products_without_published_at():
    payload = {
        "props": {
            "pageProps": {
                "searchResult": {
                    "advertSummaryList": {
                        "advertSummary": [
                            {
                                "description": "Kamera",
                                "attributes": {
                                    "attribute": [
                                        {"name": "HEADING", "values": ["Canon EOS"]},
                                        {"name": "PRICE", "values": ["€ 400,00"]},
                                        {"name": "LOCATION", "values": ["Salzburg"]},
                                    ]
                                },
                                "contextLinkList": {"contextLink": []},
                                "advertImageList": {"advertImage": []},
                            }
                        ]
                    }
                }
            }
        }
    }
    html = (
        '<script id="__NEXT_DATA__" type="application/json">'
        f"{json.dumps(payload)}"
        "</script>"
    )

    result = _extract_next_data_products(html)

    assert len(result) == 1
    assert result[0]["published_at"] is None
