"""Tests for authentication module."""

from ..auth import authenticate, authorize


def test_authenticate():
    user = authenticate("valid-token")
    assert user.name == "authenticated"


def test_authorize():
    from ..models import User

    user = User(name="test", email="test@example.com")
    assert authorize(user, "read") is True
