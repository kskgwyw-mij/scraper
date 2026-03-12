import pytest
from app.services.price_predictor import predict_price


def _make_products(prices):
    """Create simple mock product objects."""
    class FakeProduct:
        def __init__(self, price):
            self.price = price
    return [FakeProduct(p) for p in prices]


def test_predict_returns_none_for_empty():
    result = predict_price([])
    assert result["predicted_price"] is None
    assert result["count"] == 0


def test_predict_returns_none_for_too_few():
    result = predict_price(_make_products([100.0, 200.0]))
    assert result["predicted_price"] is None
    assert result["count"] == 2


def test_predict_median_price():
    prices = [100, 150, 200, 250, 300, 350, 400]
    result = predict_price(_make_products(prices), percentile=50)
    assert result["predicted_price"] is not None
    assert result["min"] <= result["predicted_price"] <= result["max"]


def test_predict_statistics():
    prices = [100.0, 200.0, 300.0, 400.0, 500.0]
    result = predict_price(_make_products(prices), percentile=50)
    assert result["mean"] == pytest.approx(300.0, abs=5)
    assert result["median"] == pytest.approx(300.0, abs=5)
    assert result["min"] is not None
    assert result["max"] is not None


def test_predict_ignores_none_prices():
    prices = [None, 100.0, None, 200.0, 300.0, None]
    result = predict_price(_make_products(prices), percentile=50)
    # Should still work with 3 valid prices
    assert result["predicted_price"] is not None


def test_predict_low_percentile_lower_than_high():
    prices = list(range(100, 600, 20))  # 25 values
    low = predict_price(_make_products(prices), percentile=25)
    high = predict_price(_make_products(prices), percentile=75)
    assert low["predicted_price"] < high["predicted_price"]
