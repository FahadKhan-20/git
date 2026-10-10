# pygit remaining phases

## Goal

Build the remaining subsystems of Git to make pygit a highly capable Git implementation:

1. **Remotes management (`remote.py`)**: Support `remote add <name> <url>`, `remote remove <name>`, and `remote rename <old> <new>` in `.git/config`.
2. **Ignore & attributes (`ignore.py`)**: Support parsing `.gitignore` and matching files/directories against glob patterns.
3. **Revision syntax & tags (`revision.py`)**: Support resolving revision syntax (e.g. `HEAD~2`, `HEAD^`, ranges, tags).
4. **Additional porcelain commands**: `reset` (soft, mixed, hard), `show`, `rm`, `clean`.
5. **Native Git config reader/writer (`config.py`)**: Native parser for `.gitconfig` and `.git/config` INI format.

---

## 1. Native config (`config.py`)

A custom INI parser that handles Git config syntax (including subsection headers like `[remote "origin"]`).

```python
# pygit/config.py
def read_config(path: str) -> dict: ...
def write_config(path: str, data: dict) -> None: ...
```

## 2. Remotes (`remote.py` modifications)

Use the native config module to support the full `remote` command.

```python
# pygit/remote.py
def add_remote(repo, name, url): ...
def remove_remote(repo, name): ...
```

## 3. Ignore & attributes (`ignore.py`)

```python
# pygit/ignore.py
def load_gitignore(repo) -> list[str]: ...
def is_ignored(path: str, pattern_list: list[str]) -> bool: ...
```

## 4. Revision syntax (`revision.py`)

Parse revision syntax like:
- `HEAD~N` (walk parents N times)
- `HEAD^` (first parent)
- Abbreviated SHA-1 (match unique prefix)
- Tag references under `refs/tags/`

```python
# pygit/revision.py
def resolve_revision(repo, rev: str) -> str: ...
```

## 5. Porcelain commands (`porcelain.py` modifications)

- **`show`**: Print commit details, message, and diff of changes against its first parent.
- **`rm`**: Stage deletions of files and delete them from the working directory.
- **`clean`**: Remove untracked files from the working directory.
- **`reset`**: Mixed (default), soft, or hard reset to target commit.
