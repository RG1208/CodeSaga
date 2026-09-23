"""Import resolution: import specifiers → repository files, with confidence."""

import pytest

from app.analysis.resolver import ImportResolver, parse_jsonc
from app.analysis.results import Confidence, ExtractedImport, ImportedName

FILES: dict[str, str] = {
    "backend/app/__init__.py": "",
    "backend/app/core/__init__.py": "",
    "backend/app/core/config.py": "",
    "backend/app/models/__init__.py": "",
    "backend/app/models/user.py": "",
    "backend/app/main.py": "",
    "tools/utils.py": "",
    "scripts/utils.py": "",
    "scripts/run.py": "",
    "web/tsconfig.json": (
        '{\n  // comment\n  "extends": "./tsconfig.base.json",\n'
        '  "compilerOptions": {"paths": {"@/*": ["./src/*"],},},\n}'
    ),
    "web/tsconfig.base.json": '{"compilerOptions": {"baseUrl": "."}}',
    "web/src/lib/api.ts": "",
    "web/src/components/Card/index.tsx": "",
    "web/src/app/page.tsx": "",
    "web/src/util.ts": "",
    "web/src/styles.css": "",
    "plain/index.js": "",
    "plain/helpers.js": "",
}


@pytest.fixture
def resolver() -> ImportResolver:
    return ImportResolver(FILES, FILES.get)


def python(resolver, importer, module, *, kind="from", names=(), level=0):  # type: ignore[no-untyped-def]
    imported = ExtractedImport(
        module=module,
        kind=kind,
        level=level,
        start_line=1,
        end_line=1,
        names=[ImportedName(n) for n in names],
    )
    return resolver.resolve(importer, "python", imported)


def js(resolver, importer, specifier, language="tsx"):  # type: ignore[no-untyped-def]
    return resolver.resolve(
        importer,
        language,
        ExtractedImport(module=specifier, kind="import", start_line=1, end_line=1),
    )


def test_python_package_under_source_root(resolver: ImportResolver) -> None:
    result = python(resolver, "backend/app/main.py", "app.core.config", names=["get_settings"])

    assert result.status == "resolved"
    assert (result.target.path, result.target.confidence, result.target.strategy) == (
        "backend/app/core/config.py",
        Confidence.CONFIRMED,
        "package",
    )
    assert result.name_targets == {}


def test_python_from_package_import_submodule(resolver: ImportResolver) -> None:
    result = python(resolver, "backend/app/main.py", "app.core", names=["config"])

    assert result.target.path == "backend/app/core/__init__.py"
    assert result.name_targets["config"].path == "backend/app/core/config.py"


def test_python_relative_imports(resolver: ImportResolver) -> None:
    parent = python(resolver, "backend/app/core/config.py", "..models", names=["user"], level=2)
    assert parent.target.path == "backend/app/models/__init__.py"
    assert parent.name_targets["user"].path == "backend/app/models/user.py"
    assert parent.target.strategy == "relative"

    missing = python(resolver, "backend/app/core/config.py", ".nothing", names=["x"], level=1)
    assert missing.status == "unresolved" and missing.target is None


def test_python_ambiguous_module_is_inferred(resolver: ImportResolver) -> None:
    result = python(resolver, "scripts/run.py", "utils", kind="import")

    assert result.target.path == "scripts/utils.py"  # closest to the importer
    assert result.target.confidence is Confidence.INFERRED
    assert result.target.candidates == ["scripts/utils.py", "tools/utils.py"]


def test_python_inner_package_names_are_not_importable_roots(resolver: ImportResolver) -> None:
    # backend/app has __init__.py, so "core.config" is not a valid top-level module.
    assert (
        python(resolver, "backend/app/main.py", "core.config", kind="import").status == "external"
    )


@pytest.mark.parametrize(
    ("module", "package"), [("os", "os"), ("os.path", "os"), ("fastapi", "fastapi")]
)
def test_python_external_modules(resolver: ImportResolver, module: str, package: str) -> None:
    result = python(resolver, "backend/app/main.py", module, kind="import")

    assert (result.status, result.package, result.target) == ("external", package, None)


@pytest.mark.parametrize(
    ("specifier", "expected", "strategy"),
    [
        ("@/lib/api", "web/src/lib/api.ts", "tsconfig"),  # paths alias via `extends` + JSONC
        ("../components/Card", "web/src/components/Card/index.tsx", "relative"),  # directory index
        ("../util.js", "web/src/util.ts", "relative"),  # ESM-style .js pointing at .ts
        ("../util", "web/src/util.ts", "relative"),
        ("src/util", "web/src/util.ts", "tsconfig"),  # baseUrl
        ("../styles.css", "web/src/styles.css", "relative"),  # non-code file
    ],
)
def test_js_resolution(
    resolver: ImportResolver, specifier: str, expected: str, strategy: str
) -> None:
    result = js(resolver, "web/src/app/page.tsx", specifier)

    assert result.status == "resolved"
    assert (result.target.path, result.target.confidence, result.target.strategy) == (
        expected,
        Confidence.CONFIRMED,
        strategy,
    )


@pytest.mark.parametrize(
    ("specifier", "package"),
    [
        ("react", "react"),
        ("react-dom/client", "react-dom"),
        ("@tanstack/react-query/devtools", "@tanstack/react-query"),
        ("node:fs", "node:fs"),
    ],
)
def test_js_external_packages(resolver: ImportResolver, specifier: str, package: str) -> None:
    result = js(resolver, "web/src/app/page.tsx", specifier)

    assert (result.status, result.package) == ("external", package)


@pytest.mark.parametrize("specifier", ["../../../../etc/passwd", "./missing", "../lib/nope"])
def test_js_unresolved_and_escaping_paths(resolver: ImportResolver, specifier: str) -> None:
    assert js(resolver, "web/src/app/page.tsx", specifier).status == "unresolved"


def test_js_without_tsconfig(resolver: ImportResolver) -> None:
    assert (
        js(resolver, "plain/index.js", "./helpers", "javascript").target.path == "plain/helpers.js"
    )
    assert js(resolver, "plain/index.js", "helpers", "javascript").status == "external"


def test_parse_jsonc() -> None:
    text = (
        '{\n "url": "http://example.com//path", // trailing comment\n'
        ' /* block */ "list": [1, 2,],\n}'
    )

    assert parse_jsonc(text) == {"url": "http://example.com//path", "list": [1, 2]}
    assert parse_jsonc("{not json") is None
