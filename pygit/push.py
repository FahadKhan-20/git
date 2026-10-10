import os
import tempfile
from pygit.http import discover_refs_receive, send_pack
from pygit.remote import get_remote_url
from pygit.refs import resolve_ref, write_ref, get_head_branch
from pygit.pack import write_pack
from pygit.objects import read_object


def _has_object(repo, sha):
    try:
        read_object(repo, sha)
        return True
    except Exception:
        return False


def get_reachable_objects(repo, start_shas):
    reachable = set()
    visited = set()
    queue = list(start_shas)
    while queue:
        sha = queue.pop()
        if sha in visited:
            continue
        visited.add(sha)
        try:
            obj_type, data = read_object(repo, sha)
        except Exception:
            continue
        reachable.add(sha)
        if obj_type == "commit":
            from pygit.commit import parse_commit
            commit = parse_commit(data)
            queue.append(commit.tree)
            for p in commit.parents:
                queue.append(p)
        elif obj_type == "tree":
            from pygit.tree import parse_tree
            entries = parse_tree(data)
            for entry in entries:
                queue.append(entry.sha)
    return reachable


def _is_ancestor(repo, ancestor_sha, descendent_sha):
    visited = set()
    queue = [descendent_sha]
    while queue:
        sha = queue.pop()
        if sha == ancestor_sha:
            return True
        if sha in visited:
            continue
        visited.add(sha)
        try:
            obj_type, data = read_object(repo, sha)
        except Exception:
            continue
        if obj_type == "commit":
            from pygit.commit import parse_commit
            commit = parse_commit(data)
            queue.extend(commit.parents)
    return False


def push_to_remote(repo, remote_name="origin", branch=None, force=False):
    url = get_remote_url(repo, remote_name)
    remote_refs, caps = discover_refs_receive(url)
    local_branch = branch or get_head_branch(repo)
    if not local_branch:
        raise ValueError("HEAD is detached; specify a branch to push")
    refname = f"refs/heads/{local_branch}"
    local_sha = resolve_ref(repo, refname)
    if not local_sha:
        raise ValueError(f"local branch '{local_branch}' does not exist")
    remote_sha = remote_refs.get(refname)
    if local_sha == remote_sha:
        return "Everything up-to-date"
    if remote_sha and not force:
        if not _is_ancestor(repo, remote_sha, local_sha):
            raise ValueError(
                f"Rejected: non-fast-forward push for '{local_branch}'. "
                "Use --force to override."
            )
    remote_shas_we_have = {sha for sha in remote_refs.values() if _has_object(repo, sha)}
    remote_reachable = get_reachable_objects(repo, remote_shas_we_have)
    local_reachable = get_reachable_objects(repo, [local_sha])
    shas_to_send = local_reachable - remote_reachable
    if shas_to_send:
        fd_pack, tmp_pack = tempfile.mkstemp(suffix=".pack")
        fd_idx, tmp_idx = tempfile.mkstemp(suffix=".idx")
        os.close(fd_pack)
        os.close(fd_idx)
        try:
            write_pack(repo, list(shas_to_send), tmp_pack, tmp_idx)
            with open(tmp_pack, "rb") as f:
                pack_data = f.read()
        finally:
            if os.path.exists(tmp_pack):
                os.remove(tmp_pack)
            if os.path.exists(tmp_idx):
                os.remove(tmp_idx)
    else:
        import hashlib
        import struct
        empty_body = b"PACK" + struct.pack(">II", 2, 0)
        pack_data = empty_body + hashlib.sha1(empty_body).digest()
    old_sha = remote_sha or ("0" * 40)
    new_sha = local_sha
    ref_updates = [(old_sha, new_sha, refname)]
    status = send_pack(url, ref_updates, pack_data)
    reason = status.get(refname)
    if reason is not None:
        raise ValueError(f"Push rejected by server: {reason}")
    tracking_ref = f"refs/remotes/{remote_name}/{local_branch}"
    write_ref(repo, tracking_ref, local_sha)
    return f"Successfully pushed '{local_branch}' to '{remote_name}'"
