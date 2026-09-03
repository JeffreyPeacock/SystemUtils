import hashlib

def compute_md5(file_path):
    """
    Compute the MD5 checksum of a file.

    Args:
        file_path (str): The path to the file for which the MD5 checksum is to be computed.

    Returns:
        str: The computed MD5 checksum as a hexadecimal string.
    """
    hash_md5 = hashlib.md5()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hash_md5.update(chunk)
    return hash_md5.hexdigest()

