import os
import sqlite3
import unittest
from src.db import (
    initialize_db, get_file_info, get_all_files_info, store_file_info,
    remove_record, remove_records_by_regex, get_md5_by_path,
    check_for_duplicates, find_duplicates_with_min_count, audit_db
)
from src.md5sum import compute_md5
from src.utils import get_file_mtime_in_ms

class TestDBFunctions(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.db_path = 'test.db'
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
        os.remove(cls.db_path)

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
        remove_record(self.db_path, file_path)
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

    def test_check_for_duplicates(self):
        file_name = 'test-file.txt'
        file_path1 = os.path.join(self.test_data_dir, file_name)
        file_path2 = os.path.join(self.duplicate_data_dir, file_name)
        store_file_info(self.db_path, file_path1, compute_md5(file_path1))
        store_file_info(self.db_path, file_path2, compute_md5(file_path2))
        duplicates = check_for_duplicates(self.db_path, compute_md5(file_path1))
        self.assertEqual(len(duplicates), 2)
        self.assertIn((file_path1,), duplicates)
        self.assertIn((file_path2,), duplicates)

    def test_find_duplicates_with_min_count(self):
        file_name = 'test-file.txt'
        file_path1 = os.path.join(self.test_data_dir, file_name)
        file_path2 = os.path.join(self.duplicate_data_dir, file_name)
        store_file_info(self.db_path, file_path1, compute_md5(file_path1))
        store_file_info(self.db_path, file_path2, compute_md5(file_path2))
        duplicates = find_duplicates_with_min_count(self.db_path, min_count=1)
        self.assertIn(compute_md5(file_path1), duplicates)
        self.assertIn(file_path1, duplicates[compute_md5(file_path1)])
        self.assertIn(file_path2, duplicates[compute_md5(file_path1)])

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

if __name__ == '__main__':
    unittest.main()