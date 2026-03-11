from flask import Flask
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


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

    return app
