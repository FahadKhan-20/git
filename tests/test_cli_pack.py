import os
import subprocess
import sys

import pytest

from pygit.objects import hash_object
from pygit.plumbing import pack_objects, index_pack_cmd
from pygit.repository import create_repo


@pytest.fixture()
def repo(tmp_path):
    return create_repo(str(tmp_path))


def _pygit(repo, *args, stdin=None):
    return subprocess.run(
        [sys.executable, "-m", "pygit"] + list(args),
        cwd=repo.worktree,
        capture_output=True,
        text=True,
        input=stdin,
        stdin=None if stdin is not None else subprocess.DEVNULL,
    )


def test_pack_objects_stdin(repo):
    shas = [hash_object(repo, f"cli{i}".encode(), "blob", write=True) for i in range(3)]
    stdin_input = "\n".join(shas) + "\n"
    result = _pygit(repo, "pack-objects", "--stdin", stdin=stdin_input)
    assert result.returncode == 0, result.stderr
    basename = result.stdout.strip()
    assert basename.startswith("pack-")
    pack_dir = os.path.join(repo.worktree, ".git", "objects", "pack")
    assert os.path.exists(os.path.join(pack_dir, basename + ".pack"))
    assert os.path.exists(os.path.join(pack_dir, basename + ".idx"))


def test_pack_objects_stdin_ignores_blank_and_comments(repo):
    sha = hash_object(repo, b"comment test", "blob", write=True)
    stdin_input = f"\n# ignored\n{sha}\n\n"
    result = _pygit(repo, "pack-objects", "--stdin", stdin=stdin_input)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().startswith("pack-")


def test_index_pack_creates_idx(repo):
    shas = [hash_object(repo, b"idx cli", "blob", write=True)]
    basename = pack_objects(repo, shas)
    pack_dir = os.path.join(repo.worktree, ".git", "objects", "pack")
    idx_path = os.path.join(pack_dir, basename + ".idx")
    os.remove(idx_path)
    pack_path = os.path.join(pack_dir, basename + ".pack")
    result = _pygit(repo, "index-pack", pack_path)
    assert result.returncode == 0, result.stderr
    assert os.path.exists(idx_path)
    assert result.stdout.strip().startswith("pack-")
