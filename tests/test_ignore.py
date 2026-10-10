from pygit.ignore import is_ignored


def test_is_ignored_filename_anywhere():
    patterns = ["*.log"]
    assert is_ignored("debug.log", patterns) is True
    assert is_ignored("src/debug.log", patterns) is True
    assert is_ignored("src/main.py", patterns) is False


def test_is_ignored_directory_anywhere():
    patterns = ["temp/"]
    assert is_ignored("temp/file.txt", patterns) is True
    assert is_ignored("src/temp/file.txt", patterns) is True


def test_is_ignored_relative_from_root():
    patterns = ["/build"]
    assert is_ignored("build", patterns) is True
    assert is_ignored("build/out.txt", patterns) is True
    assert is_ignored("src/build", patterns) is False
