import os
import sys

# Add the project root directory to the Python path
sys.path.append(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)

import logging
import argparse
from src.db import initialize_db, audit_db, get_file_info, scan_and_report_unique_files
from src.file_ops import scan, check_file, process_file, remove_record, remove_records_by_regex
from src.reporting import (
    scan_dir_report, report_duplicates, report_duplicate_sizes,
    report_prefix_count, compare_directories
)
from src.gui import show_duplicates_gui

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

def usage():
    print("""
    File Manager Application

    Usage:
        main.py <action> <path> [--db-path <db_path>] [--threads <num_threads>]
        [--prefix <prefix>] [--dirA <dirA>] [--dirB <dirB>] [--use-gui] [--min-duplicates <min_duplicates>]
        [--exclude-prefix <exclude_prefix>]

    Actions:
        scan                Scan a comma-separated list of directories or files.
        check-file          Check a file for duplicates.
        scan-dir-report     Scan a directory and report duplicates.
        report-duplicates   Report all duplicates in the database.
        audit-db            Audit the database for file changes.
        report-duplicate-sizes Report the total size of duplicate files.
        report-prefix-count Report the number of files that match a given prefix.
        remove-record       Remove the record associated with the specified path
                            from the database.
        compare-directories Compare two directories and report unique files.
        get-file-info       Get information of a file from the database.
        scan-unique-files   Scan a directory and report unique files.
        help                Show this help message.

    Options:
        --db-path           Path to the database file or directory.
        --threads           Number of threads to use for concurrent operations.
        --prefix            Prefix to match files (required for
                            report-prefix-count action).
        --dirA              Path to the first directory for comparison (required for
                            compare-directories action).
        --dirB              Path to the second directory for comparison (required for
                            compare-directories action).
        --use-gui           Use GUI for displaying duplicates.
        --min-duplicates    Minimum number of duplicates to search for (default: 1).
        --exclude-prefix    Comma-separated list of prefixes to exclude paths from processing during audit-db.

    Examples:
        python main.py scan /path/to/dir1,/path/to/dir2 --db-path /path/to/db --threads 4
        python main.py check-file /path/to/file --db-path /path/to/db --threads 4
        python main.py scan-dir-report /path/to/dir --db-path /path/to/db --threads 4
        python main.py report-duplicates --db-path /path/to/db --threads 4 --use-gui
        python main.py audit-db --db-path /path/to/db --threads 4 --exclude-prefix /exclude/path1,/exclude/path2
        python main.py report-duplicate-sizes --db-path /path/to/db
        python main.py report-prefix-count --db-path /path/to/db --prefix <prefix>
        python main.py remove-record /path/to/file --db-path /path/to/db
        python main.py compare-directories --dirA /path/to/dirA --dirB /path/to/dirB
        python main.py get-file-info /path/to/file --db-path /path/to/db
        python main.py scan-unique-files /path/to/dir --db-path /path/to/db
    """)

def get_file_info_action(db_path, file_path):
    file_info = get_file_info(db_path, file_path)
    if file_info:
        print(f"File: {file_path}")
        print(f"Size: {file_info[0]}")
        print(f"Last Modified: {file_info[1]}")
        print(f"MD5: {file_info[2]}")
    else:
        print(f"No information found for file: {file_path}")

def main():
    parser = argparse.ArgumentParser(
        description='File Manager Application', add_help=False
    )
    parser.add_argument(
        'action',
        choices=[
            'scan', 'check-file', 'scan-dir-report', 'report-duplicates',
            'audit-db', 'report-duplicate-sizes', 'report-prefix-count',
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
        '--min-duplicates', type=int, default=1,
        help='Minimum number of duplicates to search for'
    )
    parser.add_argument(
        '--dirA', help='Path to the first directory for comparison'
    )
    parser.add_argument(
        '--dirB', help='Path to the second directory for comparison'
    )
    parser.add_argument(
        '--use-gui', action='store_true',
        help='Use GUI for displaying duplicates'
    )
    # Add the --exclude-prefix argument to the parser
    parser.add_argument(
        '--exclude-prefix',
        help='Comma-separated list of prefixes to exclude paths from processing during audit-db'
    )

    try:
        args = parser.parse_args()
    except SystemExit:
        usage()
        return

    if args.action == 'help':
        usage()
        return

    if args.action in ['scan', 'check-file', 'scan-dir-report', 'remove-record', 'get-file-info'] and not args.path:
        print("Error: <path> argument is required for this action")
        usage()
        return

    if args.action == 'report-prefix-count' and not args.prefix:
        print("Error: --prefix argument is required for report-prefix-count action")
        usage()
        return

    if args.action == 'compare-directories' and (not args.dirA or not args.dirB):
        print("Error: --dirA and --dirB arguments are required for compare-directories action")
        usage()
        return

    db_path = args.db_path if args.db_path else 'file_manager.db'
    if os.path.isdir(db_path):
        db_path = os.path.join(db_path, 'file_manager.db')
    initialize_db(db_path)

    logging.info(
        f"ACTION: {args.action}; PATH(s): {args.path}; DB: {db_path}; "
        f"THREADS: {args.threads}"
    )

    if args.action == 'scan':
        paths = args.path.split(',') if args.path else []
        for path in paths:
            scan(path.strip(), db_path, args.threads)
    elif args.action == 'check-file':
        check_file(args.path, db_path)
    elif args.action == 'scan-dir-report':
        scan_dir_report(args.path, db_path, args.threads)
    elif args.action == 'report-duplicates':
        if args.prefix:
            from src.reporting import report_duplicates_for_prefix
            duplicates = report_duplicates_for_prefix(db_path, args.prefix)
        else:
            duplicates = report_duplicates(db_path, args.min_duplicates)
        print(f"Found {len(duplicates)} duplicates")
        if args.use_gui:
            truncated_duplicates = dict(list(duplicates.items())[:100])
            show_duplicates_gui(truncated_duplicates)
        else:
            for md5sum, paths in duplicates.items():
                if len(paths) > 1:
                    print(f"MD5: {md5sum}")
                    for path in paths:
                        print(f"  {path}")

    elif args.action == 'audit-db':
        exclude_prefixes = args.exclude_prefix.split(',') if args.exclude_prefix else None
        audit_db(db_path, args.threads, process_file, exclude_prefix=exclude_prefixes)
    elif args.action == 'report-duplicate-sizes':
        report_duplicate_sizes(db_path)
    elif args.action == 'report-prefix-count':
        report_prefix_count(db_path, args.prefix)
    elif args.action == 'remove-record':
        remove_record(db_path, args.path)
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
            return
        from src.reporting import report_files_for_prefix
        files = report_files_for_prefix(db_path, args.prefix)
        print(f"Files with prefix '{args.prefix}':")
        for f in files:
            print(f)

if __name__ == "__main__":
    main()