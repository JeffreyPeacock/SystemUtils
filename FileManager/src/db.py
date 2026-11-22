# src/db.py
import logging
import os
import re
import sqlite3
import stat
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import TypedDict

from src.md5sum import compute_md5
from src.regular_files import (
    NotARegularFile, SkippedEntries, file_kind, require_regular_file,
    walk_regular_files,
)
from src.utils import get_file_mtime_in_ms

MAX_RETRIES = 10  # Define a global variable for the number of retries
RETRY_DELAY = 0.1  # Delay between retries in seconds

# Statuses written to the .processed_files.txt resume log. Only the first two
# are verdicts; UNREADABLE records that the question could not be answered, and
# is deliberately NOT treated as processed on a later run.
STATUS_UNIQUE = "unique"
STATUS_NOT_UNIQUE = "not_unique"
STATUS_UNREADABLE = "unreadable"
VERDICT_STATUSES = frozenset({STATUS_UNIQUE, STATUS_NOT_UNIQUE})


class UniquenessUnknown(Exception):
    """The file's uniqueness could not be determined.

    Raised rather than returned because there is no safe value to return. This
    function used to answer False here, and False means "not unique" -- the same
    answer as a file that genuinely has a copy elsewhere, which is how a file
    whose only fault was an I/O error ended up excluded from the keep list (#41).

    A sentinel return would be no better: `None` is falsy, so any caller writing
    `if is_file_unique(...)` would silently reproduce the same wrong answer.
    Raising makes the third outcome impossible to ignore by accident.
    """


def with_connection(db_path, work, *, commit=False, description="query"):
    """Open `db_path`, run `work(conn)`, close it, retrying while SQLite is locked.

    This is the only place in the project that calls `sqlite3.connect`, which is
    what #10 is about. Before it, the retry loop was copied into each writer and
    the readers had none at all -- so a report run alongside a scan raised
    `database is locked` instead of waiting, and any change to connection
    handling (a pragma, a timeout, a pool) had to be made in ten places or it
    was only half applied.

    Only "database is locked" is retried. Every other OperationalError is
    re-raised untouched: retrying a malformed statement ten times just delays
    the error by a second.

    Args:
        db_path (str): The path to the database file.
        work (callable): Given the open connection; its return value is returned.
            It must not return a cursor or any other lazy handle -- the
            connection is closed before this function returns.
        commit (bool): Commit before closing. Writers pass True.
        description (str): Named in the log line and in the final error.

    Returns:
        Whatever `work` returned.

    Raises:
        sqlite3.OperationalError: after MAX_RETRIES attempts all found the
            database locked.
    """
    last_error = None
    for attempt in range(1, MAX_RETRIES + 1):
        conn = None
        try:
            conn = sqlite3.connect(db_path)
            result = work(conn)
            if commit:
                conn.commit()
            return result
        except sqlite3.OperationalError as e:
            if "database is locked" not in str(e):
                raise
            last_error = e
            logging.warning(
                f"Database is locked, retrying {description}... "
                f"({attempt}/{MAX_RETRIES})"
            )
            time.sleep(RETRY_DELAY)
        finally:
            if conn is not None:
                conn.close()
    raise sqlite3.OperationalError(
        f"Failed to {description} after {MAX_RETRIES} retries due to database "
        f"lock: {last_error}"
    )


def _read_all(db_path, sql, params=(), *, description="read"):
    """Every row of one read query, through `with_connection`."""
    def work(conn):
        return conn.execute(sql, params).fetchall()
    return with_connection(db_path, work, description=description)


def initialize_db(db_path):
    """
    Initialize the database by creating the necessary tables if they do not exist.

    Args:
        db_path (str): The path to the database file.
    """
    def work(conn):
        conn.execute('''
            CREATE TABLE IF NOT EXISTS files (
                id INTEGER PRIMARY KEY,
                md5sum TEXT,
                size INTEGER,
                last_modified INTEGER,
                path TEXT UNIQUE
            )
        ''')
    with_connection(db_path, work, commit=True, description="initialize the database")

