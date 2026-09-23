"""Import resolution: which repository file does an import specifier refer to?

Only the repository's own file list is consulted (plus tsconfig/jsconfig files for
path aliases); nothing is installed or executed, so third-party packages resolve
to "external".

Confidence:
* confirmed — the specifier maps to exactly one existing file by the language's rules
  (relative paths, a unique package path, tsconfig `paths`/`baseUrl`).
* inferred  — several files could match (e.g. two `utils/__init__.py` under different
  source roots); the closest one to the importing file is chosen.
"""

import json
import posixpath
import re
import sys
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

from app.analysis.results import Confidence, ExtractedImport

JS_LANGUAGES = frozenset({"javascript", "typescript", "tsx"})
_JS_EXTENSIONS = (".ts", ".tsx", ".d.ts", ".js", ".jsx", ".mjs", ".cjs", ".mts", ".cts")
_JS_SOURCE_SUFFIX = re.compile(r"\.(m|c)?jsx?$")
_TS_CONFIG_NAMES = ("tsconfig.json", "jsconfig.json")
_MAX_EXTENDS_DEPTH = 5


@dataclass
class ResolvedTarget:
    path: str
    confidence: Confidence
    strategy: str
    candidates: list[str] = field(default_factory=list)


@dataclass
class ImportResolution:
    status: str  # resolved | external | unresolved
    target: ResolvedTarget | None = None  # the module itself
    # Python `from package import submodule`: each name that is itself a module file.
    name_targets: dict[str, ResolvedTarget] = field(default_factory=dict)
    package: str | None = None  # external package / top-level module name

    def all_targets(self) -> list[ResolvedTarget]:
        targets = [self.target] if self.target else []
        return targets + list(self.name_targets.values())


