import pytest
from pygit.repository import create_repo
from pygit.objects import hash_object, read_object, BadObjectError


def test_hash_object_matches_git_blob_sha(tmp_path):
    repo = create_repo(tmp_path)
    sha = hash_object(repo, b"hello world\n", "blob", write=True)
    assert sha == "3b18e512dba79e4c8300dd08aeb37f8e728b8dad"


def test_hash_object_write_false_does_not_store(tmp_path):
    repo = create_repo(tmp_path)
    sha = hash_object(repo, b"not stored", "blob", write=False)
    with pytest.raises(BadObjectError):
        read_object(repo, sha)


def test_read_object_round_trips(tmp_path):
    repo = create_repo(tmp_path)
    sha = hash_object(repo, b"round trip content", "blob", write=True)
    type_, content = read_object(repo, sha)
    assert type_ == "blob"
    assert content == b"round trip content"


def test_read_object_missing_raises(tmp_path):
    repo = create_repo(tmp_path)
    with pytest.raises(BadObjectError):
        read_object(repo, "0" * 40)


def _build_single_entry_idx(sha_hex, offset):
    import struct
    first_byte = int(sha_hex[:2], 16)
    fanout = [0] * 256
    for b in range(first_byte, 256):
        fanout[b] = 1
    body = struct.pack(">4sI", b"\xff\x74\x4f\x63", 2)
    body += struct.pack(">256I", *fanout)
    body += bytes.fromhex(sha_hex)
    body += struct.pack(">I", 0)
    body += struct.pack(">I", offset)
    body += b"\x00" * 40
    return body


def test_read_object_falls_back_to_packs(tmp_path):
    import os
    import struct
    import hashlib
    import zlib

    repo = create_repo(tmp_path)
    content = b"packed only\n"
    sha = hashlib.sha1(f"blob {len(content)}\0".encode() + content).hexdigest()
    compressed = zlib.compress(content)
    pack_header = struct.pack(">4sII", b"PACK", 2, 1)
    pack_body = bytes([(3 << 4) | len(content)]) + compressed
    pack_bytes = pack_header + pack_body + b"\x00" * 20

    pack_dir = os.path.join(repo.gitdir, "objects", "pack")
    os.makedirs(pack_dir)
    with open(os.path.join(pack_dir, "pack-x.pack"), "wb") as f:
        f.write(pack_bytes)
    with open(os.path.join(pack_dir, "pack-x.idx"), "wb") as f:
        f.write(_build_single_entry_idx(sha, len(pack_header)))

    type_, result_content = read_object(repo, sha)
    assert type_ == "blob"
    assert result_content == content

