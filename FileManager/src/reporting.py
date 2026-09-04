import logging
import os
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from queue import Queue

from src.db import check_for_duplicates, find_duplicates_with_min_count
from src.file_ops import process_file
from src.md5sum import compute_md5
from src.utils import get_files_with_md5


import logging
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from queue import Queue
from src.db import check_for_duplicates
from src.file_ops import process_file
from src.md5sum import compute_md5

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
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT path, COUNT(*) as duplicate_count FROM files
        WHERE md5sum IN (
            SELECT md5sum FROM files
            GROUP BY md5sum HAVING COUNT(*) > 1
        )
        GROUP BY path
    ''')
    results = cursor.fetchall()
    conn.close()

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
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    # One row per duplicated checksum: the size of a single copy and how many
    # copies exist. Summing size * (n - 1) leaves one copy of each intact.
    cursor.execute('''
        SELECT MIN(size), COUNT(*) FROM files
        GROUP BY md5sum HAVING COUNT(*) > 1
    ''')
    groups = cursor.fetchall()
    conn.close()

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
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT COUNT(*) FROM files WHERE path LIKE ?
    ''', (f'{prefix}%',))
    count = cursor.fetchone()[0]
    conn.close()

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
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT path FROM files WHERE path LIKE ?", (prefix + '%',))
    files = [row[0] for row in cursor.fetchall()]
    conn.close()
    return files

def report_duplicates_for_prefix(db_path, prefix):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT md5sum, path FROM files WHERE path LIKE ?", (prefix + '%',))
    rows = cursor.fetchall()
    md5_to_paths = {}
    for md5sum, path in rows:
        md5_to_paths.setdefault(md5sum, []).append(path)
    duplicates = {md5sum: paths for md5sum, paths in md5_to_paths.items() if len(paths) > 1}
    conn.close()
    return duplicates