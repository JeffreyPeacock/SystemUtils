import logging
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from queue import Queue

# No `sqlite3` import here on purpose. Every query in this module goes through
# src/db.py, which owns the schema, the connection and the lock-retry loop
# (#10). tests/test_db_is_the_only_connection.py pins that.
from src.db import (
    check_for_duplicates,
    count_duplicates_per_path,
    count_paths_with_prefix,
    duplicate_group_sizes,
    find_duplicates_under_prefix,
    find_duplicates_with_min_count,
    list_paths_with_prefix,
)
from src.file_ops import process_file
from src.md5sum import compute_md5
from src.utils import get_files_with_md5

def scan_dir_report(path, db_path, num_threads):
    """
    Scan a directory, process files concurrently, and report duplicates using a producer-consumer model.

    Args:
        path (str): The path to the directory.
        db_path (str): The path to the database file.
        num_threads (int): The number of threads to use for concurrent operations.
    """
    file_queue = Queue()

    def producer():
        for root, _, files in os.walk(path):
            for file in files:
                file_queue.put(os.path.join(root, file))
                logging.debug(f"Found file: {os.path.join(root, file)}")
        for _ in range(num_threads):
            file_queue.put(None)  # Signal the consumers to stop

    def process_and_report(file_path):
        try:
            process_file(file_path, db_path)
            md5sum = compute_md5(file_path)
            duplicates = check_for_duplicates(db_path, md5sum)
            if len(duplicates) > 1:
                logging.info(f"Duplicate found for {file_path}")
                print(f"Duplicate found for {file_path}:")
                for duplicate in duplicates:
                    print(duplicate[0])
                    logging.info(f"Duplicate: {duplicate[0]}")
        except Exception as e:
            logging.error(f"Error processing file {file_path}: {e}")
        finally:
            file_queue.task_done()

    def consumer():
        while True:
            file_path = file_queue.get()
            if file_path is None:
                break
            process_and_report(file_path)

    def start_producer():
        producer_thread = threading.Thread(target=producer)
        producer_thread.start()
        return producer_thread

    def start_consumers():
        with ThreadPoolExecutor(max_workers=num_threads) as executor:
            for _ in range(num_threads):
                executor.submit(consumer)

    producer_thread = start_producer()
    start_consumers()
    producer_thread.join()
    file_queue.join()

def report_duplicates(db_path, min_duplicates=1):
    duplicates = find_duplicates_with_min_count(db_path, min_duplicates)
    if duplicates:
        return duplicates
    else:
        return {}

def report_files_with_more_than_1_duplicate(db_path):
    """
    Report files that have more than 1 duplicate.

    Args:
        db_path (str): The path to the database file.
    """
    results = count_duplicates_per_path(db_path)

    if results:
        print("Files with more than 1 duplicate:")
        for path, duplicate_count in results:
            print(f"{path} - {duplicate_count} duplicates")
    else:
        print("No files with more than 1 duplicate found.")


def report_duplicate_sizes(db_path):
    """
    Report the space that deleting the redundant copies would reclaim.

    Two defects lived here:

      The total was halved (#4). That is exact for a group of two and wrong
      above it -- a file with four copies has THREE redundant, not two, so the
      old figure understated by 25%, and by 40% at ten copies. The reclaimable
      size per group is (count - 1) x size, which is what the SQL computes now.

      An empty result crashed (#22). SUM over no rows is NULL, and the division
      happened BEFORE the `if total_size:` guard that reads as protection
      against exactly that -- so a database with no duplicates raised TypeError
      and the "No duplicate files found." branch was unreachable.

    Args:
        db_path (str): The path to the database file.
    """
    # One row per duplicated checksum: the size of a single copy and how many
    # copies exist. Summing size * (n - 1) leaves one copy of each intact.
    groups = duplicate_group_sizes(db_path)

    reclaimable = sum(size * (count - 1) for size, count in groups if size is not None)

    if not groups or reclaimable <= 0:
        print("No duplicate files found.")
        return

    if reclaimable >= 1024 ** 4:
        print(f"Total size of duplicate files: {reclaimable / 1024 ** 4:.2f} TB")
    elif reclaimable >= 1024 ** 3:
        print(f"Total size of duplicate files: {reclaimable / 1024 ** 3:.2f} GB")
    else:
        print(f"Total size of duplicate files: {reclaimable / 1024 ** 2:.2f} MB")


def report_prefix_count(db_path, prefix):
    """
    Count the number of files that match the given prefix.

    Args:
        db_path (str): The path to the database file.
        prefix (str): The prefix to match files.
    """
    count = count_paths_with_prefix(db_path, prefix)

    print(f"Number of files that match the prefix '{prefix}': {count}")


def compare_directories(dirA, dirB):
    """Compare two directories and report unique files in each."""
    files_md5_A = get_files_with_md5(dirA)
    files_md5_B = get_files_with_md5(dirB)

    unique_to_A = {file for file, md5 in files_md5_A.items() if md5 not in files_md5_B.values()}
    unique_to_B = {file for file, md5 in files_md5_B.items() if md5 not in files_md5_A.values()}

    print("Files unique to dirA:")
    for file in unique_to_A:
        print(file)

    print("\nFiles unique to dirB:")
    for file in unique_to_B:
        print(file)

def report_files_for_prefix(db_path, prefix):
    return list_paths_with_prefix(db_path, prefix)

def report_duplicates_for_prefix(db_path, prefix):
    return find_duplicates_under_prefix(db_path, prefix)