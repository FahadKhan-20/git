# pygit pack file writing

## Goal

Teach `pygit` to *write* `.pack` + `.idx` files from a set of object SHAs, completing the
"packfiles" architectural block. Pack reading already exists; this phase adds the write side:

- `pack.write_pack(repo, sha_set, pack_path, idx_path)` — given an iterable of object SHAs,
  produce a valid `.pack` file and its companion `.idx` v2 file that a real `git` can read.
- `plumbing.pack_objects(repo, sha_set)` — thin wrapper that picks a deterministic filename and
  calls `write_pack`, returning the pack basename (e.g. `pack-<sha>`).
- `cli.py` gains `pygit pack-objects --stdin` (reads SHAs from stdin, one per line) and
  `pygit index-pack <pack-path>` (regenerates the `.idx` for an existing `.pack`).

This is phase 1 of two toward "packfiles + network protocol": phase 2 (`clone`/`fetch`/`push`)
transfers data as packs and therefore requires this phase to exist first.

## Non-goals

- Delta compression — objects are stored as plain (non-deltified) zlib entries in this phase.
  Delta compression is a performance optimisation deferred to sub-project 16 (Performance).
  Real Git can read non-delta packs without issue, and the interop bar is binary compatibility,
  not compression ratio.
- `.idx` version 1 (the legacy format real Git stopped writing).
- 64-bit offsets (packs > 2 GB) — omitted consistent with the existing pack-reading limitation.
- `git gc`/`git repack` equivalents — that is sub-project 12 (Repo maintenance).
- Any new porcelain command beyond `pack-objects` and `index-pack`.

## Architecture

All new production code lives in `pygit/pack.py` (two new public functions) and
`pygit/plumbing.py` + `pygit/cli.py` (thin wrappers). No new module is needed.

```
pygit/
  pack.py      # extended: write_pack(), index_pack()
  plumbing.py  # extended: pack_objects(), index_pack() wrappers
  cli.py       # extended: pack-objects, index-pack subcommands
```

## `.pack` file format (write)

Layout produced by `write_pack`:

1. **Header** — 12 bytes:
   - 4-byte magic: `PACK`
   - 4-byte big-endian version: `2`
   - 4-byte big-endian object count: `N`

2. **Object entries** — one per SHA in a canonical (sorted) order:
   - Variable-length **object type + size header** (same encoding as the read path):
     - Byte 0: `(type_id << 4) | (size & 0x0F)`, with bit 7 set if more bytes follow.
     - Each continuation byte: `(size_chunk & 0x7F) | (0x80 if more else 0)`.
     - `type_id` values: `1`=commit, `2`=tree, `3`=blob, `4`=tag (no deltas in this phase).
   - **zlib-compressed object content** (the raw bytes after the `\0` in the loose-object
     header, not the full loose file — i.e. the same bytes `read_object()` returns as the
     second element of the tuple).

3. **Trailer** — 20-byte SHA-1 of all bytes from byte 0 of the header through the last
   compressed object entry (i.e. the checksum is over the pack body, including its own header).

## `.idx` v2 file format (write)

Layout produced alongside `write_pack` (same as the read path, now also written):

1. 4-byte magic: `\xff\x74\x4f\x63`
2. 4-byte big-endian version: `2`
3. 256-entry fanout table: `fanout[b]` = number of objects whose first SHA byte is `<= b`.
   `fanout[255]` = `N` (total count). Each entry is a 4-byte big-endian integer.
4. `N` sorted 20-byte raw SHA-1s (ascending).
5. `N` 4-byte big-endian CRC32 checksums of each object's *compressed* bytes in the pack.
6. `N` 4-byte big-endian offsets into the `.pack` file (all `< 2^31` — no 64-bit table needed).
7. Trailer:
   - 20-byte SHA-1 of the corresponding `.pack` file (= the pack trailer we already computed).
   - 20-byte SHA-1 of everything in the `.idx` file preceding this final checksum.

## Public interface additions

