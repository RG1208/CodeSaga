"""On-disk storage for cloned repositories.

Layout under the storage root:

    <root>/<repository-uuid>/          current checkout of a repository
    <root>/.tmp/<repository-uuid>-<random>/   in-progress clone (renamed into place on success)

Directory names are always derived from the repository's UUID, never from user
input, and every path is checked to stay inside the root before it is created,
replaced or deleted.
"""

import os
import shutil
import stat
import uuid
from pathlib import Path

from app.ingestion.errors import UnsafePathError

_TEMP_DIR_NAME = ".tmp"


def ensure_within(root: Path, candidate: Path) -> Path:
    """Resolve `candidate` and guarantee it is `root` or lies inside it."""
    resolved_root = root.resolve()
    resolved = candidate.resolve()
    if resolved != resolved_root and not resolved.is_relative_to(resolved_root):
        raise UnsafePathError(f"Path escapes the storage directory: {candidate}")
    return resolved


def _make_writable_and_retry(function, path, _exc) -> None:  # type: ignore[no-untyped-def]
    # Git marks object files read-only; on Windows rmtree needs them writable.
    os.chmod(path, stat.S_IWRITE)
    function(path)


class RepositoryStorage:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    @property
    def temp_root(self) -> Path:
        return self.root / _TEMP_DIR_NAME

    def path_for(self, repository_id: uuid.UUID) -> Path:
        if not isinstance(repository_id, uuid.UUID):
            raise UnsafePathError("Repository storage paths must be derived from a UUID.")
        return ensure_within(self.root, self.root / str(repository_id))

    def create_temp_dir(self, repository_id: uuid.UUID) -> Path:
        """A fresh, empty-parent location for a clone (git creates the leaf directory)."""
        self.temp_root.mkdir(parents=True, exist_ok=True)
        name = f"{self.path_for(repository_id).name}-{uuid.uuid4().hex}"
        return ensure_within(self.temp_root, self.temp_root / name)

    def install(self, repository_id: uuid.UUID, checkout: Path) -> Path:
        """Move a completed checkout into place, replacing any previous one."""
        source = ensure_within(self.temp_root, checkout)
        destination = self.path_for(repository_id)
        if destination.exists():
            self._remove_tree(destination)
        source.rename(destination)
        return destination

    def remove(self, repository_id: uuid.UUID) -> bool:
        """Delete a repository's checkout. Returns False if there was nothing to delete."""
        path = self.path_for(repository_id)
        if not path.exists():
            return False
        self._remove_tree(path)
        return True

    def discard(self, path: Path) -> None:
        """Delete a temporary checkout (no-op if it does not exist)."""
        target = ensure_within(self.temp_root, path)
        if target.exists():
            self._remove_tree(target)

    def clear_temp(self) -> None:
        if self.temp_root.exists():
            self._remove_tree(self.temp_root)

    def _remove_tree(self, path: Path) -> None:
        target = ensure_within(self.root, path)
        if target == self.root:
            raise UnsafePathError("Refusing to delete the storage root itself.")
        if target.is_symlink():
            target.unlink()
            return
        shutil.rmtree(target, onexc=_make_writable_and_retry)


def directory_size_bytes(path: Path) -> int:
    """Total size of regular files under `path`, without following symlinks."""
    total = 0
    for dirpath, _dirnames, filenames in os.walk(path, followlinks=False):
        for filename in filenames:
            try:
                info = os.lstat(os.path.join(dirpath, filename))
            except OSError:
                continue
            if stat.S_ISREG(info.st_mode):
                total += info.st_size
    return total