def get_file_info(db_path, file_path):
    """
    Retrieve the size and last modified time of a file from the database.

    Args:
        db_path (str): The path to the database file.
        file_path (str): The path to the file.

    Returns:
        tuple: A tuple containing the size and last modified time of the file, or None if the file is not found.
    """
    rows = _read_all(
        db_path,
        "SELECT size, last_modified FROM files WHERE path = ?",
        (file_path,),
        description="read file info",
    )
    return rows[0] if rows else None

def get_all_files_info(db_path):
    """
    Retrieve all file information from the database.

    Args:
        db_path (str): The path to the database file.

    Returns:
        list: A list of tuples, each containing the file path, size, and last modified time.
    """
    return _read_all(
        db_path,
        "SELECT path, size, last_modified FROM files",
        description="read all file info",
    )

# How many rows `iter_recorded_checksums` reads per query (#68). At the measured
# ~253 bytes per (path, md5sum) row, a page is about 2.5 MB. Large enough that
# the per-query cost is small beside hashing the files, small enough that memory
# follows the page and not the database.
VERIFY_PAGE_SIZE = 10_000


def recorded_checksums_page(db_path, prefix=None, after=None,
                            limit=VERIFY_PAGE_SIZE):
    """At most `limit` (path, md5sum) rows ordered by path, after `after`.

    The read side of #50. `audit_db` and `scan` both decide what to do from
    (size, mtime) and never look at the stored checksum, so this is the only
    query that returns it in bulk -- verifying it is the one job a stored
    checksum exists for.

    One page per call, through `with_connection`, so no cursor outlives its
    connection (#68). Keyset pagination: the next page starts after the last
    path of this one. `path` is UNIQUE and the order is by path, so the pages
    neither overlap nor skip a row, and a row inserted while the pages are read
    is either in a later page or before the current position -- never read
    twice. OFFSET was not used: it rereads every earlier row for each page.

    Ordered by path so a prefix-scoped run covers a predictable subtree and two
    runs over the same prefix read in the same order.

    Args:
        db_path (str): The path to the database file.
        prefix (str, optional): Only rows whose path starts with this. The
            database may hold millions of rows across several volumes, and
            verifying all of them takes hours (#50).
        after (str, optional): Only rows whose path sorts after this one.
            None starts at the beginning.
        limit (int): The most rows to return.

    Returns:
        list: up to `limit` (path, md5sum) tuples, ordered by path. Fewer than
        `limit` means this was the last page.
    """
    where, params = [], []
    if prefix:
        where.append("path LIKE ?")
        params.append(f"{prefix}%")
    if after is not None:
        where.append("path > ?")
        params.append(after)
    clause = f" WHERE {' AND '.join(where)}" if where else " WHERE path IS NOT NULL"
    return _read_all(
        db_path,
        f"SELECT path, md5sum FROM files{clause} ORDER BY path LIMIT ?",
        (*params, limit),
        description="read a page of recorded checksums",
    )


def iter_recorded_checksums(db_path, prefix=None, page_size=VERIFY_PAGE_SIZE):
    """Every (path, md5sum) the database holds, one page in memory at a time.

    A generator, but not a lazy handle: each page is a complete
    `recorded_checksums_page` call, so the connection is closed before any row
    is yielded, and no connection is open between pages (#68). Before #68 the
    whole result set was read into one list -- about 1.31 GiB for /home2 --
    before the first file was hashed.

    A row with a NULL path cannot be paged by path, so those rows are read first
    in one query of their own. Nothing in this program writes one, but the
    schema allows it, and before #68 verify-db reported such a row as
    unreadable. Dropping it without a word would turn "could not check" into
    nothing at all. A prefix excludes them, as `LIKE` always did.

    Args:
        db_path (str): The path to the database file.
        prefix (str, optional): Only rows whose path starts with this.
        page_size (int): Rows per query.

    Yields:
        (path, md5sum) tuples, ordered by path after any NULL-path rows.
    """
    if not prefix:
        yield from _read_all(
            db_path,
            "SELECT path, md5sum FROM files WHERE path IS NULL",
            description="read recorded checksums with no path",
        )
    after = None
    while True:
        page = recorded_checksums_page(db_path, prefix, after, page_size)
        yield from page
        if len(page) < page_size:
            return
        after = page[-1][0]


