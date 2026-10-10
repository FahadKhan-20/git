# Pack writing implementation plan

Spec: `docs/superpowers/specs/2026-07-29-pack-writing-design.md`

Each task is: failing test → minimal code → passing test. No commits until the user says so.
No inline code comments or docstrings in `pygit/` source files.

---

## Task 1 — `encode_object_header` and round-trip with `parse_object_header`

### Tests (`tests/test_pack_write.py`)

```python
import pytest
from pygit.pack import encode_object_header, parse_object_header, OBJ_BLOB, OBJ_COMMIT, OBJ_TREE, OBJ_TAG


def test_encode_header_single_byte_blob():
    data = encode_object_header(OBJ_BLOB, 0)
    type_id, size, end = parse_object_header(data, 0)
    assert type_id == OBJ_BLOB and size == 0 and end == len(data)


def test_encode_header_single_byte_max():
    # size 15 fits in 4 low bits of first byte → 1 byte total
    data = encode_object_header(OBJ_COMMIT, 15)
    type_id, size, end = parse_object_header(data, 0)
    assert type_id == OBJ_COMMIT and size == 15 and end == 1


def test_encode_header_two_bytes():
    # size 16 requires a continuation byte
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
```

### Implementation

Add to `pygit/pack.py`:

```python
def encode_object_header(type_id, size):
    first = (type_id << 4) | (size & 0x0F)
    size >>= 4
    if size == 0:
        return bytes([first])
    result = bytes([first | 0x80])
    while size:
        chunk = size & 0x7F
        size >>= 7
        result += bytes([chunk | (0x80 if size else 0)])
    return result
```

---

## Task 2 — `write_pack`: plain zlib pack with header and trailing SHA-1

### Tests (append to `tests/test_pack_write.py`)

```python
import hashlib, os, struct, tempfile, zlib
from pygit.objects import hash_object
from pygit.pack import write_pack, read_pack_index, read_object_from_packs
from pygit.repository import create_repo


def _make_repo(tmp_path):
    repo = str(tmp_path)
    create_repo(repo)
    return repo


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
    pack_dir = os.path.join(repo, ".git", "objects", "pack")
    os.makedirs(pack_dir, exist_ok=True)
    pack_path = os.path.join(pack_dir, "pack-test.pack")
    idx_path  = os.path.join(pack_dir, "pack-test.idx")
    write_pack(repo, [sha], pack_path, idx_path)
    result = read_object_from_packs(repo, sha)
    assert result == ("blob", content)


def test_write_pack_multiple_objects(tmp_path):
    repo = _make_repo(tmp_path)
    shas = [hash_object(repo, f"obj{i}".encode(), "blob", write=True) for i in range(5)]
    pack_dir = os.path.join(repo, ".git", "objects", "pack")
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
```

### Implementation

Add to `pygit/pack.py`:

```python
import hashlib
import struct as _struct
import zlib as _zlib

def write_pack(repo, shas, pack_path, idx_path):
    from pygit.objects import read_object
    shas_sorted = sorted(shas)
    entries = []
    for sha in shas_sorted:
        type_name, content = read_object(repo, sha)
        type_id = _TYPE_ID_BY_NAME[type_name]
        header = encode_object_header(type_id, len(content))
        compressed = _zlib.compress(content)
        entries.append((sha, header, compressed))

    body = bytearray()
    body += b"PACK"
    body += _struct.pack(">II", 2, len(entries))
    offsets = {}
    for sha, header, compressed in entries:
        offsets[sha] = len(body)
        body += header
        body += compressed
    pack_sha = hashlib.sha1(body).digest()
    body += pack_sha

    with open(pack_path, "wb") as f:
        f.write(body)

    _write_idx(shas_sorted, offsets, entries, pack_sha, idx_path)
    return pack_sha.hex()
```

---

## Task 3 — `.idx` v2 writing: fanout, SHAs, CRC32s, offsets, checksums

### Tests (append to `tests/test_pack_write.py`)

