import os
import sys

from pygit.objects import hash_object, read_object
from pygit.commit import Commit, get_identity, serialize_commit
from pygit.index import read_index, write_index, IndexEntry
from pygit.repository import repo_path
from pygit.tree import TreeEntry, serialize_tree, flatten_tree


def cmd_hash_object(args):
    with open(args.file, "rb") as f:
        data = f.read()
    sha = hash_object(args.repo, data, args.type, write=args.write)
    print(sha)


def cmd_cat_file(args):
    type_, content = read_object(args.repo, args.object)
    if args.show_type:
        print(type_)
    elif args.show_size:
        print(len(content))
    elif args.pretty:
        sys.stdout.buffer.write(content)


def cmd_commit_tree(args):
    identity = get_identity()
    message = args.message if args.message.endswith("\n") else args.message + "\n"
    commit = Commit(
        tree=args.tree,
        parents=args.parent or [],
        author=identity,
        committer=identity,
        message=message,
    )
    sha = hash_object(args.repo, serialize_commit(commit), "commit", write=True)
    print(sha)


def _insert(tree_dict, parts, entry):
    if len(parts) == 1:
        tree_dict[parts[0]] = entry
    else:
        subdir = tree_dict.setdefault(parts[0], {})
        _insert(subdir, parts[1:], entry)


def _write_tree_dict(repo, tree_dict):
    tree_entries = []
    for name, value in tree_dict.items():
        if isinstance(value, dict):
            sha = _write_tree_dict(repo, value)
            tree_entries.append(TreeEntry(mode="40000", name=name, sha=sha))
        else:
            mode = "100755" if value.mode & 0o111 else "100644"
            tree_entries.append(TreeEntry(mode=mode, name=name, sha=value.sha))
    return hash_object(repo, serialize_tree(tree_entries), "tree", write=True)


def build_tree(repo, entries):
    tree_dict = {}
    for entry in entries:
        _insert(tree_dict, entry.path.split("/"), entry)
    return _write_tree_dict(repo, tree_dict)


def cmd_write_tree(args):
    print(build_tree(args.repo, read_index(args.repo)))


def read_tree_into_index(repo, tree_sha):
    flat = flatten_tree(repo, tree_sha)
    entries = []
    for path, tree_entry in flat.items():
        _, content = read_object(repo, tree_entry.sha)
        mode = int(tree_entry.mode, 8)
        entries.append(IndexEntry(0, 0, 0, 0, 0, 0, mode, 0, 0, len(content), tree_entry.sha, path))
    write_index(repo, entries)
    return entries


def cmd_read_tree(args):
    read_tree_into_index(args.repo, args.tree)


def pack_objects(repo, shas):
    from pygit.pack import write_pack
    import shutil
    pack_dir = repo_path(repo, "objects", "pack")
    os.makedirs(pack_dir, exist_ok=True)
    tmp_pack = os.path.join(pack_dir, "_tmp.pack")
    tmp_idx  = os.path.join(pack_dir, "_tmp.idx")
    pack_sha = write_pack(repo, list(shas), tmp_pack, tmp_idx)
    basename = f"pack-{pack_sha}"
    shutil.move(tmp_pack, os.path.join(pack_dir, basename + ".pack"))
    shutil.move(tmp_idx,  os.path.join(pack_dir, basename + ".idx"))
    return basename


def index_pack_cmd(repo, pack_path):
    from pygit.pack import index_pack
    idx_path = pack_path[:-len(".pack")] + ".idx"
    index_pack(pack_path, idx_path)


def cmd_pack_objects(args):
    shas = [line.strip() for line in sys.stdin if line.strip() and not line.strip().startswith("#")]
    print(pack_objects(args.repo, shas))


def cmd_index_pack(args):
    from pygit.pack import index_pack
    pack_path = args.pack_path
    idx_path = pack_path[:-len(".pack")] + ".idx"
    index_pack(pack_path, idx_path)
    import os as _os
    basename = "pack-" + _os.path.basename(pack_path)[:-len(".pack")].split("pack-", 1)[-1]
    print(f"pack-{basename}" if not basename.startswith("pack-") else basename)


def cmd_clone(args):
    from pygit.clone import clone_repo
    dest = args.directory or args.url.rstrip("/").rsplit("/", 1)[-1].removesuffix(".git")
    clone_repo(args.url, dest)
    print(f"Cloned into '{dest}'")


def cmd_fetch(args):
    from pygit.fetch import fetch_from_remote
    remote = getattr(args, "remote", None) or "origin"
    updated = fetch_from_remote(args.repo, remote)
    for ref, sha in updated.items():
        print(f"  {sha[:8]}  {ref}")
