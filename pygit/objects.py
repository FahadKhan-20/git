import hashlib
import os
import zlib

from pygit.repository import repo_path


class BadObjectError(Exception):
    pass


def object_path(repo, sha, mkdir=False):
    dir_path = repo_path(repo, "objects", sha[:2])
    if mkdir:
        os.makedirs(dir_path, exist_ok=True)
    return os.path.join(dir_path, sha[2:])


def hash_object(repo, data, type_, write=False):
    header = f"{type_} {len(data)}\0".encode()
    full = header + data
    sha = hashlib.sha1(full).hexdigest()
    if write:
        path = object_path(repo, sha, mkdir=True)
        if not os.path.exists(path):
            with open(path, "wb") as f:
                f.write(zlib.compress(full))
    return sha


def read_object(repo, sha):
    path = object_path(repo, sha)
    if os.path.exists(path):
        with open(path, "rb") as f:
            full = zlib.decompress(f.read())
        nul_index = full.index(b"\0")
        type_, size_str = full[:nul_index].decode().split(" ")
        content = full[nul_index + 1:]
        if len(content) != int(size_str):
            raise BadObjectError(f"object {sha} has invalid length")
        return type_, content
    from pygit.pack import read_object_from_packs
    result = read_object_from_packs(repo, sha)
    if result is None:
        raise BadObjectError(f"object {sha} not found")
    return result
