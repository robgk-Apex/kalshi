"""Tests for RSA-PSS authentication signing in the active KalshiClient.

Auth correctness is money-critical: a bad signature means every request to
Kalshi is rejected, so the bot silently does nothing. These tests generate a
throwaway RSA key, sign with the client, and verify the signature with the
matching public key.
"""

import base64
import os
import tempfile
import unittest

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from src.api_client import KalshiClient


class TestKalshiAuth(unittest.TestCase):
    """Test the RSA-PSS signing on src.api_client.KalshiClient."""

    @classmethod
    def setUpClass(cls):
        """Generate a temporary RSA key pair for testing."""
        cls.private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048,
        )
        cls.public_key = cls.private_key.public_key()

        cls.key_file = tempfile.NamedTemporaryFile(
            suffix=".pem", delete=False, mode="wb"
        )
        cls.key_file.write(
            cls.private_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption(),
            )
        )
        cls.key_file.close()

    @classmethod
    def tearDownClass(cls):
        os.unlink(cls.key_file.name)

    def _make_client(self):
        return KalshiClient(
            base_url="https://demo-api.kalshi.co/trade-api/v2",
            key_id="test-key-id",
            private_key_path=self.key_file.name,
        )

    def test_client_loads_key(self):
        """Client should load the PEM key without error."""
        client = self._make_client()
        self.assertEqual(client.key_id, "test-key-id")
        self.assertIsNotNone(client.private_key)

    def test_missing_key_raises(self):
        """A missing key file should raise FileNotFoundError."""
        with self.assertRaises(FileNotFoundError):
            KalshiClient(
                base_url="https://demo-api.kalshi.co/trade-api/v2",
                key_id="x",
                private_key_path="/nonexistent/key.pem",
            )

    def test_public_client_is_unauthenticated(self):
        """With no key at all, the client is unauthenticated and sends no
        KALSHI-ACCESS-* headers (fine for public market data)."""
        client = KalshiClient(base_url="https://api.elections.kalshi.com/trade-api/v2")
        self.assertFalse(client.authed)
        headers = client._headers("GET", "/trade-api/v2/markets")
        self.assertNotIn("KALSHI-ACCESS-KEY", headers)
        self.assertNotIn("KALSHI-ACCESS-SIGNATURE", headers)
        self.assertEqual(headers["Accept"], "application/json")

    def test_sign_produces_base64(self):
        """_sign() should return a non-empty base64 string."""
        client = self._make_client()
        sig = client._sign("1700000000000", "GET", "/trade-api/v2/markets")
        self.assertGreater(len(sig), 0)
        self.assertGreater(len(base64.b64decode(sig)), 0)

    def test_sign_is_verifiable(self):
        """The signature must verify against the matching public key.

        The signed message is timestamp + method + path, exactly matching
        Kalshi's documented scheme.
        """
        client = self._make_client()
        timestamp = "1700000000000"
        method = "GET"
        path = "/trade-api/v2/markets"

        sig_bytes = base64.b64decode(client._sign(timestamp, method, path))
        message = f"{timestamp}{method}{path}".encode("utf-8")

        # Raises InvalidSignature if the signature does not verify.
        self.public_key.verify(
            sig_bytes,
            message,
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.DIGEST_LENGTH,
            ),
            hashes.SHA256(),
        )

    def test_headers_contain_required_fields(self):
        """_headers() should return the three required Kalshi auth headers."""
        client = self._make_client()
        headers = client._headers("GET", "/trade-api/v2/markets")

        self.assertEqual(headers["KALSHI-ACCESS-KEY"], "test-key-id")
        self.assertTrue(headers["KALSHI-ACCESS-TIMESTAMP"].isdigit())
        self.assertIn("KALSHI-ACCESS-SIGNATURE", headers)
        # The signature in the header must verify for the same message.
        ts = headers["KALSHI-ACCESS-TIMESTAMP"]
        sig_bytes = base64.b64decode(headers["KALSHI-ACCESS-SIGNATURE"])
        message = f"{ts}GET/trade-api/v2/markets".encode("utf-8")
        self.public_key.verify(
            sig_bytes,
            message,
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.DIGEST_LENGTH,
            ),
            hashes.SHA256(),
        )

    def test_headers_fresh_timestamp(self):
        """Each call to _headers should produce a non-decreasing timestamp."""
        import time

        client = self._make_client()
        h1 = client._headers("GET", "/trade-api/v2/markets")
        time.sleep(0.01)
        h2 = client._headers("GET", "/trade-api/v2/markets")
        self.assertGreaterEqual(
            int(h2["KALSHI-ACCESS-TIMESTAMP"]),
            int(h1["KALSHI-ACCESS-TIMESTAMP"]),
        )


if __name__ == "__main__":
    unittest.main()
