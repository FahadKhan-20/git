import difflib
import os

from pygit.commit import parse_commit
from pygit.index import read_index
from pygit.objects import read_object
from pygit.refs import resolve_ref
from pygit.tree import flatten_tree


def _read_blob_lines(repo, sha):
    _, content = read_object(repo, sha)
    return content.decode(errors="replace").splitlines(keepends=True)


def _print_unified(path, old_lines, new_lines):
    diff = difflib.unified_diff(old_lines, new_lines, fromfile=f"a/{path}", tofile=f"b/{path}")
    for line in diff:
        try:
            print(line, end="" if line.endswith("\n") else "\n")
        except UnicodeEncodeError:
            safe_line = line.encode("ascii", errors="replace").decode("ascii")
            print(safe_line, end="" if safe_line.endswith("\n") else "\n")


def _diff_cached(repo, index_entries):
    head_sha = resolve_ref(repo, "HEAD")
    base = {}
    if head_sha is not None:
        _, commit_data = read_object(repo, head_sha)
        base = flatten_tree(repo, parse_commit(commit_data).tree)
    for path in sorted(set(base.keys()) | set(index_entries.keys())):
        old_sha = base[path].sha if path in base else None
        new_sha = index_entries[path].sha if path in index_entries else None
        if old_sha == new_sha:
            continue
        old_lines = _read_blob_lines(repo, old_sha) if old_sha else []
        new_lines = _read_blob_lines(repo, new_sha) if new_sha else []
        _print_unified(path, old_lines, new_lines)


def _diff_working_vs_index(repo, index_entries):
    for path, entry in sorted(index_entries.items()):
        full_path = os.path.join(repo.worktree, path)
        old_lines = _read_blob_lines(repo, entry.sha)
        new_lines = []
        if os.path.exists(full_path):
            with open(full_path, encoding="utf-8", errors="replace") as f:
                new_lines = f.readlines()
        if old_lines != new_lines:
            _print_unified(path, old_lines, new_lines)


def cmd_diff(args):
    index_entries = {e.path: e for e in read_index(args.repo)}
    if args.cached:
        _diff_cached(args.repo, index_entries)
    else:
        _diff_working_vs_index(args.repo, index_entries)


def diff_trees(repo, tree1_sha, tree2_sha):
    base = flatten_tree(repo, tree1_sha) if tree1_sha else {}
    target = flatten_tree(repo, tree2_sha) if tree2_sha else {}
    for path in sorted(set(base.keys()) | set(target.keys())):
        old_sha = base[path].sha if path in base else None
        new_sha = target[path].sha if path in target else None
        if old_sha == new_sha:
            continue
        old_lines = _read_blob_lines(repo, old_sha) if old_sha else []
        new_lines = _read_blob_lines(repo, new_sha) if new_sha else []
        _print_unified(path, old_lines, new_lines)
