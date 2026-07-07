"""Kalshi API authentication using RSA-PSS signed requests."""

from __future__ import annotations

import base64
import time
from pathlib import Path

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa


class KalshiAuth:
    """Handles RSA-PSS request signing for Kalshi API.

    Kalshi requires three headers on every authenticated request:
    - KALSHI-ACCESS-KEY: your API key ID
    - KALSHI-ACCESS-TIMESTAMP: millisecond Unix timestamp
    - KALSHI-ACCESS-SIGNATURE: RSA-PSS signature of (timestamp + method + path)
    """

    def __init__(self, key_id: str, private_key_path: str):
        self.key_id = key_id
        self._private_key = self._load_key(private_key_path)

    @staticmethod
    def _load_key(path: str) -> rsa.RSAPrivateKey:
        """Load RSA private key from PEM file."""
        key_path = Path(path)
        if not key_path.exists():
            raise FileNotFoundError(
                f"Private key not found at {path}. "
                f"Generate API keys at https://kalshi.com/account/api-keys "
                f"and save the PEM file to this path."
            )
        pem_data = key_path.read_bytes()
        private_key = serialization.load_pem_private_key(pem_data, password=None)
        if not isinstance(private_key, rsa.RSAPrivateKey):
            raise ValueError("Key must be an RSA private key")
        return private_key

    def sign(self, timestamp_ms: str, method: str, path: str) -> str:
        """Create RSA-PSS signature for a request.

        Args:
            timestamp_ms: Unix timestamp in milliseconds as string
            method: HTTP method (GET, POST, DELETE, etc.)
            path: Request path without query parameters (e.g., /trade-api/v2/markets)

        Returns:
            Base64-encoded signature string
        """
        # Strip query parameters from path for signing
        path_without_query = path.split("?")[0]

        # Build the message: timestamp + method + path
        message = f"{timestamp_ms}{method}{path_without_query}".encode("utf-8")

        # Sign with RSA-PSS
        signature = self._private_key.sign(
            message,
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.DIGEST_LENGTH,
            ),
            hashes.SHA256(),
        )

        return base64.b64encode(signature).decode("utf-8")

    def get_headers(self, method: str, path: str) -> dict[str, str]:
        """Generate the three authentication headers for a request.

        Args:
            method: HTTP method (uppercase)
            path: Full request path (query params will be stripped for signing)

        Returns:
            Dict with KALSHI-ACCESS-KEY, KALSHI-ACCESS-TIMESTAMP, KALSHI-ACCESS-SIGNATURE
        """
        timestamp_ms = str(int(time.time() * 1000))
        signature = self.sign(timestamp_ms, method.upper(), path)

        return {
            "KALSHI-ACCESS-KEY": self.key_id,
            "KALSHI-ACCESS-TIMESTAMP": timestamp_ms,
            "KALSHI-ACCESS-SIGNATURE": signature,
        }
