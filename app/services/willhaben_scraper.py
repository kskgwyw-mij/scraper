import re
import time
import logging
import json
from datetime import datetime, timezone

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

_CONDITION_SPLIT_REGEX = re.compile(r"(?<!^)(?=[A-Z])")


def _normalize_url(url: str | None) -> str | None:
    """Return an absolute URL for willhaben resources."""
    if not url:
        return None
    if url.startswith("//"):
        return f"https:{url}"
    if url.startswith("/"):
        return f"{WILLHABEN_BASE}{url}"
    return url


def _parse_price(text: str):
    """Extract a float price from a price string like '€ 1.234,56' or '1234,56 €'."""
    if not text:
        return None
    cleaned = re.sub(r"[^\d,.]", "", text.replace(".", "").replace(",", "."))
    try:
        return float(cleaned)
    except (ValueError, TypeError):
        return None


def _clean_text(value: str | None) -> str:
    """Strip HTML and normalize whitespace from a text value."""
    if not value:
        return ""
    text = BeautifulSoup(str(value), "lxml").get_text(" ", strip=True)
    return re.sub(r"\s+", " ", text).strip()


def _extract_next_data_payload(html: str) -> dict | None:
    """Return the parsed __NEXT_DATA__ payload from a page, if present."""
    match = re.search(
        r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
        html,
        re.DOTALL,
    )
    if not match:
        return None

    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError as exc:
        logger.warning("Failed to decode __NEXT_DATA__ payload: %s", exc)
        return None


def _parse_published_at(value: str | None) -> datetime | None:
    """Parse a published-at timestamp string into a naive UTC datetime.

    Willhaben stores the publication date as an ISO-8601 string (e.g.
    ``"2024-01-15T10:30:00"``) or as a Unix timestamp in milliseconds.
    Returns ``None`` when the value cannot be parsed.
    """
    if not value:
        return None
    # Millisecond Unix timestamp stored as a numeric string.
    # Timestamps with more than 10 digits are in milliseconds (> year 2001 in ms).
    _MS_TIMESTAMP_MIN_DIGITS = 11
    stripped = value.strip()
    if re.fullmatch(r"\d{10,13}", stripped):
        ts_int = int(stripped)
        if len(stripped) >= _MS_TIMESTAMP_MIN_DIGITS:
            ts_int = ts_int // 1000
        return datetime.fromtimestamp(ts_int, tz=timezone.utc).replace(tzinfo=None)
    # ISO-8601 variants
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d"):
        try:
            return datetime.strptime(stripped, fmt)
        except ValueError:
            continue
    return None


def _normalize_item_condition(value: str | None) -> str | None:
    """Normalize schema.org item conditions like 'UsedCondition'."""
    if not value:
        return None

    condition = value.rsplit("/", maxsplit=1)[-1].strip()
    if not condition:
        return None

    return _CONDITION_SPLIT_REGEX.sub(" ", condition)


def _extract_image_url(article) -> str | None:
    """Extract the most useful image URL from a listing article."""
    image_tag = article.find("img")
    if image_tag is None:
        return None

    for attr in ("data-src", "src", "data-original", "data-image"):
        image_url = image_tag.get(attr)
        if image_url:
            return _normalize_url(image_url)

    srcset = image_tag.get("srcset") or image_tag.get("data-srcset")
    if not srcset:
        return None

    first_candidate = srcset.split(",")[0].strip().split(" ")[0]
    return _normalize_url(first_candidate)


def _parse_listing(article) -> dict:
    """Parse a single search-result article tag into a product dict."""
    title_tag = (
        article.find("a", attrs={"data-testid": "ad-detail-link"})
        or article.find("h2")
        or article.find("h3")
    )
    title = title_tag.get_text(strip=True) if title_tag else ""

    href = title_tag.get("href", "") if title_tag else ""
    url = _normalize_url(href) or ""

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
    image_url = _extract_image_url(article)

    # Try to extract the publication date from a <time> element or a
    # dedicated data-testid attribute used by willhaben's rendered HTML.
    published_at: datetime | None = None
    date_tag = article.find(attrs={"data-testid": "ad-posted-date"}) or article.find(
        "time"
    )
    if date_tag:
        raw_date = date_tag.get("datetime") or date_tag.get_text(strip=True)
        published_at = _parse_published_at(raw_date)

    return {
        "title": title,
        "price": price,
        "location": location,
        "url": url,
        "image_url": image_url,
        "description": description,
        "published_at": published_at,
        "seller_name": None,
        "item_condition": None,
        "category_path": None,
    }


