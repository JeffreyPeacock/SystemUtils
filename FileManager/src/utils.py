import os

from src.md5sum import compute_md5


def get_file_mtime_in_ms(file_path):
    """
    Get the last modified time of a file in milliseconds.

    Args:
        file_path (str): The path to the file.

    Returns:
        int: The last modified time in milliseconds.
    """
    return int(os.path.getmtime(file_path) * 1000)

def get_files_with_md5(directory):
    """Get a dictionary of files and their MD5 checksums in a directory."""
    files_md5 = {}
    for root, _, files in os.walk(directory):
        for file in files:
            file_path = os.path.join(root, file)
            files_md5[file_path] = compute_md5(file_path)
    return files_md5
