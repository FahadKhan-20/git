# pygit pack file reading

## Goal

Teach `pygit` to read objects out of Git's packed storage format (`.pack` + `.idx` files under
`.git/objects/pack/`), not just loose objects under `.git/objects/<sha[:2]>/<sha[2:]>`. This is a
read-only capability: every existing command keeps working unchanged, but now also works against
repositories where objects have been packed (e.g. by a real `git gc` or `git repack`, or —
eventually — by pygit's own future network layer).

This is phase 1 of two toward "packfiles + network protocol": phase 2 (a separate spec, built on
top of this one) is the smart-HTTP protocol for `clone`/`fetch`/`push`, which fundamentally
transfers data as packs and therefore requires this phase to exist first.

## Non-goals

- Writing/creating packs (`pack-objects`), needed only once `push` exists — deferred to the
  network-protocol phase.
- `.idx` version 1 (the legacy format real Git stopped writing years ago).
- Streaming/memory-mapped reads for huge packs — pack files are read fully into memory, which is a
  known scaling limitation consistent with this project's existing non-goals around performance at
  scale (see the original design spec).
- Any new CLI command. This phase only changes what `objects.read_object()` can find; existing
  commands (`cat-file`, `log`, `checkout`, `status`, ...) all go through it already.
- Repacking/garbage collection on the pygit side (no `pygit gc`).

## Architecture

A new module, `pygit/pack.py`, implements the pack index and pack file formats and delta
resolution. `pygit/objects.py`'s `read_object(repo, sha)` is extended: if the sha isn't found
loose, it asks `pack.py` to search every pack under `.git/objects/pack/`.

```
pygit/
  pack.py     # new: idx parsing, pack parsing, delta application, object resolution
  objects.py  # modified: read_object() falls back to pack.read_object_from_packs()
```

## `.idx` version 2 format (read)

Layout, in order:

1. 4-byte magic `\xff\x74\x4f\x63`.
2. 4-byte big-endian version number; must be `2` (anything else raises `InvalidPackError`).
3. A 256-entry fanout table, each entry a 4-byte big-endian integer. `fanout[b]` is the number of
   objects in the pack whose SHA-1's first byte is `<= b`. `fanout[255]` is therefore the total
   object count `N`. This table lets a lookup for a given SHA binary-search only the slice of
   entries starting with that SHA's first byte, instead of scanning all `N`.
4. `N` sorted 20-byte raw SHA-1s (ascending, matching the fanout ordering).
5. `N` 4-byte big-endian CRC32 checksums (of each object's *compressed* bytes in the pack) — parsed
   for completeness but not verified in this phase (no correctness decision depends on them).
6. `N` 4-byte big-endian offsets into the `.pack` file. If the top bit is set, the remaining 31
   bits are instead an index into a trailing table of 8-byte big-endian offsets (Git's mechanism
   for packs bigger than 2GB).
7. Trailer: 20-byte SHA-1 of the corresponding `.pack` file, then a 20-byte SHA-1 checksum of
   everything in the `.idx` file that precedes it.

`pygit` parses this into a plain `dict[sha_hex: str, offset: int]` per index file — the fanout
table is only a parsing/seek aid, not part of the public return value; a Python `dict` lookup is
plenty fast at the object counts this project will ever see.

## `.pack` format (read)

Layout:

1. Header: 4-byte magic `PACK`, 4-byte big-endian version (`2`), 4-byte big-endian object count.
2. That many object entries, back to back, each:
   - A variable-length header. The first byte: bit 7 is a continuation flag, bits 6-4 are the
     object type, bits 3-0 are the low 4 bits of the (undeltified) object size. While the
     continuation flag is set, each following byte contributes its low 7 bits to the size, least
     significant chunk first (so byte 2 contributes bits 4-10, byte 3 bits 11-17, etc.), with its
     own bit 7 as the next continuation flag.
   - Object type values: `1`=commit, `2`=tree, `3`=blob, `4`=tag, `6`=`OFS_DELTA`, `7`=`REF_DELTA`
     (`5` is reserved/unused).
   - If type is `OFS_DELTA`: immediately after the size header, a *different* variable-length
     encoding (Git calls this the "offset encoding") gives a byte count to subtract from this
     entry's own start offset to find the base object, also in this pack: first byte's low 7 bits
     seed the value; for each continuation byte, `value = ((value + 1) << 7) | (byte & 0x7f)`.
   - If type is `REF_DELTA`: immediately after the size header, 20 raw bytes — the base object's
     SHA-1.
   - Then the object's data (a plain zlib stream for base types; a delta stream, see below, for
     `OFS_DELTA`/`REF_DELTA`) follows as raw `zlib`-compressed bytes with no length prefix — the
     end of the stream is discovered by decompressing.

`pygit` reads the whole `.pack` file into a `bytes` buffer up front and walks it with an integer
offset cursor. To decompress an object without a known compressed length: create a
`zlib.decompressobj()`, call `.decompress()` with the remaining buffer from the current offset,
and use `len(remaining) - len(decompressobj.unused_data)` as the number of compressed bytes
consumed, advancing the cursor by that amount.

## Delta format and application

A decompressed delta stream (the payload of an `OFS_DELTA`/`REF_DELTA` entry) is:

1. The base object's size, as a base-128 varint (little-endian chunk order: `value = byte0 & 0x7f`,
   then for each further byte `value |= (byte & 0x7f) << shift; shift += 7`). Parsed for a sanity
   check against the actually-resolved base's length.
