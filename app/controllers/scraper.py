from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app, abort
import logging
from app import db
from app.models import SearchQuery, Product
from app.services.willhaben_scraper import scrape_willhaben
from app.services.price_predictor import predict_price
from app.services.image_classifier import classify_products

scraper_bp = Blueprint("scraper", __name__)
logger = logging.getLogger(__name__)


def _get_search_or_404(search_id: int) -> SearchQuery:
    sq = db.session.get(SearchQuery, search_id)
    if sq is None:
        abort(404)
    return sq


def _get_percentile_arg() -> float:
    """Return a clamped percentile query parameter."""
    try:
        percentile = float(request.args.get("percentile", 50))
        return max(1.0, min(99.0, percentile))
    except (ValueError, TypeError):
        return 50.0


def _get_catalog_filters() -> dict[str, object]:
    """Read catalog filter values from the current request."""
    sort_by = request.args.get("sort", "newest", type=str)
    if sort_by not in {"newest", "oldest", "price_asc", "price_desc"}:
        sort_by = "newest"

    return {
        "search_keyword": request.args.get("search", "", type=str).strip(),
        "min_price": request.args.get("min_price", "", type=str).strip(),
        "max_price": request.args.get("max_price", "", type=str).strip(),
        "location_filter": request.args.get("location", "", type=str).strip(),
        "sort_by": sort_by,
        "better_only": bool(request.args.get("better_only", type=str)),
    }


def _apply_catalog_filters(query, filters: dict[str, object]):
    """Apply catalog filters to a product query."""
    search_keyword = str(filters["search_keyword"])
    min_price = str(filters["min_price"])
    max_price = str(filters["max_price"])
    location_filter = str(filters["location_filter"])
    better_only = bool(filters["better_only"])

    if search_keyword:
        query = query.filter(Product.title.ilike(f"%{search_keyword}%"))

    if min_price:
        try:
            query = query.filter(Product.price >= float(min_price))
        except ValueError:
            pass

    if max_price:
        try:
            query = query.filter(Product.price <= float(max_price))
        except ValueError:
            pass

    if location_filter:
        query = query.filter(Product.location.ilike(f"%{location_filter}%"))

    if better_only:
        query = query.filter(Product.is_better_result.is_(True))

    return query


def _apply_catalog_sorting(query, sort_by: str):
    """Apply the selected catalog sorting to a product query."""
    if sort_by == "price_asc":
        return query.order_by(Product.price.asc().nulls_last())
    if sort_by == "price_desc":
        return query.order_by(Product.price.desc().nulls_last())
    if sort_by == "oldest":
        return query.order_by(Product.scraped_at.asc())
    return query.order_by(Product.scraped_at.desc())


@scraper_bp.route("/search", methods=["GET", "POST"])
def search():
    """Trigger a new scrape for a given keyword."""
    if request.method == "POST":
        keyword = request.form.get("keyword", "").strip()
        if not keyword:
            flash("Please enter a search keyword.", "warning")
            return redirect(url_for("main.index"))

        default_max_pages = current_app.config.get("SCRAPE_MAX_PAGES", 5)
        raw_max_pages = request.form.get("max_pages", "").strip()
        try:
            max_pages = int(raw_max_pages) if raw_max_pages else default_max_pages
        except (TypeError, ValueError):
            max_pages = default_max_pages

        max_pages = max(1, max_pages)
        timeout = current_app.config.get("SCRAPE_REQUEST_TIMEOUT", 10)

        logger.info(
            "Search requested: keyword='%s', max_pages=%d, timeout=%ss",
            keyword,
            max_pages,
            timeout,
        )

        raw_products = scrape_willhaben(keyword, max_pages=max_pages, timeout=timeout)
        logger.info("Search finished: keyword='%s', products=%d", keyword, len(raw_products))

        search_query = SearchQuery(keyword=keyword)
        db.session.add(search_query)
        db.session.flush()  # get the id before adding products

        products_to_classify = []
        for item in raw_products:
            product = Product(
                search_query_id=search_query.id,
                title=item["title"],
                price=item["price"],
                location=item["location"],
                url=item["url"],
                image_url=item.get("image_url"),
                description=item["description"],
                published_at=item.get("published_at"),
            )
            db.session.add(product)
            products_to_classify.append(product)

        # Score each product image against the search keyword.
        # classify_products sets image_match_score and is_better_result on every
        # product in place.  When CLIP is unavailable the call is a fast no-op
        # and all products remain is_better_result=False.
        classify_products(products_to_classify, keyword)
        logger.info(
            "Image classification done: keyword='%s', better=%d/%d",
            keyword,
            sum(1 for p in products_to_classify if p.is_better_result),
            len(products_to_classify),
        )

        db.session.commit()
        flash(f"Scraped {len(raw_products)} listings for '{keyword}'.", "success")
        return redirect(url_for("scraper.products", search_id=search_query.id))

    return redirect(url_for("main.index"))


