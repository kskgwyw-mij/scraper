from datetime import datetime, timezone
from app import db


class SearchQuery(db.Model):
    """Stores a user's product search keyword and its metadata."""

    __tablename__ = "search_queries"

    id = db.Column(db.Integer, primary_key=True)
    keyword = db.Column(db.String(255), nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    products = db.relationship(
        "Product", backref="search_query", lazy=True, cascade="all, delete-orphan"
    )

    def __repr__(self):
        return f"<SearchQuery id={self.id} keyword='{self.keyword}'>"


class Product(db.Model):
    """Stores a single product listing scraped from willhaben.at."""

    __tablename__ = "products"

    id = db.Column(db.Integer, primary_key=True)
    search_query_id = db.Column(
        db.Integer, db.ForeignKey("search_queries.id"), nullable=False, index=True
    )
    title = db.Column(db.String(500), nullable=False)
    price = db.Column(db.Float, nullable=True)
    location = db.Column(db.String(255), nullable=True)
    url = db.Column(db.String(1000), nullable=True)
    image_url = db.Column(db.String(1000), nullable=True)
    description = db.Column(db.Text, nullable=True)
    published_at = db.Column(db.DateTime, nullable=True)
    scraped_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    image_match_score = db.Column(db.Float, nullable=True)
    is_better_result = db.Column(db.Boolean, nullable=False, default=False)

    def to_dict(self):
        return {
            "id": self.id,
            "title": self.title,
            "price": self.price,
            "location": self.location,
            "url": self.url,
            "image_url": self.image_url,
            "description": self.description,
            "published_at": self.published_at.isoformat() if self.published_at else None,
            "scraped_at": self.scraped_at.isoformat() if self.scraped_at else None,
            "image_match_score": self.image_match_score,
            "is_better_result": self.is_better_result,
        }

    def __repr__(self):
        return f"<Product id={self.id} title='{self.title[:40]}' price={self.price}>"
