import os
import stat
import sys

# Add the project root directory to the Python path
sys.path.append(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)

import datetime
import logging
import argparse
from src.db import (
    AuditCounts,
    initialize_db, audit_db, get_file_info, get_md5_by_path,
    scan_and_report_unique_files, remove_record_by_path, remove_records_by_regex,
)
from src.file_ops import (
    scan, check_file, process_file, ScanTally, verify_db,
)
from src.reporting import (
    scan_dir_report, report_duplicates, report_duplicate_sizes,
    report_prefix_count, compare_directories,
    # Hoisted out of the report-duplicates and report-files-for-prefix arms to
    # satisfy #54 requirement 7: the zip importer reopens the archive by its
    # path, so an import executed mid-run would read whatever .pyz is at that
    # path *now*, not the one the run started from. A 20-hour scan is long
    # enough for the file to be replaced under it.
    report_duplicates_for_prefix, report_files_for_prefix,
)
from src.utils import report_settings
from src.version import NAME, TIME_FORMAT, describe, one_line

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

def usage():
    print("""
    File Manager Application

    Usage:
        main.py --version | --help
        main.py <action> <path> [--db-path <db_path>] [--threads <num_threads>]
        [--prefix <prefix>] [--dirA <dirA>] [--dirB <dirB>] [--min-duplicates <min_duplicates>]
        [--exclude-prefix <exclude_prefix>] [--regex] [--dry-run]
        [--prune-missing-dirs]

    Actions:
        scan                Scan a comma-separated list of directories or files.
        check-file          Check a file for duplicates.
        scan-dir-report     Scan a directory and report duplicates.
        report-duplicates   Report all duplicates in the database.
        audit-db            Re-verify every recorded path. Drops rows for files
                            that no longer exist and rehashes those that changed.
                            Use --dry-run first: this action deletes rows.
        verify-db           Rehash recorded files and compare against the STORED
                            checksum, reporting every mismatch. This is the only
                            action that can detect silent corruption: scan and
                            audit-db both skip on (size, mtime), which is
                            unchanged by bit rot. Never writes to the database.
                            Scope a long run with --prefix. Exits 4 on a
                            mismatch.
        report-duplicate-sizes Report the total size of duplicate files.
        report-prefix-count Report the number of files that match a given prefix.
        remove-record       Remove the record for exactly the specified path.
                            With --regex, <path> is instead a regular expression
                            matched against the WHOLE path.
        compare-directories Compare two directories and report unique files.
        get-file-info       Get information of a file from the database.
        scan-unique-files   Scan a directory and report unique files.
        help                Show this help message. `-h`, `--help` and `-?`
                            do the same and also exit 0.

    Exit codes:
        0                   the action completed and read everything it was asked
                            to, or help was requested
        1                   a required argument was missing or invalid
        2                   argparse rejected the command line
        3                   scan, audit-db or verify-db completed but could not
                            read part of what it was asked to read. Some files
                            were recorded or checked and some were not; the
                            counts and the failed paths are on stdout.
        4                   verify-db found a recorded file whose contents no
                            longer match its stored checksum. Not 3: 3 means
                            part of the answer is unknown, 4 means the answer is
                            known and bad.
        5                   the environment the run needs is not there: the
                            database's directory is missing, is not a
                            directory, cannot be written to create the
                            database, or cannot be checked. Nothing was read
                            or recorded. The message names the directory.

    Options:
        --version           Print the commit this code was built from, the
                            build time and whether the tree was clean, then
                            exit 0. A bundle reports the values embedded when
                            it was built; a source checkout says so and reads
                            git live. Either way a question git cannot answer
                            prints CANNOT DETERMINE, never a placeholder. The
                            clean/dirty check covers FileManager/ only.
        --db-path           Path to the database file or directory.
        --threads           Number of threads to use for concurrent operations.
        --prefix            Prefix to match files (required for
                            report-prefix-count action). For verify-db it scopes
                            the run to recorded paths under that prefix --
                            verifying millions of files takes hours.
        --dirA              Path to the first directory for comparison (required for
                            compare-directories action).
        --dirB              Path to the second directory for comparison (required for
                            compare-directories action).
        --min-duplicates    Report only checksums held by at least this many files
                            (default: 2). Counts copies, not copies beyond the
                            first -- 2 means a file and one other like it.
        --exclude-prefix    Comma-separated list of prefixes to exclude paths from processing during audit-db.
        --regex             Treat remove-record's <path> as a regex matched against
                            the whole path. Without it the path is taken literally.
        --dry-run           audit-db only: report what would change, change nothing.
        --prune-missing-dirs
                            audit-db only: also remove rows whose parent directory
                            is gone. Off by default, because that is what an
                            unmounted volume looks like.

    Examples:
        python main.py scan /path/to/dir1,/path/to/dir2 --db-path /path/to/db --threads 4
        python main.py check-file /path/to/file --db-path /path/to/db --threads 4
        python main.py scan-dir-report /path/to/dir --db-path /path/to/db --threads 4
        python main.py audit-db --db-path /path/to/db --threads 4 --dry-run
        python main.py verify-db --db-path /path/to/db --threads 8
        python main.py verify-db --db-path /path/to/db --prefix /mnt/backup
        python main.py audit-db --db-path /path/to/db --threads 4 --exclude-prefix /exclude/path1,/exclude/path2
        python main.py report-duplicate-sizes --db-path /path/to/db
        python main.py report-prefix-count --db-path /path/to/db --prefix <prefix>
        python main.py remove-record /path/to/file --db-path /path/to/db
        python main.py remove-record '/path/to/dir/.*' --regex --db-path /path/to/db
        python main.py compare-directories --dirA /path/to/dirA --dirB /path/to/dirB
        python main.py get-file-info /path/to/file --db-path /path/to/db
        python main.py scan-unique-files /path/to/dir --db-path /path/to/db
    """)

