# git (pygit)

A from-scratch reimplementation of Git's internals — object model, plumbing commands, and the commit graph — built to understand how version control actually works under the hood, implemented in pure Python (stdlib only).


## The object model

Every object pygit stores is content-addressed: its name *is* the SHA-1 hash of its own bytes. An object is serialized as `<type> <size>\0<content>`, hashed with SHA-1, zlib-compressed, and written to `.git/objects/<sha[:2]>/<sha[2:]>`. This is exactly what real Git does, which is why a real `git cat-file -p <sha>` can read an object pygit wrote, and vice versa.

- **Blob** — the raw bytes of a file, unmodified.
- **Tree** — a sorted list of `<mode> <name>\0<20-raw-sha-bytes>` entries, one per file/directory in a directory snapshot. Directories are sorted as if their name had a trailing `/`, which is Git's actual (slightly surprising) sort rule.
- **Commit** — a small text format: `tree <sha>`, zero or more `parent <sha>` lines, `author` and `committer` lines (`name <email> <unix-epoch> <±HHMM>`), a blank line, then the message.

## The index

pygit implements Git's real binary index format (version 2, the `DIRC` format) rather than a simplified JSON file. This was a deliberate choice: the design goal was for a real `git` install to be able to read a repo pygit created, and the index is part of that surface (`git status`, `git ls-files`, `git commit` all read it directly). The format: a 12-byte header, then one 62-byte-plus-path entry per staged file (stat metadata, mode, size, SHA-1, flags, NUL-padded path), then a trailing SHA-1 checksum over everything before it.

## Reading packed objects

Real Git periodically compacts loose objects into `.pack` files (with a companion `.idx` file for fast lookup) — `git gc` is the common trigger. pygit reads this format too: `.git/objects/pack/*.idx` is a sorted-by-SHA index (with a 256-entry fanout table for fast lookup) mapping each object's SHA-1 to a byte offset in the matching `.pack` file. A `.pack` file is a sequence of zlib-compressed entries, each either a plain object or a *delta* — instructions to reconstruct the object as a series of "copy N bytes from the base object" / "insert these literal bytes" steps against another object already read (`OFS_DELTA`, referencing a base earlier in the same pack by byte offset) or looked up by SHA (`REF_DELTA`, falling back to loose storage or another pack if that base isn't in this one). `objects.read_object()` tries loose storage first and falls back to searching every pack, so every existing command works unchanged against a repacked repository.

## Wire protocol

pygit implements the Git Smart HTTP transport layer (`pygit/http.py`) as the foundation for
`clone`, `fetch`, and `push`. All Git network traffic uses **pkt-line framing**: each message is a
4-hex-digit length prefix (the total byte count including the prefix itself) followed by the
payload; `0000` is a flush packet marking message boundaries. On top of that:

- **Ref discovery** (`GET /info/refs?service=git-upload-pack` or `git-receive-pack`) — the server advertises its refs and capabilities.
- **`upload-pack`** (`POST /git-upload-pack`) — client sends `want`/`have`/`done` pkt-lines and receives a packfile; used by `fetch` and `clone`.
- **`receive-pack`** (`POST /git-receive-pack`) — client sends ref-update commands plus a packfile; used by `push`.

`clone`, `fetch`, `pull`, and `push` are fully exposed as CLI commands.

## Command-to-internals map

| Command | What it touches |
|---|---|
| `init` | Creates `.git/objects`, `.git/refs/heads`, `.git/refs/tags`, `.git/HEAD` (→ `refs/heads/main`) |
| `hash-object` | Hashes/writes a blob object |
| `cat-file` | Reads and decompresses an object, prints type/size/content |
| `write-tree` | Groups the index by directory, recursively writes tree objects bottom-up |
| `read-tree` | Recursively walks a tree object, writes a matching index |
| `commit-tree` | Writes a commit object from an explicit tree/parents/message |
| `add` | Hashes/writes blobs for given paths, updates the index |
| `status` | Diffs working directory vs index vs `HEAD`'s tree |
| `commit` | `write-tree` + `commit-tree` (parent = current `HEAD`) + moves the current branch ref |
| `log` | Walks first-parent pointers from `HEAD`, printing each commit |
| `branch` | Lists/creates refs under `refs/heads` |
| `checkout` | Resolves a branch/commit, rewrites the working directory and index to match its tree, updates `HEAD` |
| `diff` | Line diff, working dir vs index (default) or index vs `HEAD` (`--cached`) |
| `merge` | Fast-forward only: moves the current branch ref if it's a strict ancestor of the target |
| `pack-objects` | Reads the named object SHAs (from stdin, one per line), writes a `.pack` + `.idx` v2 pair to `.git/objects/pack/` |
| `index-pack` | Parses an existing `.pack` file and regenerates its companion `.idx` v2 |
| `clone` | Creates a new local repository from a remote Smart HTTP URL, downloads all reachable objects, checks out the default branch |
| `fetch` | Downloads new objects from the remote and updates `refs/remotes/<remote>/*` tracking refs |
| `pull` | `fetch` then fast-forwards the current branch if the remote is ahead; refuses diverged histories |
| `push` | Packs local objects and updates the remote branch via Smart HTTP `receive-pack` |

## Known limitations

- Pack files are read and written (`pack-objects`, `index-pack`), but objects are stored as plain zlib entries — delta compression is not yet performed, so packs are larger than those real Git produces. `.pack`/`.idx` files are read fully into memory rather than streamed, so extremely large packs are not handled efficiently.
- Smart HTTP protocol primitives and networking (`clone`, `fetch`, `pull`, `push`) are fully implemented (`http.py`, `remote.py`, `fetch.py`, `clone.py`, `push.py`).
- `merge` only supports fast-forward; there is no three-way content merge, so a real divergent merge will refuse with an error rather than attempt to combine changes.
- No rebase, cherry-pick, stash, submodules, or hooks.
- Object/ref names must be full 40-character SHA-1 hex strings or branch names — no abbreviated SHA resolution.
- Symlinks are stored with Git's `120000` mode if encountered inside a tree, but `add`/`checkout` do not have dedicated symlink handling (they read/write file contents as regular files).
- No `.gitignore` support in `add`/`status`.

## Running the tests

```bash
pip install -e .
pytest tests/ -v
```

Interop tests in `tests/test_interop_realgit.py` and the end-to-end test in `tests/test_cli_e2e.py` skip automatically if a real `git` binary or the installed `pygit` console script isn't available, but they are the strongest evidence of compatibility and should be run whenever possible.

