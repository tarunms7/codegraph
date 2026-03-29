"""Authentication and authorization utilities."""

from .models import User


def authenticate(token: str) -> User:
    return User(name="authenticated", email="auth@example.com")


def authorize(user: User, permission: str) -> bool:
    return permission in ("read", "write")


class AuthHandler:
    def login(self, username: str, password: str) -> str:
        return "token-" + username

    def logout(self, token: str) -> None:
        pass
