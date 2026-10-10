import os
import pytest

from pygit.repository import create_repo
from pygit.index import IndexEntry, read_index, write_index, make_entry, InvalidIndexError


def _entry(path, sha="a" * 40, mode=0o100644):
    return IndexEntry(0, 0, 0, 0, 0, 0, mode, 0, 0, 0, sha, path)


def test_write_then_read_round_trips(tmp_path):
    repo = create_repo(tmp_path)
    write_index(repo, [_entry("b.txt", sha="b" * 40), _entry("a.txt", sha="a" * 40)])
    result = read_index(repo)
    assert [e.path for e in result] == ["a.txt", "b.txt"]
    assert result[0].sha == "a" * 40


def test_read_index_missing_file_returns_empty(tmp_path):
    repo = create_repo(tmp_path)
    assert read_index(repo) == []


def test_read_index_detects_corrupt_checksum(tmp_path):
    repo = create_repo(tmp_path)
    write_index(repo, [_entry("a.txt")])
    index_path = os.path.join(repo.gitdir, "index")
    with open(index_path, "r+b") as f:
        f.seek(-1, os.SEEK_END)
        f.write(b"\xff")
    with pytest.raises(InvalidIndexError):
        read_index(repo)


def test_make_entry_from_stat(tmp_path):
    file_path = tmp_path / "file.txt"
    file_path.write_bytes(b"content")
    st = os.stat(file_path)
    entry = make_entry("file.txt", "c" * 40, 0o100644, st)
    assert entry.size == 7
    assert entry.mode == 0o100644
    assert entry.path == "file.txt"


def test_write_index_handles_long_path_name(tmp_path):
    repo = create_repo(tmp_path)
    long_path = "a" * 5000
    write_index(repo, [_entry(long_path)])
    result = read_index(repo)
    assert result[0].path == long_path
