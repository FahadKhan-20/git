from pygit.pack import OBJ_BLOB, OBJ_OFS_DELTA, parse_object_header, parse_ofs_delta_offset


def test_parse_object_header_single_byte_size():
    data = bytes([0x3D])
    type_id, size, next_offset = parse_object_header(data, 0)
    assert type_id == OBJ_BLOB
    assert size == 13
    assert next_offset == 1


def test_parse_object_header_multi_byte_size():
    data = bytes([0xB8, 0x0C])
    type_id, size, next_offset = parse_object_header(data, 0)
    assert type_id == OBJ_BLOB
    assert size == 200
    assert next_offset == 2


def test_parse_object_header_reads_at_nonzero_offset():
    data = bytes([0xFF, 0x3D])
    type_id, size, next_offset = parse_object_header(data, 1)
    assert type_id == OBJ_BLOB
    assert size == 13
    assert next_offset == 2


def test_parse_ofs_delta_offset_single_byte():
    value, next_offset = parse_ofs_delta_offset(bytes([0x05]), 0)
    assert value == 5
    assert next_offset == 1


def test_parse_ofs_delta_offset_multi_byte():
    value, next_offset = parse_ofs_delta_offset(bytes([0x80, 0x48]), 0)
    assert value == 200
    assert next_offset == 2


def test_apply_delta_pure_insert():
    import pytest
    from pygit.pack import InvalidPackError, apply_delta
    delta = bytes([0, 5, 5]) + b"hello"
    assert apply_delta(b"", delta) == b"hello"


def test_apply_delta_copy_twice_from_base():
    from pygit.pack import apply_delta
    base = b"hello"
    delta = bytes([5, 10]) + bytes([0x90, 5]) + bytes([0x90, 5])
    assert apply_delta(base, delta) == b"hellohello"


def test_apply_delta_copy_and_insert():
    from pygit.pack import apply_delta
    base = b"hello world"
    delta = bytes([11, 6]) + bytes([0x90, 5]) + bytes([1]) + b"!"
    assert apply_delta(base, delta) == b"hello!"


def test_apply_delta_zero_size_copy_means_65536():
    from pygit.pack import apply_delta
    base = bytes(range(256)) * 256
    assert len(base) == 65536
    delta = bytes([0x80, 0x80, 0x04]) + bytes([0x80, 0x80, 0x04]) + bytes([0x80])
    result = apply_delta(base, delta)
    assert result == base


def test_apply_delta_rejects_base_size_mismatch():
    import pytest
    from pygit.pack import InvalidPackError, apply_delta
    delta = bytes([99, 5]) + b"hello"
    with pytest.raises(InvalidPackError):
        apply_delta(b"", delta)


def test_apply_delta_rejects_result_size_mismatch():
    import pytest
    from pygit.pack import InvalidPackError, apply_delta
    delta = bytes([0, 99, 5]) + b"hello"
    with pytest.raises(InvalidPackError):
        apply_delta(b"", delta)


def _build_idx_v2(entries):
    import struct
    entries = sorted(entries, key=lambda e: e[0])
    fanout = [0] * 256
    for sha_hex, _ in entries:
        first_byte = int(sha_hex[:2], 16)
        for b in range(first_byte, 256):
            fanout[b] += 1
    body = struct.pack(">4sI", b"\xff\x74\x4f\x63", 2)
    body += struct.pack(">256I", *fanout)
    for sha_hex, _ in entries:
        body += bytes.fromhex(sha_hex)
    for _ in entries:
        body += struct.pack(">I", 0)
    for _, offset in entries:
        body += struct.pack(">I", offset)
    body += b"\x00" * 20
    body += b"\x00" * 20
    return body


def test_read_pack_index_returns_sha_to_offset_mapping(tmp_path):
    from pygit.pack import read_pack_index
    sha1 = bytes(range(20)).hex()
    sha2 = bytes(range(20, 40)).hex()
    idx_path = tmp_path / "pack-test.idx"
    idx_path.write_bytes(_build_idx_v2([(sha1, 100), (sha2, 250)]))
    assert read_pack_index(str(idx_path)) == {sha1: 100, sha2: 250}


