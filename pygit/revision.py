import os
import re
from pygit.repository import repo_path
from pygit.refs import resolve_ref
from pygit.objects import read_object
from pygit.pack import list_pack_files, read_pack_index


def _find_prefix_loose(repo, prefix):
    if len(prefix) < 2:
        return []
    dir_path = repo_path(repo, "objects", prefix[:2])
    if not os.path.isdir(dir_path):
        return []
    suffix = prefix[2:]
    matches = []
    for name in os.listdir(dir_path):
        if name.startswith(suffix) and len(name) == 38:
            matches.append(prefix[:2] + name)
    return matches


def _find_prefix_packed(repo, prefix):
    matches = []
    for basename in list_pack_files(repo):
        idx_path = os.path.join(repo_path(repo, "objects", "pack"), basename + ".idx")
        try:
            mapping = read_pack_index(idx_path)
            for sha in mapping:
                if sha.startswith(prefix):
                    matches.append(sha)
        except Exception:
            continue
    return matches


def find_unique_prefix(repo, prefix):
    matches = list(set(_find_prefix_loose(repo, prefix) + _find_prefix_packed(repo, prefix)))
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise ValueError(f"Ambiguous prefix '{prefix}': matches {matches}")
    return None


def resolve_revision(repo, rev):
    # 1. Parse base and suffixes
    # E.g. HEAD~2^, main~, a1b2c3d
    m = re.match(r"^([a-zA-Z0-9_\-/.]+)(.*)$", rev)
    if not m:
        raise ValueError(f"Invalid revision format: {rev}")
    base = m.group(1)
    suffix = m.group(2)

    # 2. Resolve base
    sha = None
    # Try ref resolution
    for ref_prefix in ["", "refs/", "refs/heads/", "refs/tags/", "refs/remotes/origin/"]:
        possible_ref = ref_prefix + base
        resolved = resolve_ref(repo, possible_ref)
        if resolved:
            sha = resolved
            break

    # Try unique prefix match
    if not sha and re.match(r"^[0-9a-fA-F]{4,40}$", base):
        if len(base) == 40:
            sha = base.lower()
        else:
            sha = find_unique_prefix(repo, base.lower())

    if not sha:
        raise ValueError(f"Revision '{base}' not found")

    # 3. Apply suffixes
    cursor = 0
    while cursor < len(suffix):
        char = suffix[cursor]
        if char == "~":
            cursor += 1
            num_str = ""
            while cursor < len(suffix) and suffix[cursor].isdigit():
                num_str += suffix[cursor]
                cursor += 1
            num = int(num_str) if num_str else 1
            for _ in range(num):
                sha = _get_parent(repo, sha, 1)
        elif char == "^":
            cursor += 1
            num_str = ""
            while cursor < len(suffix) and suffix[cursor].isdigit():
                num_str += suffix[cursor]
                cursor += 1
            num = int(num_str) if num_str else 1
            sha = _get_parent(repo, sha, num)
        else:
            raise ValueError(f"Invalid suffix character '{char}' in revision '{rev}'")

    return sha


def _get_parent(repo, commit_sha, parent_index):
    # parent_index is 1-based (1 for first parent, 2 for second, etc.)
    obj_type, data = read_object(repo, commit_sha)
    if obj_type != "commit":
        raise ValueError(f"Object {commit_sha} is not a commit")
    from pygit.commit import parse_commit
    commit = parse_commit(data)
    if not commit.parents or len(commit.parents) < parent_index:
        raise ValueError(f"Commit {commit_sha} does not have parent index {parent_index}")
    return commit.parents[parent_index - 1]