```python
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
    offsets_start = crcs_start + n * 4
    result = read_pack_index(idx_path)
    for i, s in enumerate(sorted(result.keys())):
        offset = result[s]
        stored_crc = struct.unpack(">I", raw[crcs_start + i*4: crcs_start + i*4 + 4])[0]
        # find end of compressed data by decompressing
        from pygit.pack import parse_object_header
        _, _, header_end = parse_object_header(pack_data, offset)
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
```

### Implementation

Add `_write_idx` helper to `pygit/pack.py`:

```python
def _write_idx(shas_sorted, offsets, entries, pack_sha_bytes, idx_path):
    n = len(shas_sorted)
    fanout = [0] * 256
    for sha in shas_sorted:
        first_byte = int(sha[:2], 16)
        for b in range(first_byte, 256):
            fanout[b] += 1

    body = bytearray()
    body += b"\xff\x74\x4f\x63"
    body += _struct.pack(">I", 2)
    for count in fanout:
        body += _struct.pack(">I", count)
    for sha in shas_sorted:
        body += bytes.fromhex(sha)
    for sha, header, compressed in entries:
        body += _struct.pack(">I", _zlib.crc32(compressed) & 0xFFFFFFFF)
    for sha in shas_sorted:
        body += _struct.pack(">I", offsets[sha])
    body += pack_sha_bytes
    body += hashlib.sha1(body).digest()

    with open(idx_path, "wb") as f:
        f.write(body)
```

---

## Task 4 — `index_pack`: regenerate `.idx` from an existing `.pack`

### Tests (append to `tests/test_pack_write.py`)

```python
from pygit.pack import index_pack


def test_index_pack_regenerates_readable_idx(tmp_path):
    repo = _make_repo(tmp_path)
    shas = [hash_object(repo, f"regen{i}".encode(), "blob", write=True) for i in range(3)]
    pack_dir = os.path.join(repo, ".git", "objects", "pack")
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
    with pytest.raises(Exception):
        index_pack(str(bad), str(tmp_path / "bad.idx"))
```

### Implementation

Add to `pygit/pack.py`:

```python
def index_pack(pack_path, idx_path):
    with open(pack_path, "rb") as f:
        pack_data = f.read()
    magic, version, count = _struct.unpack(">4sII", pack_data[:12])
    if magic != b"PACK" or version != 2:
        raise InvalidPackError(f"unsupported pack file: {pack_path}")
    pack_sha_bytes = pack_data[-20:]
    shas_sorted = []
    offsets = {}
    entries = []
    cursor = 12
    for _ in range(count):
        entry_offset = cursor
        type_id, size, header_end = parse_object_header(pack_data, cursor)
        if type_id == OBJ_OFS_DELTA or type_id == OBJ_REF_DELTA:
            raise InvalidPackError("index_pack does not support delta entries")
        decomp = _zlib.decompressobj()
        remaining = pack_data[header_end:]
        decomp.decompress(remaining)
        decomp.flush()
        consumed = len(remaining) - len(decomp.unused_data)
        compressed = pack_data[header_end: header_end + consumed]
        cursor = header_end + consumed
        full_content, _ = _decompress_at(pack_data, entry_offset + (header_end - entry_offset))
        header_bytes = encode_object_header(type_id, size)
        type_name = TYPE_NAMES[type_id]
        import hashlib as _hl
        hdr = f"{type_name} {len(full_content)}\0".encode()
        sha = _hl.sha1(hdr + full_content).hexdigest()
        shas_sorted.append(sha)
        offsets[sha] = entry_offset
        entries.append((sha, header_bytes, compressed))
    shas_sorted.sort()
    _write_idx(shas_sorted, offsets, entries, pack_sha_bytes, idx_path)
```

---

## Task 5 — `plumbing.pack_objects` and `plumbing.index_pack_cmd`

### Tests (`tests/test_plumbing.py`, append)

