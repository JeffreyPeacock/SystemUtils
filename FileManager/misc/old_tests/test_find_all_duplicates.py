import unittest
import sqlite3
from src.db import initialize_db, store_file_info, find_all_duplicates

class TestFindAllDuplicates(unittest.TestCase):
    def setUp(self):
        # Set up a test database
        self.conn = sqlite3.connect(':memory:')
        self.cursor = self.conn.cursor()
        self.cursor.execute('''
            CREATE TABLE files (
                id INTEGER PRIMARY KEY,
                path TEXT UNIQUE,
                md5sum TEXT
            )
        ''')
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def test_find_all_duplicates(self):
        # Insert test data
        store_file_info(self.conn, 'file1.txt', 'md5sum1')
        store_file_info(self.conn, 'file2.txt', 'md5sum1')
        store_file_info(self.conn, 'file3.txt', 'md5sum2')
        store_file_info(self.conn, 'file4.txt', 'md5sum2')
        store_file_info(self.conn, 'file5.txt', 'md5sum3')

        # Find duplicates
        duplicates = find_all_duplicates(self.conn)

        # Check the results
        expected_duplicates = {
            'md5sum1': ['file1.txt', 'file2.txt'],
            'md5sum2': ['file3.txt', 'file4.txt']
        }
        self.assertEqual(duplicates, expected_duplicates)

if __name__ == '__main__':
    unittest.main()