def store_file_info(db_path, path, md5sum):
    """
    Store or update the information of a file in the database.

    Args:
        db_path (str): The path to the database file.
        path (str): The path to the file.
        md5sum (str): The MD5 checksum of the file.
    """
    size = os.path.getsize(path)
    last_modified = get_file_mtime_in_ms(path)  # Use the utility function
    def work(conn):
        conn.execute('''
            INSERT INTO files (path, md5sum, size, last_modified) VALUES (?, ?, ?, ?)
            ON CONFLICT(path) DO UPDATE SET md5sum=excluded.md5sum, size=excluded.size, last_modified=excluded.last_modified
        ''', (path, md5sum, size, last_modified))

    with_connection(db_path, work, commit=True,
                    description=f"store file info for {path}")

def remove_record_by_path(db_path, file_path):
    """
    Remove the record for exactly this path. Not a pattern.

    Named for what it does. It was `remove_record`, which is also what the
    regex-based removal in file_ops.py was called, so a reader grepping the
    name found the wrong definition about half the time (#7).

    Args:
        db_path (str): The path to the database file.
        file_path (str): The path to the file.

    Returns:
        int: The number of records deleted -- 0 or 1, since path is UNIQUE.
    """
    def work(conn):
        return conn.execute("DELETE FROM files WHERE path = ?", (file_path,)).rowcount

    return with_connection(db_path, work, commit=True,
                           description=f"remove the record for {file_path}")


def remove_records_by_regex(db_path, regex_pattern):
    """
    Remove records whose path matches the regex pattern, in full.

    The match is `re.fullmatch`, so the pattern must describe the WHOLE path.
    This used to be `re.match`, which anchors at the start of the string but
    not at the end -- so the literal path `/a/b` also deleted `/a/bc` and
    everything under `/a/b-old/`, silently (#1). To delete a subtree, say so
    explicitly: `/a/b/.*`.

    Args:
        db_path (str): The path to the database file.
        regex_pattern (str): The regex pattern to match file paths.

    Returns:
        int: The number of records deleted.
    """
    def work(conn):
        all_paths = conn.execute("SELECT path FROM files").fetchall()
        matching_paths = [path[0] for path in all_paths
                          if re.fullmatch(regex_pattern, path[0])]
        if matching_paths:
            conn.executemany("DELETE FROM files WHERE path = ?",
                             [(path,) for path in matching_paths])
        return len(matching_paths)

    return with_connection(db_path, work, commit=True,
                           description=f"remove records matching '{regex_pattern}'")
def get_md5_by_path(db_path, file_path):
    """
    Retrieve the MD5 checksum of a file from the database.

    Args:
        db_path (str): The path to the database file.
        file_path (str): The path to the file.

    Returns:
        str: The MD5 checksum of the file, or None if the file is not found.
    """
    rows = _read_all(
        db_path,
        "SELECT md5sum FROM files WHERE path = ?",
        (file_path,),
        description="read a checksum",
    )
    return rows[0][0] if rows else None

def check_for_duplicates(db_path, md5sum):
    """
    Check for duplicate files in the database based on the MD5 checksum.

    Args:
        db_path (str): The path to the database file.
        md5sum (str): The MD5 checksum to check for duplicates.

    Returns:
        list: A list of file paths that have the same MD5 checksum.
    """
    return _read_all(
        db_path,
        "SELECT path FROM files WHERE md5sum = ?",
        (md5sum,),
        description="check for duplicates",
    )

