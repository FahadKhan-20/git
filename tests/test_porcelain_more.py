import os
import pytest
from pygit.repository import create_repo
from pygit.objects import hash_object
from pygit.index import read_index, write_index, IndexEntry
from pygit.commit import Commit, serialize_commit
from pygit.refs import write_ref, resolve_ref
from pygit.porcelain import rm_paths, clean_untracked, reset_to


@pytest.fixture()
def repo(tmp_path):
    return create_repo(str(tmp_path))


def test_rm_removes_from_index_and_disk(repo):
    file_path = os.path.join(repo.worktree, "f.txt")
    with open(file_path, "w") as f:
        f.write("hello")
    sha = hash_object(repo, b"hello", "blob", write=True)
    write_index(repo, [IndexEntry(0, 0, 0, 0, 0, 0, 0o100644, 0, 0, 5, sha, "f.txt")])
    
    rm_paths(repo, [file_path])
    assert not os.path.exists(file_path)
    assert len(read_index(repo)) == 0


def test_clean_deletes_untracked(repo):
    file_path = os.path.join(repo.worktree, "untracked.txt")
    with open(file_path, "w") as f:
        f.write("untracked")
    
    # Dry-run
    res = clean_untracked(repo, force=False)
    assert "dry-run" in res
    assert os.path.exists(file_path)
    
    # Force clean
    res = clean_untracked(repo, force=True)
    assert "Removing untracked.txt" in res
    assert not os.path.exists(file_path)


def test_reset_soft_mixed_hard(repo):
    identity = "Test <t@t.com> 0 +0000"
    from pygit.tree import TreeEntry, serialize_tree
    
    # Commit 1
    b1 = hash_object(repo, b"v1", "blob", write=True)
    t1 = hash_object(repo, serialize_tree([TreeEntry("100644", "f.txt", b1)]), "tree", write=True)
    c1 = Commit(tree=t1, parents=[], author=identity, committer=identity, message="c1\n")
    sha1 = hash_object(repo, serialize_commit(c1), "commit", write=True)
    
    # Commit 2
    b2 = hash_object(repo, b"v2", "blob", write=True)
    t2 = hash_object(repo, serialize_tree([TreeEntry("100644", "f.txt", b2)]), "tree", write=True)
    c2 = Commit(tree=t2, parents=[sha1], author=identity, committer=identity, message="c2\n")
    sha2 = hash_object(repo, serialize_commit(c2), "commit", write=True)
    
    write_ref(repo, "refs/heads/main", sha2)
    with open(os.path.join(repo.gitdir, "HEAD"), "w") as f:
        f.write("ref: refs/heads/main\n")
        
    # Mixed reset to main~ (commit 1)
    reset_to(repo, "main~", "mixed")
    assert resolve_ref(repo, "refs/heads/main") == sha1
    # Index should match commit 1 (b1)
    entries = read_index(repo)
    assert len(entries) == 1
    assert entries[0].sha == b1
