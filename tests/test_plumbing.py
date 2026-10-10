from pygit.cli import main
from pygit.repository import create_repo


def test_hash_object_writes_and_prints_sha(tmp_path, monkeypatch, capsys):
    create_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "file.txt").write_bytes(b"hello world\n")
    main(["hash-object", "-w", "file.txt"])
    assert capsys.readouterr().out.strip() == "3b18e512dba79e4c8300dd08aeb37f8e728b8dad"


def test_cat_file_pretty_prints_content(tmp_path, monkeypatch, capsys):
    create_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "file.txt").write_bytes(b"hello world\n")
    main(["hash-object", "-w", "file.txt"])
    sha = capsys.readouterr().out.strip()
    main(["cat-file", "-p", sha])
    assert capsys.readouterr().out == "hello world\n"


def test_cat_file_type_and_size(tmp_path, monkeypatch, capsys):
    create_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "file.txt").write_bytes(b"hello world\n")
    main(["hash-object", "-w", "file.txt"])
    sha = capsys.readouterr().out.strip()
    main(["cat-file", "-t", sha])
    assert capsys.readouterr().out.strip() == "blob"
    main(["cat-file", "-s", sha])
    assert capsys.readouterr().out.strip() == "12"


def test_commit_tree_creates_commit_with_no_parent(tmp_path, monkeypatch, capsys):
    from pygit.repository import create_repo
    from pygit.objects import hash_object, read_object
    from pygit.tree import TreeEntry, serialize_tree
    from pygit.commit import parse_commit

    repo = create_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    blob_sha = hash_object(repo, b"content\n", "blob", write=True)
    tree_data = serialize_tree([TreeEntry(mode="100644", name="file.txt", sha=blob_sha)])
    tree_sha = hash_object(repo, tree_data, "tree", write=True)

    main(["commit-tree", tree_sha, "-m", "Initial commit"])
    sha = capsys.readouterr().out.strip()
    _, data = read_object(repo, sha)
    commit = parse_commit(data)
    assert commit.tree == tree_sha
    assert commit.parents == []
    assert commit.message == "Initial commit\n"


def test_commit_tree_records_parent(tmp_path, monkeypatch, capsys):
    from pygit.repository import create_repo
    from pygit.objects import hash_object, read_object
    from pygit.tree import TreeEntry, serialize_tree
    from pygit.commit import parse_commit

    repo = create_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    blob_sha = hash_object(repo, b"content\n", "blob", write=True)
    tree_data = serialize_tree([TreeEntry(mode="100644", name="file.txt", sha=blob_sha)])
    tree_sha = hash_object(repo, tree_data, "tree", write=True)

    main(["commit-tree", tree_sha, "-m", "first"])
    first_sha = capsys.readouterr().out.strip()
    main(["commit-tree", tree_sha, "-p", first_sha, "-m", "second"])
    second_sha = capsys.readouterr().out.strip()
    _, data = read_object(repo, second_sha)
    assert parse_commit(data).parents == [first_sha]


def test_build_tree_creates_nested_trees(tmp_path):
    from pygit.repository import create_repo
    from pygit.objects import hash_object, read_object
    from pygit.plumbing import build_tree
    from pygit.index import IndexEntry
    from pygit.tree import parse_tree

    repo = create_repo(tmp_path)
    blob_sha = hash_object(repo, b"content\n", "blob", write=True)
    entries = [
        IndexEntry(0, 0, 0, 0, 0, 0, 0o100644, 0, 0, 8, blob_sha, "dir/file.txt"),
        IndexEntry(0, 0, 0, 0, 0, 0, 0o100644, 0, 0, 8, blob_sha, "top.txt"),
    ]
    tree_sha = build_tree(repo, entries)
    _, data = read_object(repo, tree_sha)
    top_entries = {e.name: e for e in parse_tree(data)}
    assert top_entries["top.txt"].sha == blob_sha
    assert top_entries["dir"].mode == "40000"
    _, subdata = read_object(repo, top_entries["dir"].sha)
    sub_entries = {e.name: e for e in parse_tree(subdata)}
    assert sub_entries["file.txt"].sha == blob_sha


def test_cli_write_tree_prints_sha(tmp_path, monkeypatch, capsys):
    from pygit.repository import create_repo
    from pygit.objects import hash_object, read_object
    from pygit.index import IndexEntry, write_index

    repo = create_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    blob_sha = hash_object(repo, b"content\n", "blob", write=True)
    write_index(repo, [IndexEntry(0, 0, 0, 0, 0, 0, 0o100644, 0, 0, 8, blob_sha, "file.txt")])
    main(["write-tree"])
    sha = capsys.readouterr().out.strip()
    type_, _ = read_object(repo, sha)
    assert type_ == "tree"


def test_read_tree_into_index_populates_index(tmp_path):
    from pygit.repository import create_repo
    from pygit.objects import hash_object
    from pygit.plumbing import read_tree_into_index
    from pygit.index import read_index
    from pygit.tree import TreeEntry, serialize_tree

    repo = create_repo(tmp_path)
    blob_sha = hash_object(repo, b"content\n", "blob", write=True)
    tree_data = serialize_tree([TreeEntry(mode="100644", name="file.txt", sha=blob_sha)])
    tree_sha = hash_object(repo, tree_data, "tree", write=True)
    read_tree_into_index(repo, tree_sha)
    entries = read_index(repo)
    assert len(entries) == 1
    assert entries[0].path == "file.txt"
    assert entries[0].sha == blob_sha


def test_cli_read_tree_populates_index(tmp_path, monkeypatch, capsys):
    from pygit.repository import create_repo
    from pygit.objects import hash_object
    from pygit.index import read_index
    from pygit.tree import TreeEntry, serialize_tree

    repo = create_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    blob_sha = hash_object(repo, b"content\n", "blob", write=True)
    tree_data = serialize_tree([TreeEntry(mode="100644", name="file.txt", sha=blob_sha)])
    tree_sha = hash_object(repo, tree_data, "tree", write=True)
    main(["read-tree", tree_sha])
    entries = read_index(repo)
    assert entries[0].path == "file.txt"




def test_pack_objects_creates_pack_and_idx(tmp_path):
    import os
    from pygit.plumbing import pack_objects
    from pygit.objects import hash_object
    repo = create_repo(str(tmp_path))
    shas = [hash_object(repo, f"po{i}".encode(), "blob", write=True) for i in range(3)]
    basename = pack_objects(repo, shas)
    pack_dir = os.path.join(repo.worktree, ".git", "objects", "pack")
    assert os.path.exists(os.path.join(pack_dir, basename + ".pack"))
    assert os.path.exists(os.path.join(pack_dir, basename + ".idx"))


def test_pack_objects_basename_starts_with_pack(tmp_path):
    from pygit.plumbing import pack_objects
    from pygit.objects import hash_object
    repo = create_repo(str(tmp_path))
    sha = hash_object(repo, b"basename check", "blob", write=True)
    basename = pack_objects(repo, [sha])
    assert basename.startswith("pack-")


def test_index_pack_cmd_recreates_idx(tmp_path):
    import os
    from pygit.plumbing import pack_objects, index_pack_cmd
    from pygit.objects import hash_object
    repo = create_repo(str(tmp_path))
    sha = hash_object(repo, b"idx cmd", "blob", write=True)
    basename = pack_objects(repo, [sha])
    pack_dir = os.path.join(repo.worktree, ".git", "objects", "pack")
    idx_path = os.path.join(pack_dir, basename + ".idx")
    os.remove(idx_path)
    index_pack_cmd(repo, os.path.join(pack_dir, basename + ".pack"))
    assert os.path.exists(idx_path)