def _origin(flag):
    """Was this flag given on the command line, or is its value a default?

    Printed alongside each setting so a log distinguishes "configured to 4"
    from "defaulted to 4". A value that merely looks right is not evidence it
    was set -- see docs/Development-Principles.md section 2.
    """
    return 'set' if any(
        arg == flag or arg.startswith(flag + '=') for arg in sys.argv[1:]
    ) else 'default'


def get_file_info_action(db_path, file_path):
    """Print what the database holds for one path.

    The checksum comes from `get_md5_by_path`, not from `get_file_info`.
    This used to read `file_info[2]`, but `get_file_info` selects only
    (size, last_modified), so the action raised IndexError for every path that
    was actually in the database -- it had never worked (#21).

    Widening `get_file_info` to three columns would have been the other fix and
    was rejected: its second caller is `process_file`, which unpacks a 2-tuple
    on the skip-check hot path, and that path is the thing that makes rescanning
    a large tree cheap. A one-off diagnostic does not get to reshape it for the
    sake of one query.
    """
    file_info = get_file_info(db_path, file_path)
    if file_info:
        size, last_modified = file_info
        print(f"File: {file_path}")
        print(f"Size: {size}")
        print(f"Last Modified: {last_modified}")
        print(f"MD5: {get_md5_by_path(db_path, file_path)}")
    else:
        print(f"No information found for file: {file_path}")

# The conventional ways to ask for help. Checked against the command line
# directly rather than registered with argparse, for two reasons that both have
# to hold at once (#58):
#
#   * the help text is `usage()`, which documents the actions, the options, the
#     exit codes and worked examples. argparse's generated help has none of that.
#   * `action` is a required positional, so `main.py --help` with nothing else
#     would fail the missing-argument check before argparse looked at the flag.
#
# `-?` is included because it is conventional, with the caveat that `?` is a
# shell glob character: it needs quoting as `'-?'` in some shells.
HELP_FLAGS = ('-h', '--help', '-?')

