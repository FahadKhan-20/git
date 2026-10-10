import pytest
from pygit.repository import create_repo
from pygit.refs import (
    resolve_ref, write_ref, get_head_branch, set_head_branch, set_head_detached,
    list_branches, branch_exists, create_branch, read_ref_raw,
)


def test_resolve_ref_follows_symbolic_head(tmp_path):
    repo = create_repo(tmp_path)
    write_ref(repo, "refs/heads/main", "a" * 40)
    assert resolve_ref(repo, "HEAD") == "a" * 40


def test_resolve_ref_returns_none_for_unborn_branch(tmp_path):
    repo = create_repo(tmp_path)
    assert resolve_ref(repo, "HEAD") is None


def test_get_head_branch_returns_branch_name(tmp_path):
    repo = create_repo(tmp_path)
    assert get_head_branch(repo) == "main"


def test_get_head_branch_returns_none_when_detached(tmp_path):
    repo = create_repo(tmp_path)
    set_head_detached(repo, "b" * 40)
    assert get_head_branch(repo) is None


def test_set_head_branch_updates_head(tmp_path):
    repo = create_repo(tmp_path)
    set_head_branch(repo, "feature")
    assert read_ref_raw(repo, "HEAD") == "ref: refs/heads/feature"


def test_create_and_list_branches(tmp_path):
    repo = create_repo(tmp_path)
    create_branch(repo, "main", "c" * 40)
    create_branch(repo, "feature", "d" * 40)
    assert list_branches(repo) == ["feature", "main"]


def test_create_branch_fails_if_exists(tmp_path):
    repo = create_repo(tmp_path)
    create_branch(repo, "main", "c" * 40)
    with pytest.raises(ValueError):
        create_branch(repo, "main", "d" * 40)


def test_branch_exists(tmp_path):
    repo = create_repo(tmp_path)
    assert branch_exists(repo, "main") is False
    create_branch(repo, "main", "c" * 40)
    assert branch_exists(repo, "main") is True
