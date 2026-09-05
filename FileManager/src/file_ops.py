import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from queue import Queue

from src.db import store_file_info, check_for_duplicates, get_file_info
from src.md5sum import compute_md5


def scan(path, db_path, num_threads):
    if os.path.isdir(path):
        scan_dir(path, db_path, num_threads)
    elif os.path.isfile(path):
        scan_file(path, db_path)
    else:
        logging.error(f"Invalid path: {path}")


def scan_file(path, db_path):
    process_file(path, db_path)

def scan_dir(path, db_path, num_threads):
    file_queue = Queue()

    def producer():
        for root, _, files in os.walk(path):
            for file in files:
                file_queue.put(os.path.join(root, file))
                logging.debug(f"Found file: {os.path.join(root, file)}")
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
                process_file(file_path, db_path)
            except Exception as e:
                logging.error(f"Error processing file {file_path}: {e}")
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


def process_file(file_path, db_path):
    size = os.path.getsize(file_path)
    last_modified = int(os.path.getmtime(file_path) * 1000)  # Multiply by 1000 and convert to integer
    file_info = get_file_info(db_path, file_path)

    if file_info:
        db_size, db_last_modified = file_info
        db_last_modified = int(float(db_last_modified))  # Convert to integer for comparison
        if db_size == size and db_last_modified == last_modified:
            logging.debug(f"SKIPPED: {file_path} ")
            print(".", end="", flush=True)
            return

    start_time = time.time()
    md5sum = compute_md5(file_path)
    end_time = time.time()
    duration_ms = int((end_time - start_time) * 1000)

    store_file_info(db_path, file_path, md5sum)
    logging.info(f"PROCESSED: {file_path}")


def process_files_concurrently(file_paths, db_path, num_threads):
    with ThreadPoolExecutor(max_workers=num_threads) as executor:
        futures = {executor.submit(process_file, file_path, db_path): file_path for file_path in file_paths}
        for future in as_completed(futures):
            file_path = futures[future]
            try:
                future.result()
            except Exception as e:
                logging.error(f"Error processing file {file_path}: {e}")


def check_file(path, db_path):
    md5sum = compute_md5(path)
    duplicates = check_for_duplicates(db_path, md5sum)
    if duplicates:
        logging.info(f"Duplicate found for {path}")
        print(f"Duplicate found for {path}:")
        for duplicate in duplicates:
            print(duplicate[0])
            logging.info(f"Duplicate: {duplicate[0]}")


# Record removal lives in src/db.py: `remove_record_by_path` for one exact path,
# `remove_records_by_regex` for a pattern matched against the whole path. Two
# thin wrappers used to sit here whose only job was to print the count, and one
# of them was called `remove_record` -- the same name as db.py's exact-path
# function, but with regex behaviour (#7). main.py prints the count now.
