import pytest
from pygit.cli import main
from pygit.repository import create_repo
from pygit.refs import resolve_ref


def test_cli_branch_lists_current_branch(tmp_path, monkeypatch, capsys):
    create_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "file.txt").write_bytes(b"v1\n")
    main(["add", "file.txt"])
    capsys.readouterr()
    main(["commit", "-m", "first"])
    capsys.readouterr()
    main(["branch"])
    assert capsys.readouterr().out.strip() == "* main"


def test_cli_branch_creates_new_branch(tmp_path, monkeypatch, capsys):
    repo = create_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "file.txt").write_bytes(b"v1\n")
    main(["add", "file.txt"])
    capsys.readouterr()
    main(["commit", "-m", "first"])
    commit_sha = capsys.readouterr().out.strip()
    main(["branch", "feature"])
    assert resolve_ref(repo, "refs/heads/feature") == commit_sha


def test_cli_branch_fails_with_no_commits(tmp_path, monkeypatch):
    create_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit):
        main(["branch", "feature"])
