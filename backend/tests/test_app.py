import unittest

from backend.app import decrypt_token, encrypt_token, summarize
from backend.core.security import hash_password, verify_password
from backend.services.analytics import happened_today, snapshot_number


class FastApiBackendTests(unittest.TestCase):
    def test_kwork_token_is_encrypted_at_rest(self) -> None:
        encrypted = encrypt_token("secret-token")
        self.assertNotIn("secret-token", encrypted)
        self.assertEqual(decrypt_token(encrypted), "secret-token")

    def test_offer_summary_uses_cached_payloads(self) -> None:
        offers = [
            {"is_read": True, "is_actual": True, "market": {"buyer_order_count": 2}},
            {"is_read": False, "is_actual": False, "market": {"buyer_order_count": 0}},
        ]
        result = summarize(offers)
        self.assertEqual(result["total"], 2)
        self.assertEqual(result["read"], 1)
        self.assertEqual(result["withOrders"], 1)
        self.assertEqual(result["buyerOrders"], 2)

    def test_local_password_is_hashed_and_verifiable(self) -> None:
        encoded = hash_password("correct horse battery staple")
        self.assertNotIn("correct horse battery staple", encoded)
        self.assertTrue(verify_password("correct horse battery staple", encoded))
        self.assertFalse(verify_password("wrong", encoded))

    def test_snapshot_number_prefers_activity_metrics(self) -> None:
        payload = {"orders": 2, "activity": {"orders": "7", "earned": 1250.0}}
        self.assertEqual(snapshot_number(payload, "orders", "sales"), 7)
        self.assertEqual(snapshot_number(payload, "earned"), 1250)

    def test_today_parser_rejects_unknown_dates(self) -> None:
        self.assertFalse(happened_today("not-a-date"))


if __name__ == "__main__":
    unittest.main()
