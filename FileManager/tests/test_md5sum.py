import unittest
import os
from src.md5sum import compute_md5

class TestComputeMD5(unittest.TestCase):

    def setUp(self):
        # Create a temporary file for testing
        self.test_file_path = 'test_file.txt'
        with open(self.test_file_path, 'w') as f:
            f.write('This is a test file.')

    def tearDown(self):
        # Remove the temporary file after testing
        if os.path.exists(self.test_file_path):
            os.remove(self.test_file_path)

    def test_compute_md5(self):
        # Test the MD5 computation of the test file
        expected_md5 = '3de8f8b0dc94b8c2230fab9ec0ba0506'
        self.assertEqual(compute_md5(self.test_file_path), expected_md5)

    def test_compute_md5_empty_file(self):
        # Test the MD5 computation of an empty file
        empty_file_path = 'empty_file.txt'
        with open(empty_file_path, 'w') as f:
            pass
        expected_md5 = 'd41d8cd98f00b204e9800998ecf8427e'
        self.assertEqual(compute_md5(empty_file_path), expected_md5)
        os.remove(empty_file_path)

    def test_compute_md5_nonexistent_file(self):
        # Test the MD5 computation of a nonexistent file
        with self.assertRaises(FileNotFoundError):
            compute_md5('nonexistent_file.txt')

if __name__ == '__main__':
    unittest.main()