"""Brotli compression helper."""
import os
from typing import Optional

try:
    import brotli
    HAS_BROTLI = True
except ImportError:
    import zlib
    HAS_BROTLI = False


def compress_bytes(data: bytes, quality: int = 11) -> bytes:
    """Compresses bytes with brotli (quality 11) or zlib (level 9)."""
    if HAS_BROTLI:
        return brotli.compress(data, quality=quality)
    else:
        return zlib.compress(data, level=9)


def write_file_and_compressed(path: str, data: bytes):
    """Writes raw binary file and its companion .br file."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'wb') as f:
        f.write(data)
    br_path = path + '.br'
    compressed = compress_bytes(data)
    with open(br_path, 'wb') as f:
        f.write(compressed)
