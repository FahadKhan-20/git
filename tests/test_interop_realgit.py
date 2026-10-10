import shutil
import subprocess

import pytest

from pygit.objects import hash_object, read_object
from pygit.repository import GitRepository, create_repo

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="real git not on PATH")


def run_git(cwd, *args):
    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True, stdin=subprocess.DEVNULL)
    return result.stdout


def test_real_git_reads_pygit_blob(tmp_path):
    repo = create_repo(tmp_path)
    sha = hash_object(repo, b"interop content\n", "blob", write=True)
    output = run_git(str(tmp_path), "cat-file", "-p", sha)
    assert output == "interop content\n"


def test_pygit_reads_real_git_blob(tmp_path):
    repo = create_repo(tmp_path)
    (tmp_path / "file.txt").write_bytes(b"from real git\n")
    sha = run_git(str(tmp_path), "hash-object", "-w", "file.txt").strip()
    type_, content = read_object(repo, sha)
    assert type_ == "blob"
    assert content == b"from real git\n"


def test_real_git_reads_pygit_tree(tmp_path):
    repo = create_repo(tmp_path)
    blob_sha = hash_object(repo, b"content\n", "blob", write=True)
    from pygit.tree import TreeEntry, serialize_tree
    tree_data = serialize_tree([TreeEntry(mode="100644", name="file.txt", sha=blob_sha)])
    tree_sha = hash_object(repo, tree_data, "tree", write=True)
    output = run_git(str(tmp_path), "cat-file", "-p", tree_sha)
    assert "file.txt" in output
    assert blob_sha in output


def test_pygit_reads_real_git_tree(tmp_path):
    repo = create_repo(tmp_path)
    (tmp_path / "file.txt").write_bytes(b"content\n")
    run_git(str(tmp_path), "add", "file.txt")
    tree_sha = run_git(str(tmp_path), "write-tree").strip()
    from pygit.tree import parse_tree
    _, data = read_object(repo, tree_sha)
    entries = parse_tree(data)
    assert entries[0].name == "file.txt"


def test_real_git_reads_pygit_commit(tmp_path):
    repo = create_repo(tmp_path)
    blob_sha = hash_object(repo, b"content\n", "blob", write=True)
    from pygit.tree import TreeEntry, serialize_tree
    tree_data = serialize_tree([TreeEntry(mode="100644", name="file.txt", sha=blob_sha)])
    tree_sha = hash_object(repo, tree_data, "tree", write=True)
    identity = "Test User <test@example.com> 1700000000 +0000"
    from pygit.commit import Commit, serialize_commit
    commit = Commit(tree=tree_sha, parents=[], author=identity, committer=identity, message="Initial commit\n")
    commit_sha = hash_object(repo, serialize_commit(commit), "commit", write=True)
    output = run_git(str(tmp_path), "cat-file", "-p", commit_sha)
    assert f"tree {tree_sha}" in output
    assert "Initial commit" in output


def test_real_git_reads_pygit_index(tmp_path):
    run_git(str(tmp_path), "init", "-q")
    repo = GitRepository(str(tmp_path), str(tmp_path / ".git"))
    (tmp_path / "file.txt").write_bytes(b"hello\n")
    sha = hash_object(repo, b"hello\n", "blob", write=True)
    from pygit.index import make_entry, write_index
    write_index(repo, [make_entry("file.txt", sha, 0o100644)])
    output = run_git(str(tmp_path), "ls-files", "--stage")
    assert sha in output
    assert "file.txt" in output


def test_pygit_reads_real_git_index(tmp_path):
    run_git(str(tmp_path), "init", "-q")
    (tmp_path / "file.txt").write_bytes(b"hello\n")
    run_git(str(tmp_path), "add", "file.txt")
    repo = GitRepository(str(tmp_path), str(tmp_path / ".git"))
    from pygit.index import read_index
    entries = read_index(repo)
    assert len(entries) == 1
    assert entries[0].path == "file.txt"


