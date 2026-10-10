import pytest
from pygit.cli import main
from pygit.repository import create_repo
from pygit.refs import resolve_ref


def test_cli_merge_fast_forwards_current_branch(tmp_path, monkeypatch, capsys):
    repo = create_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "file.txt").write_bytes(b"v1\n")
    main(["add", "file.txt"])
    capsys.readouterr()
    main(["commit", "-m", "first"])
    capsys.readouterr()

    main(["branch", "feature"])
    main(["checkout", "feature"])
    (tmp_path / "file.txt").write_bytes(b"v2\n")
    main(["add", "file.txt"])
    capsys.readouterr()
    main(["commit", "-m", "second"])
    feature_sha = capsys.readouterr().out.strip()

    main(["checkout", "main"])
    main(["merge", "feature"])
    assert resolve_ref(repo, "refs/heads/main") == feature_sha
    assert (tmp_path / "file.txt").read_bytes() == b"v2\n"


def test_cli_merge_refuses_non_fast_forward(tmp_path, monkeypatch, capsys):
    create_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "file.txt").write_bytes(b"v1\n")
    main(["add", "file.txt"])
    capsys.readouterr()
    main(["commit", "-m", "first"])
    capsys.readouterr()

    main(["branch", "feature"])
    (tmp_path / "file.txt").write_bytes(b"main change\n")
    main(["add", "file.txt"])
    capsys.readouterr()
    main(["commit", "-m", "main-only commit"])
    capsys.readouterr()

    main(["checkout", "feature"])
    (tmp_path / "file.txt").write_bytes(b"feature change\n")
    main(["add", "file.txt"])
    capsys.readouterr()
    main(["commit", "-m", "feature-only commit"])
    capsys.readouterr()

    main(["checkout", "main"])
    with pytest.raises(SystemExit):
        main(["merge", "feature"])
