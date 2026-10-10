import os

from pygit.index import make_entry, read_index, write_index
from pygit.objects import hash_object, read_object
from pygit.commit import Commit, get_identity, serialize_commit, parse_commit
from pygit.refs import get_head_branch, resolve_ref, set_head_detached, write_ref
from pygit.tree import flatten_tree


def _walk_files(path):
    if os.path.isfile(path):
        return [path]
    files = []
    for root, dirs, names in os.walk(path):
        if ".git" in dirs:
            dirs.remove(".git")
        for name in names:
            files.append(os.path.join(root, name))
    return files


def stage_paths(repo, paths):
    from pygit.ignore import load_ignore_patterns, is_ignored
    patterns = load_ignore_patterns(repo)
    entries = {e.path: e for e in read_index(repo)}
    for path in paths:
        for file_path in _walk_files(path):
            rel_path = os.path.relpath(file_path, repo.worktree).replace(os.sep, "/")
            if rel_path not in entries and is_ignored(rel_path, patterns):
                continue
            with open(file_path, "rb") as f:
                data = f.read()
            sha = hash_object(repo, data, "blob", write=True)
            mode = 0o100755 if os.access(file_path, os.X_OK) else 0o100644
            st = os.stat(file_path)
            entries[rel_path] = make_entry(rel_path, sha, mode, st)
    write_index(repo, list(entries.values()))


def cmd_add(args):
    stage_paths(args.repo, args.paths)


def _list_working_files(repo):
    from pygit.ignore import load_ignore_patterns, is_ignored
    patterns = load_ignore_patterns(repo)
    files = []
    for root, dirs, names in os.walk(repo.worktree):
        if ".git" in dirs:
            dirs.remove(".git")
        for name in names:
            full_path = os.path.join(root, name)
            rel_path = os.path.relpath(full_path, repo.worktree).replace(os.sep, "/")
            if is_ignored(rel_path, patterns):
                continue
            files.append(rel_path)
    return files


def compute_status(repo):
    index_entries = {e.path: e for e in read_index(repo)}
    head_sha = resolve_ref(repo, "HEAD")
    head_tree = {}
    if head_sha is not None:
        _, commit_data = read_object(repo, head_sha)
        head_tree = flatten_tree(repo, parse_commit(commit_data).tree)

    staged_new = [p for p in index_entries if p not in head_tree]
    staged_modified = [p for p, e in index_entries.items() if p in head_tree and head_tree[p].sha != e.sha]
    staged_deleted = [p for p in head_tree if p not in index_entries]

    not_staged_modified = []
    not_staged_deleted = []
    for path, entry in index_entries.items():
        full_path = os.path.join(repo.worktree, path)
        if not os.path.exists(full_path):
            not_staged_deleted.append(path)
            continue
        with open(full_path, "rb") as f:
            data = f.read()
        if hash_object(repo, data, "blob", write=False) != entry.sha:
            not_staged_modified.append(path)

    untracked = sorted(set(_list_working_files(repo)) - set(index_entries.keys()))

    return {
        "staged_new": sorted(staged_new),
        "staged_modified": sorted(staged_modified),
        "staged_deleted": sorted(staged_deleted),
        "not_staged_modified": sorted(not_staged_modified),
        "not_staged_deleted": sorted(not_staged_deleted),
        "untracked": untracked,
    }


def cmd_status(args):
    status = compute_status(args.repo)
    if any([status["staged_new"], status["staged_modified"], status["staged_deleted"]]):
        print("Changes to be committed:")
        for path in status["staged_new"]:
            print(f"\tnew file:   {path}")
        for path in status["staged_modified"]:
            print(f"\tmodified:   {path}")
        for path in status["staged_deleted"]:
            print(f"\tdeleted:    {path}")
    if any([status["not_staged_modified"], status["not_staged_deleted"]]):
        print("Changes not staged for commit:")
        for path in status["not_staged_modified"]:
            print(f"\tmodified:   {path}")
        for path in status["not_staged_deleted"]:
            print(f"\tdeleted:    {path}")
    if status["untracked"]:
        print("Untracked files:")
        for path in status["untracked"]:
            print(f"\t{path}")