```python
from pygit.plumbing import pack_objects, index_pack_cmd


def test_pack_objects_creates_pack_and_idx(tmp_path):
    repo = str(tmp_path)
    create_repo(repo)
    from pygit.objects import hash_object as ho
    shas = [ho(repo, f"po{i}".encode(), "blob", write=True) for i in range(3)]
    basename = pack_objects(repo, shas)
    pack_dir = os.path.join(repo, ".git", "objects", "pack")
    assert os.path.exists(os.path.join(pack_dir, basename + ".pack"))
    assert os.path.exists(os.path.join(pack_dir, basename + ".idx"))


def test_pack_objects_basename_starts_with_pack(tmp_path):
    repo = str(tmp_path)
    create_repo(repo)
    from pygit.objects import hash_object as ho
    sha = ho(repo, b"basename check", "blob", write=True)
    basename = pack_objects(repo, [sha])
    assert basename.startswith("pack-")


def test_index_pack_cmd_recreates_idx(tmp_path):
    repo = str(tmp_path)
    create_repo(repo)
    from pygit.objects import hash_object as ho
    sha = ho(repo, b"idx cmd", "blob", write=True)
    basename = pack_objects(repo, [sha])
    pack_dir = os.path.join(repo, ".git", "objects", "pack")
    idx_path = os.path.join(pack_dir, basename + ".idx")
    os.remove(idx_path)
    index_pack_cmd(repo, os.path.join(pack_dir, basename + ".pack"))
    assert os.path.exists(idx_path)
```

### Implementation

Append to `pygit/plumbing.py`:

```python
def pack_objects(repo, shas):
    from pygit.pack import write_pack
    import os
    pack_dir = repo_path(repo, "objects", "pack")
    os.makedirs(pack_dir, exist_ok=True)
    import tempfile, shutil
    tmp_pack = os.path.join(pack_dir, "_tmp.pack")
    tmp_idx  = os.path.join(pack_dir, "_tmp.idx")
    pack_sha = write_pack(repo, list(shas), tmp_pack, tmp_idx)
    basename = f"pack-{pack_sha}"
    shutil.move(tmp_pack, os.path.join(pack_dir, basename + ".pack"))
    shutil.move(tmp_idx,  os.path.join(pack_dir, basename + ".idx"))
    return basename


def index_pack_cmd(repo, pack_path):
    from pygit.pack import index_pack
    idx_path = pack_path[:-len(".pack")] + ".idx"
    index_pack(pack_path, idx_path)
```

---

## Task 6 — CLI: `pack-objects --stdin` and `index-pack`

### Tests (`tests/test_cli_pack.py`, new file)

```python
import os, subprocess, sys, pytest
from pygit.repository import create_repo
from pygit.objects import hash_object


@pytest.fixture()
def repo(tmp_path):
    r = str(tmp_path)
    create_repo(r)
    return r


def _pygit(repo, *args, stdin=None):
    result = subprocess.run(
        [sys.executable, "-m", "pygit"] + list(args),
        cwd=repo,
        capture_output=True,
        text=True,
        input=stdin,
    )
    return result


def test_pack_objects_stdin(repo):
    shas = [hash_object(repo, f"cli{i}".encode(), "blob", write=True) for i in range(3)]
    stdin_input = "\n".join(shas) + "\n"
    result = _pygit(repo, "pack-objects", "--stdin", stdin=stdin_input)
    assert result.returncode == 0
    basename = result.stdout.strip()
    assert basename.startswith("pack-")
    pack_dir = os.path.join(repo, ".git", "objects", "pack")
    assert os.path.exists(os.path.join(pack_dir, basename + ".pack"))
    assert os.path.exists(os.path.join(pack_dir, basename + ".idx"))


def test_pack_objects_stdin_ignores_blank_and_comments(repo):
    sha = hash_object(repo, b"comment test", "blob", write=True)
    stdin_input = f"\n# ignored\n{sha}\n\n"
    result = _pygit(repo, "pack-objects", "--stdin", stdin=stdin_input)
    assert result.returncode == 0
    assert result.stdout.strip().startswith("pack-")


def test_index_pack_creates_idx(repo):
    from pygit.plumbing import pack_objects
    shas = [hash_object(repo, b"idx cli", "blob", write=True)]
    basename = pack_objects(repo, shas)
    pack_dir = os.path.join(repo, ".git", "objects", "pack")
    idx_path = os.path.join(pack_dir, basename + ".idx")
    os.remove(idx_path)
    pack_path = os.path.join(pack_dir, basename + ".pack")
    result = _pygit(repo, "index-pack", pack_path)
    assert result.returncode == 0
    assert os.path.exists(idx_path)
    assert result.stdout.strip().startswith("pack-")
```

