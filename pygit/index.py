import hashlib
import os
import struct
from typing import NamedTuple

from pygit.repository import repo_path

SIGNATURE = b"DIRC"
VERSION = 2
ENTRY_HEADER_FORMAT = ">10I20sH"
ENTRY_HEADER_SIZE = struct.calcsize(ENTRY_HEADER_FORMAT)


class IndexEntry(NamedTuple):
    ctime_s: int
    ctime_n: int
    mtime_s: int
    mtime_n: int
    dev: int
    ino: int
    mode: int
    uid: int
    gid: int
    size: int
    sha: str
    path: str


class InvalidIndexError(Exception):
    pass


def make_entry(path, sha, mode, st=None):
    if st is None:
        return IndexEntry(0, 0, 0, 0, 0, 0, mode, 0, 0, 0, sha, path)
    return IndexEntry(int(st.st_ctime), 0, int(st.st_mtime), 0, 0, 0, mode, 0, 0, st.st_size, sha, path)


def _entry_padded_length(name_len):
    return ((ENTRY_HEADER_SIZE + name_len + 1 + 7) // 8) * 8


def _serialize_entry(entry):
    name_bytes = entry.path.encode()
    flags = min(len(name_bytes), 0xFFF)
    header = struct.pack(
        ENTRY_HEADER_FORMAT,
        entry.ctime_s, entry.ctime_n, entry.mtime_s, entry.mtime_n,
        entry.dev, entry.ino, entry.mode, entry.uid, entry.gid, entry.size,
        bytes.fromhex(entry.sha), flags,
    )
    padded_len = _entry_padded_length(len(name_bytes))
    padding = b"\0" * (padded_len - ENTRY_HEADER_SIZE - len(name_bytes))
    return header + name_bytes + padding


def _parse_entry(data, offset):
    header = data[offset:offset + ENTRY_HEADER_SIZE]
    fields = struct.unpack(ENTRY_HEADER_FORMAT, header)
    ctime_s, ctime_n, mtime_s, mtime_n, dev, ino, mode, uid, gid, size, sha_bytes, flags = fields
    name_start = offset + ENTRY_HEADER_SIZE
    nul_index = data.index(b"\0", name_start)
    name = data[name_start:nul_index].decode()
    padded_len = _entry_padded_length(len(name.encode()))
    entry = IndexEntry(ctime_s, ctime_n, mtime_s, mtime_n, dev, ino, mode, uid, gid, size, sha_bytes.hex(), name)
    return entry, offset + padded_len


def read_index(repo):
    path = repo_path(repo, "index")
    if not os.path.exists(path):
        return []
    with open(path, "rb") as f:
        data = f.read()
    checksum = data[-20:]
    body = data[:-20]
    if hashlib.sha1(body).digest() != checksum:
        raise InvalidIndexError("index checksum mismatch")
    signature, version, count = struct.unpack(">4sII", body[:12])
    if signature != SIGNATURE or version != VERSION:
        raise InvalidIndexError("unsupported index format")
    entries = []
    offset = 12
    for _ in range(count):
        entry, offset = _parse_entry(body, offset)
        entries.append(entry)
    return entries


def write_index(repo, entries):
    entries = sorted(entries, key=lambda e: e.path)
    body = struct.pack(">4sII", SIGNATURE, VERSION, len(entries))
    for entry in entries:
        body += _serialize_entry(entry)
    checksum = hashlib.sha1(body).digest()
    with open(repo_path(repo, "index"), "wb") as f:
        f.write(body + checksum)
