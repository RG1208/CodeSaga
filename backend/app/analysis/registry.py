"""Which analyzer handles which file.

Adding a language (e.g. Go) takes two steps:
1. `pip install tree-sitter-go` and write `GoAnalyzer(TreeSitterAnalyzer)` that fills
   a `FileAnalysis`.
2. Register it in `default_registry()` below (and teach `resolver.py` its import rules
   if file-level dependencies should be resolved).
"""

from functools import lru_cache
from pathlib import PurePosixPath

from app.analysis.base import LanguageAnalyzer
from app.analysis.ecmascript import JavaScriptAnalyzer, TsxAnalyzer, TypeScriptAnalyzer
from app.analysis.python import PythonAnalyzer

# Generated or bundled code that is not worth parsing.
_SKIPPED_SUFFIXES = (".min.js", ".min.mjs", ".bundle.js", ".chunk.js")


class AnalyzerRegistry:
    def __init__(self) -> None:
        self._by_extension: dict[str, LanguageAnalyzer] = {}

    def register(self, analyzer: LanguageAnalyzer) -> None:
        for extension in analyzer.extensions:
            self._by_extension[extension.lower()] = analyzer

    def analyzer_for(self, path: str) -> LanguageAnalyzer | None:
        lowered = path.lower()
        if lowered.endswith(_SKIPPED_SUFFIXES):
            return None
        return self._by_extension.get(PurePosixPath(lowered).suffix)

    @property
    def languages(self) -> list[str]:
        return sorted({analyzer.language for analyzer in self._by_extension.values()})


@lru_cache
def default_registry() -> AnalyzerRegistry:
    registry = AnalyzerRegistry()
    for analyzer in (PythonAnalyzer(), JavaScriptAnalyzer(), TypeScriptAnalyzer(), TsxAnalyzer()):
        registry.register(analyzer)
    return registry
