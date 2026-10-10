# pygit — a minimal Git implementation in Python

## Goal

Build a functional, dependency-free (stdlib only: `hashlib`, `zlib`, `os`, etc.) reimplementation
of Git's core object model and a useful subset of its plumbing/porcelain commands, called `pygit`.
Objects, refs, and the index must be byte-for-byte compatible with real Git wherever feasible, so
a real `git` install can read a repo created by `pygit` (and vice versa).

## Non-goals

- Networking (`clone`/`fetch`/`push`/`pull`), packfiles, or garbage collection.
- Full merge algorithm (three-way content merge). Only fast-forward merge is in scope.
- Rebasing, cherry-pick, stash, submodules, hooks.
- Full binary-compatibility with every historical index version — target index format version 2 only.

## Project layout

```
pygit/
  __init__.py
  cli.py            # argv dispatch -> plumbing/porcelain
  repository.py     # GitRepository: locates .git, path helpers
  objects.py        # blob/tree/commit read/write, hashing, zlib
  tree.py           # tree entry (de)serialization + sorting
  commit.py         # commit object (de)serialization
  index.py          # binary index (DIRC) read/write
  refs.py           # ref read/write, HEAD resolution
  plumbing.py       # hash-object, cat-file, write-tree, read-tree, commit-tree
  porcelain.py      # add, status, commit, log
  branch.py         # branch create/list
  checkout.py       # checkout
tests/
  test_objects.py
  test_tree.py
  test_index.py
  test_refs.py
  test_plumbing.py
  test_porcelain.py
  test_interop_realgit.py   # shells out to a real `git` binary
  test_cli_e2e.py
README.md
pyproject.toml       # console-script entry point: pygit -> pygit.cli:main
```

## Object model

- **Header**: every object is stored as `b"<type> <size>\0" + content`, where `<type>` is
  `blob`/`tree`/`commit` and `<size>` is `len(content)` in decimal ASCII.
