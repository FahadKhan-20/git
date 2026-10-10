# pygit: path to a full Git implementation

Status snapshot of what `pygit` has vs. what real Git actually is, and how the remaining gaps map
onto buildable sub-projects.

## How this project gets built

Every subsystem in this repo goes through the same cycle, using Claude Code's `superpowers`
skills:

1. **`superpowers:brainstorming`** — scope the sub-project, ask clarifying questions, propose
   approaches, write a design spec to `docs/superpowers/specs/YYYY-MM-DD-<topic>-design.md`,
   commit it.
2. **`superpowers:writing-plans`** — turn the approved spec into a bite-sized TDD implementation
   plan (failing test → minimal code → passing test → commit, per step) at
   `docs/superpowers/plans/YYYY-MM-DD-<topic>.md`.
3. **`superpowers:subagent-driven-development`** (or `executing-plans` inline) — execute the plan
   task by task, with real-`git` interop tests as the compatibility bar, not just internal
   round-trips.

This is why the roadmap below is organized as **sub-projects**, not a flat feature list: each one
is sized to go through that cycle on its own and land as working, tested software before the next
one starts — the same way "pack file reading" was split out and finished ahead of "network
protocol," even though both were originally one bullet ("packfiles + network protocol").

## Done

Already through the full cycle above, with specs in `docs/superpowers/specs/`:

- **Object model** — blob/tree/commit, content-addressed, zlib+SHA-1, byte-compatible with real Git.
- **Binary index** — real `DIRC` v2 format (not a simplified stand-in).
- **Refs** — `HEAD`, `refs/heads/*`, symbolic ref resolution, `packed-refs` fallback.
- **Pack reading** — `.idx` v2 parsing, `.pack` parsing, `OFS_DELTA`/`REF_DELTA` resolution. Reads
  anything a real `git gc`/`git repack` produces.
- **Plumbing** — `hash-object`, `cat-file`, `write-tree`, `read-tree`, `commit-tree`.
- **Porcelain** — `init`, `add`, `status`, `commit`, `log`, `branch`, `checkout`, `diff`
  (working-dir/index/HEAD line diff), `merge` (fast-forward only).

## Remaining sub-projects

Ordered roughly by dependency and priority — each row is a candidate unit for one
brainstorming → spec → plan → build cycle.

| # | Sub-project | Depends on | Contains |
|---|---|---|---|
| 1 | **Pack writing** | Pack reading (done) | `pack-objects`/`index-pack` equivalent: delta selection, pack + idx generation |
| 2 | **Smart HTTP protocol** | Pack writing | pkt-line framing, ref discovery (`info/refs`), `upload-pack`/`receive-pack` negotiation |
| 3 | **`clone` / `fetch` / `pull`** | Smart HTTP protocol | end-to-end read-side networking, shallow/partial clone, protocol v2 |
| 4 | **`push`** | Smart HTTP protocol, Pack writing | write-side networking, ref update reporting |
| 5 | **Remotes** | — | `remote` command, multiple remotes, refspecs (can land before or after 2-4) |
| 6 | **Real merge** | — | three-way diff3 merge, conflict markers, recursive/ort strategy (replaces fast-forward-only) |
| 7 | **History rewriting** | Real merge (for rebase's replay step) | `rebase` (incl. `-i`), `cherry-pick`, `revert`, `bisect`, `reflog` |
| 8 | **Ignore & attributes** | — | `.gitignore`, `.gitattributes`, `.git/info/exclude` |
| 9 | **Stash & partial staging** | — | `stash`, `add -p`/`add -i` |
| 10 | **Tags & revision syntax** | — | annotated tag objects, `refs/tags/*`, `HEAD~2`/`HEAD^`/ranges (`a..b`, `a...b`), abbreviated SHA resolution |
| 11 | **Rename detection & patches** | — | `-M`/`-C` similarity detection in diff, `format-patch`/`apply` |
| 12 | **Repo maintenance** | Pack writing | `gc`/`repack` (writing, not just reading), `fsck`, `commit-graph`, multi-pack-index |
| 13 | **Signing** | — | GPG/SSH commit and tag signing + verification |
| 14 | **Config & hooks** | — | native `.gitconfig` parsing (system/global/local scopes, replacing the current shell-out to real `git config`), hook execution (`pre-commit`, `post-commit`, `pre-push`, ...) |
| 15 | **Worktrees & submodules** | — | `worktree`, submodules |
| 16 | **Performance** | Pack writing | streaming instead of full in-memory reads, delta compression tuning, bitmap indexes |
| 17 | **Remaining porcelain breadth** | varies | `show`, `blame`, `grep`, `archive`, `bundle`, `clean`, `mv`, `rm`, `reset`, `describe`, `notes` |

## Rough sizing

Everything built so far (object model, index, refs+packed-refs, pack reading, core
plumbing/porcelain) is roughly comparable in effort to **sub-projects 1-4 combined** (pack
writing through push) — that's the other half of "packfiles + network protocol," the single
largest remaining architectural block. Sub-projects 6-7 (real merge + history rewriting) are the
second-largest chunk — genuinely new algorithms, not just format support. Everything from 8
onward is breadth: each is independently small, but there are many of them.

## Picking the next sub-project

Say which row to brainstorm next (or ask for a recommendation) and it goes through the same
spec → plan → build cycle as pack reading did.
