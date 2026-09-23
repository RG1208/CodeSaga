"""HTTP behaviour of the code-analysis endpoints, using both fixture projects in one repository."""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import CodeFile, CodeRelationship, CodeSymbol
from tests.analysis.helpers import fixture_files, line_of, read_fixture
from tests.fakes import FakeGitClient


@pytest.fixture
def repo_id(client: TestClient, fake_git: FakeGitClient) -> str:
    fake_git.files = {
        **{f"web/{path}": content for path, content in fixture_files("ts_project").items()},
        **{f"py/{path}": content for path, content in fixture_files("python_project").items()},
        "README.md": b"# Mixed repository\n",
        "node_modules/hidden/index.js": b"module.exports = 1;\n",  # on disk, but never indexed
    }
    created = client.post(
        "/api/v1/repositories", json={"url": "https://github.com/demo/mixed"}
    ).json()
    job = client.post(f"/api/v1/repositories/{created['id']}/index").json()
    assert job["status"] == "succeeded", job
    return created["id"]


def url(repo_id: str, suffix: str) -> str:
    return f"/api/v1/repositories/{repo_id}{suffix}"


# --- files --------------------------------------------------------------------------


def test_list_files_marks_analyzed_files(client: TestClient, repo_id: str) -> None:
    body = client.get(url(repo_id, "/files")).json()

    files = {item["path"]: item for item in body["items"]}
    assert body["total"] == 16  # 8 TS project files (incl. tsconfig.json) + 7 Python + README
    assert "node_modules/hidden/index.js" not in files
    assert files["README.md"]["analyzed"] is False
    assert files["README.md"]["parser"] is None
    user_list = files["web/src/components/UserList.tsx"]
    assert (user_list["analyzed"], user_list["parser"], user_list["parse_status"]) == (
        True,
        "tsx",
        "parsed",
    )
    assert user_list["symbol_count"] == 3
    assert list(files) == sorted(files)  # ordered by path


def test_list_files_filters(client: TestClient, repo_id: str) -> None:
    analyzed = client.get(url(repo_id, "/files"), params={"analyzed": True}).json()
    prefixed = client.get(url(repo_id, "/files"), params={"path_prefix": "py/shop/api/"}).json()

    assert analyzed["total"] == 14
    assert all(item["analyzed"] for item in analyzed["items"])
    assert [item["path"] for item in prefixed["items"]] == [
        "py/shop/api/__init__.py",
        "py/shop/api/routes.py",
    ]


def test_file_content(client: TestClient, repo_id: str) -> None:
    response = client.get(url(repo_id, "/files/content"), params={"path": "py/shop/models.py"})

    assert response.status_code == 200
    body = response.json()
    assert body["content"] == read_fixture("python_project", "shop/models.py").decode()
    assert body["line_count"] == body["content"].count("\n")


@pytest.mark.parametrize(
    ("path", "status", "code"),
    [
        ("../../../etc/passwd", 422, "invalid_path"),
        ("/etc/passwd", 422, "invalid_path"),
        ("py/../README.md", 422, "invalid_path"),
        ("py\\shop\\models.py", 422, "invalid_path"),
        ("web/src/missing.ts", 404, "file_not_found"),
        ("node_modules/hidden/index.js", 404, "file_not_found"),  # exists on disk, not indexed
    ],
)
def test_file_content_rejects_unsafe_or_unknown_paths(
    client: TestClient, repo_id: str, path: str, status: int, code: str
) -> None:
    response = client.get(url(repo_id, "/files/content"), params={"path": path})

    assert response.status_code == status
    assert response.json()["error"]["code"] == code


def test_file_content_requires_an_indexed_repository(client: TestClient) -> None:
    created = client.post(
        "/api/v1/repositories", json={"url": "https://github.com/demo/new"}
    ).json()

    response = client.get(url(created["id"], "/files/content"), params={"path": "README.md"})

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "repository_not_indexed"


