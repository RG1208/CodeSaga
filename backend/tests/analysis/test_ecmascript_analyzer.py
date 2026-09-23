"""JavaScript / TypeScript / TSX analyzers: imports, exports, React, API calls, line ranges."""

from app.analysis.ecmascript import JavaScriptAnalyzer, TsxAnalyzer, TypeScriptAnalyzer
from app.analysis.results import FileAnalysis, SymbolKind
from tests.analysis.helpers import line_of, read_fixture

PROJECT = "ts_project"


def analyze(path: str) -> tuple[FileAnalysis, bytes]:
    source = read_fixture(PROJECT, path)
    analyzer = {".tsx": TsxAnalyzer, ".ts": TypeScriptAnalyzer, ".js": JavaScriptAnalyzer}[
        path[path.rfind(".") :]
    ]
    return analyzer().analyze(source, path), source


def symbol(result: FileAnalysis, qualified_name: str):  # type: ignore[no-untyped-def]
    return next(item for item in result.symbols if item.qualified_name == qualified_name)


def test_typescript_functions_classes_and_methods() -> None:
    result, source = analyze("src/lib/api.ts")

    assert [(s.qualified_name, s.kind) for s in result.symbols] == [
        ("getUsers", SymbolKind.FUNCTION),
        ("createUser", SymbolKind.FUNCTION),
        ("ApiClient", SymbolKind.CLASS),
        ("ApiClient.constructor", SymbolKind.METHOD),
        ("ApiClient.remove", SymbolKind.METHOD),
        ("ApiClient.log", SymbolKind.METHOD),
    ]
    get_users = symbol(result, "getUsers")
    assert get_users.is_async and get_users.is_exported
    assert get_users.return_type == "Promise<User[]>"
    assert get_users.docstring == "Load all users."
    assert (get_users.start_line, get_users.end_line) == (
        line_of(source, "export async function getUsers"),
        line_of(source, "return response.json();") + 1,
    )


def test_arrow_function_parameters_and_range() -> None:
    result, source = analyze("src/lib/api.ts")

    create_user = symbol(result, "createUser")
    assert create_user.signature == 'createUser(name: string, role = "member")'
    assert [p.to_dict() for p in create_user.parameters] == [
        {"name": "name", "type": "string", "kind": "positional"},
        {"name": "role", "default": '"member"', "kind": "positional"},
    ]
    assert (create_user.start_line, create_user.end_line) == (
        line_of(source, "export const createUser"),
        line_of(source, "axios.post("),
    )
    assert create_user.metadata["returns_value"] is True


def test_class_members() -> None:
    result, source = analyze("src/lib/api.ts")

    client = symbol(result, "ApiClient")
    constructor = symbol(result, "ApiClient.constructor")
    assert constructor.parent_key == client.key
    assert constructor.metadata["constructor"] is True
    assert constructor.parameters[0].name == "baseUrl"
    assert client.metadata["default_export"] is True
    remove = symbol(result, "ApiClient.remove")
    assert remove.return_type == "Promise<void>"
    assert (remove.start_line, remove.end_line) == (
        line_of(source, "async remove("),
        line_of(source, "this.log(id);") + 1,
    )


def test_imports_default_named_type_only() -> None:
    result, source = analyze("src/components/UserList.tsx")

    assert [
        (i.module, i.kind, [n.to_dict() for n in i.names], i.is_type_only, i.start_line)
        for i in result.imports
    ] == [
        (
            "react",
            "import",
            [{"name": "default", "alias": "React"}, {"name": "useEffect"}, {"name": "useState"}],
            False,
            line_of(source, 'from "react"'),
        ),
        ("@/lib/api", "import", [{"name": "getUsers"}], False, line_of(source, "@/lib/api")),
        ("@/types", "import", [{"name": "User"}], True, line_of(source, "@/types")),
        ("./UserCard", "import", [{"name": "UserCard"}], False, line_of(source, "./UserCard")),
    ]


def test_namespace_require_dynamic_and_reexports() -> None:
    app, _ = analyze("src/App.tsx")
    assert [n.to_dict() for n in app.imports[2].names] == [{"name": "*", "alias": "format"}]

    index, source = analyze("src/index.ts")
    assert [(i.module, i.kind, [n.to_dict() for n in i.names]) for i in index.imports] == [
        ("./lib/api", "re_export", [{"name": "*"}]),
        ("./components/UserList", "re_export", [{"name": "UserList", "alias": "default"}]),
        ("./utils/format", "re_export", [{"name": "formatName"}]),
        ("./components/UserCard", "dynamic", []),
    ]
    assert index.imports[3].start_line == line_of(source, 'import("./components/UserCard")')

    fmt, _ = analyze("src/utils/format.js")
    assert [(i.module, i.kind, [n.to_dict() for n in i.names]) for i in fmt.imports] == [
        ("path", "require", [{"name": "*", "alias": "path"}])
    ]


def test_exports() -> None:
    result, _ = analyze("src/components/UserList.tsx")
    assert [(e.name, e.local_name, e.kind) for e in result.exports] == [
        ("UserList", "UserList", "named"),
        ("LegacyList", "LegacyList", "named"),
        ("default", "UserList", "default"),
    ]
    assert symbol(result, "UserList").metadata["default_export"] is True

    fmt, _ = analyze("src/utils/format.js")
    assert [(e.name, e.kind) for e in fmt.exports] == [
        ("formatName", "commonjs"),
        ("initials", "commonjs"),
    ]
    assert all(s.is_exported for s in fmt.symbols)


