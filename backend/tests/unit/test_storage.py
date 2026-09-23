import uuid
from pathlib import Path

import pytest

from app.ingestion.errors import UnsafePathError
from app.ingestion.storage import RepositoryStorage, directory_size_bytes, ensure_within


@pytest.fixture
def storage(tmp_path: Path) -> RepositoryStorage:
    return RepositoryStorage(tmp_path / "storage")


def test_path_for_is_derived_from_uuid_inside_root(storage: RepositoryStorage) -> None:
    repository_id = uuid.uuid4()

    path = storage.path_for(repository_id)

    assert path == storage.root / str(repository_id)
    assert path.is_relative_to(storage.root)


@pytest.mark.parametrize("bad_id", ["../../etc", "/etc/passwd", "..", "abc"])
def test_path_for_rejects_anything_but_a_uuid(storage: RepositoryStorage, bad_id: str) -> None:
    with pytest.raises(UnsafePathError):
        storage.path_for(bad_id)  # type: ignore[arg-type]


@pytest.mark.parametrize("candidate", ["../outside", "a/../../outside", "/etc"])
def test_ensure_within_rejects_escapes(tmp_path: Path, candidate: str) -> None:
    root = tmp_path / "root"
    root.mkdir()

    with pytest.raises(UnsafePathError):
        ensure_within(root, root / candidate)


def test_ensure_within_rejects_symlink_escape(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    (root / "link").symlink_to(tmp_path, target_is_directory=True)

    with pytest.raises(UnsafePathError):
        ensure_within(root, root / "link" / "file")


def test_install_moves_checkout_into_place_and_replaces_previous(
    storage: RepositoryStorage,
) -> None:
    repository_id = uuid.uuid4()
    first = storage.create_temp_dir(repository_id)
    first.mkdir()
    (first / "v1.txt").write_text("one")
    storage.install(repository_id, first)

    second = storage.create_temp_dir(repository_id)
    second.mkdir()
    (second / "v2.txt").write_text("two")
    final = storage.install(repository_id, second)

    assert final == storage.path_for(repository_id)
    assert sorted(p.name for p in final.iterdir()) == ["v2.txt"]
    assert not first.exists() and not second.exists()


def test_install_refuses_checkouts_outside_temp_dir(
    storage: RepositoryStorage, tmp_path: Path
) -> None:
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()

    with pytest.raises(UnsafePathError):
        storage.install(uuid.uuid4(), elsewhere)


def test_remove_deletes_checkout(storage: RepositoryStorage) -> None:
    repository_id = uuid.uuid4()
    checkout = storage.create_temp_dir(repository_id)
    (checkout / "nested").mkdir(parents=True)
    (checkout / "nested" / "file.txt").write_text("x")
    storage.install(repository_id, checkout)

    assert storage.remove(repository_id) is True
    assert not storage.path_for(repository_id).exists()
    assert storage.remove(repository_id) is False


def test_remove_does_not_follow_symlinked_checkout(
    storage: RepositoryStorage, tmp_path: Path
) -> None:
    precious = tmp_path / "precious"
    precious.mkdir()
    (precious / "keep.txt").write_text("keep")
    repository_id = uuid.uuid4()
    storage.root.mkdir(parents=True)
    storage.path_for(repository_id).symlink_to(precious, target_is_directory=True)

    # The link resolves outside the root, so deletion is refused outright.
    with pytest.raises(UnsafePathError):
        storage.remove(repository_id)
    assert (precious / "keep.txt").exists()


def test_clear_temp_removes_leftover_clones(storage: RepositoryStorage) -> None:
    leftover = storage.create_temp_dir(uuid.uuid4())
    leftover.mkdir()

    storage.clear_temp()

    assert not storage.temp_root.exists()


def test_directory_size_counts_regular_files_only(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_bytes(b"12345")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b.txt").write_bytes(b"123")
    big = tmp_path.parent / f"{tmp_path.name}-big.bin"
    big.write_bytes(b"x" * 10_000)
    (tmp_path / "link").symlink_to(big)

    assert directory_size_bytes(tmp_path) == 8
