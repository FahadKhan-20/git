from pygit.repository import create_repo
from pygit.porcelain import stage_paths
from pygit.index import read_index


def test_stage_paths_adds_single_file(tmp_path):
    repo = create_repo(tmp_path)
    (tmp_path / "file.txt").write_bytes(b"content\n")
    stage_paths(repo, [str(tmp_path / "file.txt")])
    assert [e.path for e in read_index(repo)] == ["file.txt"]


def test_stage_paths_walks_directory(tmp_path):
    repo = create_repo(tmp_path)
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "a.txt").write_bytes(b"a\n")
    (tmp_path / "sub" / "b.txt").write_bytes(b"b\n")
    stage_paths(repo, [str(tmp_path / "sub")])
    assert sorted(e.path for e in read_index(repo)) == ["sub/a.txt", "sub/b.txt"]


def test_stage_paths_updates_existing_entry(tmp_path):
    repo = create_repo(tmp_path)
    file_path = tmp_path / "file.txt"
    file_path.write_bytes(b"v1\n")
    stage_paths(repo, [str(file_path)])
    first_sha = read_index(repo)[0].sha
    file_path.write_bytes(b"v2\n")
    stage_paths(repo, [str(file_path)])
    entries = read_index(repo)
    assert len(entries) == 1
    assert entries[0].sha != first_sha


def test_compute_status_reports_untracked_and_staged(tmp_path):
    repo = create_repo(tmp_path)
    (tmp_path / "tracked.txt").write_bytes(b"v1\n")
    (tmp_path / "untracked.txt").write_bytes(b"u\n")
    stage_paths(repo, [str(tmp_path / "tracked.txt")])
    from pygit.porcelain import compute_status
    status = compute_status(repo)
    assert status["staged_new"] == ["tracked.txt"]
    assert status["untracked"] == ["untracked.txt"]


def test_compute_status_detects_unstaged_modification(tmp_path):
    repo = create_repo(tmp_path)
    file_path = tmp_path / "tracked.txt"
    file_path.write_bytes(b"v1\n")
    stage_paths(repo, [str(file_path)])
    file_path.write_bytes(b"v2\n")
    from pygit.porcelain import compute_status
    status = compute_status(repo)
    assert status["not_staged_modified"] == ["tracked.txt"]


def test_compute_status_detects_unstaged_deletion(tmp_path):
    repo = create_repo(tmp_path)
    file_path = tmp_path / "tracked.txt"
    file_path.write_bytes(b"v1\n")
    stage_paths(repo, [str(file_path)])
    file_path.unlink()
    from pygit.porcelain import compute_status
    status = compute_status(repo)
    assert status["not_staged_deleted"] == ["tracked.txt"]


def test_cli_commit_creates_commit_and_moves_branch(tmp_path, monkeypatch, capsys):
    import pytest
    from pygit.cli import main
    from pygit.refs import resolve_ref
    from pygit.objects import read_object
    from pygit.commit import parse_commit

    repo = create_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "file.txt").write_bytes(b"content\n")
    main(["add", "file.txt"])
    capsys.readouterr()
    main(["commit", "-m", "Initial commit"])
    sha = capsys.readouterr().out.strip()
    assert resolve_ref(repo, "HEAD") == sha
    _, data = read_object(repo, sha)
    assert b"Initial commit" in data


def test_cli_commit_fails_when_nothing_to_commit(tmp_path, monkeypatch):
    import pytest
    from pygit.cli import main

    create_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit):
        main(["commit", "-m", "empty"])


def test_cli_commit_second_commit_has_parent(tmp_path, monkeypatch, capsys):
    import pytest
    from pygit.cli import main
    from pygit.refs import resolve_ref
    from pygit.objects import read_object
    from pygit.commit import parse_commit

    repo = create_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "file.txt").write_bytes(b"v1\n")
    main(["add", "file.txt"])
    capsys.readouterr()
    main(["commit", "-m", "first"])
    first_sha = capsys.readouterr().out.strip()
    (tmp_path / "file.txt").write_bytes(b"v2\n")
    main(["add", "file.txt"])
    capsys.readouterr()
    main(["commit", "-m", "second"])
    second_sha = capsys.readouterr().out.strip()
    _, data = read_object(repo, second_sha)
    assert parse_commit(data).parents == [first_sha]


def test_cli_log_walks_history(tmp_path, monkeypatch, capsys):
    from pygit.cli import main

    create_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "file.txt").write_bytes(b"v1\n")
    main(["add", "file.txt"])
    capsys.readouterr()
    main(["commit", "-m", "first commit"])
    first_sha = capsys.readouterr().out.strip()
    (tmp_path / "file.txt").write_bytes(b"v2\n")
    main(["add", "file.txt"])
    capsys.readouterr()
    main(["commit", "-m", "second commit"])
    second_sha = capsys.readouterr().out.strip()
    main(["log"])
    output = capsys.readouterr().out
    assert output.index(second_sha) < output.index(first_sha)
    assert "first commit" in output
    assert "second commit" in output


def test_cli_log_on_unborn_branch_prints_nothing(tmp_path, monkeypatch, capsys):
    from pygit.cli import main

    create_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    main(["log"])
    assert capsys.readouterr().out == ""



