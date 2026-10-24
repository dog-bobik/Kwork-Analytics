import unittest
from unittest.mock import AsyncMock, patch

from backend.core.security import hash_password
from backend.db.models import User
from backend.services.authentication import authenticate


class LocalAuthenticationTests(unittest.IsolatedAsyncioTestCase):
    async def test_existing_account_is_verified_without_kwork_request(self) -> None:
        user = User(
            id=1,
            kwork_user_id="42",
            login="owner",
            username="owner",
            password_hash=hash_password("secret"),
            token_encrypted="encrypted",
            profile={"username": "owner"},
        )
        with (
            patch("backend.services.authentication.repositories.find_user_by_login", new=AsyncMock(return_value=user)),
            patch("backend.services.authentication.KworkClient") as client,
        ):
            result = await authenticate("owner", "secret")
        self.assertIs(result.user, user)
        self.assertFalse(result.connected_to_kwork)
        client.assert_not_called()

    async def test_wrong_local_password_does_not_fall_back_to_kwork(self) -> None:
        user = User(
            id=1,
            kwork_user_id="42",
            login="owner",
            username="owner",
            password_hash=hash_password("secret"),
            token_encrypted="encrypted",
            profile={},
        )
        with (
            patch("backend.services.authentication.repositories.find_user_by_login", new=AsyncMock(return_value=user)),
            patch("backend.services.authentication.KworkClient") as client,
        ):
            with self.assertRaises(Exception):
                await authenticate("owner", "wrong")
        client.assert_not_called()


class RemovedRoutesTests(unittest.TestCase):
    def test_portfolio_and_foreign_profile_routes_are_absent(self) -> None:
        from backend.app import app

        paths = {route.path for route in app.routes}
        self.assertNotIn("/api/portfolio", paths)
        self.assertNotIn("/api/profiles/{username}", paths)
        self.assertIn("/api/profile/me", paths)


if __name__ == "__main__":
    unittest.main()
