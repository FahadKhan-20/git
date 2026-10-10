import argparse

from pygit import plumbing
from pygit import porcelain
from pygit import branch
from pygit import checkout
from pygit import diff
from pygit import merge
from pygit.repository import create_repo, find_repo


def cmd_init(args):
    path = args.path or "."
    create_repo(path)
    print(f"Initialized empty pygit repository in {path}")


def build_parser():
    parser = argparse.ArgumentParser(prog="pygit")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init")
    init_parser.add_argument("path", nargs="?")
    init_parser.set_defaults(func=cmd_init)

    hash_object_parser = subparsers.add_parser("hash-object")
    hash_object_parser.add_argument("file")
    hash_object_parser.add_argument("-w", dest="write", action="store_true")
    hash_object_parser.add_argument("-t", dest="type", default="blob")
    hash_object_parser.set_defaults(func=plumbing.cmd_hash_object)

    cat_file_parser = subparsers.add_parser("cat-file")
    cat_file_group = cat_file_parser.add_mutually_exclusive_group(required=True)
    cat_file_group.add_argument("-t", dest="show_type", action="store_true")
    cat_file_group.add_argument("-s", dest="show_size", action="store_true")
    cat_file_group.add_argument("-p", dest="pretty", action="store_true")
    cat_file_parser.add_argument("object")
    cat_file_parser.set_defaults(func=plumbing.cmd_cat_file)

    commit_tree_parser = subparsers.add_parser("commit-tree")
    commit_tree_parser.add_argument("tree")
    commit_tree_parser.add_argument("-p", dest="parent", action="append")
    commit_tree_parser.add_argument("-m", dest="message", required=True)
    commit_tree_parser.set_defaults(func=plumbing.cmd_commit_tree)

    write_tree_parser = subparsers.add_parser("write-tree")
    write_tree_parser.set_defaults(func=plumbing.cmd_write_tree)

    read_tree_parser = subparsers.add_parser("read-tree")
    read_tree_parser.add_argument("tree")
    read_tree_parser.set_defaults(func=plumbing.cmd_read_tree)

    add_parser = subparsers.add_parser("add")
    add_parser.add_argument("paths", nargs="+")
    add_parser.set_defaults(func=porcelain.cmd_add)

    status_parser = subparsers.add_parser("status")
    status_parser.set_defaults(func=porcelain.cmd_status)

    commit_parser = subparsers.add_parser("commit")
    commit_parser.add_argument("-m", dest="message", required=True)
    commit_parser.set_defaults(func=porcelain.cmd_commit)

    log_parser = subparsers.add_parser("log")
    log_parser.set_defaults(func=porcelain.cmd_log)

    branch_parser = subparsers.add_parser("branch")
    branch_parser.add_argument("name", nargs="?")
    branch_parser.set_defaults(func=branch.cmd_branch)

    checkout_parser = subparsers.add_parser("checkout")
    checkout_parser.add_argument("target")
    checkout_parser.set_defaults(func=checkout.cmd_checkout)

    diff_parser = subparsers.add_parser("diff")
    diff_parser.add_argument("--cached", action="store_true")
    diff_parser.set_defaults(func=diff.cmd_diff)

    merge_parser = subparsers.add_parser("merge")
    merge_parser.add_argument("branch")
    merge_parser.set_defaults(func=merge.cmd_merge)

    pack_objects_parser = subparsers.add_parser("pack-objects")
    pack_objects_parser.add_argument("--stdin", action="store_true", required=True)
    pack_objects_parser.set_defaults(func=plumbing.cmd_pack_objects)

    index_pack_parser = subparsers.add_parser("index-pack")
    index_pack_parser.add_argument("pack_path")
    index_pack_parser.set_defaults(func=plumbing.cmd_index_pack)

    clone_parser = subparsers.add_parser("clone")
    clone_parser.add_argument("url")
    clone_parser.add_argument("directory", nargs="?", default=None)
    clone_parser.set_defaults(func=plumbing.cmd_clone, skip_repo=True)

    fetch_parser = subparsers.add_parser("fetch")
    fetch_parser.add_argument("remote", nargs="?", default="origin")
    fetch_parser.set_defaults(func=plumbing.cmd_fetch)

    pull_parser = subparsers.add_parser("pull")
    pull_parser.add_argument("remote", nargs="?", default="origin")
    pull_parser.add_argument("branch", nargs="?", default=None)
    pull_parser.set_defaults(func=porcelain.cmd_pull)

    push_parser = subparsers.add_parser("push")
    push_parser.add_argument("remote", nargs="?", default="origin")
    push_parser.add_argument("branch", nargs="?", default=None)
    push_parser.add_argument("-f", "--force", action="store_true")
    push_parser.set_defaults(func=porcelain.cmd_push)

    rm_parser = subparsers.add_parser("rm")
    rm_parser.add_argument("paths", nargs="+")
    rm_parser.set_defaults(func=porcelain.cmd_rm)

    clean_parser = subparsers.add_parser("clean")
    clean_parser.add_argument("-f", "--force", action="store_true")
    clean_parser.add_argument("-d", action="store_true")
    clean_parser.set_defaults(func=porcelain.cmd_clean)

    show_parser = subparsers.add_parser("show")
    show_parser.add_argument("revision", nargs="?", default=None)
    show_parser.set_defaults(func=porcelain.cmd_show)

    reset_parser = subparsers.add_parser("reset")
    reset_parser.add_argument("revision", nargs="?", default=None)
    group = reset_parser.add_mutually_exclusive_group()
    group.add_argument("--soft", action="store_true")
    group.add_argument("--hard", action="store_true")
    reset_parser.set_defaults(func=porcelain.cmd_reset)

    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    skip_repo = getattr(args, "skip_repo", False)
    if args.command != "init" and not skip_repo:
        args.repo = find_repo()
    args.func(args)


if __name__ == "__main__":
    main()

