import unittest
from unittest.mock import AsyncMock

from backend.kwork_client import KworkClient


class ClientValidationTests(unittest.TestCase):
    def test_rejects_empty_credentials(self) -> None:
        with self.assertRaises(ValueError):
            KworkClient("", "password")
        with self.assertRaises(ValueError):
            KworkClient("login", "")

    def test_rejects_invalid_timeout(self) -> None:
        with self.assertRaises(ValueError):
            KworkClient("login", "password", timeout_seconds=0)

    def test_accepts_existing_session_token_without_credentials(self) -> None:
        client = KworkClient(token="session-token")
        self.assertEqual(client.token, "session-token")

    def test_parses_public_buyer_order_count(self) -> None:
        html = '<script>window.stateData={"wantData":{"wantGetSumOrderCount":2,"priceLimit":"10000.00","status":"active"}};window.next=1</script>'
        self.assertEqual(
            KworkClient._parse_project_state(html),
            {"buyer_order_count": 2, "project_budget": "10000.00", "project_status": "active"},
        )

    def test_rejects_page_without_project_state(self) -> None:
        with self.assertRaises(Exception):
            KworkClient._parse_project_state("<html></html>")

    def test_extracts_nested_kwork_response(self) -> None:
        response = {"data": {"kworks": [{"id": 7, "activity": {"views": 12}}]}}
        self.assertEqual(KworkClient._kworks_from_response(response), response["data"]["kworks"])


class ClientSecurityTests(unittest.IsolatedAsyncioTestCase):
    async def test_rejects_absolute_url_before_network_request(self) -> None:
        client = KworkClient("login", "password")
        with self.assertRaises(ValueError):
            await client._request("https://example.com/steal")
        self.assertIsNone(client._session)

    async def test_collects_all_offer_pages(self) -> None:
        client = KworkClient("login", "password")
        client.get_offers_page = AsyncMock(  # type: ignore[method-assign]
            side_effect=[
                {"response": [{"id": 1}], "paging": {"pages": 2}},
                {"response": [{"id": 2}], "paging": {"pages": 2}},
            ]
        )
        self.assertEqual(await client.get_all_offers(), [{"id": 1}, {"id": 2}])

    async def test_collects_all_kwork_pages(self) -> None:
        client = KworkClient(token="session-token")
        client.get_actor = AsyncMock(return_value={"id": 42})  # type: ignore[method-assign]
        client.get_kworks_page = AsyncMock(  # type: ignore[method-assign]
            side_effect=[
                {"response": {"items": [{"id": 1}]}, "paging": {"pages": 2}},
                {"response": {"items": [{"id": 2}]}, "paging": {"pages": 2}},
            ]
        )
        self.assertEqual(await client.get_all_kworks(), [{"id": 1}, {"id": 2}])

    async def test_uses_actor_kworks_when_endpoint_is_empty(self) -> None:
        client = KworkClient(token="session-token")
        client.get_actor = AsyncMock(return_value={"id": 42, "kworks": [{"id": 9}]})  # type: ignore[method-assign]
        client.get_kworks_page = AsyncMock(return_value={"response": [], "paging": {"pages": "1"}})  # type: ignore[method-assign]
        self.assertEqual(await client.get_all_kworks(), [{"id": 9}])

    async def test_collects_all_review_pages(self) -> None:
        client = KworkClient(token="session-token")
        client.get_user_reviews_page = AsyncMock(  # type: ignore[method-assign]
            side_effect=[
                {"response": [{"id": 1}], "paging": {"pages": 2}},
                {"response": [{"id": 2}], "paging": {"pages": 2}},
            ]
        )
        self.assertEqual(await client.get_all_user_reviews(42), [{"id": 1}, {"id": 2}])


if __name__ == "__main__":
    unittest.main()