def cmd_commit(args):
    from pygit.plumbing import build_tree

    entries = read_index(args.repo)
    if not entries:
        raise SystemExit("nothing to commit (create/copy files and use 'pygit add' to track)")

    tree_sha = build_tree(args.repo, entries)
    parent_sha = resolve_ref(args.repo, "HEAD")
    if parent_sha is not None:
        _, parent_data = read_object(args.repo, parent_sha)
        if parse_commit(parent_data).tree == tree_sha:
            raise SystemExit("nothing to commit, working tree clean")

    identity = get_identity()
    message = args.message if args.message.endswith("\n") else args.message + "\n"
    commit = Commit(
        tree=tree_sha,
        parents=[parent_sha] if parent_sha else [],
        author=identity,
        committer=identity,
        message=message,
    )
    commit_sha = hash_object(args.repo, serialize_commit(commit), "commit", write=True)

    branch = get_head_branch(args.repo)
    if branch is not None:
        write_ref(args.repo, f"refs/heads/{branch}", commit_sha)
    else:
        set_head_detached(args.repo, commit_sha)
    print(commit_sha)


def cmd_log(args):
    sha = resolve_ref(args.repo, "HEAD")
    while sha is not None:
        _, data = read_object(args.repo, sha)
        commit = parse_commit(data)
        print(f"commit {sha}")
        print(f"Author: {commit.author}")
        print()
        for line in commit.message.rstrip("\n").split("\n"):
            print(f"    {line}")
        print()
        sha = commit.parents[0] if commit.parents else None


def pull(repo, remote_name="origin", branch=None):
    from pygit.fetch import fetch_from_remote
    from pygit.refs import get_head_branch, resolve_ref, write_ref

    fetch_from_remote(repo, remote_name)
    current_branch = branch or get_head_branch(repo)
    if not current_branch:
        raise ValueError("HEAD is detached; specify a branch")
    local_sha = resolve_ref(repo, f"refs/heads/{current_branch}")
    remote_sha = resolve_ref(repo, f"refs/remotes/{remote_name}/{current_branch}")
    if not remote_sha:
        raise ValueError(f"no remote-tracking ref for '{remote_name}/{current_branch}'")
    if local_sha == remote_sha:
        return "Already up to date."
    if local_sha is None:
        write_ref(repo, f"refs/heads/{current_branch}", remote_sha)
        return f"Fast-forward to {remote_sha[:8]}"
    ancestor = _find_common_ancestor(repo, local_sha, remote_sha)
    if ancestor == local_sha:
        write_ref(repo, f"refs/heads/{current_branch}", remote_sha)
        return f"Fast-forward to {remote_sha[:8]}"
    raise ValueError(
        "Cannot fast-forward; branches have diverged. "
        "Three-way merge is not yet implemented."
    )


def _find_common_ancestor(repo, sha1, sha2):
    from pygit.objects import read_object as _ro
    from pygit.commit import parse_commit as _pc
    ancestors = set()
    cur = sha1
    while cur:
        ancestors.add(cur)
        try:
            _, data = _ro(repo, cur)
            cur = _pc(data).parents[0] if _pc(data).parents else None
        except Exception:
            break
    cur = sha2
    while cur:
        if cur in ancestors:
            return cur
        try:
            _, data = _ro(repo, cur)
            cur = _pc(data).parents[0] if _pc(data).parents else None
        except Exception:
            break
    return None


def cmd_pull(args):
    remote = getattr(args, "remote", "origin") or "origin"
    branch = getattr(args, "branch", None)
    msg = pull(args.repo, remote, branch)
    print(msg)


def cmd_push(args):
    from pygit.push import push_to_remote
    remote = getattr(args, "remote", "origin") or "origin"
    branch = getattr(args, "branch", None)
    msg = push_to_remote(args.repo, remote, branch, args.force)
    print(msg)


def rm_paths(repo, paths):
    entries = {e.path: e for e in read_index(repo)}
    for path in paths:
        rel_path = os.path.relpath(path, repo.worktree).replace(os.sep, "/")
        matched = []
        for p in entries:
            if p == rel_path or p.startswith(rel_path + "/"):
                matched.append(p)
        if not matched:
            raise ValueError(f"pathspec '{path}' did not match any files")
        for p in matched:
            full_path = os.path.join(repo.worktree, p)
            if os.path.exists(full_path):
                if os.path.isdir(full_path):
                    import shutil
                    shutil.rmtree(full_path, ignore_errors=True)
                else:
                    os.remove(full_path)
            if p in entries:
                del entries[p]
    write_index(repo, list(entries.values()))


def cmd_rm(args):
    rm_paths(args.repo, args.paths)


