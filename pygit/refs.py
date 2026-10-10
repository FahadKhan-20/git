import os

from pygit.repository import repo_path


def read_ref_raw(repo, ref_name):
    path = repo_path(repo, *ref_name.split("/"))
    if os.path.exists(path):
        with open(path) as f:
            return f.read().strip()
    packed_path = repo_path(repo, "packed-refs")
    if os.path.exists(packed_path):
        with open(packed_path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or line.startswith("^"):
                    continue
                parts = line.split(" ", 1)
                if len(parts) == 2:
                    sha, name = parts
                    if name == ref_name:
                        return sha
    return None


def resolve_ref(repo, ref_name):
    content = read_ref_raw(repo, ref_name)
    if content is None:
        return None
    if content.startswith("ref: "):
        return resolve_ref(repo, content[len("ref: "):])
    return content


def write_ref(repo, ref_name, sha):
    path = repo_path(repo, *ref_name.split("/"))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(sha + "\n")


def get_head_branch(repo):
    content = read_ref_raw(repo, "HEAD")
    if content and content.startswith("ref: refs/heads/"):
        return content[len("ref: refs/heads/"):]
    return None


def set_head_branch(repo, branch_name):
    with open(repo_path(repo, "HEAD"), "w") as f:
        f.write(f"ref: refs/heads/{branch_name}\n")


def set_head_detached(repo, sha):
    with open(repo_path(repo, "HEAD"), "w") as f:
        f.write(sha + "\n")


def list_branches(repo):
    branches = set()
    heads_dir = repo_path(repo, "refs", "heads")
    if os.path.isdir(heads_dir):
        for name in os.listdir(heads_dir):
            branches.add(name)
    packed_path = repo_path(repo, "packed-refs")
    if os.path.exists(packed_path):
        with open(packed_path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or line.startswith("^"):
                    continue
                parts = line.split(" ", 1)
                if len(parts) == 2:
                    _, name = parts
                    if name.startswith("refs/heads/"):
                        branches.add(name[len("refs/heads/"):])
    return sorted(list(branches))


def branch_exists(repo, name):
    return read_ref_raw(repo, f"refs/heads/{name}") is not None


def create_branch(repo, name, sha):
    if branch_exists(repo, name):
        raise ValueError(f"branch '{name}' already exists")
    write_ref(repo, f"refs/heads/{name}", sha)
