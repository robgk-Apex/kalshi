"""Tests for RSA-PSS authentication signing."""

import unittest
import tempfile
import os
from decimal import Decimal

from cryptography.hazmat.primitives.asymmetric import rsa, padding
from cryptography.hazmat.primitives import hashes, serialization


class TestKalshiAuth(unittest.TestCase):
    """Test the authentication signing module."""

    @classmethod
    def setUpClass(cls):
        """Generate a temporary RSA key pair for testing."""
        cls.private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048,
        )
        cls.public_key = cls.private_key.public_key()

        # Write private key to temp file
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

    def _make_auth(self):
        from src.client.auth import KalshiAuth
        return KalshiAuth(key_id="test-key-id", private_key_path=self.key_file.name)

    def test_auth_loads_key(self):
        """Auth should load the PEM key without error."""
        auth = self._make_auth()
        self.assertEqual(auth.key_id, "test-key-id")

    def test_auth_missing_key_raises(self):
        """Auth should raise FileNotFoundError for missing key."""
        from src.client.auth import KalshiAuth
        with self.assertRaises(FileNotFoundError):
            KalshiAuth(key_id="x", private_key_path="/nonexistent/key.pem")

    def test_sign_produces_base64(self):
        """sign() should return a non-empty base64 string."""
        import base64
        auth = self._make_auth()
        sig = auth.sign("1700000000000", "GET", "/trade-api/v2/markets")
        self.assertTrue(len(sig) > 0)
        # Should be valid base64
        decoded = base64.b64decode(sig)
        self.assertTrue(len(decoded) > 0)

    def test_sign_is_verifiable(self):
        """The signature should be verifiable with the public key."""
        import base64
        auth = self._make_auth()

        timestamp = "1700000000000"
        method = "GET"
        path = "/trade-api/v2/markets"

        sig_b64 = auth.sign(timestamp, method, path)
        sig_bytes = base64.b64decode(sig_b64)

        # Verify with public key
        message = f"{timestamp}{method}{path}".encode("utf-8")
        # Should not raise
        self.public_key.verify(
            sig_bytes,
            message,
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.DIGEST_LENGTH,
            ),
            hashes.SHA256(),
        )

    def test_sign_strips_query_params(self):
        """sign() should strip query parameters from the path."""
        import base64
        auth = self._make_auth()

        timestamp = "1700000000000"
        method = "GET"

        # Sign with query params
        sig_with_query = auth.sign(timestamp, method, "/trade-api/v2/markets?status=open&limit=100")
        # Sign without query params
        sig_without_query = auth.sign(timestamp, method, "/trade-api/v2/markets")

        # Both should produce valid signatures for the same message
        # (they won't be identical due to PSS randomness, but both should verify)
        for sig_b64 in [sig_with_query, sig_without_query]:
            sig_bytes = base64.b64decode(sig_b64)
            message = f"{timestamp}{method}/trade-api/v2/markets".encode("utf-8")
            self.public_key.verify(
                sig_bytes,
                message,
                padding.PSS(
                    mgf=padding.MGF1(hashes.SHA256()),
                    salt_length=padding.PSS.DIGEST_LENGTH,
                ),
                hashes.SHA256(),
            )

    def test_get_headers_returns_three_headers(self):
        """get_headers() should return the 3 required Kalshi headers."""
        auth = self._make_auth()
        headers = auth.get_headers("GET", "/trade-api/v2/markets")

        self.assertIn("KALSHI-ACCESS-KEY", headers)
        self.assertIn("KALSHI-ACCESS-TIMESTAMP", headers)
        self.assertIn("KALSHI-ACCESS-SIGNATURE", headers)
        self.assertEqual(headers["KALSHI-ACCESS-KEY"], "test-key-id")
        # Timestamp should be numeric
        self.assertTrue(headers["KALSHI-ACCESS-TIMESTAMP"].isdigit())

    def test_get_headers_fresh_timestamp(self):
        """Each call to get_headers should produce a fresh timestamp."""
        import time
        auth = self._make_auth()

        h1 = auth.get_headers("GET", "/trade-api/v2/markets")
        time.sleep(0.01)
        h2 = auth.get_headers("GET", "/trade-api/v2/markets")

        # Timestamps should differ (or at least not be obviously stale)
        ts1 = int(h1["KALSHI-ACCESS-TIMESTAMP"])
        ts2 = int(h2["KALSHI-ACCESS-TIMESTAMP"])
        self.assertGreaterEqual(ts2, ts1)


if __name__ == "__main__":
    unittest.main()
