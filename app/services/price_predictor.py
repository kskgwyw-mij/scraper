import logging

import numpy as np
from sklearn.linear_model import Ridge
from sklearn.preprocessing import PolynomialFeatures
from sklearn.pipeline import Pipeline

logger = logging.getLogger(__name__)


def _prices_array(products) -> np.ndarray:
    """Return a sorted 1-D numpy array of valid prices from a product list."""
    prices = [
        p.price if hasattr(p, "price") else p.get("price")
        for p in products
    ]
    valid = sorted([float(v) for v in prices if v is not None and float(v) > 0])
    return np.array(valid, dtype=float)


def predict_price(products, percentile: float = 50.0) -> dict:
    """
    Predict a 'good' selling price for a product based on the collected listings.

    Strategy:
    - Remove extreme outliers (below 5th / above 95th percentile).
    - Fit a Ridge regression on the position vs. price to learn the distribution.
    - Return the predicted price at *percentile* along with summary statistics.

    Returns a dict with keys:
        predicted_price, mean, median, min, max, count, percentile
    Returns None values when fewer than 3 valid prices are available.
    """
    prices = _prices_array(products)

    result = {
        "predicted_price": None,
        "mean": None,
        "median": None,
        "min": None,
        "max": None,
        "count": int(len(prices)),
        "percentile": percentile,
    }

    if len(prices) < 3:
        logger.info("Not enough price data for prediction (%d samples).", len(prices))
        return result

    # Remove outliers
    lower = np.percentile(prices, 5)
    upper = np.percentile(prices, 95)
    filtered = prices[(prices >= lower) & (prices <= upper)]

    if len(filtered) < 3:
        filtered = prices

    result["mean"] = round(float(np.mean(filtered)), 2)
    result["median"] = round(float(np.median(filtered)), 2)
    result["min"] = round(float(filtered.min()), 2)
    result["max"] = round(float(filtered.max()), 2)
    result["count"] = int(len(filtered))

    # Build a simple polynomial regression over sorted price positions
    x = np.linspace(0, 1, len(filtered)).reshape(-1, 1)
    y = filtered

    model = Pipeline(
        [("poly", PolynomialFeatures(degree=2)), ("ridge", Ridge(alpha=1.0))]
    )
    model.fit(x, y)

    # Predict at the requested percentile position
    target_x = np.array([[percentile / 100.0]])
    predicted = float(model.predict(target_x)[0])
    result["predicted_price"] = round(max(predicted, 0.0), 2)

    return result
