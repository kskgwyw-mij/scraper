from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app, abort
import logging
from app import db
from app.models import SearchQuery, Product
from app.services.willhaben_scraper import scrape_willhaben
from app.services.price_predictor import predict_price

scraper_bp = Blueprint("scraper", __name__)
logger = logging.getLogger(__name__)


def _get_search_or_404(search_id: int) -> SearchQuery:
    sq = db.session.get(SearchQuery, search_id)
    if sq is None:
        abort(404)
    return sq


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

        for item in raw_products:
            product = Product(
                search_query_id=search_query.id,
                title=item["title"],
                price=item["price"],
                location=item["location"],
                url=item["url"],
                description=item["description"],
            )
            db.session.add(product)

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
    return render_template(
        "products.html",
        search_query=search_query,
        products=all_products,
    )


@scraper_bp.route("/predict/<int:search_id>")
def predict(search_id: int):
    """Show price prediction for a search query's products."""
    search_query = _get_search_or_404(search_id)
    all_products = Product.query.filter_by(search_query_id=search_id).all()

    try:
        percentile = float(request.args.get("percentile", 50))
        percentile = max(1.0, min(99.0, percentile))
    except (ValueError, TypeError):
        percentile = 50.0

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
    search_keyword = request.args.get("search", "", type=str).strip()
    min_price = request.args.get("min_price", "", type=str).strip()
    max_price = request.args.get("max_price", "", type=str).strip()
    location_filter = request.args.get("location", "", type=str).strip()
    sort_by = request.args.get("sort", "newest", type=str)

    # Build query
    query = Product.query

    # Apply filters
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

    # Count total products before pagination
    total_products = query.count()

    # Apply sorting
    if sort_by == "price_asc":
        query = query.order_by(Product.price.asc().nulls_last())
    elif sort_by == "price_desc":
        query = query.order_by(Product.price.desc().nulls_last())
    elif sort_by == "oldest":
        query = query.order_by(Product.scraped_at.asc())
    else:  # newest (default)
        query = query.order_by(Product.scraped_at.desc())

    # Pagination (20 items per page)
    items_per_page = 20
    paginated = query.paginate(page=page, per_page=items_per_page, error_out=False)

    # Get unique searches for statistics
    search_queries = SearchQuery.query.all()

    return render_template(
        "catalog.html",
        paginated=paginated,
        products=paginated.items,
        search_keyword=search_keyword,
        min_price=min_price,
        max_price=max_price,
        location_filter=location_filter,
        sort_by=sort_by,
        total_products=total_products,
        search_queries=search_queries,
    )


@scraper_bp.route("/delete/<int:search_id>", methods=["POST"])
def delete_search(search_id: int):
    """Delete a search query and all its associated products."""
    search_query = _get_search_or_404(search_id)
    db.session.delete(search_query)
    db.session.commit()
    flash(f"Deleted search '{search_query.keyword}'.", "info")
    return redirect(url_for("main.index"))