def _extract_html_products(html: str) -> list[dict]:
    """Extract products from rendered HTML articles."""
    soup = BeautifulSoup(html, "lxml")

    articles = soup.find_all("article")
    if not articles:
        articles = soup.select("[data-testid='ad-card'], li.search-result")

    if not articles:
        return []

    page_results = [_parse_listing(article) for article in articles]
    return [product for product in page_results if product["title"]]


def _extract_advert_image_url(advert: dict) -> str | None:
    """Extract an image URL from an advert summary in __NEXT_DATA__."""
    advert_images = ((advert.get("advertImageList") or {}).get("advertImage")) or []
    for image in advert_images:
        image_url = _normalize_url(
            image.get("mainImageUrl")
            or image.get("thumbnailImageUrl")
            or image.get("referenceImageUrl")
        )
        if image_url:
            return image_url
    return None


def _merge_image_urls(primary_results: list[dict], html_results: list[dict]) -> list[dict]:
    """Backfill missing image URLs in JSON-derived results from parsed HTML."""
    image_by_url = {
        item["url"]: item.get("image_url")
        for item in html_results
        if item.get("url") and item.get("image_url")
    }
    image_by_title = {
        item["title"]: item.get("image_url")
        for item in html_results
        if item.get("title") and item.get("image_url")
    }

    for item in primary_results:
        item["image_url"] = (
            item.get("image_url")
            or image_by_url.get(item.get("url", ""))
            or image_by_title.get(item.get("title", ""))
        )

    return primary_results


def _extract_product_json_ld(soup: BeautifulSoup) -> dict:
    """Extract Product JSON-LD object from a detail page."""
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw_payload = script.string or script.get_text()
        if not raw_payload:
            continue

        try:
            payload = json.loads(raw_payload)
        except json.JSONDecodeError:
            continue

        candidates = payload if isinstance(payload, list) else [payload]
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue

            candidate_type = candidate.get("@type")
            if isinstance(candidate_type, list):
                is_product = "Product" in candidate_type
            else:
                is_product = candidate_type == "Product"

            if is_product:
                return candidate

    return {}


