"""Utility functions."""

import hashlib
import secrets
import string

MAX_TOKEN_LENGTH = 256


def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


def generate_token(length: int = 32) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))
