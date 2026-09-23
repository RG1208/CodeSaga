"""The code-aware tokenizer that BM25 indexes with."""

import pytest

from app.retrieval.tokenizer import split_identifier, stem, tokenize, tokenize_path


@pytest.mark.parametrize(
    ("identifier", "parts"),
    [
        ("getUserById", ["get", "user", "by", "id"]),
        ("get_user_by_id", ["get", "user", "by", "id"]),
        ("HTTPResponseCode", ["http", "response", "code"]),
        ("RateLimiter", ["rate", "limiter"]),
        # Digits stay attached, so identifiers like pbkdf2 survive as one token.
        ("user2Role", ["user2", "role"]),
        ("pbkdf2_hmac", ["pbkdf2", "hmac"]),
        ("simple", ["simple"]),
    ],
)
def test_split_identifier(identifier: str, parts: list[str]) -> None:
    assert split_identifier(identifier) == parts


@pytest.mark.parametrize(
    ("word", "stemmed"),
    [
        ("refunds", "refund"),
        ("refunded", "refund"),
        ("hashing", "hash"),
        ("classes", "class"),
        ("entries", "entry"),
        ("address", "address"),  # "ss" endings are left alone
        ("is", "is"),  # too short to strip
        ("cache", "cache"),
    ],
)
def test_stem(word: str, stemmed: str) -> None:
    assert stem(word) == stemmed


def test_identifiers_are_indexed_whole_and_in_parts() -> None:
    tokens = tokenize("def hash_password(password): return pbkdf2_hmac(password)")

    assert {"hash", "password", "hashpassword"} <= set(tokens)  # both forms are searchable
    assert "pbkdf2" in tokens


def test_stopwords_and_short_tokens_are_dropped() -> None:
    tokens = tokenize("if self.x is not None: return the value")

    assert "self" not in tokens and "is" not in tokens and "the" not in tokens
    assert "x" not in tokens  # single characters carry no signal
    assert "value" in tokens


def test_queries_match_code_after_stemming() -> None:
    document = set(tokenize("def refund_payment(charge): ..."))

    assert set(tokenize("refunding payments")) & document == {"refund", "payment"}


def test_tokenize_path() -> None:
    assert tokenize_path("app/middleware/rate_limit.py") == [
        "app",
        "middleware",
        "rate",
        "limit",
        "ratelimit",
        "py",
    ]


@pytest.mark.parametrize("text", ["", "   ", "# ...", "?!"])
def test_empty_inputs(text: str) -> None:
    assert tokenize(text) == []
