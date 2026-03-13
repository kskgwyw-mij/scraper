"""Tests for app.services.image_classifier."""

import io
from unittest.mock import MagicMock, patch

import pytest

from app.services.image_classifier import (
    BETTER_RESULT_THRESHOLD,
    _download_image,
    classify_products,
    score_image_keyword_match,
)


# ── helpers ──────────────────────────────────────────────────────────────────

class _FakeProduct:
    """Minimal product-like object for testing classify_products."""

    def __init__(self, image_url=None):
        self.image_url = image_url
        self.image_match_score = None
        self.is_better_result = False


def _make_tiny_jpeg_bytes() -> bytes:
    """Return a minimal valid JPEG byte string using Pillow."""
    from PIL import Image

    img = Image.new("RGB", (8, 8), color=(128, 64, 32))
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


# ── score_image_keyword_match ────────────────────────────────────────────────

def test_score_returns_none_for_empty_url():
    assert score_image_keyword_match("", "bicycle") is None


def test_score_returns_none_for_empty_keyword():
    assert score_image_keyword_match("https://example.com/img.jpg", "") is None


def test_score_returns_none_when_clip_unavailable():
    """When CLIP is not installed the function should return None gracefully."""
    import app.services.image_classifier as ic

    original = ic._clip_available
    try:
        ic._clip_available = False
        result = score_image_keyword_match("https://example.com/img.jpg", "bicycle")
        assert result is None
    finally:
        ic._clip_available = original


def test_score_returns_none_when_image_download_fails():
    """If the image cannot be downloaded the score should be None."""
    import app.services.image_classifier as ic

    original = ic._clip_available
    try:
        # Pretend CLIP is available
        ic._clip_available = True
        ic._clip_model = MagicMock()
        ic._clip_processor = MagicMock()

        with patch("app.services.image_classifier._download_image", return_value=None):
            result = score_image_keyword_match(
                "https://example.com/missing.jpg", "bicycle"
            )
        assert result is None
    finally:
        ic._clip_available = original
        ic._clip_model = None
        ic._clip_processor = None


def test_score_uses_clip_when_available():
    """When CLIP is available the score should be the cosine similarity float."""
    import app.services.image_classifier as ic

    original_available = ic._clip_available
    original_model = ic._clip_model
    original_processor = ic._clip_processor
    try:
        # Build a mock CLIP model that returns unit vectors → similarity = 1.0
        import torch

        ones = torch.ones(1, 512)

        mock_model = MagicMock()
        mock_model.get_image_features.return_value = ones.clone()
        mock_model.get_text_features.return_value = ones.clone()

        mock_processor = MagicMock()
        mock_processor.return_value = {
            "pixel_values": torch.zeros(1, 3, 224, 224),
            "input_ids": torch.zeros(1, 10, dtype=torch.long),
            "attention_mask": torch.ones(1, 10, dtype=torch.long),
        }

        from PIL import Image as PILImage

        dummy_image = PILImage.new("RGB", (8, 8))

        ic._clip_available = True
        ic._clip_model = mock_model
        ic._clip_processor = mock_processor

        with patch(
            "app.services.image_classifier._download_image", return_value=dummy_image
        ):
            result = score_image_keyword_match(
                "https://example.com/img.jpg", "bicycle"
            )

        assert result is not None
        assert isinstance(result, float)
        # unit vectors → cosine sim = 1.0
        assert result == pytest.approx(1.0, abs=1e-4)

    except ImportError:
        pytest.skip("torch not installed")
    finally:
        ic._clip_available = original_available
        ic._clip_model = original_model
        ic._clip_processor = original_processor


# ── _download_image ───────────────────────────────────────────────────────────

def test_download_image_returns_none_on_http_error():
    with patch("app.services.image_classifier.requests.get") as mock_get:
        mock_get.side_effect = Exception("network error")
        result = _download_image("https://example.com/img.jpg")
    assert result is None


def test_download_image_returns_pil_image():
    from PIL import Image as PILImage

    jpeg_bytes = _make_tiny_jpeg_bytes()

    mock_response = MagicMock()
    mock_response.content = jpeg_bytes
    mock_response.raise_for_status.return_value = None

    with patch("app.services.image_classifier.requests.get", return_value=mock_response):
        result = _download_image("https://example.com/img.jpg")

    assert result is not None
    assert isinstance(result, PILImage.Image)
    assert result.mode == "RGB"


# ── classify_products ─────────────────────────────────────────────────────────

def test_classify_products_sets_fields_when_no_image():
    """Products without an image_url must get score=None and is_better_result=False."""
    product = _FakeProduct(image_url=None)
    classify_products([product], "bicycle")
    assert product.image_match_score is None
    assert product.is_better_result is False


def test_classify_products_marks_better_result_above_threshold():
    """Products with a score >= BETTER_RESULT_THRESHOLD become is_better_result=True."""
    product = _FakeProduct(image_url="https://example.com/img.jpg")

    high_score = BETTER_RESULT_THRESHOLD + 0.05
    with patch(
        "app.services.image_classifier.score_image_keyword_match",
        return_value=high_score,
    ):
        classify_products([product], "bicycle")

    assert product.image_match_score == pytest.approx(high_score)
    assert product.is_better_result is True


def test_classify_products_does_not_mark_better_result_below_threshold():
    """Products with a score < BETTER_RESULT_THRESHOLD keep is_better_result=False."""
    product = _FakeProduct(image_url="https://example.com/img.jpg")

    low_score = BETTER_RESULT_THRESHOLD - 0.05
    with patch(
        "app.services.image_classifier.score_image_keyword_match",
        return_value=low_score,
    ):
        classify_products([product], "bicycle")

    assert product.image_match_score == pytest.approx(low_score)
    assert product.is_better_result is False


def test_classify_products_handles_mixed_products():
    """classify_products processes all products in one call."""
    p1 = _FakeProduct(image_url="https://example.com/a.jpg")
    p2 = _FakeProduct(image_url=None)
    p3 = _FakeProduct(image_url="https://example.com/b.jpg")

    scores = {
        "https://example.com/a.jpg": BETTER_RESULT_THRESHOLD + 0.1,
        "https://example.com/b.jpg": BETTER_RESULT_THRESHOLD - 0.1,
    }

    def _mock_score(url, keyword):
        return scores.get(url)

    with patch(
        "app.services.image_classifier.score_image_keyword_match",
        side_effect=_mock_score,
    ):
        classify_products([p1, p2, p3], "bicycle")

    assert p1.is_better_result is True
    assert p2.is_better_result is False
    assert p3.is_better_result is False


def test_classify_products_handles_score_none():
    """A None score (e.g. CLIP unavailable) means is_better_result=False."""
    product = _FakeProduct(image_url="https://example.com/img.jpg")

    with patch(
        "app.services.image_classifier.score_image_keyword_match", return_value=None
    ):
        classify_products([product], "bicycle")

    assert product.image_match_score is None
    assert product.is_better_result is False
