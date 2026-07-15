"""Presentation-layer formatting helpers."""

import base64


def image_to_base64(img: bytes) -> str:
    """Encode raw image bytes as a base64 string for data: URIs and JSON."""
    return base64.b64encode(img).decode()