### Implementation

In `pygit/cli.py`, add two subcommand handlers and wire them into `main()`:

```python
# inside main(), extend the subcommand dispatch:

elif args[0] == "pack-objects":
    if len(args) < 2 or args[1] != "--stdin":
        sys.exit("usage: pygit pack-objects --stdin")
    import sys as _sys
    shas = [line.strip() for line in _sys.stdin if line.strip() and not line.startswith("#")]
    from pygit.plumbing import pack_objects
    print(pack_objects(repo, shas))

elif args[0] == "index-pack":
    if len(args) < 2:
        sys.exit("usage: pygit index-pack <pack-path>")
    from pygit.plumbing import index_pack_cmd
    index_pack_cmd(repo, args[1])
    basename = "pack-" + args[1].rsplit("pack-", 1)[-1].replace(".pack", "")
    print(basename)
```

---

## Task 7 — Interop test: `git verify-pack` validates pygit-written packs

### Tests (append to `tests/test_interop_realgit.py`)

```python
import shutil


@pytest.mark.skipif(shutil.which("git") is None, reason="git not on PATH")
def test_git_verify_pack_accepts_pygit_written_pack(tmp_path):
    import subprocess
    from pygit.repository import create_repo
    from pygit.objects import hash_object
    from pygit.plumbing import pack_objects

    repo = str(tmp_path)
    create_repo(repo)
    subprocess.run(["git", "init", repo], check=True, capture_output=True)
    subprocess.run(["git", "-C", repo, "config", "user.email", "t@t.com"], check=True)
    subprocess.run(["git", "-C", repo, "config", "user.name", "T"], check=True)

    shas = [hash_object(repo, f"verify{i}".encode(), "blob", write=True) for i in range(5)]
    basename = pack_objects(repo, shas)
    pack_dir = os.path.join(repo, ".git", "objects", "pack")
    idx_path = os.path.join(pack_dir, basename + ".idx")

    result = subprocess.run(
        ["git", "verify-pack", "-v", idx_path],
        capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.skipif(shutil.which("git") is None, reason="git not on PATH")
def test_git_verify_pack_after_index_pack_regen(tmp_path):
    import subprocess
    from pygit.repository import create_repo
    from pygit.objects import hash_object
    from pygit.plumbing import pack_objects, index_pack_cmd

    repo = str(tmp_path)
    create_repo(repo)
    shas = [hash_object(repo, f"regen{i}".encode(), "blob", write=True) for i in range(3)]
    basename = pack_objects(repo, shas)
    pack_dir = os.path.join(repo, ".git", "objects", "pack")
    idx_path = os.path.join(pack_dir, basename + ".idx")
    pack_path = os.path.join(pack_dir, basename + ".pack")
    os.remove(idx_path)
    index_pack_cmd(repo, pack_path)

    result = subprocess.run(
        ["git", "verify-pack", "-v", idx_path],
        capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
```

---

## Task 8 — README updates

### Changes to `README.md`

1. Add to the command-to-internals table:

   | `pack-objects` | Reads the named object SHAs, writes a `.pack` + `.idx` v2 file pair to `.git/objects/pack/` |
   | `index-pack` | Parses an existing `.pack` file and regenerates its companion `.idx` v2 |

2. Update the "Known limitations" pack bullet to replace:

   > Pack files are read, but not written: pygit cannot create or repack into `.pack` files itself
   > (needed once `push` exists), and `.pack`/`.idx` files are read fully into memory rather than
   > streamed, so extremely large packs are not handled efficiently.

   with:

   > Pack files are read and written (`pack-objects`, `index-pack`), but objects are stored as
   > plain zlib entries — delta compression is not yet performed, so pack files will be larger than
   > those produced by real Git. `.pack`/`.idx` files are read fully into memory rather than
   > streamed, so extremely large packs are not handled efficiently.
