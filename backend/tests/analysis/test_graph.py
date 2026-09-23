"""Whole-project analysis: dependency graph over the Python and TypeScript fixture projects."""

import pytest

from app.analysis.repository import RepositoryAnalysis, analyze_repository
from app.analysis.results import Confidence, RelationshipType
from tests.analysis.helpers import fixture_paths, fixture_root


def run(project: str) -> RepositoryAnalysis:
    return analyze_repository(fixture_root(project), fixture_paths(project), max_file_bytes=512_000)


class Graph:
    """Readable view of analysis rows: edges as (type, confidence, source, target)."""

    def __init__(self, analysis: RepositoryAnalysis) -> None:
        self.analysis = analysis
        self.paths = {row["id"]: row["path"] for row in analysis.files}
        self.symbols = {row["id"]: row["qualified_name"] for row in analysis.symbols}

    def edges(self, kind: RelationshipType) -> set[tuple[str, str, str]]:
        result = set()
        for row in self.analysis.relationships:
            if row["relationship_type"] is not kind:
                continue
            if kind is RelationshipType.IMPORTS:
                source, target = (
                    self.paths[row["source_file_id"]],
                    self.paths[row["target_file_id"]],
                )
            else:
                source = (
                    f"{self.paths[row['source_file_id']]}:{self.symbols[row['source_symbol_id']]}"
                )
                target = (
                    f"{self.paths[row['target_file_id']]}:{self.symbols[row['target_symbol_id']]}"
                )
            result.add((row["confidence"].value, source, target))
        return result

    def resolution(self, kind: RelationshipType, source: str, target: str) -> str:
        for row in self.analysis.relationships:
            if (
                row["relationship_type"] is kind
                and self.symbols.get(row["source_symbol_id"]) == source
                and self.symbols.get(row["target_symbol_id"]) == target
            ):
                return row["relationship_metadata"]["resolution"]
        raise AssertionError(f"no {kind} edge {source} -> {target}")


@pytest.fixture(scope="module")
def python_graph() -> Graph:
    return Graph(run("python_project"))


@pytest.fixture(scope="module")
def ts_graph() -> Graph:
    return Graph(run("ts_project"))


def test_python_file_imports_are_confirmed(python_graph: Graph) -> None:
    assert python_graph.edges(RelationshipType.IMPORTS) == {
        ("confirmed", "main.py", "shop/services.py"),
        ("confirmed", "main.py", "shop/__init__.py"),
        ("confirmed", "main.py", "shop/utils.py"),
        ("confirmed", "shop/api/routes.py", "shop/services.py"),
        ("confirmed", "shop/services.py", "shop/__init__.py"),
        ("confirmed", "shop/services.py", "shop/utils.py"),
        ("confirmed", "shop/services.py", "shop/models.py"),
        ("confirmed", "shop/utils.py", "shop/models.py"),
    }


def test_python_calls_are_inferred(python_graph: Graph) -> None:
    assert python_graph.edges(RelationshipType.CALLS) == {
        ("inferred", "main.py:main", "shop/services.py:create_product"),
        ("inferred", "main.py:main", "shop/utils.py:slugify"),
        ("inferred", "shop/api/routes.py:list_products", "shop/services.py:create_product"),
        ("inferred", "shop/services.py:create_product", "shop/models.py:Product"),
        ("inferred", "shop/services.py:create_product", "shop/utils.py:slugify"),
        (
            "inferred",
            "shop/services.py:ProductService.save",
            "shop/services.py:ProductService.check",
        ),
        ("inferred", "shop/services.py:ProductService.save", "shop/utils.py:slugify"),
        ("inferred", "shop/models.py:Product.discounted", "shop/models.py:BaseModel.validate"),
    }


