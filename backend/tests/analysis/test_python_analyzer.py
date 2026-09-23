"""Python analyzer: symbols, parameters, decorators, docstrings, imports and line ranges."""

import pytest

from app.analysis.python import PythonAnalyzer
from app.analysis.results import FileAnalysis, ParseStatus, SymbolKind
from tests.analysis.helpers import line_of, read_fixture

PROJECT = "python_project"


def analyze(path: str) -> tuple[FileAnalysis, bytes]:
    source = read_fixture(PROJECT, path)
    return PythonAnalyzer().analyze(source, path), source


def symbol(result: FileAnalysis, qualified_name: str):  # type: ignore[no-untyped-def]
    return next(item for item in result.symbols if item.qualified_name == qualified_name)


def test_module_docstring_and_classes() -> None:
    result, _ = analyze("shop/models.py")

    assert result.docstring == "Domain models."
    assert result.status is ParseStatus.PARSED
    assert [(s.qualified_name, s.kind) for s in result.symbols] == [
        ("BaseModel", SymbolKind.CLASS),
        ("BaseModel.validate", SymbolKind.METHOD),
        ("Product", SymbolKind.CLASS),
        ("Product.label", SymbolKind.METHOD),
        ("Product.free", SymbolKind.METHOD),
        ("Product.discounted", SymbolKind.METHOD),
    ]
    product = symbol(result, "Product")
    assert product.docstring == "A product for sale."
    assert product.decorators == ["dataclass(frozen=True)"]
    assert product.metadata["bases"] == ["BaseModel"]
    assert product.signature == "class Product(BaseModel)"


def test_line_ranges_include_decorators_and_bodies() -> None:
    result, source = analyze("shop/models.py")

    product = symbol(result, "Product")
    assert product.start_line == line_of(source, "@dataclass(frozen=True)")
    assert product.metadata["definition_line"] == line_of(source, "class Product(BaseModel):")
    assert product.end_line == line_of(source, "return round(self.price")

    label = symbol(result, "Product.label")
    assert label.start_line == line_of(source, "@property")
    assert label.end_line == line_of(source, 'return f"{self.name} ({self.price})"')

    base = symbol(result, "BaseModel")
    assert (base.start_line, base.end_line) == (
        line_of(source, "class BaseModel:"),
        line_of(source, "return True"),
    )


def test_parent_symbols() -> None:
    result, _ = analyze("shop/models.py")

    product = symbol(result, "Product")
    for method in ("Product.label", "Product.free", "Product.discounted"):
        assert symbol(result, method).parent_key == product.key
    assert product.parent_key is None
    assert all(
        s.parent_key is None or s.parent_key < s.key for s in result.symbols
    )  # parents first


def test_method_details() -> None:
    result, _ = analyze("shop/models.py")

    label = symbol(result, "Product.label")
    assert label.metadata["method_type"] == "property"
    assert label.return_type == "str"
    assert label.metadata["returns_value"] is True

    free = symbol(result, "Product.free")
    assert free.metadata["method_type"] == "class"
    assert free.return_type == '"Product"'

    discounted = symbol(result, "Product.discounted")
    assert (
        discounted.signature
        == "def discounted(self, percent: float, *, round_to: int = 2) -> float"
    )
    assert [p.to_dict() for p in discounted.parameters] == [
        {"name": "self", "kind": "positional"},
        {"name": "percent", "type": "float", "kind": "positional"},
        {"name": "round_to", "type": "int", "default": "2", "kind": "keyword_only"},
    ]
    assert discounted.metadata["comment"] == "Apply a percentage discount."
    assert discounted.metadata["calls"] == ["self.validate", "round"]


