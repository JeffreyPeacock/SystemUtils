import hashlib
import os
import stat

from src.regular_files import NotARegularFile, file_kind, require_regular_file


def compute_md5(file_path):
    """
    Compute the MD5 checksum of a regular file.

    Refuses anything else with `NotARegularFile`, before opening it (#74). The
    path is opened with `O_NOFOLLOW`, so a symlink is refused even if one
    replaced the file after the check, and with `O_NONBLOCK`, so a FIFO that
    replaced it cannot block the `open()`. The descriptor is then checked with
    `fstat`, so the file that is read is the file that was checked. On Linux,
    `O_NONBLOCK` has no effect on reads from a regular file.

    Args:
        file_path (str): The path to the file for which the MD5 checksum is to be computed.

    Returns:
        str: The computed MD5 checksum as a hexadecimal string.
    """
    require_regular_file(file_path)
    fd = os.open(file_path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    with os.fdopen(fd, "rb") as f:
        mode = os.fstat(f.fileno()).st_mode
        if not stat.S_ISREG(mode):
            raise NotARegularFile(file_path, file_kind(mode))
        hash_md5 = hashlib.md5()
        for chunk in iter(lambda: f.read(4096), b""):
            hash_md5.update(chunk)
    return hash_md5.hexdigest()