def test_read_pack_index_rejects_bad_magic(tmp_path):
    import pytest
    from pygit.pack import InvalidPackError, read_pack_index
    idx_path = tmp_path / "bad.idx"
    idx_path.write_bytes(b"\x00" * 8 + b"\x00" * 1024)
    with pytest.raises(InvalidPackError):
        read_pack_index(str(idx_path))


def test_list_pack_files_finds_idx_basenames(tmp_path):
    import os
    from pygit.pack import list_pack_files
    from pygit.repository import create_repo
    repo = create_repo(tmp_path)
    pack_dir = os.path.join(repo.gitdir, "objects", "pack")
    os.makedirs(pack_dir)
    open(os.path.join(pack_dir, "pack-abc.idx"), "wb").close()
    open(os.path.join(pack_dir, "pack-abc.pack"), "wb").close()
    assert list_pack_files(repo) == ["pack-abc"]


def test_list_pack_files_returns_empty_when_no_pack_dir(tmp_path):
    from pygit.pack import list_pack_files
    from pygit.repository import create_repo
    repo = create_repo(tmp_path)
    assert list_pack_files(repo) == []


def _blob_sha(content):
    import hashlib
    header = f"blob {len(content)}\0".encode()
    return hashlib.sha1(header + content).hexdigest()


def test_read_object_from_packs_resolves_ofs_and_ref_delta(tmp_path):
    import zlib
    import struct
    import os
    from pygit.pack import read_object_from_packs
    from pygit.objects import hash_object
    from pygit.repository import create_repo
    repo = create_repo(tmp_path)

    external_base_content = b"external base\n"
    external_base_sha = hash_object(repo, external_base_content, "blob", write=True)

    base_content = b"base content\n"
    base_compressed = zlib.compress(base_content)
    object_a = bytes([0x3D]) + base_compressed  # type=blob(3), size=13

    ofs_delta_payload = bytes([13, 18, 0x90, 13, 5]) + b"EXTRA"
    ofs_delta_compressed = zlib.compress(ofs_delta_payload)
    ofs_delta_relative_offset = len(object_a)
    assert ofs_delta_relative_offset < 128
    object_b = bytes([0x6A]) + bytes([ofs_delta_relative_offset]) + ofs_delta_compressed  # type=OFS_DELTA(6), size=10

    ref_delta_payload = bytes([14, 18, 0x90, 14, 4]) + b"MORE"
    ref_delta_compressed = zlib.compress(ref_delta_payload)
    object_c = bytes([0x79]) + bytes.fromhex(external_base_sha) + ref_delta_compressed  # type=REF_DELTA(7), size=9

    pack_header = struct.pack(">4sII", b"PACK", 2, 3)
    pack_bytes = pack_header + object_a + object_b + object_c + b"\x00" * 20

    offset_a = len(pack_header)
    offset_b = offset_a + len(object_a)
    offset_c = offset_b + len(object_b)

    expected_b_content = base_content + b"EXTRA"
    expected_c_content = external_base_content + b"MORE"
    sha_a = _blob_sha(base_content)
    sha_b = _blob_sha(expected_b_content)
    sha_c = _blob_sha(expected_c_content)

    idx_bytes = _build_idx_v2([(sha_a, offset_a), (sha_b, offset_b), (sha_c, offset_c)])

    pack_dir = os.path.join(repo.gitdir, "objects", "pack")
    os.makedirs(pack_dir)
    with open(os.path.join(pack_dir, "pack-test.pack"), "wb") as f:
        f.write(pack_bytes)
    with open(os.path.join(pack_dir, "pack-test.idx"), "wb") as f:
        f.write(idx_bytes)

    assert read_object_from_packs(repo, sha_a) == ("blob", base_content)
    assert read_object_from_packs(repo, sha_b) == ("blob", expected_b_content)
    assert read_object_from_packs(repo, sha_c) == ("blob", expected_c_content)


def test_read_object_from_packs_returns_none_when_sha_absent(tmp_path):
    from pygit.pack import read_object_from_packs
    from pygit.repository import create_repo
    repo = create_repo(tmp_path)
    assert read_object_from_packs(repo, "0" * 40) is None