class ImportResolver:
    def __init__(self, paths: Iterable[str], read_text: Callable[[str], str | None]) -> None:
        self.paths = frozenset(paths)
        self._read_text = read_text
        self._python_modules: dict[str, list[str]] | None = None
        self._ts_configs: dict[str, dict | None] = {}

    def resolve(self, importer: str, language: str, imported: ExtractedImport) -> ImportResolution:
        if language == "python":
            return self._resolve_python(importer, imported)
        if language in JS_LANGUAGES:
            return self._resolve_js(importer, imported.module)
        return ImportResolution(status="unresolved")

    # -- Python ------------------------------------------------------------------

    def _resolve_python(self, importer: str, imported: ExtractedImport) -> ImportResolution:
        dotted = imported.module.lstrip(".")
        names = (
            [name.name for name in imported.names if name.name != "*"]
            if imported.kind == "from"
            else []
        )

        if imported.level > 0:
            package_dir = posixpath.dirname(importer)
            for _ in range(imported.level - 1):
                package_dir = posixpath.dirname(package_dir)
            base = posixpath.join(package_dir, *dotted.split(".")) if dotted else package_dir
            resolution = ImportResolution(status="unresolved")
            if path := self._python_module_file(base):
                resolution.target = ResolvedTarget(path, Confidence.CONFIRMED, "relative")
            for name in names:
                if path := self._python_module_file(posixpath.join(base, name)):
                    resolution.name_targets[name] = ResolvedTarget(
                        path, Confidence.CONFIRMED, "relative"
                    )
            if resolution.all_targets():
                resolution.status = "resolved"
            return resolution

        top_level = dotted.split(".")[0]
        resolution = ImportResolution(status="external", package=top_level)
        if target := self._python_absolute(importer, dotted):
            resolution.target = target
        for name in names:
            if target := self._python_absolute(importer, f"{dotted}.{name}"):
                resolution.name_targets[name] = target
        if resolution.all_targets():
            resolution.status = "resolved"
            resolution.package = None
        elif top_level in sys.stdlib_module_names:
            resolution.package = top_level
        return resolution

    def _python_module_file(self, base: str) -> str | None:
        for candidate in (f"{base}.py", f"{base}/__init__.py", f"{base}.pyi"):
            normalized = posixpath.normpath(candidate)
            if normalized in self.paths:
                return normalized
        return None

    def _python_absolute(self, importer: str, dotted: str) -> ResolvedTarget | None:
        candidates = self._python_index().get(dotted, [])
        if not candidates:
            return None
        if len(candidates) == 1:
            return ResolvedTarget(candidates[0], Confidence.CONFIRMED, "package")
        importer_dir = posixpath.dirname(importer)
        best = max(candidates, key=lambda path: (_shared_prefix(importer_dir, path), -len(path)))
        return ResolvedTarget(best, Confidence.INFERRED, "ambiguous", candidates=sorted(candidates))

    def _python_index(self) -> dict[str, list[str]]:
        """Map every importable dotted name to the files that could provide it.

        `backend/app/core/config.py` is importable as `app.core.config` when
        `backend/` is a source root: a directory is a possible root if it is the
        repository root or has no `__init__.py` (so it is not itself a package).
        """
        if self._python_modules is not None:
            return self._python_modules
        index: dict[str, list[str]] = {}
        for path in self.paths:
            if not path.endswith((".py", ".pyi")):
                continue
            parts = path.rsplit(".", 1)[0].split("/")
            if parts[-1] == "__init__":
                parts = parts[:-1]
            for start in range(len(parts)):
                prefix_dir = "/".join(parts[:start])
                if start > 0 and f"{prefix_dir}/__init__.py" in self.paths:
                    continue
                module = ".".join(parts[start:])
                if module and all(part.isidentifier() for part in parts[start:]):
                    index.setdefault(module, []).append(path)
        self._python_modules = index
        return index

    # -- JavaScript / TypeScript -------------------------------------------------

    def _resolve_js(self, importer: str, specifier: str) -> ImportResolution:
        if not specifier:
            return ImportResolution(status="unresolved")
        if specifier.startswith(("./", "../")) or specifier in (".", ".."):
            base = posixpath.normpath(posixpath.join(posixpath.dirname(importer), specifier))
            if base == ".." or base.startswith("../"):
                return ImportResolution(status="unresolved")  # escapes the repository
            if path := self._js_file(base):
                return ImportResolution(
                    status="resolved", target=ResolvedTarget(path, Confidence.CONFIRMED, "relative")
                )
            return ImportResolution(status="unresolved")
        if specifier.startswith("/") or ":" in specifier.split("/")[0]:
            # absolute paths, URLs and protocol imports such as node:fs
            return ImportResolution(status="external", package=specifier.split("/")[0])

        config = self._ts_config_for(importer)
        if config is not None:
            for base in self._alias_candidates(config, specifier):
                if path := self._js_file(base):
                    return ImportResolution(
                        status="resolved",
                        target=ResolvedTarget(path, Confidence.CONFIRMED, "tsconfig"),
                    )
        parts = specifier.split("/")
        package = "/".join(parts[:2]) if specifier.startswith("@") else parts[0]
        return ImportResolution(status="external", package=package)

    def _js_file(self, base: str) -> str | None:
        base = posixpath.normpath(base)
        if base in self.paths:
            return base
        stems = [base]
        if _JS_SOURCE_SUFFIX.search(base):  # TypeScript ESM: "./util.js" refers to util.ts
            stems.append(_JS_SOURCE_SUFFIX.sub("", base))
        for stem in stems:
            for extension in _JS_EXTENSIONS:
                if f"{stem}{extension}" in self.paths:
                    return f"{stem}{extension}"
        for extension in _JS_EXTENSIONS:
            candidate = f"{base}/index{extension}"
            if candidate in self.paths:
                return candidate
        return None

    def _alias_candidates(self, config: dict, specifier: str) -> list[str]:
        candidates: list[str] = []
        base_url = config.get("base_url")
        for pattern, replacements in config.get("paths", {}).items():
            match = _match_path_pattern(pattern, specifier)
            if match is None:
                continue
            for replacement in replacements:
                if isinstance(replacement, str):
                    root = base_url if base_url is not None else config["directory"]
                    candidates.append(posixpath.join(root, replacement.replace("*", match, 1)))
        if base_url is not None:
            candidates.append(posixpath.join(base_url, specifier))
        return [posixpath.normpath(candidate) for candidate in candidates]

    def _ts_config_for(self, importer: str) -> dict | None:
        directory = posixpath.dirname(importer)
        while True:
            for name in _TS_CONFIG_NAMES:
                config_path = posixpath.join(directory, name) if directory else name
                if config_path in self.paths:
                    return self._load_ts_config(config_path)
            if not directory:
                return None
            directory = posixpath.dirname(directory)

    def _load_ts_config(self, config_path: str, depth: int = 0) -> dict | None:
        if config_path in self._ts_configs:
            return self._ts_configs[config_path]
        self._ts_configs[config_path] = None  # guards against `extends` cycles
        text = self._read_text(config_path)
        data = parse_jsonc(text) if text is not None else None
        if not isinstance(data, dict):
            return None
        directory = posixpath.dirname(config_path)
        config: dict = {"directory": directory, "paths": {}, "base_url": None}

        extends = data.get("extends")
        if isinstance(extends, str) and extends.startswith(".") and depth < _MAX_EXTENDS_DEPTH:
            parent_path = posixpath.normpath(posixpath.join(directory, extends))
            if not parent_path.endswith(".json"):
                parent_path += ".json"
            if parent_path in self.paths and (
                parent := self._load_ts_config(parent_path, depth + 1)
            ):
                config.update(paths=dict(parent["paths"]), base_url=parent["base_url"])

        options = data.get("compilerOptions")
        if isinstance(options, dict):
            if isinstance(options.get("baseUrl"), str):
                config["base_url"] = posixpath.normpath(
                    posixpath.join(directory, options["baseUrl"])
                )
            if isinstance(options.get("paths"), dict):
                config["paths"] = options["paths"]
                if config["base_url"] is None:
                    config["base_url"] = directory or "."
        self._ts_configs[config_path] = config
        return config