```python
# pygit/pack.py

def encode_object_header(type_id: int, size: int) -> bytes:
    """Return the variable-length pack object header bytes for (type_id, size)."""

def write_pack(repo, shas: list[str], pack_path: str, idx_path: str) -> str:
    """
    Write a .pack file to pack_path and a .idx v2 file to idx_path for the
    given list of object SHAs (read from repo). Returns the 40-hex pack SHA
    (the pack file's own trailing checksum, which becomes its canonical name).
    Objects are written in ascending SHA order (no deltas). Raises
    BadObjectError if any sha is missing from the repo.
    """

def index_pack(pack_path: str, idx_path: str) -> None:
    """
    Parse an existing .pack file at pack_path and write a fresh .idx v2 file
    to idx_path. Useful for regenerating a missing index.
    """
```

```python
# pygit/plumbing.py (additions)

def pack_objects(repo, shas: list[str]) -> str:
    """
    Write repo's named objects into a new pack in .git/objects/pack/.
    Returns the pack basename (e.g. "pack-<40hex>").
    """

def index_pack_cmd(repo, pack_path: str) -> None:
    """
    Regenerate the .idx for an existing pack file.
    """
```

```python
# pygit/cli.py (additions)

# pygit pack-objects --stdin
#   Reads SHAs from stdin (one per line, ignoring blank lines and "#" comments).
#   Writes a new pack to .git/objects/pack/ and prints "pack-<sha>" to stdout.

# pygit index-pack <path>
#   Regenerates the .idx for the named .pack file.
#   Prints "pack-<sha>" to stdout on success.
```

## Error handling

- Any SHA in the requested set that doesn't exist (loose or packed) raises the existing
  `BadObjectError` — same as `read_object`.
- A `.pack` file passed to `index_pack` with the wrong magic or version raises `InvalidPackError`.
- 64-bit offset entries in a `.pack` passed to `index_pack` raise `InvalidPackError` (consistent
  with the read-path limitation).

## Testing strategy

### Unit tests (no real Git needed)

- `encode_object_header` round-trips: for a range of `(type_id, size)` pairs, encode then
  parse back with `parse_object_header` and assert the values match.
- `write_pack` round-trips: write a small pack from a few loose objects created in a temp repo,
  then read every object back using the existing `read_object_from_packs` and assert type +
  content match.
- `index_pack` regenerates a valid index: write a pack, delete the `.idx`, regenerate with
  `index_pack`, then verify `read_object_from_packs` still works.
- CRC32 correctness: after `write_pack`, parse the resulting `.idx` directly and verify the CRC32
  stored for each entry matches `zlib.crc32` of the corresponding compressed bytes in the pack.
- Fanout correctness: parse the resulting `.idx` and verify `fanout[b]` equals the count of
  objects whose first SHA byte is `<= b` for every `b` in 0..255.
- `pack-objects --stdin` CLI test: invoke via `subprocess`, feed SHAs on stdin, assert the printed
  basename exists as `.pack` + `.idx` in `.git/objects/pack/`.
- `index-pack` CLI test: invoke via `subprocess` with an existing `.pack`, assert `.idx` is
  (re)created and readable.

### Interop tests (skipped if `git` not on PATH)

- **pygit writes, real git reads**: create several objects with `pygit`, call
  `pack_objects(repo, all_shas)`, then run `git verify-pack -v pack-<sha>.idx` inside the repo
  and assert it exits 0 (real Git validates the checksum and every object's CRC).
- **round-trip through index_pack**: delete the `.idx`, call `pygit index-pack <pack>`, run
  `git verify-pack -v` again — still exit 0.
- **real git writes, pygit reads (regression)**: ensure the existing `git gc` interop test still
  passes after the new code is in place (no regression to the read path).

## Documentation

`README.md` updates:
- Add `pack-objects` and `index-pack` to the command-to-internals map table.
- Update the "Known limitations" bullet: pack files are now both readable *and* writable; remove
  the "read, but not written" clause. Update to note delta compression is not yet performed
  (objects stored as plain zlib entries).
