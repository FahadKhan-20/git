import struct
import hashlib
from unittest.mock import patch, MagicMock
import pytest

from pygit.repository import create_repo
from pygit.objects import hash_object
from pygit.commit import Commit, serialize_commit
from pygit.push import get_reachable_objects, _is_ancestor, push_to_remote
from pygit.remote import set_remote
from pygit.refs import write_ref, resolve_ref


@pytest.fixture()
def repo(tmp_path):
    return create_repo(str(tmp_path))


def test_get_reachable_objects_empty(repo):
    assert get_reachable_objects(repo, []) == set()


def test_get_reachable_objects_blob(repo):
    sha = hash_object(repo, b"hello", "blob", write=True)
    assert get_reachable_objects(repo, [sha]) == {sha}


def test_is_ancestor(repo):
    identity = "Test <t@t.com> 0 +0000"
    blob = hash_object(repo, b"data", "blob", write=True)
    from pygit.tree import TreeEntry, serialize_tree
    tree_sha = hash_object(repo, serialize_tree([TreeEntry("100644", "f", blob)]), "tree", write=True)
    
    c1 = Commit(tree=tree_sha, parents=[], author=identity, committer=identity, message="c1\n")
    sha1 = hash_object(repo, serialize_commit(c1), "commit", write=True)
    
    c2 = Commit(tree=tree_sha, parents=[sha1], author=identity, committer=identity, message="c2\n")
    sha2 = hash_object(repo, serialize_commit(c2), "commit", write=True)
    
    assert _is_ancestor(repo, sha1, sha2) is True
    assert _is_ancestor(repo, sha2, sha1) is False


def test_push_already_up_to_date(repo):
    set_remote(repo, "origin", "https://example.com/r.git")
    sha = hash_object(repo, b"commit", "blob", write=True)
    write_ref(repo, "refs/heads/main", sha)
    with patch("pygit.push.discover_refs_receive", return_value=({"refs/heads/main": sha}, set())):
        res = push_to_remote(repo, "origin", "main")
    assert res == "Everything up-to-date"


def test_push_success(repo):
    set_remote(repo, "origin", "https://example.com/r.git")
    identity = "Test <t@t.com> 0 +0000"
    blob = hash_object(repo, b"data", "blob", write=True)
    from pygit.tree import TreeEntry, serialize_tree
    tree_sha = hash_object(repo, serialize_tree([TreeEntry("100644", "f", blob)]), "tree", write=True)
    c = Commit(tree=tree_sha, parents=[], author=identity, committer=identity, message="c\n")
    sha = hash_object(repo, serialize_commit(c), "commit", write=True)
    write_ref(repo, "refs/heads/main", sha)
    
    with patch("pygit.push.discover_refs_receive", return_value=({}, set())), \
         patch("pygit.push.send_pack", return_value={"refs/heads/main": None}):
        res = push_to_remote(repo, "origin", "main")
    assert "Successfully pushed" in res
    assert resolve_ref(repo, "refs/remotes/origin/main") == sha

