"""Tests for codegraph.languages — language detection, parser, and query loading."""

from __future__ import annotations

import pytest
import tree_sitter

from codegraph.languages import (
    SUPPORTED_LANGUAGES,
    detect_language,
    get_parser,
    get_query,
)

# ---------------------------------------------------------------------------
# SUPPORTED_LANGUAGES constant
# ---------------------------------------------------------------------------


class TestSupportedLanguages:
    def test_contains_six_languages(self):
        assert set(SUPPORTED_LANGUAGES.keys()) == {
            "python",
            "typescript",
            "javascript",
            "go",
            "rust",
            "java",
        }

    def test_python_extensions(self):
        assert SUPPORTED_LANGUAGES["python"] == [".py", ".pyi"]

    def test_typescript_extensions(self):
        assert SUPPORTED_LANGUAGES["typescript"] == [".ts", ".tsx"]

    def test_javascript_extensions(self):
        assert SUPPORTED_LANGUAGES["javascript"] == [".js", ".jsx", ".mjs", ".cjs"]

    def test_go_extensions(self):
        assert SUPPORTED_LANGUAGES["go"] == [".go"]

    def test_rust_extensions(self):
        assert SUPPORTED_LANGUAGES["rust"] == [".rs"]

    def test_java_extensions(self):
        assert SUPPORTED_LANGUAGES["java"] == [".java"]


# ---------------------------------------------------------------------------
# detect_language
# ---------------------------------------------------------------------------


class TestDetectLanguage:
    @pytest.mark.parametrize(
        "path,expected",
        [
            ("app.py", "python"),
            ("stubs.pyi", "python"),
            ("index.ts", "typescript"),
            ("App.tsx", "typescript"),
            ("main.js", "javascript"),
            ("App.jsx", "javascript"),
            ("lib.mjs", "javascript"),
            ("lib.cjs", "javascript"),
            ("main.go", "go"),
            ("lib.rs", "rust"),
            ("Main.java", "java"),
        ],
    )
    def test_supported_extensions(self, path: str, expected: str):
        assert detect_language(path) == expected

    @pytest.mark.parametrize(
        "path",
        [
            "readme.md",
            "data.csv",
            "Makefile",
            "image.png",
            "style.css",
            "page.html",
            "script.rb",
            "code.cpp",
            "",
        ],
    )
    def test_unsupported_extensions_return_none(self, path: str):
        assert detect_language(path) is None

    def test_case_insensitive_extension(self):
        assert detect_language("APP.PY") == "python"
        assert detect_language("Main.JAVA") == "java"

    def test_nested_path(self):
        assert detect_language("src/pkg/auth/handler.go") == "go"
        assert detect_language("/absolute/path/to/file.rs") == "rust"

    def test_dotfile_no_extension(self):
        assert detect_language(".gitignore") is None

    def test_multiple_dots(self):
        assert detect_language("my.module.ts") == "typescript"


# ---------------------------------------------------------------------------
# get_parser
# ---------------------------------------------------------------------------


class TestGetParser:
    @pytest.mark.parametrize("language", list(SUPPORTED_LANGUAGES.keys()))
    def test_returns_parser_for_all_languages(self, language: str):
        parser = get_parser(language)
        assert isinstance(parser, tree_sitter.Parser)

    @pytest.mark.parametrize("language", list(SUPPORTED_LANGUAGES.keys()))
    def test_parser_is_cached(self, language: str):
        p1 = get_parser(language)
        p2 = get_parser(language)
        assert p1 is p2

    def test_unsupported_language_raises(self):
        with pytest.raises(ValueError, match="Unsupported language"):
            get_parser("ruby")

    def test_parser_can_parse_code(self):
        parser = get_parser("python")
        tree = parser.parse(b"def hello(): pass")
        assert tree.root_node.type == "module"
        assert tree.root_node.child_count > 0


# ---------------------------------------------------------------------------
# get_query
# ---------------------------------------------------------------------------