2. The result (reconstructed) object's size, same varint encoding. Used as a sanity check against
   the final reconstructed length.
3. A sequence of instructions, each starting with one instruction byte:
   - **Copy** (bit 7 set): the low 7 bits of the instruction byte are a bitmask over up to 7
     following bytes — 4 bytes (bits 0-3) build a little-endian *offset* into the base object, 3
     bytes (bits 4-6) build a little-endian *size*; a bit not set means that byte is omitted and
     treated as `0`. If the decoded size is `0`, Git's format defines it as `0x10000` (65536)
     instead. The instruction means "copy `size` bytes from the base object starting at `offset`".
   - **Insert** (bit 7 clear): the instruction byte's value (1-127) is a literal byte count; that
     many following bytes in the delta stream are appended directly to the output.
   - Instructions are applied in order, appending to an output buffer, until the delta stream is
     exhausted.

`pack.py` exposes this as a pure function, `apply_delta(base: bytes, delta: bytes) -> bytes`, with
no I/O — this is what makes it unit-testable with hand-built byte strings rather than requiring a
real packed repository.

## Object resolution

- `OFS_DELTA` bases are resolved by recursing on the *same pack's* byte buffer at
  `entry_offset - relative_offset` — no SHA lookup needed, since the base's exact byte position is
  already known.
- `REF_DELTA` bases are resolved by first checking the *same pack's* index (sha → offset) since
  that's where a base almost always lives for a pack built by `git repack`/`git gc`; if not found
  there, resolution falls back to `objects.read_object(repo, base_sha)` (loose, then any other
  pack) — the same fallback path real Git uses for "thin" packs, which don't include every base
  they delta against. This fallback is exercised directly by a hand-built test, not left
  theoretical.
- Delta chains (a delta based on another delta) are resolved recursively; a small per-call memo
  dict avoids re-resolving the same offset twice within one top-level lookup. Real packs are
  acyclic by construction, so no cycle guard is needed.
- Once a chain bottoms out at a non-delta object, that object's type is the type reported for
  every object reconstructed along the chain (matches Git's semantics: a delta doesn't have its
  own type, it inherits its ultimate base's).

## Public interface

```python
# pygit/pack.py
class InvalidPackError(Exception): ...

def list_pack_files(repo) -> list[str]: ...              # basenames, e.g. "pack-<sha>"
def read_pack_index(idx_path: str) -> dict[str, int]: ... # sha_hex -> offset
def apply_delta(base: bytes, delta: bytes) -> bytes: ...
def read_object_from_packs(repo, sha: str) -> tuple[str, bytes] | None: ...
```

```python
# pygit/objects.py (modified)
def read_object(repo, sha):
    # existing loose lookup first; on miss, falls back to pack.read_object_from_packs(repo, sha)
    # before raising BadObjectError
    ...
```

## Error handling

- An `.idx` with the wrong magic or a version other than `2` raises `InvalidPackError` immediately
  — no attempt to guess or degrade.
- A sha absent from loose storage and every pack still raises the existing `BadObjectError`,
  unchanged from today's behavior.
- A delta chain whose final reconstructed length doesn't match the header-declared result size
  raises `InvalidPackError` (signals a corrupt pack or a bug in delta application, not something to
  silently paper over).

## Testing strategy

- **Unit tests, hand-built bytes** (no real Git needed to construct the input):
  - Pack object header varint parsing (type + size), across sizes requiring 1, 2, and 3+
    continuation bytes.
  - `OFS_DELTA` offset-varint parsing.
  - `apply_delta`: pure insert, pure copy, mixed copy+insert, and the `size == 0` → `0x10000` copy
    quirk.
  - `.idx` parsing against a small hand-built index (2-3 objects), checking fanout-driven lookup
    returns the right offset for each sha and `None`/absence for a sha not present.
  - A fully hand-built single-object-plus-delta `.pack` byte string containing one base blob and
    one `REF_DELTA` entry whose base is *not* in the pack (stored as a separate loose pygit
    object instead), proving the cross-store fallback path works without depending on real Git's
    packing heuristics ever producing a thin pack locally.
- **Interop tests** (skipped if `git` isn't on `PATH`, same convention as the existing interop
  suite): build a repo with `pygit` across several commits that each slightly modify the same
  file (so Git's own delta compression has a natural incentive to produce `OFS_DELTA` entries),
  run real `git gc`, and confirm:
  - Every object `pygit cat-file -p` could read before `gc` is still readable identically after
    (looping over all previously-known SHAs).
  - `pygit log`/`pygit checkout <branch>` still work correctly post-`gc`, exercising the fallback
    through real commands, not just direct `pack.py` calls.
  - Zero loose objects remain after `git gc` (asserting on `.git/objects/*/` being empty of
    anything but the `pack/` directory) — proof the test is actually exercising the pack path and
    not silently passing via loose fallback.

## Documentation

`README.md` gains a short section describing the pack format (mirroring the existing object-model
section's style) and updates the "Known limitations" list to note pack *writing* still isn't
supported (only reading), and that huge packs are read fully into memory.
