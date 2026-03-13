"""ML service for scoring product image–keyword relevance using CLIP.

Uses the CLIP (Contrastive Language–Image Pre-Training) model to compute a
cosine similarity between a product image and a search keyword.  Products whose
score meets or exceeds BETTER_RESULT_THRESHOLD are marked as *better results*.

Dependencies
------------
Requires ``transformers``, ``torch``, and ``Pillow``.  When these libraries are
absent the module degrades gracefully: every product keeps ``is_better_result``
set to ``False`` and ``image_match_score`` set to ``None``.
"""

import io
import logging
from typing import Optional

import requests

logger = logging.getLogger(__name__)

# ── model singleton ──────────────────────────────────────────────────────────
_clip_model = None
_clip_processor = None
_clip_available: Optional[bool] = None  # None = not yet tried

# Minimum (raw) cosine similarity to be labelled a "better result".
# CLIP cosine similarities are approximately in [-1, 1]; for product photos the
# practical range is roughly [0.05, 0.40].  A threshold of 0.25 captures images
# where the depicted product clearly corresponds to the search keyword.
BETTER_RESULT_THRESHOLD: float = 0.25

_IMAGE_DOWNLOAD_TIMEOUT: int = 5  # seconds


def _load_clip() -> bool:
    """Load the CLIP model lazily (once per process).

    Returns ``True`` on success, ``False`` when the required libraries are not
    installed or the model download fails.
    """
    global _clip_model, _clip_processor, _clip_available
    if _clip_available is not None:
        return _clip_available

    try:
        from transformers import CLIPModel, CLIPProcessor  # type: ignore[import]

        logger.info("Loading CLIP model (openai/clip-vit-base-patch32)…")
        _clip_model = CLIPModel.from_pretrained("openai/clip-vit-base-patch32")
        _clip_processor = CLIPProcessor.from_pretrained("openai/clip-vit-base-patch32")
        _clip_available = True
        logger.info("CLIP model ready.")
    except Exception as exc:  # ImportError, OSError, network errors, …
        _clip_available = False
        logger.warning("CLIP model unavailable – image scoring disabled: %s", exc)

    return bool(_clip_available)


def _download_image(image_url: str):
    """Download an image and return a PIL ``Image``, or ``None`` on failure."""
    try:
        from PIL import Image  # type: ignore[import]

        response = requests.get(
            image_url, timeout=_IMAGE_DOWNLOAD_TIMEOUT, stream=True
        )
        response.raise_for_status()
        return Image.open(io.BytesIO(response.content)).convert("RGB")
    except Exception as exc:
        logger.debug("Could not download image %s: %s", image_url, exc)
        return None


def score_image_keyword_match(image_url: str, keyword: str) -> Optional[float]:
    """Return a CLIP cosine similarity score between *image_url* and *keyword*.

    The raw cosine similarity is returned as-is (approximately in [-1, 1],
    practically in [0.05, 0.40] for product photos).

    Returns ``None`` when:
    * the CLIP libraries are not installed,
    * the image cannot be downloaded, or
    * any other error occurs during inference.
    """
    if not image_url or not keyword:
        return None
    if not _load_clip():
        return None

    image = _download_image(image_url)
    if image is None:
        return None

    try:
        import torch  # type: ignore[import]

        inputs = _clip_processor(
            text=[keyword],
            images=image,
            return_tensors="pt",
            padding=True,
            truncation=True,
        )
        with torch.no_grad():
            image_features = _clip_model.get_image_features(
                pixel_values=inputs["pixel_values"]
            )
            text_features = _clip_model.get_text_features(
                input_ids=inputs["input_ids"],
                attention_mask=inputs["attention_mask"],
            )

        # L2-normalise and compute cosine similarity
        image_features = image_features / image_features.norm(dim=-1, keepdim=True)
        text_features = text_features / text_features.norm(dim=-1, keepdim=True)
        similarity = float((image_features * text_features).sum(dim=-1))
        return similarity
    except Exception as exc:
        logger.warning("Error scoring image %s: %s", image_url, exc)
        return None


def classify_products(products, keyword: str) -> None:
    """Score each product's image against *keyword* and set classification fields.

    Updates ``image_match_score`` and ``is_better_result`` **in place** on every
    product object in *products*.  Products without an ``image_url`` receive
    ``score=None`` and ``is_better_result=False``.

    This function is intentionally side-effect only so that callers can persist
    the updated objects to the database immediately after calling it.
    """
    for product in products:
        image_url = getattr(product, "image_url", None)
        score = score_image_keyword_match(image_url, keyword) if image_url else None
        product.image_match_score = score
        product.is_better_result = score is not None and score >= BETTER_RESULT_THRESHOLD
