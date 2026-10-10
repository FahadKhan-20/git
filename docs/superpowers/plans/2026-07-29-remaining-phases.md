# remaining phases implementation plan

Spec: `docs/superpowers/specs/2026-07-29-remaining-phases-design.md`

We will implement:
- `pygit/config.py` (Native INI config parser)
- `pygit/ignore.py` (Ignore `.gitignore` matching)
- `pygit/revision.py` (Revision resolution `HEAD~N`, etc.)
- Modifications to `pygit/remote.py`, `pygit/porcelain.py`, `pygit/cli.py`
- Test files `tests/test_config.py`, `tests/test_ignore.py`, `tests/test_revision.py`, `tests/test_porcelain_more.py`

---

## Task 1 — Native config parsing

### Tests (`tests/test_config.py`)

Verify read/write/update of INI files with nested sections like `[remote "origin"]`.

### Implementation (`pygit/config.py`)

Parse config blocks and serialize them back.

---

## Task 2 — Ignore matching

### Tests (`tests/test_ignore.py`)

Verify matching against `.gitignore` files with basic wildcard / folder exclusions.

### Implementation (`pygit/ignore.py`)

Add glob-based directory/file exclusion matching. Use it inside status/add/stage.

---

## Task 3 — Revision syntax resolution

### Tests (`tests/test_revision.py`)

Verify resolution of abbreviated SHAs, `HEAD~3`, `HEAD^`, and tags.

### Implementation (`pygit/revision.py`)

Walk ref and parent graphs to resolve revisions to 40-character SHA-1 strings.

---

## Task 4 — Reset, Show, Rm, Clean commands

### Tests (`tests/test_porcelain_more.py`)

Verify `show`, `rm`, `clean`, and `reset` (--soft/--mixed/--hard).

### Implementation (`pygit/porcelain.py` / `pygit/cli.py`)

Wire up these command handlers.
