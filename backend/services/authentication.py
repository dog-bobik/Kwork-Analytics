from __future__ import annotations
from dataclasses import dataclass
from backend.core.security import encrypt_token, hash_password, verify_password
from backend.db import repositories
from backend.db.models import User
from backend.kwork_client import KworkClient, KworkError

@dataclass(slots=True)
class LoginResult:
    user: User
    connected_to_kwork: bool

async def authenticate(login: str, password: str, phone_last: str | None = None) -> LoginResult:
    """Authenticate locally; contact Kwork only for first connection/migration."""
    existing = await repositories.find_user_by_login(login)
    if existing and existing.password_hash:
        if not verify_password(password, existing.password_hash):
            raise KworkError("Неверный логин или пароль")
        return LoginResult(existing, connected_to_kwork=False)
    async with KworkClient(login, password, phone_last=phone_last) as client:
        actor = await client.get_actor()
        token = client.token
    if not token:
        raise KworkError("Kwork не вернул токен")
    user = await repositories.upsert_user(login, encrypt_token(token), hash_password(password), actor)
    return LoginResult(user, connected_to_kwork=True)
