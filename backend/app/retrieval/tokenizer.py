"""Code-aware tokenizer used by BM25.

Source code is not prose: identifiers carry the meaning and are written as
`getUserById`, `get_user_by_id` or `GETUserID`. A whitespace tokenizer would index
those as single rare terms, so a search for "user" would miss them. This tokenizer
therefore emits both the whole identifier and its parts, then applies a small
deterministic stemmer so "refunds" matches "refund".
"""

import re

TOKENIZER_VERSION = 1

_WORD = re.compile(r"[A-Za-z][A-Za-z0-9_]*|\d+")
# "HTTPResponse" → HTTP, Response; "getUserID" → get, User, ID; "user_id" → user, id
_IDENTIFIER_PART = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z0-9]+|[A-Z]+|\d+")
_MIN_LENGTH = 2
_MAX_TOKEN_LENGTH = 40

# Words too common in English or code to be useful; BM25's IDF handles the rest.
STOPWORDS = frozenset(
    {
        "a",
        "about",
        "after",
        "an",
        "and",
        "are",
        "as",
        "async",
        "at",
        "await",
        "be",
        "been",
        "before",
        "being",
        "between",
        "by",
        "can",
        "class",
        "cls",
        "const",
        "could",
        "def",
        "did",
        "do",
        "does",
        "doing",
        "done",
        "down",
        "during",
        "else",
        "export",
        "false",
        "for",
        "from",
        "function",
        "had",
        "has",
        "have",
        "here",
        "if",
        "import",
        "in",
        "instanceof",
        "into",
        "is",
        "it",
        "its",
        "let",
        "may",
        "might",
        "must",
        "new",
        "none",
        "not",
        "null",
        "of",
        "on",
        "or",
        "out",
        "over",
        "return",
        "self",
        "shall",
        "should",
        "than",
        "that",
        "the",
        "then",
        "there",
        "these",
        "this",
        "those",
        "to",
        "true",
        "typeof",
        "undefined",
        "under",
        "up",
        "var",
        "was",
        "were",
        "will",
        "with",
        "would",
    }
)

# Light suffix stripping: (suffix, minimum stem length, replacement)
_SUFFIXES = (
    ("ies", 4, "y"),
    ("sses", 5, "ss"),
    ("ing", 5, ""),
    ("ed", 5, ""),
    ("es", 4, ""),
    ("s", 3, ""),
)


def stem(token: str) -> str:
    """Strip a few common English suffixes. Deterministic and intentionally simple."""
    for suffix, minimum, replacement in _SUFFIXES:
        if len(token) > minimum and token.endswith(suffix) and not token.endswith("ss"):
            return token[: -len(suffix)] + replacement
    return token


def split_identifier(identifier: str) -> list[str]:
    """`getUserByID` → ['get', 'user', 'by', 'id']; `user_id` → ['user', 'id']."""
    return [part.lower() for part in _IDENTIFIER_PART.findall(identifier) if part]


def tokenize(text: str) -> list[str]:
    """Tokens for indexing or querying: identifier parts plus the whole identifier."""
    tokens: list[str] = []
    for match in _WORD.finditer(text):
        word = match.group(0)
        if len(word) > _MAX_TOKEN_LENGTH:
            continue
        parts = split_identifier(word)
        for part in parts:
            if len(part) >= _MIN_LENGTH and part not in STOPWORDS:
                tokens.append(stem(part))
        whole = word.lower().replace("_", "")
        if (
            len(parts) > 1
            and _MIN_LENGTH <= len(whole) <= _MAX_TOKEN_LENGTH
            and whole not in STOPWORDS
        ):
            tokens.append(stem(whole))  # keeps exact "getuserbyid" searches working
    return tokens


def tokenize_path(path: str) -> list[str]:
    """Path segments are searchable too: "app/core/config.py" → app, core, config, py."""
    return tokenize(path.replace("/", " ").replace(".", " ").replace("-", " "))
