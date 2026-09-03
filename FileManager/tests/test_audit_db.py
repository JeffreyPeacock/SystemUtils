import unittest
import os
import sqlite3
import tempfile
import shutil
from unittest.mock import patch
from src.main import audit_db
from src.db import initialize_db, remove_record, store_file_info
from src.md5sum import compute_md5


class TestAuditDB(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.db_path = 'test_audit.db'
        cls.test_data_dir = tempfile.mkdtemp()

    def setUp(self):
        self.conn = sqlite3.connect(self.db_path)
        self.cursor = self.conn.cursor()
        initialize_db(self.db_path)
        self.conn.commit()

    def tearDown(self):
        self.cursor.close()
        self.conn.close()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.test_data_dir)
        os.remove(cls.db_path)

    def test_audit_db_file_removed(self):
        file_path = os.path.join(self.test_data_dir, 'test-file.txt')
        with open(file_path, 'w') as f:
            f.write('test content')

        # Use store_file_info to insert file info into the database
        md5sum = compute_md5(file_path)
        store_file_info(self.db_path, file_path, md5sum)

        os.remove(file_path)  # Remove the file to simulate a missing file

        with patch('src.db.remove_record') as mock_remove_file_info:
            audit_db(self.db_path, 2, process_file=lambda path, db: None)
            mock_remove_file_info.assert_called_once_with(self.db_path, file_path)

    # def test_audit_db_file_reprocessed(self):
    #     file_path = os.path.join(self.test_data_dir, 'test-file.txt')
    #     with open(file_path, 'w') as f:
    #         f.write('test content')
    #     size = os.path.getsize(file_path)
    #     last_modified = int(os.path.getmtime(file_path) * 1000)
    #     self.cursor.execute('INSERT INTO files (path, size, last_modified) VALUES (?, ?, ?)', (file_path, size, last_modified))
    #     self.conn.commit()
    #
    #     # Modify the file to simulate a change
    #     with open(file_path, 'a') as f:
    #         f.write(' more content')
    #     new_size = os.path.getsize(file_path)
    #     new_last_modified = int(os.path.getmtime(file_path) * 1000)
    #
    #     with patch('src.db.process_file') as mock_process_file:
    #         audit_db(self.db_path, 2)
    #         mock_process_file.assert_called_once_with(file_path, self.db_path)
    #
    # def test_audit_db_no_changes(self):
    #     file_path = os.path.join(self.test_data_dir, 'test-file.txt')
    #     with open(file_path, 'w') as f:
    #         f.write('test content')
    #     size = os.path.getsize(file_path)
    #     last_modified = int(os.path.getmtime(file_path) * 1000)
    #     self.cursor.execute('INSERT INTO files (path, size, last_modified) VALUES (?, ?, ?)', (file_path, size, last_modified))
    #     self.conn.commit()
    #
    #     with patch('src.db.process_file') as mock_process_file:
    #         audit_db(self.db_path, 2)
    #         mock_process_file.assert_not_called()
    #
    # def test_audit_db_empty_db(self):
    #     with patch('src.db.process_file') as mock_process_file:
    #         audit_db(self.db_path, 2)
    #         mock_process_file.assert_not_called()

if __name__ == '__main__':
    unittest.main()