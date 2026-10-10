import pytest
import struct
import hashlib
import os
import zlib
import tempfile

from pygit.objects import hash_object
from pygit.pack import (
    encode_object_header, parse_object_header,
    write_pack, read_pack_index, read_object_from_packs,
    index_pack,
    OBJ_BLOB, OBJ_COMMIT, OBJ_TREE, OBJ_TAG,
)
from pygit.repository import create_repo


def _make_repo(tmp_path):
    return create_repo(str(tmp_path))


def test_encode_header_single_byte_blob():
    data = encode_object_header(OBJ_BLOB, 0)
    type_id, size, end = parse_object_header(data, 0)
    assert type_id == OBJ_BLOB and size == 0 and end == len(data)


def test_encode_header_single_byte_max():
    data = encode_object_header(OBJ_COMMIT, 15)
    type_id, size, end = parse_object_header(data, 0)
    assert type_id == OBJ_COMMIT and size == 15 and end == 1


def test_encode_header_two_bytes():
    data = encode_object_header(OBJ_TREE, 16)
    type_id, size, end = parse_object_header(data, 0)
    assert type_id == OBJ_TREE and size == 16 and end == 2


def test_encode_header_large_size():
    data = encode_object_header(OBJ_TAG, 123456)
    type_id, size, end = parse_object_header(data, 0)
    assert type_id == OBJ_TAG and size == 123456 and end == len(data)


def test_encode_header_all_base_types():
    for type_id in (1, 2, 3, 4):
        for size in (0, 1, 15, 16, 127, 128, 65535, 65536):
            data = encode_object_header(type_id, size)
            rt_type, rt_size, rt_end = parse_object_header(data, 0)
            assert rt_type == type_id and rt_size == size


def test_write_pack_header_magic_and_version(tmp_path):
    repo = _make_repo(tmp_path)
    sha = hash_object(repo, b"hello", "blob", write=True)
    pack_path = str(tmp_path / "test.pack")
    idx_path  = str(tmp_path / "test.idx")
    write_pack(repo, [sha], pack_path, idx_path)
    with open(pack_path, "rb") as f:
        data = f.read()
    magic, version, count = struct.unpack(">4sII", data[:12])
    assert magic == b"PACK" and version == 2 and count == 1


def test_write_pack_trailing_sha_matches_body(tmp_path):
    repo = _make_repo(tmp_path)
    sha = hash_object(repo, b"world", "blob", write=True)
    pack_path = str(tmp_path / "test.pack")
    idx_path  = str(tmp_path / "test.idx")
    write_pack(repo, [sha], pack_path, idx_path)
    with open(pack_path, "rb") as f:
        data = f.read()
    body, trailer = data[:-20], data[-20:]
    assert hashlib.sha1(body).digest() == trailer


def test_write_pack_object_is_readable_back(tmp_path):
    repo = _make_repo(tmp_path)
    content = b"pack round trip"
    sha = hash_object(repo, content, "blob", write=True)
    pack_dir = os.path.join(repo.worktree, ".git", "objects", "pack")
    os.makedirs(pack_dir, exist_ok=True)
    pack_path = os.path.join(pack_dir, "pack-test.pack")
    idx_path  = os.path.join(pack_dir, "pack-test.idx")
    write_pack(repo, [sha], pack_path, idx_path)
    result = read_object_from_packs(repo, sha)
    assert result == ("blob", content)


def test_write_pack_multiple_objects(tmp_path):
    repo = _make_repo(tmp_path)
    shas = [hash_object(repo, f"obj{i}".encode(), "blob", write=True) for i in range(5)]
    pack_dir = os.path.join(repo.worktree, ".git", "objects", "pack")
    os.makedirs(pack_dir, exist_ok=True)
    pack_path = os.path.join(pack_dir, "pack-test.pack")
    idx_path  = os.path.join(pack_dir, "pack-test.idx")
    write_pack(repo, shas, pack_path, idx_path)
    for sha in shas:
        type_, data = read_object_from_packs(repo, sha)
        assert type_ == "blob"


def test_write_pack_returns_pack_sha(tmp_path):
    repo = _make_repo(tmp_path)
    sha = hash_object(repo, b"retval", "blob", write=True)
    pack_path = str(tmp_path / "test.pack")
    idx_path  = str(tmp_path / "test.idx")
    pack_sha = write_pack(repo, [sha], pack_path, idx_path)
    assert len(pack_sha) == 40 and all(c in "0123456789abcdef" for c in pack_sha)
    with open(pack_path, "rb") as f:
        data = f.read()
    assert data[-20:].hex() == pack_sha


def test_idx_magic_and_version(tmp_path):
    repo = _make_repo(tmp_path)
    sha = hash_object(repo, b"idx test", "blob", write=True)
    pack_path = str(tmp_path / "t.pack")
    idx_path  = str(tmp_path / "t.idx")
    write_pack(repo, [sha], pack_path, idx_path)
    with open(idx_path, "rb") as f:
        data = f.read()
    assert data[:4] == b"\xff\x74\x4f\x63"
    assert struct.unpack(">I", data[4:8])[0] == 2


