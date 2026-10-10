# Pack File Reading Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Teach `pygit` to read objects out of Git's `.pack`/`.idx` format (loose-object storage keeps working unchanged), so any repo real Git has packed (via `git gc`/`git repack`) is still fully readable through every existing pygit command.

**Architecture:** A new `pygit/pack.py` module parses `.idx` v2 files, parses `.pack` files, and resolves `OFS_DELTA`/`REF_DELTA` objects (recursively, with a `REF_DELTA` fallback into `objects.read_object()` for bases stored elsewhere). `pygit/objects.py`'s `read_object()` is extended to fall back to it when a sha isn't found loose. No CLI changes.

**Tech Stack:** Python 3.9+, stdlib only (`struct`, `zlib`, `hashlib`, `os`), pytest.

## Global Constraints

- Stdlib only — no third-party packing/delta libraries.
- No inline code comments and no docstrings in `pygit/` source files — explanations live only in `README.md`.
- Every task ends with `pytest` green (from the project root) before moving to the next task.
- Design spec: `docs/superpowers/specs/2026-07-29-pack-reading-design.md` — consult it for the exact byte-format details a task doesn't fully restate.
- No pack *writing*, no `.idx` v1, no streaming for huge packs, no new CLI commands (all confirmed non-goals from the spec).

---

### Task 1: Pack object header and OFS_DELTA offset varint parsing

**Files:**
- Create: `pygit/pack.py`
- Test: `tests/test_pack.py`

**Interfaces:**
- Produces: `OBJ_COMMIT = 1`, `OBJ_TREE = 2`, `OBJ_BLOB = 3`, `OBJ_TAG = 4`, `OBJ_OFS_DELTA = 6`, `OBJ_REF_DELTA = 7` (module-level ints); `TYPE_NAMES: dict[int, str]` mapping the four base type ids to `"commit"/"tree"/"blob"/"tag"`; `InvalidPackError(Exception)`; `parse_object_header(data: bytes, offset: int) -> tuple[int, int, int]` (returns `type_id, size, next_offset`); `parse_ofs_delta_offset(data: bytes, offset: int) -> tuple[int, int]` (returns `relative_offset, next_offset`).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_pack.py
from pygit.pack import OBJ_BLOB, OBJ_OFS_DELTA, parse_object_header, parse_ofs_delta_offset


def test_parse_object_header_single_byte_size():
    data = bytes([0x3D])  # type=blob(3), size=13, no continuation
    type_id, size, next_offset = parse_object_header(data, 0)
    assert type_id == OBJ_BLOB
    assert size == 13
    assert next_offset == 1


def test_parse_object_header_multi_byte_size():
    data = bytes([0xB8, 0x0C])  # type=blob(3), low4=8, continuation; byte1=12 -> size=8|(12<<4)=200
    type_id, size, next_offset = parse_object_header(data, 0)
    assert type_id == OBJ_BLOB
    assert size == 200
    assert next_offset == 2


def test_parse_object_header_reads_at_nonzero_offset():
    data = bytes([0xFF, 0x3D])  # a leading unrelated byte, then a single-byte blob/size-13 header
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
```

- [ ] **Step 2: Run test, confirm it fails**

Run: `pytest tests/test_pack.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'pygit.pack'`

- [ ] **Step 3: Implement `pygit/pack.py`**

```python
# pygit/pack.py
OBJ_COMMIT = 1
OBJ_TREE = 2
OBJ_BLOB = 3
OBJ_TAG = 4
OBJ_OFS_DELTA = 6
OBJ_REF_DELTA = 7

TYPE_NAMES = {
    OBJ_COMMIT: "commit",
    OBJ_TREE: "tree",
    OBJ_BLOB: "blob",
    OBJ_TAG: "tag",
}


class InvalidPackError(Exception):
    pass


def parse_object_header(data, offset):
    byte = data[offset]
    type_id = (byte >> 4) & 0x7
    size = byte & 0x0F
    shift = 4
    offset += 1
    while byte & 0x80:
        byte = data[offset]
        size |= (byte & 0x7F) << shift
        shift += 7
        offset += 1
    return type_id, size, offset


def parse_ofs_delta_offset(data, offset):
    byte = data[offset]
    value = byte & 0x7F
    offset += 1
    while byte & 0x80:
        byte = data[offset]
        value = ((value + 1) << 7) | (byte & 0x7F)
        offset += 1
    return value, offset
