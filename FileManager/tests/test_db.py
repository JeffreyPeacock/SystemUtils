import os
import re
import shutil
import sqlite3
import tempfile
import unittest

import pytest

from tests.conftest import assert_not_duplicated, assert_one_group
from src.db import (
    initialize_db, get_file_info, get_all_files_info, store_file_info,
    remove_record_by_path, remove_records_by_regex, get_md5_by_path,
    check_for_duplicates, find_duplicates_with_min_count, audit_db
)
from src.md5sum import compute_md5
from src.utils import get_file_mtime_in_ms

class TestDBFunctions(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        # An absolute path in a scratch directory. This used to be the relative
        # 'test.db', which landed in whatever directory pytest was run from --
        # i.e. in the repository.
        cls.tmp_dir = tempfile.mkdtemp()
        cls.db_path = os.path.join(cls.tmp_dir, 'test.db')
        cls.test_data_dir = os.path.join(os.path.dirname(__file__), '..', 'test_data', 'data')
        cls.duplicate_data_dir = os.path.join(os.path.dirname(__file__), '..', 'test_data', 'duplicate_data')

    def setUp(self):
        self.conn = sqlite3.connect(self.db_path)
        initialize_db(self.db_path)
        self.cursor = self.conn.cursor()
        self.cursor.execute('DELETE FROM files')
        self.conn.commit()

    def tearDown(self):
        self.cursor.close()
        self.conn.close()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp_dir, ignore_errors=True)

    def test_initialize_db(self):
        self.cursor.execute('SELECT name FROM sqlite_master WHERE type="table" AND name="files"')
        result = self.cursor.fetchone()
        self.assertIsNotNone(result)
        self.assertEqual(result[0], 'files')

    def test_store_file_info(self):
        file_name = 'test-file.txt'
        file_path = os.path.join(self.test_data_dir, file_name)
        store_file_info(self.db_path, file_path, compute_md5(file_path))
        self.cursor.execute('SELECT * FROM files WHERE path = ?', (file_path,))
        result = self.cursor.fetchone()
        self.assertIsNotNone(result)
        self.assertEqual(result[1], compute_md5(file_path))

    def test_get_file_info(self):
        file_name = 'test-file.txt'
        file_path = os.path.join(self.test_data_dir, file_name)
        store_file_info(self.db_path, file_path, compute_md5(file_path))
        file_info = get_file_info(self.db_path, file_path)
        self.assertIsNotNone(file_info)
        self.assertEqual(file_info[0], os.path.getsize(file_path))
        self.assertEqual(file_info[1], get_file_mtime_in_ms(file_path))

    def test_get_all_files_info(self):
        file_name = 'test-file.txt'
        file_path = os.path.join(self.test_data_dir, file_name)
        store_file_info(self.db_path, file_path, compute_md5(file_path))
        files_info = get_all_files_info(self.db_path)
        self.assertEqual(len(files_info), 1)
        self.assertIn((file_path, os.path.getsize(file_path), get_file_mtime_in_ms(file_path)), files_info)

    def test_remove_file_info(self):
        file_name = 'test-file.txt'
        file_path = os.path.join(self.test_data_dir, file_name)
        store_file_info(self.db_path, file_path, compute_md5(file_path))
        remove_record_by_path(self.db_path, file_path)
        self.cursor.execute('SELECT * FROM files WHERE path = ?', (file_path,))
        result = self.cursor.fetchone()
        self.assertIsNone(result)

    def test_remove_files_by_regex(self):
        file_name = 'test-file.txt'
        file_path = os.path.join(self.test_data_dir, file_name)
        store_file_info(self.db_path, file_path, compute_md5(file_path))
        remove_records_by_regex(self.db_path, r'.*test-file\.txt$')
        self.cursor.execute('SELECT * FROM files WHERE path = ?', (file_path,))
        result = self.cursor.fetchone()
        self.assertIsNone(result)

    def test_get_md5_by_path(self):
        file_name = 'test-file.txt'
        file_path = os.path.join(self.test_data_dir, file_name)
        store_file_info(self.db_path, file_path, compute_md5(file_path))
        retrieved_md5sum = get_md5_by_path(self.db_path, file_path)
        self.assertEqual(retrieved_md5sum, compute_md5(file_path))

    def test_audit_db(self):
        file_name = 'test-file.txt'
        file_path = os.path.join(self.test_data_dir, file_name)
        store_file_info(self.db_path, file_path, compute_md5(file_path))
        def mock_process_file(file_path, db_path):
            pass
        audit_db(self.db_path, num_threads=2, process_file=mock_process_file)
        self.cursor.execute('SELECT * FROM files WHERE path = ?', (file_path,))
        result = self.cursor.fetchone()
        self.assertIsNotNone(result)

