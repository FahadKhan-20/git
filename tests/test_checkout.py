import pytest
from pygit.cli import main
from pygit.repository import GitRepository, create_repo
from pygit.refs import get_head_branch


def test_cli_checkout_switches_branch_and_updates_files(tmp_path, monkeypatch, capsys):
    create_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "file.txt").write_bytes(b"main content\n")
    main(["add", "file.txt"])
    capsys.readouterr()
    main(["commit", "-m", "main commit"])
    capsys.readouterr()
    main(["branch", "feature"])
    main(["checkout", "feature"])
    (tmp_path / "file.txt").write_bytes(b"feature content\n")
    main(["add", "file.txt"])
    capsys.readouterr()
    main(["commit", "-m", "feature commit"])
    capsys.readouterr()

    main(["checkout", "main"])
    assert (tmp_path / "file.txt").read_bytes() == b"main content\n"
    repo = GitRepository(str(tmp_path), str(tmp_path / ".git"))
    assert get_head_branch(repo) == "main"


def test_cli_checkout_refuses_when_uncommitted_changes(tmp_path, monkeypatch):
    create_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "file.txt").write_bytes(b"v1\n")
    main(["add", "file.txt"])
    main(["commit", "-m", "first"])
    main(["branch", "feature"])
    (tmp_path / "file.txt").write_bytes(b"dirty\n")
    with pytest.raises(SystemExit):
        main(["checkout", "feature"])


def test_cli_checkout_removes_files_not_in_target(tmp_path, monkeypatch, capsys):
    create_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "file.txt").write_bytes(b"v1\n")
    main(["add", "file.txt"])
    capsys.readouterr()
    main(["commit", "-m", "first"])
    capsys.readouterr()
    main(["branch", "feature"])
    main(["checkout", "feature"])
    (tmp_path / "extra.txt").write_bytes(b"extra\n")
    main(["add", "extra.txt"])
    capsys.readouterr()
    main(["commit", "-m", "add extra"])
    capsys.readouterr()

    main(["checkout", "main"])
    assert not (tmp_path / "extra.txt").exists()
