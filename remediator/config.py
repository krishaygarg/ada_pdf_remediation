"""Workspace configuration for the remediator package.

Importing this module has no side effects. Callers that need a scratch
directory ask for one explicitly via :func:`ensure_tmp_dir`, and callers that
need third-party libraries to spill temporary files inside the workspace opt in
via :func:`configure_workspace_tmp`.

Keeping import free of side effects matters because ``import remediator``
happens during test collection, documentation builds and IDE autocompletion,
none of which should create directories or mutate the process environment.
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

#: Root of the checked-out workspace (the directory containing ``remediator/``).
WORKSPACE_DIR: Path = Path(__file__).resolve().parent.parent

#: Environment variable used to relocate the scratch directory.
TMP_DIR_ENV_VAR = "ADA_REMEDIATOR_TMP"

#: Default scratch directory. The path is computed on import but never created;
#: call :func:`ensure_tmp_dir` to materialise it.
LOCAL_TMP: str = os.environ.get(TMP_DIR_ENV_VAR) or str(WORKSPACE_DIR / "tmp")

_TMP_ENV_KEYS = ("TMPDIR", "TEMP", "TMP")


def get_tmp_dir() -> Path:
    """Return the configured scratch directory without creating it."""
    return Path(os.environ.get(TMP_DIR_ENV_VAR) or LOCAL_TMP)


def ensure_tmp_dir() -> Path:
    """Return the scratch directory, creating it if it does not yet exist."""
    path = get_tmp_dir()
    path.mkdir(parents=True, exist_ok=True)
    return path


@contextmanager
def configure_workspace_tmp() -> Iterator[Path]:
    """Point ``tempfile`` and the ``TMPDIR`` family at the workspace scratch dir.

    Some dependencies (notably ``pdf2image``, which shells out to Poppler) write
    intermediate files to the system temporary directory. Sandboxed and
    containerised deployments may not permit that, so entry points wrap their
    work in this context manager. The previous environment is restored on exit,
    which keeps the process-wide mutation scoped to the call that asked for it.
    """
    path = ensure_tmp_dir()
    previous_env = {key: os.environ.get(key) for key in _TMP_ENV_KEYS}
    previous_tempdir = tempfile.tempdir
    for key in _TMP_ENV_KEYS:
        os.environ[key] = str(path)
    tempfile.tempdir = str(path)
    try:
        yield path
    finally:
        for key, value in previous_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        tempfile.tempdir = previous_tempdir


__all__ = [
    "LOCAL_TMP",
    "TMP_DIR_ENV_VAR",
    "WORKSPACE_DIR",
    "configure_workspace_tmp",
    "ensure_tmp_dir",
    "get_tmp_dir",
]
