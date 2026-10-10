from typing import NamedTuple

from pygit.objects import read_object


class TreeEntry(NamedTuple):
    mode: str
    name: str
    sha: str


def sort_entries(entries):
    def key(entry):
        name = entry.name + "/" if entry.mode == "40000" else entry.name
        return name.encode()
    return sorted(entries, key=key)


def serialize_tree(entries):
    out = b""
    for entry in sort_entries(entries):
        out += f"{entry.mode} {entry.name}".encode() + b"\0" + bytes.fromhex(entry.sha)
    return out


def parse_tree(data):
    entries = []
    i = 0
    n = len(data)
    while i < n:
        sp = data.index(b" ", i)
        mode = data[i:sp].decode()
        nul = data.index(b"\0", sp + 1)
        name = data[sp + 1:nul].decode()
        sha = data[nul + 1:nul + 21].hex()
        entries.append(TreeEntry(mode=mode, name=name, sha=sha))
        i = nul + 21
    return entries


def flatten_tree(repo, tree_sha, prefix=""):
    result = {}
    if tree_sha is None:
        return result
    _, data = read_object(repo, tree_sha)
    for entry in parse_tree(data):
        path = f"{prefix}{entry.name}"
        if entry.mode == "40000":
            result.update(flatten_tree(repo, entry.sha, prefix=f"{path}/"))
        else:
            result[path] = entry
    return result