def test_real_git_reads_pygit_write_tree_output(tmp_path):
    run_git(str(tmp_path), "init", "-q")
    repo = GitRepository(str(tmp_path), str(tmp_path / ".git"))
    (tmp_path / "file.txt").write_bytes(b"content\n")
    sha = hash_object(repo, b"content\n", "blob", write=True)
    from pygit.index import IndexEntry, write_index as pygit_write_index
    pygit_write_index(repo, [IndexEntry(0, 0, 0, 0, 0, 0, 0o100644, 0, 0, 8, sha, "file.txt")])
    from pygit.plumbing import build_tree
    from pygit.index import read_index
    tree_sha = build_tree(repo, read_index(repo))
    output = run_git(str(tmp_path), "cat-file", "-p", tree_sha)
    assert "file.txt" in output


def test_pygit_reads_objects_after_real_git_gc(tmp_path, monkeypatch, capsys):
    import os
    from pygit.cli import main
    from pygit.objects import read_object
    create_repo(tmp_path)
    monkeypatch.chdir(tmp_path)

    commit_shas = []
    for content in [b"version 1\n", b"version 2\n", b"version 3 with a bit more text\n"]:
        (tmp_path / "file.txt").write_bytes(content)
        main(["add", "file.txt"])
        capsys.readouterr()
        main(["commit", "-m", f"commit for {content!r}"])
        commit_shas.append(capsys.readouterr().out.strip())

    run_git(str(tmp_path), "gc")

    objects_dir = os.path.join(str(tmp_path), ".git", "objects")
    loose_dirs = [name for name in os.listdir(objects_dir) if name not in ("pack", "info")]
    assert loose_dirs == []

    repo = GitRepository(str(tmp_path), str(tmp_path / ".git"))
    for sha in commit_shas:
        type_, _ = read_object(repo, sha)
        assert type_ == "commit"

    main(["log"])
    log_output = capsys.readouterr().out
    for sha in commit_shas:
        assert sha in log_output

    main(["checkout", commit_shas[0]])
    assert (tmp_path / "file.txt").read_bytes() == b"version 1\n"


def test_git_verify_pack_accepts_pygit_written_pack(tmp_path):
    import os
    from pygit.objects import hash_object
    from pygit.plumbing import pack_objects
    from pygit.repository import create_repo

    repo = create_repo(str(tmp_path))
    run_git(repo.worktree, "init")
    run_git(repo.worktree, "config", "user.email", "t@t.com")
    run_git(repo.worktree, "config", "user.name", "T")

    shas = [hash_object(repo, f"verify{i}".encode(), "blob", write=True) for i in range(5)]
    basename = pack_objects(repo, shas)
    pack_dir = os.path.join(repo.worktree, ".git", "objects", "pack")
    idx_path = os.path.join(pack_dir, basename + ".idx")

    result = subprocess.run(
        ["git", "verify-pack", "-v", idx_path],
        capture_output=True, text=True, stdin=subprocess.DEVNULL
    )
    assert result.returncode == 0, result.stderr


def test_git_verify_pack_after_index_pack_regen(tmp_path):
    import os
    from pygit.objects import hash_object
    from pygit.plumbing import pack_objects, index_pack_cmd
    from pygit.repository import create_repo

    repo = create_repo(str(tmp_path))
    shas = [hash_object(repo, f"regen{i}".encode(), "blob", write=True) for i in range(3)]
    basename = pack_objects(repo, shas)
    pack_dir = os.path.join(repo.worktree, ".git", "objects", "pack")
    idx_path = os.path.join(pack_dir, basename + ".idx")
    pack_path = os.path.join(pack_dir, basename + ".pack")
    os.remove(idx_path)
    index_pack_cmd(repo, pack_path)

    result = subprocess.run(
        ["git", "verify-pack", "-v", idx_path],
        capture_output=True, text=True, stdin=subprocess.DEVNULL
    )
    assert result.returncode == 0, result.stderr






