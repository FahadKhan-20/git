from pygit.refs import create_branch, get_head_branch, list_branches, resolve_ref


def cmd_branch(args):
    if args.name is None:
        current = get_head_branch(args.repo)
        for name in list_branches(args.repo):
            marker = "* " if name == current else "  "
            print(f"{marker}{name}")
    else:
        head_sha = resolve_ref(args.repo, "HEAD")
        if head_sha is None:
            raise SystemExit("cannot create branch: no commits yet")
        create_branch(args.repo, args.name, head_sha)