def _match_path_pattern(pattern: str, specifier: str) -> str | None:
    """tsconfig `paths` matching: "@/*" matches "@/lib/api" capturing "lib/api"."""
    if "*" not in pattern:
        return "" if pattern == specifier else None
    prefix, _, suffix = pattern.partition("*")
    if (
        specifier.startswith(prefix)
        and specifier.endswith(suffix)
        and len(specifier) >= len(prefix) + len(suffix)
    ):
        return specifier[len(prefix) : len(specifier) - len(suffix)]
    return None


def _shared_prefix(directory: str, path: str) -> int:
    shared = 0
    for left, right in zip(directory.split("/"), path.split("/"), strict=False):
        if left != right:
            break
        shared += 1
    return shared


def parse_jsonc(text: str) -> object | None:
    """Parse JSON with comments and trailing commas (the tsconfig.json dialect)."""
    output: list[str] = []
    index, length = 0, len(text)
    in_string = False
    while index < length:
        char = text[index]
        if in_string:
            output.append(char)
            if char == "\\" and index + 1 < length:
                output.append(text[index + 1])
                index += 1
            elif char == '"':
                in_string = False
        elif char == '"':
            in_string = True
            output.append(char)
        elif text.startswith("//", index):
            newline = text.find("\n", index)
            index = length if newline == -1 else newline
            continue
        elif text.startswith("/*", index):
            close = text.find("*/", index + 2)
            index = length if close == -1 else close + 2
            continue
        else:
            output.append(char)
        index += 1
    cleaned = re.sub(r",(\s*[}\]])", r"\1", "".join(output))
    try:
        return json.loads(cleaned)
    except ValueError:
        return None
