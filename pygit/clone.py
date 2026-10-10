import os
import shutil

from pygit.fetch import fetch_from_remote
from pygit.refs import resolve_ref, write_ref
from pygit.remote import set_remote
from pygit.repository import create_repo, GitRepository
from pygit.tree import flatten_tree
from pygit.objects import read_object


def clone_repo(url, dest_path):
    dest = os.path.realpath(dest_path)
    os.makedirs(dest, exist_ok=True)
    try:
        repo = create_repo(dest)
        set_remote(repo, "origin", url)
        updated = fetch_from_remote(repo, "origin")
        default_branch = _detect_default_branch(updated)
        if default_branch:
            remote_ref = f"refs/remotes/origin/{default_branch}"
            sha = resolve_ref(repo, remote_ref)
            if sha:
                write_ref(repo, f"refs/heads/{default_branch}", sha)
                with open(os.path.join(repo.gitdir, "HEAD"), "w") as f:
                    f.write(f"ref: refs/heads/{default_branch}\n")
                _checkout_tree(repo, sha)
        return repo
    except Exception:
        shutil.rmtree(dest, ignore_errors=True)
        raise


def _detect_default_branch(updated):
    for ref in updated:
        if ref.endswith("/main"):
            return "main"
    for ref in updated:
        if ref.endswith("/master"):
            return "master"
    for ref in sorted(updated):
        parts = ref.rsplit("/", 1)
        if len(parts) == 2:
            return parts[1]
    return None


def _checkout_tree(repo, commit_sha):
    from pygit.index import IndexEntry, write_index
    _, commit_data = read_object(repo, commit_sha)
    tree_sha = None
    for line in commit_data.decode(errors="replace").splitlines():
        if line.startswith("tree "):
            tree_sha = line[5:].strip()
            break
    if not tree_sha:
        return
    entries_flat = flatten_tree(repo, tree_sha)
    index_entries = []
    for path, sha, mode in entries_flat:
        full_path = os.path.join(repo.worktree, path)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        _, content = read_object(repo, sha)
        with open(full_path, "wb") as f:
            f.write(content)
        import stat as stat_mod
        st = os.stat(full_path)
        index_entries.append(
            IndexEntry(
                int(st.st_ctime), 0,
                int(st.st_mtime), 0,
                0, 0,
                mode, 0, 0,
                len(content), sha, path,
            )
        )
    write_index(repo, index_entries)