def test_react_components_hooks_and_renders() -> None:
    result, source = analyze("src/components/UserList.tsx")

    user_list = symbol(result, "UserList")
    assert user_list.kind is SymbolKind.COMPONENT
    assert user_list.metadata["hooks"] == ["useState", "useEffect"]
    assert user_list.metadata["renders"] == ["UserCard"]
    assert user_list.return_type == "JSX.Element"
    assert (user_list.start_line, user_list.end_line) == (
        line_of(source, "export function UserList"),
        line_of(source, "export class LegacyList") - 2,
    )

    legacy = symbol(result, "LegacyList")
    assert legacy.kind is SymbolKind.COMPONENT  # class component
    assert legacy.metadata["bases"] == ["React.Component"]
    assert symbol(result, "LegacyList.render").metadata["renders"] == ["UserList"]

    card, _ = analyze("src/components/UserCard.tsx")
    user_card = symbol(card, "UserCard")
    assert user_card.kind is SymbolKind.COMPONENT  # arrow function returning JSX
    assert user_card.parameters[0].kind == "destructured"
    assert symbol(card, "Props").kind is SymbolKind.INTERFACE
    assert symbol(card, "Props").is_exported is False


def test_api_calls() -> None:
    result, source = analyze("src/lib/api.ts")

    assert [(c.client, c.method, c.url, c.line) for c in result.api_calls] == [
        ("fetch", "GET", "/api/users", line_of(source, 'fetch("/api/users")')),
        ("axios", "POST", "{BASE}/users/{name}", line_of(source, "axios.post(")),
        ("fetch", "DELETE", "/api/users/{id}", line_of(source, "fetch(`/api/users/${id}`")),
    ]
    assert symbol(result, "ApiClient.remove").metadata["api_calls"][0]["method"] == "DELETE"


def test_api_calls_require_a_literal_url() -> None:
    source = (
        b"function f(url, api) { fetch(url); api.get(url); cache.get('key'); client.get('/ok'); }"
    )

    result = JavaScriptAnalyzer().analyze(source, "f.js")

    assert [(c.client, c.url) for c in result.api_calls] == [("client", "/ok")]


def test_types_interfaces_enums() -> None:
    result, source = analyze("src/types.ts")

    assert [(s.name, s.kind, s.is_exported) for s in result.symbols] == [
        ("User", SymbolKind.INTERFACE, True),
        ("UserId", SymbolKind.TYPE_ALIAS, True),
        ("Role", SymbolKind.ENUM, True),
    ]
    user = symbol(result, "User")
    assert user.docstring == "A registered user."
    assert (user.start_line, user.end_line) == (
        line_of(source, "export interface User"),
        line_of(source, "name: string;") + 1,
    )


def test_javascript_jsdoc_defaults_and_rest() -> None:
    result, _ = analyze("src/utils/format.js")

    format_name = symbol(result, "formatName")
    assert format_name.docstring == "Format a display name."
    assert [p.to_dict() for p in format_name.parameters] == [
        {"name": "first", "kind": "positional"},
        {"name": "last", "default": '""', "kind": "positional"},
        {"name": "extra", "kind": "rest"},
    ]
    # `formatName(name).slice(0, 2)`: the chained call on a call result is skipped,
    # the inner `formatName(...)` call is kept.
    assert symbol(result, "initials").metadata["calls"] == ["formatName"]


def test_decorators_and_fields() -> None:
    source = b"""@Controller("users")
export class UsersController {
  @Get(":id")
  find(@Param("id") id: string) { return this.service.find(id); }
  onClick = () => this.find("1");
}
"""
    result = TypeScriptAnalyzer().analyze(source, "c.ts")

    controller = symbol(result, "UsersController")
    assert controller.decorators == ['Controller("users")']
    assert controller.start_line == 1
    find = symbol(result, "UsersController.find")
    assert find.decorators == ['Get(":id")']
    assert (find.start_line, find.end_line) == (3, 4)
    on_click = symbol(result, "UsersController.onClick")
    assert on_click.metadata["field"] is True
    assert on_click.metadata["calls"] == ["this.find"]


def test_syntax_errors_are_tolerated() -> None:
    source = (
        b"export function ok() { return 1 }\nfunction broken( {\nexport const after = () => 2;\n"
    )

    result = TypeScriptAnalyzer().analyze(source, "x.ts")

    assert result.syntax_error_count > 0
    assert "ok" in {s.name for s in result.symbols}


def test_overloads_generics_and_duplicate_exports() -> None:
    source = b"""export function pick<T>(items: T[]): T;
export function pick<T>(items: T[], index: number): T;
export function pick<T>(items: T[], index = 0): T {
  return items[index];
}
"""
    result = TypeScriptAnalyzer().analyze(source, "pick.ts")

    assert [(s.name, s.start_line, s.end_line) for s in result.symbols] == [("pick", 3, 5)]
    assert result.symbols[0].signature == "function pick<T>(items: T[], index = 0): T"
    assert [(e.name, e.kind) for e in result.exports] == [("pick", "named")]