def _extract_detail_data(html: str) -> dict:
    """Extract additional listing details from an advert detail page."""
    detail_data: dict[str, object] = {}

    soup = BeautifulSoup(html, "lxml")
    product_json_ld = _extract_product_json_ld(soup)
    if product_json_ld:
        offers = product_json_ld.get("offers")
        if isinstance(offers, dict):
            seller = offers.get("seller")
            if isinstance(seller, dict):
                seller_name = _clean_text(seller.get("name"))
                if seller_name:
                    detail_data["seller_name"] = seller_name

            offer_price = _parse_price(str(offers.get("price") or ""))
            if offer_price is not None:
                detail_data["price"] = offer_price

            item_condition = _normalize_item_condition(offers.get("itemCondition"))
            if item_condition:
                detail_data["item_condition"] = item_condition

        ld_image = _normalize_url(product_json_ld.get("image"))
        if ld_image:
            detail_data["image_url"] = ld_image

    payload = _extract_next_data_payload(html) or {}
    page_props = (payload.get("props") or {}).get("pageProps") or {}
    advert_details = page_props.get("advertDetails") or {}
    if not advert_details:
        return detail_data

    attributes = ((advert_details.get("attributes") or {}).get("attribute")) or []
    attr_map: dict[str, list[str]] = {}
    for entry in attributes:
        name = entry.get("name")
        raw_values = entry.get("values") or []
        values = [cleaned for raw in raw_values if (cleaned := _clean_text(raw))]
        if name and values:
            attr_map[name] = values

    description = _clean_text(advert_details.get("description"))
    if not description:
        description = (attr_map.get("DESCRIPTION") or [""])[0]
    if description:
        detail_data["description"] = description

    # Prefer the detail-page publication timestamp when available.
    published_value = (
        advert_details.get("publishedDate")
        or advert_details.get("firstPublishedDate")
        or advert_details.get("startDate")
        or (attr_map.get("PUBLISHED") or attr_map.get("STARTDATE") or [""])[0]
    )
    published_at = _parse_published_at(str(published_value)) if published_value else None
    if published_at:
        detail_data["published_at"] = published_at

    if "seller_name" not in detail_data:
        seller_name = _clean_text((advert_details.get("organisationDetails") or {}).get("orgName"))
        if not seller_name:
            seller_name = _clean_text((advert_details.get("sellerProfileUserData") or {}).get("name"))
        if seller_name:
            detail_data["seller_name"] = seller_name

    address_details = advert_details.get("advertAddressDetails") or {}
    location_candidates = [
        address_details.get("postalName"),
        address_details.get("district"),
        address_details.get("province"),
        (attr_map.get("LOCATION/ADDRESS_2") or [""])[0],
        (attr_map.get("LOCATION/ADDRESS_3") or [""])[0],
        (attr_map.get("LOCATION/ADDRESS_4") or [""])[0],
    ]
    location_parts: list[str] = []
    seen_locations: set[str] = set()
    for candidate in location_candidates:
        cleaned = _clean_text(candidate)
        normalized = cleaned.casefold()
        if cleaned and normalized not in seen_locations:
            location_parts.append(cleaned)
            seen_locations.add(normalized)
    if location_parts:
        detail_data["location"] = ", ".join(location_parts)

    breadcrumbs = advert_details.get("breadcrumbs") or []
    category_segments = [
        _clean_text(crumb.get("displayName"))
        for crumb in breadcrumbs
        if isinstance(crumb, dict)
    ]
    category_segments = [segment for segment in category_segments if segment]
    category_segments = [
        segment
        for segment in category_segments
        if segment.casefold() not in {"startseite", "marktplatz"}
    ]
    if category_segments:
        detail_data["category_path"] = " > ".join(category_segments)

    return detail_data


def _merge_detail_data(listing: dict, detail_data: dict) -> dict:
    """Merge detail-page values into a listing dictionary."""
    merged = dict(listing)

    if detail_data.get("description"):
        merged["description"] = detail_data["description"]

    for key in ("published_at", "seller_name", "item_condition", "category_path"):
        value = detail_data.get(key)
        if value not in (None, ""):
            merged[key] = value

    for key in ("price", "location", "image_url"):
        if merged.get(key) in (None, "") and detail_data.get(key) not in (None, ""):
            merged[key] = detail_data[key]

    return merged


