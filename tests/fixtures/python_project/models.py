"""Data models for the application."""


class User:
    """Represents a user in the system."""

    def __init__(self, name: str, email: str) -> None:
        self.name = name
        self.email = email

    def validate(self) -> bool:
        return bool(self.name and self.email)


class Admin(User):
    def promote(self, user: User) -> None:
        pass
