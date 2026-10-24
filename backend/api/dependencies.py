from fastapi import Cookie, HTTPException
from backend.core.security import token_hash
from backend.db import repositories
from backend.db.models import User

async def current_user(kwork_pulse_session: str | None = Cookie(default=None)) -> User:
    if not kwork_pulse_session:
        raise HTTPException(status_code=401, detail="Требуется вход")
    user = await repositories.get_user_by_session(token_hash(kwork_pulse_session))
    if user is None:
        raise HTTPException(status_code=401, detail="Сессия истекла")
    return user