def _enrich_results_with_details(results: list[dict], timeout: int) -> list[dict]:
    """Fetch detail pages and enrich listings with additional information."""
    if not results:
        return results

    enriched_results = []
    for index, item in enumerate(results, start=1):
        listing = dict(item)
        listing.setdefault("seller_name", None)
        listing.setdefault("item_condition", None)
        listing.setdefault("category_path", None)

        detail_url = listing.get("url")
        if not detail_url:
            enriched_results.append(listing)
            continue

        try:
            response = requests.get(detail_url, headers=HEADERS, timeout=timeout)
            response.raise_for_status()
            detail_data = _extract_detail_data(response.text)
            if detail_data:
                listing = _merge_detail_data(listing, detail_data)
        except Exception as exc:
            logger.debug("Failed to enrich listing from '%s': %s", detail_url, exc)

        enriched_results.append(listing)

        if index % 25 == 0 or index == len(results):
            logger.info(
                "Detail enrichment progress: %d/%d listings",
                index,
                len(results),
            )

    return enriched_results


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
    payload = _extract_next_data_payload(html)
    if not payload:
        return []

    page_props = (payload.get("props") or {}).get("pageProps") or {}
    search_result = page_props.get("searchResult") or {}
    adverts = (
        ((search_result.get("advertSummaryList") or {}).get("advertSummary")) or []
    )

    parsed: list[dict] = []
    for advert in adverts:
        attributes = ((advert.get("attributes") or {}).get("attribute")) or []
        attr_map = {}
        for entry in attributes:
            name = entry.get("name")
            values = entry.get("values") or []
            if name and values:
                attr_map[name] = values

        heading_values = attr_map.get("HEADING") or [advert.get("description") or ""]
        title = (heading_values[0] or "").strip()
        price_text = (attr_map.get("PRICE") or [""])[0]
        location = (attr_map.get("LOCATION") or [""])[0].strip()
        body_values = attr_map.get("BODY_DYN") or [advert.get("description") or ""]
        description = (body_values[0] or "").strip()

        # willhaben exposes the listing publication date under the "PUBLISHED"
        # or "STARTDATE" attribute (value is an ISO-8601 string or ms epoch).
        raw_published = (
            (attr_map.get("PUBLISHED") or attr_map.get("STARTDATE") or [""])[0]
        )
        published_at = _parse_published_at(str(raw_published)) if raw_published else None

        # Build the web URL for the listing on www.willhaben.at.
        # Priority:
        #   1. iadShareLink  → already a www.willhaben.at URL
        #   2. seoSelfLink   → api.willhaben.at URL; extract the SEO path and
        #                      map it to www.willhaben.at/iad/…
        #   3. advert id     → construct /iad/object?adId=<id> as last resort
        detail_url = ""
        links = ((advert.get("contextLinkList") or {}).get("contextLink")) or []
        link_by_id = {lnk.get("id"): lnk for lnk in links}

        detail_url = ""
        if "iadShareLink" in link_by_id:
            detail_url = link_by_id["iadShareLink"].get("uri") or ""
        if not detail_url and "adDetailLink" in link_by_id:
            detail_url = link_by_id["adDetailLink"].get("uri") or ""
        if not detail_url and "seoSelfLink" in link_by_id:
            seo_uri = link_by_id["seoSelfLink"].get("uri") or ""
            # seo_uri looks like: https://api.willhaben.at/restapi/v2/atverz/kaufen-und-verkaufen/d/{slug}/
            # The path after "/atverz/" maps directly under www.willhaben.at/iad/
            seo_match = re.search(r"/atverz/(kaufen-und-verkaufen/.+)", seo_uri)
            if seo_match:
                detail_url = f"{WILLHABEN_BASE}/iad/{seo_match.group(1)}"
        advert_id = advert.get("id") or ""
        if not detail_url and advert_id:
            detail_url = f"{WILLHABEN_BASE}/iad/object?adId={advert_id}"
        image_url = _extract_advert_image_url(advert)

        detail_url = _normalize_url(detail_url) or ""
        image_url = _extract_advert_image_url(advert)

        parsed.append(
            {
                "title": title,
                "price": _parse_price(str(price_text)),
                "location": location,
                "url": detail_url,
                "image_url": image_url,
                "description": description,
                "published_at": published_at,
                "seller_name": None,
                "item_condition": None,
                "category_path": None,
            }
        )

    return [item for item in parsed if item["title"]]


def scrape_willhaben(
    keyword: str,
    max_pages: int = 5,
    timeout: int = 10,
    include_details: bool = True,
) -> list[dict]:
    """
    Scrape willhaben.at marketplace for *keyword* and return a list of product dicts.

    Each dict contains: title, price (float|None), location, url, image_url,
    description, published_at, seller_name, item_condition and category_path.
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
            if any(not item.get("image_url") for item in page_results):
                html_results = _extract_html_products(response.text)
                page_results = _merge_image_urls(page_results, html_results)
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

        page_results = _extract_html_products(response.text)
        if not page_results:
            logger.info("No listing containers found on page %d - stopping.", page)
            break

        logger.info("Page %d: extracted %d listings from HTML", page, len(page_results))
        results.extend(page_results)

        # Be polite – short delay between pages
        if page < max_pages:
            time.sleep(1)

    logger.info("Scraping done for '%s': %d listings total", keyword, len(results))

    if include_details and results:
        logger.info("Enriching %d listings with detail information", len(results))
        results = _enrich_results_with_details(results, timeout=timeout)

    return results
