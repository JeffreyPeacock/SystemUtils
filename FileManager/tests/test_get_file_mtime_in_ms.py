import unittest
import os
import tempfile
from src.utils import get_file_mtime_in_ms

class TestGetFileMtimeInMs(unittest.TestCase):

    def setUp(self):
        # Create a temporary file for testing
        self.temp_file = tempfile.NamedTemporaryFile(delete=False)
        self.temp_file.close()

    def tearDown(self):
        # Remove the temporary file after tests
        os.remove(self.temp_file.name)

    def test_get_file_mtime_in_ms_valid_file(self):
        # Test with a valid file path
        mtime = get_file_mtime_in_ms(self.temp_file.name)
        self.assertIsInstance(mtime, int)
        self.assertGreater(mtime, 0)

    def test_get_file_mtime_in_ms_nonexistent_file(self):
        # Test with a non-existent file path
        with self.assertRaises(FileNotFoundError):
            get_file_mtime_in_ms('/path/to/nonexistent/file.txt')

    def test_get_file_mtime_in_ms_directory(self):
        # Test with a directory path
        dir_path = tempfile.mkdtemp()
        try:
            mtime = get_file_mtime_in_ms(dir_path)
            self.assertIsInstance(mtime, int)
            self.assertGreater(mtime, 0)
        finally:
            os.rmdir(dir_path)

    def test_get_file_mtime_in_ms_empty_string(self):
        # Test with an empty string as file path
        with self.assertRaises(FileNotFoundError):
            get_file_mtime_in_ms('')

    def test_get_file_mtime_in_ms_none(self):
        # Test with None as file path
        with self.assertRaises(TypeError):
            get_file_mtime_in_ms(None)

    def test_get_file_mtime_in_ms_special_characters(self):
        # Test with a file path containing special characters
        special_file = tempfile.NamedTemporaryFile(prefix='!@#$', delete=False)
        special_file.close()
        try:
            mtime = get_file_mtime_in_ms(special_file.name)
            self.assertIsInstance(mtime, int)
            self.assertGreater(mtime, 0)
        finally:
            os.remove(special_file.name)

    def test_get_file_mtime_in_ms_symlink(self):
        # Test with a symbolic link
        symlink_path = self.temp_file.name + '_symlink'
        os.symlink(self.temp_file.name, symlink_path)
        try:
            mtime = get_file_mtime_in_ms(symlink_path)
            self.assertIsInstance(mtime, int)
            self.assertGreater(mtime, 0)
        finally:
            os.remove(symlink_path)

if __name__ == '__main__':
    unittest.main()