```

- [ ] **Step 4: Run test, confirm it passes**

Run: `pytest tests/test_pack.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add pygit/pack.py tests/test_pack.py
git commit -m "Add pack object header and OFS_DELTA offset varint parsing"
```

---

### Task 2: Delta application

**Files:**
- Modify: `pygit/pack.py`
- Test: `tests/test_pack.py`

**Interfaces:**
- Consumes: `InvalidPackError` (this file).
- Produces: `apply_delta(base: bytes, delta: bytes) -> bytes`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_pack.py`:

```python
import pytest

from pygit.pack import InvalidPackError, apply_delta


def test_apply_delta_pure_insert():
    delta = bytes([0, 5]) + b"hello"
    assert apply_delta(b"", delta) == b"hello"


def test_apply_delta_copy_twice_from_base():
    base = b"hello"
    delta = bytes([5, 10]) + bytes([0x90, 5]) + bytes([0x90, 5])
    assert apply_delta(base, delta) == b"hellohello"


def test_apply_delta_copy_and_insert():
    base = b"hello world"
    delta = bytes([11, 6]) + bytes([0x90, 5]) + bytes([1]) + b"!"
    assert apply_delta(base, delta) == b"hello!"


def test_apply_delta_zero_size_copy_means_65536():
    base = bytes(range(256)) * 256
    assert len(base) == 65536
    delta = bytes([0x80, 0x80, 0x04]) + bytes([0x80, 0x80, 0x04]) + bytes([0x80])
    result = apply_delta(base, delta)
    assert result == base


def test_apply_delta_rejects_base_size_mismatch():
    delta = bytes([99, 5]) + b"hello"
    with pytest.raises(InvalidPackError):
        apply_delta(b"", delta)


def test_apply_delta_rejects_result_size_mismatch():
    delta = bytes([0, 99, 5]) + b"hello"
    with pytest.raises(InvalidPackError):
        apply_delta(b"", delta)
```

Note on `test_apply_delta_copy_and_insert`: base is 11 bytes, result is 12 bytes ("hello" + "!"), built from copying 5 bytes at offset 0 (`"hello"`) then inserting the literal byte `"!"`.

- [ ] **Step 2: Run test, confirm it fails**

Run: `pytest tests/test_pack.py -v`
Expected: FAIL — `apply_delta` doesn't exist

- [ ] **Step 3: Implement `apply_delta`**

Add to `pygit/pack.py`:

```python
def _read_delta_varint(data, offset):
    value = 0
    shift = 0
    while True:
        byte = data[offset]
        offset += 1
        value |= (byte & 0x7F) << shift
        shift += 7
        if not (byte & 0x80):
            break
    return value, offset


def apply_delta(base, delta):
    base_size, offset = _read_delta_varint(delta, 0)
    result_size, offset = _read_delta_varint(delta, offset)
    if base_size != len(base):
        raise InvalidPackError("delta base size does not match actual base length")
    output = bytearray()
    n = len(delta)
    while offset < n:
        instruction = delta[offset]
        offset += 1
        if instruction & 0x80:
            copy_offset = 0
            copy_size = 0
            for bit in range(4):
                if instruction & (1 << bit):
                    copy_offset |= delta[offset] << (8 * bit)
                    offset += 1
            for bit in range(3):
                if instruction & (1 << (4 + bit)):
                    copy_size |= delta[offset] << (8 * bit)
                    offset += 1
            if copy_size == 0:
                copy_size = 0x10000
            output += base[copy_offset:copy_offset + copy_size]
        elif instruction != 0:
            output += delta[offset:offset + instruction]
            offset += instruction
        else:
            raise InvalidPackError("delta instruction byte 0 is reserved/invalid")
    if len(output) != result_size:
        raise InvalidPackError("delta result size does not match reconstructed length")
    return bytes(output)
```

- [ ] **Step 4: Run test, confirm it passes**

Run: `pytest tests/test_pack.py -v`
Expected: PASS (11 tests)

- [ ] **Step 5: Commit**

```bash
git add pygit/pack.py tests/test_pack.py
git commit -m "Add delta application"
```

---

### Task 3: Pack index (`.idx` v2) parsing and pack file listing

**Files:**
- Modify: `pygit/pack.py`
- Test: `tests/test_pack.py`

**Interfaces:**
- Consumes: `repo_path` (`pygit.repository`); `InvalidPackError` (this file).
- Produces: `list_pack_files(repo) -> list[str]` (sorted basenames, e.g. `"pack-<sha>"`); `read_pack_index(idx_path: str) -> dict[str, int]` (sha hex → byte offset into the matching `.pack`).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_pack.py`:

```python
import os
import struct

