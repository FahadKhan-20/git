import subprocess
import time
from typing import NamedTuple


class Commit(NamedTuple):
    tree: str
    parents: list
    author: str
    committer: str
    message: str


def parse_commit(data):
    text = data.decode()
    header_text, message = text.split("\n\n", 1)
    tree = None
    parents = []
    author = None
    committer = None
    for line in header_text.split("\n"):
        key, _, value = line.partition(" ")
        if key == "tree":
            tree = value
        elif key == "parent":
            parents.append(value)
        elif key == "author":
            author = value
        elif key == "committer":
            committer = value
    return Commit(tree=tree, parents=parents, author=author, committer=committer, message=message)


def serialize_commit(commit):
    lines = [f"tree {commit.tree}"]
    for parent in commit.parents:
        lines.append(f"parent {parent}")
    lines.append(f"author {commit.author}")
    lines.append(f"committer {commit.committer}")
    return ("\n".join(lines) + "\n\n" + commit.message).encode()


def build_identity(name, email, timestamp, tz_offset_seconds):
    sign = "+" if tz_offset_seconds >= 0 else "-"
    offset = abs(tz_offset_seconds)
    hours = offset // 3600
    minutes = (offset % 3600) // 60
    return f"{name} <{email}> {timestamp} {sign}{hours:02d}{minutes:02d}"


def _git_config(key):
    try:
        result = subprocess.run(["git", "config", key], capture_output=True, text=True, stdin=subprocess.DEVNULL)
    except FileNotFoundError:
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def get_identity():
    name = _git_config("user.name") or "pygit"
    email = _git_config("user.email") or "pygit@localhost"
    timestamp = int(time.time())
    is_dst = time.localtime().tm_isdst > 0
    tz_offset_seconds = -time.altzone if is_dst else -time.timezone
    return build_identity(name, email, timestamp, tz_offset_seconds)
