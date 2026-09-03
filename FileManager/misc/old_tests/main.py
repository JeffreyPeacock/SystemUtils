import unittest
from unittest.mock import patch, MagicMock
import os
import sys
from io import StringIO
from src.main import main, scan_directory

class TestFileManagerMain(unittest.TestCase):

    def setUp(self):
        self.test_data_dir = os.path.join(os.path.dirname(__file__), '..', 'data', 'data')

    @patch('src.main.store_file_info')
    @patch('src.main.compute_md5')
    @patch('src.main.scan_directory')
    def test_scan_dir(self, mock_scan_directory, mock_compute_md5, mock_store_file_info):
        mock_scan_directory.return_value = [
            os.path.join(self.test_data_dir, 'test-file-01.txt'),
            os.path.join(self.test_data_dir, 'test-file-02.txt')
        ]
        mock_compute_md5.side_effect = ['md5sum1', 'md5sum2']

        test_args = ['main.py', 'scan_dir', self.test_data_dir]
        with patch.object(sys, 'argv', test_args):
            main()

        mock_scan_directory.assert_called_once_with(self.test_data_dir)
        self.assertEqual(mock_compute_md5.call_count, 2)
        self.assertEqual(mock_store_file_info.call_count, 2)

    @patch('src.main.store_file_info')
    @patch('src.main.compute_md5')
    def test_scan_file(self, mock_compute_md5, mock_store_file_info):
        mock_compute_md5.return_value = 'md5sum1'
        test_file_path = os.path.join(self.test_data_dir, 'test-file-01.txt')

        test_args = ['main.py', 'scan_file', test_file_path]
        with patch.object(sys, 'argv', test_args):
            main()

        mock_compute_md5.assert_called_once_with(test_file_path)
        mock_store_file_info.assert_called_once_with(test_file_path, 'md5sum1')

    @patch('src.main.check_for_duplicates')
    @patch('src.main.compute_md5')
    def test_check_file(self, mock_compute_md5, mock_check_for_duplicates):
        mock_compute_md5.return_value = 'md5sum1'
        mock_check_for_duplicates.return_value = [(os.path.join(self.test_data_dir, 'test-file-01.txt'),)]
        test_file_path = os.path.join(self.test_data_dir, 'test-file-01.txt')

        test_args = ['main.py', 'check_file', test_file_path]
        with patch.object(sys, 'argv', test_args):
            with patch('sys.stdout', new=StringIO()) as fake_out:
                main()
                self.assertIn(f'Duplicate found for {test_file_path}:', fake_out.getvalue())

        mock_compute_md5.assert_called_once_with(test_file_path)
        mock_check_for_duplicates.assert_called_once_with('md5sum1')

    @patch('src.main.store_file_info')
    @patch('src.main.check_for_duplicates')
    @patch('src.main.compute_md5')
    @patch('src.main.scan_directory')
    def test_scan_dir_report(self, mock_scan_directory, mock_compute_md5, mock_check_for_duplicates, mock_store_file_info):
        mock_scan_directory.return_value = [
            os.path.join(self.test_data_dir, 'test-file-01.txt'),
            os.path.join(self.test_data_dir, 'test-file-02.txt')
        ]
        mock_compute_md5.side_effect = ['md5sum1', 'md5sum2']
        mock_check_for_duplicates.side_effect = [[], [(os.path.join(self.test_data_dir, 'test-file-02.txt'),)]]

        test_args = ['main.py', 'scan_dir_report', self.test_data_dir]
        with patch.object(sys, 'argv', test_args):
            with patch('sys.stdout', new=StringIO()) as fake_out:
                main()
                self.assertIn(f'Duplicate found for {os.path.join(self.test_data_dir, "test-file-02.txt")}:', fake_out.getvalue())

        mock_scan_directory.assert_called_once_with(self.test_data_dir)
        self.assertEqual(mock_compute_md5.call_count, 2)
        self.assertEqual(mock_store_file_info.call_count, 2)
        self.assertEqual(mock_check_for_duplicates.call_count, 2)

    def test_scan_directory(self):
        with patch('os.walk') as mock_walk:
            mock_walk.return_value = [
                (self.test_data_dir, ('subdir',), ('test-file-01.txt', 'test-file-02.txt')),
                (os.path.join(self.test_data_dir, 'subdir'), (), ('test-file-03.txt',))
            ]
            result = scan_directory(self.test_data_dir)
            expected = [
                os.path.join(self.test_data_dir, 'test-file-01.txt'),
                os.path.join(self.test_data_dir, 'test-file-02.txt'),
                os.path.join(self.test_data_dir, 'subdir', 'test-file-03.txt')
            ]
            self.assertEqual(result, expected)

if __name__ == '__main__':
    unittest.main()