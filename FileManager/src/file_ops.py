import logging
import os
import stat
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from queue import Queue

from src.db import (
    store_file_info, check_for_duplicates, get_file_info, recorded_checksums,
)
from src.md5sum import compute_md5
from src.regular_files import (
    NotARegularFile, SkippedEntries, file_kind, require_regular_file,
    walk_regular_files,
)

# How many failed paths a summary prints before it gives a count instead. Every
# failure is logged individually regardless; this bounds only the final block,
# because a scan of millions of files on a failing disk should not bury the
# counts under its own error list.
MAX_FAILURES_LISTED = 20

# The most paths a scan's producer may hold queued ahead of its consumers (#67).
# The producer only reads metadata and the consumers hash contents, so on a
# baseline scan an unbounded queue grew to the whole tree -- about 0.63 GiB of
# path strings for 5.58M files -- before the first worker caught up. With a
# bound, `put()` blocks the producer instead, and memory follows the number of
# workers rather than the size of the tree.
#
# The bound is a memory budget, converted to a path count. A Queue limits
# items, not bytes, so the conversion uses the measured cost of one queued
# path: 122 bytes for a 67-character path, counting the str object and its
# deque slot (#67). A longer path costs about one byte more per character, so
# a tree of very long paths can go somewhat past the budget; it is a size to
# aim at, not a hard ceiling.
#
# Shutdown still works with the bound in place: the producer puts its one
# sentinel per worker after the last path, and the workers keep draining the
# queue until each has taken its sentinel, so those puts can block but always
# complete -- including when there are more workers than slots.
SCAN_QUEUE_MEMORY_BYTES = 8 * 1024 * 1024
BYTES_PER_QUEUED_PATH = 122
SCAN_QUEUE_MAXSIZE = SCAN_QUEUE_MEMORY_BYTES // BYTES_PER_QUEUED_PATH  # 68,759