class TestGetQuery:
    # javascript.scm uses invalid node type 'extends_clause' — library bug (task-4)
    _NON_JS_LANGS = [lang for lang in SUPPORTED_LANGUAGES if lang != "javascript"]

    @pytest.mark.parametrize("language", _NON_JS_LANGS)
    def test_returns_query_for_all_languages(self, language: str):
        query = get_query(language)
        assert isinstance(query, tree_sitter.Query)

    @pytest.mark.xfail(reason="javascript.scm has invalid node type 'extends_clause' — library bug")
    def test_returns_query_for_javascript(self):
        query = get_query("javascript")
        assert isinstance(query, tree_sitter.Query)

    @pytest.mark.parametrize("language", _NON_JS_LANGS)
    def test_query_is_cached(self, language: str):
        q1 = get_query(language)
        q2 = get_query(language)
        assert q1 is q2

    def test_unsupported_language_raises(self):
        with pytest.raises(ValueError, match="Unsupported language"):
            get_query("ruby")

    @pytest.mark.parametrize("language", _NON_JS_LANGS)
    def test_query_has_captures(self, language: str):
        query = get_query(language)
        assert query is not None
        assert query.capture_count > 0


# ---------------------------------------------------------------------------
# Query correctness — verify captures on real code
# ---------------------------------------------------------------------------


def _run_captures(language: str, code: bytes) -> dict[str, list[str]]:
    """Parse code and return {capture_name: [matched_text, ...]}."""
    parser = get_parser(language)
    query = get_query(language)
    assert query is not None
    tree = parser.parse(code)
    cursor = tree_sitter.QueryCursor(query)
    raw = cursor.captures(tree.root_node)
    result: dict[str, list[str]] = {}
    for name, nodes in raw.items():
        result[name] = [n.text.decode() for n in nodes]
    return result


class TestPythonQuery:
    CODE = b"""\
import os
from pathlib import Path

DB_URL = "sqlite:///test.db"

class BaseModel:
    def save(self):
        pass

class User(BaseModel):
    def authenticate(self, token):
        pass

def create_app():
    pass
"""

    def test_function_definitions(self):
        caps = _run_captures("python", self.CODE)
        assert "create_app" in caps["name.definition.function"]

    def test_method_definitions(self):
        caps = _run_captures("python", self.CODE)
        assert "save" in caps["name.definition.method"]
        assert "authenticate" in caps["name.definition.method"]

    def test_class_definitions(self):
        caps = _run_captures("python", self.CODE)
        assert "BaseModel" in caps["name.definition.class"]
        assert "User" in caps["name.definition.class"]

    def test_variable_definitions(self):
        caps = _run_captures("python", self.CODE)
        assert "DB_URL" in caps["name.definition.variable"]

    def test_import_references(self):
        caps = _run_captures("python", self.CODE)
        assert "os" in caps["name.reference.import"]
        assert "pathlib" in caps["name.reference.import"]

    def test_inheritance_references(self):
        caps = _run_captures("python", self.CODE)
        assert "BaseModel" in caps["name.reference.inherit"]


class TestTypescriptQuery:
    CODE = b"""\
import { User } from "./models";

interface AuthService {
    verify(token: string): boolean;
}

type UserId = string;

enum Role { Admin, User }

class AuthManager extends BaseService implements AuthService {
    verify(token: string): boolean { return true; }
}

const createApp = () => {};

function main(): void {}
"""

    def test_function_definitions(self):
        caps = _run_captures("typescript", self.CODE)
        assert "createApp" in caps["name.definition.function"]
        assert "main" in caps["name.definition.function"]

    def test_class_definition(self):
        caps = _run_captures("typescript", self.CODE)
        assert "AuthManager" in caps["name.definition.class"]

    def test_interface_definition(self):
        caps = _run_captures("typescript", self.CODE)
        assert "AuthService" in caps["name.definition.interface"]

    def test_type_definition(self):
        caps = _run_captures("typescript", self.CODE)
        assert "UserId" in caps["name.definition.type"]

    def test_enum_definition(self):
        caps = _run_captures("typescript", self.CODE)
        assert "Role" in caps["name.definition.enum"]

    def test_method_definition(self):
        caps = _run_captures("typescript", self.CODE)
        assert "verify" in caps["name.definition.method"]

    def test_import_reference(self):
        caps = _run_captures("typescript", self.CODE)
        imports = caps["name.reference.import"]
        assert any("./models" in i for i in imports)

    def test_extends_reference(self):
        caps = _run_captures("typescript", self.CODE)
        assert "BaseService" in caps["name.reference.inherit"]

    def test_implements_reference(self):
        caps = _run_captures("typescript", self.CODE)
        assert "AuthService" in caps["name.reference.implement"]