@pytest.mark.parametrize(
    ("source", "target", "resolution"),
    [
        ("main", "create_product", "namespace"),  # shop.services.create_product(...)
        ("list_products", "create_product", "import"),  # from ..services import create_product
        ("create_product", "slugify", "import"),  # aliased: make_slug(...)
        ("ProductService.save", "ProductService.check", "self"),
        ("Product.discounted", "BaseModel.validate", "self_inherited"),
    ],
)
def test_python_call_resolution_strategies(
    python_graph: Graph, source: str, target: str, resolution: str
) -> None:
    assert python_graph.resolution(RelationshipType.CALLS, source, target) == resolution


def test_python_inheritance_and_unresolved_calls(python_graph: Graph) -> None:
    assert python_graph.edges(RelationshipType.INHERITS) == {
        ("inferred", "shop/models.py:Product", "shop/models.py:BaseModel")
    }
    # `service.save(product)` depends on a runtime value: no edge is guessed.
    assert not any(
        "list_products" in s and "save" in t
        for _, s, t in python_graph.edges(RelationshipType.CALLS)
    )


def test_python_import_rows(python_graph: Graph) -> None:
    rows = {
        (python_graph.paths[r["file_id"]], r["module"]): r for r in python_graph.analysis.imports
    }

    missing = rows[("shop/api/routes.py", "..missing_module")]
    assert (missing["resolution_status"], missing["resolved_file_id"]) == ("unresolved", None)
    requests_import = rows[("shop/api/routes.py", "requests")]
    assert requests_import["resolution_status"] == "external"
    assert requests_import["import_metadata"]["package"] == "requests"
    package_import = rows[("main.py", "shop")]
    assert package_import["import_metadata"]["name_targets"] == {"utils": "shop/utils.py"}


def test_ts_file_imports_through_aliases_and_reexports(ts_graph: Graph) -> None:
    assert ts_graph.edges(RelationshipType.IMPORTS) == {
        ("confirmed", "src/App.tsx", "src/index.ts"),
        ("confirmed", "src/App.tsx", "src/utils/format.js"),
        ("confirmed", "src/components/UserCard.tsx", "src/types.ts"),
        ("confirmed", "src/components/UserList.tsx", "src/lib/api.ts"),
        ("confirmed", "src/components/UserList.tsx", "src/types.ts"),
        ("confirmed", "src/components/UserList.tsx", "src/components/UserCard.tsx"),
        ("confirmed", "src/index.ts", "src/lib/api.ts"),
        ("confirmed", "src/index.ts", "src/components/UserList.tsx"),
        ("confirmed", "src/index.ts", "src/utils/format.js"),
        ("confirmed", "src/index.ts", "src/components/UserCard.tsx"),  # dynamic import()
        ("confirmed", "src/lib/api.ts", "src/types.ts"),
    }


def test_ts_calls_and_renders(ts_graph: Graph) -> None:
    assert ts_graph.edges(RelationshipType.CALLS) == {
        (
            "inferred",
            "src/App.tsx:App.onCreate",
            "src/lib/api.ts:createUser",
        ),  # via `export *` barrel
        ("inferred", "src/App.tsx:App.onCreate", "src/lib/api.ts:getUsers"),
        ("inferred", "src/App.tsx:App", "src/utils/format.js:formatName"),  # namespace import
        ("inferred", "src/components/UserList.tsx:UserList", "src/lib/api.ts:getUsers"),
        ("inferred", "src/lib/api.ts:ApiClient.remove", "src/lib/api.ts:ApiClient.log"),
        ("inferred", "src/utils/format.js:initials", "src/utils/format.js:formatName"),
    }
    assert ts_graph.edges(RelationshipType.RENDERS) == {
        (
            "inferred",
            "src/App.tsx:App",
            "src/components/UserList.tsx:UserList",
        ),  # `export { X as default }`
        (
            "inferred",
            "src/components/UserList.tsx:UserList",
            "src/components/UserCard.tsx:UserCard",
        ),
        (
            "inferred",
            "src/components/UserList.tsx:LegacyList.render",
            "src/components/UserList.tsx:UserList",
        ),
    }


