import pytest

from app.analysis.base import LanguageAnalyzer
from app.analysis.registry import AnalyzerRegistry, default_registry
from app.analysis.results import ExtractedSymbol, FileAnalysis, SymbolKind


@pytest.mark.parametrize(
    ("path", "language"),
    [
        ("app/main.py", "python"),
        ("types.pyi", "python"),
        ("src/index.js", "javascript"),
        ("src/App.jsx", "javascript"),
        ("lib/x.mjs", "javascript"),
        ("src/api.ts", "typescript"),
        ("src/types.d.ts", "typescript"),
        ("src/App.tsx", "tsx"),
        ("SRC/APP.TSX", "tsx"),
        ("README.md", None),
        ("Makefile", None),
        ("dist/vendor.min.js", None),
    ],
)
def test_default_registry_languages(path: str, language: str | None) -> None:
    analyzer = default_registry().analyzer_for(path)

    assert (analyzer.language if analyzer else None) == language


def test_new_languages_plug_in_without_touching_existing_analyzers() -> None:
    class ToyAnalyzer(LanguageAnalyzer):
        language = "toy"
        extensions = (".toy",)

        def analyze(self, source: bytes, path: str) -> FileAnalysis:
            result = FileAnalysis(language="toy")
            result.symbols.append(
                ExtractedSymbol(
                    key=0, name="main", kind=SymbolKind.FUNCTION, start_line=1, end_line=1
                )
            )
            return result

    registry = AnalyzerRegistry()
    registry.register(ToyAnalyzer())

    analyzer = registry.analyzer_for("hello.toy")
    assert analyzer is not None
    assert analyzer.analyze(b"", "hello.toy").symbols[0].name == "main"
    assert registry.languages == ["toy"]