@scraper_bp.route("/products/<int:search_id>")
def products(search_id: int):
    """Display all scraped products for a search query."""
    search_query = _get_search_or_404(search_id)
    all_products = (
        Product.query.filter_by(search_query_id=search_id)
        .order_by(Product.price.asc().nulls_last())
        .all()
    )

    better_results = [p for p in all_products if p.is_better_result]
    other_results = [p for p in all_products if not p.is_better_result]

    return render_template(
        "products.html",
        search_query=search_query,
        products=all_products,
        better_results=better_results,
        other_results=other_results,
    )


@scraper_bp.route("/predict/<int:search_id>")
def predict(search_id: int):
    """Show price prediction for a search query's better-result products."""
    search_query = _get_search_or_404(search_id)
    all_products = Product.query.filter_by(
        search_query_id=search_id,
        is_better_result=True,
    ).all()

    percentile = _get_percentile_arg()

    prediction = predict_price(all_products, percentile=percentile)
    return render_template(
        "prediction.html",
        search_query=search_query,
        prediction=prediction,
        percentile=percentile,
    )


@scraper_bp.route("/catalog")
def catalog():
    """Display a catalog of all scraped products from the database."""
    page = request.args.get("page", 1, type=int)
    filters = _get_catalog_filters()
    percentile = _get_percentile_arg()

    query = _apply_catalog_filters(Product.query, filters)
    total_products = query.count()

    query = _apply_catalog_sorting(query, filters["sort_by"])

    # Pagination (20 items per page)
    items_per_page = 20
    paginated = query.paginate(page=page, per_page=items_per_page, error_out=False)

    # Get unique searches for statistics
    search_queries = SearchQuery.query.all()

    return render_template(
        "catalog.html",
        paginated=paginated,
        products=paginated.items,
        search_keyword=filters["search_keyword"],
        min_price=filters["min_price"],
        max_price=filters["max_price"],
        location_filter=filters["location_filter"],
        sort_by=filters["sort_by"],
        better_only=filters["better_only"],
        percentile=percentile,
        total_products=total_products,
        search_queries=search_queries,
    )


@scraper_bp.route("/catalog/predict")
def catalog_predict():
    """Show a price prediction for the currently filtered catalog results."""
    filters = _get_catalog_filters()
    percentile = _get_percentile_arg()

    filtered_products = _apply_catalog_filters(Product.query, filters).all()
    prediction = predict_price(filtered_products, percentile=percentile)

    return render_template(
        "catalog_prediction.html",
        prediction=prediction,
        percentile=percentile,
        search_keyword=filters["search_keyword"],
        min_price=filters["min_price"],
        max_price=filters["max_price"],
        location_filter=filters["location_filter"],
        sort_by=filters["sort_by"],
        better_only=filters["better_only"],
        total_products=len(filtered_products),
    )


@scraper_bp.route("/delete/<int:search_id>", methods=["POST"])
def delete_search(search_id: int):
    """Delete a search query and all its associated products."""
    search_query = _get_search_or_404(search_id)
    db.session.delete(search_query)
    db.session.commit()
    flash(f"Deleted search '{search_query.keyword}'.", "info")
    return redirect(url_for("main.index"))
