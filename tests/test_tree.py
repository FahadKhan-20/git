from pygit.repository import create_repo
from pygit.objects import hash_object
from pygit.tree import TreeEntry, parse_tree, serialize_tree, sort_entries, flatten_tree


def test_sort_entries_treats_directories_as_slash_suffixed():
    entries = [
        TreeEntry(mode="100644", name="foo.txt", sha="a" * 40),
        TreeEntry(mode="40000", name="foo", sha="b" * 40),
        TreeEntry(mode="100644", name="bar.txt", sha="c" * 40),
    ]
    result = sort_entries(entries)
    assert [e.name for e in result] == ["bar.txt", "foo.txt", "foo"]


def test_tree_round_trips():
    entries = [
        TreeEntry(mode="100644", name="a.txt", sha="1" * 40),
        TreeEntry(mode="40000", name="dir", sha="2" * 40),
        TreeEntry(mode="100755", name="run.sh", sha="3" * 40),
    ]
    data = serialize_tree(entries)
    assert parse_tree(data) == sort_entries(entries)


def test_flatten_tree_recurses_subdirectories(tmp_path):
    repo = create_repo(tmp_path)
    blob_sha = hash_object(repo, b"content\n", "blob", write=True)
    inner = serialize_tree([TreeEntry(mode="100644", name="file.txt", sha=blob_sha)])
    inner_sha = hash_object(repo, inner, "tree", write=True)
    outer = serialize_tree([
        TreeEntry(mode="40000", name="dir", sha=inner_sha),
        TreeEntry(mode="100644", name="top.txt", sha=blob_sha),
    ])
    outer_sha = hash_object(repo, outer, "tree", write=True)
    flat = flatten_tree(repo, outer_sha)
    assert set(flat.keys()) == {"dir/file.txt", "top.txt"}
    assert flat["dir/file.txt"].sha == blob_sha


def test_flatten_tree_of_none_is_empty(tmp_path):
    repo = create_repo(tmp_path)
    assert flatten_tree(repo, None) == {}