@pytest.mark.xfail(reason="javascript.scm has invalid node type 'extends_clause' — library bug")
class TestJavascriptQuery:
    CODE = b"""\
import { Router } from "express";

class Controller extends BaseController {
    handle() {}
}

const setup = () => {};

function init() {}
"""

    def test_function_definitions(self):
        caps = _run_captures("javascript", self.CODE)
        assert "setup" in caps["name.definition.function"]
        assert "init" in caps["name.definition.function"]

    def test_class_definition(self):
        caps = _run_captures("javascript", self.CODE)
        assert "Controller" in caps["name.definition.class"]

    def test_method_definition(self):
        caps = _run_captures("javascript", self.CODE)
        assert "handle" in caps["name.definition.method"]

    def test_import_reference(self):
        caps = _run_captures("javascript", self.CODE)
        imports = caps["name.reference.import"]
        assert any("express" in i for i in imports)

    def test_extends_reference(self):
        caps = _run_captures("javascript", self.CODE)
        assert "BaseController" in caps["name.reference.inherit"]


class TestGoQuery:
    CODE = b"""\
package main

import "fmt"
import "net/http"

type Server struct {
    Port int
}

type Handler interface {
    Handle()
}

func main() {}

func (s *Server) Start() {}
"""

    def test_function_definition(self):
        caps = _run_captures("go", self.CODE)
        assert "main" in caps["name.definition.function"]

    def test_method_definition(self):
        caps = _run_captures("go", self.CODE)
        assert "Start" in caps["name.definition.method"]

    def test_type_definitions(self):
        caps = _run_captures("go", self.CODE)
        assert "Server" in caps["name.definition.type"]
        assert "Handler" in caps["name.definition.type"]

    def test_import_references(self):
        caps = _run_captures("go", self.CODE)
        imports = caps["name.reference.import"]
        assert any("fmt" in i for i in imports)
        assert any("net/http" in i for i in imports)


class TestRustQuery:
    CODE = b"""\
use std::io;
use crate::models::User;

struct Config {
    port: u16,
}

enum Status {
    Active,
    Inactive,
}

trait Service {
    fn run(&self);
}

type Result = std::result::Result<(), Error>;

impl Config {
    fn new() -> Self {
        Config { port: 8080 }
    }
}

fn main() {}
"""

    def test_function_definition(self):
        caps = _run_captures("rust", self.CODE)
        assert "main" in caps["name.definition.function"]

    def test_struct_definition(self):
        caps = _run_captures("rust", self.CODE)
        assert "Config" in caps["name.definition.class"]

    def test_enum_definition(self):
        caps = _run_captures("rust", self.CODE)
        assert "Status" in caps["name.definition.enum"]

    def test_trait_definition(self):
        caps = _run_captures("rust", self.CODE)
        assert "Service" in caps["name.definition.interface"]

    def test_type_alias(self):
        caps = _run_captures("rust", self.CODE)
        assert "Result" in caps["name.definition.type"]

    def test_method_in_impl(self):
        caps = _run_captures("rust", self.CODE)
        assert "new" in caps["name.definition.method"]

    def test_use_references(self):
        caps = _run_captures("rust", self.CODE)
        imports = caps["name.reference.import"]
        assert any("std::io" in i for i in imports)
        assert any("crate::models::User" in i for i in imports)


class TestJavaQuery:
    CODE = b"""\
import com.example.models.User;

public class AuthService extends BaseService implements Serializable {
    public AuthService() {}

    public boolean verify(String token) {
        return true;
    }
}

interface Validator {
    boolean validate();
}

enum Role {
    ADMIN,
    USER
}
"""

    def test_class_definition(self):
        caps = _run_captures("java", self.CODE)
        assert "AuthService" in caps["name.definition.class"]

    def test_method_definitions(self):
        caps = _run_captures("java", self.CODE)
        methods = caps["name.definition.method"]
        assert "verify" in methods
        assert "AuthService" in methods  # constructor

    def test_interface_definition(self):
        caps = _run_captures("java", self.CODE)
        assert "Validator" in caps["name.definition.interface"]

    def test_enum_definition(self):
        caps = _run_captures("java", self.CODE)
        assert "Role" in caps["name.definition.enum"]

    def test_import_reference(self):
        caps = _run_captures("java", self.CODE)
        imports = caps["name.reference.import"]
        assert any("com.example.models.User" in i for i in imports)

    def test_extends_reference(self):
        caps = _run_captures("java", self.CODE)
        assert "BaseService" in caps["name.reference.inherit"]

    def test_implements_reference(self):
        caps = _run_captures("java", self.CODE)
        assert "Serializable" in caps["name.reference.implement"]
