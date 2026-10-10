import pytest
from pygit.repository import create_repo
from pygit.objects import hash_object
from pygit.commit import Commit, serialize_commit
from pygit.refs import write_ref
from pygit.revision import resolve_revision


@pytest.fixture()
def repo(tmp_path):
    return create_repo(str(tmp_path))


def test_resolve_revision_ref_and_prefix(repo):
    identity = "Test <t@t.com> 0 +0000"
    from pygit.tree import TreeEntry, serialize_tree
    blob = hash_object(repo, b"hi", "blob", write=True)
    tree_sha = hash_object(repo, serialize_tree([TreeEntry("100644", "f", blob)]), "tree", write=True)
    
    c = Commit(tree=tree_sha, parents=[], author=identity, committer=identity, message="initial\n")
    sha = hash_object(repo, serialize_commit(c), "commit", write=True)
    write_ref(repo, "refs/heads/main", sha)
    
    assert resolve_revision(repo, "main") == sha
    assert resolve_revision(repo, sha[:6]) == sha


def test_resolve_revision_parents(repo):
    identity = "Test <t@t.com> 0 +0000"
    from pygit.tree import TreeEntry, serialize_tree
    blob = hash_object(repo, b"hi", "blob", write=True)
    tree_sha = hash_object(repo, serialize_tree([TreeEntry("100644", "f", blob)]), "tree", write=True)
    
    c1 = Commit(tree=tree_sha, parents=[], author=identity, committer=identity, message="c1\n")
    sha1 = hash_object(repo, serialize_commit(c1), "commit", write=True)
    
    c2 = Commit(tree=tree_sha, parents=[sha1], author=identity, committer=identity, message="c2\n")
    sha2 = hash_object(repo, serialize_commit(c2), "commit", write=True)
    
    write_ref(repo, "refs/heads/main", sha2)
    
    assert resolve_revision(repo, "main~") == sha1
    assert resolve_revision(repo, "main~1") == sha1
    assert resolve_revision(repo, "main^") == sha1
