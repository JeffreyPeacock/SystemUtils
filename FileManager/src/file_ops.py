import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from queue import Queue

from src.db import store_file_info, check_for_duplicates, get_file_info
from src.md5sum import compute_md5

# How many failed paths a summary prints before it gives a count instead. Every
# failure is logged individually regardless; this bounds only the final block,
# because a scan of millions of files on a failing disk should not bury the
# counts under its own error list.
MAX_FAILURES_LISTED = 20


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
    if os.path.isdir(path):
        scan_dir(path, db_path, num_threads, tally)
    elif os.path.isfile(path):
        scan_file(path, db_path, tally)
    else:
        # Not a warning. A path given on the command line that is neither a
        # file nor a directory means the scan did not cover what it was asked
        # to cover, which is the same kind of gap as an unreadable file.
        logging.error(f"Invalid path: {path}")
        tally.record_failure(path, "not a file or directory")
    return tally


def scan_file(path, db_path, tally=None):
    tally = tally if tally is not None else ScanTally()
    try:
        tally.record_outcome(process_file(path, db_path))
    except Exception as e:
        logging.error(f"Error processing file {path}: {e}")
        tally.record_failure(path, e)
    return tally

def scan_dir(path, db_path, num_threads, tally=None):
    tally = tally if tally is not None else ScanTally()
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
                tally.record_outcome(process_file(file_path, db_path))
            except Exception as e:
                logging.error(f"Error processing file {file_path}: {e}")
                tally.record_failure(file_path, e)
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
            except Exception as e:
                logging.error(f"Error processing file {file_path}: {e}")
                tally.record_failure(file_path, e)
    return tally


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
