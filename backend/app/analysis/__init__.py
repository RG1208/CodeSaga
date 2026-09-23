"""Source-code analysis: turn source files into symbols, imports and relationships.

Layers (each only uses the ones above it):

* `results.py`  — plain dataclasses describing what was found in one file.
* `base.py`     — the `LanguageAnalyzer` interface and Tree-sitter helpers.
* `python.py`, `ecmascript.py` — one analyzer per language family.
* `registry.py` — maps file extensions to analyzers; add languages here.
* `resolver.py` — turns import specifiers into repository file paths.
* `graph.py`    — builds file- and symbol-level relationships.
* `repository.py` — analyzes a whole checkout and returns database-ready rows.

Like ingestion, analysis only *reads* files. Nothing is imported or executed:
Tree-sitter builds a syntax tree from the bytes.
"""
