"""Which files this tool reads: regular files only, symlinks never followed (#74).

Every name `os.walk` lists under `files` used to be opened and hashed, and that
includes character and block devices, FIFOs, sockets and symlinks. A copy of
`/dev/random` never reaches end of file, so a worker read it for 36 hours; a
FIFO blocks `open()` until a writer appears, so that worker never returned at
all. A root backup made with `rsync -a` recreates both, so any backup volume
can hold them.

The rule is the owner's: **only regular files are read or recorded, and a
symlink is never followed** -- a symlink is skipped like any other entry that
is not a regular file, whatever it points at. Nothing else belongs in the
database.

A skip is not a failure, because nothing that should have been recorded was
missed. It is not silent either: every skipped path is logged, and the totals
are counted by kind so that the run's summary can report them.

This module is the one definition of that rule. Each walk goes through
`walk_regular_files`, and every hash goes through `require_regular_file` (in
`compute_md5`, which also re-checks the open descriptor, so a file replaced
between the check and the `open()` is still refused).
"""

import logging
import os
import stat
import threading
from collections import Counter
from collections.abc import Iterator


def file_kind(mode: int) -> str:
    """Name the type of a file from its `st_mode`, for logs and summaries."""
    if stat.S_ISREG(mode):
        return "regular file"
    if stat.S_ISLNK(mode):
        return "symlink"
    if stat.S_ISDIR(mode):
        return "directory"
    if stat.S_ISCHR(mode):
        return "char device"
    if stat.S_ISBLK(mode):
        return "block device"
    if stat.S_ISFIFO(mode):
        return "fifo"
    if stat.S_ISSOCK(mode):
        return "socket"
    return "other"


class NotARegularFile(Exception):
    """Raised instead of opening a path that is not a regular file.

    Callers that count skips catch this separately from other exceptions: it
    is a decision not to read the path, not a failure to read it.
    """

    def __init__(self, path: str, kind: str) -> None:
        super().__init__(f"not a regular file ({kind}): {path}")
        self.path = path
        self.kind = kind


def require_regular_file(path: str) -> os.stat_result:
    """Return `os.lstat(path)`, or raise `NotARegularFile` if it is not one.

    `lstat`, not `stat`: a symlink is reported as a symlink and never followed.
    An `OSError` from `lstat` itself (a missing path, a directory that cannot be
    searched) propagates unchanged, because that is a failure to check and not
    a decision about the file.
    """
    st = os.lstat(path)
    if not stat.S_ISREG(st.st_mode):
        raise NotARegularFile(path, file_kind(st.st_mode))
    return st


class SkippedEntries:
    """Thread-safe count of the entries a run did not read, by kind."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.by_kind: Counter[str] = Counter()

    def record(self, path: str, kind: str) -> None:
        logging.info(f"NOT REGULAR ({kind}), skipped: {path}")
        with self._lock:
            self.by_kind[kind] += 1

    def summary_line(self) -> str | None:
        """One line for a run summary, or None when nothing was skipped."""
        with self._lock:
            if not self.by_kind:
                return None
            total = sum(self.by_kind.values())
            kinds = ", ".join(f"{kind} {n}" for kind, n in sorted(self.by_kind.items()))
        return f"skipped {total} not regular file(s), not read: {kinds}"


def walk_regular_files(top: str, skipped: SkippedEntries) -> Iterator[str]:
    """Yield every regular file under `top`, never following a symlink.

    Every other entry is passed to `skipped.record` -- including a symlink to a
    directory, which `os.walk` lists under `dirs` and does not descend into, so
    that it is counted rather than silently left out.

    A path whose `lstat` fails is still yielded. The walk cannot classify it,
    so the caller tries it and reports the error as a failure; dropping it
    here would turn "could not check" into "not there".
    """
    for root, dirs, files in os.walk(top):
        for name in dirs:
            path = os.path.join(root, name)
            if os.path.islink(path):
                skipped.record(path, "symlink")
        for name in files:
            path = os.path.join(root, name)
            try:
                st = os.lstat(path)
            except OSError:
                yield path
                continue
            if stat.S_ISREG(st.st_mode):
                yield path
            else:
                skipped.record(path, file_kind(st.st_mode))