class ScanTally:
    """What a scan did, and what it could not do.

    A scan used to report nothing but a stream of per-file log lines and exit 0,
    so a run that could not read part of the tree was indistinguishable from a
    complete one -- and the database looks the same whether a file was absent
    from the tree or merely unreadable (#57). Counting is therefore not
    presentation: it is the only record that a gap exists.

    Mutated from every consumer thread, so each update takes the lock. The
    counts are read only after the workers have been joined.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self.hashed = 0
        self.skipped = 0
        self.failed = 0
        self.failures = []
        # Entries that are not regular files: skipped, logged and counted by
        # kind (#74). Not a failure -- nothing that belongs in the index was
        # missed -- so they do not change the exit status.
        self.not_regular = SkippedEntries()

    def record_hashed(self):
        with self._lock:
            self.hashed += 1

    def record_skipped(self):
        with self._lock:
            self.skipped += 1

    def record_failure(self, path, error):
        """Note that `path` could not be read, and why."""
        with self._lock:
            self.failed += 1
            self.failures.append((path, str(error)))

    def record_not_regular(self, path, kind):
        self.not_regular.record(path, kind)

    def record_outcome(self, outcome):
        if outcome == 'skipped':
            self.record_skipped()
        else:
            self.record_hashed()

    @property
    def checked(self):
        return self.hashed + self.skipped

    def summary_lines(self):
        """The report a human or a log reader sees, newest fact last."""
        lines = [
            f"scan complete: {self.hashed} hashed, "
            f"{self.skipped} skipped unchanged, {self.failed} failed"
        ]
        not_regular = self.not_regular.summary_line()
        if not_regular:
            lines.append(not_regular)
        if self.failed:
            shown = self.failures[:MAX_FAILURES_LISTED]
            lines.append(f"failed ({self.failed}):")
            lines.extend(f"  {path}: {error}" for path, error in shown)
            remaining = self.failed - len(shown)
            if remaining:
                lines.append(
                    f"  ... and {remaining} more; every one is on an ERROR line "
                    f"in this run's log"
                )
        return lines


def scan(path, db_path, num_threads, tally=None):
    """Scan one directory or file, recording outcomes into `tally`.

    Returns:
        ScanTally: the tally passed in, or a fresh one. Callers must read
            `tally.failed` -- a scan that could not read part of the tree
            returns normally, and the exit status is the caller's job (#57).
    """
    tally = tally if tally is not None else ScanTally()
    # lstat, not isdir/isfile: those follow a symlink, and a symlink is never
    # followed (#74) -- not even one named on the command line.
    try:
        mode = os.lstat(path).st_mode
    except OSError:
        mode = None
    if mode is not None and stat.S_ISDIR(mode):
        scan_dir(path, db_path, num_threads, tally)
    elif mode is not None and stat.S_ISREG(mode):
        scan_file(path, db_path, tally)
    elif mode is None:
        # Not a warning. A path given on the command line that is neither a
        # file nor a directory means the scan did not cover what it was asked
        # to cover, which is the same kind of gap as an unreadable file.
        logging.error(f"Invalid path: {path}")
        tally.record_failure(path, "not a file or directory")
    else:
        # A failure, not a skip, for the same reason: the operator named this
        # path, and the scan did not cover it.
        kind = file_kind(mode)
        logging.error(f"Not scanned: {path} is a {kind}, not a regular file or directory")
        tally.record_failure(path, f"not a regular file or directory ({kind})")
    return tally


def _scan_one(file_path, db_path, tally):
    """Scan one path into `tally`: hashed, skipped, not regular, or failed."""
    try:
        tally.record_outcome(process_file(file_path, db_path))
    except NotARegularFile as e:
        tally.record_not_regular(e.path, e.kind)
    except Exception as e:
        logging.error(f"Error processing file {file_path}: {e}")
        tally.record_failure(file_path, e)


def scan_file(path, db_path, tally=None):
    tally = tally if tally is not None else ScanTally()
    _scan_one(path, db_path, tally)
    return tally

def scan_dir(path, db_path, num_threads, tally=None):
    tally = tally if tally is not None else ScanTally()
    file_queue = Queue(maxsize=SCAN_QUEUE_MAXSIZE)

    def producer():
        # Only regular files reach the queue; every other entry is counted
        # into the tally by the walk itself (#74).
        for file_path in walk_regular_files(path, tally.not_regular):
            file_queue.put(file_path)
            logging.debug(f"Found file: {file_path}")
        for _ in range(num_threads):
            file_queue.put("")  # Signal the consumers to stop

    def consumer():
        while True:
            file_path = file_queue.get()
            if file_path == "":
                logging.debug(f"Consumer {threading.current_thread().name} exiting")
                file_queue.task_done()  # Mark the stop signal as done
                # DO NOT DO THIS:  file_queue.put("")  # Signal the next consumer to stop
                break
            try:
                _scan_one(file_path, db_path, tally)
            finally:
                file_queue.task_done()

    producer_thread = threading.Thread(target=producer)
    producer_thread.start()

    with ThreadPoolExecutor(max_workers=num_threads) as executor:
        for _ in range(num_threads):
            executor.submit(consumer)

    producer_thread.join()
    logging.debug(f"Items remaining in queue: {file_queue.qsize()}")
    file_queue.join()
    logging.debug("All tasks completed.")
    return tally


def process_file(file_path, db_path):
    """Record one regular file, hashing it only if (size, mtime) changed.

    Raises `NotARegularFile` for anything else (#74). The check comes first,
    before the skip check: a symlink recorded by an older version would
    otherwise match its stored (size, mtime) through the link and be reported
    as 'skipped' rather than refused.
    """
    require_regular_file(file_path)
    size = os.path.getsize(file_path)
    last_modified = int(os.path.getmtime(file_path) * 1000)  # Multiply by 1000 and convert to integer
    file_info = get_file_info(db_path, file_path)

    if file_info:
        db_size, db_last_modified = file_info
        db_last_modified = int(float(db_last_modified))  # Convert to integer for comparison
        if db_size == size and db_last_modified == last_modified:
            logging.debug(f"SKIPPED: {file_path} ")
            print(".", end="", flush=True)
            return 'skipped'

    start_time = time.time()
    md5sum = compute_md5(file_path)
    end_time = time.time()
    duration_ms = int((end_time - start_time) * 1000)

    store_file_info(db_path, file_path, md5sum)
    logging.info(f"PROCESSED: {file_path}")
    return 'hashed'


def process_files_concurrently(file_paths, db_path, num_threads, tally=None):
    tally = tally if tally is not None else ScanTally()
    with ThreadPoolExecutor(max_workers=num_threads) as executor:
        futures = {executor.submit(process_file, file_path, db_path): file_path for file_path in file_paths}
        for future in as_completed(futures):
            file_path = futures[future]
            try:
                tally.record_outcome(future.result())
            except NotARegularFile as e:
                tally.record_not_regular(e.path, e.kind)
            except Exception as e:
                logging.error(f"Error processing file {file_path}: {e}")
                tally.record_failure(file_path, e)
    return tally


def check_file(path, db_path):
    """Print every recorded path sharing `path`'s checksum.

    Returns:
        bool: False if `path` is not a regular file and was not read (#74),
            True otherwise.
    """
    try:
        md5sum = compute_md5(path)
    except NotARegularFile as e:
        logging.error(f"Not checked: {e}")
        return False
    duplicates = check_for_duplicates(db_path, md5sum)
    if duplicates:
        logging.info(f"Duplicate found for {path}")
        print(f"Duplicate found for {path}:")
        for duplicate in duplicates:
            print(duplicate[0])
            logging.info(f"Duplicate: {duplicate[0]}")
    return True


# Record removal lives in src/db.py: `remove_record_by_path` for one exact path,
# `remove_records_by_regex` for a pattern matched against the whole path. Two
# thin wrappers used to sit here whose only job was to print the count, and one
# of them was called `remove_record` -- the same name as db.py's exact-path
# function, but with regex behaviour (#7). main.py prints the count now.


class VerifyTally:
    """What a verify found: matches, mismatches, and files it could not read.

    Three outcomes, never two (#50). A file that could not be read is **not a
    pass**: the stored checksum is still unverified, and calling that "fine"
    recreates the exact failure the ticket is about. Same reasoning as
    `UniquenessUnknown` (#41) and the scan's failed count (#57).

    `mismatches` holds (path, stored, actual) so the report names both
    checksums. The stored row is **never** overwritten -- a verify that
    rewrote the baseline on a mismatch would destroy the evidence and pass
    the second time it ran, which is worse than not verifying at all.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self.matched = 0
        self.mismatched = 0
        self.unreadable = 0
        self.mismatches = []
        self.failures = []

    def record_match(self):
        with self._lock:
            self.matched += 1

    def record_mismatch(self, path, stored, actual):
        with self._lock:
            self.mismatched += 1
            self.mismatches.append((path, stored, actual))

    def record_unreadable(self, path, error):
        with self._lock:
            self.unreadable += 1
            self.failures.append((path, str(error)))

    @property
    def checked(self):
        return self.matched + self.mismatched + self.unreadable

    def summary_lines(self):
        """The report, for stdout. Mismatches first: they are the finding."""
        lines = [
            f"verify complete: checked {self.checked}, "
            f"{self.matched} matched, {self.mismatched} MISMATCHED, "
            f"{self.unreadable} unreadable"
        ]
        if self.mismatches:
            lines.append(f"MISMATCHED ({self.mismatched}):")
            for path, stored, actual in self.mismatches[:MAX_FAILURES_LISTED]:
                lines.append(f"  {path}")
                lines.append(f"    stored {stored}")
                lines.append(f"    actual {actual}")
            if self.mismatched > MAX_FAILURES_LISTED:
                lines.append(
                    f"  ... and {self.mismatched - MAX_FAILURES_LISTED} more; "
                    f"each is on an ERROR line in the log"
                )
        if self.failures:
            lines.append(f"unreadable ({self.unreadable}):")
            for path, message in self.failures[:MAX_FAILURES_LISTED]:
                lines.append(f"  {path}: {message}")
            if self.unreadable > MAX_FAILURES_LISTED:
                lines.append(
                    f"  ... and {self.unreadable - MAX_FAILURES_LISTED} more; "
                    f"each is on an ERROR line in the log"
                )
        return lines


def verify_one_recording(path, stored_md5, tally):
    """Rehash one recorded file and compare with what the database holds.

    Unconditional: no (size, mtime) shortcut, because that shortcut is the
    whole defect in #50. Bit rot, a bad sector and a failing cable all rewrite
    bytes without touching either, so the files whose contents are in question
    are exactly the ones a metadata comparison skips.
    """
    try:
        actual = compute_md5(path)
    except NotARegularFile as e:
        # Never opened. The row should not be in the database at all (#74), but
        # verify never writes, so it is reported as not verified -- which is
        # what it is -- and audit-db is named as the action that removes it.
        message = f"not a regular file ({e.kind}); audit-db removes the row"
        logging.error(f"VERIFY unreadable {path}: {message}")
        tally.record_unreadable(path, message)
        return 'unreadable'
    except Exception as e:
        logging.error(f"VERIFY unreadable {path}: {e}")
        tally.record_unreadable(path, e)
        return 'unreadable'

    if actual == stored_md5:
        tally.record_match()
        return 'matched'

    logging.error(
        f"VERIFY MISMATCH {path}: stored {stored_md5}, actual {actual}"
    )
    tally.record_mismatch(path, stored_md5, actual)
    return 'mismatched'


def verify_db(db_path, num_threads=4, prefix=None, tally=None):
    """Rehash recorded files and compare against the stored checksums (#50).

    Read-only with respect to the database. Nothing is updated, removed or
    rewritten: the stored checksum is the baseline being tested, and a verify
    that "repaired" it would be a no-op on its second run and would have
    destroyed the only evidence of corruption on its first.

    Args:
        db_path (str): The path to the database file.
        num_threads (int): Width of the hashing pool.
        prefix (str, optional): Verify only recorded paths under this prefix.
            Verifying everything takes hours at the sizes this is used on, so
            scoping is how a run is made to fit (#50).
        tally (VerifyTally, optional): Accumulate into an existing tally.

    Returns:
        VerifyTally: the counts and the findings.
    """
    tally = VerifyTally() if tally is None else tally
    rows = recorded_checksums(db_path, prefix)

    logging.info(
        f"VERIFY {len(rows)} recorded path(s)"
        + (f" under {prefix}" if prefix else "")
    )

    with ThreadPoolExecutor(max_workers=num_threads) as executor:
        futures = {
            executor.submit(verify_one_recording, path, stored, tally): path
            for path, stored in rows
        }
        for future in as_completed(futures):
            path = futures[future]
            try:
                future.result()
            except Exception as e:
                # verify_one_recording catches read errors itself, so reaching
                # here means something else broke -- it is still not a pass.
                logging.error(f"VERIFY failed {path}: {e}")
                tally.record_unreadable(path, e)

    return tally