# Checked the same way and for the same reasons as HELP_FLAGS: `action` is a
# required positional, so `main.py --version` alone would fail the
# missing-argument check before argparse ever saw the flag (#62).
#
# Deliberately NOT argparse's `action='version'`. That route would raise
# SystemExit(0) through the handler below -- which works as of #58 -- but it
# would also mean two mechanisms answering two conventional flags in two
# different places. One is easier to keep true. CLAUDE.md predicted the
# argparse route; this supersedes it.
#
# `-V` is not accepted. #54's installer reads `--version`, and the long form is
# the only one specified; adding a short alias nobody asked for is one more
# string to keep documented.
VERSION_FLAGS = ('--version',)


# An action that ran to completion but could not read part of what it was asked
# to read. Distinct from 1 (bad argument) and 2 (argparse rejection), both of
# which mean nothing was recorded at all. See main()'s docstring and #57.
EXIT_INCOMPLETE = 3

# verify-db found a recorded file whose contents no longer match the stored
# checksum. Deliberately NOT 3: 3 means part of the answer is unknown, while
# this means the answer is known and bad. Conflating "could not check" with
# "checked and found corruption" is the mistake this whole area of the code
# keeps being fixed for (#50, and #41 before it).
EXIT_MISMATCH = 4

# The environment the run needs is not there, so nothing was read or recorded
# (#69). Deliberately NOT 1: 1 means the operator typed something invalid, and
# a well-formed --db-path whose directory has not been created is not that.
# Before #69 this case exited 1 only because 1 is Python's status for an
# uncaught exception -- the code never chose it.
EXIT_ENVIRONMENT = 5


def _database_directory_problem(db_path):
    """Why the database cannot be opened where `db_path` puts it, or None.

    Checked before `initialize_db`, which would otherwise die inside sqlite3
    with `unable to open database file` and a traceback that names no
    directory (#69). Each outcome gets its own message, because each has a
    different fix:

      * the directory does not exist -> create it. **It is never created
        here**: where the index lives is an operational decision, and a typo in
        a path must not invent a directory.
      * it exists but is not a directory.
      * the database file does not exist yet and the directory cannot be
        written, so the file cannot be created there. A permission problem is
        not a missing directory.
      * the directory could not be checked at all -- an ancestor that cannot
        be searched, for example. That is reported as itself, not folded into
        "does not exist", which is what `os.path.isdir` would have answered.

    Writability is checked only when the file must be created. An existing
    database in a read-only directory can still be read by the report actions,
    and refusing that would break a run that works today.
    """
    directory = os.path.abspath(os.path.dirname(db_path) or '.')
    try:
        mode = os.stat(directory).st_mode
    except (FileNotFoundError, NotADirectoryError):
        return (f"database directory does not exist: {directory}\n"
                f"Create it first (mkdir -p {directory}). "
                f"FileManager does not create it.")
    except OSError as exc:
        return f"cannot check database directory {directory}: {exc}"
    if not stat.S_ISDIR(mode):
        return f"database directory is not a directory: {directory}"
    if (not os.path.exists(db_path)
            and not os.access(directory, os.W_OK | os.X_OK)):
        return (f"database directory is not writable by uid {os.geteuid()}, "
                f"so the database cannot be created there: {directory}")
    return None


