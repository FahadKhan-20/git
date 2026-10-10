import os
from pygit.cli import main


def test_cli_init_creates_repo_layout(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    main(["init"])
    assert os.path.isdir(os.path.join(str(tmp_path), ".git", "objects"))
    assert os.path.isdir(os.path.join(str(tmp_path), ".git", "refs", "heads"))
    with open(os.path.join(str(tmp_path), ".git", "HEAD")) as f:
        assert f.read() == "ref: refs/heads/main\n"
    assert "Initialized" in capsys.readouterr().out


def test_cli_init_with_explicit_path(tmp_path):
    target = tmp_path / "project"
    target.mkdir()
    main(["init", str(target)])
    assert os.path.isdir(os.path.join(str(target), ".git", "objects"))
