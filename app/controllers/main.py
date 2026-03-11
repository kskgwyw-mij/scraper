from flask import Blueprint, render_template, current_app
from app.models import SearchQuery

main_bp = Blueprint("main", __name__)


@main_bp.route("/")
def index():
    """Landing page – shows recent searches."""
    recent_searches = (
        SearchQuery.query.order_by(SearchQuery.created_at.desc()).limit(10).all()
    )
    return render_template(
        "index.html",
        recent_searches=recent_searches,
        default_max_pages=current_app.config.get("SCRAPE_MAX_PAGES", 5),
    )
