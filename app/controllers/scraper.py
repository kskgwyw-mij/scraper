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

        max_pages = current_app.config.get("SCRAPE_MAX_PAGES", 5)
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


@scraper_bp.route("/delete/<int:search_id>", methods=["POST"])
def delete_search(search_id: int):
    """Delete a search query and all its associated products."""
    search_query = _get_search_or_404(search_id)
    db.session.delete(search_query)
    db.session.commit()
    flash(f"Deleted search '{search_query.keyword}'.", "info")
    return redirect(url_for("main.index"))