def clean_untracked(repo, force=False, remove_dirs=False):
    if not force:
        return "clean: dry-run (use -f/--force to clean)"
    status = compute_status(repo)
    cleaned = []
    for path in status["untracked"]:
        full_path = os.path.join(repo.worktree, path)
        if os.path.exists(full_path) and not os.path.isdir(full_path):
            os.remove(full_path)
            cleaned.append(path)
    if remove_dirs:
        for root, dirs, files in os.walk(repo.worktree, topdown=False):
            if ".git" in dirs:
                dirs.remove(".git")
            for d in dirs:
                full_dir = os.path.join(root, d)
                rel_dir = os.path.relpath(full_dir, repo.worktree).replace(os.sep, "/")
                index_entries = read_index(repo)
                is_tracked = any(e.path.startswith(rel_dir + "/") for e in index_entries)
                if not is_tracked and os.path.isdir(full_dir):
                    import shutil
                    shutil.rmtree(full_dir, ignore_errors=True)
                    cleaned.append(rel_dir + "/")
    return "\n".join(f"Removing {p}" for p in sorted(cleaned))


def cmd_clean(args):
    msg = clean_untracked(args.repo, args.force, args.d)
    print(msg)


def show_object(repo, rev_str):
    from pygit.revision import resolve_revision
    sha = resolve_revision(repo, rev_str or "HEAD")
    obj_type, data = read_object(repo, sha)
    if obj_type != "commit":
        print(data.decode(errors="replace"))
        return
    from pygit.commit import parse_commit
    commit = parse_commit(data)
    def _safe_p(text=""):
        try:
            print(text)
        except UnicodeEncodeError:
            print(text.encode("ascii", errors="replace").decode("ascii"))

    _safe_p(f"commit {sha}")
    _safe_p(f"Author: {commit.author}")
    _safe_p()
    for line in commit.message.rstrip("\n").split("\n"):
        _safe_p(f"    {line}")
    _safe_p()
    
    parent_tree = None
    if commit.parents:
        parent_sha = commit.parents[0]
        try:
            _, parent_data = read_object(repo, parent_sha)
            parent_tree = parse_commit(parent_data).tree
        except Exception:
            pass
    from pygit.diff import diff_trees
    diff_trees(repo, parent_tree, commit.tree)


def cmd_show(args):
    show_object(args.repo, args.revision)


def reset_to(repo, rev_str, mode="mixed"):
    from pygit.revision import resolve_revision
    from pygit.refs import get_head_branch, write_ref, set_head_detached
    from pygit.commit import parse_commit
    from pygit.tree import flatten_tree
    
    target_sha = resolve_revision(repo, rev_str or "HEAD")
    obj_type, data = read_object(repo, target_sha)
    if obj_type != "commit":
        raise ValueError(f"object {target_sha} is not a commit")
    commit = parse_commit(data)
    
    branch = get_head_branch(repo)
    if branch:
        write_ref(repo, f"refs/heads/{branch}", target_sha)
    else:
        set_head_detached(repo, target_sha)
        
    if mode == "soft":
        return
        
    target_tree = flatten_tree(repo, commit.tree)
    
    if mode == "mixed" or mode == "hard":
        from pygit.index import IndexEntry, write_index
        index_entries = []
        for path, entry in sorted(target_tree.items()):
            full_path = os.path.join(repo.worktree, path)
            st_ctime = st_mtime = st_size = 0
            if os.path.exists(full_path):
                st = os.stat(full_path)
                st_ctime = int(st.st_ctime)
                st_mtime = int(st.st_mtime)
                st_size = int(st.st_size)
            index_entries.append(
                IndexEntry(
                    st_ctime, 0,
                    st_mtime, 0,
                    0, 0,
                    int(entry.mode, 8), 0, 0,
                    st_size or 8, entry.sha, path
                )
            )
        write_index(repo, index_entries)
        
    if mode == "hard":
        for root, dirs, files in os.walk(repo.worktree):
            if ".git" in dirs:
                dirs.remove(".git")
            for f in files:
                full_path = os.path.join(root, f)
                rel_path = os.path.relpath(full_path, repo.worktree).replace(os.sep, "/")
                if rel_path not in target_tree:
                    os.remove(full_path)
        for path, entry in target_tree.items():
            full_path = os.path.join(repo.worktree, path)
            os.makedirs(os.path.dirname(full_path), exist_ok=True)
            _, content = read_object(repo, entry.sha)
            with open(full_path, "wb") as f:
                f.write(content)


def cmd_reset(args):
    mode = "mixed"
    if args.soft:
        mode = "soft"
    elif args.hard:
        mode = "hard"
    reset_to(args.repo, args.revision, mode)
