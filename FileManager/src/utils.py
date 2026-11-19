import logging
import os

from src.md5sum import compute_md5
from src.regular_files import SkippedEntries, walk_regular_files


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
    """Map every regular file under `directory` to its MD5 checksum.

    Anything else -- a symlink, a device, a FIFO, a socket -- is not read, and
    is logged and counted instead (#74).
    """
    files_md5 = {}
    skipped = SkippedEntries()
    for file_path in walk_regular_files(directory, skipped):
        files_md5[file_path] = compute_md5(file_path)
    not_regular = skipped.summary_line()
    if not_regular:
        logging.warning(f"{directory}: {not_regular}")
    return files_md5


# Credential-shaped names never go through report_settings: its whole job is to
# print, and Development-Principles section 2 says the helper should refuse
# rather than trust each call site to remember.
_CREDENTIAL_NAMES = ('key', 'token', 'secret', 'password', 'passwd', 'credential')


def report_settings(action, settings, emit=print):
    """Print the name, resolved value and origin of every setting for a run.

    `settings` is a sequence of (name, value, origin) where origin is 'set' or
    'default'. Printed before any work, so a log records what the run was
    CONFIGURED to do and not merely what it did -- see
    docs/Development-Principles.md section 2. The value of a setting at the
    moment a run happened is not recoverable afterwards.

    Raises:
        ValueError: if a setting's name looks like a credential.
    """
    for name, _value, _origin in settings:
        lowered = name.lower()
        if any(bad in lowered for bad in _CREDENTIAL_NAMES):
            raise ValueError(
                f"refusing to report setting {name!r}: this output is printed "
                f"and written to disk, so credentials must not pass through it"
            )
    emit(f"{action} settings:")
    width = max((len(n) for n, _, _ in settings), default=0)
    for name, value, origin in settings:
        emit(f"  {name.ljust(width)} = {value}  ({origin})")
