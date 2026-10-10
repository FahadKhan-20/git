from pygit.cli import main
from pygit.repository import create_repo


def test_cli_diff_shows_unstaged_change(tmp_path, monkeypatch, capsys):
    create_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    file_path = tmp_path / "file.txt"
    file_path.write_bytes(b"line1\n")
    main(["add", "file.txt"])
    capsys.readouterr()
    file_path.write_bytes(b"line1 changed\n")
    main(["diff"])
    output = capsys.readouterr().out
    assert "-line1" in output
    assert "+line1 changed" in output


def test_cli_diff_cached_shows_staged_change(tmp_path, monkeypatch, capsys):
    create_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "file.txt").write_bytes(b"line1\n")
    main(["add", "file.txt"])
    capsys.readouterr()
    main(["commit", "-m", "first"])
    capsys.readouterr()
    (tmp_path / "file.txt").write_bytes(b"line2\n")
    main(["add", "file.txt"])
    capsys.readouterr()
    main(["diff", "--cached"])
    output = capsys.readouterr().out
    assert "-line1" in output
    assert "+line2" in output
