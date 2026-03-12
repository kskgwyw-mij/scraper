import logging

from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import inspect, text

db = SQLAlchemy()
logger = logging.getLogger(__name__)


def _ensure_schema() -> None:
    """Apply lightweight schema updates for existing databases."""
    inspector = inspect(db.engine)
    if "products" not in inspector.get_table_names():
        return

    product_columns = {column["name"] for column in inspector.get_columns("products")}
    if "image_url" in product_columns:
        return

    with db.engine.begin() as connection:
        connection.execute(text("ALTER TABLE products ADD COLUMN image_url VARCHAR(1000)"))

    logger.info("Added missing column 'products.image_url'.")


def create_app(config_name="default"):
    from config import config

    app = Flask(__name__)
    app.config.from_object(config[config_name])

    db.init_app(app)

    from app.controllers.main import main_bp
    from app.controllers.scraper import scraper_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(scraper_bp, url_prefix="/scraper")

    with app.app_context():
        db.create_all()
        _ensure_schema()

    return app
