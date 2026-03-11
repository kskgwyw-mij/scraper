import re
import time
import logging

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "de-AT,de;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

WILLHABEN_BASE = "https://www.willhaben.at"
WILLHABEN_SEARCH = (
    "https://www.willhaben.at/iad/kaufen-und-verkaufen/marktplatz"
)


def _parse_price(text: str):
    """Extract a float price from a price string like '€ 1.234,56' or '1234,56 €'."""
    if not text:
        return None
    cleaned = re.sub(r"[^\d,.]", "", text.replace(".", "").replace(",", "."))
    try:
        return float(cleaned)
    except (ValueError, TypeError):
        return None


def _parse_listing(article) -> dict:
    """Parse a single search-result article tag into a product dict."""
    title_tag = (
        article.find("a", attrs={"data-testid": "ad-detail-link"})
        or article.find("h2")
        or article.find("h3")
    )
    title = title_tag.get_text(strip=True) if title_tag else ""

    href = title_tag.get("href", "") if title_tag else ""
    url = (WILLHABEN_BASE + href) if href.startswith("/") else href

    price_tag = (
        article.find(attrs={"data-testid": "ad-price"})
        or article.find(class_=re.compile(r"price", re.I))
    )
    price_text = price_tag.get_text(strip=True) if price_tag else ""
    price = _parse_price(price_text)

    location_tag = article.find(attrs={"data-testid": "ad-location"}) or article.find(
        class_=re.compile(r"location", re.I)
    )
    location = location_tag.get_text(strip=True) if location_tag else ""

    desc_tag = article.find(attrs={"data-testid": "ad-description"}) or article.find(
        "p"
    )
    description = desc_tag.get_text(strip=True) if desc_tag else ""

    return {
        "title": title,
        "price": price,
        "location": location,
        "url": url,
        "description": description,
    }


def scrape_willhaben(keyword: str, max_pages: int = 5, timeout: int = 10) -> list[dict]:
    """
    Scrape willhaben.at marketplace for *keyword* and return a list of product dicts.

    Each dict contains: title, price (float|None), location, url, description.
    """
    results = []

    for page in range(1, max_pages + 1):
        params = {"keyword": keyword, "page": page}
        try:
            response = requests.get(
                WILLHABEN_SEARCH,
                params=params,
                headers=HEADERS,
                timeout=timeout,
            )
            response.raise_for_status()
        except Exception as exc:
            logger.warning("Failed to fetch page %d for '%s': %s", page, keyword, exc)
            break

        soup = BeautifulSoup(response.text, "lxml")

        # willhaben renders listings inside <article> elements
        articles = soup.find_all("article")
        if not articles:
            # fallback: try common ad-list containers
            articles = soup.select("[data-testid='ad-card'], li.search-result")

        if not articles:
            logger.debug("No articles found on page %d – stopping.", page)
            break

        page_results = [_parse_listing(a) for a in articles]
        # Filter out empty titles (navigation articles etc.)
        page_results = [p for p in page_results if p["title"]]
        results.extend(page_results)

        # Be polite – short delay between pages
        if page < max_pages:
            time.sleep(1)

    return results
