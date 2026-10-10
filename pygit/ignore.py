import fnmatch
import os


def load_ignore_patterns(repo):
    path = os.path.join(repo.worktree, ".gitignore")
    patterns = []
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                patterns.append(line)
    return patterns


def is_ignored(rel_path, patterns):
    parts = rel_path.split("/")
    name = parts[-1]
    for pattern in patterns:
        p = pattern.rstrip("/")
        anchored = p.startswith("/")
        p = p.lstrip("/")
        if anchored or "/" in p:
            if fnmatch.fnmatchcase(rel_path, p) or fnmatch.fnmatchcase(rel_path + "/", p + "/"):
                return True
            if any(fnmatch.fnmatchcase("/".join(parts[:i+1]), p) for i in range(len(parts))):
                return True
        else:
            if fnmatch.fnmatchcase(name, p) or any(fnmatch.fnmatchcase(part, p) for part in parts):
                return True
    return False