def find_duplicates_with_min_count(db_path, min_count=2):
    """
    Find checksums held by at least `min_count` files.

    `min_count` counts COPIES, not copies beyond the first: 2 means "a file and
    at least one other like it", which is the smallest thing worth calling a
    duplicate. The default is therefore 2, and it reports what the old default
    of 1 reported, because the comparison used to be `>` (#6). Under that,
    `--min-duplicates 3` returned groups of four -- the flag was off by one at
    every value except where the two readings happen to coincide.

    Args:
        db_path (str): The path to the database file.
        min_count (int): The minimum number of files sharing a checksum.

    Returns:
        dict: keys are MD5 checksums, values are lists of paths sharing it.
    """
    # One row per (checksum, path), rather than GROUP_CONCAT joined server-side.
    #
    # This used to select GROUP_CONCAT(path) and split the result on ",". A
    # comma is legal in a filename and common in a media library -- this tool's
    # stated use case -- so any such path was torn into fragments: the group
    # reported names that do not exist and omitted the real one (#5). SQLite
    # offers no way to escape the separator, and no delimiter is safe against
    # arbitrary paths, so the grouping is done in Python instead.
    rows = _read_all(
        db_path,
        '''
        SELECT md5sum, path FROM files
        WHERE md5sum IN (
            SELECT md5sum FROM files
            GROUP BY md5sum HAVING COUNT(*) >= ?
        )
        ORDER BY md5sum
        ''',
        (min_count,),
        description="find duplicates",
    )

    duplicates: dict[str, list[str]] = {}
    for md5sum, path in rows:
        duplicates.setdefault(md5sum, []).append(path)
    return duplicates


def count_duplicates_per_path(db_path):
    """(path, count) for every path whose checksum is shared with another file.

    Args:
        db_path (str): The path to the database file.

    Returns:
        list: (path, duplicate_count) tuples.
    """
    return _read_all(
        db_path,
        '''
        SELECT path, COUNT(*) as duplicate_count FROM files
        WHERE md5sum IN (
            SELECT md5sum FROM files
            GROUP BY md5sum HAVING COUNT(*) > 1
        )
        GROUP BY path
        ''',
        description="count duplicates per path",
    )


def duplicate_group_sizes(db_path):
    """One (size, count) row per duplicated checksum.

    MIN(size) rather than size: files sharing an MD5 have the same length, so
    the aggregate picks the one value the group has.

    Args:
        db_path (str): The path to the database file.

    Returns:
        list: (size, count) tuples, one per checksum held by two or more files.
    """
    return _read_all(
        db_path,
        '''
        SELECT MIN(size), COUNT(*) FROM files
        GROUP BY md5sum HAVING COUNT(*) > 1
        ''',
        description="read duplicate group sizes",
    )


def count_paths_with_prefix(db_path, prefix):
    """How many recorded paths start with `prefix`.

    Args:
        db_path (str): The path to the database file.
        prefix (str): The leading portion of the path to match.

    Returns:
        int: The number of matching rows.
    """
    rows = _read_all(
        db_path,
        "SELECT COUNT(*) FROM files WHERE path LIKE ?",
        (f"{prefix}%",),
        description="count paths with a prefix",
    )
    return rows[0][0]


def list_paths_with_prefix(db_path, prefix):
    """Every recorded path starting with `prefix`.

    Args:
        db_path (str): The path to the database file.
        prefix (str): The leading portion of the path to match.

    Returns:
        list: The matching paths.
    """
    rows = _read_all(
        db_path,
        "SELECT path FROM files WHERE path LIKE ?",
        (f"{prefix}%",),
        description="list paths with a prefix",
    )
    return [row[0] for row in rows]


def find_duplicates_under_prefix(db_path, prefix):
    """Checksums held by more than one path, restricted to paths under `prefix`.

    The grouping is done here rather than in SQL for the same reason as
    `find_duplicates_with_min_count`: a comma is legal in a filename, so
    GROUP_CONCAT cannot be split back apart safely (#5).

    Args:
        db_path (str): The path to the database file.
        prefix (str): The leading portion of the path to match.

    Returns:
        dict: keys are MD5 checksums, values are lists of paths sharing it.
    """
    rows = _read_all(
        db_path,
        "SELECT md5sum, path FROM files WHERE path LIKE ?",
        (f"{prefix}%",),
        description="find duplicates under a prefix",
    )
    md5_to_paths: dict[str, list[str]] = {}
    for md5sum, path in rows:
        md5_to_paths.setdefault(md5sum, []).append(path)
    return {md5sum: paths for md5sum, paths in md5_to_paths.items() if len(paths) > 1}


