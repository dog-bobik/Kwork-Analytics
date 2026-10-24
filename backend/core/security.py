from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

from cryptography.fernet import Fernet, InvalidToken

from backend.core.config import settings
from backend.kwork_client import KworkError

PBKDF2_ITERATIONS = 600_000


def _fernet() -> Fernet:
    key = hashlib.sha256(settings.app_secret.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def encrypt_token(token: str) -> str:
    return _fernet().encrypt(token.encode()).decode()


def decrypt_token(token: str) -> str:
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken as error:
        raise KworkError("Не удалось расшифровать сохранённый токен Kwork") from error


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, encoded: str | None) -> bool:
    if not encoded:
        return False
    try:
        algorithm, raw_iterations, raw_salt, expected = encoded.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        actual = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), bytes.fromhex(raw_salt), int(raw_iterations)
        ).hex()
    except (TypeError, ValueError):
        return False
    return hmac.compare_digest(actual, expected)


def token_hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()
