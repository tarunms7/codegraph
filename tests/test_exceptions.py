"""Tests for codegraph.exceptions."""

from __future__ import annotations

import pytest

from codegraph.exceptions import CacheError, CodeGraphError, ParseError


class TestCodeGraphError:
    def test_is_exception(self):
        assert issubclass(CodeGraphError, Exception)

    def test_message(self):
        err = CodeGraphError("something went wrong")
        assert str(err) == "something went wrong"

    def test_raise_and_catch(self):
        with pytest.raises(CodeGraphError, match="boom"):
            raise CodeGraphError("boom")


class TestParseError:
    def test_inherits_codegraph_error(self):
        assert issubclass(ParseError, CodeGraphError)

    def test_catchable_as_base(self):
        with pytest.raises(CodeGraphError):
            raise ParseError("bad file")

    def test_message(self):
        err = ParseError("cannot parse foo.py")
        assert "cannot parse foo.py" in str(err)


class TestCacheError:
    def test_inherits_codegraph_error(self):
        assert issubclass(CacheError, CodeGraphError)

    def test_catchable_as_base(self):
        with pytest.raises(CodeGraphError):
            raise CacheError("db locked")

    def test_message(self):
        err = CacheError("db locked")
        assert "db locked" in str(err)