def _print_run_header(action, paths, db_path, threads):
    """Print what this run is, before it does anything (#54 requirement 10).

    On **stdout**, for the same reason the scan counts are (#57): a scheduled
    scan runs with `2>/dev/null` to suppress the per-file logging, and a header
    that vanishes under the one redirection every scheduled run uses is not a
    header. All the per-file diagnostics stay on stderr.

    **The zone is the requirement, not decoration.** Output is read from a log
    days later, and a bare clock time here has already been read against the
    wrong zone. `TIME_FORMAT` is shared with the build stamp so the two cannot
    drift apart.

    This replaces a `logging.info` line that carried the action, paths, database
    and thread count but went to stderr, had no version, and whose `asctime`
    had no zone. Nothing grepped it -- checked across the wrappers and tests
    before removing it.

    `help` and `--version` do not reach here: they are questions about the tool
    rather than runs of it, and the build verifies `--version` by grepping its
    output, which a header would sit in front of.
    """
    started = datetime.datetime.now().astimezone().strftime(TIME_FORMAT)
    fields = [
        ('started', started),
        ('version', one_line()),
        ('action', action),
        ('paths', paths if paths else '(none given)'),
        ('db', db_path),
        ('threads', str(threads)),
    ]
    width = max(len(label) for label, _ in fields)
    print(f'{NAME} run')
    for label, value in fields:
        print(f'{label.ljust(width)} : {value}')
    print()


def _print_verify_summary(tally):
    """The verify report, on stdout beside the other run results (#50)."""
    print()
    for line in tally.summary_lines():
        print(line)


def _print_scan_summary(tally):
    """Print the scan's counts to stdout, where a log reader will find them.

    stdout, not the logging stream: the counts are the result of the run, not a
    diagnostic, and they have to survive `2>/dev/null`. The leading newline is
    load-bearing -- `process_file` writes a bare "." to stdout per skipped file,
    so without it the summary lands at the end of a long line of dots.
    """
    print()
    for line in tally.summary_lines():
        print(line)


def _print_audit_summary(counts: AuditCounts) -> None:
    """The same, for audit-db. It logs its own INFO summary as well; this is the
    copy that reaches stdout and names what could not be read."""
    print()
    print(
        f"audit complete: checked {counts['checked']}, "
        f"removed {counts['removed']}, reprocessed {counts['reprocessed']}, "
        f"skipped {counts['skipped']}, suspect {counts['suspect']}, "
        f"not regular {counts['not_regular']}, failed {counts['failed']}"
    )
    failures = counts.get('failures') or []
    if failures:
        print(f"failed ({counts['failed']}):")
        for path, message in failures[:20]:
            print(f"  {path}: {message}")
        if len(failures) > 20:
            print(f"  ... and {len(failures) - 20} more; each is on an ERROR line in the log")


