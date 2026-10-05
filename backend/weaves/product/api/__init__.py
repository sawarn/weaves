"""Product-native HTTP API, separate from the legacy POC routes."""

from weaves.product.api.app import create_app

__all__ = ["create_app"]
