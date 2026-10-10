# pygit clone / fetch / pull

## Goal

Implement the read-side network commands that bring remote objects into a local repository,
building on top of the `http.py` protocol layer (sub-project 2, done):

- **`pygit clone <url> [<dir>]`** — create a new local repository from a remote URL, downloading
  all reachable objects and checking out the default branch.
- **`pygit fetch [<remote>]`** — download new objects from the remote and update remote-tracking
  refs (`refs/remotes/<remote>/<branch>`).
- **`pygit pull [<remote> [<branch>]]`** — `fetch` then fast-forward the current branch if
  possible (refuses a non-fast-forward merge; three-way merge is sub-project 6).

## Non-goals

- Protocol v2. Protocol v1 Smart HTTP only (matching sub-project 2).
- SSH transport.
- Authentication / credential helpers beyond embedded URL credentials.
- Shallow (`--depth`) or partial clones.
- Submodules.
- `--rebase` pull mode (sub-project 7).
- Multiple remotes per repo (sub-project 5 adds a full `remote` command). For now, a single
  remote named `origin` is hard-coded and its URL stored in `.git/config` as a minimal INI file.

## Architecture

Three new files (all thin orchestrators over the existing layer):

```
pygit/
  remote.py   # new: minimal .git/config read/write, remote URL storage
  fetch.py    # new: fetch_from_remote() — discover refs, download pack, write objects + refs
  clone.py    # new: clone_repo() — create repo, fetch, checkout default branch
```

`cli.py` and `plumbing.py` gain `clone`, `fetch`, and `pull` subcommands.

## `.git/config` (minimal)

pygit reads and writes only the `[remote "origin"]` and `[branch "..."]` sections needed for
fetch/pull. Format is standard Git INI:

```ini
[remote "origin"]
	url = https://github.com/user/repo.git
	fetch = +refs/heads/*:refs/remotes/origin/*
```

Functions in `remote.py`:
```python
def set_remote(repo, name, url): ...          # write [remote "<name>"] url = <url>
def get_remote_url(repo, name) -> str: ...    # read url from [remote "<name>"]
```

## Fetch logic (`fetch.py`)

```python
def fetch_from_remote(repo, remote_name="origin") -> dict[str, str]:
    """
    1. Read remote URL from .git/config.
    2. discover_refs(url) → remote refs + caps.
    3. Compute wants = remote SHAs not already in local repo.
    4. fetch_pack(url, wants) → raw pack bytes.
    5. Write the pack to .git/objects/pack/ via write_pack / index_pack, or
       unpack loose objects if the pack is small (≤ 20 objects).
    6. Update refs/remotes/<remote>/<branch> for each remote branch.
    7. Return {refname: sha} mapping of updated remote-tracking refs.
    """
```

## Clone logic (`clone.py`)

```python
def clone_repo(url, dest_path) -> GitRepository:
    """
    1. Create bare directory structure (create_repo).
    2. set_remote(repo, "origin", url).
    3. fetch_from_remote(repo, "origin").
    4. Determine default branch from refs/remotes/origin/HEAD or first branch.
    5. Create local branch tracking the default remote branch.
    6. Checkout the branch (reuse existing checkout logic).
    7. Return the GitRepository.
    """
```

## Pull logic

`pull` is implemented in `porcelain.py` as:
1. `fetch_from_remote(repo, remote_name)` → get updated remote-tracking refs.
2. Resolve remote-tracking ref for the current branch.
3. If local branch tip is an ancestor of the remote tip → fast-forward (update local ref).
4. If already up to date → print "Already up to date."
5. If diverged → refuse with an error (three-way merge is sub-project 6).

## Storing the pack vs. unpacking

After `fetch_pack` returns raw pack bytes:
- If the pack contains ≤ 20 objects: unpack each object into loose storage using
  `read_object_from_packs` after writing the pack temporarily (or parse the pack directly). This
  keeps the object store simple for small fetches.
- If > 20 objects: write the pack permanently to `.git/objects/pack/` using `write_pack` /
  `index_pack` logic (the pack is already indexed-format-ready since it comes from the server).

In this phase the threshold is fixed at 20. Real Git's `transfer.unpackLimit` is configurable;
that is deferred to sub-project 14 (Config).

## Error handling

- `get_remote_url` raises `ValueError` if no remote named `name` exists.
- `fetch_from_remote` raises `ProtocolError` (from `http.py`) on network/protocol failures.
- `clone_repo` cleans up the partially-created directory on any failure.
- `pull` raises `ValueError` if the current branch has no upstream tracking ref set.

## Public interface

```python
# pygit/remote.py
def set_remote(repo, name: str, url: str) -> None: ...
def get_remote_url(repo, name: str) -> str: ...

# pygit/fetch.py
def fetch_from_remote(repo, remote_name: str = "origin") -> dict[str, str]: ...

# pygit/clone.py
def clone_repo(url: str, dest_path: str) -> GitRepository: ...

# pygit/porcelain.py (additions)
def pull(repo, remote_name: str = "origin", branch: str | None = None) -> str: ...
def cmd_pull(args): ...

# pygit/cli.py (additions)
# pygit clone <url> [<dir>]
# pygit fetch [<remote>]
# pygit pull [<remote> [<branch>]]
```

## Testing strategy

### Unit tests (mocked network)

- `set_remote` / `get_remote_url` round-trip against a temp repo's `.git/config`.
- `fetch_from_remote` with `urllib.request.urlopen` mocked:
  - Mock `discover_refs` response with 2 refs.
  - Mock `fetch_pack` response with a hand-built minimal pack.
  - Assert remote-tracking refs are written correctly.
- `pull` fast-forward: set up local repo with a commit, mock fetch returning a newer commit SHA,
  assert local branch ref is advanced.
- `pull` up-to-date: remote ref equals local ref → returns "Already up to date."
- `pull` diverged: refuses with an error.

### Interop tests (skipped if git not on PATH)

- **`clone` against a local bare repo**: use `git init --bare` + a few `git commit`s in a source
  repo, then `git clone --local` equivalent via pygit's `clone_repo(file_path, dest)` (or HTTP
  using `git http-backend` over a local WSGI server — too complex, use `git upload-pack` directly
  via subprocess for the interop path).

  Actually: the cleanest interop path is to test against a real GitHub/remote URL, but that
  requires network. Instead, spawn a real `git daemon` process for the duration of the test (skip
  if unavailable), run `clone_repo("git://localhost/repo", dest)`, and verify object identity.

  Given the complexity of a local git daemon, these tests will be `pytest.mark.network` and
  skipped by default, enabled via `--run-network-tests`. The primary correctness bar is the
  mocked-HTTP unit tests.

## Documentation

`README.md` updates:
- Add `clone`, `fetch`, `pull` to the command-to-internals table.
- Update "Known limitations" to remove the "no clone/fetch/pull" note.
- Note that `push` is still pending (sub-project 4).