def looks_like_a_missing_volume(file_path):
    """True when this path is absent AND so is the directory that held it.

    Distinguishes the two ways a recorded path can stop existing:

      a deleted FILE       leaves its parent directory in place
      a missing VOLUME     takes the whole tree with it

    That difference is the only signal available without recording mount points
    at scan time, and it is a reliable one: `rm foo.txt` cannot remove the
    directory `foo.txt` lived in, whereas a volume that failed to mount leaves
    nothing beneath its mount point. Treating the second case as "the file was
    deleted" is what empties thousands of rows in one pass (#2).
    """
    parent = os.path.dirname(file_path)
    return not os.path.exists(file_path) and not os.path.isdir(parent)


class AuditCounts(TypedDict):
    """What an audit did, and what it could not read.

    A TypedDict rather than `dict[str, Any]` (#60) because the values are
    genuinely heterogeneous -- six counters and a list of failures -- and `Any`
    switches off checking for every caller rather than describing the shape.
    `src/main.py` is not on the `check_untyped_defs` opt-out list, so it only
    typechecked before this because `audit_db` returned `Any` out of an
    unchecked module: a precise type here is what lets the caller be checked at
    all.

    **`failed` is the field a caller must read.** An audit that could not read
    part of the tree returns normally; turning that into an exit status is the
    caller's job (#57).
    """

    checked: int
    removed: int
    reprocessed: int
    skipped: int
    suspect: int
    not_regular: int
    failed: int
    failures: list[tuple[str, str]]


