import os
from pygit.config import read_config, write_config


def test_read_write_config_roundtrip(tmp_path):
    path = str(tmp_path / "config")
    config = {
        ("core", None): {"bare": "false", "filemode": "true"},
        ("remote", "origin"): {"url": "http://g.com/r.git", "fetch": "f"},
    }
    write_config(path, config)
    res = read_config(path)
    assert res == config
