import unittest
import sqlite3
import os
from src.db import initialize_db, store_file_info, get_md5_by_path, check_for_duplicates

class TestFileManagerDB(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        # Set up the database before running tests
        initialize_db()

    def setUp(self):
        # Clear the database before each test
        conn = sqlite3.connect('file_manager.db')
        cursor = conn.cursor()
        cursor.execute('DELETE FROM files')
        conn.commit()
        conn.close()

    def test_initialize_db(self):
        # Test if the database initializes correctly
        conn = sqlite3.connect('file_manager.db')
        cursor = conn.cursor()
        cursor.execute('SELECT name FROM sqlite_master WHERE type="table" AND name="files"')
        result = cursor.fetchone()
        conn.close()
        self.assertIsNotNone(result)
        self.assertEqual(result[0], 'files')

    def test_store_file_info(self):
        store_file_info('/path/to/file1.txt', 'd41d8cd98f00b204e9800998ecf8427e')
        conn = sqlite3.connect('file_manager.db')
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM files WHERE path = ?', ('/path/to/file1.txt',))
        result = cursor.fetchone()
        conn.close()
        self.assertIsNotNone(result)
        self.assertEqual(result[1], '/path/to/file1.txt')
        self.assertEqual(result[2], 'd41d8cd98f00b204e9800998ecf8427e')

    def test_get_md5_by_path(self):
        store_file_info('/path/to/file2.txt', 'd41d8cd98f00b204e9800998ecf8427e')
        md5sum = get_md5_by_path('/path/to/file2.txt')
        self.assertEqual(md5sum, 'd41d8cd98f00b204e9800998ecf8427e')

    def test_get_md5_by_path_nonexistent(self):
        md5sum = get_md5_by_path('/path/to/nonexistent.txt')
        self.assertIsNone(md5sum)

    def test_check_for_duplicates(self):
        store_file_info('/path/to/file3.txt', 'd41d8cd98f00b204e9800998ecf8427e')
        store_file_info('/path/to/file4.txt', 'd41d8cd98f00b204e9800998ecf8427e')
        duplicates = check_for_duplicates('d41d8cd98f00b204e9800998ecf8427e')
        self.assertEqual(len(duplicates), 2)
        self.assertIn(('/path/to/file3.txt',), duplicates)
        self.assertIn(('/path/to/file4.txt',), duplicates)

    def test_check_for_duplicates_none(self):
        store_file_info('/path/to/file5.txt', 'd41d8cd98f00b204e9800998ecf8427e')
        duplicates = check_for_duplicates('nonexistent_md5sum')
        self.assertEqual(len(duplicates), 0)


if __name__ == '__main__':
    unittest.main()
