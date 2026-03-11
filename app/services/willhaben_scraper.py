import re
import time
import logging
import json

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


def _extract_next_data_products(html: str) -> list[dict]:
    """
    Extract products from the Next.js __NEXT_DATA__ JSON payload used by willhaben pages.

    Returns:
        list[dict]: A list of product dictionaries, each matching the structure
            returned by `_parse_listing`, with the keys:

            - ``title``: str – The listing title.
            - ``price``: float | None – The parsed price, or ``None`` if unavailable.
            - ``location``: str – The listing location text.
            - ``url``: str – The absolute URL to the listing.
            - ``description``: str – A short description of the listing.
    """
    match = re.search(
        r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
        html,
        re.DOTALL,
    )
    if not match:
        return []

    try:
        payload = json.loads(match.group(1))
    except json.JSONDecodeError as exc:
        logger.warning("Failed to decode __NEXT_DATA__ payload: %s", exc)
        return []

    page_props = (payload.get("props") or {}).get("pageProps") or {}
    search_result = page_props.get("searchResult") or {}
    adverts = (
        ((search_result.get("advertSummaryList") or {}).get("advertSummary")) or []
        heading_values = attr_map.get("HEADING")
        fallback_heading = advert.get("description") or ""
        heading_source = heading_values or [fallback_heading]
        raw_title = (heading_source[0] or "") if heading_source else ""
        title = raw_title.strip()
        price_text = (attr_map.get("PRICE") or [""])[0]
        location = (attr_map.get("LOCATION") or [""])[0].strip()
        body_dyn_values = attr_map.get("BODY_DYN")
        fallback_body = advert.get("description") or ""
        body_source = body_dyn_values or [fallback_body]
        raw_description = (body_source[0] or "") if body_source else ""
        description = raw_description.strip()
            if name and values:
                attr_map[name] = values

        title = (
            (attr_map.get("HEADING") or [advert.get("description") or ""])[0] or ""
        ).strip()
        price_text = (attr_map.get("PRICE") or [""])[0]
        location = (attr_map.get("LOCATION") or [""])[0].strip()
        description = (attr_map.get("BODY_DYN") or [advert.get("description") or ""])[
            0
        ].strip()

        detail_url = ""
        links = ((advert.get("contextLinkList") or {}).get("contextLink")) or []
        for link in links:
            if link.get("id") == "adDetailLink":
                detail_url = link.get("uri") or ""
                break

        if not detail_url:
            detail_url = advert.get("selfLink") or ""

        parsed.append(
            {
                "title": title,
                "price": _parse_price(str(price_text)),
                "location": location,
                "url": detail_url,
                "description": description,
            }
        )

    return [item for item in parsed if item["title"]]


def scrape_willhaben(keyword: str, max_pages: int = 5, timeout: int = 10) -> list[dict]:
    """
    Scrape willhaben.at marketplace for *keyword* and return a list of product dicts.

    Each dict contains: title, price (float|None), location, url, description.
    """
    results = []
    logger.info(
        "Starting willhaben scrape: keyword='%s', max_pages=%d, timeout=%ss",
        keyword,
        max_pages,
        timeout,
    )

    for page in range(1, max_pages + 1):
        params = {"keyword": keyword, "page": page}
        page_url = requests.Request("GET", WILLHABEN_SEARCH, params=params).prepare().url
        logger.info("Fetching page %d: %s", page, page_url)
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

        page_results = _extract_next_data_products(response.text)
        if page_results:
            logger.info(
                "Page %d: extracted %d listings from __NEXT_DATA__",
                page,
                len(page_results),
            )
            results.extend(page_results)
            if page < max_pages:
                time.sleep(1)
            continue

        logger.info(
            "Page %d: __NEXT_DATA__ extraction yielded 0 listings, trying HTML fallback",
            page,
        )

        soup = BeautifulSoup(response.text, "lxml")

        # willhaben renders listings inside <article> elements
        articles = soup.find_all("article")
        if not articles:
            # fallback: try common ad-list containers
            articles = soup.select("[data-testid='ad-card'], li.search-result")

        if not articles:
            logger.info("No listing containers found on page %d - stopping.", page)
            break

        page_results = [_parse_listing(a) for a in articles]
        # Filter out empty titles (navigation articles etc.)
        page_results = [p for p in page_results if p["title"]]
        logger.info("Page %d: extracted %d listings from HTML", page, len(page_results))
        results.extend(page_results)

        # Be polite – short delay between pages
        if page < max_pages:
            time.sleep(1)

    logger.info("Scraping done for '%s': %d listings total", keyword, len(results))

    return results
