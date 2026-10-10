from pygit.checkout import apply_tree_to_worktree, has_uncommitted_changes
from pygit.commit import parse_commit
from pygit.objects import read_object
from pygit.refs import branch_exists, get_head_branch, resolve_ref, write_ref


def _is_ancestor(repo, candidate_sha, descendant_sha):
    sha = descendant_sha
    while sha is not None:
        if sha == candidate_sha:
            return True
        _, data = read_object(repo, sha)
        parents = parse_commit(data).parents
        sha = parents[0] if parents else None
    return False


def cmd_merge(args):
    repo = args.repo
    if not branch_exists(repo, args.branch):
        raise SystemExit(f"error: branch '{args.branch}' not found")
    if has_uncommitted_changes(repo):
        raise SystemExit("error: your local changes would be overwritten by merge")

    current_sha = resolve_ref(repo, "HEAD")
    target_sha = resolve_ref(repo, f"refs/heads/{args.branch}")

    if current_sha is not None and not _is_ancestor(repo, current_sha, target_sha):
        raise SystemExit("error: merge is not a fast-forward; only fast-forward merges are supported")

    _, commit_data = read_object(repo, target_sha)
    apply_tree_to_worktree(repo, parse_commit(commit_data).tree)

    branch = get_head_branch(repo)
    write_ref(repo, f"refs/heads/{branch}", target_sha)
    print(f"Fast-forward merge to {target_sha}")