def test_file_detail(client: TestClient, repo_id: str) -> None:
    body = client.get(
        url(repo_id, "/files/detail"), params={"path": "web/src/components/UserList.tsx"}
    ).json()
    source = read_fixture("ts_project", "src/components/UserList.tsx")

    assert (body["language"], body["parse_status"], body["symbol_count"]) == ("tsx", "parsed", 3)
    symbols = {symbol["qualified_name"]: symbol for symbol in body["symbols"]}
    user_list = symbols["UserList"]
    assert user_list["kind"] == "component"
    assert user_list["start_line"] == line_of(source, "export function UserList")
    assert user_list["metadata"]["hooks"] == ["useState", "useEffect"]
    assert symbols["LegacyList.render"]["parent_symbol_id"] == symbols["LegacyList"]["id"]

    imports = {item["module"]: item for item in body["imports"]}
    assert imports["@/lib/api"]["resolved_path"] == "web/src/lib/api.ts"
    assert imports["@/lib/api"]["metadata"]["confidence"] == "confirmed"
    assert imports["react"]["resolution_status"] == "external"

    assert [(d["path"], d["confidence"]) for d in body["depends_on"]] == [
        ("web/src/components/UserCard.tsx", "confirmed"),
        ("web/src/lib/api.ts", "confirmed"),
        ("web/src/types.ts", "confirmed"),
    ]
    assert [d["path"] for d in body["imported_by"]] == ["web/src/index.ts"]
    assert {e["name"] for e in body["metadata"]["exports"]} == {"UserList", "LegacyList", "default"}


def test_file_detail_includes_api_calls_and_docstring(client: TestClient, repo_id: str) -> None:
    api = client.get(url(repo_id, "/files/detail"), params={"path": "web/src/lib/api.ts"}).json()
    models = client.get(url(repo_id, "/files/detail"), params={"path": "py/shop/models.py"}).json()

    assert [(c["method"], c["url"]) for c in api["metadata"]["api_calls"]] == [
        ("GET", "/api/users"),
        ("POST", "{BASE}/users/{name}"),
        ("DELETE", "/api/users/{id}"),
    ]
    assert models["metadata"]["docstring"] == "Domain models."


def test_file_detail_for_unparsed_file(client: TestClient, repo_id: str) -> None:
    response = client.get(url(repo_id, "/files/detail"), params={"path": "README.md"})

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "file_not_analyzed"


def test_file_symbols(client: TestClient, repo_id: str) -> None:
    symbols = client.get(
        url(repo_id, "/files/symbols"), params={"path": "py/shop/models.py"}
    ).json()
    source = read_fixture("python_project", "shop/models.py")

    assert [s["qualified_name"] for s in symbols] == [
        "BaseModel",
        "BaseModel.validate",
        "Product",
        "Product.label",
        "Product.free",
        "Product.discounted",
    ]
    discounted = symbols[-1]
    assert (discounted["start_line"], discounted["end_line"]) == (
        line_of(source, "def discounted"),
        line_of(source, "return round(self.price"),
    )
    assert discounted["parameters"][2] == {
        "name": "round_to",
        "type": "int",
        "default": "2",
        "kind": "keyword_only",
        "optional": False,
    }
    assert symbols[2]["decorators"] == ["dataclass(frozen=True)"]


# --- symbols --------------------------------------------------------------------------


def test_search_symbols(client: TestClient, repo_id: str) -> None:
    body = client.get(url(repo_id, "/symbols"), params={"q": "user"}).json()

    names = [item["qualified_name"] for item in body["items"]]
    assert names[:2] == ["User", "UserId"]  # exact match first, then shorter names
    assert {"UserList", "UserCard", "getUsers", "createUser"} <= set(names)
    assert body["items"][0]["file_path"] == "web/src/types.ts"


def test_search_symbols_filters(client: TestClient, repo_id: str) -> None:
    components = client.get(
        url(repo_id, "/symbols"), params={"kind": "component", "limit": 100}
    ).json()
    python_classes = client.get(
        url(repo_id, "/symbols"), params={"kind": "class", "path_prefix": "py/"}
    ).json()
    exported = client.get(
        url(repo_id, "/symbols"), params={"exported": True, "path_prefix": "py/shop/utils"}
    ).json()

    assert {item["name"] for item in components["items"]} == {
        "UserList",
        "UserCard",
        "LegacyList",
        "App",
    }
    assert {item["name"] for item in python_classes["items"]} == {
        "BaseModel",
        "Product",
        "ProductService",
    }
    assert {item["name"] for item in exported["items"]} == {"slugify", "fetch_catalog"}


