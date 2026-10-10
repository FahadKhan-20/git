import os
import pytest
from pygit.repository import create_repo, find_repo, NotAGitRepository


def test_create_repo_creates_expected_layout(tmp_path):
    repo = create_repo(tmp_path)
    assert os.path.isdir(os.path.join(repo.gitdir, "objects"))
    assert os.path.isdir(os.path.join(repo.gitdir, "refs", "heads"))
    assert os.path.isdir(os.path.join(repo.gitdir, "refs", "tags"))
    with open(os.path.join(repo.gitdir, "HEAD")) as f:
        assert f.read() == "ref: refs/heads/main\n"


def test_create_repo_fails_if_already_exists(tmp_path):
    create_repo(tmp_path)
    with pytest.raises(FileExistsError):
        create_repo(tmp_path)


def test_find_repo_locates_from_subdirectory(tmp_path):
    create_repo(tmp_path)
    subdir = tmp_path / "a" / "b"
    subdir.mkdir(parents=True)
    repo = find_repo(str(subdir))
    assert os.path.realpath(repo.worktree) == os.path.realpath(str(tmp_path))


def test_find_repo_raises_when_not_in_a_repo(tmp_path, monkeypatch):
    monkeypatch.setattr(os.path, "isdir", lambda path: False)
    with pytest.raises(NotAGitRepository):
        find_repo(str(tmp_path))