from pygit.pack import list_pack_files, read_pack_index
from pygit.repository import create_repo


def _build_idx_v2(entries):
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
    sha1 = bytes(range(20)).hex()
    sha2 = bytes(range(20, 40)).hex()
    idx_path = tmp_path / "pack-test.idx"
    idx_path.write_bytes(_build_idx_v2([(sha1, 100), (sha2, 250)]))
    assert read_pack_index(str(idx_path)) == {sha1: 100, sha2: 250}


def test_read_pack_index_rejects_bad_magic(tmp_path):
    idx_path = tmp_path / "bad.idx"
    idx_path.write_bytes(b"\x00" * 8 + b"\x00" * 1024)
    with pytest.raises(InvalidPackError):
        read_pack_index(str(idx_path))


def test_list_pack_files_finds_idx_basenames(tmp_path):
    repo = create_repo(tmp_path)
    pack_dir = os.path.join(repo.gitdir, "objects", "pack")
    os.makedirs(pack_dir)
    open(os.path.join(pack_dir, "pack-abc.idx"), "wb").close()
    open(os.path.join(pack_dir, "pack-abc.pack"), "wb").close()
    assert list_pack_files(repo) == ["pack-abc"]


def test_list_pack_files_returns_empty_when_no_pack_dir(tmp_path):
    repo = create_repo(tmp_path)
    assert list_pack_files(repo) == []
```

- [ ] **Step 2: Run test, confirm it fails**

Run: `pytest tests/test_pack.py -v`
Expected: FAIL — `list_pack_files`/`read_pack_index` don't exist

- [ ] **Step 3: Implement `list_pack_files` and `read_pack_index`**

Add to `pygit/pack.py`:

```python
import os
import struct

from pygit.repository import repo_path

IDX_MAGIC = b"\xff\x74\x4f\x63"


def list_pack_files(repo):
    pack_dir = repo_path(repo, "objects", "pack")
    if not os.path.isdir(pack_dir):
        return []
    names = set()
    for name in os.listdir(pack_dir):
        if name.endswith(".idx"):
            names.add(name[:-len(".idx")])
    return sorted(names)


def read_pack_index(idx_path):
    with open(idx_path, "rb") as f:
        data = f.read()
    magic, version = struct.unpack(">4sI", data[:8])
    if magic != IDX_MAGIC or version != 2:
        raise InvalidPackError(f"unsupported pack index format: {idx_path}")
    fanout = struct.unpack(">256I", data[8:8 + 256 * 4])
    count = fanout[255]
    shas_start = 8 + 256 * 4
    shas_end = shas_start + count * 20
    offsets_start = shas_end + count * 4
    result = {}
    for i in range(count):
        sha = data[shas_start + i * 20: shas_start + i * 20 + 20].hex()
        offset = struct.unpack(">I", data[offsets_start + i * 4: offsets_start + i * 4 + 4])[0]
        if offset & 0x80000000:
            raise InvalidPackError("64-bit pack offsets are not supported")
        result[sha] = offset
    return result
```

- [ ] **Step 4: Run test, confirm it passes**

Run: `pytest tests/test_pack.py -v`
Expected: PASS (15 tests)

- [ ] **Step 5: Commit**

```bash
git add pygit/pack.py tests/test_pack.py
git commit -m "Add pack index parsing and pack file listing"
```

---

### Task 4: Full object resolution (`read_object_from_packs`)

**Files:**
- Modify: `pygit/pack.py`
- Test: `tests/test_pack.py`

**Interfaces:**
- Consumes: everything produced in Tasks 1-3 in this module; `read_object` (`pygit.objects`, used only as a lazy fallback for `REF_DELTA` bases not present in the current pack).
- Produces: `read_object_from_packs(repo, sha: str) -> tuple[str, bytes] | None`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_pack.py`:

```python
import hashlib
import zlib

from pygit.pack import read_object_from_packs
from pygit.objects import hash_object


def _blob_sha(content):
    header = f"blob {len(content)}\0".encode()
    return hashlib.sha1(header + content).hexdigest()


def test_read_object_from_packs_resolves_ofs_and_ref_delta(tmp_path):
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
    repo = create_repo(tmp_path)
    assert read_object_from_packs(repo, "0" * 40) is None
```

- [ ] **Step 2: Run test, confirm it fails**

Run: `pytest tests/test_pack.py -v`
Expected: FAIL — `read_object_from_packs` doesn't exist

