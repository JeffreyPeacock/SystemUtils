import logging
import os

from src.md5sum import compute_md5
from src.regular_files import SkippedEntries, walk_regular_files


def is_valid_utf8(path):
    """True when `path` is a str that UTF-8 can encode as it is (#82).

    Python decodes a file name that is not valid UTF-8 with `surrogateescape`,
    so the byte 0x82 becomes the character U+DC82. Such a str cannot be
    encoded as UTF-8 in strict mode: not by `print()` in a UTF-8 locale, and
    not by sqlite3 (#83).
    """
    try:
        path.encode('utf-8')
    except UnicodeEncodeError:
        return False
    return True


def shell_quoted(path):
    """`path` as a bash `$'...'` string that holds its exact bytes (#82).

    The owner's requirement: a name that is not valid UTF-8 must be reported
    in a form that `mv` accepts, so the operator can rename the file. Python's
    own `\\udc82` escape is not the byte on disk, and no shell reads it.

    Printable ASCII is kept as it is, except `'` and `\\`. Every other byte,
    including each byte of a valid multibyte character, is written as `\\xHH`,
    so the output is plain ASCII whatever the name holds.
    """
    raw = path.encode('utf-8', 'surrogateescape')
    body = ''.join(
        chr(b) if 0x20 <= b < 0x7f and b not in (0x27, 0x5c) else f'\\x{b:02x}'
        for b in raw
    )
    return f"$'{body}'"


def display_path(path):
    """`path` ready for stdout: unchanged when it is valid UTF-8, otherwise in
    `shell_quoted` form (#82). A row with no path (#68) prints as `None`."""
    if not isinstance(path, str):
        return str(path)
    return path if is_valid_utf8(path) else shell_quoted(path)


def name_to_rename(path):
    """The shortest leading part of `path` that ends in a name that is not
    valid UTF-8 (#82).

    Every file under a directory with such a name fails, and renaming the
    directory fixes them all. So the summary lists the directory once, with a
    count, and not every file under it.
    """
    parts = path.split('/')
    for i, part in enumerate(parts):
        if not is_valid_utf8(part):
            return '/'.join(parts[:i + 1])
    return path


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