def audit_db(db_path, num_threads, process_file, exclude_prefix=None,
             dry_run=False, prune_missing_dirs=False):
    """
    Audit the database for file changes and reprocess files if necessary.

    Args:
        db_path (str): The path to the database file.
        num_threads (int): The number of threads to use for concurrent operations.
        process_file (function): The function to process a file.
        exclude_prefix (list, optional): A list of prefixes to exclude paths from processing.
        dry_run (bool): Report what would change and modify nothing.
        prune_missing_dirs (bool): Also remove rows whose parent directory is
            gone. Off by default -- see `looks_like_a_missing_volume`.

    Returns:
        AuditCounts: counts keyed 'removed', 'reprocessed', 'skipped',
            'suspect', 'not_regular', 'checked', 'failed', plus 'failures' as
            a list of (path, message). 'not_regular' counts rows removed
            because the path is no longer a regular file (#74); they are not
            also counted in 'removed'.
            On a dry run 'removed' and 'reprocessed' are what *would* have
            happened. **The caller must read 'failed'** -- an audit that could
            not read part of the tree returns normally, and turning that into an
            exit status is the caller's job (#57).
    """
    batch_size = 100
    processed_files_count = 0
    # Every key is declared, including 'failures', so the literal satisfies a
    # total TypedDict rather than being filled in later and typed `Any` to hide
    # the gap. #57 added 'failures' to a dict mypy had inferred as
    # dict[str, int]; the error went unreported because `src.db` was on the
    # check_untyped_defs opt-out list, which is how an opt-out comes to hide a
    # new fault instead of a known one (#60, #61).
    counts: AuditCounts = {'removed': 0, 'reprocessed': 0, 'skipped': 0,
                           'suspect': 0, 'not_regular': 0, 'checked': 0,
                           'failed': 0, 'failures': []}
    suspect_paths = []
    failures: list[tuple[str, str]] = []

    def process_file_info(file_info):
        nonlocal processed_files_count
        file_path, db_size, db_last_modified = file_info
        counts['checked'] += 1

        # Skip files with any of the specified prefixes
        if exclude_prefix and any(file_path.startswith(prefix) for prefix in exclude_prefix):
            logging.info(f"SKIPPED: {file_path} (Matches exclude prefix)")
            counts['skipped'] += 1
            return

        # lstat, not os.path.exists (#74). exists() follows a symlink, so a
        # recorded symlink looked like the file it pointed at. It also returns
        # False for *any* error -- a directory the auditor cannot search
        # included -- so a row for a file that is still there was removed as
        # deleted. Only "no such path" counts as missing now; any other error
        # propagates and is counted as a failure, and the row is kept.
        try:
            mode = os.lstat(file_path).st_mode
        except (FileNotFoundError, NotADirectoryError):
            mode = None

        if mode is not None and not stat.S_ISREG(mode):
            # Only regular files belong in the database. Such a row was made
            # by a version that followed symlinks, or the path has since been
            # replaced. It is removed like a deleted file, with the same
            # --dry-run guard, and counted separately.
            kind = file_kind(mode)
            counts['not_regular'] += 1
            if dry_run:
                logging.info(f"WOULD REMOVE: {file_path} (not a regular file: {kind})")
            else:
                logging.info(f"REMOVED: {file_path} (not a regular file: {kind})")
                remove_record_by_path(db_path, file_path)
        elif mode is None:
            if looks_like_a_missing_volume(file_path) and not prune_missing_dirs:
                logging.warning(
                    f"SUSPECT: {file_path} (its directory is missing too -- "
                    f"unmounted volume? row kept)"
                )
                counts['suspect'] += 1
                suspect_paths.append(file_path)
                return
            counts['removed'] += 1
            if dry_run:
                logging.info(f"WOULD REMOVE: {file_path} (File no longer exists)")
            else:
                logging.info(f"REMOVED: {file_path} (File no longer exists)")
                remove_record_by_path(db_path, file_path)
        else:
            size = os.path.getsize(file_path)
            last_modified = get_file_mtime_in_ms(file_path)
            if size != db_size or last_modified != db_last_modified:
                counts['reprocessed'] += 1
                if dry_run:
                    logging.info(f"WOULD REPROCESS: {file_path} (Size or last modified time changed)")
                else:
                    logging.info(f"REPROCESSING: {file_path} (Size or last modified time changed)")
                    process_file(file_path, db_path)
        processed_files_count += 1

    def work(conn):
        cursor = conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")  # Enable WAL mode
        cursor.execute("SELECT path, size, last_modified FROM files")

        with ThreadPoolExecutor(max_workers=num_threads) as executor:
            while True:
                batch = cursor.fetchmany(batch_size)
                if not batch:
                    break
                # Keyed by path, so a failure can name the row it was
                # auditing. It used to be a bare list, and the error line said
                # only "Error processing file info", which is not something
                # anyone can act on (#57).
                futures = {executor.submit(process_file_info, file_info): file_info[0]
                           for file_info in batch}
                for future in as_completed(futures):
                    file_path = futures[future]
                    try:
                        future.result()
                    except Exception as e:
                        logging.error(f"Error auditing {file_path}: {e}")
                        counts['failed'] += 1
                        failures.append((file_path, str(e)))

    with_connection(db_path, work, description="audit the database")

    # This summary used to sit after the `raise` above, so it never ran and the
    # total was never reported.
    verb = 'would remove' if dry_run else 'removed'
    logging.info(
        f"AUDIT {'(dry run) ' if dry_run else ''}checked {counts['checked']}: "
        f"{verb} {counts['removed']}, reprocessed {counts['reprocessed']}, "
        f"skipped {counts['skipped']}, suspect {counts['suspect']}, "
        f"not regular {counts['not_regular']}, failed {counts['failed']}"
    )
    counts['failures'] = failures
    if suspect_paths:
        logging.warning(
            f"{len(suspect_paths)} row(s) kept because their directory is also "
            f"missing -- check whether a volume failed to mount. Re-run with "
            f"--prune-missing-dirs to remove them anyway."
        )
        for path in suspect_paths[:10]:
            logging.warning(f"  SUSPECT: {path}")
        if len(suspect_paths) > 10:
            logging.warning(f"  ... and {len(suspect_paths) - 10} more")
    return counts