- **Hashing**: SHA-1 over the header+content bytes (Git's historical hash; no SHA-256 mode).
- **Storage**: zlib-compressed header+content written to
  `.git/objects/<sha[:2]>/<sha[2:]>`, directories created on demand.
- **Blob**: raw file bytes, no transformation.
- **Tree**: sequence of entries `<mode-ascii> <name>\0<20-byte-raw-sha>`, concatenated with no
  separators between entries. Modes used: `100644` (file), `100755` (executable), `40000` (dir),
  `120000` (symlink) — symlinks supported opportunistically but not a primary target.
  Entries sorted by name, with directory names treated as if suffixed with `/` for sort purposes
  (Git's actual tree-sort rule), so `pygit`-written trees sort identically to real Git's.
- **Commit**: text format:
  ```
  tree <sha>
  parent <sha>            # zero or more, one per line, omitted for root commit
  author <name> <email> <epoch> <±HHMM>
  committer <name> <email> <epoch> <±HHMM>

  <message>
  ```

## Index format

Real Git binary index, version 2 (`DIRC` header):
- 12-byte header: signature `DIRC`, version (4-byte BE uint32 = 2), entry count (4-byte BE uint32).
- Per entry: ctime sec/nsec, mtime sec/nsec, dev, ino, mode, uid, gid, file size (all 4-byte BE
  uint32; fields with no meaningful value on the host OS are zeroed, matching Git's own behavior
  on filesystems lacking certain stat data), 20-byte object SHA, 2-byte flags (name length +
  assume-valid/stage bits, no extended flags), NUL-terminated path, then NUL padding to the next
  8-byte boundary (Git's padding rule, computed from a fixed base offset per entry).
- Entries sorted by path (byte-wise).
- Trailer: 20-byte SHA-1 checksum over all preceding bytes.
- No extensions (tree cache, etc.) are written or required to be understood; a real Git reading
  a `pygit`-written index just re-derives anything it needs.

## Commands

### Repository setup
- `init [path]` — creates `.git/objects`, `.git/refs/heads`, `.git/refs/tags`, and `.git/HEAD`
  containing `ref: refs/heads/main\n`. Errors if `.git` already exists.

### Plumbing
- `hash-object [-w] [-t <type>] <file>` — hash a file as an object; `-w` also writes it to
  the object store. Prints the SHA.
- `cat-file (-t | -s | -p) <object>` — print type, size, or pretty-printed content.
- `write-tree` — build a tree object from the current index, recursively creating subtree
  objects for directories. Prints the resulting SHA.
- `read-tree <tree-ish>` — populate the index from a tree object (recursively), replacing
  current index content.
- `commit-tree <tree-sha> [-p <parent-sha>]... -m <message>` — create a commit object with
  author/committer identity from `git config user.name`/`user.email` (via subprocess to the
  real `git` binary; falls back to `pygit <pygit@localhost>` if unset) and current
  timestamp/timezone. Prints the resulting commit SHA. Does not move any ref.

### Porcelain
- `add <path>...` — hash each file as a blob (writing it to the object store), then
  insert/update its entry in the index. Supports individual files; directories are walked
  recursively. Does not support `.gitignore` (out of scope).
- `status` — three-way comparison of working directory, index, and `HEAD`'s tree:
  "Changes to be committed" (index vs HEAD), "Changes not staged for commit" (working dir vs
  index), "Untracked files" (working dir files absent from index).
- `commit -m <message>` — `write-tree` from the current index, `commit-tree` with `HEAD` as
  the sole parent (omitted for the first commit), then update the ref that `HEAD` points at to
  the new commit SHA. Fails if the index is empty or matches `HEAD`'s tree exactly (nothing to
  commit).
- `log` — walk parent pointers starting at `HEAD`, printing SHA, author, date, and message for
  each commit, most recent first. Stops at a commit with no parent.

### Branching & refs
- `branch [<name>]` — with no argument, lists branches under `refs/heads` (marking the current
  one); with a name, creates `refs/heads/<name>` pointing at the current `HEAD` commit. Errors
  if the branch already exists.
- `checkout <branch-or-sha>` — resolves the target to a commit, reads its tree, and updates the
  working directory to match (writing/overwriting files present in the target tree, deleting
  tracked files absent from it), rewrites the index to match the target tree, and updates
  `HEAD` (symbolic ref if a branch name was given, detached SHA otherwise). Refuses to proceed
  if doing so would silently discard uncommitted changes (working dir differs from current
  index) — this is a deliberate safety check, not present in the original request list, added
  because destructive-by-default checkout is a common Git footgun.

### Nice-to-haves (implemented if time allows, after the above is solid)
- `diff` — unified-ish line diff between working tree and index, and index vs `HEAD`.
- `merge <branch>` — fast-forward only: if `HEAD` is a strict ancestor of the target, move the
  ref forward and check out the result; otherwise error out explaining that non-fast-forward
  merges aren't supported.

## Error handling

- Commands other than `init` fail with a clear message and non-zero exit if no `.git` directory
  is found (searching upward from cwd, matching Git's behavior).
- `cat-file`/`read-tree`/`commit-tree` on an unknown or malformed SHA fail with a clear message
  rather than a raw traceback.
- `hash-object` on a nonexistent file fails with a clear message.
- `checkout`'s uncommitted-changes safety check (see above).
- No silent fallbacks or swallowed exceptions; internal invariant violations (e.g. a corrupt
  index checksum) raise loudly.

## Testing strategy

- **Unit tests** per module: object header/hash/round-trip, tree entry sort order and
  (de)serialization, index binary round-trip (write then read back byte-identical, and a
  known-good hand-built index parses correctly), ref read/write, commit text format.
- **Interop tests** (skipped automatically if `git` isn't on `PATH`, otherwise required to
  pass): create a repo with `pygit`, then invoke the real `git` binary via `subprocess` to run
  `cat-file -p`, `log`, `status`, `ls-files` against it and assert the output matches
  expectations. Also the reverse direction: `git init` + `git commit` a small repo, then read
  it with `pygit cat-file`/`pygit log` and assert correctness.
- **End-to-end CLI test**: drive the `pygit` CLI through `init` → `hash-object -w` → `add` →
  `commit` → `branch` → `checkout` → `log` against a temp directory, asserting on filesystem
  state and command output at each step.
- Order of implementation, verified incrementally: object storage layer (`hash-object` +
  `cat-file`) first, confirmed round-tripping (including against real `git cat-file`) before any
  higher-level command is built on top of it.

## Documentation

`README.md` covers: the object model (headers, hashing, compression, content addressing) with a
worked example; the index format and why the real binary format was chosen over a simplified
one; a table mapping each `pygit` command to the Git internals it touches; and known
limitations (see Non-goals).
