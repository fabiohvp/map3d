"""UOP archive reader with Jenkins lookup3 hashlittle2."""
import struct
import zlib
from typing import Dict, Tuple, Optional

M = 0xFFFFFFFF


def rot(x: int, k: int) -> int:
    return ((x << k) | (x >> (32 - k))) & M


def hashlittle2(s: bytes) -> int:
    """Jenkins lookup3 hashlittle2 hash, returning (pb << 32) | pc."""
    length = len(s)
    a = b = c = (0xDEADBEEF + length) & M
    k = 0
    while length > 12:
        a = (a + (s[k] | s[k + 1] << 8 | s[k + 2] << 16 | s[k + 3] << 24)) & M
        b = (b + (s[k + 4] | s[k + 5] << 8 | s[k + 6] << 16 | s[k + 7] << 24)) & M
        c = (c + (s[k + 8] | s[k + 9] << 8 | s[k + 10] << 16 | s[k + 11] << 24)) & M
        a = (a - c) & M; a ^= rot(c, 4); c = (c + b) & M
        b = (b - a) & M; b ^= rot(a, 6); a = (a + c) & M
        c = (c - b) & M; c ^= rot(b, 8); b = (b + a) & M
        a = (a - c) & M; a ^= rot(c, 16); c = (c + b) & M
        b = (b - a) & M; b ^= rot(a, 19); a = (a + c) & M
        c = (c - b) & M; c ^= rot(b, 4); b = (b + a) & M
        length -= 12
        k += 12
    if length == 0:
        return (b << 32) | c
    t = s[k:] + b'\0' * 12
    if length >= 12: c = (c + (t[11] << 24)) & M
    if length >= 11: c = (c + (t[10] << 16)) & M
    if length >= 10: c = (c + (t[9] << 8)) & M
    if length >= 9: c = (c + t[8]) & M
    if length >= 8: b = (b + (t[7] << 24)) & M
    if length >= 7: b = (b + (t[6] << 16)) & M
    if length >= 6: b = (b + (t[5] << 8)) & M
    if length >= 5: b = (b + t[4]) & M
    if length >= 4: a = (a + (t[3] << 24)) & M
    if length >= 3: a = (a + (t[2] << 16)) & M
    if length >= 2: a = (a + (t[1] << 8)) & M
    if length >= 1: a = (a + t[0]) & M
    c ^= b; c = (c - rot(b, 14)) & M
    a ^= c; a = (a - rot(c, 11)) & M
    b ^= a; b = (b - rot(a, 25)) & M
    c ^= b; c = (c - rot(b, 16)) & M
    a ^= c; a = (a - rot(c, 4)) & M
    b ^= a; b = (b - rot(a, 14)) & M
    c ^= b; c = (c - rot(b, 24)) & M
    return (b << 32) | c


class UopReader:
    """Reader for Ultima Online UOP archives."""

    def __init__(self, filepath: str):
        self.filepath = filepath
        self.file = open(filepath, 'rb')
        self.entries: Dict[int, Tuple[int, int, int, int]] = {}
        self._load_table()

    def _load_table(self):
        self.file.seek(0)
        magic, ver, sig, nxt, bsz, cnt = struct.unpack('<4sIIQII', self.file.read(28))
        if magic != b'MYP\0':
            raise ValueError(f"Invalid UOP header magic in {self.filepath}: {magic}")
        self.version = ver

        while nxt != 0:
            self.file.seek(nxt)
            fc, nxt = struct.unpack('<IQ', self.file.read(12))
            for _ in range(fc):
                off, hl, cl, dl, h, adl, flag = struct.unpack('<QIIIQIH', self.file.read(34))
                if off:
                    # data is at off + hl
                    self.entries[h] = (off + hl, cl, dl, flag)

    def read_entry_by_hash(self, hash_val: int) -> Optional[bytes]:
        if hash_val not in self.entries:
            return None
        off, cl, dl, flag = self.entries[hash_val]
        self.file.seek(off)
        data = self.file.read(cl)
        if flag == 1:
            data = zlib.decompress(data)
        return data

    def read_entry(self, name: str) -> Optional[bytes]:
        h = hashlittle2(name.lower().encode('ascii'))
        return self.read_entry_by_hash(h)

    def close(self):
        if self.file:
            self.file.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