def main():
    """Run one CLI action.

    Returns:
        int: 0 on success, 1 when an argument is missing or invalid, 2 when
            argparse itself rejected the command line, 3 when the action ran to
            completion but could not read part of what it was asked to read.
            `main.py` used to `return` from every one of these branches, which
            exits 0 -- so an invalid invocation was indistinguishable from
            success to any caller checking $?, including the fm-*.sh wrappers
            running under set -e (#23).

            3 is separate from 1 and 2 on purpose: a caller needs to tell a bad
            command line, which recorded nothing, from a scan that recorded most
            of a tree and skipped the rest. Both are failures; only one leaves a
            partial index behind (#57).

            4 is verify-db finding a stored checksum that no longer matches the
            file (#50), and it is separate from 3 for the same kind of reason:
            3 says part of the answer is unknown, 4 says the answer is known and
            bad. A mismatch outranks an unreadable file when both happen.

            5 is an environment the run needs and does not have: the
            database's directory is missing, unwritable or uncheckable (#69).
            Nothing was read or recorded. Not 1, because the argument was well
            formed.
    """
    parser = argparse.ArgumentParser(
        description='File Manager Application', add_help=False
    )
    parser.add_argument(
        'action',
        choices=[
            'scan', 'check-file', 'scan-dir-report', 'report-duplicates',
            'audit-db', 'verify-db',
            'report-duplicate-sizes', 'report-prefix-count',
            'report-files-for-prefix',
            'remove-record', 'compare-directories', 'get-file-info',
            'scan-unique-files', 'help'
        ],
        help='Action to perform'
    )

    parser.add_argument(
        'path', nargs='?', help='Comma-separated list of paths to directories or files'
    )
    parser.add_argument('--db-path', help='Path to the database file or directory')
    parser.add_argument('--prefix', help='Prefix to match files')
    parser.add_argument(
        '--threads', type=int, default=4,
        help='Number of threads to use for concurrent operations'
    )
    parser.add_argument(
        '--min-duplicates', type=int, default=2,
        help='Report only checksums held by at least this many files (default: 2)'
    )
    parser.add_argument(
        '--dirA', help='Path to the first directory for comparison'
    )
    parser.add_argument(
        '--dirB', help='Path to the second directory for comparison'
    )
    parser.add_argument(
        '--dry-run', action='store_true',
        help='audit-db only: report what would change without changing it'
    )
    parser.add_argument(
        '--prune-missing-dirs', action='store_true',
        help='audit-db only: also remove rows whose parent directory is missing'
    )
    parser.add_argument(
        '--regex', action='store_true',
        help="Treat remove-record's path as a regex matched against the whole path"
    )
    # Add the --exclude-prefix argument to the parser
    parser.add_argument(
        '--exclude-prefix',
        help='Comma-separated list of prefixes to exclude paths from processing during audit-db'
    )

    # Before parsing: see HELP_FLAGS. Asking for help is not an error, and it
    # must work with no action given.
    if any(arg in HELP_FLAGS for arg in sys.argv[1:]):
        usage()
        return 0

    # Likewise before parsing. Help wins if both are given: a caller asking
    # both questions at once is asking how to use the tool.
    if any(arg in VERSION_FLAGS for arg in sys.argv[1:]):
        for line in describe():
            print(line)
        return 0

    try:
        args = parser.parse_args()
    except SystemExit as exc:
        # Respect the code argparse chose instead of flattening every exit to 2.
        # Returning 2 unconditionally meant a SystemExit(0) -- which is what
        # argparse raises for its own --help, and will raise for the --version
        # action in #54 -- was reported as a rejection. Same shape as #23, where
        # every branch `return`ed and so exited 0 whatever had happened.
        # `exc.code` is compared directly. It can be an int, a string or None;
        # only an int 0 means success, and neither a string nor None equals 0,
        # so both land on the rejection path without a type check. A type check
        # was tried here and removed: it could not be made to change any
        # observable behaviour, and a guard that cannot fail is noise.
        if exc.code == 0:
            return 0
        usage()
        return 2

    if args.action == 'help':
        usage()
        return 0

    if args.action in ['scan', 'check-file', 'scan-dir-report', 'remove-record', 'get-file-info'] and not args.path:
        print("Error: <path> argument is required for this action")
        usage()
        return 1

    if args.action == 'report-prefix-count' and not args.prefix:
        print("Error: --prefix argument is required for report-prefix-count action")
        usage()
        return 1

    if args.action == 'compare-directories' and (not args.dirA or not args.dirB):
        print("Error: --dirA and --dirB arguments are required for compare-directories action")
        usage()
        return 1

    db_path = args.db_path if args.db_path else 'file_manager.db'
    if os.path.isdir(db_path):
        db_path = os.path.join(db_path, 'file_manager.db')

    # Before initialize_db, which creates the file: the header describes a run
    # that is about to touch something, so it goes out before the first effect.
    _print_run_header(args.action, args.path, db_path, args.threads)

    # After the header, so the log shows which database was meant; before
    # initialize_db, which is the first thing that would fail (#69).
    problem = _database_directory_problem(db_path)
    if problem is not None:
        print(f"Error: {problem}")
        return EXIT_ENVIRONMENT

    initialize_db(db_path)

    if args.action == 'scan':
        paths = args.path.split(',') if args.path else []
        # One tally across every path in the comma-separated list: the caller
        # asked for one scan, so one answer about whether it was complete.
        tally = ScanTally()
        for path in paths:
            scan(path.strip(), db_path, args.threads, tally)
        _print_scan_summary(tally)
        if tally.failed:
            return EXIT_INCOMPLETE
    elif args.action == 'check-file':
        # A path that is not a regular file is an invalid argument (#74).
        if not check_file(args.path, db_path):
            return 1
    elif args.action == 'scan-dir-report':
        # False means the walk stopped early and part of the tree was not
        # scanned: the same partial result as an incomplete scan (#75).
        if not scan_dir_report(args.path, db_path, args.threads):
            return EXIT_INCOMPLETE
    elif args.action == 'report-duplicates':
        if args.prefix:
            duplicates = report_duplicates_for_prefix(db_path, args.prefix)
        else:
            duplicates = report_duplicates(db_path, args.min_duplicates)
        print(f"Found {len(duplicates)} duplicates")
        for md5sum, paths in duplicates.items():
            if len(paths) > 1:
                print(f"MD5: {md5sum}")
                for path in paths:
                    print(f"  {path}")

    elif args.action == 'audit-db':
        exclude_prefixes = args.exclude_prefix.split(',') if args.exclude_prefix else None
        # State what this run was configured to do before it does any of it --
        # audit-db deletes rows, and the settings that governed a past run are
        # not recoverable afterwards. docs/Development-Principles.md section 2.
        report_settings('audit-db', [
            ('db_path', db_path, _origin('--db-path')),
            ('threads', args.threads, _origin('--threads')),
            ('exclude_prefix', exclude_prefixes, _origin('--exclude-prefix')),
            ('dry_run', args.dry_run, _origin('--dry-run')),
            ('prune_missing_dirs', args.prune_missing_dirs, _origin('--prune-missing-dirs')),
        ])
        counts = audit_db(db_path, args.threads, process_file,
                           exclude_prefix=exclude_prefixes,
                           dry_run=args.dry_run,
                           prune_missing_dirs=args.prune_missing_dirs)
        _print_audit_summary(counts)
        if counts['failed']:
            return EXIT_INCOMPLETE
    elif args.action == 'verify-db':
        report_settings('verify-db', [
            ('db_path', db_path, _origin('--db-path')),
            ('threads', args.threads, _origin('--threads')),
            ('prefix', args.prefix or '(every recorded path)',
             _origin('--prefix')),
        ])
        tally = verify_db(db_path, args.threads, args.prefix)
        _print_verify_summary(tally)
        # A mismatch outranks an unreadable file. Both are failures, but one
        # is a definite wrong answer already in the database and the other is
        # a gap still to be checked.
        if tally.mismatched:
            return EXIT_MISMATCH
        if tally.unreadable:
            return EXIT_INCOMPLETE
    elif args.action == 'report-duplicate-sizes':
        report_duplicate_sizes(db_path)
    elif args.action == 'report-prefix-count':
        report_prefix_count(db_path, args.prefix)
    elif args.action == 'remove-record':
        # Literal by default. The regex form is opt-in because this action's
        # argument looks like a path, and a path silently interpreted as a
        # pattern is how #1 deleted siblings.
        if args.regex:
            count = remove_records_by_regex(db_path, args.path)
            print(f"{count} record(s) matching the pattern '{args.path}' "
                  f"have been removed from the database.")
        else:
            count = remove_record_by_path(db_path, args.path)
            if count:
                print(f"Removed the record for '{args.path}'.")
            else:
                print(f"No record found for '{args.path}'. Nothing removed.")
    elif args.action == 'compare-directories':
        compare_directories(args.dirA, args.dirB)
    elif args.action == 'get-file-info':
        get_file_info_action(db_path, args.path)
    elif args.action == 'scan-unique-files':
        unique_files = scan_and_report_unique_files(args.path, db_path, args.threads)
        print(f"Unique files:\n" + "\n".join(unique_files))

    # In main(), add:
    elif args.action == 'report-files-for-prefix':
        if not args.prefix:
            print("Error: --prefix argument is required for report-files-for-prefix action")
            usage()
            return 1
        files = report_files_for_prefix(db_path, args.prefix)
        print(f"Files with prefix '{args.prefix}':")
        for f in files:
            print(f)

    return 0


if __name__ == "__main__":
    sys.exit(main())