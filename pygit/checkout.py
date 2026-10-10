import os

from pygit.commit import parse_commit
from pygit.index import read_index
from pygit.objects import hash_object, read_object
from pygit.plumbing import read_tree_into_index
from pygit.refs import branch_exists, resolve_ref, set_head_branch, set_head_detached
from pygit.tree import flatten_tree


def has_uncommitted_changes(repo):
    for path, entry in {e.path: e for e in read_index(repo)}.items():
        full_path = os.path.join(repo.worktree, path)
        if not os.path.exists(full_path):
            return True
        with open(full_path, "rb") as f:
            data = f.read()
        if hash_object(repo, data, "blob", write=False) != entry.sha:
            return True
    return False


def apply_tree_to_worktree(repo, tree_sha):
    target_files = flatten_tree(repo, tree_sha)
    current_files = {e.path for e in read_index(repo)}
    for path in current_files - set(target_files.keys()):
        full_path = os.path.join(repo.worktree, path)
        if os.path.exists(full_path):
            os.remove(full_path)
    for path, tree_entry in target_files.items():
        full_path = os.path.join(repo.worktree, path)
        dir_path = os.path.dirname(full_path)
        if dir_path:
            os.makedirs(dir_path, exist_ok=True)
        _, content = read_object(repo, tree_entry.sha)
        with open(full_path, "wb") as f:
            f.write(content)
    read_tree_into_index(repo, tree_sha)


def cmd_checkout(args):
    repo = args.repo
    if has_uncommitted_changes(repo):
        raise SystemExit("error: your local changes would be overwritten by checkout")

    target = args.target
    if branch_exists(repo, target):
        commit_sha = resolve_ref(repo, f"refs/heads/{target}")
    else:
        commit_sha = target

    _, commit_data = read_object(repo, commit_sha)
    commit = parse_commit(commit_data)
    apply_tree_to_worktree(repo, commit.tree)

    if branch_exists(repo, target):
        set_head_branch(repo, target)
    else:
        set_head_detached(repo, commit_sha)
