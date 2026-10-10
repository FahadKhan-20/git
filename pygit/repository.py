import os


class NotAGitRepository(Exception):
    pass


class GitRepository:
    def __init__(self, worktree, gitdir):
        self.worktree = worktree
        self.gitdir = gitdir


def find_repo(start_path="."):
    path = os.path.realpath(start_path)
    while True:
        gitdir = os.path.join(path, ".git")
        if os.path.isdir(gitdir):
            return GitRepository(path, gitdir)
        parent = os.path.dirname(path)
        if parent == path:
            raise NotAGitRepository("not a pygit repository (or any parent up to root)")
        path = parent


def create_repo(path):
    worktree = os.path.realpath(str(path))
    gitdir = os.path.join(worktree, ".git")
    if os.path.exists(gitdir):
        raise FileExistsError(f"{gitdir} already exists")
    os.makedirs(os.path.join(gitdir, "objects"))
    os.makedirs(os.path.join(gitdir, "refs", "heads"))
    os.makedirs(os.path.join(gitdir, "refs", "tags"))
    with open(os.path.join(gitdir, "HEAD"), "w") as f:
        f.write("ref: refs/heads/main\n")
    return GitRepository(worktree, gitdir)


def repo_path(repo, *parts):
    return os.path.join(repo.gitdir, *parts)
