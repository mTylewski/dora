"""Password (argon2) + TOTP 2FA, session helpers, CSRF and a simple login throttle."""

from __future__ import annotations

import secrets
import time
from collections import defaultdict, deque

import pyotp
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import HTTPException, Request

_hasher = PasswordHasher()

MAX_ATTEMPTS = 5
WINDOW_SECONDS = 15 * 60
MIN_PASSWORD_LENGTH = 12


def hash_password(password: str) -> str:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"hasło musi mieć co najmniej {MIN_PASSWORD_LENGTH} znaków")
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def new_totp_secret() -> str:
    return pyotp.random_base32()


def totp_uri(secret: str, email: str, issuer: str = "Analiza roszczeń") -> str:
    return pyotp.TOTP(secret).provisioning_uri(name=email, issuer_name=issuer)


def verify_totp(secret: str, code: str) -> bool:
    return pyotp.TOTP(secret).verify(code.strip().replace(" ", ""), valid_window=1)


class Throttle:
    """At most MAX_ATTEMPTS failed logins per key within WINDOW_SECONDS (per process)."""

    def __init__(self) -> None:
        self._failures: dict[str, deque[float]] = defaultdict(deque)

    def blocked(self, key: str, now: float | None = None) -> bool:
        now = now or time.monotonic()
        q = self._failures[key]
        while q and now - q[0] > WINDOW_SECONDS:
            q.popleft()
        return len(q) >= MAX_ATTEMPTS

    def fail(self, key: str, now: float | None = None) -> None:
        self._failures[key].append(now or time.monotonic())

    def reset(self, key: str) -> None:
        self._failures.pop(key, None)


def csrf_token(request: Request) -> str:
    token = request.session.get("csrf")
    if not token:
        token = secrets.token_urlsafe(32)
        request.session["csrf"] = token
    return token


def check_csrf(request: Request, submitted: str | None) -> None:
    expected = request.session.get("csrf")
    if not expected or not submitted or not secrets.compare_digest(expected, submitted):
        raise HTTPException(status_code=403, detail="Nieprawidłowy token formularza. Odśwież stronę.")
