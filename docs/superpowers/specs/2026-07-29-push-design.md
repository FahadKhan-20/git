# pygit push

## Goal

Implement the write-side network command that sends local commits to a remote repository,
completing the final part of the "packfiles + network protocol" block:

- **`pygit push [<remote> [<branch>]] [--force]`** — determine the local commits and objects to send,
  build a temporary packfile, transmit it to the remote using `receive-pack`, and update the local
  remote-tracking ref.

## Non-goals

- Protocol v2 support. Smart HTTP protocol v1 is used.
- Interactive password prompting (only embedded URL credentials are supported).
- Pushing tags or multiple refspecs at once.
- Setting upstream (`--set-upstream` or `-u`).

## Architecture

A new module `pygit/push.py` will implement the reachability calculations, ancestor checking,
and orchestration of the push.

```
pygit/
  push.py     # new: get_reachable_objects, push_to_remote
```

`porcelain.py` and `cli.py` will be extended to expose the `push` subcommand.

## Reachability and Object Selection

To determine which local objects (commits, trees, blobs) to pack and send:
1. Query the remote advertised refs using `discover_refs_receive(url)`.
2. Filter the remote refs to find those we have locally: `remote_shas_we_have = {sha for sha in remote_refs.values() if _has_object(repo, sha)}`.
3. Compute `remote_reachable` by traversing commits, trees, and blobs starting from `remote_shas_we_have`.
4. Compute `local_reachable` by traversing from the local branch's SHA.
5. The set of objects to pack is `shas_to_send = local_reachable - remote_reachable`.

This avoids sending objects that the remote already has.

## Fast-forward validation

By default, if the remote branch has a different tip `remote_sha` than our local tracking tip,
pygit must reject the push as non-fast-forward unless:
- `remote_sha` is an ancestor of the local tip.
- The `--force` / `-f` flag is passed.

## Packfile construction

If `shas_to_send` is non-empty:
1. Generate a temporary packfile and idx file in the system temp directory using `write_pack`.
2. Read the packfile bytes.
3. Clean up the temp files.
If `shas_to_send` is empty, send a valid empty packfile (12-byte header + 20-byte SHA checksum).

## CLI registration

- Register `push` in `cli.py`.
- Arguments:
  - `remote`: optional (default: `origin`).
  - `branch`: optional (default: current branch).
  - `--force` / `-f`: optional boolean flag.