- [ ] **Step 3: Implement object resolution**

Add to `pygit/pack.py`:

```python
import zlib

_TYPE_ID_BY_NAME = {"commit": OBJ_COMMIT, "tree": OBJ_TREE, "blob": OBJ_BLOB, "tag": OBJ_TAG}


def _decompress_at(data, offset):
    decompressor = zlib.decompressobj()
    remaining = data[offset:]
    content = decompressor.decompress(remaining)
    content += decompressor.flush()
    consumed = len(remaining) - len(decompressor.unused_data)
    return content, offset + consumed


def _resolve_at_offset(repo, pack_data, sha_to_offset, offset, memo):
    if offset in memo:
        return memo[offset]
    type_id, size, header_end = parse_object_header(pack_data, offset)
    if type_id in (OBJ_COMMIT, OBJ_TREE, OBJ_BLOB, OBJ_TAG):
        content, _ = _decompress_at(pack_data, header_end)
        if len(content) != size:
            raise InvalidPackError(f"object at offset {offset} has wrong size")
        result = (type_id, content)
    elif type_id == OBJ_OFS_DELTA:
        rel_offset, delta_start = parse_ofs_delta_offset(pack_data, header_end)
        base_type, base_content = _resolve_at_offset(repo, pack_data, sha_to_offset, offset - rel_offset, memo)
        delta_content, _ = _decompress_at(pack_data, delta_start)
        if len(delta_content) != size:
            raise InvalidPackError(f"delta at offset {offset} has wrong size")
        result = (base_type, apply_delta(base_content, delta_content))
    elif type_id == OBJ_REF_DELTA:
        base_sha = pack_data[header_end:header_end + 20].hex()
        delta_start = header_end + 20
        if base_sha in sha_to_offset:
            base_type, base_content = _resolve_at_offset(repo, pack_data, sha_to_offset, sha_to_offset[base_sha], memo)
        else:
            from pygit.objects import read_object
            base_type_name, base_content = read_object(repo, base_sha)
            base_type = _TYPE_ID_BY_NAME[base_type_name]
        delta_content, _ = _decompress_at(pack_data, delta_start)
        if len(delta_content) != size:
            raise InvalidPackError(f"delta at offset {offset} has wrong size")
        result = (base_type, apply_delta(base_content, delta_content))
    else:
        raise InvalidPackError(f"unsupported pack object type {type_id} at offset {offset}")
    memo[offset] = result
    return result


def read_object_from_packs(repo, sha):
    for basename in list_pack_files(repo):
        idx_path = repo_path(repo, "objects", "pack", basename + ".idx")
        sha_to_offset = read_pack_index(idx_path)
        if sha in sha_to_offset:
            pack_path = repo_path(repo, "objects", "pack", basename + ".pack")
            with open(pack_path, "rb") as f:
                pack_data = f.read()
            type_id, content = _resolve_at_offset(repo, pack_data, sha_to_offset, sha_to_offset[sha], {})
            return TYPE_NAMES[type_id], content
    return None
```

- [ ] **Step 4: Run test, confirm it passes**

Run: `pytest tests/test_pack.py -v`
Expected: PASS (17 tests)

- [ ] **Step 5: Commit**

```bash
git add pygit/pack.py tests/test_pack.py
git commit -m "Add full pack object resolution with OFS_DELTA/REF_DELTA support"
```

---

### Task 5: Integrate pack fallback into `objects.read_object`

**Files:**
- Modify: `pygit/objects.py`
- Test: `tests/test_objects.py`

**Interfaces:**
- Consumes: `read_object_from_packs` (`pygit.pack`).
- Produces: no new public names — `read_object(repo, sha)`'s behavior is extended, its signature and return type (`tuple[str, bytes]`) are unchanged; it still raises `BadObjectError` when a sha is truly absent.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_objects.py`:

```python
import os
import struct

from pygit.repository import create_repo


def _build_single_entry_idx(sha_hex, offset):
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
```

Note: this test uses `content = b"packed only\n"` (12 bytes, `< 16`), so its pack object header is the single byte `(3 << 4) | 12`, no continuation needed — matching the same style used in `tests/test_pack.py`.

- [ ] **Step 2: Run test, confirm it fails**

Run: `pytest tests/test_objects.py -v`
Expected: FAIL — `read_object` raises `BadObjectError` because it doesn't check packs yet

- [ ] **Step 3: Modify `read_object` to fall back to packs**

In `pygit/objects.py`, replace the body of `read_object` with:

