from pygit.repository import repo_path
from pygit.config import read_config, write_config


def _config_path(repo):
    return repo_path(repo, "config")


def set_remote(repo, name, url):
    path = _config_path(repo)
    config = read_config(path)
    config[("remote", name)] = {
        "url": url,
        "fetch": f"+refs/heads/*:refs/remotes/{name}/*",
    }
    write_config(path, config)


def get_remote_url(repo, name):
    path = _config_path(repo)
    config = read_config(path)
    section = ("remote", name)
    if section in config and "url" in config[section]:
        return config[section]["url"]
    raise ValueError(f"no remote named '{name}'")
