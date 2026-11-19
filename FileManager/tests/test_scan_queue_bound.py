"""#67 -- a scan's producer blocks on a bounded queue instead of queueing the tree.

`scan_dir` and `scan_dir_report` each walk the tree on a producer thread and
hand paths to `--threads` workers through a `Queue`. The walk only reads
metadata and the workers hash contents, so on a baseline scan the producer runs
far ahead. With an unbounded queue it ran to the end of the walk, and the queue
held every path in the tree at once: about 0.63 GiB for the 5.58M files on
`/home2`.

The tests hold the workers on a gate so that the producer is guaranteed to get
ahead, then read the largest `qsize()` seen after any `put()`. Without the bound
the producer queues every file before the gate opens, and the largest size is
the file count; with it, the size stops at the bound.

The bound is shrunk to a few slots so that a small tree is enough to overrun
it. The same shrinking gives the shutdown test its case: more workers than
slots, so the producer's own sentinel puts must block and still complete.
Hanging there is caught by the `timeout = 60` in `pytest.ini`, which is left as
it is.
"""

from __future__ import annotations

import queue
import threading

import pytest

from src import file_ops, reporting

BOUND = 4
FILES = 40
# Long enough for an unbounded producer to queue all FILES paths many times
# over; it only has to stat and join forty names.
GATE_SECONDS = 0.5


class RecordingQueue(queue.Queue):
    """A Queue that remembers the largest size it reached after a put()."""

    instances: list["RecordingQueue"] = []

    def __init__(self, maxsize: int = 0) -> None:
        super().__init__(maxsize)
        self.largest = 0
        self._record_lock = threading.Lock()
        RecordingQueue.instances.append(self)

    def put(self, item, block=True, timeout=None):
        super().put(item, block, timeout)
        size = self.qsize()
        with self._record_lock:
            self.largest = max(self.largest, size)


@pytest.fixture
def recording_queue(monkeypatch):
    """Install RecordingQueue and a small bound in both scan modules."""
    RecordingQueue.instances = []
    for module in (file_ops, reporting):
        monkeypatch.setattr(module, "Queue", RecordingQueue)
        monkeypatch.setattr(module, "SCAN_QUEUE_MAXSIZE", BOUND)
    return RecordingQueue.instances


@pytest.fixture
def tree(tmp_path):
    root = tmp_path / "tree"
    root.mkdir()
    for i in range(FILES):
        (root / f"f{i:03d}.txt").write_text(f"file {i}\n")
    return root


@pytest.fixture
def gate():
    """An Event that opens by itself after GATE_SECONDS."""
    event = threading.Event()
    timer = threading.Timer(GATE_SECONDS, event.set)
    timer.start()
    yield event
    timer.cancel()
    event.set()


def _gated_process_file(gate, seen):
    lock = threading.Lock()

    def process_file(path, db_path):
        gate.wait()
        with lock:
            seen.append(path)
        return "hashed"

    return process_file


def test_the_bound_is_a_few_thousand_entries():
    """The production value: large enough to keep every worker fed, small
    enough that its memory does not depend on the tree."""
    assert 1000 <= file_ops.SCAN_QUEUE_MAXSIZE <= 10000
    assert reporting.SCAN_QUEUE_MAXSIZE == file_ops.SCAN_QUEUE_MAXSIZE


def test_scan_dir_producer_blocks_at_the_bound(db_path, tree, recording_queue,
                                               gate, monkeypatch):
    seen: list[str] = []
    monkeypatch.setattr(file_ops, "process_file", _gated_process_file(gate, seen))

    tally = file_ops.scan_dir(str(tree), db_path, 1)

    [q] = recording_queue
    assert q.maxsize == BOUND
    # Reached the bound and went no further: the producer filled the queue
    # while the worker was held, then waited.
    assert q.largest == BOUND
    assert len(seen) == FILES
    assert tally.hashed == FILES and tally.failed == 0


def test_scan_dir_report_producer_blocks_at_the_bound(db_path, tree,
                                                      recording_queue, gate,
                                                      monkeypatch):
    seen: list[str] = []
    monkeypatch.setattr(reporting, "process_file", _gated_process_file(gate, seen))

    reporting.scan_dir_report(str(tree), db_path, 1)

    [q] = recording_queue
    assert q.maxsize == BOUND
    assert q.largest == BOUND
    assert len(seen) == FILES


@pytest.mark.parametrize("scan", ["scan_dir", "scan_dir_report"])
def test_more_workers_than_slots_still_shuts_down(db_path, tree,
                                                  recording_queue, scan):
    """Eight sentinels into a four-slot queue: the producer's last puts block
    until workers take sentinels off, and every worker must still exit. A hang
    here is reported by pytest-timeout with every thread's stack."""
    num_threads = BOUND * 2
    if scan == "scan_dir":
        tally = file_ops.scan_dir(str(tree), db_path, num_threads)
        assert tally.checked == FILES and tally.failed == 0
    else:
        reporting.scan_dir_report(str(tree), db_path, num_threads)

    [q] = recording_queue
    assert q.maxsize == BOUND
    assert q.largest <= BOUND
    assert q.qsize() == 0
    assert q.unfinished_tasks == 0