def test_idx_fanout_correctness(tmp_path):
    repo = _make_repo(tmp_path)
    shas = [hash_object(repo, f"fanout{i}".encode(), "blob", write=True) for i in range(6)]
    pack_path = str(tmp_path / "t.pack")
    idx_path  = str(tmp_path / "t.idx")
    write_pack(repo, shas, pack_path, idx_path)
    with open(idx_path, "rb") as f:
        raw = f.read()
    fanout = struct.unpack(">256I", raw[8:8 + 256*4])
    assert fanout[255] == len(shas)
    for b in range(256):
        expected = sum(1 for s in shas if int(s[:2], 16) <= b)
        assert fanout[b] == expected


def test_idx_sha_list_is_sorted(tmp_path):
    repo = _make_repo(tmp_path)
    shas = [hash_object(repo, f"sort{i}".encode(), "blob", write=True) for i in range(4)]
    pack_path = str(tmp_path / "t.pack")
    idx_path  = str(tmp_path / "t.idx")
    write_pack(repo, shas, pack_path, idx_path)
    result = read_pack_index(idx_path)
    keys = list(result.keys())
    assert keys == sorted(keys)


def test_idx_crc32_correctness(tmp_path):
    repo = _make_repo(tmp_path)
    content = b"crc check"
    sha = hash_object(repo, content, "blob", write=True)
    pack_path = str(tmp_path / "t.pack")
    idx_path  = str(tmp_path / "t.idx")
    write_pack(repo, [sha], pack_path, idx_path)
    with open(pack_path, "rb") as pf:
        pack_data = pf.read()
    with open(idx_path, "rb") as f:
        raw = f.read()
    fanout = struct.unpack(">256I", raw[8:8+256*4])
    n = fanout[255]
    shas_start = 8 + 256*4
    crcs_start = shas_start + n * 20
    result = read_pack_index(idx_path)
    for i, s in enumerate(sorted(result.keys())):
        offset = result[s]
        stored_crc = struct.unpack(">I", raw[crcs_start + i*4: crcs_start + i*4 + 4])[0]
        from pygit.pack import parse_object_header as poh
        _, _, header_end = poh(pack_data, offset)
        decomp = zlib.decompressobj()
        remaining = pack_data[header_end:]
        decomp.decompress(remaining)
        decomp.flush()
        consumed = len(remaining) - len(decomp.unused_data)
        compressed_bytes = pack_data[offset: header_end + consumed]
        assert stored_crc == zlib.crc32(compressed_bytes) & 0xFFFFFFFF


def test_idx_trailing_checksum(tmp_path):
    repo = _make_repo(tmp_path)
    sha = hash_object(repo, b"chk", "blob", write=True)
    pack_path = str(tmp_path / "t.pack")
    idx_path  = str(tmp_path / "t.idx")
    write_pack(repo, [sha], pack_path, idx_path)
    with open(idx_path, "rb") as f:
        raw = f.read()
    body, trailer = raw[:-20], raw[-20:]
    assert hashlib.sha1(body).digest() == trailer


def test_index_pack_regenerates_readable_idx(tmp_path):
    repo = _make_repo(tmp_path)
    shas = [hash_object(repo, f"regen{i}".encode(), "blob", write=True) for i in range(3)]
    pack_dir = os.path.join(repo.worktree, ".git", "objects", "pack")
    os.makedirs(pack_dir, exist_ok=True)
    pack_path = os.path.join(pack_dir, "pack-test.pack")
    idx_path  = os.path.join(pack_dir, "pack-test.idx")
    write_pack(repo, shas, pack_path, idx_path)
    os.remove(idx_path)
    index_pack(pack_path, idx_path)
    for sha in shas:
        type_, content = read_object_from_packs(repo, sha)
        assert type_ == "blob"


def test_index_pack_crc32_matches_after_regen(tmp_path):
    repo = _make_repo(tmp_path)
    content = b"regen crc"
    sha = hash_object(repo, content, "blob", write=True)
    pack_path = str(tmp_path / "regen.pack")
    idx_path  = str(tmp_path / "regen.idx")
    write_pack(repo, [sha], pack_path, idx_path)
    with open(idx_path, "rb") as f:
        original = f.read()
    os.remove(idx_path)
    index_pack(pack_path, idx_path)
    with open(idx_path, "rb") as f:
        regenerated = f.read()
    assert original == regenerated


def test_index_pack_rejects_bad_magic(tmp_path):
    bad = tmp_path / "bad.pack"
    bad.write_bytes(b"JUNK" + b"\x00" * 100)
    from pygit.pack import InvalidPackError
    with pytest.raises(InvalidPackError):
        index_pack(str(bad), str(tmp_path / "bad.idx"))