def test_search_treats_like_wildcards_literally(client: TestClient, repo_id: str) -> None:
    assert client.get(url(repo_id, "/symbols"), params={"q": "%"}).json()["total"] == 0
    assert client.get(url(repo_id, "/symbols"), params={"q": "_private"}).json()["total"] == 1


# --- dependencies ------------------------------------------------------------------------


def test_dependencies_by_type_and_confidence(client: TestClient, repo_id: str) -> None:
    imports = client.get(
        url(repo_id, "/dependencies"), params={"type": "imports", "limit": 100}
    ).json()
    inferred_imports = client.get(
        url(repo_id, "/dependencies"), params={"type": "imports", "confidence": "inferred"}
    ).json()
    renders = client.get(url(repo_id, "/dependencies"), params={"type": "renders"}).json()

    assert imports["total"] == 19  # 11 TypeScript + 8 Python file edges
    assert all(item["source_symbol"] is None for item in imports["items"])
    assert inferred_imports["total"] == 0
    assert {
        (r["source_symbol"]["qualified_name"], r["target_symbol"]["qualified_name"])
        for r in renders["items"]
    } == {
        ("App", "UserList"),
        ("UserList", "UserCard"),
        ("LegacyList.render", "UserList"),
    }
    assert all(r["confidence"] == "inferred" for r in renders["items"])


def test_dependencies_for_a_file_and_direction(client: TestClient, repo_id: str) -> None:
    params = {"type": "imports", "path": "web/src/types.ts"}
    incoming = client.get(
        url(repo_id, "/dependencies"), params={**params, "direction": "incoming"}
    ).json()
    outgoing = client.get(
        url(repo_id, "/dependencies"), params={**params, "direction": "outgoing"}
    ).json()

    assert sorted(item["source_path"] for item in incoming["items"]) == [
        "web/src/components/UserCard.tsx",
        "web/src/components/UserList.tsx",
        "web/src/lib/api.ts",
    ]
    assert outgoing["total"] == 0


def test_dependencies_for_a_symbol(client: TestClient, repo_id: str) -> None:
    search = client.get(
        url(repo_id, "/symbols"), params={"q": "create_product", "kind": "function"}
    ).json()
    symbol_id = search["items"][0]["id"]

    callers = client.get(
        url(repo_id, "/dependencies"), params={"symbol_id": symbol_id, "direction": "incoming"}
    ).json()

    assert {item["source_symbol"]["qualified_name"] for item in callers["items"]} == {
        "main",
        "list_products",
    }
    assert {item["metadata"]["resolution"] for item in callers["items"]} == {"namespace", "import"}


def test_dependencies_unknown_symbol_or_file(client: TestClient, repo_id: str) -> None:
    unknown_symbol = client.get(
        url(repo_id, "/dependencies"), params={"symbol_id": str(uuid.uuid4())}
    )
    unknown_file = client.get(url(repo_id, "/dependencies"), params={"path": "nope.py"})

    assert unknown_symbol.status_code == 404
    assert unknown_file.status_code == 404


@pytest.mark.parametrize(
    "suffix", ["/files", "/symbols", "/dependencies", "/files/detail?path=a.py"]
)
def test_unknown_repository(client: TestClient, suffix: str) -> None:
    assert client.get(f"/api/v1/repositories/{uuid.uuid4()}{suffix}").status_code == 404


# --- lifecycle ----------------------------------------------------------------------------


def test_analysis_summary_on_repository(client: TestClient, repo_id: str) -> None:
    analysis = client.get(url(repo_id, "")).json()["metadata"]["analysis"]

    assert analysis["files_analyzed"] == 14
    assert analysis["files_by_language"]["python"] == 7
    assert analysis["relationships"]["imports"]["confirmed"] == 19


def test_deleting_repository_removes_analysis(
    client: TestClient, repo_id: str, db_session: Session
) -> None:
    assert client.delete(url(repo_id, "")).status_code == 204

    for model in (CodeFile, CodeSymbol, CodeRelationship):
        assert db_session.scalar(select(func.count()).select_from(model)) == 0