def scan_and_report_unique_files(directory, db_path, num_threads=4):
    """
    Optimized: Scan a directory and report unique files based on their MD5 checksum using multiple threads.
    Persists processed file paths and their uniqueness status in a temporary file to skip reprocessing.

    Args:
        directory (str): The directory to scan.
        db_path (str): The path to the database file.
        num_threads (int): The number of threads to use for concurrent processing.

    Returns:
        list: A list of unique file paths. Files that could not be read are not
            in it, and are not counted as duplicates either -- they are logged
            as `unreadable` and retried on the next run.
    """
    if not os.path.isdir(directory):
        raise ValueError(f"Invalid directory: {directory}")

    temp_file_path = os.path.join(directory, ".processed_files.txt")
    processed_files = {}
    answered = set()

    # Load already processed files and their statuses from the temp file
    if os.path.exists(temp_file_path):
        print(f"Temp file: {temp_file_path}")
        with open(temp_file_path, "r") as temp_file:
            for line in temp_file:
                file_path, status = line.strip().split("\t")
                processed_files[file_path] = status
                # Only a verdict counts as answered. An `unreadable` row records
                # that the question was asked and could not be answered, so the
                # next run asks again -- a permission or a mount usually differs
                # between runs, and skipping forever would make one bad read
                # permanent (#41).
                if status in VERDICT_STATUSES:
                    answered.add(file_path)
        print("Previously processed files:")
        for file_path, status in processed_files.items():
            print(f"{file_path}\t{status}")

    unique_files = []
    unreadable_files = []

    def process_file(file_path):
        if file_path in answered:
            return None, None
        try:
            is_unique = is_file_unique(file_path, db_path)
        except UniquenessUnknown as e:
            # Recorded, not silently dropped and not called a duplicate.
            logging.warning(f"UNREADABLE: {file_path} ({e})")
            return file_path, STATUS_UNREADABLE
        except Exception as e:
            logging.error(f"Error processing file {file_path}: {e}")
            return None, None
        return file_path, STATUS_UNIQUE if is_unique else STATUS_NOT_UNIQUE

    # Collect every regular file; anything else is logged and counted (#74).
    skipped = SkippedEntries()
    file_paths = list(walk_regular_files(directory, skipped))

    # Process files using ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=num_threads) as executor:
        future_to_file = {executor.submit(process_file, file_path): file_path for file_path in file_paths}

        with open(temp_file_path, "a+") as temp_file:  # Open in append mode
            for future in as_completed(future_to_file):
                file_path, status = future.result()
                if file_path and status:
                    processed_files[file_path] = status
                    if status == STATUS_UNIQUE:
                        unique_files.append(file_path)
                        print(f"Unique file found: {file_path}")
                    elif status == STATUS_UNREADABLE:
                        unreadable_files.append(file_path)
                    temp_file.write(f"{file_path}\t{status}\n")
                    temp_file.flush()  # Ensure data is written to disk immediately
                    # print(".", end="", flush=True)  # Indicate progress
                    # print(f"Processed: {file_path} - {status}")

    print()  # Move to the next line after processing
    logging.info(f"Unique files found: {len(unique_files)}")
    not_regular = skipped.summary_line()
    if not_regular:
        logging.warning(f"{not_regular} -- in neither list")
    if unreadable_files:
        # Said out loud, because the answer for these files is "we do not know"
        # and the caller is about to treat the returned list as complete.
        logging.warning(
            f"{len(unreadable_files)} file(s) could not be read and are in "
            f"NEITHER list -- they are not known to be unique and not known to "
            f"be duplicates. Recorded as '{STATUS_UNREADABLE}' and retried next "
            f"run."
        )
        for path in unreadable_files[:10]:
            logging.warning(f"  UNREADABLE: {path}")
        if len(unreadable_files) > 10:
            logging.warning(f"  ... and {len(unreadable_files) - 10} more")
    return unique_files


def is_file_unique(file_path, db_path):
    """
    Check if a file is unique by comparing its MD5 checksum with the database.

    Args:
        file_path (str): The path to the file to check.
        db_path (str): The path to the database file.

    Returns:
        bool: True if no other recorded file shares its checksum, False if one
            does.

    Raises:
        ValueError: if `file_path` is not a regular file, or cannot be
            examined. A symlink is not followed (#74).
        UniquenessUnknown: if the checksum or the lookup failed, so neither
            answer is available. Never returns False for this case -- see #41.
    """
    try:
        require_regular_file(file_path)
    except (NotARegularFile, OSError) as e:
        raise ValueError(f"Invalid file path: {file_path} ({e})") from e

    try:
        md5sum = compute_md5(file_path)
        duplicates = check_for_duplicates(db_path, md5sum)
    except Exception as e:
        logging.error(f"Cannot determine uniqueness of {file_path}: {e}")
        raise UniquenessUnknown(
            f"cannot determine whether {file_path} is unique: {e}"
        ) from e
    return len(duplicates) == 0  # Unique if no duplicates are found