```python
def read_object(repo, sha):
    path = object_path(repo, sha)
    if os.path.exists(path):
        with open(path, "rb") as f:
            full = zlib.decompress(f.read())
        nul_index = full.index(b"\0")
        type_, size_str = full[:nul_index].decode().split(" ")
        content = full[nul_index + 1:]
        if len(content) != int(size_str):
            raise BadObjectError(f"object {sha} has invalid length")
        return type_, content
    from pygit.pack import read_object_from_packs
    result = read_object_from_packs(repo, sha)
    if result is None:
        raise BadObjectError(f"object {sha} not found")
    return result
```

- [ ] **Step 4: Run full test suite, confirm it passes**

Run: `pytest tests/ -v`
Expected: PASS (all tests so far)

- [ ] **Step 5: Commit**

```bash
git add pygit/objects.py tests/test_objects.py
git commit -m "Fall back to pack storage in read_object"
```

---

### Task 6: Real-git interop test (`git gc` round trip)

**Files:**
- Modify: `tests/test_interop_realgit.py`

**Interfaces:**
- Consumes: `main` (`pygit.cli`); `read_object` (`pygit.objects`); `GitRepository` (`pygit.repository`); the file's existing `run_git` helper.

- [ ] **Step 1: Write the interop test**

Append to `tests/test_interop_realgit.py`:

```python
import os

from pygit.cli import main


def test_pygit_reads_objects_after_real_git_gc(tmp_path, monkeypatch, capsys):
    create_repo(tmp_path)
    monkeypatch.chdir(tmp_path)

    commit_shas = []
    for content in [b"version 1\n", b"version 2\n", b"version 3 with a bit more text\n"]:
        (tmp_path / "file.txt").write_bytes(content)
        main(["add", "file.txt"])
        capsys.readouterr()
        main(["commit", "-m", f"commit for {content!r}"])
        commit_shas.append(capsys.readouterr().out.strip())

    run_git(str(tmp_path), "gc")

    objects_dir = os.path.join(str(tmp_path), ".git", "objects")
    loose_dirs = [name for name in os.listdir(objects_dir) if name not in ("pack", "info")]
    assert loose_dirs == []

    repo = GitRepository(str(tmp_path), str(tmp_path / ".git"))
    for sha in commit_shas:
        type_, _ = read_object(repo, sha)
        assert type_ == "commit"

    main(["log"])
    log_output = capsys.readouterr().out
    for sha in commit_shas:
        assert sha in log_output

    main(["checkout", commit_shas[0]])
    assert (tmp_path / "file.txt").read_bytes() == b"version 1\n"
```

- [ ] **Step 2: Run the interop test**

Run: `pytest tests/test_interop_realgit.py -v`
Expected: PASS (1 new test, others unaffected) or SKIPPED if `git` is unavailable

- [ ] **Step 3: Run the entire test suite**

Run: `pytest tests/ -v`
Expected: PASS, no failures

- [ ] **Step 4: Commit**

```bash
git add tests/test_interop_realgit.py
git commit -m "Add real-git gc round-trip interop test for pack reading"
```

---

### Task 7: `README.md` updates

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Add a pack format section**

Insert into `README.md`, after the existing "## The index" section and before "## Command-to-internals map":

```markdown
## Reading packed objects

Real Git periodically compacts loose objects into `.pack` files (with a companion `.idx` file
for fast lookup) — `git gc` is the common trigger. pygit reads this format too: `.git/objects/pack/*.idx`
is a sorted-by-SHA index (with a 256-entry fanout table for fast lookup) mapping each object's
SHA-1 to a byte offset in the matching `.pack` file. A `.pack` file is a sequence of
zlib-compressed entries, each either a plain object or a *delta* — instructions to reconstruct
the object as a series of "copy N bytes from the base object" / "insert these literal bytes"
steps against another object already read (`OFS_DELTA`, referencing a base earlier in the same
pack by byte offset) or looked up by SHA (`REF_DELTA`, falling back to loose storage or another
pack if that base isn't in this one). `objects.read_object()` tries loose storage first and
falls back to searching every pack, so every existing command works unchanged against a
repacked repository.
```

- [ ] **Step 2: Update the known limitations list**

In the "## Known limitations" section of `README.md`, add:

```markdown
- Pack files are read, but not written: pygit cannot create or repack into `.pack` files itself
  (needed once `push` exists), and `.pack`/`.idx` files are read fully into memory rather than
  streamed, so extremely large packs are not handled efficiently.
```

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "Document pack format support in README"
```
