"""File classification tables used by the scanner.

Language detection is by file extension (or well-known file name). It is a
cheap heuristic that is good enough for repository statistics; later phases
parse files properly.
"""

LANGUAGE_BY_EXTENSION: dict[str, str] = {
    ".py": "Python", ".pyi": "Python", ".ipynb": "Jupyter Notebook",
    ".js": "JavaScript", ".mjs": "JavaScript", ".cjs": "JavaScript", ".jsx": "JavaScript",
    ".ts": "TypeScript", ".mts": "TypeScript", ".cts": "TypeScript", ".tsx": "TypeScript",
    ".java": "Java", ".kt": "Kotlin", ".kts": "Kotlin", ".scala": "Scala", ".groovy": "Groovy",
    ".go": "Go", ".rs": "Rust", ".c": "C", ".h": "C",
    ".cc": "C++", ".cpp": "C++", ".cxx": "C++", ".hpp": "C++", ".hh": "C++",
    ".cs": "C#", ".fs": "F#", ".swift": "Swift", ".m": "Objective-C", ".mm": "Objective-C",
    ".rb": "Ruby", ".php": "PHP", ".pl": "Perl", ".lua": "Lua", ".r": "R", ".jl": "Julia",
    ".dart": "Dart", ".ex": "Elixir", ".exs": "Elixir", ".erl": "Erlang", ".hs": "Haskell",
    ".clj": "Clojure", ".ml": "OCaml", ".zig": "Zig", ".sol": "Solidity",
    ".sh": "Shell", ".bash": "Shell", ".zsh": "Shell", ".ps1": "PowerShell",
    ".sql": "SQL", ".html": "HTML", ".htm": "HTML", ".css": "CSS", ".scss": "SCSS",
    ".sass": "Sass", ".less": "Less", ".vue": "Vue", ".svelte": "Svelte",
    ".json": "JSON", ".yaml": "YAML", ".yml": "YAML", ".toml": "TOML", ".xml": "XML",
    ".ini": "INI", ".proto": "Protocol Buffers", ".graphql": "GraphQL", ".gql": "GraphQL",
    ".md": "Markdown", ".mdx": "MDX", ".rst": "reStructuredText", ".tex": "TeX",
}  # fmt: skip

LANGUAGE_BY_FILENAME: dict[str, str] = {
    "Dockerfile": "Dockerfile",
    "Makefile": "Makefile",
    "CMakeLists.txt": "CMake",
    "Jenkinsfile": "Groovy",
}

# Data/markup formats are indexed but never chosen as a repository's primary language.
NON_PROGRAMMING_LANGUAGES = frozenset(
    {"JSON", "YAML", "TOML", "XML", "INI", "Markdown", "MDX", "reStructuredText", "TeX"}
)

# Directories that hold dependencies, build output or tool caches, not project source.
IGNORED_DIRECTORIES = frozenset(
    {
        ".git", ".hg", ".svn", "node_modules", "bower_components", ".venv", "venv", "env",
        "__pycache__", ".mypy_cache", ".pytest_cache", ".ruff_cache", ".tox", ".nox",
        ".next", ".nuxt", ".svelte-kit", ".turbo", ".cache", "dist", "build", "out",
        "target", "coverage", ".gradle", ".idea", ".vscode", ".terraform",
    }
)  # fmt: skip

# Dependency and build manifests: they describe a project's stack.
MANIFEST_FILENAMES = frozenset(
    {
        "package.json", "pyproject.toml", "requirements.txt", "setup.py", "setup.cfg",
        "Pipfile", "poetry.lock", "go.mod", "Cargo.toml", "pom.xml", "build.gradle",
        "build.gradle.kts", "Gemfile", "composer.json", "mix.exs", "pubspec.yaml",
        "Package.swift", "CMakeLists.txt", "Makefile", "Dockerfile", "docker-compose.yml",
    }
)  # fmt: skip

README_PREFIXES = ("readme",)
LICENSE_PREFIXES = ("license", "licence", "copying")


def detect_language(filename: str) -> str | None:
    if filename in LANGUAGE_BY_FILENAME:
        return LANGUAGE_BY_FILENAME[filename]
    dot = filename.rfind(".")
    if dot <= 0:  # no extension, or a dotfile such as ".gitignore"
        return None
    return LANGUAGE_BY_EXTENSION.get(filename[dot:].lower())