# ---------------------------------------------------------------------------
# Duplicate detection, on the shared fixtures.
#
# These replace TestCase versions that hand-built their state out of
# test_data/ and asserted on raw tuples. The fixtures supply a tree whose
# duplicate relationships are known in advance, so a test says what it means
# and a failure names the paths involved.
# ---------------------------------------------------------------------------


def test_check_for_duplicates_finds_both_copies(db_path, dup_tree):
    left, right = dup_tree.duplicated[0]
    md5sum = compute_md5(str(left))
    store_file_info(db_path, str(left), md5sum)
    store_file_info(db_path, str(right), compute_md5(str(right)))

    found = {row[0] for row in check_for_duplicates(db_path, md5sum)}

    assert found == {str(left), str(right)}


def test_find_duplicates_groups_every_shared_pair(db_path, dup_tree):
    """Each duplicated pair forms its own group; the unique files form none."""
    for path in dup_tree.all_files():
        store_file_info(db_path, str(path), compute_md5(str(path)))

    duplicates = find_duplicates_with_min_count(db_path, min_count=2)

    # Every pair, the comma-carrying one included -- see #5.
    for left, right in dup_tree.duplicated:
        assert_one_group(duplicates, left, right)
    assert_not_duplicated(duplicates, *dup_tree.unique)


def test_find_duplicates_survives_a_comma_in_the_path(db_path, dup_tree):
    left, right = dup_tree.comma_pair
    store_file_info(db_path, str(left), compute_md5(str(left)))
    store_file_info(db_path, str(right), compute_md5(str(right)))

    duplicates = find_duplicates_with_min_count(db_path, min_count=2)

    assert_one_group(duplicates, left, right)


def test_skip_check_sees_a_size_change(db_path, dup_tree):
    """The size half of process_file's skip check."""
    before = os.path.getsize(dup_tree.grows)
    dup_tree.grow()
    assert os.path.getsize(dup_tree.grows) != before


def test_skip_check_sees_an_mtime_only_change(db_path, dup_tree):
    """The mtime half: same size, different mtime."""
    before_size = os.path.getsize(dup_tree.touched)
    before_mtime = get_file_mtime_in_ms(str(dup_tree.touched))
    dup_tree.touch()
    assert os.path.getsize(dup_tree.touched) == before_size
    assert get_file_mtime_in_ms(str(dup_tree.touched)) != before_mtime


if __name__ == '__main__':
    unittest.main()

# ---------------------------------------------------------------------------
# #1 -- removal must not reach past the path it was given.
#
# remove_records_by_regex used re.match, which anchors the start of the string
# and not the end, so the literal path /a/b also deleted /a/bc and everything
# under /a/b-old/. Nothing in a diff shows that; only a test does.
# ---------------------------------------------------------------------------


def _record(db, path):
    store_file_info(db, str(path), compute_md5(str(path)))


def _paths(db):
    return {row[0] for row in get_all_files_info(db)}


def test_exact_removal_leaves_sibling_prefixes_alone(db_path, dup_tree):
    """The case from #1: removing /a/b must not touch /a/bc."""
    target = dup_tree.left / "unique-left.txt"
    sibling = dup_tree.left / "unique-left.txt.bak"
    sibling.write_bytes(b"a different file whose path starts with the target's\n")
    _record(db_path, target)
    _record(db_path, sibling)

    removed = remove_record_by_path(db_path, str(target))

    assert removed == 1
    assert _paths(db_path) == {str(sibling)}


def test_regex_removal_is_anchored_at_both_ends(db_path, dup_tree):
    """The same guarantee through the regex path: fullmatch, not match."""
    target = dup_tree.left / "unique-left.txt"
    sibling = dup_tree.left / "unique-left.txt.bak"
    sibling.write_bytes(b"a different file whose path starts with the target's\n")
    _record(db_path, target)
    _record(db_path, sibling)

    removed = remove_records_by_regex(db_path, re.escape(str(target)))

    assert removed == 1
    assert _paths(db_path) == {str(sibling)}


def test_regex_removal_can_still_take_a_subtree_when_asked(db_path, dup_tree):
    """Deleting a subtree stays possible -- it just has to be explicit."""
    for path in (dup_tree.left / "unique-left.txt", *dup_tree.duplicated[0]):
        _record(db_path, path)
    survivor = dup_tree.right / "unique-right.txt"
    _record(db_path, survivor)

    removed = remove_records_by_regex(db_path, re.escape(str(dup_tree.left)) + "/.*")

    assert removed == 2  # unique-left.txt and left/shared-one.txt
    assert _paths(db_path) == {str(dup_tree.duplicated[0][1]), str(survivor)}


def test_exact_removal_of_an_absent_path_removes_nothing(db_path, dup_tree):
    kept = dup_tree.left / "unique-left.txt"
    _record(db_path, kept)

    removed = remove_record_by_path(db_path, str(dup_tree.left / "never-recorded.txt"))

    assert removed == 0
    assert _paths(db_path) == {str(kept)}