def test_confidence_rule_holds_everywhere(python_graph: Graph, ts_graph: Graph) -> None:
    for graph in (python_graph, ts_graph):
        for row in graph.analysis.relationships:
            if row["relationship_type"] is RelationshipType.IMPORTS:
                assert row["source_symbol_id"] is None and row["target_symbol_id"] is None
            else:
                assert row["confidence"] is Confidence.INFERRED
                assert row["source_symbol_id"] and row["target_symbol_id"]
                assert row["relationship_metadata"]["resolution"]


def test_summary(ts_graph: Graph) -> None:
    summary = ts_graph.analysis.summary

    assert summary["files_analyzed"] == 7
    assert summary["files_by_language"] == {"tsx": 3, "typescript": 3, "javascript": 1}
    assert summary["parse_status"] == {"parsed": 7}
    assert summary["symbols_by_kind"]["component"] == 4
    assert summary["relationships"]["imports"] == {"confirmed": 11, "inferred": 0}
    assert summary["most_imported"][0] == {"path": "src/types.ts", "importers": 3}
    assert {item["name"] for item in summary["external_packages"]} == {"react", "axios", "path"}
    assert summary["api_calls"] == 3


def test_rows_are_consistent(ts_graph: Graph) -> None:
    analysis = ts_graph.analysis
    file_ids = {row["id"] for row in analysis.files}
    symbol_ids = [row["id"] for row in analysis.symbols]
    seen: set = set()
    for row in analysis.symbols:
        assert row["file_id"] in file_ids
        assert (
            row["parent_symbol_id"] is None or row["parent_symbol_id"] in seen
        )  # parents inserted first
        seen.add(row["id"])
    assert len(symbol_ids) == len(set(symbol_ids))
    for row in analysis.relationships:
        assert row["source_file_id"] in file_ids and row["target_file_id"] in file_ids


def test_skips_large_binary_and_minified_files(tmp_path) -> None:  # type: ignore[no-untyped-def]
    (tmp_path / "ok.py").write_text("def ok():\n    pass\n")
    (tmp_path / "big.py").write_text("x = 1\n" * 1000)
    (tmp_path / "bin.py").write_bytes(b"\x00\x01binary")
    (tmp_path / "vendor.min.js").write_text("function a(){}")
    (tmp_path / "notes.txt").write_text("not code")

    analysis = analyze_repository(
        tmp_path, ["ok.py", "big.py", "bin.py", "vendor.min.js", "notes.txt"], max_file_bytes=1000
    )

    assert [row["path"] for row in analysis.files] == ["ok.py"]
    assert analysis.summary["skipped_files"] == 2  # big.py (size) and bin.py (binary)


def test_parser_crash_marks_file_failed(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from app.analysis.python import PythonAnalyzer

    def explode(self, source, path):  # type: ignore[no-untyped-def]
        raise RuntimeError("boom")

    monkeypatch.setattr(PythonAnalyzer, "analyze", explode)
    (tmp_path / "a.py").write_text("def a(): pass\n")

    analysis = analyze_repository(tmp_path, ["a.py"], max_file_bytes=1000)

    assert analysis.files[0]["parse_status"].value == "failed"
    assert analysis.files[0]["file_metadata"]["error"]


def test_imports_of_known_non_text_files_resolve(tmp_path) -> None:  # type: ignore[no-untyped-def]
    (tmp_path / "App.jsx").write_text(
        'import logo from "./logo.png";\nimport missing from "./nope.png";\n'
    )
    (tmp_path / "logo.png").write_bytes(b"\x89PNG\x00")

    without = analyze_repository(tmp_path, ["App.jsx"], max_file_bytes=1000)
    with_known = analyze_repository(
        tmp_path, ["App.jsx"], max_file_bytes=1000, known_paths=["logo.png"]
    )

    assert [row["resolution_status"] for row in without.imports] == ["unresolved", "unresolved"]
    assert [(row["resolution_status"], row["resolved_path"]) for row in with_known.imports] == [
        ("resolved", "logo.png"),
        ("unresolved", None),
    ]
    assert with_known.relationships == []  # edges only connect parsed source files