def test_functions_parameters_and_async() -> None:
    result, source = analyze("shop/utils.py")

    slugify = symbol(result, "slugify")
    assert slugify.kind is SymbolKind.FUNCTION
    assert slugify.docstring == "Turn text into a URL slug."
    assert slugify.return_type == "str"
    assert (slugify.start_line, slugify.end_line) == (
        line_of(source, "def slugify"),
        line_of(source, "return re.sub"),
    )

    fetch = symbol(result, "fetch_catalog")
    assert fetch.is_async is True
    assert fetch.metadata["is_generator"] is True
    assert [(p.name, p.kind, p.default) for p in fetch.parameters] == [
        ("url", "positional", None),
        ("args", "var_positional", None),
        ("timeout", "keyword_only", "10"),
        ("options", "var_keyword", None),
    ]


def test_dunder_all_controls_exports() -> None:
    result, source = analyze("shop/utils.py")

    assert {s.name: s.is_exported for s in result.symbols} == {
        "slugify": True,
        "fetch_catalog": True,
        "_private_helper": False,
    }
    assert [(e.name, e.kind, e.line) for e in result.exports] == [
        ("slugify", "all", line_of(source, "__all__")),
        ("fetch_catalog", "all", line_of(source, "__all__")),
    ]


def test_implicit_exports_without_dunder_all() -> None:
    result, _ = analyze("shop/services.py")

    assert {e.name for e in result.exports} == {"create_product", "ProductService"}
    assert all(e.kind == "implicit" for e in result.exports)


def test_imports() -> None:
    result, source = analyze("shop/services.py")

    imports = [
        (i.module, i.kind, i.level, [n.to_dict() for n in i.names], i.start_line)
        for i in result.imports
    ]
    assert imports == [
        ("json", "import", 0, [{"name": "json"}], line_of(source, "import json")),
        (".", "from", 1, [{"name": "utils"}], line_of(source, "from . import utils")),
        (".models", "from", 1, [{"name": "Product"}], line_of(source, "from .models import")),
        (
            "shop.utils",
            "from",
            0,
            [{"name": "slugify", "alias": "make_slug"}],
            line_of(source, "make_slug"),
        ),
    ]


def test_conditional_and_type_checking_imports() -> None:
    result, _ = analyze("shop/utils.py")

    models_import = next(i for i in result.imports if i.module == "shop.models")
    assert models_import.is_type_only is True
    assert models_import.metadata["conditional"] is True
    assert next(i for i in result.imports if i.module == "re").is_type_only is False


def test_nested_functions_and_decorated_functions() -> None:
    result, source = analyze("shop/api/routes.py")

    route = symbol(result, "route")
    decorator = symbol(result, "route.decorator")
    assert decorator.kind is SymbolKind.FUNCTION
    assert decorator.parent_key == route.key

    list_products = symbol(result, "list_products")
    assert list_products.decorators == ['route("/products")']
    assert list_products.start_line == line_of(source, '@route("/products")')
    assert list_products.parameters[0].type == "ProductService"
    assert list_products.metadata["calls"] == ["create_product", "service.save"]


def test_calls_are_attributed_to_the_enclosing_symbol() -> None:
    result, _ = analyze("main.py")

    keys = {s.key: s.qualified_name for s in result.symbols}
    calls = [(c.callee, keys.get(c.caller_key)) for c in result.calls]
    assert ("shop.services.create_product", "main") in calls
    assert ("utils.slugify", "main") in calls
    assert ("main", None) in calls  # the module-level `main()` call


def test_syntax_errors_are_tolerated() -> None:
    source = (
        b"def ok():\n    return 1\n\n"
        b"def broken(:\n    pass\n\n"
        b"class Still:\n    def fine(self): pass\n"
    )

    result = PythonAnalyzer().analyze(source, "broken.py")

    assert result.status is ParseStatus.PARTIAL
    assert result.syntax_error_count > 0
    assert "ok" in {s.name for s in result.symbols}
    assert "Still.fine" in {s.qualified_name for s in result.symbols}


@pytest.mark.parametrize("source", [b"", b"# only a comment\n", b"\n\n"])
def test_empty_files(source: bytes) -> None:
    result = PythonAnalyzer().analyze(source, "empty.py")

    assert result.symbols == [] and result.imports == [] and result.status is ParseStatus.PARSED
